"""The assistant: retrieval, scope, and the gates that keep it from deciding.

The model is injected as a scripted stub throughout. What matters here is not
what a model happens to say — it is that the code refuses to pass off an
ungrounded answer as a sourced one, and that a member scope cannot read another
member's claim.
"""

import pytest
from fastapi.testclient import TestClient

from app.agents.assistant import Assistant
from app.core.config import Settings
from app.kb.retrieval import KnowledgeBase, Scope, Unavailable
from app.main import create_app
from app.models.assistant import ChatMessage


class StubStore:
    """Two claims, two members — enough to prove scope isolation."""

    RECORDS = [
        {
            "claim_id": "CLM_AAAA1111",
            "submitted_at": "2024-11-01T00:00:00Z",
            "member_id": "EMP001",
            "category": "CONSULTATION",
            "status": "APPROVED",
            "result": {
                "claim_id": "CLM_AAAA1111",
                "decision": "APPROVED",
                "approved_amount": "1350.00",
                "confidence": 0.98,
                "reasons": ["Approved ₹1,350 of claimed ₹1,500."],
                "financial": {"steps": [{"amount_before": "1500.00"}]},
                "trace": {
                    "claim_id": "CLM_AAAA1111",
                    "steps": [
                        {
                            "seq": 1,
                            "component": "adjudication_engine",
                            "action": "copay",
                            "outcome": "PASS",
                            "detail": "Co-pay applied.",
                            "rule_ref": "opd_categories.consultation.copay_percent",
                            "confidence_delta": 0.0,
                        }
                    ],
                },
            },
        },
        {
            "claim_id": "CLM_BBBB2222",
            "submitted_at": "2024-11-02T00:00:00Z",
            "member_id": "EMP002",
            "category": "DENTAL",
            "status": "REJECTED",
            "result": {
                "claim_id": "CLM_BBBB2222",
                "decision": "REJECTED",
                "approved_amount": "0",
                "confidence": 0.9,
                "reasons": ["Excluded."],
                "rejection_reasons": ["EXCLUDED_CONDITION"],
                "trace": {"claim_id": "CLM_BBBB2222", "steps": []},
            },
        },
    ]

    def get(self, claim_id):
        return next((r for r in self.RECORDS if r["claim_id"] == claim_id), None)

    def list_full(self, limit=500):
        return list(self.RECORDS)


def scripted(*steps):
    """A model that emits the given tool-call rounds in order."""
    rounds = list(steps)

    def chat(messages, tools):
        return rounds.pop(0) if rounds else {"tool_calls": []}

    return chat


def answer_round(answer, citations):
    return {
        "tool_calls": [
            {
                "id": "1",
                "name": "submit_answer",
                "arguments": {"answer": answer, "citations": citations},
            }
        ]
    }


@pytest.fixture
def kb(snapshot):
    return KnowledgeBase(snapshot=snapshot, store=StubStore())


def ask(assistant, kb, text, scope=None, claim_id=None):
    return assistant.answer(
        [ChatMessage(role="user", content=text)], kb, scope or Scope.ops(), claim_id=claim_id
    )


# --- retrieval ---------------------------------------------------------------


def test_exact_questions_are_looked_up_not_searched(kb):
    """A limit has an exact answer; routing it through a vector search would
    manufacture a chance to be wrong."""
    assert kb.lookup_policy("coverage.per_claim_limit") == {
        "rule_ref": "coverage.per_claim_limit",
        "value": "5000",
    }


def test_an_unknown_policy_path_is_refused_not_guessed(kb):
    with pytest.raises(Unavailable):
        kb.lookup_policy("coverage.does_not_exist")


def test_policy_search_falls_back_to_tokens_without_embeddings(kb):
    """No API key means no embeddings; recall degrades but does not vanish."""
    result = kb.search_policy("teeth whitening")
    assert result["source"] == "tokens"
    assert any("whitening" in h["concept"].lower() for h in result["hits"])


def test_category_rules_gathers_every_exclusion_that_reaches_dental(kb):
    rules = kb.category_rules("DENTAL")
    reaches = {e["reach"] for e in rules["exclusions"]}
    assert reaches == {"policy-wide", "dental only"}
    assert "HOSPITAL_BILL" in rules["required_documents"]
    assert any("Whitening" in e["clause"] for e in rules["exclusions"])


def test_waiting_period_states_the_eligibility_date_for_a_member(kb):
    result = kb.waiting_period("Type 2 Diabetes Mellitus", member_id="EMP005")
    assert result["matched_condition"] == "diabetes"
    assert result["eligible_from"] == "2024-11-30"
    assert result["rule_ref"] == "waiting_periods.specific_conditions.diabetes"


# --- scope -------------------------------------------------------------------


def test_a_member_scope_cannot_read_another_members_claim(kb):
    """The seam that makes member access a config change rather than a rewrite —
    proven before there is any authentication to construct it from."""
    assert kb.get_claim("CLM_AAAA1111", Scope.member("EMP001"))["claim_id"] == "CLM_AAAA1111"
    with pytest.raises(Unavailable) as refused:
        kb.get_claim("CLM_BBBB2222", Scope.member("EMP001"))
    # Indistinguishable from an unknown claim: whether a claim exists is itself
    # something a member should not be able to probe for.
    assert "No claim 'CLM_BBBB2222'" in refused.value.detail


def test_find_claims_never_returns_claims_outside_the_scope(kb):
    found = kb.find_claims(Scope.member("EMP001"))
    assert {c["member_id"] for c in found["claims"]} == {"EMP001"}


def test_portfolio_figures_are_out_of_scope_for_a_member(kb):
    with pytest.raises(Unavailable):
        kb.portfolio(Scope.member("EMP001"))
    assert kb.portfolio(Scope.ops())["total"] == 2


# --- the gates ---------------------------------------------------------------


def test_a_citation_that_was_never_retrieved_is_rejected(kb):
    """The clause is real, but nothing this turn retrieved it — so the model was
    citing a clause whose contents it invented."""
    assistant = Assistant(Settings(openai_api_key=None), chat_fn=scripted(
        answer_round("Dental is capped at the sub-limit.",
                     [{"kind": "policy", "ref": "opd_categories.dental.sub_limit"}])
    ))
    result = ask(assistant, kb, "What is the dental sub-limit?")

    assert result.grounded is False
    assert "citations not retrieved this turn" in result.refusals[0]


def test_an_amount_no_tool_returned_is_rejected(kb):
    """The pipeline is the only thing allowed to produce a number."""
    assistant = Assistant(Settings(openai_api_key=None), chat_fn=scripted(
        {"tool_calls": [{"id": "1", "name": "lookup_policy",
                         "arguments": {"path": "coverage.per_claim_limit"}}]},
        answer_round("You would be paid ₹4,200 on this claim.",
                     [{"kind": "policy", "ref": "coverage.per_claim_limit"}]),
    ))
    result = ask(assistant, kb, "How much would I get?")

    assert result.grounded is False
    assert any("amounts no tool returned" in r for r in result.refusals)
    assert "4,200" in result.refusals[0]


def test_a_grounded_answer_passes_both_gates(kb):
    assistant = Assistant(Settings(openai_api_key=None), chat_fn=scripted(
        {"tool_calls": [{"id": "1", "name": "lookup_policy",
                         "arguments": {"path": "coverage.per_claim_limit"}}]},
        answer_round("The per-claim limit is ₹5000.",
                     [{"kind": "policy", "ref": "coverage.per_claim_limit"}]),
    ))
    result = ask(assistant, kb, "What is the per-claim limit?")

    assert result.grounded is True
    assert result.refusals == []
    assert [c.ref for c in result.citations] == ["coverage.per_claim_limit"]


def test_restating_a_figure_the_user_supplied_is_allowed(kb):
    """Otherwise the gate refuses the assistant for repeating the question."""
    assistant = Assistant(Settings(openai_api_key=None), chat_fn=scripted(
        {"tool_calls": [{"id": "1", "name": "category_rules", "arguments": {"category": "DENTAL"}}]},
        answer_round("Whether a ₹9,000 dental claim is payable depends on the procedure.",
                     [{"kind": "policy", "ref": "opd_categories.dental"}]),
    ))
    result = ask(assistant, kb, "Would a ₹9,000 dental claim be approved?")
    assert result.grounded is True


def test_a_portfolio_answer_has_something_to_cite(kb):
    """Aggregates need a reference too, or every answer about them is refused for
    citing something that was never retrieved."""
    assistant = Assistant(Settings(openai_api_key=None), chat_fn=scripted(
        {"tool_calls": [{"id": "1", "name": "portfolio", "arguments": {}}]},
        answer_round("Two claims are on record.",
                     [{"kind": "portfolio", "ref": "portfolio.recent_claims"}]),
    ))
    result = ask(assistant, kb, "How many claims have we processed?")
    assert result.grounded is True
    assert result.refusals == []


def test_an_answer_that_cites_nothing_is_not_grounded(kb):
    """The citation check only validates citations that are present, so an
    uncited answer slipped through as grounded — which is how "what architecture
    does this use" came back as confident general knowledge from no source."""
    assistant = Assistant(Settings(openai_api_key=None), chat_fn=scripted(
        {"tool_calls": [{"id": "1", "name": "search_docs",
                         "arguments": {"text": "architecture"}}]},
        answer_round("It uses a tool-augmented architecture with specialised APIs.", []),
    ))
    result = ask(assistant, kb, "What architecture does this application use?")

    assert result.grounded is False
    assert any(r.startswith("no citation") for r in result.refusals)


def test_doc_anchors_are_reproducible_from_ascii(kb):
    """Eval-report headings carry status emoji, and a model asked to quote one
    back mangles it — which failed the gate on a citation that was correct."""
    from app.kb.retrieval import anchor

    assert anchor("TC002 — Unreadable Document ✅") == "tc002-unreadable-document"
    assert anchor("Adjudication rule order (deterministic)") == "adjudication-rule-order-deterministic"
    found = kb.search_docs("unreadable blurred document re-upload")
    assert all(r.isascii() for r in [s["rule_ref"] for s in found["sections"]])


def test_a_citation_differing_only_in_decoration_still_counts(kb):
    """Rejecting a citation over case or punctuation teaches the reader to
    distrust a banner that fired on a typo."""
    assistant = Assistant(Settings(openai_api_key=None), chat_fn=scripted(
        {"tool_calls": [{"id": "1", "name": "lookup_policy",
                         "arguments": {"path": "coverage.per_claim_limit"}}]},
        answer_round("The per-claim limit is 5000.",
                     [{"kind": "policy", "ref": "Coverage.Per_Claim_Limit"}]),
    ))
    result = ask(assistant, kb, "What is the per-claim limit?")

    assert result.grounded is True
    # Quoted back the way the source spells it, not the way the model typed it.
    assert [c.ref for c in result.citations] == ["coverage.per_claim_limit"]


def test_the_project_documents_are_searchable_and_citable(kb):
    """How the system behaves is written down; answering it from the model's own
    knowledge sounds right and is sourced from nothing."""
    found = kb.search_docs("how does extraction handle a blurred or unreadable bill")

    assert found["sections"], "expected at least one matching doc section"
    assert all(s["rule_ref"].startswith("docs/") for s in found["sections"])
    assert any("#" in s["rule_ref"] for s in found["sections"])


def test_quoting_an_amount_a_tool_did_return_is_allowed(kb):
    assistant = Assistant(Settings(openai_api_key=None), chat_fn=scripted(
        {"tool_calls": [{"id": "1", "name": "get_claim", "arguments": {"claim_id": "CLM_AAAA1111"}}]},
        answer_round("It was approved for ₹1,350.", [{"kind": "claim", "ref": "CLM_AAAA1111"}]),
    ))
    result = ask(assistant, kb, "What happened to CLM_AAAA1111?")
    assert result.grounded is True


# --- degradation -------------------------------------------------------------


def test_a_pinned_claim_is_fetched_before_the_model_is_asked(kb):
    assistant = Assistant(Settings(openai_api_key=None), chat_fn=scripted(
        answer_round("It was approved.", [{"kind": "claim", "ref": "CLM_AAAA1111"}])
    ))
    result = ask(assistant, kb, "Why was this decided that way?", claim_id="CLM_AAAA1111")
    assert result.grounded is True
    assert any(step.action == "retrieve: get_claim" for step in result.trace.steps)


def test_without_a_model_a_claim_question_still_answers_from_the_store(kb):
    """No API key: routed by rule, answered from retrieved material, and honest
    that it was not explained."""
    assistant = Assistant(Settings(openai_api_key=None))
    result = ask(assistant, kb, "Why was CLM_AAAA1111 decided that way?")

    assert assistant.is_configured is False
    assert result.grounded is False
    assert result.refusals == ["no_model_configured"]
    assert "CLM_AAAA1111" in result.answer and "APPROVED" in result.answer


def test_without_a_model_a_policy_question_returns_the_closest_clauses(kb):
    result = ask(Assistant(Settings(openai_api_key=None)), kb, "is teeth whitening covered")
    assert "whitening" in result.answer.lower()


def test_a_model_outage_mid_turn_degrades_instead_of_failing(kb):
    def explode(messages, tools):
        raise RuntimeError("upstream 503")

    result = ask(Assistant(Settings(openai_api_key=None), chat_fn=explode), kb, "CLM_AAAA1111?")
    assert result.grounded is False
    assert result.refusals == ["model_unavailable"]
    assert "CLM_AAAA1111" in result.answer


def test_every_turn_carries_a_trace_with_timings(kb):
    result = ask(Assistant(Settings(openai_api_key=None)), kb, "what is covered for dental")
    assert result.trace.steps
    assert all(step.duration_ms is not None for step in result.trace.steps)


# --- endpoint ----------------------------------------------------------------


def test_endpoint_answers_without_a_model_configured(tmp_path):
    with TestClient(create_app(database_path=tmp_path / "claims.db")) as client:
        body = client.post(
            "/assistant/chat",
            json={"messages": [{"role": "user", "content": "what is the per-claim limit?"}]},
        ).json()
    assert body["assistant"] == "no model configured"
    assert body["grounded"] is False
    assert body["trace"]["steps"]


def test_endpoint_rejects_a_malformed_conversation(tmp_path):
    with TestClient(create_app(database_path=tmp_path / "claims.db")) as client:
        assert client.post("/assistant/chat", json={"messages": []}).status_code == 422
