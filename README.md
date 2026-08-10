# Plum — Health Insurance Claims Processing System

Automated OPD claim adjudication: document verification → extraction → policy
rules → `APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW`, with specific reasons,
a confidence score, and a complete decision trace for every claim.

**Docs:** [Architecture](docs/ARCHITECTURE.md) ·
[Component Contracts](docs/CONTRACTS.md) ·
[Eval Report — 12/12 structured, 12/12 uploaded](docs/EVAL_REPORT.md) ·
[Assumptions](docs/ASSUMPTIONS.md) ·
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

## Deploying

The console is a static bundle; the API is a long-lived process — Server-Sent
Events for the streaming trace, a ~10s cold start, native imaging dependencies,
and a writable uploads directory. So they deploy differently, and the API cannot
go on a static or serverless host.

**Console — Vercel or Netlify** (pick one; both are free and zero-config)

| | Vercel | Netlify |
|---|---|---|
| Setup | Import the repo, set **Root Directory** to `frontend`; Vite is auto-detected | `netlify.toml` in this repo already sets base/command/publish |
| Required env var | `VITE_API_URL` = the API's base URL, no trailing slash | same |

`VITE_API_URL` is read with `??`, not `||`, so the empty string means *same
origin* — that is what the single-service Docker path uses.

**API — Render** (native Python, no container)

`render.yaml` is a blueprint: Render → New → Blueprint → this repo. Then set the
secrets it marks `sync: false`. Alternatively, `Dockerfile` at the repo root
builds console and API into one image that serves both from one origin — use it
for Fly, Koyeb, or any container host, which also removes the `VITE_API_URL` and
CORS coordination.

**Everything optional is optional.** With no secrets set at all the deployment
still runs and the 12-case eval still passes: documents are trusted by their
declared type, the assistant retrieves clauses without explaining them, and the
stores fall back per the table in [ARCHITECTURE.md](docs/ARCHITECTURE.md). Set
`OPENAI_API_KEY`, `DATABASE_URL` and the `NEO4J_*` trio to light up vision, the
assistant, Postgres and the policy graph.

> **Before exposing a public URL with `OPENAI_API_KEY` set:** there is no
> authentication, so the API is an open proxy to that key. Set a hard monthly
> spend limit in the OpenAI dashboard — the worst case should be a dead key, not
> a bill.

Free tiers sleep. Render wakes in ~10s plus Neon's own cold start, during which
the console loads instantly and then waits on its first request — worth a
scheduled ping to `/health` if you are demoing on a link.

## Tests & eval

```bash
cd backend
uv run pytest                                    # 146 tests (148 with store credentials set)
uv run python -m app.eval.runner                 # regenerates docs/EVAL_REPORT.md (12/12)
uv run python -m app.eval.runner --with-uploads  # adds the vision run (needs OPENAI_API_KEY)
uv run python -m app.eval.retrieval              # assistant retrieval recall (needs OPENAI_API_KEY)
```

The eval passes **12/12 on every path**: the deterministic tier (no accounts,
no API key — reproducible anywhere), routed through the live knowledge stores
(`--with-kb`), and as real document uploads classified and read by GPT-4o
vision (`--with-uploads`). The last of those is the only one that can catch a
fault in *reading* a document — the structured cases arrive pre-typed, so they
are handed the answers.

## Repo layout

```
backend/
  app/
    api/           # FastAPI routes (claims, assistant, analytics, eval, health)
    orchestrator/  # pipeline + TraceBuilder (single writer of the trace)
    agents/        # verifier, extraction, GPT-4o wrapper, assistant
    engine/        # deterministic core: checks, financial, fraud, synthesizer
    kb/            # snapshot (typed policy lookups), semantic (Qdrant),
                   #   graph (Neo4j), retrieval (the assistant's knowledge base)
    models/        # Pydantic contracts for every boundary
    core/          # config, typed errors, claim store, portfolio analytics
    eval/          # runner → docs/EVAL_REPORT.md; retrieval recall eval
  scripts/         # mock medical document generator
  tests/
frontend/          # React console — see the views below
data/              # policy_terms.json, test_cases.json, mock documents
docs/              # review guide, architecture, contracts, assumptions,
                   #   eval report, defect record, demo script
```

## The console

Six views, all served by the running app:

| View | What it is |
|---|---|
| **Console** | Submit a claim — real files through vision, or an eval case as structured data — and read the decision, financial breakdown and streaming trace |
| **Assistant** | Ask why a claim was decided as it was, what the policy says, how the portfolio looks, or how the system works. Cites the clause behind every answer and refuses to predict a decision |
| **Analytics** | Portfolio figures over recorded decisions: decision mix, payout ratio, confidence distribution, why claims stop, where a claim's time goes |
| **Recent claims** | Every stored claim; pick one to re-read its decision and trace |
| **Eval report** | All 12 assignment cases on both paths, with full traces |
| **Docs** | Architecture, contracts, assumptions — rendered in-app, so the deployed URL carries its own evidence |

## Key properties

- **The LLM never decides money** — all 12 eval cases pass with the LLM
  disabled; GPT-4o only classifies/extracts documents, behind typed contracts.
- **Fail-fast for members, degrade for infrastructure** — wrong/unreadable
  documents stop early with instructions (no decision); component outages
  skip, lower confidence, and recommend review. Nothing returns a 500.
- **Every decision is reconstructable from its trace** — each rule check lands
  in the trace with outcome, specifics, rule reference, and confidence delta.
