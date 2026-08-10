# What running it found

Every defect below was found by *exercising* the system, not by reading it — and
most were invisible to the test suite that existed at the time. They are recorded
because the pattern is the useful part: each one shows a place where a
plausible-looking implementation and a correct one diverge, and each is now
pinned by a test.

The 12 assignment cases supply document *contents* as data. That path was passing
12/12. Running the same 12 as real uploaded files — the path a member actually
takes — found the first five of these in an afternoon.

## 1. A diagnostic claim could never satisfy its own requirement

**Found by** running TC007 (MRI without pre-authorization) as real files instead
of structured data.

`document_requirements.DIAGNOSTIC` asks for a `LAB_REPORT`. An MRI report is
radiology, which the classifier correctly labels `DIAGNOSTIC_REPORT` — its own
prompt says so. So the claim stopped at the document gate and never reached the
pre-auth rule the case exists to test. Both routes dead-ended: auto-detect
reported a missing lab report, and *declaring* one was contradicted by the
classifier.

Invisible to the structured path because the eval JSON hand-labels that document
`LAB_REPORT`. **Fix:** the two labels are interchangeable where a requirement
names either, with the reason recorded at the constant.

## 2. Every upload was fined 0.20 confidence for fields that do not exist

**Found by** asking why a clean TC004 upload scored 0.78 when the case expects
above 0.85.

The extractor asks the model for a per-field confidence and penalises anything
below 0.7. The model scores *every* field in the schema, returning 0.0 for the
ones a document does not have — so a prescription was penalised for lacking
`line_items` and a `total`, and a bill for lacking `diagnosis` and `medicines`.
Direct call on `prescription_rajesh.jpg`: every field it actually read scored
**1.0**; the three "hard to read" fields were the three that a prescription
never has.

Worse than the number: the member-facing reason read *"Some fields on
'prescription_rajesh.jpg' were hard to read (test_name, line_items, total)"* — a
confident, specific, false statement.

**Fix:** only a field that was actually read can have been hard to read. A field
the model tried and failed to recover is reported in `warnings`, which is
penalised separately.

## 3. A damaged upload was also accused of being the wrong document

**Found by** uploading `corrupt.jpg` — a fixture that exists precisely to be
invalid — alongside a valid bill.

Two problems came back: the honest one (*"could not be opened"*) and a spurious
`WRONG_TYPE` telling the member to upload a prescription, rendered as **"a
UNKNOWN"**. A file that will not open says nothing about its type, and the
corrupt file may well have *been* the prescription.

This contradicted the code's own stated principle — the verifier already carried
the comment *"never accuse the member of the wrong document when the real problem
is that we could not read it"* and applied that guard for blurred files. Damaged
files used a separate set that never got the same treatment.

**Fix:** one `unread` set covers both ways a document can go unread.

## 4. A two-page PDF was typed by its first page

**Found by** uploading `prescription_and_bill_2page.pdf` — a member scanning a
whole claim into one file, which is how people actually scan.

Classification sent page 1 only, so the file was a `PRESCRIPTION` and the bill it
contained was reported missing: *"You uploaded PRESCRIPTION … no HOSPITAL_BILL was
included."* Specific, actionable, and false — the worst combination for the
criterion that grades those qualities. Extraction had been reading all pages the
whole time; only typing was single-page.

**Fix:** classify every page in one call and count each document found. The same
PDF now decides APPROVED ₹1,350.

## 5. A null in a model response killed the claim

**Found by** a full eval run failing on TC004 with
`float() argument must be a string or a real number, not 'NoneType'`, then
passing on retry.

The extraction schema declares confidence as `number`; GPT-4o intermittently
returns `null` anyway. `float(None)` raised, and the API returned an
`UNEXPECTED` error with no decision. A schema constrains a model, it does not
guarantee it.

**Fix:** an absent score reads as no confidence stated. The same coercion covers
`warnings: null`.

## 6. An answer that cited nothing counted as grounded

**Found by** asking the assistant *"What architecture does this application
use?"*

It answered fluently about a *"tool-augmented architecture integrating
specialised APIs"* — plausible, generic, invented — with **zero citations**, and
was reported as `grounded: true`. The citation gate validated only the citations
that were *present*, so an answer with none had nothing to invalidate.

Two faults in one: the gate had a hole, and the project documents were never
indexed, so the model had nothing to answer from and filled the gap itself.

**Fix:** an answer must cite something whenever retrieval returned anything
citable, and `search_docs` makes the architecture, contracts, assumptions and
eval report retrievable by section.

## 7. A correct citation failed on an emoji

**Found by** asking *"How does the system handle a blurred bill?"* and getting
**Not grounded** for a citation that was right.

Doc anchors were built from raw markdown headings, and the eval report's headings
carry status emoji (`## TC002 — Unreadable Document ✅`). Asked to quote that
reference back, the model mangled the emoji, so exact-string comparison rejected
it. The gate fired on a character the model had no way to type — and a banner
that cries wolf teaches a reader to ignore it.

**Fix:** anchors are slugged to ASCII the way a markdown renderer would, and
citations are compared on a normalised form. Normalising cannot make a
*different* clause match, so the check keeps its teeth.

## 8. Retrieval always returned something, however irrelevant

**Found by** asking *"is physiotherapy covered"* — a word the policy never uses.
Nearest-neighbour search offered naturopathy and a waiting period, and the
grounding gate would have accepted either, because it checks that a citation was
*retrieved*, not that it was *relevant*.

**Fix:** measure it instead of guessing a threshold.
`app/eval/retrieval.py` holds 24 paraphrased cases — recall **0.905@1, 1.0@3** —
of which three are deliberate negatives. The worst correct top hit scores 0.416;
the best hit for a question the policy does not cover scores 0.380. `0.40` sits
in that gap: recall@3 stays 1.0 and every negative now returns nothing at all.

## Two of these were mine, found the same way

Worth recording, because the lesson is identical.

The **decision-mix stack** was validated for colour-blind separation in the order
green→amber→blue→red→grey, and then shipped as green→amber→**red**→blue→grey —
putting amber adjacent to red, the exact pair that collapses to ΔE 2.3 under
deuteranopia and which I had rejected minutes earlier. Caught by screenshotting
the built page. Now pinned by a test asserting those two are never neighbours.

The **assistant composer** opened 230px tall and empty, because the global
`textarea` rule carries `min-height: 170px` for the eval-cases JSON field. My
first fix — auto-growing by measuring `scrollHeight` — reported the maximum for
an empty field and clamped it open. Both would have shipped had I only run the
build instead of looking at the page.

## What this changed about the test suite

The suite grew from 75 to 146 tests, and the additions are shaped by the above:
a layer for **what the eval cases structurally cannot reach** (damaged files,
multi-page PDFs, malformed model output), a layer for the **assistant's gates and
scope isolation** with the model injected as a stub, and a **retrieval eval** that
reports a number rather than a pass.
