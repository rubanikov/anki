# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The HTTP boundary — the only place the graph's output becomes visible.

Every route funnels through `attribution.payload`, which returns `None` for a
record that cannot cite a source. That is the whole enforcement: not a check
somewhere in the graph that a future node might route around, but the single
function that turns a `Carried` into JSON, refusing when there is no span. An
output without a source cannot cross this line, because there is no other line.

This is also the seam the tests use. SPEC §Seam 2 is explicit that the gate is
tested here and never node by node: node-level tests would pin the graph's
current shape — three nodes, these names, this order — while proving nothing
about the only place the rule matters. So `create_app` takes its corpus,
generator and gate rule as arguments, and a test swaps the corpus for one that
does not contain the answer and asserts against the response.

**Nothing in the desktop app imports anything from this package.** The add-on
reaches this service over HTTP with a timeout and treats any failure — refused,
timed out, garbage — as `ai_enabled = false`. Memory, coverage and the dashboard
come from the Rust engine, which never consults this service at all. Killing
this process removes generation and the coach loop and nothing else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from . import topics
from .attribution import latest, payload
from .corpus_gateway import Bm25Corpus, Corpus
from .gate import GateRule
from .generators import Generator, available_provider, default_generator
from .graph import GATE, Request, build_graph
from .rejections import AttemptLog
from .tracing import Tracer, default_tracer, langsmith_key

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "out"


def create_app(
    *,
    corpus: Corpus | None = None,
    generator: Generator | None = None,
    log: AttemptLog | None = None,
    tracer: Tracer | None = None,
    gate_rule: GateRule | None = None,
    out_dir: Path | str | None = None,
) -> FastAPI:
    """Build the service. Every collaborator is an argument with a real default.

    The defaults are what `uv run speedrun-agent` gets; the arguments are what
    the boundary tests use. There is no test-only code path — the tests drive
    the same `create_app` the process does, over the same HTTP.
    """
    out = Path(out_dir) if out_dir else DEFAULT_OUT
    corpus = corpus or Bm25Corpus.open()
    generator = generator or default_generator()
    log = log or AttemptLog(out / "attempts.jsonl")
    tracer = tracer or default_tracer(out / "trace.jsonl")
    graph = build_graph(
        corpus=corpus,
        generator=generator,
        log=log,
        tracer=tracer,
        gate_rule=gate_rule,
    )

    app = FastAPI(
        title="Speedrun agent",
        version="0.1.0",
        summary="Grounded item generation behind a span-level gate.",
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        """What the add-on probes. Cheap, and it never opens a model connection.

        `switches.probe` treats anything but a 2xx/3xx as unreachable, and an
        unreachable service *is* `ai_enabled = false` — so this endpoint's only
        job is to answer, and its body is for humans.

        Keys appear here only as booleans and provider names. No endpoint of
        this service can emit a key, because no code path holds one after the
        SDK client is constructed.
        """
        return {
            "status": "ok",
            "corpus": corpus.stats(),
            "generator": getattr(generator, "name", "unknown"),
            "model": getattr(generator, "model", ""),
            "provider_key_present": available_provider(),
            "tracing": getattr(tracer, "name", "unknown"),
            "langsmith_key_present": langsmith_key() is not None,
        }

    @app.post("/item/generate")
    def generate_item(
        topic_id: str = Query(..., description="An Outline Topic, e.g. 1D"),
        seed: int = Query(0, ge=0, description="Which candidate; fixed per ADR-0006"),
        limit: int = Query(8, ge=1, le=32, description="Chunks retrieved"),
    ) -> JSONResponse:
        """One attempt. 200 with a citation, or 409 with a reason and no item.

        409 rather than 200-with-nothing because a dropped item is not a
        successful empty result — it is the request failing to produce something
        showable, and a caller that ignores status codes should still not be
        able to render an ungrounded item, since `item` is null either way.
        """
        if not topics.known(topic_id):
            return JSONResponse(
                status_code=404,
                content={
                    "item": None,
                    "error": f"{topic_id!r} is not an Outline Topic",
                    "topics": topics.ids(),
                },
            )

        request = Request(topic_id=topic_id, seed=seed, limit=limit)
        with tracer.run(
            "item.generate",
            "chain",
            topic_id=topic_id,
            seed=seed,
            attempt_id=request.attempt_id,
        ) as span:
            state = graph.invoke({"request": request, "trail": []})
            shipped = payload(latest(state.get("trail", []), GATE))
            if shipped is None:
                ruling = state.get("rejection")
                reason = str(ruling.reason) if ruling else "unattributed_output"
                detail = ruling.detail if ruling else "no ruling was recorded"
                span.outputs(shipped=False, reason=reason)
                return JSONResponse(
                    status_code=409,
                    content={
                        "item": None,
                        "attempt_id": request.attempt_id,
                        "topic_id": topic_id,
                        "seed": seed,
                        "rejected": {"reason": reason, "detail": detail},
                    },
                )
            span.outputs(shipped=True, citation=shipped["citation"])
            return JSONResponse(
                status_code=200,
                content={
                    **shipped,
                    "attempt_id": request.attempt_id,
                    "topic_id": topic_id,
                    "seed": seed,
                },
            )

    @app.get("/gate/yield")
    def gate_yield() -> dict[str, Any]:
        """Yield and its decomposition — the numbers ADR-0006 and #16 read."""
        return log.tally()

    @app.get("/gate/rejections")
    def gate_rejections(limit: int = Query(50, ge=1, le=1000)) -> dict[str, Any]:
        """The dropped attempts themselves, each with the reason that stopped it."""
        return {"rejections": log.rejections(limit=limit)}

    return app
