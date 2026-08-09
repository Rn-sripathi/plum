"""Assignment §1: a claim accepts member details, treatment type, claimed
amount, and one or more uploaded documents as **images or PDFs**.

These tests cover the file-handling contract (no LLM calls): both formats
convert to vision-ready image parts, and multi-page PDFs are rasterized page
by page.
"""

import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.agents.llm import MAX_PDF_PAGES, image_parts
from app.main import create_app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "claims.db"
    with TestClient(create_app(database_path=db)) as c:
        yield c


def _page(color: str = "white") -> Image.Image:
    return Image.new("RGB", (400, 560), color)


def test_image_upload_produces_one_part(tmp_path):
    path = tmp_path / "bill.jpg"
    _page().save(path)
    parts, pages = image_parts(path)
    assert pages == 1
    assert len(parts) == 1
    assert parts[0].startswith("data:image/jpeg;base64,")


def test_single_page_pdf_is_rendered_to_an_image(tmp_path):
    path = tmp_path / "bill.pdf"
    _page().save(path)
    parts, pages = image_parts(path)
    assert pages == 1
    assert len(parts) == 1
    # Rasterized: a PDF must never reach the vision model as application/pdf.
    assert parts[0].startswith("data:image/png;base64,")


def test_multi_page_pdf_renders_every_page(tmp_path):
    path = tmp_path / "discharge.pdf"
    first, *rest = [_page(c) for c in ("white", "ivory", "white")]
    first.save(path, save_all=True, append_images=rest)
    parts, pages = image_parts(path)
    assert pages == 3
    assert len(parts) == 3
    assert all(p.startswith("data:image/png;base64,") for p in parts)


def test_long_pdf_is_capped(tmp_path):
    path = tmp_path / "long.pdf"
    pages = [_page() for _ in range(MAX_PDF_PAGES + 3)]
    pages[0].save(path, save_all=True, append_images=pages[1:])
    parts, page_count = image_parts(path)
    assert page_count == MAX_PDF_PAGES + 3
    assert len(parts) == MAX_PDF_PAGES  # tail dropped; extract() warns about it


def test_upload_accepts_member_treatment_amount_and_files(client, tmp_path):
    """The §1 payload shape is accepted end to end (503 here only because no
    LLM is configured in tests — the request itself validated and routed)."""
    img = tmp_path / "rx.jpg"
    _page().save(img)
    pdf = tmp_path / "bill.pdf"
    _page().save(pdf)

    metadata = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": 1500,
    }
    resp = client.post(
        "/claims/upload",
        data={"metadata": json.dumps(metadata), "document_types": "PRESCRIPTION,HOSPITAL_BILL"},
        files=[
            ("files", ("rx.jpg", img.read_bytes(), "image/jpeg")),
            ("files", ("bill.pdf", pdf.read_bytes(), "application/pdf")),
        ],
    )
    assert resp.status_code == 503
    assert resp.json()["component"] == "extraction_agent"


def test_corrupt_file_is_a_member_problem_not_a_server_error(client, tmp_path):
    """§6: bad input must not crash — and a damaged upload is the member's to
    fix, so it must NOT surface as a 503 infrastructure failure."""
    good = tmp_path / "rx.jpg"
    _page().save(good)

    metadata = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": 1500,
    }
    resp = client.post(
        "/claims/upload",
        data={"metadata": json.dumps(metadata), "document_types": "PRESCRIPTION,HOSPITAL_BILL"},
        files=[
            ("files", ("rx.jpg", good.read_bytes(), "image/jpeg")),
            ("files", ("bill.jpg", b"not an image at all" * 20, "image/jpeg")),
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "DOCUMENTS_REQUIRED"
    damaged = [p for p in body["problems"] if p["file_name"] == "bill.jpg"]
    assert len(damaged) == 1, "the damaged file must be reported exactly once"
    assert "damaged" in damaged[0]["message"]
    assert "Re-upload" in damaged[0]["action_needed"]


def test_truncated_pdf_is_reported_as_damaged(client, tmp_path):
    metadata = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": 1500,
    }
    resp = client.post(
        "/claims/upload",
        data={"metadata": json.dumps(metadata), "document_types": "HOSPITAL_BILL"},
        files=[("files", ("bill.pdf", b"%PDF-1.4 truncated", "application/pdf"))],
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "DOCUMENTS_REQUIRED"


def test_upload_rejects_empty_document_set(client):
    metadata = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": 1500,
    }
    resp = client.post(
        "/claims/upload", data={"metadata": json.dumps(metadata), "document_types": ""}
    )
    assert resp.status_code == 422  # "one or more documents" is enforced
