# Research workflow implementation plan

Status: implemented. This is the original specification; where it differs, the README is authoritative (notably: the command is `rsagent`, paper notes are numbered in discussion order as `0002_title.md` with `x0003_title.md` for undiscussed papers, repo/tool/web keys are `s0001`, and paper notes carry a managed summary block).

This is a self-contained specification for building a reusable research-management toolkit. The implementing agent does not need the preceding conversation or an earlier proposal. Use the requirements, command contracts, implementation sequence, and acceptance criteria below.

## 0. Product brief and implementation handoff

### What we are building and why

Build a small tool called `rsagent`, with project-local agent skills, that lets a researcher use Codex or Claude Code as a collaborator for computer-science research. The researcher starts with a broad idea, investigates one question deeply, reads related work, discusses possible approaches, accepts or rejects ideas, and sometimes returns to an earlier investigation. Selected findings eventually become a scientific manuscript.

The researcher finds parallel topics difficult to follow and wants to work on one thread at a time. They also find that agents spend too long listing directories, grepping files, repeating searches, and rereading old context. The system must make it easy to identify the current question, resume its reasoning, park tangents, and locate earlier evidence with few tool calls and little unnecessary context.

The intended experience is a focused conversation with automatic recordkeeping. The researcher controls research direction and substantive decisions. The agent preserves the reasoning and evidence, distinguishes tentative suggestions from confirmed conclusions, and proposes the next useful step. Small bookkeeping operations run directly as code; research and synthesis use the LLM.

### How the pieces fit together

- **Markdown documents** hold the authoritative research. A thread is a durable investigation document, separate from an agent chat.
- **The project overview** preserves the big picture and active-thread selection. Each thread's compact resume makes returning to it inexpensive.
- **Paper/source notes** hold information about individual sources. Threads hold our interpretations and conclusions. The manuscript incorporates selected outcomes only on explicit request.
- **The Python `rsagent` CLI** handles deterministic operations such as TODOs, keyword assignment, source registration, navigation, and reference maintenance.
- **Project-local skills and `AGENTS.md`** teach both agents the same research workflow, including saving before switching or clearing a chat.
- **GNO** indexes the documents for finding past reasoning and evidence. Known thread resumes and navigation are read directly.
- **Docsify**, using the existing `index.html`, presents the research documents to the user.

The primary optimization target is end-to-end response time, followed by avoiding unnecessary model context and repeated work. Keep retrieval accurate and preserve the reasoning needed to resume; a short but incomplete checkpoint does not meet the goal.

### Example user journey

A researcher opens a project and resumes a thread about a proposed algorithm. During discussion, an evaluation idea arises; it is added to `TODO.md` without interrupting the current investigation. A relevant paper is registered, its reading notes are saved, and the thread records how its evidence changes the argument. The researcher saves, switches to another thread, and optionally clears the chat. A fresh session resumes from the overview and selected thread's saved state. Later, the researcher asks for one confirmed result to be written into a specific section of `paper.md`.

### What the implementing agent must deliver

This repository is the toolkit's implementation/source repository. The per-project installer applies the toolkit to a separate research directory; the layout in section 3 describes that installed research project. Keep reusable code, templates, skills, tests, and installer sources in this repository, and use temporary target directories for demonstrations.

Deliver the working Python package and `rsagent` executable, document templates, GNO adapter/index maintenance, shared workflow skills with both engine integrations, engine-selecting installer, README/command reference, Docsify integration, meaningful tests, and the end-to-end demonstration described below. The toolkit must be usable in a new research project without relying on this conversation, global research skills, or hidden machine-specific files.

When asked to implement this plan, inspect the repository and its applicable instructions, then execute section 12 and validate against section 13. Resolve ordinary implementation choices within this specification. Record version-sensitive limitations or genuine requirement conflicts explicitly. Report what was built, how it was verified, and any remaining limitations. Planning is complete enough to begin implementation; no implementation has been performed as part of writing this document.

## 1. Objectives and scope

- Work on one research thread and one immediate question at a time.
- Reduce response latency and model context by making routine navigation direct and predictable.
- Preserve enough reasoning and evidence to resume an investigation without reconstructing it from chat history.
- Keep research editable as Markdown and present it through the existing Docsify site.
- Use GNO for discovery across research records and sources.
- Use deterministic code for bookkeeping and an LLM for interpretation, discussion, synthesis, and writing.
- Support Codex CLI and Claude Code with the same research files, CLI, and workflow.
- Never run Git commands. The user controls commits.

Research threads are independent of agent chats. One thread may span multiple chats; one chat may visit multiple threads. There is one active research thread per research project, shared by all chats using that project.

Out of scope for the initial implementation: a custom authoritative SQLite database, a new chat application, custom composer autocomplete, automatic manuscript writing, and local archiving of URL sources.

## 2. Research workflow

1. Run `rsagent status` once to obtain a bounded project brief and the active thread's compact resume. Do not read the full overview/thread directory or discover these files through a broad search.
2. Choose the immediate question within that thread.
3. Discuss ideas, read sources, or run experiments one step at a time.
4. Capture tangents in `TODO.md`, including why they matter, and return to the current question.
5. At meaningful checkpoints, save the substantive reasoning and update the resume. Label tentative ideas separately from user-confirmed conclusions.
6. Continue, pause, close, mark obsolete, or switch at the user's direction.

Automatic checkpoints occur after meaningful conclusions, useful evidence, or changes in direction, and before a deliberate switch or session ending. Explicit `rs-save` saves even an unfinished discussion. Do not save after every message or require approval for routine recordkeeping.

An abrupt application exit cannot guarantee a checkpoint. The documentation must distinguish saved research from conversation-only material.

### Switching and clearing a chat

Switching is an LLM workflow, because code cannot summarize unsaved conversation:

1. Save the current thread's research record and resume.
2. Record the selected thread as active.
3. Confirm the checkpoint and switch succeeded.
4. Optionally let the user clear the chat or start a fresh one.
5. Run `rsagent status` in the new chat to retrieve the project brief from `project_overview.md` and the selected thread's resume in one operation.

Do not clear the chat before a successful save. Clearing is optional and uses the host's own interface; the research CLI must not pretend it can reset either agent's chat. Background lexical synchronization and semantic indexing need not finish before clearing if the Markdown checkpoint and pending indexing work have been persisted.

## 3. Research project layout

```text
AGENTS.md                       Shared instructions for both engines
README.md                       Project usage and installation guidance
project_overview.md              Goal, shared conclusions, active thread, directory
TODO.md                         Deferred, unstarted topics with stable IDs
keywords.yaml                   Manually maintained controlled vocabulary
paper.md                        Manuscript, edited only on explicit request
refs.bib                        Generated bibliography
index.html                      Existing Docsify renderer
_sidebar.md                     Docsify navigation
threads/
  001_topic_title.md            Thread metadata, resume, research record
papers/
  paper_title.md                Paper metadata and reading notes
  files/
    paper_title.pdf             Copies of imported local files
sources/
  source_title.md               Repository, tool, and webpage notes
.rs/
  ...                          Project marker/configuration and derived runtime state
.agents/skills/rs-*/SKILL.md     Installed for Codex
.claude/skills/rs-*/SKILL.md     Installed for Claude Code
```

The two skill directories are installed according to the selected engine. Installing both integrations is supported. Their source templates are maintained together in the implementation repository.

Markdown and `keywords.yaml` are authoritative. `refs.bib`, navigation blocks, and GNO indexes are derived. `.rs/` may hold installation metadata, ID allocation, indexing jobs, and recovery information, but must not become a second authoritative research store.

Use stable IDs and citation keys independent of display titles. Sanitize filenames and handle collisions without overwriting existing notes or imported files. Do not reuse deleted thread or TODO IDs.

## 4. Document responsibilities and metadata

### Project overview

`project_overview.md` contains the overall goal/problem definition, shared assumptions and constraints, user-confirmed conclusions with supporting thread links, and a compact thread directory.

Maintain a designated compact project-brief section within this file for startup: the goal, essential shared assumptions, and the few current conclusions needed to orient the active investigation. `rsagent status` returns this brief plus the active thread's designated resume in one call. It excludes the full thread directory, accumulated project history, and source-note bodies. Use `rsagent threads` for the directory and targeted reads for additional overview sections.

Define documented default output-size limits for the brief and resume, and keep them within those limits during checkpoints. If manual edits make either section exceed its limit, return an explicitly marked bounded excerpt and its source location so the agent can retrieve missing context deliberately. Never silently truncate a section or interpret an excerpt as the complete record.

Its metadata is the sole authority for the active-thread selection:

```yaml
---
active_thread: "003"
---
```

Use an explicit empty value when no thread is active. Commands requiring an active thread fail clearly when it is absent; they do not guess from chat or modification times. Thread IDs remain strings to preserve zero padding.

Keep generated navigation in marked blocks so code can update it without rewriting the overview's prose.

### Threads

Minimum metadata: stable ID, title, stored status, and keyword labels. The filename includes the stable ID. Timestamps may be maintained by code where useful.

Each document has two parts:

1. **Compact resume:** guiding question; current understanding with confidence/confirmation distinctions; immediate focus; next step; and a few links to necessary supporting material.
2. **Research record:** reasoning, examples, equations, experiments, source references and evidence locations, accepted/rejected/deferred ideas with reasons, and unresolved questions.

Organize the record by subtopic. Use dated checkpoints when understanding changes; retain earlier reasoning when a conclusion is superseded. It is a coherent research record, not a mandatory verbatim chat transcript or a series of disconnected log rows.

Resume commands read the designated resume section directly and do not automatically return the entire record or every linked source. Preserve a compact section through editing rather than silently truncating important qualifications.

### Thread states

Stored statuses are `open`, `closed`, and `obsolete`:

- An open thread selected by the overview is displayed as **active**.
- Other open threads are displayed as **paused**.
- **Closed** means finished but retained and searchable.
- **Obsolete** means outside the current research direction but retained for useful information.

Obsolete threads are excluded from the default picker/list, included by `--all`, and remain searchable with their status visible. Closed and obsolete threads may be restored to open. The active pointer must never reference a closed, obsolete, missing, or deleted thread.

Status transitions need a small internal CLI operation used by the agent. If a transition affects the active discussion, the LLM checkpoints first. This is an implementation helper, not a requirement for another public skill.

### TODOs

`TODO.md` is an ordered list of unstarted topics. Each item has a stable ID, text, and optional originating-thread link; include motivation in the text when needed.

- `--next` returns the first item in file order, without LLM ranking.
- Users can reorder the file directly.
- Starting an item creates a thread, removes the item only after creation succeeds, checkpoints the current discussion, and switches through the LLM workflow.
- Completed or unwanted items are removed rather than accumulating a second historical log.
- Paused investigations remain threads; do not duplicate them as TODOs.

### Paper and other source notes

`papers/<paper_title>.md` records a particular paper's bibliographic metadata, stable citation key, keyword labels, reading notes, relevant passages/locations, and limitations.

`sources/<source_title>.md` provides equivalent notes for `repo`, `tool`, and `web` sources, including identity, URL, available metadata, access date, capabilities, limitations, and useful links.

Our interpretations, arguments, and conclusions belong in threads. Source notes describe the source and support targeted retrieval.

### Manuscript

`paper.md` is separate from the overview. Edit it only when explicitly requested, targeting the requested section and preserving manual edits. A thread can contribute a section, a subsection, a small claim, or nothing to the manuscript, and can remain open after contributing.

Draft from thread reasoning and supporting evidence; one-sentence source summaries alone are insufficient support for scientific claims. Use `$...$`, `$$...$$`, and `\cite{key}`. The initial skeleton contains title, abstract, introduction, related work, and method, without automatically adding results or conclusion sections.

## 5. Public command reference

These are the agreed public commands. `!` is the coding agent terminal's direct-shell prefix, not part of the `rsagent` executable. Shell arguments containing spaces must be quoted.

```text
!rsagent status                           Bounded project brief + active thread resume
!rsagent threads                          List threads, excluding obsolete
!rsagent threads --all                    Include obsolete threads
!rsagent threads --kw keyword             Filter by keyword
!rsagent thread delete ID                 Preview references, then confirm deletion
!rsagent todo                             List open TODOs
!rsagent todo "text"                      Add a TODO with active-thread provenance
!rsagent todo --next                      First TODO in file order
!rsagent todo --done ID                   Remove completed TODO
!rsagent todo --delete ID                 Remove unwanted TODO
!rsagent keywords                         Show active thread's keywords
!rsagent keywords kw1,kw2                 Add keywords without replacing existing ones
!rsagent keywords --global                Show the controlled vocabulary
!rsagent paper add "ID/URL/local-file"    Register paper and create its note
!rsagent paper list                       List registered papers
!rsagent paper list --kw keyword          Filter papers by keyword
!rsagent keywords --paper KEY             Show paper keywords
!rsagent keywords --paper KEY kw1,kw2      Add paper keywords
!rsagent source add URL --type repo|tool|web
```

All read commands support compact plain text and `--json`. Registration should report the stable key and note path. Mutating commands report a short concrete result, not an LLM-generated explanation.

Source keys share the bibliography namespace. The `--paper KEY` keyword target can address a registered non-paper source key too; document this compatibility behavior so non-paper notes receive the same labels without a duplicate keyword subsystem.

Small internal helpers are required for thread creation, selection, status changes, checkpoint completion, TODO promotion, index scheduling, and validation. Define their machine-facing arguments during implementation, keeping them distinct from LLM summarization. A code operation that changes the active pointer does not itself save conversation history.

### Skills / LLM workflows

| Skill | Responsibility |
| --- | --- |
| `rs-research` | Core session protocol, immediate focus, evidence standards, checkpoint and retrieval behavior |
| `rs-threads` | Select/create a thread, save the current discussion, and switch; accepts an explicit ID |
| `rs-todo --start ID` | Promote a TODO and perform the checkpointed switch |
| `rs-save` | Save reasoning and evidence, update the resume/overview as needed, schedule indexing, briefly confirm |
| `rs-write` | Transfer selected outcomes to the requested manuscript section and validate references |

Paper reading and ordinary research are conversational requests governed by the core protocol. Do not require an extra skill for every mechanical action.

Claude invokes skills as `/rs-save`; Codex CLI invokes them as `$rs-save` or through its skill picker. The names and behavior match, but the host invocation syntax differs. Do not advertise a portable custom `/rs-threads ` popup: show a compact selection list after invocation, use host-supported selection controls when available, and keep a text-selection fallback.

## 6. Keywords

- Create an initial `keywords.yaml` template; the user maintains it directly.
- Each keyword has a normalized name and optional short description. Normalize lowercase and surrounding whitespace while retaining internal spaces.
- Papers, other sources, and threads support multiple labels from the same vocabulary.
- Assignment is deterministic: validate against the vocabulary, deduplicate, preserve existing assignments, and reject unknown keywords clearly.
- The agent may suggest labels or a vocabulary addition, but assignment does not silently extend the vocabulary.
- Do not build keyword vocabulary editing, renaming, merging, or deletion commands. Those were explicitly removed from scope.
- Validate and report dangling labels after manual vocabulary changes; do not infer rename intent from a missing keyword.
- Keyword filters identify related documents; links/citation keys identify a particular thread or source.
- Document the metadata field used for labels and map it to GNO's supported tag indexing. Test this against the supported GNO version instead of assuming every frontmatter field is searchable as a tag.

## 7. Source registration and bibliography

Registration is code-driven; reading and discussing a source is a separate LLM action.

- Resolve DOI/arXiv identifiers and recognizable paper URLs to available bibliographic metadata.
- For other paper URLs, record only metadata that can be established; represent missing fields explicitly.
- Support local PDF and BibTeX file import through `rsagent paper add`. Copy local source files into `papers/files/` and link them relatively from the note. Preserve the original file. For BibTeX files containing multiple entries, register each entry and report the resulting keys; validate the import before committing it.
- Use existing conversion/extraction capabilities for local documents, preferably the installed GNO stack. Do not implement a PDF parser from scratch. If metadata extraction is unavailable or incomplete, create a clearly marked incomplete record with a stable key and explicit missing fields; do not invent authors, dates, or titles.
- For GitHub repositories, obtain available structured repository metadata; for tools/webpages, allow explicit title/organization/year overrides when extraction is insufficient.
- URL registration stores the URL, metadata, access date, and notes. It does not download and archive the webpage, clone a repository, or automatically archive a remote PDF.
- Assign sequential numerical citation keys in registration order: `0001`, `0002`, and so on. Use the same sequence for papers and other source types because they share `refs.bib`. Pad to at least four digits, allowing `10000` and higher naturally. Allocate keys under the project lock, retain the allocation high-water mark, and never renumber existing records or reuse retired keys. A duplicate registration returns the existing key. Imported BibTeX entries receive keys from this sequence. Titles and metadata improvements do not change keys or rename paper notes automatically.
- Store numerical keys as quoted YAML strings, such as `key: "0001"`, and preserve them as strings in JSON. Cite a source as `\cite{0001}` and target it with, for example, `rsagent keywords --paper 0001`.
- Detect duplicates using known DOI, arXiv ID, normalized URL, and local-file identity/hash where appropriate.
- Build `refs.bib` from authoritative note metadata, sorted by numerical key value, using appropriate paper/software/misc entry types and valid escaping. Mark it as generated with BibTeX-compatible comments.
- Stage remote metadata before committing a registration. On a required metadata-fetch failure, add nothing and report the error. Optional enrichment failure must be distinguished from a failed registration and missing fields remain explicit.
- Regenerate the bibliography after relevant metadata mutations/checkpoints; do not rewrite source-note prose.

The internal validator checks citation keys across overview, threads, manuscript, source notes, and other research Markdown; source/thread links; label validity; active-pointer validity; and required resume sections. Ignore examples in fenced code when validating citations. Validation is not a reason to rewrite user prose wholesale.

## 8. Deletion

`rsagent thread delete ID` first previews the exact document and incoming references that will be affected. Confirmation must work in both engines: do not depend solely on an interactive stdin prompt inside a shell tool; provide a preview token/explicit confirmation path if necessary.

Confirmed deletion:

1. Removes the thread document.
2. Removes links and structured references to that thread from the overview, TODOs, paper/source notes, other threads, and manuscript navigation where present.
3. Clears the active pointer if it targets that thread.
4. Removes the deleted document from GNO retrieval and refreshes changed documents.
5. Preserves independent content: TODO topics, shared sources, and scientific manuscript text already derived from the thread.

Removing a link should retain surrounding independent prose. Use canonical ID-based links and explicit metadata references so cleanup is deterministic. Do not delete arbitrary text merely because it contains the same number/title; flag ambiguous references in the preview. Make unresolved incoming references visible rather than claiming complete cleanup when it cannot be established.

Preview validation must detect if files changed before confirmation. Coordinate multi-file updates with locking and a small recoverable transaction/journal so failure does not silently leave broken navigation. Temporary recovery artifacts are cleaned after successful completion, rather than retaining a user-visible archive of deleted threads.

Do not report complete removal from search until index invalidation succeeds. If Markdown deletion succeeds but GNO fails, report the partial result and retain a retryable cleanup task.

## 9. GNO retrieval and freshness

Use GNO as a derived retrieval index, not the authoritative store of decisions, notes, or active-thread state.

### Fast paths

- Resume/switch: one `rsagent status` operation returns the compact project brief and designated resume section, without the full overview or thread directory.
- Thread/source lists and exact IDs: use maintained navigation/metadata with predictable paths.
- Keyword/TODO operations: deterministic local operations without LLM interpretation or discovery searches.
- Past arguments/unknown locations: GNO search, followed by bounded passage retrieval when necessary.

Use keyword search for known identifiers/phrases and an appropriate hybrid mode for conceptual questions. Favor bounded results and fast hybrid retrieval for ordinary lookups; escalate to more expensive expansion/reranking when needed. Do not run GNO's answer-generation model when the current research agent only needs evidence passages.

Include source locations and thread status with retrieved evidence. Obsolete research remains discoverable but must not be presented as the project's current conclusion. A search miss is not proof that a discussion never happened.

### Index maintenance

- Checkpoints, explicit saves, registrations, metadata changes, and other searchable mutations persist their file changes and enqueue index work before returning. Small TODO/keyword mutations must not wait for a GNO process or project-wide synchronization.
- Run both lexical synchronization and semantic embedding in the background, as separate stages with observable pending/error states. Search can briefly lag behind saved files; direct status, TODO, keyword, and list commands read current authoritative data.
- Persist pending work, coalesce rapid edits, and avoid concurrent index writers or one new model process per small change. Batch pending changes before incremental synchronization rather than starting a full sync for every mutation.
- Deletion is the explicit exception: wait for removal/invalidation of the deleted document from retrieval before reporting deletion fully complete, as specified in section 8. Do not wait for unrelated semantic re-embedding of surviving documents. An explicitly requested indexing flush may also wait; routine reads never do so.
- Routine reads never rebuild or scan the corpus for freshness. Direct Markdown reads always return the latest saved thread state.
- Surface pending/failed indexing compactly and provide a retry path. Allow a brief lexical and semantic search freshness delay, with saved Markdown immediately available.
- Manual document edits are picked up by an explicit save/sync or the supported project indexing worker; document which behavior is implemented.
- Isolate each project's configuration/index selection and use explicit GNO scope on every invocation. Do not search an unrelated default collection or modify an existing corpus accidentally.
- Never enable GNO options that run Git commands, including `update --git-pull`.

Before implementing the adapter, verify installed-version behavior for frontmatter/tags, incremental sync, deleted-document removal, PDF conversion, index isolation, and background work. Do not assume single-file sync exists: installed GNO 1.5.1 exposes `update` without a per-file argument, so use bounded project collections and its incremental behavior.

## 10. Installation and cross-engine compatibility

### One-time machine setup

The implementation repository's README documents Python >=3.10, installing the `rsagent` executable on PATH, GNO installation, required model downloads, and supported agent/GNO versions. Prefer a straightforward package entry point: `rsagent = "rs.cli:main"`.

Use short functional Python code with the standard library plus PyYAML as the YAML runtime dependency, declared in `pyproject.toml`. This explicitly replaces the earlier standard-library-only restriction for YAML parsing. Parse vocabulary files and frontmatter with `yaml.safe_load` (or an equivalent SafeLoader), then validate the application schema and field types. Use standard YAML syntax rather than a custom parser/dialect. Keep zero-padded IDs and citation keys quoted as strings. Code never rewrites the manually maintained `keywords.yaml`; limit metadata writes to the necessary frontmatter and preserve Markdown bodies. GNO remains an external prerequisite and provides existing document-conversion capabilities where available. Use pytest for tests only.

### Per-project installer

```bash
python scripts/install_project.py --project /path/to/research --engine codex
python scripts/install_project.py --project /path/to/research --engine claude
```

The script must:

1. Validate prerequisites and target directory without modifying global skills or agent configuration.
2. Create missing research templates, project marker/config, and the initial keyword vocabulary.
3. Install project-local skills for the requested engine only.
4. Add a concise managed section to the shared `AGENTS.md`, preserving existing instructions.
5. Configure project-scoped GNO retrieval and indexing.
6. Connect existing/new Docsify navigation to the research documents.
7. Verify the setup and show the exact startup/invocation instructions for that engine.

Rerunning the installer is idempotent. Preserve research, manually edited templates, existing `keywords.yaml`, unrelated skills, Docsify customizations, and other agent settings. Installing the other engine later must use the same project and research records. Detect conflicting modified installed files and report them rather than overwrite blindly.

Use `.agents/skills/rs-*/SKILL.md` for Codex and `.claude/skills/rs-*/SKILL.md` for Claude. Keep shared skill content engine-neutral, generating only necessary invocation/tool adaptations. Do not rely on a tool or question UI available in only one host; use text fallbacks. Do not create separate Claude research instructions: `AGENTS.md` is the shared file.

The supported Claude setup must actually load `AGENTS.md`. Current documentation says direct loading begins at v2.1.277, with additional fixes by v2.1.281; existing project/ancestor `CLAUDE.md` or `CLAUDE.local.md` and host settings can change precedence. Check these conditions, document a supported version, and provide an explicit compatible startup configuration when needed. Do not silently edit global settings or create a separate instruction copy. A project-specific `--settings` launch file is an option to validate for conflicting existing setups.

Both terminal clients support direct `!` shell execution. Claude's automatic response to shell output must be disabled in the supported setup when users want no LLM round trip (`respondToBashCommands: false`, subject to supported-version validation). Keep command output compact because it can enter later chat context. Desktop composer behavior is not assumed equivalent to the CLI.

### README contents

- What the system does and the single-thread workflow.
- One-time GNO/CLI/model setup and supported versions.
- Per-project installation for each engine and installing both.
- Full direct-command and skill reference, including shell quoting.
- How to start/resume, save, switch, and clear safely.
- Manual editing rules, YAML metadata examples, PyYAML installation, source registration, and keyword assignment.
- Background-index freshness and failure recovery.
- Local-file copying versus non-archived URL sources.
- Deletion and obsolete-thread behavior.
- Troubleshooting missing skills, active-thread selection, GNO configuration, and citation rendering.

## 11. Docsify integration

Preserve and adapt the existing `index.html`; do not replace the renderer unnecessarily. It already supports LaTeX-style citations, KaTeX, Mermaid, and D2 diagrams.

Repository inspection found that `bibliographyPath()` currently looks for a page-local `ref.bib`. Change the implementation to use the project's single root-level `refs.bib`, including when viewing nested thread/source notes. Ensure bibliography updates are not hidden indefinitely by the current in-memory bibliography cache.

Render frontmatter as appropriate metadata or hide it; do not leak raw metadata syntax into document prose. Maintain navigation in clearly marked generated blocks, preserving user links. Replace the existing placeholder edit URL with an explicit configuration or omit the link until configured.

Verify navigation, nested note links, citations/backlinks, missing-key indicators, math, keyword-filter/list views where provided, and retained diagrams. Docsify browser search may remain available, while agent discovery uses GNO.

## 12. Implementation sequence

1. **Storage and templates:** document schemas with PyYAML safe loading, root discovery, stable IDs, targeted writes, lock/recovery behavior, overview/thread/TODO/source templates.
2. **Mechanical CLI:** status/list/filter, TODO operations, keyword assignment, thread helper operations, deletion preview/cleanup, compact and JSON output.
3. **Source registration:** DOI/arXiv/GitHub/URL/local-file inputs, stable citation keys, deduplication, bibliography generation, validators.
4. **GNO integration:** isolated configuration, evidence retrieval conventions, queued/coalesced background lexical synchronization and embedding, deletion invalidation, freshness reporting.
5. **Agent workflows:** concise project-local skills, checkpoints, switching/clear handoff, TODO promotion, explicit manuscript writing, shared `AGENTS.md`.
6. **Installation and presentation:** engine-selecting installer, README, Docsify integration, preservation/idempotency behavior.
7. **Verification and handoff:** unit/integration checks, temporary-project demo, cross-engine smoke tests, and latency measurements.

Use small modules and functions rather than frameworks or elaborate class hierarchies. Execute external commands with argument arrays and explicit working directories; do not interpolate source URLs, paper titles, or TODO text into shell code.

## 13. Verification and acceptance criteria

### Deterministic tests

- Root discovery from subdirectories; stable ID allocation and collision-safe filenames.
- One active pointer; switch/close/obsolete/reopen/delete invariants; active and paused presentation.
- TODO ordering, source-thread provenance, completion/deletion, and promotion without duplicate or lost items.
- Keyword validation, additive deduplication, paper/source targeting, and dangling labels after manual vocabulary edits.
- A single status operation returns the bounded project brief and active resume while excluding a large thread directory, full thread histories, and source notes; oversize manual edits produce explicit excerpt markers and source pointers.
- DOI/arXiv/GitHub metadata fixtures, required-fetch failures, incomplete metadata, local PDF/BibTeX imports, copying and duplicate detection.
- Sequential numerical citation-key allocation, duplicate reuse, stability across metadata edits, no recycling after deletion, preservation of leading zeroes, ordering beyond `9999`, valid bibliography escaping and entry types, missing-key checks, and nested-page bibliography resolution.
- Deletion preview/confirmation, incoming-link cleanup, preservation of independent prose and manuscript claims, stale-preview detection, and recovery after injected failures.
- GNO job scheduling/coalescing, pending/error states, deleted-note invalidation, and strict project scoping. A blocked/slow index worker must not delay completed small TODO/keyword mutations; deletion must not claim complete retrieval removal before invalidation succeeds.
- Installer for each engine, repeated installation, installing both, and preserving existing files/settings.
- Compact and JSON read outputs; malformed YAML, invalid field types, and unsafe object tags produce clear diagnostics without damaging files. Quoted numerical IDs/keys retain their leading zeroes.

Mock network calls in routine tests. Test GNO integration separately against the documented version; do not claim mocked retrieval proves actual ranking, metadata indexing, or embedding behavior.

### End-to-end demonstration

In a temporary research project:

1. Install each engine integration and confirm all skills are project-local.
2. Create two threads, select one, record a checkpoint, and resume it from saved files.
3. Add/reorder/promote a TODO; assign keywords; demonstrate unknown-key rejection.
4. Register a paper from fixtures and a local file, plus one URL source without archiving its page.
5. Generate the bibliography and validate citations.
6. Mark a thread obsolete, find it through search, restore it, then preview/delete a disposable thread and verify reference cleanup.
7. Verify saved-state recovery after a fresh chat and after interrupted indexing.
8. Render overview, thread, source note, and manuscript in Docsify and inspect citations/math/navigation.

Perform actual Codex and Claude Code smoke tests when available; record any untested host/version explicitly. File-generation tests alone do not establish end-to-end agent compatibility.

### Latency and token-efficiency checks

Measure representative tasks: resume, list/filter threads, add/next TODO, assign labels, and recover an old argument. Separate subprocess execution, indexing, retrieval, and agent/tool overhead. Measure cold and warm GNO searches and check that relevant evidence was retrieved.

Acceptance targets:

- Direct bookkeeping uses no model inference from `rsagent`.
- Small bookkeeping mutations return after local persistence and enqueueing index work; they do not await lexical synchronization or embedding.
- Resume and navigation require no corpus search and no embedding work.
- One `rsagent status` operation returns only the bounded project brief, active thread resume, and key pointers; the full directory is retrieved separately when requested.
- GNO searches return bounded passages with exact source locations.
- Routine reads do not rebuild the index.
- Indexing failure does not destroy saved research or masquerade as successful indexing.
- Both engines operate on the same files without global skill installation.
- No Git command is used by the implementation, installer, tests, or indexing hooks.

Do not promise an absolute search latency before measuring the actual hardware, models, and corpus.

## 14. Reference checks used for this plan

- Local repository: `index.html`, `README.md`, `_sidebar.md`; no project or ancestor `AGENTS.md` was present during inspection.
- Installed GNO: version 1.5.1; CLI help verified `--config`, `--index`, `update`, collection filters, and collection-scoped embedding. No corpus was changed for this plan.
- [Codex skills and project-local discovery](https://learn.chatgpt.com/docs/build-skills).
- [Codex CLI commands and direct shell execution](https://learn.chatgpt.com/docs/developer-commands?surface=cli).
- [Claude Code skills](https://code.claude.com/docs/en/skills).
- [Claude Code shared AGENTS.md loading](https://code.claude.com/docs/en/memory#agentsmd).
- [Claude Code direct shell execution](https://code.claude.com/docs/en/interactive-mode#shell-mode-with-prefix).
- [GNO CLI](https://gno.sh/docs/cli) and [search pipeline](https://gno.sh/docs/how-search-works).
- [PyYAML documentation and safe loading](https://pyyaml.org/wiki/PyYAMLDocumentation).

Recheck version-sensitive integration details during implementation. To hand this specification to another coding agent, give it this repository and the following task:

> Implement `IMPLEMENTATION_PLAN.md` in this repository. Read the product brief first, follow the implementation sequence, and verify the acceptance criteria. Preserve existing files and manual edits, install research skills only in target projects, and never run Git commands. Complete the tests and temporary-project demonstration, then report results and any unverified engine/version behavior.
