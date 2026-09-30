"""Source registration and derived references; network work precedes mutations."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import subprocess
from datetime import date
from urllib.parse import urlsplit, urlunsplit, unquote, quote
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import yaml

from .storage import read_doc, write_doc, atomic_write, StringDumper, RESUME_FIELDS, section, normalize_key, key_order, doc_text, research_files


def fetch(url: str) -> bytes:
    """Small replaceable network boundary used by metadata fixtures."""
    try:
        with urlopen(Request(url, headers={'User-Agent': 'research-rs/0.1', 'Accept': 'application/json, application/atom+xml, text/html'}), timeout=20) as response:
            return response.read(4 * 1024 * 1024)
    except Exception as exc:
        raise ValueError(f'Metadata fetch failed for {url}: {exc}') from exc


def normalize_url(value: str) -> str:
    bits = urlsplit(value.strip())
    if bits.scheme not in ('http', 'https') or not bits.netloc:
        raise ValueError('Expected an HTTP(S) URL or supported paper identifier/local file')
    return urlunsplit((bits.scheme.lower(), bits.netloc.lower(), bits.path.rstrip('/'), bits.query, ''))


def _doi(value):
    value = re.sub(r'^(?:doi:|https?://(?:dx\.)?doi\.org/)', '', value.strip(), flags=re.I)
    return value.lower() if re.fullmatch(r'10\.\d{4,9}/\S+', value, re.I) else None


def _arxiv(value):
    match = re.fullmatch(r'(?:arxiv:|https?://arxiv\.org/(?:abs|pdf)/)?((?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7}))(?:v\d+)?(?:\.pdf)?', value.strip(), re.I)
    return match.group(1).lower() if match else None


def _metadata(value, kind):
    doi, arxiv = _doi(value), _arxiv(value)
    if doi:
        payload = json.loads(fetch('https://api.crossref.org/works/' + quote(doi, safe='')))
        data = payload['message']
        dates = data.get('published', data.get('issued', {})).get('date-parts', [[]])
        return {'doi': doi, 'url': 'https://doi.org/' + doi, 'title': (data.get('title') or [None])[0],
                'authors': [' '.join(filter(None, [a.get('given'), a.get('family')])) for a in data.get('author', [])],
                'year': str(dates[0][0]) if dates and dates[0] else None,
                'journal': (data.get('container-title') or [None])[0], 'bib_type': 'article'}
    if arxiv:
        root = ET.fromstring(fetch('https://export.arxiv.org/api/query?id_list=' + quote(arxiv, safe='')))
        ns = {'a': 'http://www.w3.org/2005/Atom'}
        entry = root.find('a:entry', ns)
        if entry is None or entry.findtext('a:title', '', ns).lower() == 'error':
            raise ValueError(f'arXiv returned no paper for {arxiv}')
        return {'arxiv': arxiv, 'url': 'https://arxiv.org/abs/' + arxiv,
                'title': ' '.join(entry.findtext('a:title', '', ns).split()) or None,
                'authors': [a.findtext('a:name', '', ns) for a in entry.findall('a:author', ns)],
                'year': entry.findtext('a:published', '', ns)[:4] or None, 'bib_type': 'article'}
    url = normalize_url(value)
    bits = urlsplit(url)
    match = re.fullmatch(r'/([^/]+)/([^/]+)', bits.path)
    if bits.netloc in ('github.com', 'www.github.com') and match:
        owner, repo = match.groups()
        repo = repo.removesuffix('.git')
        data = json.loads(fetch(f'https://api.github.com/repos/{quote(owner)}/{quote(repo)}'))
        return {'title': data.get('name'), 'organization': data.get('owner', {}).get('login'),
                'url': normalize_url(data.get('html_url', f'https://github.com/{owner}/{repo}')),
                'description': data.get('description'), 'year': None, 'authors': [], 'bib_type': 'software' if kind in ('repo', 'tool') else 'misc'}
    # Generic pages require no fetch: a URL establishes identity, not a publication date/title.
    return {'url': url, 'title': None, 'authors': [], 'year': None, 'bib_type': 'misc'}


def parse_bibtex(text):
    """Parse entries with nested braced/quoted fields; reject unsupported macros."""
    entries, i = [], 0
    def skip(pos):
        while pos < len(text):
            if text[pos].isspace() or text[pos] == ',': pos += 1
            elif text[pos] == '%':
                end = text.find('\n', pos); pos = len(text) if end < 0 else end + 1
            else: break
        return pos
    def enclosed(pos, opener, closer):
        start, depth, escaped = pos + 1, 1, False
        pos += 1
        while pos < len(text):
            ch = text[pos]
            if escaped: escaped = False
            elif ch == '\\': escaped = True
            elif ch == opener and opener != closer: depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0: return text[start:pos], pos + 1
            pos += 1
        raise ValueError('Unclosed BibTeX field or entry')
    while True:
        i = skip(i)
        if i == len(text): break
        match = re.match(r'@([A-Za-z]+)\s*([({])', text[i:])
        if not match: raise ValueError('Malformed BibTeX: expected an entry')
        typ, opener = match.groups(); i += match.end() - 1
        block, i = enclosed(i, opener, '}' if opener == '{' else ')')
        if typ.lower() in ('comment', 'preamble'): continue
        if typ.lower() == 'string': raise ValueError('BibTeX string macros are unsupported; expand them before import')
        comma = block.find(',')
        if comma < 1: raise ValueError('BibTeX entry is missing its key or fields')
        original, fields, pos = block[:comma].strip(), {}, comma + 1
        # Reuse the balanced scanner for a field-local buffer.
        original_text = text; text = block
        try:
            while True:
                pos = skip(pos)
                if pos == len(block): break
                field = re.match(r'([A-Za-z][\w-]*)\s*=\s*', block[pos:])
                if not field: raise ValueError(f'Malformed BibTeX fields in {original}')
                name = field.group(1).lower(); pos += field.end()
                if pos >= len(block): raise ValueError('Missing BibTeX value')
                if block[pos] == '{': val, pos = enclosed(pos, '{', '}')
                elif block[pos] == '"': val, pos = enclosed(pos, '"', '"')
                else:
                    literal = re.match(r'\d+', block[pos:])
                    if not literal: raise ValueError('Unsupported BibTeX macro/value; expand it before import')
                    val = literal.group(); pos += literal.end()
                if name in fields: raise ValueError(f'Duplicate BibTeX field {name}')
                fields[name] = val
                if pos < len(block) and block[pos] not in ', \n\r\t': raise ValueError('BibTeX field concatenation is unsupported; expand it before import')
        finally: text = original_text
        fields = {k: (re.sub(r'[{}]', '', v) if k in ('title', 'author', 'journal', 'booktitle') else v) for k, v in fields.items()}
        if not fields.get('title'): raise ValueError(f'BibTeX entry {original} has no title')
        entries.append({'title': fields.get('title'), 'authors': fields.get('author', '').split(' and ') if fields.get('author') else [],
                        'year': fields.get('year'), 'doi': _doi(fields['doi']) if fields.get('doi') else None,
                        'url': normalize_url(fields['url']) if fields.get('url') else None,
                        'journal': fields.get('journal'), 'booktitle': fields.get('booktitle'),
                        'bib_type': typ.lower(), 'imported_key': original})
    if not entries: raise ValueError('No bibliographic entries found')
    return entries


def list_sources(project, papers_only=False, keyword=None):
    rows = []
    for folder in ('papers',) if papers_only else ('papers', 'sources'):
        for path in sorted((project.root / folder).glob('*.md')):
            metadata, _ = read_doc(path)
            if keyword and keyword not in metadata.get('tags', []): continue
            rows.append({**metadata, 'path': str(path.relative_to(project.root))})
    return sorted(rows, key=lambda row: key_order(row['key']))


def _identities(meta):
    names = ('doi', 'arxiv', 'url', 'entry_hash') if meta.get('entry_hash') else ('doi', 'arxiv', 'url', 'file_hash')
    return {f'{name}:{meta[name]}' for name in names if meta.get(name)}


def _unique(directory, stem, suffix):
    path = directory / (stem + suffix); index = 2
    while path.exists():
        path = directory / f'{stem}_{index}{suffix}'; index += 1
    return path


def _slug(title):
    return re.sub(r'[^\w-]+', '_', (title or 'untitled').lower(), flags=re.UNICODE).strip('_')[:90] or 'untitled'


def _pdf_metadata(path):
    # Use an installed document tool when present; never parse the PDF ourselves.
    metadata = {'title': None, 'authors': [], 'year': None, 'bib_type': 'misc'}
    executable = shutil.which('pdfinfo')
    if not executable:
        metadata['metadata_note'] = 'PDF metadata extraction unavailable; supply verified fields in this note.'
        return metadata
    try:
        process = subprocess.run([executable, str(path)], capture_output=True, text=True, timeout=15)
        if process.returncode:
            metadata['metadata_note'] = 'Optional PDF metadata extraction failed; supply verified fields in this note.'
            return metadata
        fields = dict(line.split(':', 1) for line in process.stdout.splitlines() if ':' in line)
        metadata['title'] = fields.get('Title', '').strip() or None
        author = fields.get('Author', '').strip()
        metadata['authors'] = [author] if author else []
        # CreationDate is a file date, not a verified publication year.
        metadata['metadata_note'] = 'Embedded PDF metadata is unverified; publication year remains unknown.'
    except (OSError, subprocess.TimeoutExpired):
        metadata['metadata_note'] = 'Optional PDF metadata extraction failed; supply verified fields in this note.'
    return metadata


SUMMARY_START, SUMMARY_END = '<!-- rs:summary:start -->', '<!-- rs:summary:end -->'
SUMMARY_PLACEHOLDER = SUMMARY_START + '\n## Summary\n\n_Not discussed yet._\n' + SUMMARY_END + '\n'


def register(project, value, type='paper', title=None, organization=None, year=None):
    if type not in ('paper', 'repo', 'tool', 'web'): raise ValueError('Unknown source type')
    value = str(value)
    local = Path(value).expanduser()
    local = local if local.is_absolute() else Path.cwd() / local
    is_local = local.is_file()
    file_hash = None
    if is_local:
        if local.suffix.lower() not in ('.pdf', '.bib'): raise ValueError('Only local PDF and BibTeX imports are supported')
        file_hash = hashlib.sha256(local.read_bytes()).hexdigest()
        if local.suffix.lower() == '.bib':
            staged = parse_bibtex(local.read_text(encoding='utf-8'))
            for meta in staged:
                meta['entry_hash'] = hashlib.sha256(json.dumps(meta, sort_keys=True).encode()).hexdigest()
        else:
            staged = [_pdf_metadata(local)]
            staged[0]['file_hash'] = file_hash
    else:
        identities = {'doi': _doi(value), 'arxiv': _arxiv(value)}
        if not any(identities.values()): identities['url'] = normalize_url(value)
        with project.lock():
            duplicate = next((row for row in list_sources(project) if _identities(row) & _identities(identities)), None)
            if duplicate:
                return [{'key': duplicate['key'], 'path': duplicate['path'], 'duplicate': True}]
        try: staged = [_metadata(value, type)]
        except ValueError: raise
        except Exception as exc: raise ValueError(f'Invalid metadata response for {value}: {exc}') from exc
    for meta in staged:
        meta.update({'type': type, 'tags': [], 'accessed': date.today().isoformat()})
        for field, override in (('title', title), ('organization', organization), ('year', year)):
            if override is not None: meta[field] = str(override)
        for field in ('title', 'year', 'organization', 'url', 'doi', 'arxiv'):
            if meta.get(field) is not None and not isinstance(meta[field], str):
                raise ValueError(f'Invalid metadata: {field} must be a string or null')
        if not isinstance(meta.get('authors', []), list) or any(not isinstance(author, str) for author in meta.get('authors', [])):
            raise ValueError('Invalid metadata: authors must be a list of strings')
        meta['missing_fields'] = [f for f in ('title', 'authors', 'year') if not meta.get(f)]
    result = []
    with project.lock():
        existing = list_sources(project)
        copied = None
        changes = {}
        for meta in staged:
            duplicate = next((row for row in existing if _identities(row) & _identities(meta)), None)
            if duplicate:
                result.append({'key': duplicate['key'], 'path': duplicate['path'], 'duplicate': True}); continue
            key = project.allocate('paper_x' if type == 'paper' else 'source')
            meta['key'] = key
            directory = project.root / ('papers' if type == 'paper' else 'sources')
            directory.mkdir(parents=True, exist_ok=True)
            if is_local and copied is None:
                files = project.root / 'papers' / 'files'; files.mkdir(parents=True, exist_ok=True)
                copied = _unique(files, _slug(local.stem), local.suffix.lower())
                fd, temp = tempfile.mkstemp(dir=files); os.close(fd)
                try: shutil.copyfile(local, temp); os.replace(temp, copied)
                finally:
                    if os.path.exists(temp): os.unlink(temp)
            if copied:
                meta['local_file'] = os.path.relpath(copied, directory)
                if local.suffix.lower() == '.bib': meta['file_hash'] = file_hash
            stem = _slug(meta.get('title') or local.stem if is_local else meta.get('title'))
            path = _unique(directory, f'{key}_{stem}' if type == 'paper' else stem, '.md')
            body = f"# {meta.get('title') or 'Untitled source (metadata incomplete)'}\n\n"
            if meta['missing_fields']: body += 'Metadata incomplete: ' + ', '.join(meta['missing_fields']) + '.\n\n'
            if copied: body += f"[Imported file]({meta['local_file']})\n\n"
            body += SUMMARY_PLACEHOLDER if type == 'paper' else '## Reading notes\n\n## Evidence and locations\n\n## Limitations\n'
            while path in changes:
                path = path.with_name(path.stem + '_2' + path.suffix)
            changes[path] = '---\n' + yaml.dump(meta, Dumper=StringDumper, sort_keys=False, allow_unicode=True).rstrip() + '\n---\n' + body
            row = {**meta, 'path': str(path.relative_to(project.root))}; existing.append(row)
            result.append({'key': key, 'path': row['path'], 'duplicate': False, 'missing_fields': meta['missing_fields'], 'metadata_note': meta.get('metadata_note')})
        if changes:
            changes[project.root / 'refs.bib'] = _render_bib(existing)
            project.transaction(changes)
        project.refresh_navigation()
        project.enqueue([project.root / row['path'] for row in result] + [project.root / 'refs.bib'])
    return result


def _escape(value):
    replacements = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    return ''.join(replacements.get(char, char) for char in str(value)).replace('\n', ' ')


def _render_bib(rows):
    chunks = ['% Generated by rs from authoritative source notes. Do not edit.\n']
    allowed_types = {'article', 'book', 'inproceedings', 'proceedings', 'incollection', 'phdthesis', 'mastersthesis', 'techreport', 'unpublished', 'misc', 'software'}
    for row in sorted(rows, key=lambda row: key_order(row['key'])):
        typ = row.get('bib_type') or ('software' if row.get('type') in ('repo', 'tool') else 'misc')
        if typ not in allowed_types: typ = 'misc'
        fields = {name: row.get(name) for name in ('title', 'year', 'journal', 'booktitle', 'organization', 'doi', 'url')}
        if row.get('authors'): fields['author'] = ' and '.join(row['authors'])
        if row.get('arxiv'): fields.update({'eprint': row['arxiv'], 'archivePrefix': 'arXiv'})
        if row.get('accessed'): fields['note'] = 'Accessed ' + row['accessed']
        lines = [f'@{typ}{{{row["key"]},']
        lines += [f'  {name} = {{{_escape(value)}}},' for name, value in fields.items() if value is not None and value != '']
        lines += ['}\n']; chunks.append('\n'.join(lines))
    rendered = '\n'.join(chunks)
    return rendered


def bibliography(project):
    rendered = _render_bib(list_sources(project))
    atomic_write(project.root / 'refs.bib', rendered)
    return rendered


def _without_fences(body):
    body = re.sub(r'(?m)^\s*(`{3,}|~{3,})[^\n]*\n[\s\S]*?^\s*\1\s*$', '', body)
    return re.sub(r'`[^`\n]*`', '', body)


def validate(project):
    errors, known_keys, known_threads, records = [], set(), {}, []
    paths = [p for p in project.root.rglob('*.md') if not any(part.startswith('.') for part in p.relative_to(project.root).parts) and p.name not in ('AGENTS.md', 'README.md')]
    for path in paths:
        relative = str(path.relative_to(project.root))
        try: meta, body = read_doc(path)
        except (ValueError, yaml.YAMLError) as exc:
            errors.append(f'{relative}: {exc}'); continue
        records.append((path, meta, body))
        if path.parent.name in ('papers', 'sources'):
            key = meta.get('key')
            pattern, shape = (r'x?\d{4,}', 'a number such as 0002, or x0003 if undiscussed') if path.parent.name == 'papers' else (r's\d{4,}', 's followed by at least four digits')
            if not isinstance(key, str) or not re.fullmatch(pattern, key): errors.append(f'{relative}: key must be a quoted string: {shape}')
            elif path.parent.name == 'papers' and not path.name.startswith(key + '_'): errors.append(f'{relative}: file name must start with {key}_')
            elif key in known_keys: errors.append(f'{relative}: duplicate citation key {key}')
            else: known_keys.add(key)
        if path.parent.name == 'threads' and isinstance(meta.get('id'), str): known_threads[meta['id']] = (path, meta, body)
    try:
        vocabulary = set(project.vocabulary())
    except (ValueError, OSError) as exc:
        errors.append(f'keywords.yaml: {exc}'); vocabulary = set()
    for path, meta, body in records:
        relative = str(path.relative_to(project.root)); clean = _without_fences(body)
        tags = meta.get('tags', [])
        if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags): errors.append(f'{relative}: tags must be a list of strings')
        else:
            for tag in tags:
                if tag not in vocabulary: errors.append(f'{relative}: unknown keyword {tag}')
        for match in re.finditer(r'\\cite\w*\s*\{([^}]+)\}', clean):
            for key in match.group(1).split(','):
                if key.strip() not in known_keys: errors.append(f'{relative}: missing citation key {key.strip()}')
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', clean):
            target = target.split('#', 1)[0].split(' "', 1)[0]
            if not target or urlsplit(target).scheme or target.startswith('//'): continue
            resolved = project.root / unquote(target.lstrip('/')) if target.startswith('/') else path.parent / unquote(target)
            if resolved.suffix == '.md' and not resolved.exists(): errors.append(f'{relative}: missing document link {target}')
        if path.name == 'project_overview.md':
            active = meta.get('active_thread')
            if active not in ('', None):
                if not isinstance(active, str): errors.append(f'{relative}: active_thread must be a quoted string')
                elif active not in known_threads: errors.append(f'{relative}: missing active thread {active}')
                elif known_threads[active][1].get('status') != 'open': errors.append(f'{relative}: active thread {active} is not open')
        if path.parent.name in ('papers', 'sources'):
            if 'authors' in meta and (not isinstance(meta['authors'], list) or any(not isinstance(author, str) for author in meta['authors'])):
                errors.append(f'{relative}: authors must be a list of strings')
            for field in ('year', 'doi', 'arxiv', 'url', 'organization'):
                if meta.get(field) is not None and not isinstance(meta[field], str): errors.append(f'{relative}: {field} must be a string or null')
        if path.parent.name == 'threads':
            try:
                resume = section(body, 'resume')
                for field in RESUME_FIELDS:
                    if not re.search(r'^###\s+' + re.escape(field) + r'\s*$', resume, re.M | re.I): errors.append(f'{relative}: missing resume field {field}')
            except ValueError as exc: errors.append(f'{relative}: {exc}')
            if not isinstance(meta.get('id'), str): errors.append(f'{relative}: thread id must be a quoted string')
            if meta.get('status') not in ('open', 'closed', 'obsolete'): errors.append(f'{relative}: invalid thread status')
            if not re.search(r'^##\s+(?:Compact )?Resume\s*$', body, re.M | re.I): errors.append(f'{relative}: missing Resume section')
            if not re.search(r'^##\s+Research record\s*$', body, re.M | re.I): errors.append(f'{relative}: missing Research record section')
    return errors


def _code_aware(text, transform):
    """Apply transform to prose only, leaving fenced and inline code untouched."""
    code = re.compile(r'(?m)^\s*(`{3,}|~{3,})[^\n]*\n[\s\S]*?^\s*\1\s*$|`[^`\n]*`')
    result, position = [], 0
    for match in code.finditer(text):
        result += [transform(text[position:match.start()]), match.group()]
        position = match.end()
    return ''.join(result) + transform(text[position:])


def _rekey(project, moves):
    """Rename notes and rewrite references for {old_key: new_key}, as one transaction."""
    rows = {row['key']: row for row in list_sources(project)}
    changes, names = {}, {}
    for old, new in moves.items():
        row = rows[old]
        source = project.root / row['path']
        meta, body = read_doc(source)
        meta['key'] = new
        target = source
        if source.parent.name == 'papers':
            target = source.with_name(new + (source.name[len(old):] if source.name.startswith(old + '_') else '_' + source.name))
            if target.exists():
                raise ValueError(f'{target.name} already exists')
            names[source.name] = target.name
            changes[source] = None
        changes[target] = doc_text(meta, body)
        row.update(meta, path=str(target.relative_to(project.root)))
    cites = re.compile(r'(\\cite\w*\s*\{)([^}]+)(\})')
    swap = lambda match: match.group(1) + ','.join(moves.get(k.strip(), k.strip()) for k in match.group(2).split(',')) + match.group(3)
    def transform(text):
        text = cites.sub(swap, text)
        for old_name, new_name in names.items():
            text = text.replace(old_name, new_name)
        return text
    skipped = {'README.md', 'AGENTS.md', 'RESEARCH_WORKFLOW.md'}
    for path in research_files(project):
        if path in changes or path.name in skipped and path.parent == project.root or path.parent.name == 'files':
            continue
        text = path.read_text()
        updated = _code_aware(text, transform)
        if updated != text:
            changes[path] = updated
    changes[project.root / 'refs.bib'] = _render_bib(list(rows.values()))
    project.transaction(changes)
    project.refresh_navigation()
    project.enqueue([path for path, value in changes.items() if value is not None])


def _find(project, ref):
    key = normalize_key(ref)
    row = next((row for row in list_sources(project) if row['key'] == key), None)
    if not row:
        undiscussed = next((r for r in list_sources(project) if r['key'] == 'x' + key), None) if key[:1].isdigit() else None
        hint = f"; the undiscussed paper with that number is x{key}" if undiscussed else ''
        raise ValueError(f'no registered paper or source numbered {key}{hint}')
    return row


def discuss(project, ref):
    """Give an undiscussed (x-prefixed) paper its permanent discussion number; idempotent."""
    with project.lock():
        row = _find(project, ref)
        if row.get('type') != 'paper':
            raise ValueError(f"{row['key']} is not a paper")
        if not row['key'].startswith('x'):
            return {'key': row['key'], 'path': row['path'], 'duplicate': True}
        new = project.allocate('discussed')
        _rekey(project, {row['key']: new})
        return {'key': new, 'path': _find(project, new)['path'], 'previous': row['key']}


def show_summary(project, ref):
    row = _find(project, ref)
    _, body = read_doc(project.root / row['path'])
    if SUMMARY_START not in body or SUMMARY_END not in body:
        return {'key': row['key'], 'path': row['path'], 'summary': None, 'message': 'note has no summary block'}
    block = body[body.index(SUMMARY_START) + len(SUMMARY_START):body.index(SUMMARY_END)].strip()
    return {'key': row['key'], 'path': row['path'], 'summary': block}


def set_summary(project, ref, text):
    """Replace (or insert, after the title) the managed summary block of a paper note."""
    text = text.strip()
    if not text:
        raise ValueError('summary text is empty')
    if not text.startswith('## Summary'):
        text = '## Summary\n\n' + text
    block = f'{SUMMARY_START}\n{text}\n{SUMMARY_END}\n'
    with project.lock():
        row = _find(project, ref)
        path = project.root / row['path']
        meta, body = read_doc(path)
        if SUMMARY_START in body and SUMMARY_END in body:
            start, stop = body.index(SUMMARY_START), body.index(SUMMARY_END) + len(SUMMARY_END)
            body = body[:start] + block.rstrip('\n') + body[stop:]
        else:
            heading = re.match(r'(?:\s*# [^\n]*\n)?', body)
            body = body[:heading.end()] + '\n' * (heading.end() > 0) + block + '\n' + body[heading.end():].lstrip('\n')
        project.transaction({path: doc_text(meta, body)})
        project.enqueue([path])
    return {'key': row['key'], 'path': row['path']}
