# Demo Video Script (8–12 minutes)

Three beats are required by the brief: a claim stopped early by a document
problem, an end-to-end approval with the full trace, and one decision you are
proud of plus one you would change. Everything else is optional — cut it before
you overrun.

**Before recording**

- Backend and frontend running; browser at http://localhost:5173; a terminal
  visible for the eval run.
- **Seed a clean store.** A demo that opens on 90 test claims reads as a
  scratchpad. Submit four or five deliberate claims first so **Recent claims**
  and **Analytics** look like a system in use.
- Check the health chip says *all systems healthy*, and know which stores are
  live — Neo4j free tier sleeps, and a degraded chip invites a question you
  should answer on purpose rather than by surprise.

## 0. Framing (45s)

- The problem: manual claim review is slow and inconsistent.
- The shape, in one breath: a deterministic adjudication pipeline behind a
  fail-fast document gate, an LLM used only to *read* documents and never to
  decide money, and a trace that lets operations reconstruct any decision.
- Point at the nav: Console, Assistant, Analytics, Recent claims, Eval report,
  Docs. "The documentation is served by the running app."

## 1. REQUIRED BEAT — stopped early by a document problem (2 min)

Lead with **real files**, not the JSON path — the system reading images is the
stronger claim.

- **Upload documents**, attach `prescription_rajesh.jpg` *twice* for a
  CONSULTATION claim, both types left on **Auto-detect**. Submit.
- Watch the trace stream: both files classified `PRESCRIPTION` by vision, then
  the verifier stops. **No decision was made** — `DOCUMENTS REQUIRED`.
- Read the message aloud. It names what was uploaded, what is required, and the
  action. *"A generic error is not acceptable"* — this is the opposite of one.
- Then the beat that lands: attach **`prescription_and_bill_2page.pdf`** — one
  PDF holding both documents, the way people actually scan. It approves. Say
  why: typing a file by its first page reported the bill as missing, which was
  specific, actionable and false. Every page is classified now.

## 2. REQUIRED BEAT — approval with the full trace (3–4 min)

- Upload `prescription_deepak_apollo.jpg` + `hospital_bill_apollo_deepak.jpg`,
  member EMP010, hospital **Apollo Hospitals**, ₹4,500.
- Decision: APPROVED **₹3,240**, confidence 0.98.
- **Financial breakdown**: eligible base 4,500 → network discount 20% → 3,600 →
  co-pay 10% → **3,240**. The order is a graded policy rule and deterministic
  code computes it.
- **Trace timeline**, top to bottom: every check, its outcome, the numbers it
  looked at, and its `rule_ref` pointing into `policy_terms.json`. Stop on the
  timing column — vision in seconds, **every policy rule under a millisecond**.
  That is the "LLM never decides money" claim made visible.
- 30s on resilience: **TC011** in structured mode. Still APPROVED, fraud checker
  `DEGRADED`, confidence 0.78, review recommended, nothing crashed. The
  confidence arithmetic is readable down the delta column: `−0.20` at the
  degraded step, reconciled two rows later as `0.78 = base 0.98 −0.20`.
- Terminal: `uv run python -m app.eval.runner --with-uploads` → **12/12 and
  12/12**, and `uv run pytest` → **146 passing**.

## 3. Optional, if the clock allows (1–2 min)

Pick **one**, not both.

- **Assistant** — *"Why was &lt;claim&gt; rejected, and what should I tell the
  member?"* It explains from that claim's recorded trace, cites the clause, and
  drafts the member wording. Then ask *"Would a ₹9,000 dental claim be
  approved?"* and let it refuse: it explains what governs the answer and defers
  to the pipeline. Say that the refusal is enforced in code, not requested in a
  prompt.
- **Analytics** — the timing panel makes the same point as the trace at
  portfolio scale: extraction and retrieval cost seconds, the adjudication
  engine costs 2ms.

## 4. REQUIRED BEAT — proud of / would change (2 min)

**Proud: the LLM never decides money.** The adjudication engine is pure, ordered,
unit-tested Python over policy *data* — all 12 decision cases pass with the LLM
disabled entirely. GPT-4o answers only "what document is this?" and "what does it
say?", behind JSON-schema-validated contracts with a documented fallback for
every failure. That is why the eval is reproducible on a laptop with no accounts,
and why every rupee is explainable. The timing column proves it at a glance.

**Would change: I trusted the structured path for too long.** The 12 cases supply
document contents as data, and on that path the system read 12/12 while three
real defects sat in the upload path — a diagnostic claim that could never satisfy
its own document requirement, every upload silently fined 0.20 confidence for
fields its documents do not have, and a damaged file accused of being the wrong
document. Passing tests were measuring the wrong path. Given more time I would
have built the dual-path eval on day one rather than last, and I would extend the
same treatment to the browser layer, which is still the one place I assert rather
than verify. `docs/DEFECTS.md` records each one and the test that now pins it.

*(If asked what else you would change: retrieval for the assistant is measured —
recall 0.905@1 over 24 paraphrased cases — but on a 24-case set and one policy.
That set wants to be ten times bigger before the relevance floor deserves real
confidence.)*

## Close (30s)

- `docs/REVIEW_GUIDE.md` on screen: every claim in the docs has a command behind
  it.
- "At 10x": queue-backed async processing, materialised analytics columns,
  per-policy concept indexes, member-scoped auth — the seam is already threaded
  through every claim lookup. Details in ARCHITECTURE.md.
