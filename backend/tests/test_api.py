"""API tests — submission, retrieval, early stop, eval, health."""

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


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["policy"] == "PLUM_GHI_2024"
    assert body["store"] == "sqlite: healthy"
    assert "token matching" in body["semantic_index"]
    assert body["policy_graph"] == "not configured (snapshot only)"


def test_submit_and_fetch_decision(client, by_id):
    resp = client.post("/claims", json=by_id["TC004"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "APPROVED"
    assert body["approved_amount"] == "1350.00"
    assert body["persistence"] == "ok"

    claim_id = body["claim_id"]
    stored = client.get(f"/claims/{claim_id}").json()
    assert stored["status"] == "APPROVED"
    assert stored["result"]["decision"] == "APPROVED"

    trace = client.get(f"/claims/{claim_id}/trace").json()
    assert len(trace["steps"]) >= 5


def test_document_problem_is_200_not_500(client, by_id):
    resp = client.post("/claims", json=by_id["TC001"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "DOCUMENTS_REQUIRED"
    assert body["decision"] is None
    assert body["problems"][0]["required"] == "HOSPITAL_BILL"


def test_invalid_payload_is_422(client):
    resp = client.post("/claims", json={"member_id": "EMP001"})
    assert resp.status_code == 422


def test_unknown_claim_is_404(client):
    assert client.get("/claims/NOPE").status_code == 404


def test_upload_without_llm_returns_503_with_guidance(client, by_id):
    meta = dict(by_id["TC004"])
    meta.pop("documents")
    resp = client.post(
        "/claims/upload",
        data={"metadata": __import__("json").dumps(meta), "document_types": "PRESCRIPTION,HOSPITAL_BILL"},
        files=[
            ("files", ("rx.jpg", b"fake-image-bytes", "image/jpeg")),
            ("files", ("bill.jpg", b"fake-image-bytes", "image/jpeg")),
        ],
    )
    assert resp.status_code == 503
    body = resp.json()
    assert body["component"] == "extraction_agent"
    assert "not decided" in body["message"]


def test_eval_endpoint_matches_all(client):
    body = client.post("/eval/run").json()
    assert body["total"] == 12
    assert body["matched"] == 12


def test_list_claims(client):
    listing = client.get("/claims").json()
    assert len(listing) >= 2  # TC004 decision + TC001 stop were stored
