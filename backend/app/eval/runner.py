"""Eval runner — runs all 12 cases from test_cases.json through the pipeline
and writes docs/EVAL_REPORT.md (deliverable #4) with the full decision output
and trace for every case, plus a matched/not-matched verdict per expectation.

Two paths, same expectations. The cases supply document contents as data, so
the default run feeds them straight in: reproducible anywhere, no API key, no
model in the loop. `--with-uploads` runs the same 12 as real files through
GPT-4o classification and extraction, which is the path a member actually
takes — and the only one that can catch a fault in reading a document, since
the structured path is handed the answers. The structured run stays the
canonical verdict because it is deterministic.

Run:  uv run python -m app.eval.runner [--with-uploads]
"""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from app.agents.llm import DocumentAI
from app.core.config import REPO_ROOT, settings
from app.core.errors import ComponentUnavailable
from app.engine.checks import fmt_inr
from app.kb.snapshot import PolicySnapshot
from app.models import ClaimDecision, ClaimSubmission
from app.models.documents import DocumentProblemReport
from app.orchestrator.pipeline import process_claim

# Per-case keyword obligations derived from each case's `system_must` — the
# report shows exactly which obligation each output satisfied.
MUST_KEYWORDS: dict[str, list[tuple[str, list[str]]]] = {
    "TC001": [("names uploaded and required types", ["PRESCRIPTION", "HOSPITAL_BILL"])],
    "TC002": [("asks re-upload of the specific document", ["{file:2}", "e-upload"])],
    "TC003": [("names both patients", ["Rajesh Kumar", "Arjun Mehta"])],
    "TC005": [("states the eligibility date", ["2024-11-30"])],
    "TC006": [("itemizes line-item verdicts", ["Teeth Whitening", "Root Canal Treatment"])],
    "TC007": [("explains pre-auth and resubmission", ["pre-authorization", "resubmit"])],
    "TC008": [("states limit and claimed amount", ["₹5,000", "₹7,500"])],
    "TC009": [("includes the specific fraud signals", ["same-day limit of 2"])],
    "TC010": [("shows discount and co-pay breakdown", ["₹900", "₹360"])],
    "TC011": [("failure visible + review recommended", ["skipped", "incomplete"])],
}

# The document files that stand in for each case on the upload path. The cases
# describe their documents but ship none, so these are the generated fixtures
# in data/mock_documents (see scripts/make_mock_docs.py), carrying each case's
# own member, doctor and amounts.
CASE_DOCUMENTS: dict[str, list[str]] = {
    "TC001": ["prescription_rajesh.jpg", "prescription_followup.jpg"],
    "TC002": ["prescription_sneha.jpg", "pharmacy_bill_unreadable.jpg"],
    "TC003": ["prescription_rajesh.jpg", "hospital_bill_arjun_mehta.jpg"],
    "TC004": ["prescription_rajesh.jpg", "hospital_bill_city_clinic.jpg"],
    "TC005": ["prescription_vikram_diabetes.jpg", "hospital_bill_vikram.jpg"],
    "TC006": ["dental_bill_priya.jpg"],
    "TC007": [
        "prescription_suresh_mri.jpg",
        "lab_report_suresh_mri.jpg",
        "hospital_bill_suresh_mri.jpg",
    ],
    "TC008": ["prescription_amit_gastro.jpg", "hospital_bill_amit.jpg"],
    "TC009": ["prescription_ravi_migraine.jpg", "hospital_bill_ravi.jpg"],
    "TC010": ["prescription_deepak_apollo.jpg", "hospital_bill_apollo_deepak.jpg"],
    "TC011": ["prescription_kavita_ayurveda.jpg", "hospital_bill_ayur_wellness.jpg"],
    "TC012": ["prescription_anita_bariatric.jpg", "hospital_bill_anita_bariatric.jpg"],
}


@dataclass
class CaseResult:
    case_id: str
    case_name: str
    expected: dict
    result: ClaimDecision | DocumentProblemReport
    matched: bool = True
    mismatches: list[str] = field(default_factory=list)
    must_checks: list[tuple[str, bool]] = field(default_factory=list)

    @property
    def decision_label(self) -> str:
        if isinstance(self.result, DocumentProblemReport):
            return "— (stopped: document problems)"
        return self.result.decision.value


def _searchable_text(result: ClaimDecision | DocumentProblemReport) -> str:
    if isinstance(result, DocumentProblemReport):
        parts = [p.message + " " + p.action_needed for p in result.problems]
    else:
        parts = list(result.reasons) + [s.detail for s in result.fraud_signals]
        parts += [
            f"{i.description}: {'approved' if i.approved else 'rejected'} {i.reason or ''}"
            for i in result.line_items
        ]
    return " ".join(parts)


def _judge(case: dict, submission: ClaimSubmission, result) -> CaseResult:
    """Score one run against the case's expectations.

    Shared by both paths deliberately: a decision that only holds when the
    documents arrive pre-typed has not been demonstrated.
    """
    expected = case["expected"]
    cr = CaseResult(case["case_id"], case["case_name"], expected, result)

    if expected.get("decision") is None:
        if not isinstance(result, DocumentProblemReport):
            cr.matched = False
            cr.mismatches.append(
                f"expected an early stop with no decision, got {result.decision.value}"
            )
    else:
        if isinstance(result, DocumentProblemReport):
            cr.matched = False
            cr.mismatches.append("expected a decision, but verification stopped the claim")
        else:
            if result.decision.value != expected["decision"]:
                cr.matched = False
                cr.mismatches.append(
                    f"decision: expected {expected['decision']}, got {result.decision.value}"
                )
            if "approved_amount" in expected and result.approved_amount != Decimal(
                expected["approved_amount"]
            ):
                cr.matched = False
                cr.mismatches.append(
                    f"amount: expected {fmt_inr(expected['approved_amount'])}, got {fmt_inr(result.approved_amount)}"
                )
            if "rejection_reasons" in expected:
                got = [r.value for r in result.rejection_reasons]
                if got != expected["rejection_reasons"]:
                    cr.matched = False
                    cr.mismatches.append(
                        f"rejection_reasons: expected {expected['rejection_reasons']}, got {got}"
                    )
            if "confidence_score" in expected:
                floor = float(expected["confidence_score"].removeprefix("above").strip())
                if not result.confidence > floor:
                    cr.matched = False
                    cr.mismatches.append(
                        f"confidence: expected above {floor}, got {result.confidence}"
                    )

    text = _searchable_text(result)
    for label, keywords in MUST_KEYWORDS.get(case["case_id"], []):
        # `{file:N}` resolves to the Nth document's file name, so "names the
        # specific document" is checked against whatever each path uploaded.
        resolved = [_resolve_placeholder(k, submission) for k in keywords]
        ok = all(k in text for k in resolved)
        cr.must_checks.append((label, ok))
        if not ok:
            cr.matched = False
            cr.mismatches.append(f"system_must not satisfied: {label} (need {resolved})")
    return cr


def _resolve_placeholder(keyword: str, submission: ClaimSubmission) -> str:
    if not keyword.startswith("{file:"):
        return keyword
    index = int(keyword.removeprefix("{file:").removesuffix("}")) - 1
    documents = submission.documents
    return documents[index].file_name or "" if index < len(documents) else keyword


def evaluate_case(case: dict, snapshot: PolicySnapshot, semantic=None, graph=None) -> CaseResult:
    """Structured path: the case's document contents feed the pipeline directly."""
    submission = ClaimSubmission.model_validate(case["input"])
    result = process_claim(
        submission, snapshot, claim_id=case["case_id"], semantic=semantic, graph=graph
    )
    return _judge(case, submission, result)


def evaluate_upload_case(
    case: dict, snapshot: PolicySnapshot, doc_ai: DocumentAI, semantic=None, graph=None
) -> CaseResult:
    """Upload path: the same claim as real files, classified and read by vision.

    Types are left undeclared, as the console's file picker leaves them, so the
    classifier's own reading is what the requirement check sees.
    """
    payload = {k: v for k, v in case["input"].items() if k != "documents"}
    payload["documents"] = [
        {
            "file_id": f"F{i + 1:03d}",
            "file_name": name,
            "storage_path": str(REPO_ROOT / "data" / "mock_documents" / name),
        }
        for i, name in enumerate(CASE_DOCUMENTS[case["case_id"]])
    ]
    submission = ClaimSubmission.model_validate(payload)
    result = process_claim(
        submission,
        snapshot,
        claim_id=f"{case['case_id']}_UPLOAD",
        doc_ai=doc_ai,
        semantic=semantic,
        graph=graph,
    )
    return _judge(case, submission, result)


def run_all(with_kb: bool = False) -> list[CaseResult]:
    """Run all 12 cases. `with_kb=True` routes through the live knowledge
    stores (Qdrant semantic tier + Neo4j rule source) — the Phase 5 exit
    criterion is 12/12 both with the KB live and with it absent."""
    snapshot = PolicySnapshot.from_file(settings.policy_terms_path)
    cases = json.loads(settings.test_cases_path.read_text(encoding="utf-8"))["test_cases"]
    semantic = graph = None
    if with_kb:
        from app.kb.graph import PolicyGraph
        from app.kb.semantic import SemanticPolicyIndex

        semantic = SemanticPolicyIndex(settings)
        graph = PolicyGraph(settings)
    return [evaluate_case(case, snapshot, semantic, graph) for case in cases]


def run_all_uploads() -> list[CaseResult]:
    """Run all 12 as real document uploads through vision. Needs an API key."""
    doc_ai = DocumentAI(settings)
    if not doc_ai.is_configured:
        raise ComponentUnavailable(
            "llm", "The upload run needs OPENAI_API_KEY; the structured run does not."
        )
    snapshot = PolicySnapshot.from_file(settings.policy_terms_path)
    cases = json.loads(settings.test_cases_path.read_text(encoding="utf-8"))["test_cases"]
    return [evaluate_upload_case(case, snapshot, doc_ai) for case in cases]


# --- report rendering --------------------------------------------------------


def _took(ms: float) -> str:
    """Step duration, so the trace shows where a claim's time actually goes."""
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    return f"{ms:.0f}ms" if ms >= 1 else "<1ms"


def _render_case(cr: CaseResult, suffix: str = "") -> str:
    lines = [f"## {cr.case_id}{suffix} — {cr.case_name} {'✅' if cr.matched else '❌'}", ""]
    exp = cr.expected
    exp_desc = "early stop, no decision" if exp.get("decision") is None else exp["decision"]
    if "approved_amount" in exp:
        exp_desc += f", {fmt_inr(exp['approved_amount'])}"
    if "rejection_reasons" in exp:
        exp_desc += f", reasons {exp['rejection_reasons']}"
    lines.append(f"**Expected:** {exp_desc}  ")
    lines.append(f"**Got:** {cr.decision_label}")
    lines.append("")

    r = cr.result
    if isinstance(r, DocumentProblemReport):
        lines.append("**Member-facing problems:**")
        for p in r.problems:
            lines.append(f"- **[{p.kind.value}]** {p.message}")
            lines.append(f"  - *Action:* {p.action_needed}")
    else:
        lines.append(
            f"**Approved:** {fmt_inr(r.approved_amount)} · **Confidence:** {r.confidence:.2f}"
            + (" · **Manual review recommended**" if r.manual_review_recommended else "")
        )
        lines.append("")
        lines.append("**Reasons given:**")
        lines += [f"- {reason}" for reason in r.reasons]
        if r.line_items:
            lines += [
                "",
                "**Line items:**",
                "| Item | Claimed | Verdict | Reason |",
                "|------|---------|---------|--------|",
            ]
            lines += [
                f"| {i.description} | {fmt_inr(i.claimed_amount)} | "
                f"{'✅ approved' if i.approved else '❌ rejected'} | {i.reason or '—'} |"
                for i in r.line_items
            ]
        if r.fraud_signals:
            lines.append("")
            lines.append("**Fraud signals:**")
            lines += [f"- `{s.code.value}` — {s.detail}" for s in r.fraud_signals]
        if r.degraded_components:
            lines.append("")
            lines.append(f"**Degraded components:** {', '.join(r.degraded_components)}")

    if cr.must_checks:
        lines.append("")
        lines.append("**system_must checks:**")
        lines += [f"- {'✅' if ok else '❌'} {label}" for label, ok in cr.must_checks]
    if cr.mismatches:
        lines.append("")
        lines.append("**Mismatches:**")
        lines += [f"- {m}" for m in cr.mismatches]

    trace = r.trace
    lines += [
        "",
        "<details><summary><b>Full trace</b> (" + str(len(trace.steps)) + " steps)</summary>",
        "",
        "| # | Component | Action | Outcome | Took | Δ conf | Detail |",
        "|---|-----------|--------|---------|------|--------|--------|",
    ]
    for s in trace.steps:
        detail = s.detail.replace("|", "\\|")
        took = "—" if s.duration_ms is None else _took(s.duration_ms)
        delta = f"{s.confidence_delta:+.2f}" if s.confidence_delta else "—"
        lines.append(
            f"| {s.seq} | {s.component} | {s.action} | {s.outcome.value} | "
            f"{took} | {delta} | {detail} |"
        )
    lines += ["", "</details>", ""]
    return "\n".join(lines)


def render_report(results: list[CaseResult], uploads: list[CaseResult] | None = None) -> str:
    matched = sum(1 for r in results if r.matched)
    header = [
        "# Eval Report — Claims Processing System",
        "",
        f"**{matched}/{len(results)} cases matched expected outcomes.**",
        "",
        "Generated by `uv run python -m app.eval.runner` (from `backend/`). "
        "Every case shows the full decision output and the complete trace.",
        "",
    ]
    if uploads is not None:
        up_matched = sum(1 for r in uploads if r.matched)
        by_id = {r.case_id: r for r in uploads}
        header += [
            f"The same 12 also run as **real document uploads** through GPT-4o "
            f"classification and extraction: **{up_matched}/{len(uploads)} matched** "
            f"(`--with-uploads`). Two paths, one set of expectations — a decision that "
            f"only holds when documents arrive pre-typed has not been demonstrated. "
            f"The structured run below is the canonical verdict because it is "
            f"deterministic; the upload run is what a member actually triggers, and is "
            f"the only path that can catch a fault in *reading* a document.",
            "",
            "| Case | Name | Expected | Structured | Upload | Match |",
            "|------|------|----------|------------|--------|-------|",
        ]
        for cr in results:
            exp = "— (stop)" if cr.expected.get("decision") is None else cr.expected["decision"]
            up = by_id.get(cr.case_id)
            header.append(
                f"| {cr.case_id} | {cr.case_name} | {exp} | "
                f"{cr.decision_label} {'✅' if cr.matched else '❌'} | "
                f"{up.decision_label if up else '—'} {'✅' if up and up.matched else '❌'} | "
                f"{'✅' if cr.matched and up and up.matched else '❌'} |"
            )
    else:
        header += [
            "| Case | Name | Expected | Got | Match |",
            "|------|------|----------|-----|-------|",
        ]
        for cr in results:
            exp = "— (stop)" if cr.expected.get("decision") is None else cr.expected["decision"]
            header.append(
                f"| {cr.case_id} | {cr.case_name} | {exp} | {cr.decision_label} | "
                f"{'✅' if cr.matched else '❌'} |"
            )
    header.append("")
    body = "\n".join(_render_case(cr) for cr in results)
    if uploads is None:
        return "\n".join(header) + "\n" + body
    upload_section = "\n".join(
        [
            "",
            "---",
            "",
            "# Upload path — the same 12 cases as real files",
            "",
            "Documents are the generated fixtures in `data/mock_documents/`, uploaded with "
            "their type left on *auto-detect* so the classifier's own reading is what the "
            "requirement check sees. Confidence differs from the structured run by design: "
            "vision-read fields carry per-field scores, pre-supplied content does not.",
            "",
        ]
        + [_render_case(cr, suffix=" (upload)") for cr in uploads]
    )
    return "\n".join(header) + "\n" + body + "\n" + upload_section


def main() -> None:
    import sys

    with_kb = "--with-kb" in sys.argv
    with_uploads = "--with-uploads" in sys.argv
    results = run_all(with_kb=with_kb)
    matched = sum(1 for r in results if r.matched)
    if with_kb:
        # Live-KB verification run: report to stdout, keep the committed
        # report as the deterministic (reproducible-anywhere) run.
        print(f"[live KB] {matched}/{len(results)} matched")
    else:
        uploads = None
        if with_uploads:
            print(f"{matched}/{len(results)} structured; running uploads through vision…")
            uploads = run_all_uploads()
            up_matched = sum(1 for r in uploads if r.matched)
            print(f"{up_matched}/{len(uploads)} upload")
        report = render_report(results, uploads)
        out = REPO_ROOT / "docs" / "EVAL_REPORT.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"{matched}/{len(results)} matched -> {out}")
        for cr in uploads or []:
            if not cr.matched:
                print(f"  UPLOAD MISMATCH {cr.case_id}: {'; '.join(cr.mismatches)}")
    for cr in results:
        if not cr.matched:
            print(f"  MISMATCH {cr.case_id}: {'; '.join(cr.mismatches)}")


if __name__ == "__main__":
    main()
