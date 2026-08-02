# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The one shape every node writes, and the only channel it can write to.

Attribution is a structural property here rather than a habit. A node does not
return "its output" and then, separately, remember to log where the output came
from: the only value the graph accepts from a node is a `Carried` — output,
source_id and span in one frozen record — and the reducer rejects anything else
before it reaches the next node. There is no field a developer can forget to
fill in, because there is no other field.

`source_id` and `span` are allowed to be `None`, and that is the point. A
generator's output genuinely has no source; pretending otherwise by copying the
retrieved chunk's id onto it is exactly how an invented answer acquires a
citation. So an ungrounded output is representable, travels through the graph as
one, and is stopped at the boundary by `payload`, which returns `None` for it.

The rule the boundary enforces: an output that reaches the service boundary
without a source is dropped, not displayed.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any


@dataclasses.dataclass(frozen=True)
class SpanRef:
    """A citation, in page coordinates, carrying the source's own characters.

    A copy of `corpus.spans.Span` that does not depend on the corpus package
    being importable, so a trace record or an HTTP response can be re-read
    without it. `quote` is always the source's text, never the caller's.
    """

    source_id: str
    chunk_id: str
    start: int
    end: int
    quote: str
    block_id: str | None = None
    url: str = ""

    @classmethod
    def of(cls, span: Any, url: str = "") -> SpanRef:
        """Build from a `corpus.spans.Span` (duck-typed, not imported)."""
        return cls(
            source_id=span.source_id,
            chunk_id=span.chunk_id,
            start=span.start,
            end=span.end,
            quote=span.quote,
            block_id=getattr(span, "block_id", None),
            url=url,
        )

    @property
    def citation(self) -> str:
        where = f"{self.source_id}[{self.start}:{self.end}]"
        if self.url and self.block_id:
            return f"{where} {self.url}#{self.block_id}"
        if self.url:
            return f"{where} {self.url}"
        return where

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class Carried:
    """One node's output, inseparable from where it came from.

    Constructed only through `grounded` or `unsourced`, so the two states are
    named at the call site. A half-attributed record — a source with no span, or
    a span whose source_id disagrees with the record's — cannot be built.
    """

    node: str
    output: Any
    source_id: str | None
    span: SpanRef | None

    def __post_init__(self) -> None:
        if (self.source_id is None) != (self.span is None):
            raise ValueError(
                f"node {self.node!r}: source_id and span must be present or "
                f"absent together; a source without a span is a claim, not a "
                f"citation"
            )
        if self.span is not None and self.span.source_id != self.source_id:
            raise ValueError(
                f"node {self.node!r}: span cites {self.span.source_id!r} but "
                f"the record claims {self.source_id!r}"
            )

    @classmethod
    def grounded(cls, node: str, output: Any, span: SpanRef) -> Carried:
        return cls(node=node, output=output, source_id=span.source_id, span=span)

    @classmethod
    def unsourced(cls, node: str, output: Any) -> Carried:
        """An output with no source. Legal in the graph, dropped at the boundary."""
        return cls(node=node, output=output, source_id=None, span=None)

    @property
    def is_grounded(self) -> bool:
        return self.span is not None

    def trace_record(self, quote_limit: int = 200) -> dict[str, Any]:
        """The triple, flattened for a trace line. Long quotes are elided."""
        span = None
        if self.span is not None:
            span = self.span.as_dict()
            if len(span["quote"]) > quote_limit:
                span["quote"] = span["quote"][:quote_limit] + "…"
        return {
            "node": self.node,
            "output": _summarize(self.output),
            "source_id": self.source_id,
            "span": span,
        }


def carry(existing: Sequence[Carried] | None, incoming: Any) -> list[Carried]:
    """The trail's reducer: the graph's only writable output channel.

    Every node's return value passes through here, and anything that is not a
    `Carried` is refused. That refusal is what makes attribution structural: a
    node cannot invent a second, unattributed way to hand a value forward,
    because there is no other key in the state it is allowed to append to.
    """
    trail = list(existing or ())
    if isinstance(incoming, Carried):
        incoming = [incoming]
    for item in incoming or ():
        if not isinstance(item, Carried):
            raise TypeError(
                f"a node returned {type(item).__name__} into the attribution "
                f"trail; every node output must be a Carried carrying "
                f"{{output, source_id, span}}"
            )
        trail.append(item)
    return trail


def latest(trail: Sequence[Carried], node: str) -> Carried | None:
    for item in reversed(trail):
        if item.node == node:
            return item
    return None


def all_from(trail: Sequence[Carried], node: str) -> list[Carried]:
    return [item for item in trail if item.node == node]


def payload(carried: Carried | None) -> dict[str, Any] | None:
    """The boundary. Returns None for anything that cannot cite a source.

    This is the last thing between the graph and the wire, and it is a total
    function of the record's own shape — it cannot be persuaded by a flag, a
    header, or a caller in a hurry.
    """
    if carried is None or not carried.is_grounded:
        return None
    assert carried.span is not None  # narrowed by is_grounded
    return {
        "item": _plain(carried.output),
        "source_id": carried.source_id,
        "span": carried.span.as_dict(),
        "citation": carried.span.citation,
    }


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return value


def _summarize(value: Any) -> Any:
    """Trace-sized view of a node output; whole chunks are not trace material."""
    plain = _plain(value)
    if isinstance(plain, str):
        return plain[:200] + "…" if len(plain) > 200 else plain
    if isinstance(plain, dict):
        return {k: _summarize(v) for k, v in plain.items()}
    if isinstance(plain, (list, tuple)):
        return [_summarize(v) for v in plain][:8]
    return plain
