"""Knowledge base for the assistant — four sources behind one typed surface.

Each source is used for what it is actually good at, and each degrades:

| Source              | Job                                              | Fallback           |
|---------------------|--------------------------------------------------|--------------------|
| `PolicySnapshot`    | exact structured lookups (limits, days, terms)   | always present     |
| `SemanticPolicyIndex` (Qdrant) | paraphrase recall over policy concepts | token matcher      |
| `PolicyGraph` (Neo4j)          | traversals: every exclusion reaching a category, member + dependents | snapshot |
| `ClaimStore` (Postgres)        | claims, decisions, traces, portfolio  | policy answers only |

Nothing here generates prose. Every method returns typed data carrying the
`rule_ref` the adjudication engine stamps on decisions, so an answer's
citations point at the same clauses the trace does, and can be checked.

Deliberately absent: any method that computes an amount or a verdict. The
assistant explains what was decided; `engine/` decides.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core.analytics import summarize
from app.core.config import REPO_ROOT
from app.engine.matching import distinctive_tokens, tokens
from app.kb.graph import PolicyGraph
from app.kb.semantic import SemanticHit, SemanticPolicyIndex
from app.kb.snapshot import PolicySnapshot
from app.models import ClaimCategory

MAX_CLAIMS_WINDOW = 500
# The documents the assistant may quote — the same allowlist the API serves, so
# there is one answer to "which files are public".
PUBLIC_DOCS = {
    "architecture": "ARCHITECTURE.md",
    "contracts": "CONTRACTS.md",
    "assumptions": "ASSUMPTIONS.md",
    "eval": "EVAL_REPORT.md",
}


@dataclass(frozen=True)
class Scope:
    """Who is asking, and therefore which claims they may read.

    Threaded through every claim lookup from the start even though this console
    runs unrestricted: the day it gets authentication, member access is a scope
    constructed at the edge, not a rewrite of the retrieval layer.
    """

    member_id: str | None = None

    @classmethod
    def ops(cls) -> "Scope":
        """Unrestricted — an adjudicator reviewing any claim."""
        return cls(member_id=None)

    @classmethod
    def member(cls, member_id: str) -> "Scope":
        return cls(member_id=member_id)

    @property
    def is_ops(self) -> bool:
        return self.member_id is None

    def allows(self, member_id: str | None) -> bool:
        return self.is_ops or member_id == self.member_id


class Unavailable(Exception):
    """A source could not answer. Carries what to tell the caller instead."""

    def __init__(self, source: str, detail: str):
        super().__init__(detail)
        self.source = source
        self.detail = detail


def anchor(heading: str) -> str:
    """A citable anchor for a document heading.

    Headings in the eval report carry status emoji ("## TC002 — Unreadable
    Document ✅"), and a model asked to quote such a reference back mangles the
    emoji — which failed the grounding gate on a citation that was correct. An
    anchor a model can reproduce from ASCII is the fix, and it matches how
    markdown renderers slug headings anyway.
    """
    kept = [c if c.isalnum() else " " for c in heading.lower()]
    return "-".join("".join(kept).split())


def _walk(data: Any, path: str) -> Any:
    """Resolve a dotted `rule_ref` path (with `[i]` indexes) through plain data.

    Traversal is over a dumped dict, never over Python attributes, so a path
    from a model can only ever reach policy data — there is no object graph to
    walk into.
    """
    node = data
    for part in path.split("."):
        name, _, index = part.partition("[")
        if name:
            if not isinstance(node, dict) or name not in node:
                raise KeyError(path)
            node = node[name]
        if index:
            position = int(index.rstrip("]"))
            if not isinstance(node, list) or position >= len(node):
                raise KeyError(path)
            node = node[position]
    return node


class KnowledgeBase:
    """Read-only retrieval over the policy, the claim store and the docs."""

    def __init__(
        self,
        snapshot: PolicySnapshot,
        semantic: SemanticPolicyIndex | None = None,
        graph: PolicyGraph | None = None,
        store: Any = None,
    ):
        self.snapshot = snapshot
        self.semantic = semantic
        self.graph = graph
        self.store = store
        self.degraded: list[str] = []

    def _degrade(self, component: str) -> None:
        if component not in self.degraded:
            self.degraded.append(component)

    # --- policy -------------------------------------------------------------

    def lookup_policy(self, path: str) -> dict:
        """Exact value at a `rule_ref` path.

        Structured questions ('what is the per-claim limit') have exact answers,
        and routing them through a vector search would invent a chance to be
        wrong where none needs to exist.
        """
        try:
            value = _walk(self.snapshot.terms.model_dump(mode="json"), path)
        except (KeyError, ValueError, IndexError) as exc:
            raise Unavailable("policy", f"No policy clause at '{path}'.") from exc
        return {"rule_ref": path, "value": value}

    def search_policy(self, text: str, top_k: int = 4) -> dict:
        """Concepts close in meaning to `text` — the paraphrase channel.

        Qdrant when embeddings are configured, otherwise the same token matcher
        the engine falls back to, so 'is physio covered' still finds something
        with no API key at all.
        """
        if self.semantic is not None and self.semantic.is_configured:
            try:
                hits = self.semantic.search(text, top_k=top_k)
                return {
                    "source": "vector",
                    "hits": [
                        {
                            "concept": h.concept,
                            "concept_type": h.concept_type,
                            "rule_ref": h.rule_ref,
                            "score": round(h.score, 3),
                        }
                        for h in hits
                    ],
                }
            except Exception:
                self._degrade("semantic_index")
        return {"source": "tokens", "hits": self._token_search(text, top_k)}

    def _token_search(self, text: str, top_k: int) -> list[dict]:
        """Overlap of distinctive tokens — recall without embeddings."""
        query = tokens(text)
        scored: list[tuple[int, dict]] = []
        for concept in self._policy_concepts():
            overlap = len(distinctive_tokens(concept["concept"]) & query)
            if overlap:
                scored.append((overlap, concept))
        scored.sort(key=lambda pair: -pair[0])
        return [
            {**concept, "score": None, "overlap": overlap} for overlap, concept in scored[:top_k]
        ]

    def _policy_concepts(self) -> list[dict]:
        """Every clause the index would hold, built from the snapshot.

        Imported lazily from the semantic module so the two tiers can never
        disagree about what a policy concept is.
        """
        from app.kb.semantic import _concepts

        return _concepts(self.snapshot.terms)

    def search_docs(self, text: str, top_k: int = 3) -> dict:
        """Sections of the project documents closest to `text`.

        How the system behaves is written down in `docs/` — the architecture,
        the component contracts, the documented assumptions. Without this the
        model answers "how does extraction handle a blurred bill" from its own
        general knowledge, which sounds right and is sourced from nothing.

        Split on headings so a citation points at a section a reader can find.
        """
        query = tokens(text)
        scored: list[tuple[int, dict]] = []
        for slug, filename in PUBLIC_DOCS.items():
            path = REPO_ROOT / "docs" / filename
            if not path.is_file():
                continue
            heading = filename
            body: list[str] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("#"):
                    if body:
                        scored.append(self._doc_section(slug, heading, body, query))
                    heading = line.lstrip("# ").strip()
                    body = []
                else:
                    body.append(line)
            if body:
                scored.append(self._doc_section(slug, heading, body, query))
        scored.sort(key=lambda pair: -pair[0])
        return {
            "source": "docs",
            "sections": [section for overlap, section in scored[:top_k] if overlap > 0],
        }

    def _doc_section(self, slug: str, heading: str, body: list[str], query: set[str]) -> tuple:
        text = "\n".join(body).strip()
        overlap = len(distinctive_tokens(f"{heading} {text}") & query)
        return (
            overlap,
            {
                # Same key as a policy citation so the grounding gate sees it.
                "rule_ref": f"docs/{slug}#{anchor(heading)}",
                "heading": heading,
                "excerpt": text[:900],
            },
        )

    def category_rules(self, category: str) -> dict:
        """Everything that governs one treatment category.

        The graph answers this in one traversal — category terms, the documents
        it requires, and every exclusion that reaches it, global and specific.
        Unreachable graph falls back to the snapshot and says so.
        """
        try:
            cat = ClaimCategory(category.upper())
        except ValueError as exc:
            raise Unavailable(
                "policy",
                f"'{category}' is not a treatment category. Known: "
                f"{', '.join(c.value for c in ClaimCategory)}.",
            ) from exc

        terms = self.snapshot.category_terms(cat)
        reqs = self.snapshot.document_requirements(cat)
        key = cat.value.lower()
        exclusions = [
            {"clause": clause, "rule_ref": f"exclusions.conditions[{i}]", "reach": "policy-wide"}
            for i, clause in enumerate(self.snapshot.terms.exclusions.conditions)
        ]
        for scope_name, clauses in (
            ("dental", self.snapshot.terms.exclusions.dental_exclusions),
            ("vision", self.snapshot.terms.exclusions.vision_exclusions),
        ):
            if key == scope_name:
                exclusions += [
                    {
                        "clause": clause,
                        "rule_ref": f"exclusions.{scope_name}_exclusions[{i}]",
                        "reach": f"{scope_name} only",
                    }
                    for i, clause in enumerate(clauses)
                ]
        if terms is not None:
            exclusions += [
                {
                    "clause": procedure,
                    "rule_ref": f"opd_categories.{key}.excluded_procedures",
                    "reach": f"{key} only",
                }
                for procedure in terms.excluded_procedures + terms.excluded_items
            ]

        required = list(reqs.required) if reqs else []
        source = "snapshot"
        if self.graph is not None and self.graph.is_configured:
            try:
                from_graph = self.graph.document_requirements(
                    self.snapshot.terms.policy_id, cat.value
                )
                if from_graph:
                    required, source = from_graph, "graph"
            except Exception:
                self._degrade("policy_graph")

        return {
            "category": cat.value,
            "rule_ref": f"opd_categories.{key}",
            "terms": terms.model_dump(mode="json") if terms else None,
            "required_documents": required,
            "optional_documents": list(reqs.optional) if reqs else [],
            "requirements_source": source,
            "exclusions": exclusions,
        }

    def waiting_period(self, condition: str, member_id: str | None = None) -> dict:
        """When a condition becomes claimable, and for whom.

        A date, not a verdict: the same arithmetic the engine records in its
        rejection message, so the two can never state different dates.
        """
        keys = list(self.snapshot.terms.waiting_periods.specific_conditions)
        from app.engine.matching import match_condition_key

        matched = match_condition_key(condition, keys)
        days = (
            self.snapshot.terms.waiting_periods.specific_conditions[matched]
            if matched
            else self.snapshot.terms.waiting_periods.initial_waiting_period_days
        )
        rule_ref = (
            f"waiting_periods.specific_conditions.{matched}"
            if matched
            else "waiting_periods.initial_waiting_period_days"
        )
        result: dict[str, Any] = {
            "condition": condition,
            "matched_condition": matched,
            "days": days,
            "rule_ref": rule_ref,
        }
        if member_id:
            member = self.snapshot.get_member(member_id)
            if member is None:
                raise Unavailable("policy", f"No member '{member_id}' in the roster.")
            join = self.snapshot.effective_join_date(member)
            if join is not None:
                result["member"] = member.name
                result["join_date"] = join.isoformat()
                result["eligible_from"] = self.snapshot.waiting_period_end(
                    join, matched
                ).isoformat()
        return result

    def member(self, member_id: str, scope: Scope) -> dict:
        if not scope.allows(member_id):
            raise Unavailable("scope", "That member is outside this conversation's scope.")
        found = self.snapshot.get_member(member_id)
        if found is None:
            raise Unavailable("policy", f"No member '{member_id}' in the roster.")
        return {
            "rule_ref": "members",
            "member": found.model_dump(mode="json"),
            "covered_patients": [m.name for m in self.snapshot.eligible_patients(member_id)],
        }

    # --- claims -------------------------------------------------------------

    def get_claim(self, claim_id: str, scope: Scope) -> dict:
        """One recorded decision, with its reasons and trace.

        This is the only source for 'why was this rejected': the answer restates
        what the engine recorded, so the assistant cannot invent a reason the
        pipeline never gave.
        """
        if self.store is None:
            raise Unavailable("store", "The claim store is not available.")
        try:
            record = self.store.get(claim_id)
        except Exception as exc:
            self._degrade("claim_store")
            raise Unavailable("store", f"The claim store is unreachable ({exc}).") from exc
        if record is None:
            raise Unavailable("store", f"No claim '{claim_id}'.")
        if not scope.allows(record.get("member_id")):
            # Same message as an unknown claim: whether a claim exists is itself
            # information a member should not be able to probe for.
            raise Unavailable("store", f"No claim '{claim_id}'.")
        result = record["result"]
        return {
            "claim_id": claim_id,
            "member_id": record["member_id"],
            "category": record["category"],
            "status": record["status"],
            "decision": result.get("decision"),
            "approved_amount": result.get("approved_amount"),
            "confidence": result.get("confidence"),
            "reasons": result.get("reasons") or [],
            "rejection_reasons": result.get("rejection_reasons") or [],
            "problems": [
                {"kind": p["kind"], "message": p["message"], "action_needed": p["action_needed"]}
                for p in (result.get("problems") or [])
            ],
            "line_items": result.get("line_items") or [],
            "financial": result.get("financial"),
            "degraded_components": result.get("degraded_components") or [],
            "rule_refs": sorted(
                {
                    step["rule_ref"]
                    for step in (result.get("trace") or {}).get("steps") or []
                    if step.get("rule_ref")
                }
            ),
            "trace_steps": [
                {
                    "seq": step["seq"],
                    "component": step["component"],
                    "action": step["action"],
                    "outcome": step["outcome"],
                    "detail": step["detail"],
                    "rule_ref": step.get("rule_ref"),
                    "confidence_delta": step.get("confidence_delta"),
                }
                for step in (result.get("trace") or {}).get("steps") or []
            ],
        }

    def find_claims(
        self,
        scope: Scope,
        status: str | None = None,
        category: str | None = None,
        rejection_reason: str | None = None,
        member_id: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Claims matching typed filters.

        Filters are parameters, never generated query text: a model composing
        its own query against the claims table is a correctness and disclosure
        risk that a fixed filter set does not have.
        """
        if self.store is None:
            raise Unavailable("store", "The claim store is not available.")
        if member_id and not scope.allows(member_id):
            raise Unavailable("scope", "That member is outside this conversation's scope.")
        try:
            records = self.store.list_full(MAX_CLAIMS_WINDOW)
        except Exception as exc:
            self._degrade("claim_store")
            raise Unavailable("store", f"The claim store is unreachable ({exc}).") from exc

        wanted = member_id or scope.member_id
        matches = [
            r
            for r in records
            if scope.allows(r.get("member_id"))
            and (wanted is None or r.get("member_id") == wanted)
            and (status is None or r["status"] == status.upper())
            and (category is None or r["category"] == category.upper())
            and (
                rejection_reason is None
                or rejection_reason.upper() in (r["result"].get("rejection_reasons") or [])
            )
        ]
        return {
            "matched": len(matches),
            "claims": [
                {
                    "claim_id": r["claim_id"],
                    "member_id": r["member_id"],
                    "category": r["category"],
                    "status": r["status"],
                    "approved_amount": r["result"].get("approved_amount"),
                }
                for r in matches[:limit]
            ],
        }

    def portfolio(self, scope: Scope) -> dict:
        """Portfolio figures — the same aggregation the analytics view renders.

        Calling `summarize` rather than re-deriving anything is the point: a
        number quoted in conversation and the same number on the dashboard are
        one computation, so they cannot drift apart.
        """
        if not scope.is_ops:
            raise Unavailable(
                "scope", "Portfolio figures cover every member, so they are out of scope here."
            )
        if self.store is None:
            raise Unavailable("store", "The claim store is not available.")
        try:
            records = self.store.list_full(MAX_CLAIMS_WINDOW)
        except Exception as exc:
            self._degrade("claim_store")
            raise Unavailable("store", f"The claim store is unreachable ({exc}).") from exc
        # Carries a citable reference like every other source: without one there
        # is nothing an answer about the portfolio can legitimately cite, and the
        # grounding gate rejects the answer for having invented a reference.
        return {"rule_ref": "portfolio.recent_claims", **summarize(records)}


def refs_in(payload: Any) -> set[str]:
    """Every `rule_ref` a tool result carries, at any depth.

    The grounding gate compares an answer's citations against this: a citation
    the retrieval never returned is not a citation.
    """
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "rule_ref" and isinstance(value, str):
                found.add(value)
            elif key == "rule_refs" and isinstance(value, list):
                found.update(v for v in value if isinstance(v, str))
            elif key == "claim_id" and isinstance(value, str):
                found.add(value)
            else:
                found |= refs_in(value)
    elif isinstance(payload, list):
        for item in payload:
            found |= refs_in(item)
    return found


def amounts_in(payload: Any) -> set[str]:
    """Numeric strings appearing in tool output, for the currency gate."""
    found: set[str] = set()
    if isinstance(payload, dict):
        for value in payload.values():
            found |= amounts_in(value)
    elif isinstance(payload, list):
        for item in payload:
            found |= amounts_in(item)
    elif isinstance(payload, (int, float, Decimal)):
        text = f"{payload}"
        found.add(text)
        if text.endswith(".0"):
            found.add(text[:-2])
        if isinstance(payload, (int, float)) and float(payload).is_integer():
            found.add(f"{int(payload)}")
    elif isinstance(payload, str):
        found.add(payload)
    return found
