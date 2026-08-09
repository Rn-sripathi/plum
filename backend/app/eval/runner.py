"""Eval runner — runs all 12 cases from test_cases.json through the pipeline
and writes docs/EVAL_REPORT.md (deliverable #4) with the full decision output
and trace for every case, plus a matched/not-matched verdict per expectation.

Run:  uv run python -m app.eval.runner
"""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from app.core.config import REPO_ROOT, settings
from app.engine.checks import fmt_inr
from app.kb.snapshot import PolicySnapshot
from app.models import ClaimDecision, ClaimSubmission
from app.models.documents import DocumentProblemReport
from app.orchestrator.pipeline import process_claim

# Per-case keyword obligations derived from each case's `system_must` — the
# report shows exactly which obligation each output satisfied.
MUST_KEYWORDS: dict[str, list[tuple[str, list[str]]]] = {
    "TC001": [("names uploaded and required types", ["PRESCRIPTION", "HOSPITAL_BILL"])],
    "TC002": [("asks re-upload of the specific document", ["blurry_bill.jpg", "e-upload"])],
    "TC003": [("names both patients", ["Rajesh Kumar", "Arjun Mehta"])],
    "TC005": [("states the eligibility date", ["2024-11-30"])],
    "TC006": [("itemizes line-item verdicts", ["Teeth Whitening", "Root Canal Treatment"])],
    "TC007": [("explains pre-auth and resubmission", ["pre-authorization", "resubmit"])],
    "TC008": [("states limit and claimed amount", ["₹5,000", "₹7,500"])],
    "TC009": [("includes the specific fraud signals", ["same-day limit of 2"])],
    "TC010": [("shows discount and co-pay breakdown", ["₹900", "₹360"])],
    "TC011": [("failure visible + review recommended", ["skipped", "incomplete"])],
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


def evaluate_case(case: dict, snapshot: PolicySnapshot, semantic=None, graph=None) -> CaseResult:
    submission = ClaimSubmission.model_validate(case["input"])
    result = process_claim(
        submission, snapshot, claim_id=case["case_id"], semantic=semantic, graph=graph
    )
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
        ok = all(k in text for k in keywords)
        cr.must_checks.append((label, ok))
        if not ok:
            cr.matched = False
            cr.mismatches.append(f"system_must not satisfied: {label} (need {keywords})")
    return cr


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


# --- report rendering --------------------------------------------------------


def _render_case(cr: CaseResult) -> str:
    lines = [f"## {cr.case_id} — {cr.case_name} {'✅' if cr.matched else '❌'}", ""]
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
        "| # | Component | Action | Outcome | Detail |",
        "|---|-----------|--------|---------|--------|",
    ]
    for s in trace.steps:
        detail = s.detail.replace("|", "\\|")
        lines.append(f"| {s.seq} | {s.component} | {s.action} | {s.outcome.value} | {detail} |")
    lines += ["", "</details>", ""]
    return "\n".join(lines)


def render_report(results: list[CaseResult]) -> str:
    matched = sum(1 for r in results if r.matched)
    header = [
        "# Eval Report — Claims Processing System",
        "",
        f"**{matched}/{len(results)} cases matched expected outcomes.**",
        "",
        "Generated by `uv run python -m app.eval.runner` (from `backend/`). "
        "Every case shows the full decision output and the complete trace.",
        "",
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
    return "\n".join(header) + "\n" + "\n".join(_render_case(cr) for cr in results)


def main() -> None:
    import sys

    with_kb = "--with-kb" in sys.argv
    results = run_all(with_kb=with_kb)
    matched = sum(1 for r in results if r.matched)
    if with_kb:
        # Live-KB verification run: report to stdout, keep the committed
        # report as the deterministic (reproducible-anywhere) run.
        print(f"[live KB] {matched}/{len(results)} matched")
    else:
        report = render_report(results)
        out = REPO_ROOT / "docs" / "EVAL_REPORT.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"{matched}/{len(results)} matched -> {out}")
    for cr in results:
        if not cr.matched:
            print(f"  MISMATCH {cr.case_id}: {'; '.join(cr.mismatches)}")


if __name__ == "__main__":
    main()
