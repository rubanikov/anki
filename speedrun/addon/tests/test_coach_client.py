# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The coach's one reach outward, and its behaviour when nothing is listening.

The non-negotiable is that with the service dead the app still starts, still
scores Memory and still shows coverage. The structural half of that is asserted
in the service's own suite, which reads this directory and fails if anything
here names the service or its dependency tree. This file asserts the other half
by running the calls: against a closed port, against something that is not a
service, and against a refusal — and requiring a readable sentence out of each
rather than an exception.

No Qt, no collection, no network beyond a refused connection to a port nothing
is on.
"""

from __future__ import annotations

import socket

import coach.client as client


def _closed_port() -> int:
    """A port nothing is listening on. Bound and released, so it is really free."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_the_probe_url_becomes_the_service_root():
    """One address in the config, not two to keep in step."""
    assert client.base_url("http://127.0.0.1:8000/health") == "http://127.0.0.1:8000"
    assert client.base_url("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
    assert client.base_url("") == ""


def test_no_configured_service_is_a_sentence_and_not_an_error():
    """The state a fresh install is in. It must not look like a crash."""
    reply = client.start("", "1D", 0)

    assert reply.ok is False
    assert "did not answer" in reply.reason
    assert reply.data == {}


def test_a_dead_service_returns_a_reply_rather_than_raising():
    """Every call, against a closed port. None may raise; all must explain.

    This is the degraded path the whole feature is required to survive. It is
    exercised here rather than described, because the same code runs when a
    student closes the service mid-session.
    """
    base = f"http://127.0.0.1:{_closed_port()}"

    replies = [
        client.start(base, "1D", 0),
        client.turn(base, {"session_id": "x"}),
        client.transcribe(base, "AAEC"),
        client.speak_rate(base),
    ]

    for reply in replies:
        assert reply.ok is False
        assert reply.status == 0
        assert reply.reason
        assert "Memory, coverage" in reply.reason


def test_a_gate_rejection_is_reported_as_a_rejection_not_an_outage():
    """A dropped item and a dead service are different sentences.

    They are the same *state* for the off switches — no coach either way — but
    a student told "the service is down" when the truth is "no real source
    supports a question here" has been told the wrong thing about their corpus.
    """
    reply = client.Reply(
        ok=False,
        status=409,
        data={"item": None, "rejected": {"reason": "answer_not_in_retrieved_text"}},
    )

    assert "grounded in a real source" in reply.reason
    assert "answer_not_in_retrieved_text" in reply.reason


def test_a_refused_turn_carries_the_services_own_message():
    """The step order lives in the service; the add-on repeats what it says."""
    reply = client.Reply(
        ok=False,
        status=409,
        data={"error": "step confidence needs one of low, medium, high"},
    )

    assert reply.reason == "step confidence needs one of low, medium, high"
