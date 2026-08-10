"""Assistant contracts — the conversational surface over the knowledge base.

The assistant explains decisions and policy; it never makes them. That is a
contract, not a prompt preference: `ChatAnswer.grounded` is False whenever the
answer failed the citation or currency gate, and the caller is told so rather
than shown an ungrounded answer as if it were sourced.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .trace import DecisionTrace

CitationKind = Literal["policy", "claim", "portfolio", "document"]


class ChatMessage(BaseModel):
    """One turn of the conversation.

    The server keeps no session: the client posts the history it wants
    considered, which is the same statelessness the rest of the API has.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    claim_id: str | None = Field(
        default=None,
        description="Scopes the conversation to one claim, so 'why was this rejected' needs no id.",
    )
    member_id: str | None = Field(
        default=None,
        description=(
            "Restricts every claim lookup to this member. Absent = operations "
            "scope (unrestricted), which is what this console runs as until it "
            "has authentication."
        ),
    )


class Citation(BaseModel):
    """Where an assertion came from.

    `ref` is a pointer, not prose: a policy `rule_ref` that resolves against
    `policy_terms.json`, or a claim id that resolves against the store. That is
    what makes a citation checkable instead of decorative.
    """

    model_config = ConfigDict(extra="forbid")

    kind: CitationKind
    ref: str
    detail: str | None = None


class ChatAnswer(BaseModel):
    """What the assistant returns for one turn."""

    answer: str
    citations: list[Citation] = Field(default_factory=list)
    grounded: bool = Field(
        description=(
            "True when every citation was retrieved during this turn and no "
            "unsourced amount appears in the answer. False means the checks "
            "rejected the generated answer and this is retrieved material only."
        )
    )
    refusals: list[str] = Field(
        default_factory=list,
        description="Checks that failed, named so the caller can see why.",
    )
    degraded_components: list[str] = Field(default_factory=list)
    trace: DecisionTrace = Field(
        description="Retrieval and generation steps, same contract as a claim's trace."
    )
