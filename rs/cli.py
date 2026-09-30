"""Compact deterministic shell commands; conversation synthesis lives in skills."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from .storage import Project, Error, read_doc, section, BRIEF_LIMIT, RESUME_LIMIT, RESUME_FIELDS, research_files


def parser():
    cli = argparse.ArgumentParser(prog='rsagent', description=__doc__)
    cli.add_argument('--project', help='Explicit research project root')
    cli.add_argument('--json', action='store_true', help='Machine-readable output (also accepted after subcommands)')
    commands = cli.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    threads = commands.add_parser('threads')
    threads.add_argument('--all', action='store_true')
    threads.add_argument('--kw')
    thread = commands.add_parser('thread').add_subparsers(dest='operation', required=True)
    create = thread.add_parser('create'); create.add_argument('title')
    select = thread.add_parser('select'); select.add_argument('id')
    for name in ('state', 'status'):
        state = thread.add_parser(name); state.add_argument('id'); state.add_argument('state', choices=['open', 'closed', 'obsolete'])
    delete = thread.add_parser('delete'); delete.add_argument('id'); delete.add_argument('--confirm', metavar='PREVIEW_TOKEN')
    todo = commands.add_parser('todo')
    todo.add_argument('text', nargs='?')
    options = todo.add_mutually_exclusive_group()
    options.add_argument('--next', action='store_true')
    options.add_argument('--done'); options.add_argument('--delete'); options.add_argument('--start')
    kw = commands.add_parser('keywords'); kw.add_argument('labels', nargs='?'); kw.add_argument('--global', dest='global_', action='store_true'); kw.add_argument('--paper')
    papers = commands.add_parser('paper').add_subparsers(dest='operation', required=True)
    add = papers.add_parser('add'); add.add_argument('input'); metadata_options(add)
    listing = papers.add_parser('list'); listing.add_argument('--kw')
    for name in ('discuss', 'show'): papers.add_parser(name).add_argument('ref')
    summary = papers.add_parser('summary'); summary.add_argument('ref'); summary.add_argument('--file', help='read the summary from FILE (default: standard input)')
    sources = commands.add_parser('source').add_subparsers(dest='operation', required=True)
    add = sources.add_parser('add'); add.add_argument('input'); add.add_argument('--type', required=True, choices=['repo', 'tool', 'web']); metadata_options(add)
    listing = sources.add_parser('list'); listing.add_argument('--kw')
    commands.add_parser('validate')
    commands.add_parser('checkpoint', help='Validate already-written checkpoint and enqueue derived updates; never summarizes chat')
    commands.add_parser('bibliography')
    index = commands.add_parser('index').add_subparsers(dest='operation', required=True)
    index.add_parser('status')
    sync = index.add_parser('flush'); sync.add_argument('--lexical-only', action='store_true')
    index.add_parser('worker')
    search = commands.add_parser('search'); search.add_argument('query'); search.add_argument('--hybrid', action='store_true'); search.add_argument('--semantic', action='store_true'); search.add_argument('--limit', type=int, default=5)
    return cli


def metadata_options(command):
    command.add_argument('--title'); command.add_argument('--organization'); command.add_argument('--year')


def run(args, project):
    if args.command == 'status':
        return project.status()
    if args.command == 'threads':
        return project.threads(args.all, normalize(args.kw))
    if args.command == 'thread':
        with project.lock():
            if args.operation == 'create': return project.create_thread(args.title)
            if args.operation == 'select': return project.select(args.id)
            if args.operation in ('state', 'status'): return project.set_status(args.id, args.state)
            from .storage import deletion_preview, delete_thread
            return delete_thread(project, args.id, args.confirm) if args.confirm else deletion_preview(project, args.id)
    if args.command == 'todo':
        if args.text and any((args.next, args.done, args.delete, args.start)):
            raise Error('TODO text cannot be combined with selection/removal/promotion options')
        if args.text or args.done or args.delete or args.start:
            with project.lock():
                if args.text: return project.add_todo(args.text)
                if args.start: return project.promote(args.start)
                return project.remove_todo(args.done or args.delete)
        items = project.todos()
        return (items[0] if items else None) if args.next else items
    if args.command == 'keywords':
        if args.global_:
            if args.labels or args.paper: raise Error('--global cannot assign or target keywords')
            return project.vocabulary()
        if args.labels is not None:
            with project.lock(): return project.keywords(args.labels, args.paper)
        return project.keywords(key=args.paper)
    if args.command in ('paper', 'source'):
        from .sources import register, list_sources, discuss, show_summary, set_summary
        if args.operation == 'discuss': return discuss(project, args.ref)
        if args.operation == 'show': return show_summary(project, args.ref)
        if args.operation == 'summary':
            return set_summary(project, args.ref, Path(args.file).read_text() if args.file else sys.stdin.read())
        if args.operation == 'add':
            return register(project, args.input, type='paper' if args.command == 'paper' else args.type,
                            title=args.title, organization=args.organization, year=args.year)
        return list_sources(project, papers_only=args.command == 'paper', keyword=normalize(args.kw))
    if args.command in ('validate', 'checkpoint'):
        from .sources import validate, bibliography
        with project.lock():
            diagnostics = validate(project)
            if args.command == 'validate':
                return {'valid': not diagnostics, 'diagnostics': diagnostics}
            # Validate before reporting a checkpoint complete; oversized sections are not silently shortened.
            _, overview = read_doc(project.root / 'project_overview.md')
            config = project.config()
            if len(section(overview, 'brief')) > config.get('brief_limit', BRIEF_LIMIT): diagnostics.append('project brief exceeds bounded size; edit it before completing checkpoint')
            for path in project.notes('thread'):
                _, body = read_doc(path)
                resume = section(body, 'resume')
                if len(resume) > config.get('resume_limit', RESUME_LIMIT): diagnostics.append(f'{path.name}: resume exceeds bounded size')
                for field in RESUME_FIELDS:
                    if f'### {field}' not in resume: diagnostics.append(f'{path.name}: missing resume field {field}')
            if diagnostics:
                raise Error('checkpoint incomplete: ' + '; '.join(diagnostics))
            bibliography(project)
            project.refresh_navigation()
            project.enqueue(research_files(project))
            return {'checkpoint': 'saved Markdown validated; bibliography/navigation refreshed; indexing queued', 'active_thread': read_doc(project.root / 'project_overview.md')[0].get('active_thread', '')}
    if args.command == 'bibliography':
        from .sources import bibliography
        with project.lock(): bibliography(project)
        return {'bibliography': 'refs.bib'}
    if args.command == 'index':
        from . import indexing
        if args.operation == 'status': return indexing.state(project.root)
        if args.operation == 'worker': return indexing.worker(project.root)
        # Explicit flush picks up manual edits as well as retrying persisted tasks.
        indexing.enqueue(project.root, research_files(project))
        return indexing.flush(project.root, semantic=not args.lexical_only)
    if args.command == 'search':
        from .indexing import search
        return search(project.root, args.query, mode='hybrid' if args.hybrid else ('semantic' if args.semantic else 'keyword'), limit=args.limit)
    raise Error('unknown command')


def normalize(value):
    return value.strip().lower() if value else None


def display(value):
    if value is None:
        return 'No items.'
    if isinstance(value, list):
        if not value: return 'No items.'
        return '\n'.join(display(item) for item in value)
    if isinstance(value, dict):
        if 'brief' in value:
            text = value['brief']['text']
            if 'thread' in value:
                item = value['thread']
                text += f"\n\nActive {item['id']}: {item['title']} ({item['path']})\n" + item['resume']['text']
            else: text += '\n\nNo active thread.'
            state = value['indexing']
            text += '\n\nPointers: rsagent threads; TODO.md; project_overview.md'
            if state.get('lexical_pending') or state.get('semantic_pending'): text += '\nIndexing pending (saved Markdown is current).'
            for stage in ('lexical', 'semantic'):
                if state.get(stage + '_error'): text += f"\n{stage} indexing failed: {state[stage + '_error']}; retry rsagent index flush"
            return text
        if 'id' in value and 'title' in value:
            return f"{value['id']} [{value.get('status', '')}] {value['title']} — {value.get('path', '')}"
        if 'id' in value and 'text' in value:
            return f"{value['id']}: {value['text']}" + (f" (from {value['origin']})" if value.get('origin') else '')
        if 'summary' in value:
            return value['summary'] if value['summary'] is not None else f"{value['key']}: {value['message']}"
        if 'key' in value:
            return f"{value['key']} {value.get('title') or ''} — {value.get('path', '')}" + (' (existing)' if value.get('duplicate') else '') + (f"; incomplete: {', '.join(value['missing_fields'])}" if value.get('missing_fields') else '')
        if 'token' in value:
            return f"Delete preview: {value['path']}\nReferences: {json.dumps(value['references'], ensure_ascii=False)}\nConfirm: {value['confirm']}"
        return '\n'.join(f'{key}: {json.dumps(item, ensure_ascii=False) if isinstance(item, (list, dict)) else item}' for key, item in value.items())
    return str(value)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Permit --json anywhere while keeping an uncomplicated command grammar.
    machine = '--json' in argv
    argv = [item for item in argv if item != '--json']
    args = parser().parse_args(argv)
    try:
        project = Project(args.project) if args.project else Project.discover()
        result = run(args, project)
        print(json.dumps(result, ensure_ascii=False) if machine else display(result))
        return 1 if args.command == 'validate' and not result['valid'] else 0
    except (Error, ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}) if machine else f'rsagent: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
