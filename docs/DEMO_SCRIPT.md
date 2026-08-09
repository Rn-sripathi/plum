# Demo Video Script (8–12 minutes)

Setup before recording: backend running (`uv run fastapi dev app/main.py`),
frontend running (`npm run dev`), browser at http://localhost:5173, a terminal
visible for the eval run. Practice once — the three required beats are marked.

## 0. Framing (1 min)

- One sentence on the problem: manual claim review is slow and inconsistent.
- One sentence on the shape: a deterministic adjudication pipeline with a
  fail-fast document gate, an LLM used only to read documents (never to decide
  money), and a trace that lets ops reconstruct any decision.
- Show the health badge in the UI top bar: policy loaded, store healthy,
  "llm disabled (deterministic mode)" — point out everything you're about to
  see runs with no LLM at all.

## 1. REQUIRED BEAT — claim stopped early by a document problem (2–3 min)

**Lead with real files** (stronger than the JSON path): in **Upload documents**
mode, attach `data/mock_documents/prescription_rajesh.jpg` *twice* for a
CONSULTATION claim, leaving both types on **Auto-detect**. GPT-4o vision
classifies both images as PRESCRIPTION and the verifier stops the claim —
nothing was *declared*, the system read the images and worked out what they
were. Then switch to **Structured (eval cases)** mode and load preset **TC001**
to show the same behavior on the assignment's own test case.

- Submit. Point at the result: **no decision was made** — status
  `DOCUMENTS REQUIRED`.
- Read the message aloud: it names what was uploaded (PRESCRIPTION), what is
  required (HOSPITAL_BILL), and the exact action. "A generic error is not
  acceptable" — this is the opposite.
- Quickly show **TC002** (blurry bill → re-upload that one file, claim not
  rejected) and **TC003** (documents for two different patients, both names
  surfaced).
- Show the trace panel: the verifier's FAIL step, and that processing stopped
  before any adjudication step ran.

## 2. REQUIRED BEAT — end-to-end approval with the full trace (3–4 min)

- Load preset **TC010** (Apollo Hospitals — network discount).
- Submit. Walk the decision: APPROVED ₹3,240 of ₹4,500, confidence 98%.
- Walk the **financial breakdown table**: eligible base 4,500 → network
  discount 20% → 3,600 → co-pay 10% → 3,240 — emphasize the order is a graded
  policy rule, computed by deterministic code.
- Walk the **trace timeline** top to bottom: every §6 rule check (eligibility,
  deadline, exclusions, waiting periods, pre-auth, line items, per-claim cap)
  with PASS/FAIL, the exact numbers it looked at, and the rule reference into
  `policy_terms.json`.
- Bonus 30s: load **TC011** — simulated component failure. Decision still
  APPROVED, fraud checker step shows DEGRADED, confidence dropped to 0.78,
  "manual review recommended". Nothing crashed.
- In the terminal: `uv run python -m app.eval.runner` → **12/12**, and
  `uv run pytest` → 75 passing.

## 3. REQUIRED BEAT — one decision I'm proud of, one I'd change (2–3 min)

**Proud: the LLM never decides money.** The adjudication engine is pure,
ordered, unit-tested Python over policy *data* — all 12 cases pass with the
LLM disabled. GPT-4o only answers "what document is this?" and "what does it
say?", behind JSON-schema-validated contracts, with a documented fallback for
every failure (trust declared type / proceed on supplied content / stop with
retry guidance). That's why the eval is reproducible and every rupee is
explainable.

**Would change: semantic matching is token-based.** `engine/matching.py` maps
free text onto policy concepts by distinctive-token overlap — explainable and
sufficient for the eval ("Morbid Obesity" → obesity exclusion, "Herniation" ≠
`hernia`), but it will miss paraphrases ("sugar complaint" → diabetes). The
plan's Qdrant embedding tier was cut on the timebox; the matcher is an
interface seam, so the upgrade path is: embedding search as tier 1, LLM
confirmation in the gray zone, tokens as the always-on fallback. Mention the
other trade-offs live in ASSUMPTIONS.md — judgment about what to cut was part
of the design.

## Close (30s)

- Repo layout on screen: engine / agents / orchestrator / models — contracts
  per component in docs/CONTRACTS.md.
- "At 10x": queue-backed async processing, Postgres behind the existing store
  protocol, per-policy concept indexes — details in ARCHITECTURE.md.
