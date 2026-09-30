import json
from pathlib import Path
import pytest
from rs.storage import Project, Error, read_doc, write_doc, section, replace_section, deletion_preview, delete_thread
from rs.cli import main

@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv('RS_DISABLE_WORKER', '1')
    return Project.initialize(tmp_path / 'research')


def create(project, title='Question'):
    with project.lock():
        result = project.create_thread(title)
        project.select(result['id'])
    return result


def test_root_and_stable_ids(project):
    item = create(project)
    nested = project.root / 'papers/files'
    assert Project.discover(nested).root == project.root
    with project.lock():
        project.set_status(item['id'], 'closed')
        assert read_doc(project.root / 'project_overview.md')[0]['active_thread'] == ''
        assert project.create_thread('Question')['id'] == '002'
        project.set_status(item['id'], 'open')
        project.select(item['id'])
    assert project.threads()[0]['status'] == 'active'
    assert project.threads()[1]['status'] == 'paused'
    with project.lock():
        project.set_status(item['id'], 'obsolete')
    assert len(project.threads()) == 1
    assert len(project.threads(True)) == 2
    with pytest.raises(Error): project.select(item['id'])


def test_status_bounded_and_no_corpus_reads(project, monkeypatch):
    item = create(project)
    path = project.root / item['path']
    meta, body = read_doc(path)
    write_doc(path, meta, body + 'RECORD_SENTINEL' * 10000)
    overview_path = project.root / 'project_overview.md'
    overview, body = read_doc(overview_path)
    write_doc(overview_path, overview, body + 'DIRECTORY_SENTINEL' * 10000)
    (project.root / 'papers/broken.md').write_text('---\nkey: invalid: yaml\n---\nSOURCE_SENTINEL')
    result = project.status()
    rendered = json.dumps(result)
    assert 'RECORD_SENTINEL' not in rendered and 'DIRECTORY_SENTINEL' not in rendered and 'SOURCE_SENTINEL' not in rendered
    meta, body = read_doc(path)
    write_doc(path, meta, replace_section(body, 'resume', 'x' * 6000))
    resume = project.status()['thread']['resume']
    assert resume['excerpt'] and len(resume['text']) <= 5000 and 'BOUNDED EXCERPT' in resume['text']


def test_todo_order_promotion_and_keywords(project):
    create(project)
    with project.lock():
        first = project.add_todo('First motivation')
        second = project.add_todo('Second')
    path = project.root / 'TODO.md'
    lines = path.read_text().splitlines()
    items = [line for line in lines if line.startswith('- [ ]')]
    path.write_text('# Deferred\n\n' + '\n'.join(reversed(items)) + '\n')
    assert project.todos()[0]['id'] == second['id']
    assert project.todos()[0]['origin'].startswith('threads/001_')
    with project.lock():
        promoted = project.promote(second['id'])
        assert project.status()['active_thread'] == promoted['id']
        assert len(project.todos()) == 1
        project.keywords(' ALGORITHM,algorithm, evaluation ')
    assert project.keywords()['tags'] == ['algorithm', 'evaluation']
    with pytest.raises(Error, match='unknown keywords'): project.keywords('missing')
    assert 'missing' not in project.vocabulary()
    with project.lock():
        project.remove_todo(first['id'])
        assert project.add_todo('New')['id'] == '003'


def test_deletion_preview_cleanup_and_stale(project, monkeypatch):
    item = create(project)
    target = project.root / item['path']
    paper = project.root / 'paper.md'
    paper.write_text(f'# Paper\nIndependent claim supported by [reasoning]({item["path"]}).\nAmbiguous: {target.name}\n')
    with project.lock():
        project.add_todo('Keep topic')
        preview = deletion_preview(project, item['id'])
    assert preview['references']
    paper.write_text(paper.read_text() + 'New text\n')
    with pytest.raises(Error, match='stale'): delete_thread(project, item['id'], preview['token'])
    monkeypatch.setattr('rs.indexing.invalidate', lambda *args: (_ for _ in ()).throw(RuntimeError('offline')))
    with project.lock():
        preview = deletion_preview(project, item['id'])
        result = delete_thread(project, item['id'], preview['token'])
        assert project.create_thread('Replacement')['id'] == '002'
    assert 'pending' in result['indexing'] and result['unresolved']
    assert not target.exists()
    assert 'Independent claim supported by reasoning.' in paper.read_text()
    assert project.todos()[0]['text'].startswith('Keep topic')
    assert read_doc(project.root / 'project_overview.md')[0]['active_thread'] == ''
    assert not (project.root / '.rs/transaction.json').exists()


def test_recovery_rolls_forward(project, monkeypatch):
    a, b = project.root / 'a.md', project.root / 'b.md'
    import rs.storage as storage
    original = storage.atomic_write
    def fail(path, text):
        if Path(path) == b: raise OSError('injected')
        return original(path, text)
    monkeypatch.setattr(storage, 'atomic_write', fail)
    with pytest.raises(OSError): project.transaction({a: 'A', b: 'B'})
    assert (project.root / '.rs/transaction.json').exists()
    monkeypatch.setattr(storage, 'atomic_write', original)
    with project.lock(): pass
    assert a.read_text() == 'A' and b.read_text() == 'B'
    assert not (project.root / '.rs/transaction.json').exists()


@pytest.mark.parametrize('header', ['id: 001', 'id: !!python/object:danger {}', 'tags: wrong', 'status: active'])
def test_yaml_errors_preserve_files(project, header):
    path = project.root / 'bad.md'
    content = f'---\n{header}\n---\nKeep'
    path.write_text(content)
    with pytest.raises(Error): read_doc(path)
    assert path.read_text() == content


def test_cli_json_and_exit_codes(project, capsys, monkeypatch):
    monkeypatch.chdir(project.root)
    assert main(['thread', 'create', 'Hello', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['id'] == '001'
    assert main(['thread', 'select', '001']) == 0
    capsys.readouterr()
    assert main(['status', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['active_thread'] == '001'
    assert main(['keywords', 'nope', '--json']) == 2
    assert 'unknown' in json.loads(capsys.readouterr().err)['error']


def test_promotion_preserves_origin_in_new_thread(project):
    create(project)
    with project.lock():
        todo = project.add_todo('Evaluate on bigger data')
        promoted = project.promote(todo['id'])
    text = (project.root / promoted['path']).read_text()
    assert 'Evaluate on bigger data' in text.split('## Research record')[1]
    assert 'threads/001_' in text.split('## Research record')[1]
