# Plum — Health Insurance Claims Processing System

Automated OPD claim adjudication: document verification → extraction → policy
rules → `APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW`, with specific reasons,
a confidence score, and a complete decision trace for every claim.

**Docs:** [Architecture](docs/ARCHITECTURE.md) ·
[Component Contracts](docs/CONTRACTS.md) ·
[Assumptions](docs/ASSUMPTIONS.md) ·
[Eval Report — 12/12](docs/EVAL_REPORT.md) ·
[Demo Script](docs/DEMO_SCRIPT.md)

## Quick start

Prereqs: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 18+.

```bash
# Backend (from backend/) — http://localhost:8000, OpenAPI docs at /docs
cd backend
uv sync
uv run fastapi dev app/main.py

# Frontend (from frontend/) — http://localhost:5173
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, pick a test-case preset (TC001 = document stop,
TC004 = clean approval, TC010 = network-discount breakdown), submit, and read
the decision + trace.

### Optional: real document extraction

```bash
export OPENAI_API_KEY=sk-...   # enables GPT-4o classification/extraction
```

Without a key the system runs fully deterministic (declared document types +
pre-extracted content); with it, `POST /claims/upload` accepts real files.
Generate demo documents with `uv run python scripts/make_mock_docs.py`.

## Tests & eval

```bash
cd backend
uv run pytest                      # 75 tests: units, 12 pipeline cases, API
uv run python -m app.eval.runner   # regenerates docs/EVAL_REPORT.md (12/12)
```

## Repo layout

```
backend/
  app/
    api/           # FastAPI routes (POST /claims, /eval/run, /health, …)
    orchestrator/  # pipeline + TraceBuilder (single writer of the trace)
    agents/        # document verifier, extraction, GPT-4o wrapper
    engine/        # deterministic core: checks, financial, fraud, synthesizer
    kb/            # policy snapshot (typed lookups over policy_terms.json)
    models/        # Pydantic contracts for every boundary
    core/          # config, typed errors, claim store (SQLite; Postgres seam)
    eval/          # eval runner → docs/EVAL_REPORT.md
  scripts/         # mock medical document generator
  tests/
frontend/          # React console: submit, decision review, trace timeline
data/              # policy_terms.json, test_cases.json, mock documents
docs/              # architecture, contracts, assumptions, eval report
```

## Key properties

- **The LLM never decides money** — all 12 eval cases pass with the LLM
  disabled; GPT-4o only classifies/extracts documents, behind typed contracts.
- **Fail-fast for members, degrade for infrastructure** — wrong/unreadable
  documents stop early with instructions (no decision); component outages
  skip, lower confidence, and recommend review. Nothing returns a 500.
- **Every decision is reconstructable from its trace** — each rule check lands
  in the trace with outcome, specifics, rule reference, and confidence delta.
