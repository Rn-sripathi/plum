"""HTTP API (PLAN.md §8).

A stopped claim (document problems) is a successful HTTP interaction — 200
with `status: DOCUMENTS_REQUIRED` — never a 5xx. Only infrastructure failure
that prevents any decision (extraction with no fallback) returns 503, with
retry guidance.
"""

import json
import queue
import threading
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError

from app.core.config import settings
from app.core.errors import ComponentUnavailable, IntakeError
from app.eval.runner import run_all
from app.models import ClaimSubmission, DocumentType
from app.models.claim import SubmittedDocument
from app.orchestrator.pipeline import process_claim

router = APIRouter()


def _submission_from_upload(
    metadata: str, files: list[UploadFile], document_types: str
) -> ClaimSubmission:
    """Turn a multipart upload into a validated ClaimSubmission.

    Shared by the buffered and streaming upload routes so both reject bad
    input identically (422, never a 500).
    """
    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"metadata is not valid JSON: {exc}") from exc

    if not files:
        raise HTTPException(
            422,
            "A claim needs at least one document. Attach the bill, prescription, or "
            "report for this treatment (images or PDFs) and submit again.",
        )

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
    try:
        return ClaimSubmission.model_validate(meta)
    except ValidationError as exc:
        # Bad metadata must read like a form error, never a server crash.
        raise HTTPException(422, json.loads(exc.json())) from exc


def _document_summaries(submission: ClaimSubmission) -> list[dict]:
    """What documents this claim carried, and which can be previewed.

    Eval-case documents arrive as structured data with no file behind them,
    so `previewable` tells the UI whether an image is fetchable.
    """
    return [
        {
            "file_id": d.file_id,
            "file_name": d.file_name,
            "doc_type": d.actual_type.value if d.actual_type else None,
            "previewable": bool(d.storage_path),
        }
        for d in submission.documents
    ]


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _stream_claim(request: Request, submission: ClaimSubmission) -> StreamingResponse:
    """Run the pipeline and emit each trace step as it happens.

    The decision is streamed while it is being made, so a reviewer watches the
    checks land in order rather than receiving a verdict with an explanation
    attached after the fact. Events: `step` per trace step, then exactly one
    terminal `result` or `error`.
    """
    state = request.app.state
    events: queue.Queue = queue.Queue()
    done = object()

    def on_step(step) -> None:
        events.put(("step", json.loads(step.model_dump_json())))

    def run() -> None:
        try:
            result = process_claim(
                submission,
                state.snapshot,
                doc_ai=state.doc_ai,
                semantic=state.semantic,
                graph=state.graph,
                on_step=on_step,
            )
            payload = json.loads(result.model_dump_json())
            payload["documents"] = _document_summaries(submission)
            try:
                state.store.save(submission, result)
                payload["persistence"] = "ok"
            except Exception as exc:
                payload["persistence"] = f"failed: {exc}"
            events.put(("result", payload))
        except ComponentUnavailable as exc:
            events.put((
                "error",
                {
                    "error": exc.code,
                    "component": exc.component,
                    "message": exc.message,
                    "guidance": "The claim was not decided. Retry once the component recovers.",
                },
            ))
        except Exception as exc:  # last resort — the stream still closes cleanly
            events.put(("error", {"error": "UNEXPECTED", "message": str(exc)}))
        finally:
            events.put(done)

    threading.Thread(target=run, daemon=True).start()

    def generate():
        while True:
            item = events.get()
            if item is done:
                return
            event, data = item
            yield _sse(event, data)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    payload["documents"] = _document_summaries(submission)
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


@router.post("/claims/stream")
def submit_claim_streaming(request: Request, submission: ClaimSubmission) -> StreamingResponse:
    """Same as POST /claims, streamed as Server-Sent Events."""
    return _stream_claim(request, submission)


@router.post("/claims/upload/stream")
def submit_claim_with_files_streaming(
    request: Request,
    metadata: str = Form(description="ClaimSubmission JSON without document content"),
    files: list[UploadFile] = File(default=[]),
    document_types: str = Form(default=""),
) -> StreamingResponse:
    """Upload path, streamed. Most useful here: vision classification and
    extraction take seconds per document, so each step lands as it completes."""
    submission = _submission_from_upload(metadata, files, document_types)
    return _stream_claim(request, submission)


@router.post("/claims/upload")
def submit_claim_with_files(
    request: Request,
    metadata: str = Form(description="ClaimSubmission JSON without document content"),
    files: list[UploadFile] = File(default=[]),
    document_types: str = Form(default="", description="Comma-separated declared type per file, in order"),
) -> dict:
    """Submit a claim with real document files (vision extraction path)."""
    submission = _submission_from_upload(metadata, files, document_types)
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


@router.get("/claims/{claim_id}/documents/{file_id}")
def get_claim_document(request: Request, claim_id: str, file_id: str) -> FileResponse:
    """Serve one uploaded document so a reviewer can read it beside the decision.

    Only files referenced by a stored claim are served, and the resolved path
    must sit inside the upload directory — a stored path must never be able to
    reach elsewhere on disk.
    """
    record = request.app.state.store.get(claim_id)
    if record is None:
        raise HTTPException(404, f"No claim '{claim_id}'.")
    document = next(
        (d for d in record["submission"]["documents"] if d.get("file_id") == file_id), None
    )
    if document is None:
        raise HTTPException(404, f"Claim '{claim_id}' has no document '{file_id}'.")
    stored = document.get("storage_path")
    if not stored:
        raise HTTPException(
            404,
            f"Document '{file_id}' was submitted as structured data, not an uploaded file.",
        )
    path = Path(stored).resolve()
    root = settings.upload_path.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, f"The file for document '{file_id}' is no longer available.")
    return FileResponse(path, filename=document.get("file_name") or path.name)


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
