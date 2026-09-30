---
name: rs-help
description: Explain the rsagent research workflow, its commands and skills, and how to save, switch, resume and search. Use when the user asks for help, usage, or what they can do.
---

Answer briefly from this reference; do not read project files unless asked. Run `rsagent --help` only if the user wants the full command list.

**Workflow:** one research thread at a time. `rsagent status` resumes (project brief + active thread resume). Discuss, read sources, run experiments; park tangents with `rsagent todo "text"`; save at meaningful conclusions. Only saved Markdown survives a cleared chat or an exit.

**Skills** (`$name` in Codex, `/name` in Claude):
- `rs-research` — core protocol: focus, evidence standards, automatic checkpoints, retrieval.
- `rs-save` — save reasoning and update the resume now, even if unfinished.
- `rs-threads [ID]` — save, then create/select/switch thread; without ID shows a short list.
- `rs-todo --start ID` — save, then promote a TODO to a thread and switch.
- `rs-paper REF` — number a paper on first discussion and write/update its summary (Main idea, Training setup, Key Q&A, Relevance, Related work paragraph, Reading notes).
- `rs-write` — write a chosen outcome into a named section of paper.md (only when asked).
- `rs-help` — this summary.

**Direct commands** (prefix `!` in the agent terminal; quote arguments with spaces): `rsagent status`, `threads [--all] [--kw k]`, `todo ["text"|--next|--done ID|--delete ID]`, `keywords [k1,k2|--global|--paper KEY [k1,k2]]`, `paper add "DOI/arXiv/URL/file"`, `paper list`, `paper discuss REF`, `paper show REF`, `paper summary REF` (stdin), `source add URL --type repo|tool|web`, `search "phrase" [--hybrid]`, `thread delete ID` (preview, then `--confirm TOKEN`), `validate`, `index status|flush`.

**Paper numbers:** discussed papers are `0001_title.md`, numbered in discussion order and never renumbered; undiscussed ones are `x0003_title.md`; repos/tools/web are `s0001`. Reference papers by number only (`2`, `0002`, `x3`); cite as `\cite{0002}`.

**Switching safely:** run `rs-threads` (it saves first), confirm the checkpoint, then optionally clear the chat and run `rsagent status` in the new one.

**Notes:** obsolete threads are hidden unless `--all` but remain searchable; keywords come only from keywords.yaml; search may briefly lag saved files (`rsagent index status`). Full documentation: RESEARCH_WORKFLOW.md in the project.
