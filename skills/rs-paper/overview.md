# Initial paper overview

Goal: explain the paper so the reader understands its central idea, how it works concretely, and why it matters. Do not discuss benchmark results.

Read the entire PDF first (the note's `local_file`, otherwise the paper's PDF URL). If the full text cannot be read, say so and stop; do not work from the abstract. Organize the explanation around the paper's contribution, not a fixed list of technical components. Write "not specified" for anything the paper does not state; never fill gaps. Prefer a coherent explanation over maximum detail; leave secondary details for follow-up questions.

Write in this order:

### Core points
4-6 clear bullets. Include those that apply and adapt or replace the rest for the paper's type (algorithm, framework, dataset, benchmark, theory); distinguish these types.
- **Core idea:** the central design decision in plain language.
- **Mechanism:** how the main components interact.
- **Policy/model interface:** what it observes and produces.
- **Training data and learning:** where the supervision comes from.
- **Deployment:** what happens during execution.
- **Why this matters:** what the design enables.

### Takeaway
One short conceptual takeaway: what changes relative to the usual approach.

### One cycle
Only when the mechanism contains a feedback loop or several stages: a numbered sequence tracing one complete cycle, using concrete verbs (e.g. observe, render, compare, predict, correct, execute). Prefer an example, figure or algorithm from the paper itself.

### Caveats
One or two lines on what the work does not establish, plus any unresolved details.

Style:
- Introduce architecture, representations, targets and losses only where they help explain the mechanism. Do not force every paper into an encoder-predictor-target template.
- Include equations only when they clarify something prose cannot, with every symbol defined. Do not front-load dimensions, hyperparameters, optimizer settings or implementation details.
- Prefer concrete operations over phrases such as "captures dynamics" or "improves representations".
- Keep factual qualifications brief and next to the claim they qualify. Tag interpretations as such, separate from paper-grounded facts, without letting uncertainty labels dominate the explanation.
- Cite the sections, figures and equations you rely on, unobtrusively.

Before finishing, check that training data, inputs, targets, losses and inference are covered where applicable; add them to the bullets only if they matter for understanding the idea.
