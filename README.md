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

Open http://localhost:5173. The submit form has two modes:

- **Upload documents** (default) — attach real images/PDFs, as the assignment
  describes. Leave each type on *Auto-detect* and GPT-4o vision classifies and
  extracts them; declare a type instead and the system cross-checks your
  declaration against what the document actually is. Sample files live in
  `data/mock_documents/` (run `uv run python scripts/make_mock_docs.py`).
- **Structured (eval cases)** — replays the assignment's 12 test cases, which
  supply document contents as data rather than image files. Identical pipeline;
  only the extraction stage differs, and the trace records that it was skipped.

Either way, the decision, reasons, financial breakdown, and full trace appear
on the right. Good starting presets: TC001 (document stop), TC004 (clean
approval), TC010 (network-discount breakdown), TC011 (graceful degradation).

### Optional: LLM + knowledge/persistence stores

Everything below is **optional and independently activated** — absent, the
system runs fully deterministic with tested fallbacks (SQLite, token
matching, in-memory policy snapshot) and the eval still passes 12/12.

```bash
# GPT-4o document classification/extraction + embeddings for the vector index
export OPENAI_API_KEY=sk-...

# Postgres system of record (Neon free tier: console.neon.tech -> copy DSN)
export DATABASE_URL=postgresql://user:pass@host/db

# Neo4j AuraDB policy graph (free tier: console.neo4j.io -> create instance)
export NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io
export NEO4J_PASSWORD=...

# Qdrant: runs EMBEDDED locally by default (no account needed).
# For Qdrant Cloud instead: export QDRANT_URL=... and QDRANT_API_KEY=...
```

Then load the knowledge stores and verify them:

```bash
uv run python -m app.kb.ingest             # policy_terms.json -> Qdrant + Neo4j
uv run python scripts/verify_kb.py         # live check of all three stores
uv run python -m app.eval.runner --with-kb # 12/12 through the live stores
```

`GET /health` reports each store's live status (connected / fallback /
disabled). Generate demo documents for the real-upload path with
`uv run python scripts/make_mock_docs.py`.

## Tests & eval

```bash
cd backend
uv run pytest                      # 83 tests (85 with store credentials set)
uv run python -m app.eval.runner   # regenerates docs/EVAL_REPORT.md (12/12)
```

The eval passes **12/12 both ways**: on the deterministic tier (no accounts,
no API key — reproducible anywhere) and routed through the live knowledge
stores (`--with-kb`).

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
