# Architecture

Automated adjudication of OPD health-insurance claims: a member submits claim
details plus medical documents; the system verifies the documents, extracts
structured data, applies the policy rules from `policy_terms.json`, and returns
`APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW` with the approved amount,
specific reasons, a confidence score, and a **complete decision trace**.

## Design principles

1. **The LLM never decides money.** GPT-4o is used for exactly two judgment
   calls — "what kind of document is this?" and "what does it say?" — both
   behind typed contracts with validation. Every rupee of the decision comes
   from deterministic, unit-tested Python interpreting policy data.
2. **The trace is a first-class output, not a log.** Every component appends
   typed `TraceStep`s (component, action, outcome, detail, confidence delta,
   rule reference). The test of done-ness: operations can reconstruct any
   decision from the trace alone.
3. **Two failure regimes, never confused.** Problems the *member* can fix
   (wrong document, unreadable photo, mismatched patients) stop the pipeline
   early with specific instructions and **no decision**. Problems in *our
   infrastructure* (LLM down, store down) degrade: the pipeline continues,
   the trace records what was skipped, confidence drops, and manual review is
   recommended. Nothing crashes either way.
4. **Policy is data, not code.** The engine interprets `policy_terms.json`
   through typed lookups. A new policy is a data change; no rule is hardcoded.

## Component map

```mermaid
flowchart TD
    UI[React UI\nsubmit · review · trace] --> API[FastAPI\napi/routes.py]
    API --> P[Pipeline\norchestrator/pipeline.py\nowns TraceBuilder]
    P --> V[Document Verifier\nagents/verifier.py]
    V -->|member-fixable problem| STOP[DocumentProblemReport\nno decision, specific actions]
    V --> X[Extraction Agent\nagents/extraction.py\ntest mode / GPT-4o vision]
    X --> A[Adjudication Engine\nengine/* — deterministic, zero LLM]
    A --> F[Fraud Checker\nengine/fraud.py]
    F --> S[Decision Synthesizer\nengine/synthesizer.py\nconfidence rollup]
    S --> OUT[ClaimDecision\namount · reasons · confidence · trace]
    A -.reads.-> KB[(PolicySnapshot\nkb/snapshot.py)]
    X -.calls.-> LLM[DocumentAI\nagents/llm.py\nGPT-4o, optional]
    P -.persists.-> DB[(ClaimStore\ncore/store.py — SQLite,\nPostgres seam)]
```

### Pipeline stages

| # | Stage | Responsibility | On failure |
|---|-------|---------------|-----------|
| 1 | Intake | Payload validation (Pydantic at the API boundary) | 422/400, never enters pipeline |
| 2 | Document Verifier | Required types per category, readability, cross-document patient consistency, registration-number format | Member-fixable → early stop with `DocumentProblem`s; classifier outage → trust declared type, flag unverified |
| 3 | Extraction | Pre-extracted content (test mode) or GPT-4o vision with per-field confidence | LLM down + no content → 503 with retry guidance (the one undecidable failure) |
| 4 | Adjudication Engine | Ordered rule checks (below), line-item verdicts, financial breakdown | Pure function — cannot fail; unknown data → `SKIPPED` check |
| 5 | Fraud Checker | Velocity rules (same-day/monthly), high-value threshold | Skipped → decision still produced, confidence −0.20, review recommended (TC011) |
| 6 | Synthesizer | Decision + confidence rollup + human-readable reasons | Pure function — always returns |

### Adjudication rule order (deterministic, all checks always run)

1. Eligibility (member in roster, policy active)
2. Submission rules (30-day deadline, ₹500 minimum)
3. **Exclusions** — before waiting periods: an excluded condition is *never*
   covered, so it must win the primary rejection reason over a merely
   time-bound rule. (Discovered via TC012: "Morbid Obesity" matches both the
   `obesity_treatment` waiting period and the obesity exclusion.)
4. Waiting periods — initial 30d + condition-specific; the rejection message
   states the exact date the member becomes eligible
5. Pre-authorization — named high-value tests above the category threshold
6. Line-item adjudication — covered/excluded per item → PARTIAL when mixed
7. Per-claim limit — checked on the **eligible amount** (after excluded items)
   against `max(per_claim_limit, category sub_limit)` — see ASSUMPTIONS.md #5
8. Financial computation, **order graded**: eligible base → network discount →
   co-pay → sub-limit cap → annual limit

The first failing check sets the primary rejection reason; every other
violation still lands in the trace so ops sees the whole picture.

### Confidence model

Start at 0.98 (never claim certainty), subtract per signal: degraded component
−0.20, poor-quality document −0.10, low-confidence extracted fields −0.10,
un-itemized bill −0.05, unverifiable registration −0.05. Below 0.50 →
`MANUAL_REVIEW`; 0.50–0.75 → decision stands with `manual_review_recommended`;
any degraded component also forces the recommendation. Every delta appears in
the trace next to the step that caused it.

## Decisions considered and rejected

| Considered | Rejected because |
|---|---|
| **LLM-driven adjudication** (hand the policy + claim to GPT and ask for a decision) | Unauditable, non-reproducible, and wrong on arithmetic ordering (TC010-style money math). The 12 decision cases pass with the LLM completely disabled — that's the property we wanted. |
| **Qdrant + Neo4j knowledge stores** (embedding search for exclusion matching; policy-as-graph) | Planned (PLAN.md §5) and designed with fallbacks from day one; cut on the 2–3 day timebox exactly as the plan's cut line prescribed. The deterministic token matcher (`engine/matching.py`) passes all 12 cases with explainable matches (`matched on: obesity`); the matcher is an interface seam where an embedding tier slots in without touching the engine. |
| **Postgres from day one** | Cloud provisioning friction for a reviewer running locally. `ClaimStore` is a protocol; SQLite implements it with zero setup, Postgres is a second implementation away. |
| **Separate eval harness repo/scripts** | The eval runner lives in the app (`app/eval/runner.py`) and doubles as an API endpoint (`POST /eval/run`), so the report can never drift from the shipped pipeline. |
| **Rejecting claims on fraud signals** | Signals route to `MANUAL_REVIEW` with named evidence instead — false-positive rejections are the most expensive mistake in claims UX. |

## Known limitations, and the 10x plan

| Limitation today | At 10x load |
|---|---|
| Synchronous processing: the API decides in-request (fine at ~1s deterministic path) | Queue-backed async: `POST /claims` returns `202 + claim_id`, workers consume; UI already polls `GET /claims/{id}` |
| SQLite single-writer | Postgres (JSONB for traces — they're already JSON), read replicas for the review console |
| Token-overlap semantic matching | Embedding index (Qdrant) as tier 1, LLM confirmation for the gray zone, token matcher stays as the always-on fallback; per-policy concept index rebuilt on policy ingestion |
| One policy, in-memory snapshot | Policy registry keyed by `policy_id` with versioning (claims must adjudicate against the terms in force on the treatment date); snapshot cache per policy |
| Vision extraction is per-document, sequential | Batch/parallel extraction (`asyncio.gather` over documents), response caching keyed by file hash |
| No auth | Member-scoped tokens; ops console behind SSO; PII encryption at rest |
| Fraud checker sees only payload-supplied history | Claims history from the store (same member/provider velocity across submissions), plus `DOCUMENT_ALTERATION` signals from extraction |

## Testing strategy

75 tests, three layers: **unit** (matching rules, financial ordering and
rounding, fraud boundaries, snapshot lookups), **pipeline** (all 12 assignment
cases end-to-end, asserting decisions, amounts, reason codes, message
specificity, trace completeness), **API** (HTTP contracts: 200-with-problems
for member-fixable stops, 503-with-guidance for undecidable infrastructure
failure, persistence round-trips). `POST /eval/run` regenerates the eval
verdict on demand; `docs/EVAL_REPORT.md` is the committed snapshot.
