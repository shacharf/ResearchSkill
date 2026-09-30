#!/usr/bin/env python3
"""Install only project-local research assets; never edit global host settings."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


CLAUDE_SETTINGS = {
    'respondToBashCommands': False,
    'pluginConfigs': {'agents-md@builtin': {'options': {'instructionFiles': 'claude-md-and-agents-md'}}},
}


def merge_missing(current: dict, wanted: dict, path: str = '') -> list:
    """Add wanted keys that are absent; return the paths whose existing values differ."""
    conflicts = []
    for key, value in wanted.items():
        if key not in current:
            current[key] = value
        elif isinstance(value, dict) and isinstance(current[key], dict):
            conflicts += merge_missing(current[key], value, f'{path}{key}.')
        elif current[key] != value:
            conflicts.append(path + key)
    return conflicts


def configure_claude(project: Path) -> list:
    """Merge the required settings into project .claude/settings.json; return problems (empty = plain `claude` works)."""
    target = project / '.claude' / 'settings.json'
    if target.is_symlink():
        return ['.claude/settings.json is a symbolic link']
    try:
        current = json.loads(target.read_text()) if target.exists() else {}
    except (ValueError, OSError) as error:
        return [f'.claude/settings.json is not valid JSON ({error})']
    if not isinstance(current, dict):
        return ['.claude/settings.json is not a JSON object']
    conflicts = merge_missing(current, CLAUDE_SETTINGS)
    if conflicts:
        return [f'.claude/settings.json sets {name} differently' for name in conflicts]
    text = json.dumps(current, indent=2) + '\n'
    if not target.exists() or json.loads(target.read_text()) != current:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return []


def install(project: Path, engine: str, skip_gno: bool = False) -> dict:
    if sys.version_info < (3, 10):
        raise ValueError('Python >=3.10 is required')
    import yaml  # declared runtime prerequisite
    from rs.storage import Project
    from rs import indexing
    project = project.expanduser().resolve()
    if project.exists() and not project.is_dir():
        raise ValueError('Project target must be a directory')
    if not skip_gno and not shutil.which('gno'):
        raise ValueError('GNO is required on PATH; --skip-gno is for offline tests only')
    if engine not in ('codex', 'claude'):
        raise ValueError('Engine must be codex or claude')
    state_path = project / '.rs' / 'installation.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'managed': {}, 'engines': []}
    desired = {}
    skill_dir = '.agents' if engine == 'codex' else '.claude'
    for source in sorted((SOURCE / 'skills').glob('rs-*/SKILL.md')):
        # One neutral source is maintained for both clients.
        data = source.read_bytes()
        metadata = yaml.safe_load(data.decode().split('---', 2)[1])
        if metadata.get('name') != source.parent.name:
            raise ValueError(f'Invalid skill metadata: {source}')
        desired[f'{skill_dir}/skills/{source.parent.name}/SKILL.md'] = data
    desired['RESEARCH_WORKFLOW.md'] = (SOURCE / 'README.md').read_bytes()
    if engine == 'claude':
        desired['.rs/claude-settings.json'] = (json.dumps(CLAUDE_SETTINGS, indent=2) + '\n').encode()
    # Preflight every managed asset before creating/modifying any research files.
    conflicts = []
    for relative, data in desired.items():
        target = project / relative
        if target.is_symlink():
            conflicts.append(relative + ' (symbolic link)')
        elif target.exists():
            current = digest(target.read_bytes())
            if current != digest(data) and current != state['managed'].get(relative):
                conflicts.append(relative)
    agents = project / 'AGENTS.md'
    begin, end = '<!-- rs:instructions:start -->', '<!-- rs:instructions:end -->'
    block = begin + '\n' + (SOURCE / 'templates' / 'AGENTS.md').read_text().strip() + '\n' + end
    agents_text = agents.read_text() if agents.exists() else ''
    if (begin in agents_text) != (end in agents_text) or agents_text.count(begin) > 1 or agents_text.count(end) > 1:
        conflicts.append('AGENTS.md (malformed managed block)')
    elif begin in agents_text:
        old_block = agents_text[agents_text.index(begin):agents_text.index(end) + len(end)]
        old_digest = digest(old_block.encode())
        if old_block != block and old_digest != state['managed'].get('AGENTS.md#instructions'):
            conflicts.append('AGENTS.md (modified instructions block)')
    if conflicts:
        raise ValueError('Preserved modified installed files; resolve conflicts before reinstalling: ' + ', '.join(conflicts))
    project.mkdir(parents=True, exist_ok=True)
    sidebar = project / '_sidebar.md'
    if sidebar.exists() and '<!-- rs:navigation:start -->' not in sidebar.read_text():
        sidebar.write_text(sidebar.read_text().rstrip() + '\n\n<!-- rs:navigation:start -->\n<!-- rs:navigation:end -->\n')
    previous_worker = os.environ.get('RS_DISABLE_WORKER')
    os.environ['RS_DISABLE_WORKER'] = '1'
    try:
        Project.initialize(project)
    finally:
        if previous_worker is None:
            os.environ.pop('RS_DISABLE_WORKER', None)
        else:
            os.environ['RS_DISABLE_WORKER'] = previous_worker
    if not skip_gno:
        indexing.configure(project)
    for relative, data in desired.items():
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != data:
            target.write_bytes(data)
        state['managed'][relative] = digest(data)
    if begin in agents_text:
        start, stop = agents_text.index(begin), agents_text.index(end) + len(end)
        agents_text = agents_text[:start] + block + agents_text[stop:]
    else:
        agents_text = agents_text.rstrip() + ('\n\n' if agents_text.strip() else '') + block + '\n'
    if not agents.exists() or agents.read_text() != agents_text:
        agents.write_text(agents_text)
    state['managed']['AGENTS.md#instructions'] = digest(block.encode())
    renderer = project / 'index.html'
    if not renderer.exists():
        shutil.copyfile(SOURCE / 'index.html', renderer)
    else:
        adapt_renderer(renderer)
    if not (project / 'README.md').exists():
        (project / 'README.md').write_text('# Research project\n\nStart with `rsagent status`. See [workflow instructions](RESEARCH_WORKFLOW.md).\n')
    state['engines'] = sorted(set(state['engines'] + [engine]))
    state['offline_test_install'] = skip_gno
    state_path.write_text(json.dumps(state, indent=2) + '\n')
    warnings = []
    if not shutil.which('rsagent'):
        warnings.append('The rsagent command is not on PATH. From the toolkit checkout run `uv tool install .` then `uv tool update-shell`, and start a new shell before launching the agent.')
    settings_problems = configure_claude(project) if engine == 'claude' else []
    warnings.extend(settings_problems)
    if skip_gno:
        warnings.append('Offline test installation: GNO indexing is not configured. Reinstall without --skip-gno for research use.')
    if engine == 'claude':
        for ancestor in (project, *project.parents):
            for relative in ('CLAUDE.md', 'CLAUDE.local.md', '.claude/CLAUDE.md'):
                if (ancestor / relative).exists():
                    warnings.append(f'Existing instructions: {ancestor / relative}; confirm AGENTS.md appears under /memory.')
        executable = shutil.which('claude')
        if executable:
            version = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=15).stdout.strip()
            warnings.append(f'Claude version detected: {version}. Supported: >=2.1.281; confirm AGENTS.md under /memory.')
        else:
            warnings.append('Claude is not on PATH. Install Claude Code >=2.1.281.')
    from rs.sources import validate
    warnings.extend('Validation: ' + error for error in validate(Project(project)))
    if not skip_gno:
        indexing.start_worker(project)
    startup = 'codex' if engine == 'codex' else ('claude --settings .rs/claude-settings.json' if settings_problems else 'claude')
    invocation = '$rs-research' if engine == 'codex' else '/rs-research'
    return {'project': str(project), 'engine': engine, 'startup': startup, 'invoke': invocation, 'warnings': warnings}


def adapt_renderer(path: Path) -> None:
    """Patch the known legacy renderer surgically, preserving all other customizations."""
    text = path.read_text()
    original = text
    source = (SOURCE / 'index.html').read_text()
    if "function bibliographyPath(" in text and "'ref.bib'" in text:
        start = text.index('    function bibliographyPath(')
        stop = text.index('    function renderLatexCitations', start)
        new_start = source.index('    function bibliographyPath(')
        new_stop = source.index('    function renderLatexCitations', new_start)
        text = text[:start] + source[new_start:new_stop] + text[stop:]
        text = text.replace('    const bibliographyCache = new Map();\n', '')
        text = text.replace('markdown = normalizeMermaidFlowcharts(markdown);',
                            'markdown = normalizeMermaidFlowcharts(hideFrontmatter(markdown));')
        text = text.replace('next(markdown);\n              });', 'next(renderLatexCitations(markdown, [], vm.route.path));\n              });')
    if 'https://github.com/USER/REPO/edit/main/docs/' in text:
        start = text.index('          hook.afterEach(')
        stop = text.index('          hook.doneEach(', start)
        new_start = source.index('          hook.afterEach(')
        new_stop = source.index('          hook.doneEach(', new_start)
        text = text[:start] + source[new_start:new_stop] + text[stop:]
    if 'window.$docsify' in text and "homepage:" not in text:
        text = text.replace('window.$docsify = {', "window.$docsify = {\n      homepage: 'project_overview.md',", 1)
    if 'window.$docsify' in text and "alias:" not in text:
        text = text.replace('window.$docsify = {', "window.$docsify = {\n      alias: { '/.*/_sidebar.md': '/_sidebar.md' },", 1)
    if text != original:
        path.write_text(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--engine', required=True, choices=('codex', 'claude'))
    parser.add_argument('--skip-gno', action='store_true', help='offline installation/tests only; leaves retrieval unconfigured')
    args = parser.parse_args()
    try:
        result = install(args.project, args.engine, args.skip_gno)
    except (ValueError, OSError, ImportError, subprocess.SubprocessError) as error:
        print(f'Installation failed: {error}', file=sys.stderr)
        return 1
    print(f"Installed {result['engine']} skills in {result['project']}.")
    print(f"From that project: {result['startup']}\nThen invoke {result['invoke']} or run !rsagent status.")
    if result['startup'].startswith('claude --settings'):
        print('Existing Claude settings were left unchanged, so launch with the settings file above.')
    for warning in result['warnings']:
        print('Note: ' + warning)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
