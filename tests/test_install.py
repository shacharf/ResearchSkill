"""Installer preservation and project-local integration tests (no host inference)."""
import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('install_project', Path(__file__).parents[1] / 'scripts/install_project.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

@pytest.fixture(autouse=True)
def no_worker(monkeypatch):
    monkeypatch.setenv('RS_DISABLE_WORKER', '1')


def test_both_engines_and_repeat_preserve_records(tmp_path):
    project = tmp_path / 'research'
    installer.install(project, 'codex', True)
    overview = project / 'project_overview.md'
    overview.write_text(overview.read_text() + '\nManual research stays.\n')
    vocabulary = project / 'keywords.yaml'
    vocabulary.write_text(vocabulary.read_text() + '  - name: systems\n')
    snapshot = vocabulary.read_bytes()
    settings = project / '.claude/settings.json'
    settings.parent.mkdir(exist_ok=True)
    settings.write_text('{"custom":"preserve"}\n')
    installer.install(project, 'claude', True)
    installer.install(project, 'codex', True)
    assert 'Manual research stays.' in overview.read_text()
    assert vocabulary.read_bytes() == snapshot
    merged = json.loads(settings.read_text())
    assert merged['custom'] == 'preserve' and merged['respondToBashCommands'] is False
    assert len(list((project / '.agents/skills').glob('rs-*/SKILL.md'))) == 7
    assert len(list((project / '.claude/skills').glob('rs-*/SKILL.md'))) == 7
    assert (project / 'AGENTS.md').read_text().count('<!-- rs:instructions:start -->') == 1
    assert json.loads((project / '.rs/installation.json').read_text())['engines'] == ['claude', 'codex']
    launch = json.loads((project / '.rs/claude-settings.json').read_text())
    assert launch['respondToBashCommands'] is False
    assert launch['pluginConfigs']['agents-md@builtin']['options']['instructionFiles'] == 'claude-md-and-agents-md'


def test_existing_custom_instructions_sidebar_renderer_preserved(tmp_path):
    (tmp_path / 'AGENTS.md').write_text('User instructions.\n')
    (tmp_path / '_sidebar.md').write_text('- [Custom](custom.md)\n')
    (tmp_path / 'custom.md').write_text('Custom page')
    (tmp_path / 'index.html').write_text('<html>Custom renderer</html>')
    result = installer.install(tmp_path, 'codex', True)
    assert (tmp_path / 'AGENTS.md').read_text().startswith('User instructions.')
    sidebar = (tmp_path / '_sidebar.md').read_text()
    assert '[Custom](custom.md)' in sidebar and '[Overview](project_overview.md)' in sidebar
    assert (tmp_path / 'index.html').read_text() == '<html>Custom renderer</html>'
    assert not (tmp_path / '.claude').exists()
    assert any('Offline test' in value for value in result['warnings'])


def test_modified_skill_conflict_does_not_overwrite_or_install_other_assets(tmp_path):
    installer.install(tmp_path, 'codex', True)
    skill = tmp_path / '.agents/skills/rs-save/SKILL.md'
    skill.write_text(skill.read_text() + '\nManual change\n')
    before = (tmp_path / '.rs/installation.json').read_bytes()
    with pytest.raises(ValueError, match='rs-save'):
        installer.install(tmp_path, 'codex', True)
    assert skill.read_text().endswith('Manual change\n')
    assert (tmp_path / '.rs/installation.json').read_bytes() == before


def test_modified_managed_instructions_conflict(tmp_path):
    installer.install(tmp_path, 'codex', True)
    agents = tmp_path / 'AGENTS.md'
    agents.write_text(agents.read_text().replace('Never run Git commands.', 'Manual rule.'))
    with pytest.raises(ValueError, match='modified instructions'):
        installer.install(tmp_path, 'codex', True)


def test_prerequisite_failure_leaves_target_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.shutil, 'which', lambda value: None)
    target = tmp_path / 'new'
    with pytest.raises(ValueError, match='GNO is required'):
        installer.install(target, 'codex')
    assert not target.exists()


def test_root_bibliography_runtime(tmp_path):
    # Exercise browser-independent renderer functions in Node when available.
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    text = (Path(__file__).parents[1] / 'index.html').read_text()
    script = text[text.index('    function bibliographyPath('):text.index('    function renderLatexCitations')]
    js = "const assert=require('assert'); global.window={location:{href:'https://example.org/research/#/threads/001_test'}};" + script + """
assert.equal(bibliographyPath('threads/001_test.md'), 'https://example.org/research/refs.bib');
assert.equal(hideFrontmatter('---\\nid: "001"\\n---\\n# Thread'), '# Thread');
let calls=0;global.fetch=async (path, opts)=>{assert.equal(opts.cache,'no-cache');calls++;return {ok:true,text:async()=>''}};
global.bibtexParse={toJSON:()=>[]};
(async()=>{await loadBibliography(bibliographyPath());await loadBibliography(bibliographyPath());assert.equal(calls,2)})();
"""
    process = subprocess.run([node, '-e', js], capture_output=True, text=True)
    assert process.returncode == 0, process.stderr


def test_claude_settings_created_and_plain_launch(tmp_path):
    result = installer.install(tmp_path, 'claude', True)
    settings = json.loads((tmp_path / '.claude/settings.json').read_text())
    assert settings['respondToBashCommands'] is False
    assert settings['pluginConfigs']['agents-md@builtin']['options']['instructionFiles'] == 'claude-md-and-agents-md'
    assert result['startup'] == 'claude'
    again = installer.install(tmp_path, 'claude', True)
    assert json.loads((tmp_path / '.claude/settings.json').read_text()) == settings and again['startup'] == 'claude'


def test_claude_conflicting_settings_preserved_and_launch_file_used(tmp_path):
    settings = tmp_path / '.claude/settings.json'
    settings.parent.mkdir()
    original = '{"respondToBashCommands": true, "permissions": {"allow": ["Bash(ls)"]}}\n'
    settings.write_text(original)
    result = installer.install(tmp_path, 'claude', True)
    assert settings.read_text() == original
    assert result['startup'] == 'claude --settings .rs/claude-settings.json'
    assert any('respondToBashCommands' in w for w in result['warnings'])


def test_claude_malformed_settings_untouched(tmp_path):
    settings = tmp_path / '.claude/settings.json'
    settings.parent.mkdir()
    settings.write_text('{not json')
    result = installer.install(tmp_path, 'claude', True)
    assert settings.read_text() == '{not json'
    assert result['startup'].startswith('claude --settings')


def test_codex_install_writes_no_claude_settings(tmp_path):
    result = installer.install(tmp_path, 'codex', True)
    assert not (tmp_path / '.claude').exists() and result['startup'] == 'codex'


def test_warns_when_rsagent_missing_from_path(tmp_path, monkeypatch):
    real = installer.shutil.which
    monkeypatch.setattr(installer.shutil, 'which', lambda name: None if name == 'rsagent' else real(name))
    result = installer.install(tmp_path, 'codex', True)
    assert any('rsagent command is not on PATH' in w for w in result['warnings'])


def test_skill_support_files_are_installed(tmp_path):
    installer.install(tmp_path, 'claude', True)
    assert (tmp_path / '.claude/skills/rs-paper/overview.md').exists()
