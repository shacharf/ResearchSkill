"""Authoritative Markdown, stable allocation and recoverable local transactions."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import unquote, urlsplit

import yaml


class Error(ValueError):
    """A diagnostic suitable for compact terminal output."""


class StringDumper(yaml.SafeDumper):
    pass


def _string(dumper, value):
    return dumper.represent_scalar('tag:yaml.org,2002:str', value,
                                   style='"' if value.isdigit() else None)


StringDumper.add_representer(str, _string)


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
        try:
            handle.write(text if isinstance(text, bytes) else text.encode('utf-8'))
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_doc(path):
    path = Path(path)
    text = path.read_text(encoding='utf-8')
    if not text.startswith('---\n'):
        return {}, text
    match = re.match(r'\A---\n(.*?)\n---(?:\n|$)', text, re.S)
    if not match:
        raise Error(f'{path}: unterminated YAML frontmatter')
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise Error(f'{path}: invalid YAML: {exc}') from exc
    if not isinstance(meta, dict):
        raise Error(f'{path}: frontmatter must be a mapping')
    for field in ('id', 'key', 'active_thread'):
        if field in meta and not isinstance(meta[field], str):
            raise Error(f'{path}: {field} must be a quoted string')
    if 'tags' in meta and (not isinstance(meta['tags'], list) or
                           any(not isinstance(tag, str) for tag in meta['tags'])):
        raise Error(f'{path}: tags must be a list of strings')
    for field in ('title', 'status', 'type'):
        if field in meta and not isinstance(meta[field], str):
            if field == 'title' and meta[field] is None and meta.get('type') in ('paper', 'repo', 'tool', 'web'):
                continue
            raise Error(f'{path}: {field} must be a string')
    if 'status' in meta and meta['status'] not in ('open', 'closed', 'obsolete'):
        raise Error(f'{path}: invalid stored thread status')
    return meta, text[match.end():]


def write_doc(path, metadata, body):
    if not metadata:
        return atomic_write(path, body)
    atomic_write(path, '---\n' + yaml.dump(metadata, Dumper=StringDumper,
                  sort_keys=False, allow_unicode=True).rstrip() + '\n---\n' + body)


def slug(text):
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')[:80] or 'untitled'


def normalize_key(ref):
    """Normalize a paper/source number such as 2, 0002, x3 or S1 to its stored key."""
    match = re.fullmatch(r'([xXsS]?)0*(\d+)', str(ref).strip())
    if not match:
        raise Error(f'{ref!r} is not a paper number (examples: 2, 0002, x0003)')
    return match.group(1).lower() + str(int(match.group(2))).zfill(4)


def key_order(key):
    """Sort discussed papers numerically first, then x papers, then s sources."""
    return ({'': 0, 'x': 1, 's': 2}[key[:1] if key[:1] in 'xs' else ''], int(key.lstrip('xs')))


def unique_path(directory, stem, suffix='.md'):
    directory = Path(directory)
    path = directory / (stem + suffix)
    number = 2
    while path.exists():
        path = directory / f'{stem}_{number}{suffix}'
        number += 1
    return path


def section(body, name):
    pattern = rf'<!-- rs:{re.escape(name)}:start -->\n?(.*?)<!-- rs:{re.escape(name)}:end -->'
    match = re.search(pattern, body, re.S)
    if not match:
        raise Error(f'missing designated {name} section')
    return match.group(1).strip()


def replace_section(body, name, value):
    pattern = rf'(<!-- rs:{re.escape(name)}:start -->)\n?.*?(<!-- rs:{re.escape(name)}:end -->)'
    result, count = re.subn(pattern, lambda m: m[1] + '\n' + value.rstrip() + '\n' + m[2], body, flags=re.S)
    if not count:
        raise Error(f'missing designated {name} section')
    return result


BRIEF_LIMIT = 3000
RESUME_LIMIT = 5000
RESUME_FIELDS = ('Guiding question', 'Current understanding', 'Immediate focus', 'Next step', 'Supporting material')


def bounded(text, limit, location):
    if len(text) <= limit:
        return {'text': text, 'excerpt': False, 'location': location}
    marker = f'\n[BOUNDED EXCERPT: section exceeds {limit} characters; read {location} for omitted context]'
    return {'text': text[:max(0, limit - len(marker))] + marker,
            'excerpt': True, 'location': location}


def _origin_note(pending):
    origin = pending.get('origin')
    source = f" from [{origin.split('/')[-1][:3]}]({origin})" if origin else ''
    return f"Started from TODO{source}: {pending['title']}\n\n"


class Project:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not (self.root / '.rs/config.json').is_file():
            raise Error(f'{self.root}: no rs project; run the project installer')

    @classmethod
    def discover(cls, start=None):
        path = Path(start or Path.cwd()).resolve()
        for root in (path, *path.parents):
            if (root / '.rs/config.json').is_file():
                return cls(root)
        raise Error('no rs project found in this directory or its parents')

    @classmethod
    def initialize(cls, root):
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        for name in ('.rs', 'threads', 'papers/files', 'sources'):
            (root / name).mkdir(parents=True, exist_ok=True)
        defaults = {
            '.rs/config.json': json.dumps({'schema': 1, 'high_water': {}, 'brief_limit': BRIEF_LIMIT,
                                          'resume_limit': RESUME_LIMIT}, indent=2) + '\n',
            'project_overview.md': '---\nactive_thread: ""\n---\n# Project overview\n\n<!-- rs:brief:start -->\n## Project brief\nGoal: Define the research problem.\n\nShared assumptions: None confirmed yet.\n\nConfirmed conclusions: None yet.\n<!-- rs:brief:end -->\n\n## Shared research\n\n## Thread directory\n<!-- rs:navigation:start -->\n<!-- rs:navigation:end -->\n',
            'TODO.md': '# Deferred research topics\n\n',
            'keywords.yaml': '# Edit this controlled vocabulary directly. Names are normalized to lowercase.\nkeywords:\n  - name: algorithm\n    description: Algorithm design and analysis\n  - name: evaluation\n    description: Experimental evaluation\n',
            'paper.md': '# Title\n\n## Abstract\n\n## Introduction\n\n## Related work\n\n## Method\n',
            'refs.bib': '% Generated by rs from source-note metadata.\n',
            '_sidebar.md': '<!-- rs:navigation:start -->\n<!-- rs:navigation:end -->\n',
        }
        for name, content in defaults.items():
            if not (root / name).exists():
                atomic_write(root / name, content)
        project = cls(root)
        with project.lock():
            project.refresh_navigation()
        return project

    @contextlib.contextmanager
    def lock(self):
        with (self.root / '.rs/project.lock').open('a+') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                self.recover()
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def config(self):
        try:
            value = json.loads((self.root / '.rs/config.json').read_text())
            if not isinstance(value, dict):
                raise ValueError('expected object')
            return value
        except (ValueError, OSError) as exc:
            raise Error(f'invalid .rs/config.json: {exc}') from exc

    def notes(self, kind):
        directory = {'thread': 'threads', 'paper': 'papers', 'source': 'sources'}[kind]
        return sorted((self.root / directory).glob('*.md'))

    def allocate(self, kind):
        """Next counter value for thread, todo, discussed (paper number), paper_x (x-prefixed paper) or source (s-prefixed)."""
        config = self.config()
        water = config.setdefault('high_water', {})
        observed = []
        if kind == 'todo':
            observed = [int(item['id']) for item in self.todos()]
        else:
            group, field, prefix = {'thread': ('thread', 'id', ''), 'discussed': ('paper', 'key', ''),
                                    'paper_x': ('paper', 'key', 'x'), 'source': ('source', 'key', 's')}[kind]
            for path in self.notes(group):
                value = read_doc(path)[0].get(field)
                if not isinstance(value, str) or not value:
                    raise Error(f'{path}: invalid {field}')
                if value[:len(prefix)] == prefix and value[len(prefix):].isdigit():
                    observed.append(int(value[len(prefix):]))
        number = max(int(water.get(kind, 0)), max(observed, default=0)) + 1
        water[kind] = number
        atomic_write(self.root / '.rs/config.json', json.dumps(config, indent=2) + '\n')
        prefix = {'paper_x': 'x', 'source': 's'}.get(kind, '')
        return prefix + str(number).zfill(3 if kind in ('thread', 'todo') else 4)

    def transaction(self, changes):
        """Roll forward a persisted multi-file change, including deletions, after interruption."""
        journal = {}
        for path, value in changes.items():
            relative = Path(path).resolve().relative_to(self.root).as_posix()
            if relative.startswith('.rs/'):
                raise Error('research transactions cannot alter runtime state')
            journal[relative] = value
        atomic_write(self.root / '.rs/transaction.json', json.dumps(journal))
        self.recover()

    def recover(self):
        path = self.root / '.rs/transaction.json'
        if not path.exists():
            return
        changes = json.loads(path.read_text())
        for name, value in changes.items():
            target = (self.root / name).resolve()
            target.relative_to(self.root)
            if value is None:
                target.unlink(missing_ok=True)
            else:
                atomic_write(target, value)
        # Persist retries before removing the only recovery record.
        self.enqueue([self.root / name for name in changes])
        path.unlink()

    def enqueue(self, paths):
        from .indexing import enqueue
        enqueue(self.root, paths)

    def thread(self, identifier=None):
        if identifier is None:
            identifier = read_doc(self.root / 'project_overview.md')[0].get('active_thread', '')
            if not identifier:
                raise Error('no active thread selected')
        for path in self.notes('thread'):
            meta, body = read_doc(path)
            if meta.get('id') == identifier:
                if identifier == read_doc(self.root / 'project_overview.md')[0].get('active_thread') and meta.get('status') != 'open':
                    raise Error('active pointer references a non-open thread')
                return path, meta, body
        raise Error(f'thread {identifier} does not exist')

    def threads(self, include_all=False, keyword=None):
        active = read_doc(self.root / 'project_overview.md')[0].get('active_thread', '')
        result = []
        for path in self.notes('thread'):
            meta, _ = read_doc(path)
            if not isinstance(meta.get('id'), str) or not meta['id'].isdigit():
                raise Error(f'{path}: invalid thread ID')
            if meta.get('status') not in ('open', 'closed', 'obsolete'):
                raise Error(f'{path}: invalid thread status')
            if (meta['status'] == 'obsolete' and not include_all) or (keyword and keyword not in meta.get('tags', [])):
                continue
            result.append({**meta, 'status': ('active' if meta['id'] == active else 'paused') if meta['status'] == 'open' else meta['status'],
                           'path': path.relative_to(self.root).as_posix()})
        return sorted(result, key=lambda item: int(item['id']))

    def status(self):
        path = self.root / 'project_overview.md'
        meta, body = read_doc(path)
        config = self.config()
        result = {'project': str(self.root), 'brief': bounded(section(body, 'brief'), config.get('brief_limit', BRIEF_LIMIT), 'project_overview.md#project-brief'),
                  'active_thread': meta.get('active_thread', ''), 'pointers': {'threads': 'rsagent threads', 'todo': 'TODO.md', 'overview': 'project_overview.md'}}
        if result['active_thread']:
            thread_path, thread_meta, thread_body = self.thread()
            result['thread'] = {'id': thread_meta['id'], 'title': thread_meta.get('title'), 'path': thread_path.relative_to(self.root).as_posix(),
                                'resume': bounded(section(thread_body, 'resume'), config.get('resume_limit', RESUME_LIMIT), thread_path.relative_to(self.root).as_posix() + '#compact-resume')}
        from .indexing import state
        result['indexing'] = state(self.root)
        return result

    def create_thread(self, title):
        if not title.strip():
            raise Error('thread title cannot be empty')
        identifier = self.allocate('thread')
        path = unique_path(self.root / 'threads', identifier + '_' + slug(title))
        body = f'# {title}\n\n## Compact resume\n<!-- rs:resume:start -->\n' + '\n\n'.join(f'### {field}\n' + (title if field == 'Guiding question' else 'Not established yet.') for field in RESUME_FIELDS) + '\n<!-- rs:resume:end -->\n\n## Research record\n\n'
        write_doc(path, {'id': identifier, 'title': title, 'status': 'open', 'tags': []}, body)
        self.refresh_navigation()
        self.enqueue([path])
        return {'id': identifier, 'path': path.relative_to(self.root).as_posix()}

    def select(self, identifier):
        _, meta, _ = self.thread(identifier)
        if meta['status'] != 'open':
            raise Error('only open threads can be selected; restore it first')
        path = self.root / 'project_overview.md'
        overview, body = read_doc(path)
        overview['active_thread'] = identifier
        write_doc(path, overview, body)
        self.refresh_navigation()
        self.enqueue([path])
        return {'active_thread': identifier, 'warning': 'Selection changes files only; checkpoint unsaved conversation before switching.'}

    def set_status(self, identifier, status):
        if status not in ('open', 'closed', 'obsolete'):
            raise Error('status must be open, closed, or obsolete')
        path, meta, body = self.thread(identifier)
        meta['status'] = status
        changes = {path: doc_text(meta, body)}
        overview_path = self.root / 'project_overview.md'
        overview, overview_body = read_doc(overview_path)
        if status != 'open' and overview.get('active_thread') == identifier:
            overview['active_thread'] = ''
            changes[overview_path] = doc_text(overview, overview_body)
        self.transaction(changes)
        self.refresh_navigation()
        return {'id': identifier, 'status': status}

    def todos(self):
        text = (self.root / 'TODO.md').read_text()
        result = []
        for match in re.finditer(r'^- \[ \] <!-- rs:todo:(\d+) --> (.*)$', text, re.M):
            identifier, content = match.groups()
            provenance = re.search(r' \(from \[[^\]]*\]\((threads/[^)]+)\)\)$', content)
            result.append({'id': identifier, 'text': content[:provenance.start()] if provenance else content,
                           'origin': provenance[1] if provenance else None})
        ids = [item['id'] for item in result]
        if len(set(ids)) != len(ids):
            raise Error('duplicate TODO IDs')
        return result

    def add_todo(self, text):
        text = ' '.join(text.splitlines()).strip()
        if not text:
            raise Error('TODO text cannot be empty')
        identifier = self.allocate('todo')
        active = read_doc(self.root / 'project_overview.md')[0].get('active_thread', '')
        provenance = ''
        if active:
            path, _, _ = self.thread(active)
            provenance = f' (from [{active}]({path.relative_to(self.root).as_posix()}))'
        path = self.root / 'TODO.md'
        atomic_write(path, path.read_text().rstrip() + f'\n\n- [ ] <!-- rs:todo:{identifier} --> {text}{provenance}\n')
        self.enqueue([path])
        return {'id': identifier, 'text': text}

    def remove_todo(self, identifier):
        if not any(item['id'] == identifier for item in self.todos()):
            raise Error(f'TODO {identifier} does not exist')
        path = self.root / 'TODO.md'
        text = re.sub(rf'^- \[ \] <!-- rs:todo:{re.escape(identifier)} --> .*\n?', '', path.read_text(), flags=re.M)
        atomic_write(path, text)
        self.enqueue([path])
        return {'removed': identifier}

    def promote(self, identifier):
        pending_path = self.root / '.rs/promotion.json'
        if pending_path.exists():
            pending = json.loads(pending_path.read_text())
            if pending['todo'] != identifier:
                raise Error(f"finish interrupted promotion of TODO {pending['todo']} first")
            result = pending['thread']
        else:
            item = next((item for item in self.todos() if item['id'] == identifier), None)
            if not item:
                raise Error(f'TODO {identifier} does not exist')
            # Allocate and journal before creating, so an interrupted retry cannot duplicate a thread.
            thread_id = self.allocate('thread')
            path = unique_path(self.root / 'threads', thread_id + '_' + slug(item['text']))
            result = {'id': thread_id, 'path': path.relative_to(self.root).as_posix()}
            atomic_write(pending_path, json.dumps({'todo': identifier, 'thread': result, 'title': item['text'], 'origin': item['origin']}))
        pending = json.loads(pending_path.read_text())
        path = self.root / result['path']
        if not path.exists():
            body = f"# {pending['title']}\n\n## Compact resume\n<!-- rs:resume:start -->\n" + '\n\n'.join(f'### {field}\n' + (pending['title'] if field == 'Guiding question' else 'Not established yet.') for field in RESUME_FIELDS) + '\n<!-- rs:resume:end -->\n\n## Research record\n\n' + _origin_note(pending)
            write_doc(path, {'id': result['id'], 'title': pending['title'], 'status': 'open', 'tags': []}, body)
        if any(item['id'] == identifier for item in self.todos()):
            self.remove_todo(identifier)
        self.select(result['id'])
        self.refresh_navigation()
        self.enqueue([path])
        pending_path.unlink()
        return result

    def vocabulary(self):
        path = self.root / 'keywords.yaml'
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise Error(f'{path}: invalid YAML: {exc}') from exc
        if not isinstance(data, dict) or not isinstance(data.get('keywords'), list):
            raise Error('keywords.yaml requires a keywords list of {name, description} mappings')
        result = {}
        for entry in data['keywords']:
            if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or ('description' in entry and not isinstance(entry['description'], str)):
                raise Error('keyword entries require string name and optional string description')
            name = entry['name'].strip().lower()
            if not name or name in result:
                raise Error(f'empty or duplicate vocabulary keyword: {name}')
            result[name] = entry.get('description', '')
        return result

    def keywords(self, value=None, key=None):
        if key:
            key = normalize_key(key)
            paths = [path for kind in ('paper', 'source') for path in self.notes(kind) if read_doc(path)[0].get('key') == key]
            if len(paths) != 1:
                raise Error(f'source key {key} does not identify a unique note')
            path = paths[0]
            meta, body = read_doc(path)
        else:
            path, meta, body = self.thread()
        if value is not None:
            additions = [word.strip().lower() for word in value.split(',') if word.strip()]
            unknown = set(additions) - set(self.vocabulary())
            if unknown:
                raise Error('unknown keywords: ' + ', '.join(sorted(unknown)) + '; edit keywords.yaml explicitly')
            meta['tags'] = list(dict.fromkeys(meta.get('tags', []) + additions))
            write_doc(path, meta, body)
            self.enqueue([path])
        return {'target': key or meta['id'], 'tags': meta.get('tags', [])}

    def refresh_navigation(self):
        items = self.threads(include_all=True)
        directory = '\n'.join(f"- [{item['id']} — {item['title']} ({item['status']})]({item['path']})" for item in items)
        overview_path = self.root / 'project_overview.md'
        meta, body = read_doc(overview_path)
        if '<!-- rs:navigation:start -->' in body:
            write_doc(overview_path, meta, replace_section(body, 'navigation', directory))
        sidebar = self.root / '_sidebar.md'
        navigation = '- [Overview](project_overview.md)\n- [TODO](TODO.md)\n- [Manuscript](paper.md)\n' + directory
        for kind in ('paper', 'source'):
            for path in self.notes(kind):
                note, _ = read_doc(path)
                navigation += f"\n- [{note.get('key', '?')} — {note.get('title', path.stem)}]({path.relative_to(self.root).as_posix()})"
        if sidebar.exists():
            content = sidebar.read_text()
            if '<!-- rs:navigation:start -->' in content:
                atomic_write(sidebar, replace_section(content, 'navigation', navigation))
        self.enqueue([overview_path, sidebar])


def doc_text(meta, body):
    return '---\n' + yaml.dump(meta, Dumper=StringDumper, sort_keys=False, allow_unicode=True).rstrip() + '\n---\n' + body


def research_files(project):
    # Include user research Markdown, but never skills/runtime/vendor documentation.
    return sorted(path for path in project.root.rglob('*.md') if not any(part.startswith('.') or part in ('node_modules', '__pycache__') for part in path.relative_to(project.root).parts))


def incoming(project, target):
    references = []
    for path in research_files(project):
        if path == target:
            continue
        meta, body = read_doc(path)
        clean, count = clean_references(project, path, target, meta, body)
        ambiguous = []
        for number, line in enumerate(body.splitlines(), 1):
            if target.name in line and not re.search(r'\[[^\]]*\]\([^)]*' + re.escape(target.name), line):
                ambiguous.append({'line': number, 'text': line[:200]})
        if count or ambiguous:
            references.append({'path': path.relative_to(project.root).as_posix(), 'links_or_metadata': count, 'ambiguous': ambiguous})
    return references


def clean_references(project, path, target, meta, body):
    count = 0
    def substitute(match):
        nonlocal count
        dest = unquote(match[2].split('#')[0].split('?')[0])
        if urlsplit(dest).scheme:
            return match[0]
        if (path.parent / dest).resolve() == target or (project.root / dest.lstrip('/')).resolve() == target:
            count += 1
            # Generated directory lines are removed separately; keep independent anchor text.
            return match[1]
        return match[0]
    result = re.sub(r'\[([^\]]*)\]\(([^)]+)\)', substitute, body)
    updated = dict(meta)
    identifier = read_doc(target)[0]['id']
    for field in ('origin_thread', 'source_thread', 'thread_id'):
        if updated.get(field) == identifier:
            updated.pop(field)
            count += 1
    if isinstance(updated.get('thread_ids'), list) and identifier in updated['thread_ids']:
        updated['thread_ids'] = [value for value in updated['thread_ids'] if value != identifier]
        count += 1
    if path.name == 'project_overview.md' and updated.get('active_thread') == identifier:
        updated['active_thread'] = ''
        count += 1
    # Remove the generated directory row, preserving manual prose outside managed blocks.
    for block_name in ('navigation',):
        if f'<!-- rs:{block_name}:start -->' in body:
            block = section(body, block_name)
            block = '\n'.join(line for line in block.splitlines() if target.name not in line)
            result = replace_section(result, block_name, block)
    return doc_text(updated, result), count


def deletion_preview(project, identifier):
    target, _, _ = project.thread(identifier)
    files = research_files(project)
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(project.root).as_posix().encode())
        digest.update(path.read_bytes())
    digest.update((project.root / '.rs/config.json').read_bytes())
    return {'id': identifier, 'path': target.relative_to(project.root).as_posix(), 'references': incoming(project, target), 'token': digest.hexdigest(),
            'confirm': f'rsagent thread delete {identifier} --confirm {digest.hexdigest()}'}


def delete_thread(project, identifier, token):
    preview = deletion_preview(project, identifier)
    if token != preview['token']:
        raise Error('stale deletion preview; preview again before confirming')
    target, _, _ = project.thread(identifier)
    # Preserve high-water allocation even if the project has manually added records.
    config = project.config()
    water = config.setdefault('high_water', {})
    water['thread'] = max(int(water.get('thread', 0)), int(identifier))
    atomic_write(project.root / '.rs/config.json', json.dumps(config, indent=2) + '\n')
    changes = {}
    for path in research_files(project):
        if path == target:
            changes[path] = None
            continue
        meta, body = read_doc(path)
        cleaned, count = clean_references(project, path, target, meta, body)
        if count:
            changes[path] = cleaned
    project.transaction(changes)
    project.refresh_navigation()
    from .indexing import invalidate
    try:
        invalidate(project.root, target)
        indexing = 'removed from retrieval'
    except Exception as exc:
        indexing = f'Markdown deleted; retrieval invalidation pending: {exc}'
    return {'deleted': identifier, 'indexing': indexing, 'unresolved': [item for item in preview['references'] if item['ambiguous']]}
