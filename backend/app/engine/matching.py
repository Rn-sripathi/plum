"""Deterministic text matching — the zero-LLM tier of semantic matching.

Maps free-text diagnoses/treatments/line items onto policy concepts
(exclusion clauses, waiting-period condition keys, procedure lists) using
token overlap over normalized text. Keywords are derived from the policy
strings themselves — nothing policy-specific is hardcoded here.

Matching rules (documented behavior, unit-tested):
- Tokens match by exact word equality, never substring — "Herniation" must
  NOT match the `hernia` waiting period.
- Waiting-period condition keys require ALL their distinctive tokens in the
  text — "Chronic Joint Pain" must NOT match `joint_replacement`.
- Exclusion clauses match on ANY distinctive token — "Morbid Obesity" matches
  "Obesity and weight loss programs".
- Generic words (treatment, programs, procedures…) are never distinctive.

In later phases an embedding/LLM matcher wraps this; this module remains the
final fallback (PLAN.md §4 resilience table).
"""

import re
from dataclasses import dataclass

# Common Indian medical shorthand (sample_documents_guide.md) expanded before
# matching. General medical knowledge, not policy logic.
SHORTHAND: dict[str, str] = {
    "htn": "hypertension",
    "t2dm": "diabetes",
    "t1dm": "diabetes",
    "dm2": "diabetes",
}

_STOPWORDS = {
    "and", "or", "of", "the", "a", "an", "to", "for", "with", "non",
    "medically", "necessary", "other", "related",
}

# Words too generic to identify a policy concept on their own.
_GENERIC = {
    "treatment", "treatments", "program", "programs", "programme", "programmes",
    "procedure", "procedures", "condition", "conditions", "disorder", "disorders",
    "surgery", "surgeries", "therapy", "therapies", "care", "health",
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    """Lowercased word tokens with shorthand expanded and stopwords removed."""
    words = _WORD_RE.findall(text.lower())
    expanded = {SHORTHAND.get(w, w) for w in words}
    return expanded - _STOPWORDS


def distinctive_tokens(concept: str) -> set[str]:
    """Tokens of a policy concept that are specific enough to match on."""
    return tokens(concept) - _GENERIC


@dataclass
class ConceptMatch:
    """A policy concept matched in free text."""

    concept: str
    matched_tokens: set[str]
    score: float  # 0..1 — fraction of the concept's distinctive tokens found


def match_exclusion(text: str, exclusion_clauses: list[str]) -> ConceptMatch | None:
    """Best exclusion clause matched by ANY distinctive token, or None."""
    text_tokens = tokens(text)
    best: ConceptMatch | None = None
    for clause in exclusion_clauses:
        distinct = distinctive_tokens(clause)
        hit = distinct & text_tokens
        if not hit:
            continue
        score = len(hit) / len(distinct)
        if best is None or score > best.score:
            best = ConceptMatch(concept=clause, matched_tokens=hit, score=score)
    return best


def match_condition_key(text: str, condition_keys: list[str]) -> str | None:
    """Waiting-period condition key whose distinctive tokens ALL appear in text.

    Condition keys are snake_case (e.g. 'joint_replacement'); requiring every
    distinctive token prevents 'Joint Pain' matching 'joint_replacement'.
    """
    text_tokens = tokens(text)
    for key in condition_keys:
        distinct = distinctive_tokens(key.replace("_", " "))
        if distinct and distinct <= text_tokens:
            return key
    return None


def match_in_list(item_description: str, procedures: list[str]) -> str | None:
    """Match a bill line item against a covered/excluded procedure list.

    Exact case-insensitive match first; otherwise all distinctive tokens of a
    listed procedure must appear in the item description.
    """
    needle = item_description.strip().lower()
    for proc in procedures:
        if proc.strip().lower() == needle:
            return proc
    item_tokens = tokens(item_description)
    for proc in procedures:
        distinct = distinctive_tokens(proc)
        if distinct and distinct <= item_tokens:
            return proc
    return None
