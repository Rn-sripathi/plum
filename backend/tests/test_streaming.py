"""Streaming decisions: trace steps must arrive as Server-Sent Events while the
pipeline runs, followed by exactly one terminal result/error event."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "claims.db"
    with TestClient(create_app(database_path=db)) as c:
        yield c


@pytest.fixture(scope="module")
def by_id(test_cases):
    return {c["case_id"]: c["input"] for c in test_cases}


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for frame in text.split("\n\n"):
        name, payload = "message", None
        for line in frame.split("\n"):
            if line.startswith("event: "):
                name = line[7:].strip()
            elif line.startswith("data: "):
                payload = line[6:]
        if payload is not None:
            events.append((name, json.loads(payload)))
    return events


def test_decision_streams_steps_then_result(client, by_id):
    resp = client.post("/claims/stream", json=by_id["TC004"])
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(resp.text)
    names = [n for n, _ in events]
    assert names.count("result") == 1
    assert names[-1] == "result", "the result must be the terminal event"
    assert names.count("error") == 0

    steps = [d for n, d in events if n == "step"]
    assert len(steps) >= 5
    assert [s["seq"] for s in steps] == list(range(1, len(steps) + 1))
    assert {"component", "action", "outcome", "detail"} <= steps[0].keys()

    result = events[-1][1]
    assert result["decision"] == "APPROVED"
    assert result["approved_amount"] == "1350.00"
    # Streamed steps and the persisted trace must agree exactly.
    assert [s["seq"] for s in result["trace"]["steps"]] == [s["seq"] for s in steps]


def test_document_stop_streams_then_reports_problems(client, by_id):
    events = parse_sse(client.post("/claims/stream", json=by_id["TC001"]).text)
    assert [n for n, _ in events][-1] == "result"
    result = events[-1][1]
    assert result["status"] == "DOCUMENTS_REQUIRED"
    assert result["problems"][0]["required"] == "HOSPITAL_BILL"
    # The verifier's failing step was streamed before the stop.
    assert any(
        d["component"] == "document_verifier" and d["outcome"] == "FAIL"
        for n, d in events
        if n == "step"
    )


def test_streamed_claim_is_persisted(client, by_id):
    result = parse_sse(client.post("/claims/stream", json=by_id["TC010"]).text)[-1][1]
    assert result["persistence"] == "ok"
    stored = client.get(f"/claims/{result['claim_id']}").json()
    assert stored["status"] == "APPROVED"


def test_undecidable_failure_streams_error_event(client, by_id, tmp_path):
    """No LLM configured + real files -> terminal `error`, not a broken stream."""
    from PIL import Image

    page = tmp_path / "page.jpg"
    Image.new("RGB", (300, 400), "white").save(page)
    meta = dict(by_id["TC004"])
    meta.pop("documents")

    resp = client.post(
        "/claims/upload/stream",
        data={"metadata": json.dumps(meta), "document_types": "PRESCRIPTION,HOSPITAL_BILL"},
        files=[
            ("files", ("rx.jpg", page.read_bytes(), "image/jpeg")),
            ("files", ("bill.jpg", page.read_bytes(), "image/jpeg")),
        ],
    )
    events = parse_sse(resp.text)
    name, payload = events[-1]
    assert name == "error"
    assert payload["component"] == "extraction_agent"
    assert "Retry" in payload["guidance"]


def test_streaming_upload_rejects_empty_document_set(client, by_id):
    meta = dict(by_id["TC004"])
    meta.pop("documents")
    resp = client.post(
        "/claims/upload/stream", data={"metadata": json.dumps(meta), "document_types": ""}
    )
    assert resp.status_code == 422
