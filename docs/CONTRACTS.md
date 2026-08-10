# Component Contracts

Every boundary is a Pydantic model in `backend/app/models/` — the definitions
below are precise enough to reimplement any component without reading its
code. Field-level detail lives in the models themselves (they carry
descriptions and validation rules).

## Document Verifier — `agents/verifier.py`

| | |
|---|---|
| **Input** | `ClaimSubmission`, `PolicySnapshot`, `TraceBuilder`, optional `DocumentAI` |
| **Output** | `VerifiedDocuments{documents: [VerifiedDocument], warnings: [str]}` — every document with a confirmed `doc_type` (`DECLARED` or `CLASSIFIED`), quality, and passthrough content |
| **Raises** | `DocumentVerificationStop{problems: [DocumentProblem]}` — each problem carries `kind` (`WRONG_TYPE`, `MISSING_REQUIRED`, `UNREADABLE`, `PATIENT_MISMATCH`, `UNCLASSIFIED`), `found`, `required`, member-facing `message`, and `action_needed` |
| **Guarantees** | Blocking problems name the exact file, the found type, and the required type. Non-blocking findings (poor quality, unverifiable registration) become warnings with trace confidence deltas, never stops. Classifier outage degrades to trusting the declared type. |

## Extraction Agent — `agents/extraction.py`

| | |
|---|---|
| **Input** | `[VerifiedDocument]`, optional `DocumentAI`, `TraceBuilder`, penalties accumulator |
| **Output** | `[ExtractedDocument{file_id, doc_type, quality, content: DocumentContent, field_confidence: {field: 0..1}, warnings, extraction_skipped}]` |
| **Raises** | `ComponentUnavailable(component="extraction_agent")` — only when a document has neither pre-extracted content nor a reachable vision path; the API maps this to 503 + retry guidance |
| **Guarantees** | Pre-extracted content is used verbatim (`extraction_skipped=True`, trace records it). Vision-extracted fields below 0.7 confidence add a −0.10 penalty and a `DEGRADED` trace step. |

## DocumentAI (LLM wrapper) — `agents/llm.py`

| | |
|---|---|
| **Input** | `classify(image_path)` / `extract(image_path, doc_type)` |
| **Output** | `(DocumentType, confidence, DocumentQuality)` / `(DocumentContent, field_confidence, warnings)` |
| **Raises** | `ComponentUnavailable("llm", …)` after bounded retries/timeout; never anything else |
| **Guarantees** | JSON-schema-constrained responses validated into typed models. `is_configured=False` (no API key) means callers never attempt a call — the system is fully functional without it. |

## Policy Snapshot — `kb/snapshot.py`

| | |
|---|---|
| **Input** | `PolicySnapshot.from_file(path)` → typed `PolicyTerms` |
| **Output** | Read-only lookups: `get_member`, `eligible_patients` (tolerates roster gaps), `effective_join_date` (dependents inherit primary's), `category_terms`, `document_requirements`, `per_claim_cap` = max(per_claim_limit, sub_limit), `waiting_period_end`, `is_network_hospital`, `policy_active_on` |
| **Raises** | `pydantic.ValidationError` at load time only — a malformed policy file fails at startup, never mid-claim |
| **Guarantees** | No policy *logic* (thresholds, ordering, decisions) — accessors only. |

## Adjudication Engine — `engine/adjudicator.py`

| | |
|---|---|
| **Input** | `ClaimSubmission`, `[ExtractedDocument]`, `PolicySnapshot` |
| **Output** | `Adjudication{checks: [RuleCheck], line_items: [LineItemDecision], eligible_amount, financial: FinancialBreakdown?, decision, rejection_reasons (primary first), notes}` |
| **Raises** | Nothing — pure function. Missing data yields `SKIPPED` checks with explanations. |
| **Guarantees** | All checks run even after a hard fail; check order fixed (see ARCHITECTURE.md); every `RuleCheck.detail` carries the specific numbers/dates it evaluated; `FinancialBreakdown.steps` records before/adjustment/after for each step in the graded order. |

## Fraud Checker — `engine/fraud.py`

| | |
|---|---|
| **Input** | `ClaimSubmission` (payload `claims_history` trusted), `FraudThresholds` |
| **Output** | `FraudAssessment{signals: [FraudSignal{code, detail}], requires_manual_review}` |
| **Raises** | Nothing |
| **Guarantees** | Signals name the evidence (claim ids, counts, limits). Flags route to review, never auto-reject. |

## Decision Synthesizer — `engine/synthesizer.py`

| | |
|---|---|
| **Input** | `ClaimSubmission`, `Adjudication`, `FraudAssessment`, penalties `[(reason, delta)]`, `TraceBuilder` |
| **Output** | `ClaimDecision{claim_id, decision, approved_amount, reasons: [str], rejection_reasons, confidence: 0..1, manual_review_recommended, fraud_signals, line_items, financial, degraded_components, trace}` |
| **Raises** | Nothing |
| **Guarantees** | Confidence = 0.98 + Σ penalties, clamped, thresholds per ARCHITECTURE.md; the rollup arithmetic is itself a trace step. |

## Pipeline — `orchestrator/pipeline.py`

| | |
|---|---|
| **Input** | `ClaimSubmission`, `PolicySnapshot`, optional `claim_id`, optional `DocumentAI` |
| **Output** | `ClaimDecision` **or** `DocumentProblemReport{status: "DOCUMENTS_REQUIRED", decision: null, problems, trace}` |
| **Raises** | `ComponentUnavailable` (undecidable extraction failure) — everything else is handled inside |
| **Guarantees** | Exactly one writer of the trace (`TraceBuilder`); `simulate_component_failure` exercises the same degradation machinery as a real outage. |

## Knowledge Base — `kb/retrieval.py`

| | |
|---|---|
| **Input** | `lookup_policy(path)`, `search_policy(text)`, `category_rules(category)`, `waiting_period(condition, member_id)`, `member(id, scope)`, `get_claim(id, scope)`, `find_claims(scope, …filters)`, `portfolio(scope)` |
| **Output** | Typed dicts, each carrying the `rule_ref` the engine stamps on decisions — so an answer's citations point at the same clauses a trace does |
| **Raises** | `Unavailable(source, detail)` — an unknown path, a claim outside scope, or a store that could not be reached. Never an exception the caller must translate |
| **Guarantees** | Exact lookups go to the snapshot (never a vector search); paraphrase search degrades Qdrant → token matcher; graph traversals degrade to the snapshot and say which source answered. `Scope` filters every claim read — a member scope refuses another member's claim with the same message as an unknown claim, so existence is not probeable. No method computes an amount or a verdict |

## Assistant — `agents/assistant.py`

| | |
|---|---|
| **Input** | `answer(messages, KnowledgeBase, Scope, claim_id=None)` |
| **Output** | `ChatAnswer{answer, citations, grounded, refusals, degraded_components, trace}` — the trace is a `DecisionTrace`, the same contract a claim's is |
| **Raises** | Nothing. A model outage, an unreachable source or a rejected answer all degrade |
| **Guarantees** | Answering is itself a tool call, so the reply is always structured. Two gates run before returning: every citation must be a reference retrieved *this turn*, and every rupee figure must have come from a tool or the user's own question. A gate failure returns retrieved material with `grounded: false` and the failed check named — never a generated answer presented as sourced. With no API key a deterministic router (claim id → store, else policy search) still answers |

## Claim Store — `core/store.py`

| | |
|---|---|
| **Input** | `save(ClaimSubmission, result)`, `get(claim_id)`, `list_recent(limit)`, `list_full(limit)`, `healthy()` |
| **Output** | Stored record: `{claim_id, submitted_at, member_id, category, status, submission, result}` (result includes the full trace). `list_recent` returns the index columns only; `list_full` adds `result` in one query, so aggregation never costs a round-trip per claim |
| **Raises** | `sqlite3.Error` — callers treat persistence failure as a warning on the response, never a crash |
| **Guarantees** | `ClaimStore` is a `Protocol`; SQLite is the zero-setup default, Postgres is a drop-in second implementation. |

## HTTP API — `api/routes.py`

| Endpoint | Contract |
|---|---|
| `POST /claims` | `ClaimSubmission` JSON → 200 with `ClaimDecision` or `DocumentProblemReport` (+ `persistence` flag). 422 invalid payload, 400 `IntakeError`, 503 `ComponentUnavailable` with retry guidance |
| `POST /claims/upload` | multipart: `metadata` JSON + `files` + `document_types` → same as above via the vision path |
| `GET /claims` / `GET /claims/{id}` / `GET /claims/{id}/trace` | Stored records; 404 when unknown |
| `POST /assistant/chat` | `{messages[], claim_id?, member_id?}` → `ChatAnswer`. Absent `member_id` = operations scope. Retrieval problems and ungrounded answers come back 200 with `grounded: false`; 422 on a malformed conversation |
| `GET /analytics` | Portfolio figures over the most recent `limit` claims: decision mix, payout ratio, confidence distribution, stop reasons, per-stage time, degraded runs. A stopped claim counts toward volume and stop reasons, never toward money or confidence. Store outage → 200 with `available: false` and empty totals, never a 5xx (see `core/analytics.py` for the definitions) |
| `GET /eval/cases` / `POST /eval/run` | The 12 assignment cases; run them and return per-case matched/mismatch |
| `GET /health` | Component status: policy id, member count, store health, LLM mode |
