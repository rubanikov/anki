# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The gate, tested where it matters: the response a caller actually receives.

Every assertion here is against an HTTP status code and a JSON body. Nothing
imports a node, calls one, or knows how many there are. That is not squeamish-
ness about internals — it is that a node-level test freezes the graph's current
shape while proving nothing about the boundary, and the boundary is the only
place an ungrounded item could ever reach a student.

The test that carries the ticket is `test_ungrounded_claim_ships_no_item`: hold
the generator constant, swap the corpus for one that does not contain the
answer, and the response must contain no item and record a rejection with a
reason. Its twin, `test_grounded_claim_ships_with_a_citation`, exists so the
first cannot pass by the service being broken.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from speedrun_agent.app import create_app
from speedrun_agent.attribution import Carried
from speedrun_agent.gate import Ruling
from speedrun_agent.rejections import AttemptLog, Reason
from speedrun_agent.tracing import LocalTracer

from conftest import ANSWER, TOPIC


def _client(corpus, generator, tmp_path, gate_rule=None) -> TestClient:
    app = create_app(
        corpus=corpus,
        generator=generator,
        log=AttemptLog(tmp_path / "attempts.jsonl"),
        tracer=LocalTracer(tmp_path / "trace.jsonl"),
        gate_rule=gate_rule,
        out_dir=tmp_path,
    )
    return TestClient(app)


def test_grounded_claim_ships_with_a_citation(
    supporting_corpus, claiming_generator, tmp_path
):
    """The control. Support exists, so an item crosses the boundary — with a span."""
    client = _client(supporting_corpus, claiming_generator, tmp_path)

    response = client.post(f"/item/generate?topic_id={TOPIC}")

    assert response.status_code == 200
    body = response.json()
    assert body["item"]["answer"] == ANSWER
    assert body["source_id"]
    # The quote is the source's own characters, not the generator's string.
    assert body["span"]["quote"] in _page(supporting_corpus, body["source_id"])
    assert body["citation"].startswith(body["source_id"])


def test_ungrounded_claim_ships_no_item(silent_corpus, claiming_generator, tmp_path):
    """The ticket's acceptance criterion, asserted at the seam it names.

    Same generator, same claim, same topic. The corpus no longer says it, so
    there is no item in the response at all — not a hedged one, not a "low
    confidence" one — and the attempt is on the record with the reason.
    """
    client = _client(silent_corpus, claiming_generator, tmp_path)

    response = client.post(f"/item/generate?topic_id={TOPIC}")

    assert response.status_code == 409
    body = response.json()
    assert body["item"] is None
    assert body["rejected"]["reason"] == Reason.ANSWER_NOT_IN_RETRIEVED_TEXT
    assert ANSWER in body["rejected"]["detail"]

    rejections = client.get("/gate/rejections").json()["rejections"]
    assert [r["outcome"] for r in rejections] == [Reason.ANSWER_NOT_IN_RETRIEVED_TEXT]
    assert rejections[0]["attempt_id"] == body["attempt_id"]
    # Retrieval worked; the gate is what stopped it. Without this the test would
    # also pass on a service that simply failed to retrieve anything.
    assert rejections[0]["retrieved"]


def test_unsourced_output_never_crosses_the_boundary(
    supporting_corpus, claiming_generator, tmp_path
):
    """Sabotage the gate into approving an unsourced item; ship nothing anyway.

    The corpus here *does* support the claim, so the only reason this attempt
    fails is that the record reaching the boundary carries no span. This is the
    invariant stated as a test rather than as a comment: attribution is what
    licenses display, and a broken gate cannot grant it.
    """

    def approves_without_a_source(retrieved, answer, page_text):
        return Ruling.drop(Reason.UNATTRIBUTED_OUTPUT, "sabotaged gate")

    client = _client(
        supporting_corpus,
        claiming_generator,
        tmp_path,
        gate_rule=approves_without_a_source,
    )

    response = client.post(f"/item/generate?topic_id={TOPIC}")

    assert response.status_code == 409
    assert response.json()["item"] is None


def test_carried_cannot_be_half_attributed():
    """The type refuses the shape that would make the boundary check bypassable.

    A record with a source but no span would satisfy a naive "does it have a
    source_id?" check while carrying nothing anyone could re-verify. It is not
    constructible, so no boundary check has to defend against it.
    """
    import pytest

    with pytest.raises(ValueError, match="present or absent together"):
        Carried(node="gate", output="x", source_id="page-1", span=None)


def test_yield_counts_both_outcomes(
    supporting_corpus, silent_corpus, claiming_generator, tmp_path
):
    """Yield is a ratio, so the denominator has to include the drops."""
    log = AttemptLog(tmp_path / "attempts.jsonl")
    tracer = LocalTracer(tmp_path / "trace.jsonl")

    shipping = TestClient(
        create_app(
            corpus=supporting_corpus,
            generator=claiming_generator,
            log=log,
            tracer=tracer,
            out_dir=tmp_path,
        )
    )
    dropping = TestClient(
        create_app(
            corpus=silent_corpus,
            generator=claiming_generator,
            log=log,
            tracer=tracer,
            out_dir=tmp_path,
        )
    )

    shipping.post(f"/item/generate?topic_id={TOPIC}")
    for _ in range(3):
        dropping.post(f"/item/generate?topic_id={TOPIC}")

    tally = shipping.get("/gate/yield").json()
    assert tally["attempts"] == 4
    assert tally["shipped"] == 1
    assert tally["yield_per_hundred"] == 25.0
    assert tally["by_reason"][Reason.ANSWER_NOT_IN_RETRIEVED_TEXT] == 3


def test_yield_abstains_before_any_attempt(
    supporting_corpus, claiming_generator, tmp_path
):
    """No attempts means no rate. A rate over an empty denominator is a fiction."""
    client = _client(supporting_corpus, claiming_generator, tmp_path)

    tally = client.get("/gate/yield").json()

    assert tally["attempts"] == 0
    assert tally["yield_per_hundred"] is None


def test_unknown_topic_is_refused_rather_than_guessed(
    supporting_corpus, claiming_generator, tmp_path
):
    client = _client(supporting_corpus, claiming_generator, tmp_path)

    response = client.post("/item/generate?topic_id=99Z")

    assert response.status_code == 404
    assert response.json()["item"] is None


def test_health_reports_what_is_actually_wired(
    supporting_corpus, claiming_generator, tmp_path
):
    """The probe the add-on makes. It must answer without a model or a key."""
    client = _client(supporting_corpus, claiming_generator, tmp_path)

    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["corpus"]["retriever"] == "bm25-fts5"
    assert body["generator"] == "fixed-claim"
    assert body["tracing"] == "local-jsonl"


def test_trace_carries_the_triple_for_every_node(
    supporting_corpus, claiming_generator, tmp_path
):
    """A trace that cannot be re-checked is a log, not evidence.

    Asserted on the file rather than the tracer object: the record shape is the
    contract with whatever reads traces later, LangSmith included.
    """
    import json

    client = _client(supporting_corpus, claiming_generator, tmp_path)
    client.post(f"/item/generate?topic_id={TOPIC}")

    runs = [
        json.loads(line)
        for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    by_name = {run["name"]: run for run in runs}
    assert {"retrieve", "generate", "gate", "ship", "item.generate"} <= set(by_name)
    for run in runs:
        assert set(run) >= {
            "id",
            "trace_id",
            "parent_run_id",
            "name",
            "run_type",
            "start_time",
            "end_time",
            "inputs",
            "outputs",
            "error",
        }
    # Every node's trail entry carries the triple, generate's included — its
    # source and span are null, which is the record the boundary acts on.
    for name in ("retrieve", "generate", "gate"):
        for entry in by_name[name]["outputs"]["trail"]:
            assert set(entry) == {"node", "output", "source_id", "span"}
    assert by_name["generate"]["outputs"]["trail"][0]["source_id"] is None
    assert by_name["gate"]["outputs"]["trail"][0]["source_id"] is not None


def _page(corpus, source_id: str) -> str:
    return corpus.page_text(source_id)
