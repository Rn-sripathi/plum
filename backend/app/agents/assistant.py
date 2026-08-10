"""Claims assistant — a conversational surface over the knowledge base.

It answers three kinds of question: why a claim was decided the way it was,
what the policy says, and what the portfolio looks like. It does not decide
anything. That boundary is enforced in code rather than requested in a prompt:

* **Citation gate.** Every citation must be a `rule_ref` or claim id that the
  retrieval actually returned *this turn*. A real-but-unretrieved clause is
  rejected too, because the model would be citing a clause whose contents it
  invented.
* **Currency gate.** Any rupee figure in the answer must have come out of a
  tool. The pipeline is the only thing allowed to produce an amount.
* **Answering is a tool call**, so the reply is always structured; there is no
  free-text mode to fall out of.

When a gate rejects an answer, the caller gets the retrieved material with
`grounded: false` and the failed check named — never a generated answer dressed
as a sourced one.

With no `OPENAI_API_KEY` there is no model to route with, so a deterministic
router handles the turn: a claim id goes to the store, anything else to policy
search. Reduced, honest, and still useful — the same posture as the rest of the
system without an LLM.
"""

import json
import re
from collections.abc import Callable
from time import perf_counter
from typing import Any

from app.core.config import Settings
from app.kb.retrieval import KnowledgeBase, Scope, Unavailable, amounts_in, refs_in
from app.models import Outcome
from app.models.assistant import ChatAnswer, ChatMessage, Citation
from app.orchestrator.trace import TraceBuilder

MAX_TOOL_ITERATIONS = 4
CLAIM_ID = re.compile(r"\bCLM_[A-Z0-9]{4,}\b", re.IGNORECASE)
# Rupee figures the answer asserts: "₹1,350", "1350 rupees", "INR 1350".
CURRENCY = re.compile(r"(?:₹|\bINR\s*)([\d,]+(?:\.\d+)?)|\b([\d,]+(?:\.\d+)?)\s*rupees?\b", re.I)
NUMBER = re.compile(r"[\d,]+(?:\.\d+)?")

SYSTEM_PROMPT = """You are the assistant inside an insurance claims console, used by the \
operations team that reviews adjudicated claims.

WHAT YOU DO
- Explain why a claim was decided as it was, from its recorded trace.
- Answer what the policy says, from the policy clauses.
- Report portfolio figures.
- On request, draft the wording to send a member: name what was found, what is \
required, and what to do next.

WHAT YOU NEVER DO
- Never state an amount, a payout or a decision that a tool did not return. You do not \
adjudicate. If asked whether a claim would be approved, explain the rules that would \
apply and offer to run it through the pipeline, which is what actually decides.
- Never cite a clause you did not retrieve this turn. Retrieve it first.
- Never give medical advice.

HOW TO WORK
- Retrieve before answering. Prefer `lookup_policy` and `category_rules` for exact \
questions; `search_policy` when the wording is a paraphrase of a clause.
- Then call `submit_answer` with your answer and a citation for every assertion.
- If retrieval does not support an answer, say so in `submit_answer` and cite nothing.
- Be specific and brief. Quote figures and dates exactly as retrieved."""

_ANSWER_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_answer",
        "description": "Return the final answer with a citation for every assertion.",
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": ["policy", "claim", "portfolio", "document"],
                            },
                            "ref": {"type": "string"},
                            "detail": {"type": "string"},
                        },
                        "required": ["kind", "ref"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["answer", "citations"],
            "additionalProperties": False,
        },
    },
}


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


RETRIEVAL_TOOLS = [
    _tool(
        "lookup_policy",
        "Exact value at a policy path, e.g. 'coverage.per_claim_limit' or "
        "'opd_categories.dental.sub_limit'. Use for precise questions.",
        {"path": {"type": "string"}},
        ["path"],
    ),
    _tool(
        "search_policy",
        "Find policy concepts close in meaning to a phrase. Use when the question "
        "paraphrases a clause, e.g. 'is physiotherapy covered'.",
        {"text": {"type": "string"}},
        ["text"],
    ),
    _tool(
        "category_rules",
        "Everything governing one treatment category: terms, required documents, and "
        "every exclusion that reaches it. Categories: CONSULTATION, DIAGNOSTIC, "
        "PHARMACY, DENTAL, VISION, ALTERNATIVE_MEDICINE.",
        {"category": {"type": "string"}},
        ["category"],
    ),
    _tool(
        "waiting_period",
        "The waiting period for a condition, and when a given member becomes eligible.",
        {"condition": {"type": "string"}, "member_id": {"type": "string"}},
        ["condition"],
    ),
    _tool(
        "member",
        "A member's roster record and the patients their policy covers.",
        {"member_id": {"type": "string"}},
        ["member_id"],
    ),
    _tool(
        "get_claim",
        "One claim's decision, reasons, financial breakdown and trace.",
        {"claim_id": {"type": "string"}},
        ["claim_id"],
    ),
    _tool(
        "find_claims",
        "Claims matching filters. status: APPROVED|PARTIAL|REJECTED|MANUAL_REVIEW|"
        "DOCUMENTS_REQUIRED. rejection_reason e.g. WAITING_PERIOD.",
        {
            "status": {"type": "string"},
            "category": {"type": "string"},
            "rejection_reason": {"type": "string"},
            "member_id": {"type": "string"},
        },
        [],
    ),
    _tool(
        "portfolio",
        "Portfolio figures over recent claims: decision mix, payout ratio, confidence, "
        "stop reasons, per-stage timing.",
        {},
        [],
    ),
]

# (name, whether the call is scoped to who is asking)
_DISPATCH: dict[str, bool] = {
    "lookup_policy": False,
    "search_policy": False,
    "category_rules": False,
    "waiting_period": False,
    "member": True,
    "get_claim": True,
    "find_claims": True,
    "portfolio": True,
}

ChatFn = Callable[[list[dict], list[dict]], dict]
"""Takes (messages, tools) and returns {"tool_calls": [...]} — one step of the loop.

Injected so the loop can be tested without a model, the same way the semantic
index takes an embedder.
"""


def _openai_chat(settings: Settings) -> ChatFn:
    from openai import OpenAI

    client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )

    def chat(messages: list[dict], tools: list[dict]) -> dict:
        response = client.chat.completions.create(
            model=settings.openai_model, messages=messages, tools=tools, tool_choice="required"
        )
        message = response.choices[0].message
        return {
            "tool_calls": [
                {
                    "id": call.id,
                    "name": call.function.name,
                    "arguments": json.loads(call.function.arguments or "{}"),
                }
                for call in (message.tool_calls or [])
            ]
        }

    return chat


def _digits(text: str) -> str:
    return text.replace(",", "").rstrip("0").rstrip(".") if "." in text else text.replace(",", "")


class Assistant:
    def __init__(self, settings: Settings, chat_fn: ChatFn | None = None):
        self._settings = settings
        self._chat = chat_fn or (_openai_chat(settings) if settings.openai_api_key else None)

    @property
    def is_configured(self) -> bool:
        return self._chat is not None

    def answer(self, messages: list[ChatMessage], kb: KnowledgeBase, scope: Scope,
               claim_id: str | None = None) -> ChatAnswer:
        """Answer the latest turn, retrieving first and checking afterwards."""
        tb = TraceBuilder("ASSISTANT")
        question = messages[-1].content
        retrieved: list[tuple[str, Any]] = []

        tb.step(
            "assistant", "receive question", Outcome.PASS,
            f"{len(messages)} message(s) in scope "
            f"{'operations (unrestricted)' if scope.is_ops else scope.member_id}"
            + (f", pinned to claim {claim_id}" if claim_id else "")
            + ".",
        )

        if claim_id:
            # A pinned claim is context the user already chose; fetch it up front
            # so "why was this rejected" needs no id in the sentence.
            self._run_tool("get_claim", {"claim_id": claim_id}, kb, scope, tb, retrieved)

        if self._chat is None:
            return self._without_model(question, kb, scope, tb, retrieved)

        conversation: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *({"role": m.role, "content": m.content} for m in messages),
        ]
        for name, payload in retrieved:
            conversation.append(
                {"role": "system", "content": f"Retrieved {name}: {json.dumps(payload, default=str)}"}
            )

        tools = [*RETRIEVAL_TOOLS, _ANSWER_TOOL]
        for _ in range(MAX_TOOL_ITERATIONS):
            started = perf_counter()
            try:
                step = self._chat(conversation, tools)
            except Exception as exc:
                tb.step(
                    "assistant", "model call", Outcome.DEGRADED,
                    f"The model was unreachable ({exc}); answering from retrieved material only.",
                    duration_ms=round((perf_counter() - started) * 1000, 1),
                )
                return self._fallback(question, kb, scope, tb, retrieved, ["model_unavailable"])

            calls = step.get("tool_calls") or []
            if not calls:
                break
            answer_call = next((c for c in calls if c["name"] == "submit_answer"), None)
            if answer_call is not None:
                return self._check(answer_call["arguments"], tb, retrieved, kb, messages)
            for call in calls:
                result = self._run_tool(call["name"], call["arguments"], kb, scope, tb, retrieved)
                conversation.append(
                    {
                        "role": "system",
                        "content": f"Result of {call['name']}: {json.dumps(result, default=str)}",
                    }
                )

        tb.step(
            "assistant", "answer", Outcome.DEGRADED,
            f"No answer was submitted within {MAX_TOOL_ITERATIONS} retrieval rounds.",
        )
        return self._fallback(question, kb, scope, tb, retrieved, ["no_answer_submitted"])

    # --- tools --------------------------------------------------------------

    def _run_tool(self, name: str, arguments: dict, kb: KnowledgeBase, scope: Scope,
                  tb: TraceBuilder, retrieved: list) -> Any:
        if name not in _DISPATCH:
            tb.step("assistant", f"retrieve: {name}", Outcome.FAIL, f"No such tool '{name}'.")
            return {"error": f"No such tool '{name}'."}
        started = perf_counter()
        method = getattr(kb, name)
        try:
            payload = method(**arguments, scope=scope) if _DISPATCH[name] else method(**arguments)
        except Unavailable as exc:
            tb.step(
                "assistant", f"retrieve: {name}", Outcome.SKIPPED, exc.detail,
                duration_ms=round((perf_counter() - started) * 1000, 1),
            )
            return {"unavailable": exc.detail}
        except TypeError as exc:  # the model passed arguments the tool does not take
            tb.step("assistant", f"retrieve: {name}", Outcome.FAIL, f"Bad arguments: {exc}")
            return {"error": f"Bad arguments for {name}: {exc}"}

        retrieved.append((name, payload))
        tb.step(
            "assistant", f"retrieve: {name}", Outcome.PASS,
            f"{name}({', '.join(f'{k}={v}' for k, v in arguments.items()) or '—'}) returned "
            f"{len(refs_in(payload))} citable reference(s).",
            input_summary=json.dumps(arguments, default=str) if arguments else None,
            duration_ms=round((perf_counter() - started) * 1000, 1),
        )
        return payload

    # --- gates --------------------------------------------------------------

    def _check(self, submitted: dict, tb: TraceBuilder, retrieved: list,
               kb: KnowledgeBase, messages: list[ChatMessage]) -> ChatAnswer:
        """Hold the generated answer to what retrieval actually returned."""
        answer = str(submitted.get("answer") or "").strip()
        citations = [
            Citation(
                kind=c.get("kind", "policy"), ref=str(c.get("ref", "")), detail=c.get("detail")
            )
            for c in submitted.get("citations") or []
            if c.get("ref")
        ]
        allowed_refs = set().union(*(refs_in(p) for _, p in retrieved)) if retrieved else set()
        allowed_amounts = {
            _digits(a) for _, p in retrieved for a in amounts_in(p) if isinstance(a, str)
        }
        # A figure the user themselves put in the question is not an invention:
        # restating "a ₹9,000 dental claim" back to them has to be allowed, or the
        # gate refuses the assistant for repeating the question.
        allowed_amounts |= {
            _digits(figure)
            for message in messages
            if message.role == "user"
            for figure in NUMBER.findall(message.content)
        }

        refusals: list[str] = []
        invented = [c.ref for c in citations if c.ref not in allowed_refs]
        if invented:
            refusals.append(f"citations not retrieved this turn: {', '.join(invented)}")
        unsourced = [
            figure
            for match in CURRENCY.finditer(answer)
            for figure in [match.group(1) or match.group(2)]
            if _digits(figure) not in allowed_amounts
        ]
        if unsourced:
            refusals.append(f"amounts no tool returned: {', '.join(unsourced)}")

        if refusals:
            tb.step(
                "assistant", "grounding check", Outcome.FAIL,
                "The generated answer was rejected — " + "; ".join(refusals)
                + ". Returning retrieved material instead.",
            )
            return _grounded_failure(retrieved, refusals, kb, tb)

        tb.step(
            "assistant", "grounding check", Outcome.PASS,
            f"{len(citations)} citation(s), all retrieved this turn; no unsourced amounts.",
        )
        return ChatAnswer(
            answer=answer,
            citations=citations,
            grounded=True,
            degraded_components=kb.degraded,
            trace=tb.build(),
        )

    # --- no model -----------------------------------------------------------

    def _without_model(self, question: str, kb: KnowledgeBase, scope: Scope, tb: TraceBuilder,
                       retrieved: list) -> ChatAnswer:
        tb.step(
            "assistant", "routing", Outcome.DEGRADED,
            "No language model is configured, so the question is routed by rule: a claim "
            "id to the store, anything else to policy search. Retrieved clauses are "
            "returned verbatim rather than explained.",
        )
        return self._fallback(question, kb, scope, tb, retrieved, ["no_model_configured"])

    def _fallback(self, question: str, kb: KnowledgeBase, scope: Scope, tb: TraceBuilder,
                  retrieved: list, refusals: list[str]) -> ChatAnswer:
        """Deterministic answer: retrieve by rule, report what was found."""
        if not retrieved:
            found = CLAIM_ID.search(question)
            if found:
                self._run_tool(
                    "get_claim", {"claim_id": found.group(0).upper()}, kb, scope, tb, retrieved
                )
            else:
                self._run_tool("search_policy", {"text": question}, kb, scope, tb, retrieved)
        return _grounded_failure(retrieved, refusals, kb, tb)


# What to say instead of an answer, per reason the answer was withheld. Naming
# the reason is the point: "I cannot predict a decision" is useful, where a bare
# list of clauses looks like the assistant simply failed.
_PREFACE = {
    "amounts": (
        "I can't predict a decision or an amount — the pipeline decides that, and it is "
        "the only thing that should. Submit the claim to get a real answer. Here is what "
        "governs it:"
    ),
    "citations": (
        "I couldn't ground that answer in what I retrieved, so I'm showing the source "
        "material instead of an explanation of it:"
    ),
    "no_model_configured": (
        "No language model is configured, so I can retrieve but not explain. Here is what "
        "the policy and the claim records say:"
    ),
    "model_unavailable": (
        "The language model is unreachable, so this is retrieved material rather than an "
        "explanation:"
    ),
    "no_answer_submitted": "Here is what I found:",
}


def _preface_for(refusals: list[str]) -> str:
    for refusal in refusals:
        if refusal.startswith("amounts"):
            return _PREFACE["amounts"]
        if refusal.startswith("citations"):
            return _PREFACE["citations"]
        if refusal in _PREFACE:
            return _PREFACE[refusal]
    return _PREFACE["no_answer_submitted"]


def _primary_refs(retrieved: list[tuple[str, Any]]) -> list[str]:
    """One or two citations per retrieval, not every nested reference.

    A category lookup legitimately touches eighteen exclusion clauses; listing
    all of them as citations is noise that hides which clause actually answered
    the question.
    """
    refs: list[str] = []
    for name, payload in retrieved:
        if not isinstance(payload, dict):
            continue
        direct = payload.get("rule_ref") or payload.get("claim_id")
        if isinstance(direct, str):
            refs.append(direct)
        elif name == "search_policy":
            refs += [
                hit["rule_ref"]
                for hit in (payload.get("hits") or [])[:3]
                if isinstance(hit, dict) and hit.get("rule_ref")
            ]
    return list(dict.fromkeys(refs))


def _grounded_failure(retrieved: list, refusals: list[str], kb: KnowledgeBase,
                      tb: TraceBuilder) -> ChatAnswer:
    """The honest answer when generation is withheld: say why, then show sources."""
    found = _summarize_retrieved(retrieved)
    return ChatAnswer(
        answer=f"{_preface_for(refusals)}\n{found}"
        if found
        else "I could not find anything in the policy or the claim records for that.",
        citations=[Citation(kind="policy", ref=ref) for ref in _primary_refs(retrieved)],
        grounded=False,
        refusals=refusals,
        degraded_components=kb.degraded,
        trace=tb.build(),
    )


def _summarize_retrieved(retrieved: list[tuple[str, Any]]) -> str:
    """Render retrieved material as plain text — no model involved.

    Deliberately reads as evidence rather than an answer: it is what was found,
    not a claim about what it means.
    """
    lines: list[str] = []
    for name, payload in retrieved:
        if name == "get_claim":
            lines.append(
                f"Claim {payload['claim_id']} ({payload['category']}, member "
                f"{payload['member_id']}) — {payload['status']}."
            )
            lines += [f"  · {reason}" for reason in payload["reasons"][:6]]
            lines += [f"  · {problem['message']}" for problem in payload["problems"][:4]]
        elif name == "search_policy":
            hits = payload.get("hits") or []
            if hits:
                lines.append(f"Closest policy clauses ({payload.get('source')} match):")
                lines += [f"  · {h['concept']} — {h['rule_ref']}" for h in hits]
        elif name == "lookup_policy":
            lines.append(f"{payload['rule_ref']} = {payload['value']}")
        elif name == "category_rules":
            lines.append(
                f"{payload['category']} requires "
                f"{', '.join(payload['required_documents']) or 'no documents'}; "
                f"{len(payload['exclusions'])} exclusion(s) reach it."
            )
        elif name == "waiting_period":
            eligible = payload.get("eligible_from")
            lines.append(
                f"{payload['condition']}: {payload['days']}-day waiting period "
                f"({payload['rule_ref']})"
                + (f", eligible from {eligible}." if eligible else ".")
            )
        elif name == "portfolio":
            mix = ", ".join(f"{m['status']} {m['count']}" for m in payload["decision_mix"])
            slowest = (payload["timing"] or [{}])[0]
            ratio = payload["money"]["payout_ratio"]
            lines.append(f"{payload['total']} claims: {mix}.")
            if ratio is not None:
                lines.append(
                    f"  · Payout ratio {ratio:.0%} "
                    f"({payload['money']['approved']} of {payload['money']['claimed']})."
                )
            if slowest.get("component"):
                lines.append(
                    f"  · Costliest stage {slowest['component']} at "
                    f"{slowest['per_claim_ms']}ms per claim."
                )
        elif name == "find_claims":
            lines.append(f"{payload['matched']} claim(s) matched:")
            lines += [
                f"  · {c['claim_id']} — {c['member_id']}, {c['category']}, {c['status']}"
                for c in payload["claims"][:8]
            ]
        elif name == "member":
            member = payload["member"]
            lines.append(
                f"{member['member_id']} is {member['name']}, joined "
                f"{member.get('join_date') or 'unknown'}; covers "
                f"{', '.join(payload['covered_patients'])}."
            )
        elif "unavailable" in payload:
            lines.append(f"{name}: {payload['unavailable']}")
        else:
            lines.append(f"{name}: {json.dumps(payload, default=str)[:400]}")
    return "\n".join(lines)
