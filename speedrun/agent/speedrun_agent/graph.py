# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""retrieve → generate → gate → ship or drop, as a LangGraph graph.

The shape is the argument. Generation sits *between* retrieval and the gate, so
there is no path from a proposal to the wire that does not pass the assertion,
and the assertion is a separate node rather than a clause inside the generator —
a generator cannot be talked into skipping a step it does not own.

State is three keys and one of them is the point. `trail` is the only channel a
node may append to, and its reducer accepts nothing but a `Carried`
(`{output, source_id, span}`), so a node's output and its provenance move
together or not at all. `request` is read-only input. `rejection` holds the one
ruling that ended the attempt, and setting it is how any node says "stop" — the
conditional edges route on its presence, so a drop cannot be forgotten into a
ship.

Both terminal nodes exist for symmetry: `ship` and `drop` are the same size, do
the same amount of work, and write to the same ledger. A dropped attempt is
recorded as carefully as a shipped one because Yield is a ratio, and a pipeline
that only counts its successes cannot report one.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Sequence
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .attribution import Carried, SpanRef, all_from, carry, latest
from .corpus_gateway import Corpus, RetrievedChunk
from .gate import GateRule, Ruling
from .gate import rule as default_rule
from .generators import Candidate, Generator
from .rejections import Attempt, AttemptLog, Reason, SHIPPED
from .tracing import Tracer
from . import topics

RETRIEVE = "retrieve"
GENERATE = "generate"
GATE = "gate"
SHIP = "ship"
DROP = "drop"


@dataclasses.dataclass(frozen=True)
class Request:
    """One generation attempt, reproducible from its own fields.

    `seed` selects which of a topic's candidates is attempted. It exists so the
    retrieval comparison can make its three requests per category and get the
    same three every run — a metric that moves when nothing changed is not a
    metric.
    """

    topic_id: str
    seed: int = 0
    limit: int = 8
    attempt_id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def query(self) -> str:
        return topics.query_for(self.topic_id)


class GateState(TypedDict, total=False):
    request: Request
    trail: Annotated[list[Carried], carry]
    rejection: Ruling | None


def _retrieved(trail: Sequence[Carried]) -> list[RetrievedChunk]:
    """The retrieved chunks, read back out of the attribution trail.

    Retrieval's outputs are not stashed in a side channel; they live in the
    trail with the spans that address them, and every later node reads them from
    there. There is no second copy to drift.
    """
    return [carried.output for carried in all_from(trail, RETRIEVE)]


def build_graph(
    *,
    corpus: Corpus,
    generator: Generator,
    log: AttemptLog,
    tracer: Tracer,
    gate_rule: GateRule | None = None,
) -> Any:
    """Compile the graph. `gate_rule` is injectable so the gate can be sabotaged.

    The boundary test substitutes a rule that returns an unsourced ruling, to
    prove the service still ships nothing — the invariant is enforced at the
    boundary, not by trusting this node.
    """
    rule = gate_rule or default_rule

    def retrieve(state: GateState) -> dict[str, Any]:
        request = state["request"]
        with tracer.run(
            RETRIEVE, "retriever", topic_id=request.topic_id, query=request.query
        ) as span:
            chunks = corpus.retrieve(
                request.query,
                limit=request.limit,
                categories=(request.topic_id,),
            )
            if not chunks:
                ruling = Ruling.drop(
                    Reason.NO_RETRIEVAL,
                    f"no chunks for topic {request.topic_id} "
                    f"with query {request.query!r}",
                )
                span.outputs(chunks=0, reason=str(ruling.reason))
                return {"rejection": ruling}

            # One Carried per chunk: a retrieved passage's "source" is the page
            # it came from and its "span" is its own extent, so retrieval's
            # output is attributable on exactly the same terms as everything
            # downstream. Nothing here is a special case.
            carried = [
                Carried.grounded(
                    RETRIEVE,
                    chunk,
                    SpanRef(
                        source_id=chunk.source_id,
                        chunk_id=chunk.chunk_id,
                        start=chunk.char_start,
                        end=chunk.char_end,
                        quote=chunk.text,
                        url=chunk.url,
                    ),
                )
                for chunk in chunks
            ]
            span.outputs(
                chunks=len(chunks),
                trail=[item.trace_record() for item in carried],
            )
            return {"trail": carried}

    def generate(state: GateState) -> dict[str, Any]:
        request = state["request"]
        chunks = _retrieved(state["trail"])
        with tracer.run(
            GENERATE, "llm", topic_id=request.topic_id, seed=request.seed
        ) as span:
            candidate = generator.propose(
                topic_id=request.topic_id, retrieved=chunks, seed=request.seed
            )
            if candidate is None:
                ruling = Ruling.drop(
                    Reason.GENERATOR_EMPTY,
                    f"{getattr(generator, 'name', 'generator')} proposed nothing "
                    f"for {request.topic_id} seed {request.seed}",
                )
                span.outputs(proposed=False, reason=str(ruling.reason))
                return {"rejection": ruling}
            if not candidate.well_formed:
                ruling = Ruling.drop(
                    Reason.MALFORMED_ITEM,
                    "proposal lacked a stem, an answer, or two distractors",
                )
                span.outputs(proposed=True, reason=str(ruling.reason))
                return {"rejection": ruling}
            if candidate.answer_leaks_into_stem:
                ruling = Ruling.drop(
                    Reason.ANSWER_LEAKS_INTO_STEM,
                    f"stem contains the answer {candidate.answer!r} verbatim",
                )
                span.outputs(proposed=True, reason=str(ruling.reason))
                return {"rejection": ruling}

            # Unsourced on purpose. A generated claim has no citation of its
            # own, and copying the retrieved chunk's id onto it here is exactly
            # how an invented answer would acquire one.
            carried = Carried.unsourced(GENERATE, candidate)
            span.outputs(trail=[carried.trace_record()])
            return {"trail": [carried]}

    def gate(state: GateState) -> dict[str, Any]:
        chunks = _retrieved(state["trail"])
        proposal = latest(state["trail"], GENERATE)
        assert proposal is not None  # only reachable after a successful generate
        candidate: Candidate = proposal.output
        with tracer.run(
            GATE, "tool", answer=candidate.answer, chunks=len(chunks)
        ) as span:
            ruling = rule(chunks, candidate.answer, corpus.page_text)
            if not ruling.ships:
                span.outputs(ships=False, reason=str(ruling.reason), detail=ruling.detail)
                return {"rejection": ruling}
            assert ruling.span is not None
            # The item is the same proposal, now carrying the characters that
            # licensed it. The quote is the source's, never the generator's.
            carried = Carried.grounded(GATE, candidate, ruling.span)
            span.outputs(ships=True, trail=[carried.trace_record()])
            return {"trail": [carried]}

    def ship(state: GateState) -> dict[str, Any]:
        request = state["request"]
        item = latest(state["trail"], GATE)
        with tracer.run(SHIP, "chain", attempt_id=request.attempt_id) as span:
            # Defence in depth. `payload` is the real boundary and it drops an
            # unsourced record on its own; this branch exists so that when it
            # does, the attempt is counted with a reason rather than vanishing.
            if item is None or not item.is_grounded:
                ruling = Ruling.drop(
                    Reason.UNATTRIBUTED_OUTPUT,
                    "an output reached the boundary with no source",
                )
                span.outputs(shipped=False, reason=str(ruling.reason))
                return {"rejection": ruling}
            assert item.span is not None
            log.record(
                Attempt(
                    attempt_id=request.attempt_id,
                    topic_id=request.topic_id,
                    seed=request.seed,
                    generator=getattr(generator, "name", "unknown"),
                    outcome=SHIPPED,
                    source_id=item.source_id,
                    citation=item.span.citation,
                    retrieved=tuple(chunk.chunk_id for chunk in _retrieved(state["trail"])),
                )
            )
            span.outputs(shipped=True, citation=item.span.citation)
            return {}

    def drop(state: GateState) -> dict[str, Any]:
        request = state["request"]
        ruling = state.get("rejection")
        assert ruling is not None and ruling.reason is not None
        with tracer.run(DROP, "chain", attempt_id=request.attempt_id) as span:
            log.record(
                Attempt(
                    attempt_id=request.attempt_id,
                    topic_id=request.topic_id,
                    seed=request.seed,
                    generator=getattr(generator, "name", "unknown"),
                    outcome=str(ruling.reason),
                    detail=ruling.detail,
                    retrieved=tuple(
                        chunk.chunk_id for chunk in _retrieved(state.get("trail", []))
                    ),
                )
            )
            span.outputs(shipped=False, reason=str(ruling.reason), detail=ruling.detail)
            return {}

    def onward(after: str) -> Any:
        def route(state: GateState) -> str:
            return DROP if state.get("rejection") is not None else after

        return route

    builder = StateGraph(GateState)
    builder.add_node(RETRIEVE, retrieve)
    builder.add_node(GENERATE, generate)
    builder.add_node(GATE, gate)
    builder.add_node(SHIP, ship)
    builder.add_node(DROP, drop)

    builder.add_edge(START, RETRIEVE)
    builder.add_conditional_edges(RETRIEVE, onward(GENERATE), [GENERATE, DROP])
    builder.add_conditional_edges(GENERATE, onward(GATE), [GATE, DROP])
    builder.add_conditional_edges(GATE, onward(SHIP), [SHIP, DROP])
    # `ship` can itself refuse — an unsourced record reaching the boundary is a
    # rejection like any other and has to reach the ledger, not fall off the end.
    builder.add_conditional_edges(
        SHIP,
        lambda state: DROP if state.get("rejection") is not None else END,
        [DROP, END],
    )
    builder.add_edge(DROP, END)
    return builder.compile()
