# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The generation gate: one question, asked of text rather than of a model.

    Is the supporting text for this item's correct answer present in what
    retrieval actually returned?

Everything the gate does is a consequence of asking that question of the
retrieved characters. It does not ask a model whether the item looks right. The
fake-organ result settles why: a generator and a checker drawn from the same
weights share a blind spot, so a model that will invent an answer will also
certify it, and the pair reads as two independent confirmations while being one.
An LLM "is this correct?" step here would not add a check — it would delete the
only one there is.

The gate is therefore mechanical, and it is allowed to be wrong in exactly one
direction: it drops items whose support is real but paraphrased. That is the
cheap error. The expensive error — shipping an item whose answer is in no
source — is the one it cannot make, because a citation is only ever built from
characters that were retrieved, and the quote is copied out of the source rather
than out of the candidate.

Two properties make the ruling re-checkable by someone who does not trust it:
the span is re-verified against the page it claims to come from before it is
accepted, and the reason for every rejection is a member of a closed set.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence

from .attribution import SpanRef
from .corpus_gateway import RetrievedChunk, spans_module
from .rejections import Reason


@dataclasses.dataclass(frozen=True)
class Ruling:
    """Ship with this citation, or drop for this reason. Never both, never neither."""

    span: SpanRef | None
    reason: Reason | None
    detail: str = ""

    def __post_init__(self) -> None:
        if (self.span is None) == (self.reason is None):
            raise ValueError("a ruling is exactly one of a span or a reason")

    @property
    def ships(self) -> bool:
        return self.span is not None

    @classmethod
    def ship(cls, span: SpanRef) -> Ruling:
        return cls(span=span, reason=None)

    @classmethod
    def drop(cls, reason: Reason, detail: str = "") -> Ruling:
        return cls(span=None, reason=reason, detail=detail)


#: The signature the graph depends on. Named so the boundary test can substitute
#: a deliberately broken gate and prove the service still refuses to ship.
GateRule = Callable[[Sequence[RetrievedChunk], str, Callable[[str], str]], Ruling]


def rule(
    retrieved: Sequence[RetrievedChunk],
    answer: str,
    page_text: Callable[[str], str],
) -> Ruling:
    """Assert the answer's support is in `retrieved`, or say why it is not.

    `page_text` is a lookup rather than a corpus, so the gate can be re-run over
    an archived trace by anyone who has the pages — the assertion is not the
    service's private property.
    """
    if not retrieved:
        return Ruling.drop(Reason.NO_RETRIEVAL, "retrieval returned no chunks")

    spans = spans_module()
    span = spans.support_for([chunk.chunk for chunk in retrieved], answer)
    if span is None:
        return Ruling.drop(
            Reason.ANSWER_NOT_IN_RETRIEVED_TEXT,
            f"no span supporting {answer!r} in "
            f"{len(retrieved)} retrieved chunks "
            f"({', '.join(chunk.chunk_id for chunk in retrieved[:4])}…)",
        )

    try:
        page = page_text(span.source_id)
    except KeyError:
        return Ruling.drop(
            Reason.SPAN_FAILED_REVERIFICATION,
            f"page {span.source_id!r} is not in the corpus",
        )
    if not spans.verify(span, page):
        return Ruling.drop(
            Reason.SPAN_FAILED_REVERIFICATION,
            f"span {span.source_id}[{span.start}:{span.end}] no longer reads "
            f"{span.quote!r} on its page",
        )

    url = next(
        (chunk.url for chunk in retrieved if chunk.source_id == span.source_id), ""
    )
    return Ruling.ship(SpanRef.of(span, url=url))
