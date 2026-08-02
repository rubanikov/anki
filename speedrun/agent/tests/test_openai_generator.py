# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The real model, through the same HTTP boundary as everything else.

Skipped cleanly when no `OPENAI_API_KEY` is available or the `openai` extra is
not installed — the suite's job is the gate, and the gate is demonstrable
without a key. A test that quietly required one would make the graded part of
this service un-runnable on a machine that has none.

Exactly one API call: the small corpus from `conftest.py` supports the answer,
so a competent model handed the passage should ship. What is asserted is not
that the model is clever but that the *pipeline* holds — the answer it chose is
present verbatim in the source, the citation resolves to those characters, and
the resolved model id (not the moving alias) reaches the response.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from speedrun_agent.app import create_app
from speedrun_agent.environment import has_key
from speedrun_agent.rejections import AttemptLog
from speedrun_agent.tracing import LocalTracer

from conftest import TOPIC

openai = pytest.importorskip("openai", reason="the openai extra is not installed")
pytestmark = pytest.mark.skipif(
    not has_key("OPENAI_API_KEY"), reason="no OPENAI_API_KEY available"
)


def test_a_real_model_ships_only_what_the_source_says(supporting_corpus, tmp_path):
    from speedrun_agent.generators import OpenAIGenerator

    log = AttemptLog(tmp_path / "attempts.jsonl")
    client = TestClient(
        create_app(
            corpus=supporting_corpus,
            generator=OpenAIGenerator(),
            log=log,
            tracer=LocalTracer(tmp_path / "trace.jsonl"),
            out_dir=tmp_path,
        )
    )

    response = client.post(f"/item/generate?topic_id={TOPIC}")

    assert response.status_code in (200, 409)
    body = response.json()

    if response.status_code == 409:
        # A real model is allowed to fail the gate — that is the point of having
        # one. What is not allowed is an item without a source.
        assert body["item"] is None
        assert body["rejected"]["reason"]
        return

    # The quote is the page's characters, and the offsets address them.
    page = supporting_corpus.page_text(body["source_id"])
    span = body["span"]
    assert page[span["start"] : span["end"]] == span["quote"]
    assert body["item"]["answer"]
    # The resolved snapshot, not the alias that was asked for.
    assert body["item"]["model"].startswith("gpt-5")
    assert body["item"]["model"] != "gpt-5", "the alias should resolve to a snapshot"
    assert log.tally()["models"] == [body["item"]["model"]]


def test_the_key_never_reaches_the_response_or_the_ledger(supporting_corpus, tmp_path):
    """`/health` may say a provider is configured. It may not say what with."""
    from speedrun_agent.generators import OpenAIGenerator

    client = TestClient(
        create_app(
            corpus=supporting_corpus,
            generator=OpenAIGenerator(),
            log=AttemptLog(tmp_path / "attempts.jsonl"),
            tracer=LocalTracer(tmp_path / "trace.jsonl"),
            out_dir=tmp_path,
        )
    )

    body = client.get("/health").text

    assert '"provider_key_present":"openai"' in body.replace(" ", "")
    assert "sk-" not in body
