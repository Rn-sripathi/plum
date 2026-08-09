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


PRESCRIPTION_FOLLOWUP = [
    "Dr. Neha Kulkarni, MBBS, MD (General Medicine)",
    "Reg. No: KA/51234/2017",
    "Sunrise Clinic, 8 Residency Road, Bengaluru",
    "-" * 60,
    "Patient: Rajesh Kumar          Date: 05-Nov-2024",
    "Age: 39 years   Gender: M",
    "-" * 60,
    "Diagnosis: Viral Fever - follow up",
    "",
    "Rx:",
    "1. Tab Azithromycin 500mg - 1-0-0 x 3 days",
    "2. Syrup Ascoril - 10ml 1-1-1 x 5 days",
    "",
    "Review: After 1 week",
    "                       [Signed] Dr. Neha Kulkarni",
]

PRESCRIPTION_SNEHA = [
    "Dr. Arun Sharma, MBBS, MD (Internal Medicine)",
    "Reg. No: KA/45678/2015",
    "City Medical Centre, 12 MG Road, Bengaluru",
    "-" * 60,
    "Patient: Sneha Reddy           Date: 25-Oct-2024",
    "Age: 32 years   Gender: F",
    "-" * 60,
    "Diagnosis: Acute Bronchitis",
    "",
    "Rx:",
    "1. Tab Azithromycin 500mg - 1-0-0 x 3 days",
    "2. Tab Paracetamol 650mg - 1-1-1 x 5 days",
    "3. Cough Syrup - 10ml 1-1-1 x 5 days",
    "4. Multivitamin - 0-1-0 x 30 days",
    "",
    "                       [Signed] Dr. Arun Sharma",
]

PHARMACY_BILL = [
    "HEALTH FIRST PHARMACY",
    "Drug Lic. No: KA-BLR-2291",
    "22 Brigade Road, Bengaluru",
    "-" * 60,
    "Bill No: HFP-24-09821    Date: 25-Oct-2024",
    "Patient: Sneha Reddy     Dr: Dr. Arun Sharma",
    "-" * 60,
    "MEDICINE        BATCH   EXP    QTY  MRP    AMT",
    "Paracetamol 650 A2341  03/26    15  2.50   37.50",
    "Azithromycin500 B7821  06/26    10  45.00  450.00",
    "Cough Syrup     C1102  11/25     1  180.00 180.00",
    "Multivitamin    D5540  02/27    30  4.42   132.50",
    "",
    "Subtotal:                              800.00",
    "Net Amount:                            800.00",
    "-" * 60,
    "Pharmacist: R. Sharma   [Stamp]",
]

HOSPITAL_BILL_OTHER_PATIENT = [
    "CITY MEDICAL CENTRE",
    "12 MG Road, Bengaluru - 560001",
    "GSTIN: 29ABCDE1234F1ZX",
    "-" * 60,
    "BILL / RECEIPT",
    "Bill No: CMC/2024/08477    Date: 01-Nov-2024",
    "-" * 60,
    "Patient Name: Arjun Mehta",
    "Age/Gender: 44 / Male",
    "Referring Doctor: Dr. Arun Sharma",
    "-" * 60,
    "DESCRIPTION                  QTY   RATE     AMOUNT",
    "Consultation Fee (OPD)        1   1000.00  1000.00",
    "CBC (Complete Blood Count)    1    300.00   300.00",
    "Dengue NS1 Antigen Test       1    200.00   200.00",
    "",
    "Total Amount:                         1500.00",
    "-" * 60,
    "Payment Mode: Card    Received by: Cashier",
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
    # A second, visibly different prescription — a file picker will not let you
    # choose the same file twice, and TC001 needs two prescriptions.
    render(PRESCRIPTION_FOLLOWUP, OUT / "prescription_followup.jpg")
    render(HOSPITAL_BILL, OUT / "hospital_bill_city_clinic.jpg")
    # TC002: matching prescription plus a pharmacy bill, readable and not.
    render(PRESCRIPTION_SNEHA, OUT / "prescription_sneha.jpg")
    render(PHARMACY_BILL, OUT / "pharmacy_bill.jpg")
    render(PHARMACY_BILL, OUT / "pharmacy_bill_unreadable.jpg", blur=7.0)
    # TC003: same treatment, different patient printed on the bill.
    render(HOSPITAL_BILL_OTHER_PATIENT, OUT / "hospital_bill_arjun_mehta.jpg")
    render(HOSPITAL_BILL, OUT / "blurry_bill.jpg", blur=6.0)
    # Partially legible: vision reads it, but with low field confidence — the
    # case that exercises the amount-reconciliation guard.
    render(HOSPITAL_BILL, OUT / "smudged_bill.jpg", blur=1.6)
    # Not an image at all: must be reported as a damaged upload, never a 503.
    (OUT / "corrupt.jpg").write_bytes(b"this is not an image at all" * 20)
    print(f"wrote {OUT / 'corrupt.jpg'} (deliberately invalid)")
    render_pdf([HOSPITAL_BILL], OUT / "hospital_bill.pdf")
    render_pdf(
        [PRESCRIPTION, HOSPITAL_BILL], OUT / "prescription_and_bill_2page.pdf"
    )


if __name__ == "__main__":
    main()
