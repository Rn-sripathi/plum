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

PRESCRIPTION_VIKRAM = [
    "Dr. Sunil Mehta, MBBS, MD (Diabetology)",
    "Reg. No: GJ/56789/2014",
    "Sterling Clinic, 44 CG Road, Ahmedabad",
    "-" * 60,
    "Patient: Vikram Joshi          Date: 15-Oct-2024",
    "Age: 45 years   Gender: M",
    "-" * 60,
    "Diagnosis: Type 2 Diabetes Mellitus",
    "",
    "Rx:",
    "1. Tab Metformin 500mg - 1-0-1 x 30 days",
    "2. Tab Glimepiride 1mg - 1-0-0 x 30 days",
    "",
    "Advice: HbA1c after 3 months, diet control",
    "                       [Signed] Dr. Sunil Mehta",
]

HOSPITAL_BILL_VIKRAM = [
    "STERLING CLINIC",
    "44 CG Road, Ahmedabad - 380009",
    "-" * 60,
    "BILL / RECEIPT",
    "Bill No: SC/2024/1188    Date: 15-Oct-2024",
    "-" * 60,
    "Patient Name: Vikram Joshi",
    "Age/Gender: 45 / Male",
    "Consulting Doctor: Dr. Sunil Mehta",
    "-" * 60,
    "DESCRIPTION                  QTY   RATE     AMOUNT",
    "Specialist Consultation       1   1200.00  1200.00",
    "HbA1c Test                    1    800.00   800.00",
    "Fasting Blood Sugar           1    400.00   400.00",
    "Lipid Profile                 1    600.00   600.00",
    "",
    "Total Amount:                         3000.00",
    "-" * 60,
    "Payment Mode: UPI    Received by: Cashier",
]

DENTAL_BILL_PRIYA = [
    "SMILE DENTAL CLINIC",
    "7 Koramangala 5th Block, Bengaluru - 560095",
    "GSTIN: 29SMILE4321K1ZP",
    "-" * 60,
    "BILL / RECEIPT",
    "Bill No: SDC/2024/0442    Date: 15-Oct-2024",
    "-" * 60,
    "Patient Name: Priya Singh",
    "Age/Gender: 34 / Female",
    "Treating Dentist: Dr. Kavya Rao, BDS, MDS",
    "-" * 60,
    "DESCRIPTION                  QTY   RATE     AMOUNT",
    "Root Canal Treatment          1   8000.00  8000.00",
    "Teeth Whitening               1   4000.00  4000.00",
    "",
    "Total Amount:                        12000.00",
    "-" * 60,
    "Payment Mode: Card    Received by: Reception",
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


PRESCRIPTION_SURESH_MRI = [
    "Dr. Venkat Rao, MBBS, MS (Orthopaedics)",
    "Reg. No: AP/67890/2017",
    "Gachibowli Ortho Care, 5 Hitech City Road, Hyderabad",
    "-" * 60,
    "Patient: Suresh Patil          Date: 02-Nov-2024",
    "Age: 48 years   Gender: M",
    "Chief Complaint: Low back pain radiating to left leg, 6 weeks",
    "-" * 60,
    "Diagnosis: Suspected Lumbar Disc Herniation",
    "",
    "Investigations Advised:",
    "1. MRI Lumbar Spine (plain)",
    "",
    "Rx:",
    "1. Tab Etoricoxib 60mg - 0-1-0 x 7 days",
    "",
    "Review with MRI report",
    "                       [Signed] Dr. Venkat Rao",
]

MRI_REPORT_SURESH = [
    "GACHIBOWLI DIAGNOSTIC LABORATORY",
    "5 Hitech City Road, Hyderabad - 500081",
    "-" * 60,
    "LAB REPORT",
    "Report No: GDL/MRI/2024/4471   Date: 02-Nov-2024",
    "-" * 60,
    "Patient Name: Suresh Patil",
    "Age/Gender: 48 / Male",
    "Referred By: Dr. Venkat Rao",
    "-" * 60,
    "TEST NAME: MRI Lumbar Spine",
    "",
    "FINDINGS:",
    "L4-L5: Posterocentral disc protrusion indenting thecal sac.",
    "L5-S1: Mild diffuse disc bulge. No canal stenosis.",
    "Vertebral body height and marrow signal preserved.",
    "",
    "IMPRESSION: L4-L5 disc herniation with left lateral recess",
    "narrowing, correlating with the clinical picture.",
    "-" * 60,
    "                  [Signed] Dr. M. Reddy, MD (Radiodiagnosis)",
]

HOSPITAL_BILL_SURESH_MRI = [
    "GACHIBOWLI DIAGNOSTIC LABORATORY",
    "5 Hitech City Road, Hyderabad - 500081",
    "GSTIN: 36GDLAB6712H1ZQ",
    "-" * 60,
    "BILL / RECEIPT",
    "Bill No: GDL/2024/4471    Date: 02-Nov-2024",
    "-" * 60,
    "Patient Name: Suresh Patil",
    "Age/Gender: 48 / Male",
    "Referring Doctor: Dr. Venkat Rao",
    "-" * 60,
    "DESCRIPTION                  QTY   RATE     AMOUNT",
    "MRI Lumbar Spine              1  15000.00 15000.00",
    "",
    "Total Amount:                        15000.00",
    "-" * 60,
    "Payment Mode: Card    Received by: Cashier",
]

PRESCRIPTION_AMIT_GASTRO = [
    "Dr. R. Gupta, MBBS, MD (Gastroenterology)",
    "Reg. No: DL/34567/2016",
    "Rohini Care Clinic, 21 Sector 9, New Delhi",
    "-" * 60,
    "Patient: Amit Verma            Date: 20-Oct-2024",
    "Age: 35 years   Gender: M",
    "Chief Complaint: Loose stools and vomiting since 2 days",
    "-" * 60,
    "Diagnosis: Acute Gastroenteritis",
    "",
    "Rx:",
    "1. Tab Ofloxacin 200mg - 1-0-1 x 5 days",
    "2. Cap Probiotic - 1-0-1 x 7 days",
    "3. ORS sachets - as needed",
    "",
    "Advice: Oral hydration, bland diet",
    "                       [Signed] Dr. R. Gupta",
]

HOSPITAL_BILL_AMIT = [
    "ROHINI CARE CLINIC",
    "21 Sector 9, Rohini, New Delhi - 110085",
    "GSTIN: 07RCCLI8890M1ZR",
    "-" * 60,
    "BILL / RECEIPT",
    "Bill No: RCC/2024/2210    Date: 20-Oct-2024",
    "-" * 60,
    "Patient Name: Amit Verma",
    "Age/Gender: 35 / Male",
    "Consulting Doctor: Dr. R. Gupta",
    "-" * 60,
    "DESCRIPTION                  QTY   RATE     AMOUNT",
    "Consultation Fee              1   2000.00  2000.00",
    "Medicines                     1   5500.00  5500.00",
    "",
    "Total Amount:                         7500.00",
    "-" * 60,
    "Payment Mode: Card    Received by: Cashier",
]

PRESCRIPTION_RAVI_MIGRAINE = [
    "Dr. S. Khan, MBBS, DM (Neurology)",
    "Reg. No: KL/23456/2015",
    "Marine Drive Neuro Clinic, 9 Marine Drive, Kochi",
    "-" * 60,
    "Patient: Ravi Menon            Date: 30-Oct-2024",
    "Age: 37 years   Gender: M",
    "Chief Complaint: Recurrent one-sided headache with photophobia",
    "-" * 60,
    "Diagnosis: Migraine without aura",
    "",
    "Rx:",
    "1. Tab Sumatriptan 50mg - SOS, max 2/day",
    "2. Tab Propranolol 20mg - 1-0-1 x 30 days",
    "",
    "Advice: Sleep hygiene, trigger diary",
    "                       [Signed] Dr. S. Khan",
]

HOSPITAL_BILL_RAVI = [
    "MARINE DRIVE NEURO CLINIC",
    "9 Marine Drive, Kochi - 682031",
    "-" * 60,
    "BILL / RECEIPT",
    "Bill No: MDNC/2024/0774   Date: 30-Oct-2024",
    "-" * 60,
    "Patient Name: Ravi Menon",
    "Age/Gender: 37 / Male",
    "Consulting Doctor: Dr. S. Khan",
    "-" * 60,
    "DESCRIPTION                  QTY   RATE     AMOUNT",
    "Specialist Consultation       1   1800.00  1800.00",
    "Medicines                     1   3000.00  3000.00",
    "",
    "Total Amount:                         4800.00",
    "-" * 60,
    "Payment Mode: UPI     Received by: Cashier",
]

PRESCRIPTION_DEEPAK_APOLLO = [
    "Dr. S. Iyer, MBBS, MD (Pulmonology)",
    "Reg. No: TN/56789/2013",
    "Apollo Hospitals, 21 Greams Lane, Chennai",
    "-" * 60,
    "Patient: Deepak Shah           Date: 03-Nov-2024",
    "Age: 44 years   Gender: M",
    "Chief Complaint: Productive cough and wheeze, 5 days",
    "-" * 60,
    "Diagnosis: Acute Bronchitis",
    "",
    "Rx:",
    "1. Tab Amoxicillin 500mg - 1-1-1 x 5 days",
    "2. Salbutamol Inhaler - 2 puffs SOS",
    "",
    "Review: After 5 days if symptoms persist",
    "                       [Signed] Dr. S. Iyer",
]

HOSPITAL_BILL_APOLLO_DEEPAK = [
    "APOLLO HOSPITALS",
    "21 Greams Lane, Off Greams Road, Chennai - 600006",
    "GSTIN: 33APOLL1122A1ZK",
    "-" * 60,
    "BILL / RECEIPT",
    "Bill No: AH/2024/55130    Date: 03-Nov-2024",
    "-" * 60,
    "Patient Name: Deepak Shah",
    "Age/Gender: 44 / Male",
    "Consulting Doctor: Dr. S. Iyer",
    "-" * 60,
    "DESCRIPTION                  QTY   RATE     AMOUNT",
    "Consultation Fee              1   1500.00  1500.00",
    "Medicines                     1   3000.00  3000.00",
    "",
    "Total Amount:                         4500.00",
    "-" * 60,
    "Payment Mode: Card    Received by: Cashier",
]

PRESCRIPTION_KAVITA_AYURVEDA = [
    "Vaidya T. Krishnan, BAMS, MD (Ayurveda)",
    "Reg. No: AYUR/KL/2345/2019",
    "Ayur Wellness Centre, 14 Temple Road, Thrissur",
    "-" * 60,
    "Patient: Kavita Nair           Date: 28-Oct-2024",
    "Age: 41 years   Gender: F",
    "Chief Complaint: Chronic joint pain, both knees, 8 months",
    "-" * 60,
    "Diagnosis: Chronic Joint Pain (Sandhigata Vata)",
    "",
    "Treatment Advised:",
    "1. Panchakarma Therapy - 5 sessions",
    "2. Ksheerabala capsules - 1-0-1 x 30 days",
    "",
    "Advice: Warm oil application, gentle yoga",
    "                       [Signed] Vaidya T. Krishnan",
]

HOSPITAL_BILL_AYUR_WELLNESS = [
    "AYUR WELLNESS CENTRE",
    "14 Temple Road, Thrissur - 680001",
    "-" * 60,
    "BILL / RECEIPT",
    "Bill No: AWC/2024/0318    Date: 28-Oct-2024",
    "-" * 60,
    "Patient Name: Kavita Nair",
    "Age/Gender: 41 / Female",
    "Treating Physician: Vaidya T. Krishnan",
    "-" * 60,
    "DESCRIPTION                  QTY   RATE     AMOUNT",
    "Panchakarma Therapy           5    600.00  3000.00",
    "Consultation                  1   1000.00  1000.00",
    "",
    "Total Amount:                         4000.00",
    "-" * 60,
    "Payment Mode: UPI     Received by: Reception",
]

PRESCRIPTION_ANITA_BARIATRIC = [
    "Dr. P. Banerjee, MBBS, MS (General Surgery)",
    "Reg. No: WB/34567/2015",
    "Salt Lake Metabolic Clinic, 3 Sector V, Kolkata",
    "-" * 60,
    "Patient: Anita Desai           Date: 18-Oct-2024",
    "Age: 32 years   Gender: F",
    "-" * 60,
    "Diagnosis: Morbid Obesity - BMI 37",
    "",
    "Treatment Advised:",
    "1. Bariatric Consultation",
    "2. Customised Diet Plan / weight loss program",
    "",
    "Review: Monthly weight and BMI tracking",
    "                       [Signed] Dr. P. Banerjee",
]

HOSPITAL_BILL_ANITA_BARIATRIC = [
    "SALT LAKE METABOLIC CLINIC",
    "3 Sector V, Salt Lake, Kolkata - 700091",
    "GSTIN: 19SLMET7788B1ZW",
    "-" * 60,
    "BILL / RECEIPT",
    "Bill No: SLM/2024/0906    Date: 18-Oct-2024",
    "-" * 60,
    "Patient Name: Anita Desai",
    "Age/Gender: 32 / Female",
    "Consulting Doctor: Dr. P. Banerjee",
    "-" * 60,
    "DESCRIPTION                  QTY   RATE     AMOUNT",
    "Bariatric Consultation        1   3000.00  3000.00",
    "Personalised Diet and         1   5000.00  5000.00",
    "  Nutrition Program",
    "",
    "Total Amount:                         8000.00",
    "-" * 60,
    "Payment Mode: Card    Received by: Reception",
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
    # TC006: dental bill mixing a covered treatment with a cosmetic one.
    render(DENTAL_BILL_PRIYA, OUT / "dental_bill_priya.jpg")
    # TC005: diabetes claim inside the 90-day condition waiting period.
    render(PRESCRIPTION_VIKRAM, OUT / "prescription_vikram_diabetes.jpg")
    render(HOSPITAL_BILL_VIKRAM, OUT / "hospital_bill_vikram.jpg")
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
    # TC007: MRI above the pre-authorization threshold, no pre-auth reference.
    render(PRESCRIPTION_SURESH_MRI, OUT / "prescription_suresh_mri.jpg")
    render(MRI_REPORT_SURESH, OUT / "lab_report_suresh_mri.jpg")
    render(HOSPITAL_BILL_SURESH_MRI, OUT / "hospital_bill_suresh_mri.jpg")
    # TC008: bill total above the per-claim limit.
    render(PRESCRIPTION_AMIT_GASTRO, OUT / "prescription_amit_gastro.jpg")
    render(HOSPITAL_BILL_AMIT, OUT / "hospital_bill_amit.jpg")
    # TC009: the 4th same-day claim — the fraud velocity signal.
    render(PRESCRIPTION_RAVI_MIGRAINE, OUT / "prescription_ravi_migraine.jpg")
    render(HOSPITAL_BILL_RAVI, OUT / "hospital_bill_ravi.jpg")
    # TC010: network hospital — discount applies before co-pay.
    render(PRESCRIPTION_DEEPAK_APOLLO, OUT / "prescription_deepak_apollo.jpg")
    render(HOSPITAL_BILL_APOLLO_DEEPAK, OUT / "hospital_bill_apollo_deepak.jpg")
    # TC011: alternative medicine, used with the component-failure flag.
    render(PRESCRIPTION_KAVITA_AYURVEDA, OUT / "prescription_kavita_ayurveda.jpg")
    render(HOSPITAL_BILL_AYUR_WELLNESS, OUT / "hospital_bill_ayur_wellness.jpg")
    # TC012: obesity / weight-loss program — an excluded condition.
    render(PRESCRIPTION_ANITA_BARIATRIC, OUT / "prescription_anita_bariatric.jpg")
    render(HOSPITAL_BILL_ANITA_BARIATRIC, OUT / "hospital_bill_anita_bariatric.jpg")
    # Not an image at all: must be reported as a damaged upload, never a 503.
    (OUT / "corrupt.jpg").write_bytes(b"this is not an image at all" * 20)
    print(f"wrote {OUT / 'corrupt.jpg'} (deliberately invalid)")
    render_pdf([HOSPITAL_BILL], OUT / "hospital_bill.pdf")
    render_pdf(
        [PRESCRIPTION, HOSPITAL_BILL], OUT / "prescription_and_bill_2page.pdf"
    )


if __name__ == "__main__":
    main()
