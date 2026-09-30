---
name: rs-paper
description: Start or summarize a paper discussion. Gives an undiscussed paper its permanent number and writes or updates the discussion summary in the paper note. Use when the user asks to summarize or discuss a paper by number.
---

Papers are referenced only by number (`2`, `0002`, `x3`). Undiscussed papers are `x`-prefixed (`x0003_title.md`); the first time one is discussed it receives the next discussion number, which never changes afterwards.

1. Run `rsagent paper discuss REF` (a no-op if the paper already has its number) and note the printed key and path. Use the new number from then on, including in `\cite{...}`; the command rewrites existing references itself.
2. Read the note with `rsagent paper show REF`; open the full note only if reading notes are needed.
3. From this conversation, write the summary using the format below and save it with `rsagent paper summary REF` (pass the text on standard input, e.g. with a quoted heredoc `<<'EOF'`, or use `--file`). The command creates or replaces only the managed summary block and leaves the rest of the note intact. Revise earlier content instead of appending a second summary. Keep it brief (about 300-450 words, excluding Reading notes and the related work paragraph) but capture the main points. Distinguish Confirmed (user agreed) from Tentative (suggested). Do not invent details not in the paper or discussion; write "unknown" or "not discussed" instead.
4. Run `rsagent checkpoint`, then confirm the paper number and path in one line.

Summary format:

```markdown
## Summary
_Last updated: YYYY-MM-DD · discussed in thread NNN_

### Main idea
- **Goal:** what the paper sets out to do.
- **Background:** the minimum context needed to follow it.
- **Core insights:** the key ideas that make it work.
- **Contribution:** what is new relative to prior work.

### Training setup
- **Data:** dataset(s), format and size.
- **Input -> Output:** what the model receives and predicts.
- **Loss:** objective(s) and any auxiliary terms.
- **Architecture:** high-level components only.
(For non-learning papers, replace this section's bullets with a short "Method / setup".)

### Key Q&A
- **Q:** a question we raised. **A:** the answer reached (section or page). Mark unresolved ones **Open:**. Keep 3-7 items that clarified something.

### Relevance to this research
How it bears on our question, linking the thread(s). Mark Confirmed vs Tentative.

### Related work paragraph
One or two paragraphs of plain prose, ready to paste into the manuscript's Related work section. State the paper's main point and contribution, cite it as `\cite{NNNN}`, and say how it relates to our research question. Neutral third person; include only relations marked Confirmed above, and hedge or omit Tentative ones. This text stays in the note; it goes into `paper.md` only through `rs-write` on explicit request.

### Reading notes
Other important details: numbers, ablations, assumptions, limitations, quotes with locations.
```
