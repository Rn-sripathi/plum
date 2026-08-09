"""HTTP API (PLAN.md §8).

A stopped claim (document problems) is a successful HTTP interaction — 200
with `status: DOCUMENTS_REQUIRED` — never a 5xx. Only infrastructure failure
that prevents any decision (extraction with no fallback) returns 503, with
retry guidance.
"""

import json
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.core.config import settings
from app.core.errors import ComponentUnavailable, IntakeError
from app.eval.runner import run_all
from app.models import ClaimSubmission, DocumentType
from app.models.claim import SubmittedDocument
from app.orchestrator.pipeline import process_claim

router = APIRouter()


def _process_and_store(request: Request, submission: ClaimSubmission) -> dict:
    state = request.app.state
    result = process_claim(
        submission,
        state.snapshot,
        doc_ai=state.doc_ai,
        semantic=state.semantic,
        graph=state.graph,
    )
    payload = json.loads(result.model_dump_json())
    try:
        state.store.save(submission, result)
        payload["persistence"] = "ok"
    except Exception as exc:  # store outage: decision still returned (PLAN §4)
        payload["persistence"] = f"failed: {exc}"
    return payload


@router.post("/claims")
def submit_claim(request: Request, submission: ClaimSubmission) -> dict:
    """Submit a claim as JSON (documents pre-typed, optionally pre-extracted)."""
    return _process_and_store(request, submission)


@router.post("/claims/upload")
def submit_claim_with_files(
    request: Request,
    metadata: str = Form(description="ClaimSubmission JSON without document content"),
    files: list[UploadFile] = File(default=[]),
    document_types: str = Form(default="", description="Comma-separated declared type per file, in order"),
) -> dict:
    """Submit a claim with real document files (vision extraction path)."""
    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"metadata is not valid JSON: {exc}") from exc

    declared = [t.strip() or None for t in document_types.split(",")] if document_types else []
    upload_root = settings.upload_path / uuid4().hex[:12]
    upload_root.mkdir(parents=True, exist_ok=True)
    documents = []
    for i, file in enumerate(files):
        dest = upload_root / (file.filename or f"file_{i}")
        dest.write_bytes(file.file.read())
        declared_type = declared[i] if i < len(declared) else None
        documents.append(
            SubmittedDocument(
                file_id=f"F{i + 1:03d}",
                file_name=file.filename,
                actual_type=DocumentType(declared_type) if declared_type else None,
                storage_path=str(dest),
            )
        )
    meta["documents"] = [d.model_dump(mode="json") for d in documents]
    submission = ClaimSubmission.model_validate(meta)
    return _process_and_store(request, submission)


@router.get("/claims")
def list_claims(request: Request, limit: int = 50) -> list[dict]:
    return request.app.state.store.list_recent(limit)


@router.get("/claims/{claim_id}")
def get_claim(request: Request, claim_id: str) -> dict:
    record = request.app.state.store.get(claim_id)
    if record is None:
        raise HTTPException(404, f"No claim '{claim_id}'.")
    return record


@router.get("/claims/{claim_id}/trace")
def get_trace(request: Request, claim_id: str) -> dict:
    record = request.app.state.store.get(claim_id)
    if record is None:
        raise HTTPException(404, f"No claim '{claim_id}'.")
    return record["result"]["trace"]


@router.get("/eval/cases")
def eval_cases() -> dict:
    """The 12 assignment test cases — used by the UI as submission presets."""
    return json.loads(settings.test_cases_path.read_text(encoding="utf-8"))


@router.post("/eval/run")
def run_eval() -> dict:
    results = run_all()
    return {
        "total": len(results),
        "matched": sum(1 for r in results if r.matched),
        "cases": [
            {
                "case_id": r.case_id,
                "case_name": r.case_name,
                "decision": r.decision_label,
                "matched": r.matched,
                "mismatches": r.mismatches,
            }
            for r in results
        ],
    }


@router.get("/health")
def health(request: Request) -> dict:
    state = request.app.state
    store_kind = type(state.store).__name__.removesuffix("ClaimStore").lower()
    if state.semantic.is_configured:
        semantic_status = "ready" if state.semantic.healthy() else "configured, not ingested"
    else:
        semantic_status = "disabled (no OPENAI_API_KEY — token matching only)"
    if state.graph.is_configured:
        graph_status = "connected" if state.graph.healthy() else "configured, unreachable (snapshot fallback)"
    else:
        graph_status = "not configured (snapshot only)"
    return {
        "status": "ok",
        "policy": state.snapshot.terms.policy_id,
        "members": len(state.snapshot.terms.members),
        "store": f"{store_kind}: {'healthy' if state.store.healthy() else 'unavailable'}",
        "llm": "configured" if state.doc_ai.is_configured else "disabled (deterministic mode)",
        "semantic_index": semantic_status,
        "policy_graph": graph_status,
    }


def register_error_handlers(app) -> None:
    from fastapi.responses import JSONResponse

    @app.exception_handler(ComponentUnavailable)
    async def component_unavailable(_, exc: ComponentUnavailable):
        return JSONResponse(
            status_code=503,
            content={
                "error": exc.code,
                "component": exc.component,
                "message": exc.message,
                "guidance": "The claim was not decided. Retry once the component recovers.",
            },
        )

    @app.exception_handler(IntakeError)
    async def intake_error(_, exc: IntakeError):
        return JSONResponse(
            status_code=400,
            content={"error": exc.code, "field": exc.field, "message": exc.message},
        )
