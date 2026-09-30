# Research threads with rsagent

`rsagent` keeps one research question in focus across Codex CLI and Claude Code chats. Markdown contains the authoritative research; the CLI handles bookkeeping without model inference. Project-local skills preserve evidence, reasoning, rejected alternatives and a compact resume. GNO finds earlier arguments; Docsify presents the documents.

## Install once

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/). Run from this checkout:

```bash
# 1. Install the rsagent command (isolated environment; PyYAML is pulled in automatically)
uv tool install .

# 2. Make sure uv's tool directory is on PATH (then restart your shell)
uv tool update-shell

# 3. Check it
which rsagent && rsagent --help

# 4. Install GNO (search backend, external to Python) and check it
bun install -g @gmickel/gno   # or follow https://gno.sh/docs/cli
gno --version                 # integration baseline: 1.5.1

# 5. Optional: PDF metadata extraction (macOS)
brew install poppler

# 6. Optional, development only: run the tests
uv run --with pytest python -m pytest -q
```

After editing the source, reinstall with `uv tool install --reinstall .`. Download GNO's embedding/query models as described in the GNO docs (`gno models --help`).

### Supported hosts

| Host | Requirement | Observed |
| --- | --- | --- |
| Codex CLI | Project-local `.agents/skills` discovery | 0.159.2 |
| Claude Code | >= 2.1.281 (loads shared `AGENTS.md` directly) | 2.1.284 |

Host documentation: [Codex skills](https://learn.chatgpt.com/docs/build-skills), [Claude skills](https://code.claude.com/docs/en/skills), [Claude memory](https://code.claude.com/docs/en/memory#agentsmd). Version and help checks are separate from live, authenticated agent-session verification.

## Install a research project

Run these from the toolkit source checkout, targeting a separate research directory:

```bash
uv run python scripts/install_project.py  --engine codex --project /path/to/research
uv run python scripts/install_project.py  --engine claude --project /path/to/research
```

Run both to share the same research records between clients.

- The installer creates missing files, installs only the chosen engine's skills, preserves user settings and research, and reports modified installed-file conflicts rather than overwriting them.
- Managed instruction and navigation blocks preserve surrounding prose. Rerunning is safe.
- `--skip-gno` is for offline tests only; research installations require GNO. Reinstall without that flag before using retrieval.

### Start a session

```bash
cd /path/to/research
codex    # Codex
claude   # Claude Code
```

Nothing else is needed. The installer configures the project for you:

- **Codex:** reads `AGENTS.md` and `.agents/skills` natively, and its `!` shell does not trigger a model reply, so no settings are written.
- **Claude Code:** the installer merges two settings into the project's `.claude/settings.json` (creating it if missing, keeping every other key): `respondToBashCommands: false`, so `!rsagent ...` output gets no automatic model reply, and the built-in `agents-md` plugin with `instructionFiles: claude-md-and-agents-md`, so `AGENTS.md` loads.
- **If your `.claude/settings.json` already sets one of those keys differently, or is not valid JSON,** it is left untouched, the installer says so, and you launch with `claude --settings .rs/claude-settings.json` instead (that file is always generated).
- An ancestor `CLAUDE.md` / `CLAUDE.local.md` can suppress `AGENTS.md`; the installer reports them. Confirm `AGENTS.md` appears under Claude `/memory`. Managed host policies may override project settings.

See [Claude instructions precedence](https://code.claude.com/docs/en/memory#choose-which-instruction-files-load) and [shell mode](https://code.claude.com/docs/en/interactive-mode#shell-mode-with-prefix).

## Work in one thread

Start with `!rsagent status`, or invoke `$rs-research` in Codex and `/rs-research` in Claude. `!` is the host CLI's direct-shell prefix; ordinary terminals use `rsagent` without it. Output enters later chat context, so keep requests bounded. Desktop composer behavior is not assumed equivalent.

1. Choose one immediate question.
2. Park tangents in `TODO.md` with their motivation.
3. Source notes describe sources; threads hold interpretations and conclusions.
4. Save at meaningful conclusions, evidence and changes of direction.
5. Before switching, the agent saves the reasoning and updates the resume, then selects the next thread and confirms success.
6. A fresh chat resumes through one `rsagent status` call. Clearing the chat is optional, done through the host interface, and only after a successful checkpoint.

An abrupt exit cannot save conversation-only material.

The default project brief limit is 3000 characters and the compact resume limit is 5000. Manually oversized sections yield an explicitly marked excerpt and source pointer; retrieve the missing section deliberately. `rsagent status` excludes the full directory, thread history and source bodies.

### Skills

| Skill | Purpose |
| --- | --- |
| `rs-research` | Focus, evidence, retrieval and automatic checkpoints |
| `rs-save` | Save unfinished or completed reasoning and update the resume |
| `rs-threads [ID]` | Save, then create/select/switch threads; text picker fallback |
| `rs-todo --start ID` | Save, then promote a TODO and switch |
| `rs-write` | Write selected outcomes into an explicitly requested manuscript section |
| `rs-paper REF` | Give a paper its number on first discussion; write or update its summary |
| `rs-help` | Summary of the workflow, skills and commands |

Invoke as `$rs-save` in Codex (or via its skill picker) and `/rs-save` in Claude. These are LLM workflows: changing the active pointer with a code helper does not summarize unsaved chat.

## Direct commands

Quote arguments that contain spaces. Read commands support `--json`.

| Command | Effect |
| --- | --- |
| `rsagent status` | Bounded project brief plus active thread resume |
| `rsagent threads [--all] [--kw keyword]` | List threads (`--all` includes obsolete) |
| `rsagent thread delete ID` | Preview exact incoming references |
| `rsagent thread delete ID --confirm TOKEN` | Confirm an unchanged preview |
| `rsagent todo` | List TODOs in file order |
| `rsagent todo "topic and motivation"` | Add a TODO with active-thread provenance |
| `rsagent todo --next` | First TODO in file order |
| `rsagent todo --done ID` / `--delete ID` | Remove a completed / unwanted TODO |
| `rsagent keywords` | Active thread labels |
| `rsagent keywords kw1,kw2` | Add labels (additive) |
| `rsagent keywords --global` | Show the controlled vocabulary |
| `rsagent paper add "ID/URL/local-file"` | Register a paper and create its note |
| `rsagent paper list [--kw keyword]` | List papers |
| `rsagent paper discuss REF` | Give an undiscussed paper (`x0003`) its permanent discussion number |
| `rsagent paper show REF` | Print only the paper's summary block |
| `rsagent paper summary REF [--file F]` | Create or replace the summary block from standard input or a file |
| `rsagent keywords --paper KEY [kw1,kw2]` | Show / add labels for a source |
| `rsagent source add URL --type repo\|tool\|web` | Register a non-paper source |
| `rsagent search "phrase" [--hybrid] [--limit N]` | Search past research through GNO |

`--paper REF` also targets repo/tool/web notes. Papers are always referenced by number only: `2`, `0002` and `x3` all work.

### Paper numbers

| Kind | Key and file | Meaning |
| --- | --- | --- |
| Discussed paper | `0002` → `papers/0002_universal_teleporter.md` | Numbered in the order papers are first discussed; never changes afterwards |
| Undiscussed paper | `x0003` → `papers/x0003_universal_teleporter.md` | Registered but not yet discussed (registration order) |
| Repo / tool / web | `s0001` → `sources/title.md` | Registration order; the `s` keeps them distinct from discussed papers |

Cite as `\cite{0002}`. The first time a paper is discussed (`rsagent paper discuss 3` or `/rs-paper 3`) it is renamed from `x0003` to the next free discussion number, and `\cite{x0003}` and note links are rewritten. Numbers are never reused.

### Paper summaries

Each paper note has a summary block (between `<!-- rs:summary:start -->` and `<!-- rs:summary:end -->`). It is written by the agent at every save, switch, pause or close for the papers discussed in that conversation, and on request with `/rs-paper REF`:

```markdown
## Summary
_Last updated: YYYY-MM-DD · discussed in thread NNN_

### Main idea
- **Goal:** ...
- **Background:** minimum context
- **Core insights:** ...
- **Contribution:** what is new

### Training setup
- **Data:** ...  **Input -> Output:** ...  **Loss:** ...  **Architecture:** high level

### Key Q&A
- **Q:** ... **A:** ... (3-7 items; unresolved ones marked **Open:**)

### Relevance to this research
How it bears on the question; Confirmed vs Tentative.

### Related work paragraph
One or two paragraphs of prose, cited with `\cite{NNNN}`, ready to paste into the manuscript's Related work section (Confirmed relations only).

### Reading notes
Other important details with locations.
```

Aim for about 300-450 words, not counting Reading notes and the Related work paragraph. The Related work paragraph stays in the note; it reaches `paper.md` only when you ask `/rs-write` to use it. `rsagent paper show REF` prints just this block.

### Machine helpers

Used by the skills, not normally typed by hand.

| Command | Effect |
| --- | --- |
| `rsagent thread create "title"` | Create a thread |
| `rsagent thread select ID` | Set the active thread |
| `rsagent thread state ID open\|closed\|obsolete` | Change stored status |
| `rsagent todo --start ID` | Promote a TODO to a thread and select it |
| `rsagent checkpoint` | Validate saved Markdown, refresh references/navigation, queue indexing |
| `rsagent validate` | Check citations, links, labels, active pointer and resume sections |
| `rsagent bibliography` | Regenerate `refs.bib` |
| `rsagent index status` / `flush` | Inspect / run pending indexing |

Notes:

- Promotion writes several files under a retry journal (not one atomic step); the agent checkpoints first, and rerunning the same command completes an interrupted promotion.
- Stored states are `open`, `closed`, `obsolete`. A selected open thread is shown as active; other open threads as paused. Obsolete threads are hidden from default lists, shown by `--all`, and searchable. Reopen before selecting.
- Deletion previews references and accepts an explicit confirmation token without relying on interactive stdin; changed files invalidate the preview. Independent prose, topics, shared sources and manuscript claims survive link cleanup.

## Edit the records

| File | Purpose |
| --- | --- |
| `project_overview.md` | Goal, shared assumptions, confirmed conclusions, generated directory; its frontmatter alone selects the active thread |
| `threads/NNN_title.md` | Compact resume and research record |
| `TODO.md` | Unstarted topics with stable IDs; reorder manually |
| `papers/`, `sources/` | Source notes (papers/files holds copied local files) |
| `keywords.yaml` | Controlled vocabulary, maintained by hand |
| `paper.md` | Manuscript; edited only on your explicit request |
| `refs.bib` | Generated bibliography; do not edit |

Use standard YAML, quote numerical IDs and keys, and keep Markdown bodies intact:

```yaml
---
id: "003"
title: Example investigation
status: open
tags: [algorithm]
---
```

Maintain `keywords.yaml` directly, using lowercase labels with optional descriptions. Assignment validates, deduplicates and preserves existing labels; it never extends the vocabulary silently. Labels are stored in `tags` frontmatter, which GNO indexes as tags. `rsagent validate` reports dangling labels after manual vocabulary edits. Code uses PyYAML safe loading and schema checks.

### Sources

Register DOI/arXiv/URL identities or local PDF/BibTeX files.

- Local files are copied to `papers/files/`.
- URLs store identity, metadata, access date and notes; webpages are not archived, repositories are not cloned, remote PDFs are not downloaded.
- Required metadata failures add nothing; optional missing fields stay explicit.
- Cite as `\cite{0002}` (or `\cite{x0003}` before first discussion); use `$...$` and `$$...$$` for math.

## Retrieval and recovery

Use `rsagent search "known phrase"` for lexical discovery and `rsagent search "conceptual question" --hybrid` for hybrid retrieval. Results are bounded, include exact source locations and thread status, and use a project-specific GNO configuration and index. No answer-generation model or unrelated default collection is used. A search miss does not prove a discussion never happened.

- Mutations save local files and persist/coalesce indexing jobs before returning.
- Lexical synchronization and semantic embedding run as separate background stages; routine reads never rebuild indexes or wait for embeddings.
- Status, list, TODO and keyword output reflects current files even while search lags.
- Manual edits are picked up by `rsagent checkpoint` or an explicit `rsagent index flush`; there is no file watcher.
- Inspect with `rsagent index status`; retry with `rsagent index flush`. Worker failure retains saved research and retryable work.
- Deletion waits for search invalidation before claiming completion, and reports partial success if GNO fails.

## Present and troubleshoot

Serve the research directory and open it in a browser:

```bash
python3 -m http.server 8000   # then visit http://localhost:8000
```

Docsify loads `project_overview.md`, generated sidebar links, nested thread/source notes, math, citations with backlinks, Mermaid and D2. Citations use the root `refs.bib` on every page and revalidate on navigation; missing keys are visibly marked. Frontmatter is hidden. Set `window.RESEARCH_EDIT_BASE_URL` in `index.html` only if you want an edit link. Existing custom renderers are preserved and may need these adapters applied manually.

### Sidebar

Docsify's left navigation comes from `_sidebar.md`. Choose one of two ways to maintain it.

**1. Built-in (default).** The installer adds a managed block (`<!-- rs:navigation:start -->` ... `end`) listing the overview, TODO, manuscript, threads, papers and sources. `rsagent` keeps it current whenever you create, rename, close or delete something. Your own links outside the block are preserved. Nothing to do.

**2. Folder-tree sidebar from a script.** If you prefer a sidebar that mirrors your directory layout (any extra Markdown files or folders you add), generate it with [`generate_sidebar.py`](https://gist.github.com/shacharf/b32b7ee607e4795067e05108d5ca24db), a standalone script that scans a folder for `.md` files:

```bash
# once: download the script into the research project
curl -fsSL -o generate_sidebar.py https://gist.githubusercontent.com/shacharf/b32b7ee607e4795067e05108d5ca24db/raw

# generate (re-run whenever notes are added or removed)
python3 generate_sidebar.py . -r --mode nested     # --mode details (default) gives collapsible sections
```

- `.` is the folder to scan and `-r` includes subfolders (`threads/`, `papers/`, `sources/`).
- Hidden folders (`.rs`, `.agents`, `.claude`) are skipped automatically.
- To leave files out, list patterns, one per line like a `.gitignore`, in a `.gen_sidebar_ignore` file in the project root, for example `AGENTS.md`, `RESEARCH_WORKFLOW.md` and `README.md`.

Things to know when using the script:

- It **overwrites `_sidebar.md` completely**, so the managed block disappears and `rsagent` then leaves the file alone (it only edits a block that exists). Edit sidebar links by hand only in files the script does not generate.
- The sidebar does **not update by itself**; run the script again after `rsagent` creates a thread, paper or source. Paper renames (`x0003_...` to `0002_...`) also change links.
- Re-running `install_project.py` adds the managed block back to a `_sidebar.md` that lacks one. Run the script again afterwards.
- The script is not part of this toolkit and is not tested with it.

### Troubleshooting

| Problem | Check |
| --- | --- |
| Skills missing | Look in the project's `.agents/skills` or `.claude/skills`, restart host discovery, use the right invocation prefix |
| No active thread | Select an open thread explicitly; code never guesses from modification times |
| Search returns nothing | Inspect the GNO config, model availability and `rsagent index status` |
| Sidebar missing or stale | Run `generate_sidebar.py` again (script option), or check that `_sidebar.md` still contains the `rs:navigation` block (built-in option) |
| Citation errors | Run `rsagent validate`, inspect `refs.bib`, and serve from the project root |
| Stale search after manual edits | Run `rsagent checkpoint` or `rsagent index flush` |

Never use Git commands or GNO Git-pull options through this toolkit.

## Limitations and notes

- **Command name:** the executable is `rsagent` (the name `rs` collides with a system utility on macOS). The Python package, `.rs/` state directory and `rs-*` skill names keep the short prefix.
- **BibTeX import:** macros (`@string`) and `#` concatenation are rejected before any change is made; expand them first. Protective braces in title/author/journal fields are removed on import.
- **PDF metadata:** optional, uses `pdfinfo` when installed; otherwise the record is marked incomplete with explicit missing fields. Text conversion for retrieval is done by GNO.
- **Embedding models:** each project uses a private GNO config/cache under `.rs/`. Globally downloaded models are not visible there automatically; set `RS_GNO_EMBED_MODEL=file:/absolute/path/model.gguf` to reuse an existing model read-only. Semantic retrieval depends on the local GNO/llama runtime working (it failed with a Metal allocation error in the sandboxed test environment) and has not been ranking-validated; lexical search is verified against GNO 1.5.1.
- **Host compatibility:** installer output and version checks were verified, but live Codex/Claude Code research sessions were not exercised end to end.
