"""Serving uploaded documents back for review, and refusing to serve anything
that is not a file belonging to the requested claim."""

import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.main import create_app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "claims.db"
    with TestClient(create_app(database_path=db)) as c:
        yield c


@pytest.fixture(scope="module")
def uploaded_claim(client, tmp_path_factory):
    """A claim submitted with real files. Extraction fails (no LLM in tests),
    so we submit a category needing one document and read the stored record."""
    image = tmp_path_factory.mktemp("img") / "bill.jpg"
    Image.new("RGB", (300, 400), "white").save(image)
    metadata = {
        "member_id": "EMP002",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "DENTAL",
        "treatment_date": "2024-10-15",
        "claimed_amount": 2000,
    }
    resp = client.post(
        "/claims/upload",
        data={"metadata": json.dumps(metadata), "document_types": "PRESCRIPTION"},
        files=[("files", ("bill.jpg", image.read_bytes(), "image/jpeg"))],
    )
    # DENTAL requires a HOSPITAL_BILL; a PRESCRIPTION stops the claim early,
    # which still stores the record with its uploaded file.
    assert resp.status_code == 200
    return resp.json()


def test_result_lists_previewable_documents(uploaded_claim):
    docs = uploaded_claim["documents"]
    assert len(docs) == 1
    assert docs[0]["file_name"] == "bill.jpg"
    assert docs[0]["previewable"] is True


def test_document_is_served_back(client, uploaded_claim):
    doc = uploaded_claim["documents"][0]
    resp = client.get(f"/claims/{uploaded_claim['claim_id']}/documents/{doc['file_id']}")
    assert resp.status_code == 200
    assert resp.content[:2] == b"\xff\xd8"  # JPEG magic bytes
    assert "bill.jpg" in resp.headers.get("content-disposition", "")


def test_structured_documents_are_not_previewable(client, test_cases):
    case = next(c for c in test_cases if c["case_id"] == "TC004")
    result = client.post("/claims", json=case["input"]).json()
    assert all(d["previewable"] is False for d in result["documents"])
    resp = client.get(f"/claims/{result['claim_id']}/documents/F007")
    assert resp.status_code == 404
    assert "structured data" in resp.json()["detail"]


def test_unknown_claim_or_document_is_404(client, uploaded_claim):
    assert client.get("/claims/NOPE/documents/F001").status_code == 404
    assert (
        client.get(f"/claims/{uploaded_claim['claim_id']}/documents/F999").status_code == 404
    )


def test_path_traversal_is_refused(client, uploaded_claim, tmp_path):
    """A stored path outside the upload directory must never be served."""
    secret = tmp_path / "secret.txt"
    secret.write_text("credentials")

    store = client.app.state.store
    record = store.get(uploaded_claim["claim_id"])
    record["submission"]["documents"][0]["storage_path"] = str(secret)
    with store._connect() as conn:
        conn.execute(
            "UPDATE claims SET submission = ? WHERE claim_id = ?",
            (json.dumps(record["submission"]), uploaded_claim["claim_id"]),
        )

    doc_id = uploaded_claim["documents"][0]["file_id"]
    resp = client.get(f"/claims/{uploaded_claim['claim_id']}/documents/{doc_id}")
    assert resp.status_code == 404
    assert secret.read_text() == "credentials"  # untouched, never served


def test_upload_dir_is_the_only_root(client):
    assert settings.upload_path.name == "uploads"
