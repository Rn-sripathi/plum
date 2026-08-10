# Review guide — what to look at, and how to check it

Written for someone with twenty minutes who would rather verify than be told.
Every claim below has a command or a screen behind it.

Setup is two commands (`backend/`: `uv sync && uv run fastapi dev app/main.py`;
`frontend/`: `npm install && npm run dev`). **No API key or account is needed** —
without them the system runs deterministic and the 12-case eval still passes.
Set `OPENAI_API_KEY` to exercise the vision and assistant paths.

## The twenty-minute path

| # | Do this | What it demonstrates |
|---|---|---|
| 1 | `uv run pytest` | 146 pass, 3 skipped (the skips need live store credentials) |
| 2 | `uv run python -m app.eval.runner` | 12/12, and rewrites `EVAL_REPORT.md` from the shipped pipeline — the report cannot drift from the code. (Add `--with-uploads` to reproduce the committed version, which carries the vision run too) |
| 3 | Console → upload `data/mock_documents/prescription_rajesh.jpg` **twice** as a CONSULTATION claim | The document gate stops it with no decision, naming what was uploaded and what was required |
| 4 | Console → `prescription_rajesh.jpg` + `hospital_bill_city_clinic.jpg` | APPROVED ₹1,350, and the trace shows every check with its cost |
| 5 | Open **How this was answered** / the trace timing column | Where a claim's seconds go: vision in seconds, every policy rule in under a millisecond |
| 6 | **Analytics** | Portfolio figures, and the same numbers the assistant quotes |
| 7 | **Assistant** → *"Why was &lt;claim id&gt; rejected, and what should I tell the member?"* | An explanation drawn from that claim's recorded trace, with the clause cited |
| 8 | **Assistant** → *"Would a ₹9,000 dental claim be approved?"* | It explains what governs the answer and refuses to predict one |

## Claim → where to check it

| The claim | Check it here |
|---|---|
| "The LLM never decides money" | `uv run pytest tests/test_decision_cases.py` — all 12 decisions pass with the LLM disabled. `engine/` imports no LLM at all |
| "Policy is data, not code" | Every check stamps a `rule_ref` into `policy_terms.json`; change a percentage in the file and the decision, the explanation and the citation all move together |
| "Any decision is reconstructible from the trace" | Any claim in **Recent claims** → the trace lists each check in order with its outcome, the numbers it looked at, its rule reference, its confidence delta and its duration. Step 21 of a degraded claim shows `−0.20`; step 22 reconciles it as `0.78 = base 0.98 −0.20` |
| "Failures degrade, they never crash" | TC011 (`simulate_component_failure`) → still APPROVED, fraud checker skipped, confidence lowered, review recommended. Kill Postgres mid-run → decision still returned with `persistence: failed` |
| "Document problems are specific and actionable" | `docs/EVAL_REPORT.md` TC001–TC003, plus `tests/test_upload_verification.py` for the cases the eval cannot reach (damaged file, multi-page PDF) |
| "Both paths agree" | `uv run python -m app.eval.runner --with-uploads` → 12/12 structured **and** 12/12 as real files through GPT-4o vision, scored by identical expectations |
| "The assistant cannot invent" | `uv run pytest tests/test_assistant.py` — 25 tests covering scope isolation and the three grounding gates |
| "Retrieval actually finds the right clause" | `uv run python -m app.eval.retrieval` → recall 0.905@1, 1.0@3 over 24 paraphrased cases |
| "Every store is optional" | Unset every credential and repeat steps 1–4. Qdrant → token matcher, Neo4j → snapshot, Postgres → SQLite, GPT-4o → declared types |

## Reading order for the documents

1. **[ARCHITECTURE.md](ARCHITECTURE.md)** — the components, the two paths, the rule
   order, the confidence model, what was considered and rejected, and the 10x plan.
2. **[CONTRACTS.md](CONTRACTS.md)** — every component's input, output, errors and
   guarantees, precise enough to reimplement one without reading its code.
3. **[EVAL_REPORT.md](EVAL_REPORT.md)** — all 12 cases on both paths, each with its
   full decision output and complete trace.
4. **[ASSUMPTIONS.md](ASSUMPTIONS.md)** — 14 decisions where the spec or the data was
   ambiguous, each with the reasoning and the case that forced it.
5. **[DEFECTS.md](DEFECTS.md)** — what running the system found that reading it did
   not, and what changed as a result.

## Where the interesting code is

| Read this | Because |
|---|---|
| `engine/financial.py` | The ordered money computation. Network discount before co-pay is a graded rule, and each step records its own `rule_ref` |
| `agents/verifier.py` | The fail-fast gate, and the comments explaining why legibility is measured in code rather than asked of the model |
| `orchestrator/trace.py` | The single writer of the trace — the observability contract in 90 lines |
| `agents/assistant.py` | The tool loop and the three gates that keep a chat surface from becoming a second adjudicator |
| `core/analytics.py` | Portfolio definitions, including why a stopped claim is not a rejection |
