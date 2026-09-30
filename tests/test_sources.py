import json
from pathlib import Path

import pytest

from rs.storage import Project, read_doc, write_doc
from rs import sources


@pytest.fixture
def project(tmp_path):
    return Project.initialize(tmp_path)


def test_doi_fixture_duplicate_and_quoted_key(project, monkeypatch):
    payload = {'message': {'title': ['A & B'], 'author': [{'given': 'Ada', 'family': 'Lovelace'}], 'issued': {'date-parts': [[2024]]}}}
    calls = []
    def fetch(url):
        calls.append(url)
        return json.dumps(payload).encode()
    monkeypatch.setattr(sources, 'fetch', fetch)
    first = sources.register(project, '10.1234/example')[0]
    second = sources.register(project, 'https://doi.org/10.1234/example')[0]
    assert first['key'] == second['key'] == 'x0001'
    assert second['duplicate']
    note = project.root / first['path']
    assert read_doc(note)[0]['key'] == 'x0001' and note.name.startswith('x0001_')
    assert '@article{x0001,' in (project.root / 'refs.bib').read_text()
    assert r'A \& B' in (project.root / 'refs.bib').read_text()


def test_required_failure_no_commits(project, monkeypatch):
    monkeypatch.setattr(sources, 'fetch', lambda _: (_ for _ in ()).throw(ValueError('offline')))
    with pytest.raises(ValueError, match='offline'):
        sources.register(project, '10.1234/failure')
    assert sources.list_sources(project) == []
    row = sources.register(project, 'https://example.com', type='web')[0]
    assert row['key'] == 's0001'
    assert row['missing_fields'] == ['title', 'authors', 'year']


def test_arxiv_and_github_fixtures(project, monkeypatch):
    atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Paper title</title><author><name>A. Author</name></author><published>2025-01-01</published></entry></feed>'
    monkeypatch.setattr(sources, 'fetch', lambda url: atom if 'arxiv' in url else json.dumps({'name': 'repo', 'owner': {'login': 'org'}, 'html_url': 'https://github.com/org/repo'}).encode())
    first = sources.register(project, 'https://arxiv.org/pdf/2501.12345v2.pdf')[0]
    assert sources.register(project, 'arxiv:2501.12345')[0]['key'] == first['key']
    repo = sources.register(project, 'https://github.com/org/repo', type='repo')[0]
    assert read_doc(project.root / repo['path'])[0]['organization'] == 'org'
    assert '@software{' in (project.root / 'refs.bib').read_text()
    assert not list((project.root / 'papers' / 'files').glob('*'))


def test_pdf_copy_duplicate_and_missing_fields(project, tmp_path):
    original = tmp_path / 'input.pdf'
    original.write_bytes(b'%PDF-1.4\nfixture')
    first = sources.register(project, str(original))[0]
    meta, body = read_doc(project.root / first['path'])
    assert meta['missing_fields'] == ['title', 'authors', 'year']
    copied = (project.root / first['path']).parent / meta['local_file']
    assert copied.read_bytes() == original.read_bytes()
    assert copied.resolve() != original.resolve()
    assert sources.register(project, str(original))[0]['duplicate']
    assert 'Metadata incomplete' in body


def test_multi_bib_import_validates_first(project, tmp_path):
    path = tmp_path / 'references.bib'
    path.write_text('@article{old, title={Nested {term} and comma, inside}, author="One and Two", year=2024}\n@misc{other,title="Second",url={https://example.org}}')
    rows = sources.register(project, str(path))
    assert [r['key'] for r in rows] == ['x0001', 'x0002']
    assert len(sources.list_sources(project)) == 2
    assert all(r['duplicate'] for r in sources.register(project, str(path)))
    path.write_text('@misc{good,title={Good}}\n@misc{bad,title={unclosed}')
    with pytest.raises(ValueError): sources.register(project, str(path))
    assert len(sources.list_sources(project)) == 2


def test_titles_do_not_change_keys_and_allocations_do_not_recycle(project):
    first = sources.register(project, 'https://example.org/a', type='web', title='Same')[0]
    second = sources.register(project, 'https://example.org/b', type='web', title='Same')[0]
    assert first['path'] != second['path']
    path = project.root / first['path']
    metadata, body = read_doc(path)
    metadata['title'] = 'Improved'
    write_doc(path, metadata, body)
    sources.bibliography(project)
    assert read_doc(path)[0]['key'] == 's0001'
    path.unlink()
    assert sources.register(project, 'https://example.org/c', type='web')[0]['key'] == 's0003'


def test_validation_citations_links_and_fences(project):
    row = sources.register(project, 'https://example.org', type='web')[0]
    manuscript = project.root / 'paper.md'
    manuscript.write_text(r'Known \cite{0001}, missing \cite{1234}.' + '\n```latex\n' + r'\cite{9999}' + '\n```\n[Missing](threads/missing.md)\n')
    errors = sources.validate(project)
    assert any('1234' in err for err in errors)
    assert not any('9999' in err for err in errors)
    assert any('missing.md' in err for err in errors)
    note = project.root / row['path']
    metadata, body = read_doc(note)
    metadata['tags'] = ['unknown']
    write_doc(note, metadata, body)
    assert any('unknown keyword unknown' in err for err in sources.validate(project))


def test_bibliography_sorts_numerically_and_escapes(project):
    for key, title in [('s10000', 'Later'), ('s9999', r'Earlier $ # _ { } \\')]:
        write_doc(project.root / 'sources' / f'{key}.md', {'key': key, 'type': 'web', 'title': title, 'tags': []}, '')
    bib = sources.bibliography(project)
    assert bib.index('{s9999,') < bib.index('{s10000,')
    assert r'\$' in bib and r'\#' in bib and r'\_' in bib


def test_nested_note_links_and_resume_validation(project):
    thread = project.create_thread('Evidence')
    row = sources.register(project, 'https://example.org', type='web', title='Evidence source')[0]
    path = project.root / row['path']
    meta, body = read_doc(path)
    thread_path = project.thread(thread['id'])[0]
    write_doc(path, meta, body + f'\n[Evidence](../threads/{thread_path.name})\n[Broken](../threads/missing.md)\n')
    errors = sources.validate(project)
    assert any('missing.md' in err for err in errors)
    assert not any(thread_path.name in err for err in errors)
    thread_meta, thread_body = read_doc(thread_path)
    write_doc(thread_path, thread_meta, thread_body.replace('### Next step', '### Other'))
    assert any('missing resume field Next step' in err for err in sources.validate(project))


def test_registration_transaction_recovers_complete_bib_import(project, tmp_path, monkeypatch):
    from rs import storage
    bib = tmp_path / 'refs-import.bib'
    bib.write_text('@misc{one,title={One}}\n@misc{two,title={Two}}')
    original = storage.atomic_write
    failed = False
    def fail_once(path, text):
        nonlocal failed
        if Path(path).parent.name == 'papers' and not failed:
            failed = True
            raise OSError('injected interruption')
        return original(path, text)
    monkeypatch.setattr(storage, 'atomic_write', fail_once)
    with pytest.raises(OSError, match='injected interruption'):
        sources.register(project, str(bib))
    assert (project.root / '.rs' / 'transaction.json').exists()
    with project.lock(): pass
    assert not (project.root / '.rs' / 'transaction.json').exists()
    assert [row['key'] for row in sources.list_sources(project)] == ['x0001', 'x0002']
    assert '@misc{x0002,' in (project.root / 'refs.bib').read_text()


def test_known_doi_duplicate_succeeds_offline(project, monkeypatch):
    monkeypatch.setattr(sources, 'fetch', lambda _: b'{"message":{"title":["Known"]}}')
    first = sources.register(project, '10.1234/known')[0]
    monkeypatch.setattr(sources, 'fetch', lambda _: (_ for _ in ()).throw(ValueError('offline')))
    assert sources.register(project, 'doi:10.1234/known')[0]['key'] == first['key']


def test_inline_code_citation_examples_are_ignored(project):
    (project.root / 'paper.md').write_text('Write citations as `\\cite{0042}` in text.\n')
    assert not [e for e in sources.validate(project) if '0042' in e]


def test_bibtex_protective_braces_removed(project, tmp_path):
    bib = tmp_path / 'x.bib'
    bib.write_text('@article{a,title={A {Nice} Paper},author={Doe, Jane},year={2020}}\n')
    row = sources.register(project, str(bib))[0]
    assert read_doc(project.root / row['path'])[0]['title'] == 'A Nice Paper'


def _three_papers(project, tmp_path):
    bib = tmp_path / 'three.bib'
    bib.write_text('@misc{a,title={Alpha Paper},year=2020}\n@misc{b,title={Beta Paper},year=2021}\n@misc{c,title={Gamma Paper},year=2022}\n')
    return [r['key'] for r in sources.register(project, str(bib))]


def test_discussion_order_numbering_and_idempotence(project, tmp_path):
    assert _three_papers(project, tmp_path) == ['x0001', 'x0002', 'x0003']
    first = sources.discuss(project, 'x3')
    assert first['key'] == '0001' and first['previous'] == 'x0003'
    assert (project.root / 'papers/0001_gamma_paper.md').exists()
    assert not list((project.root / 'papers').glob('x0003_*'))
    assert sources.discuss(project, '1')['key'] == '0001' and sources.discuss(project, '0001')['duplicate']
    assert sources.discuss(project, 'x0001')['key'] == '0002'
    assert [r['key'] for r in sources.list_sources(project)] == ['0001', '0002', 'x0002']
    bib = (project.root / 'refs.bib').read_text()
    assert '{0001,' in bib and 'x0003' not in bib and bib.index('{0002,') < bib.index('{x0002,')


def test_discuss_rewrites_references_outside_code_only(project, tmp_path):
    _three_papers(project, tmp_path)
    (project.root / 'paper.md').write_text('See \\cite{x0002, x0001}.\n`\\cite{x0002}`\n```\n\\cite{x0002}\n```\n[note](papers/x0002_beta_paper.md)\n')
    sources.discuss(project, 'x0002')
    text = (project.root / 'paper.md').read_text()
    assert text.startswith('See \\cite{0001,x0001}.')
    assert text.count('\\cite{x0002}') == 2 and 'papers/0001_beta_paper.md' in text
    assert not [e for e in sources.validate(project) if 'x0002' not in e and 'citation' in e]


def test_discuss_failure_leaves_old_state(project, tmp_path, monkeypatch):
    from rs import storage
    _three_papers(project, tmp_path)
    original = storage.atomic_write
    def boom(path, text):
        if Path(path).name == 'refs.bib': raise OSError('injected')
        return original(path, text)
    monkeypatch.setattr(storage, 'atomic_write', boom)
    with pytest.raises(OSError): sources.discuss(project, 'x0001')
    monkeypatch.setattr(storage, 'atomic_write', original)
    with project.lock(): pass
    assert [r['key'] for r in sources.list_sources(project)] == ['0001', 'x0002', 'x0003']


def test_lookup_unknown_and_non_paper(project, tmp_path):
    _three_papers(project, tmp_path)
    web = sources.register(project, 'https://example.org/x', type='web')[0]['key']
    assert web == 's0001'
    with pytest.raises(ValueError, match='not a paper'): sources.discuss(project, 's1')
    with pytest.raises(ValueError, match='no registered'): sources.discuss(project, 'x9')
    with pytest.raises(ValueError, match='not a paper number'): sources.discuss(project, 'alpha')
    with project.lock(): assert project.keywords('algorithm', 'x2')['target'] == 'x0002'


def test_summary_block_and_show(project, tmp_path):
    _three_papers(project, tmp_path)
    assert sources.show_summary(project, 'x1')['summary'].endswith('_Not discussed yet._')
    note = project.root / sources.list_sources(project)[0]['path']
    meta, body = read_doc(note)
    write_doc(note, meta, body.replace('_Not discussed yet._', '### Main idea\n- Goal: x'))
    assert 'Goal: x' in sources.show_summary(project, 'x0001')['summary']


def test_bare_number_error_points_to_x_paper(project, tmp_path):
    _three_papers(project, tmp_path)
    with pytest.raises(ValueError, match='undiscussed paper with that number is x0002'):
        sources.discuss(project, '2')


def test_set_summary_inserts_and_replaces_block(project, tmp_path):
    _three_papers(project, tmp_path)
    sources.set_summary(project, 'x1', '## Summary\n\n### Main idea\n- Goal: first')
    assert 'Goal: first' in sources.show_summary(project, 'x1')['summary']
    sources.set_summary(project, 'x0001', '## Summary\n\n### Main idea\n- Goal: second')
    summary = sources.show_summary(project, 'x1')['summary']
    assert 'second' in summary and 'first' not in summary
    note = (project.root / sources.list_sources(project)[0]['path']).read_text()
    assert note.count('rs:summary:start') == 1 and 'Alpha Paper' in note


def test_set_summary_on_note_without_block_preserves_notes(project):
    write_doc(project.root / 'papers/x0001_old_one.md', {'key': 'x0001', 'type': 'paper', 'title': 'Old One', 'tags': []}, '# Old One\n\n## Reading notes\nkept\n')
    sources.set_summary(project, 'x1', '## Summary\n\nhello')
    text = (project.root / 'papers/x0001_old_one.md').read_text()
    assert 'hello' in text and 'kept' in text and text.index('rs:summary:start') < text.index('## Reading notes')
