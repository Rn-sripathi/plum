"""Generate mock Indian medical documents (sample_documents_guide.md layouts)
for demoing the real-upload path: a prescription, a hospital bill, and a
deliberately blurred bill for the unreadable-document demo.

Run:  uv run python scripts/make_mock_docs.py
Output: data/mock_documents/*.jpg
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "data" / "mock_documents"

PRESCRIPTION = [
    "Dr. Arun Sharma, MBBS, MD (Internal Medicine)",
    "Reg. No: KA/45678/2015",
    "City Medical Centre, 12 MG Road, Bengaluru",
    "-" * 60,
    "Patient: Rajesh Kumar          Date: 01-Nov-2024",
    "Age: 39 years   Gender: M",
    "Chief Complaint: Fever since 3 days, body ache",
    "-" * 60,
    "Diagnosis: Viral Fever",
    "",
    "Rx:",
    "1. Tab Paracetamol 650mg - 1-1-1 x 5 days",
    "2. Tab Vitamin C 500mg - 0-0-1 x 7 days",
    "",
    "Investigations: CBC, Dengue NS1",
    "Follow-up: After 5 days if no improvement",
    "",
    "                       [Signed] Dr. Arun Sharma",
]

HOSPITAL_BILL = [
    "CITY MEDICAL CENTRE",
    "12 MG Road, Bengaluru - 560001",
    "GSTIN: 29ABCDE1234F1ZX",
    "-" * 60,
    "BILL / RECEIPT",
    "Bill No: CMC/2024/08321    Date: 01-Nov-2024",
    "-" * 60,
    "Patient Name: Rajesh Kumar",
    "Age/Gender: 39 / Male",
    "Referring Doctor: Dr. Arun Sharma",
    "-" * 60,
    "DESCRIPTION                  QTY   RATE     AMOUNT",
    "Consultation Fee (OPD)        1   1000.00  1000.00",
    "CBC (Complete Blood Count)    1    300.00   300.00",
    "Dengue NS1 Antigen Test       1    200.00   200.00",
    "",
    "Subtotal:                             1500.00",
    "GST (0% on medical):                     0.00",
    "Total Amount:                         1500.00",
    "-" * 60,
    "Payment Mode: UPI     Received by: Cashier",
]


def render(lines: list[str], path: Path, blur: float = 0.0) -> None:
    img = Image.new("RGB", (720, 40 + 34 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((40, 24 + 34 * i), line, fill="black")
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    img.save(path, quality=88)
    print(f"wrote {path}")


def render_pdf(pages: list[list[str]], path: Path) -> None:
    """Multi-page PDF — the pipeline rasterizes each page for extraction."""
    images = []
    for lines in pages:
        img = Image.new("RGB", (720, 40 + 34 * len(lines)), "white")
        draw = ImageDraw.Draw(img)
        for i, line in enumerate(lines):
            draw.text((40, 24 + 34 * i), line, fill="black")
        images.append(img)
    images[0].save(path, save_all=True, append_images=images[1:])
    print(f"wrote {path} ({len(images)} page(s))")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    render(PRESCRIPTION, OUT / "prescription_rajesh.jpg")
    render(HOSPITAL_BILL, OUT / "hospital_bill_city_clinic.jpg")
    render(HOSPITAL_BILL, OUT / "blurry_bill.jpg", blur=6.0)
    render_pdf([HOSPITAL_BILL], OUT / "hospital_bill.pdf")
    render_pdf(
        [PRESCRIPTION, HOSPITAL_BILL], OUT / "prescription_and_bill_2page.pdf"
    )


if __name__ == "__main__":
    main()
