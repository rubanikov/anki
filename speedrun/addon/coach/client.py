# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The add-on's only reach toward the coach service, and it cannot raise.

Four calls over ``urllib``, each with a timeout and a blanket ``except``. That
shape is not defensive habit — it is the third off switch stated as code. The
service dying, hanging, or answering with something that is not JSON must all
produce the same thing: a ``Reply`` that is not ``ok``, carrying a sentence a
student can read. Memory, coverage, the dashboard and the review queue come from
the Rust engine and never touch this module, so nothing here can withhold a
measurement no matter how it fails.

Nothing in this file imports the service or anything in its dependency tree; it
speaks HTTP to a URL from the add-on config and knows nothing else about what is
on the other end. ``tests/test_degradation.py`` in the service's own suite reads
this directory and fails if that stops being true.

Stdlib only, and no ``aqt`` import, so it can be exercised against a local HTTP
server in a test without a Qt event loop.
"""

from __future__ import annotations

import dataclasses
import json
import urllib.error
import urllib.request
from typing import Any

#: Long enough for a model round trip behind ``/coach/start``, short enough that
#: a hung service is a message on screen rather than a frozen window. The call
#: is made off the UI thread regardless.
TIMEOUT_SECS = 45.0

#: Transcription is the one call the loop does not wait on, so it gets less
#: patience: a slow transcript is worth abandoning, a slow question is not.
TRANSCRIBE_TIMEOUT_SECS = 25.0

UNREACHABLE = (
    "The coach service did not answer. Reviews, Memory, coverage and the "
    "dashboard are unaffected — they are computed by the engine, which does not "
    "use this service."
)


@dataclasses.dataclass(frozen=True)
class Reply:
    """What came back, including when nothing did.

    ``ok`` is false for every failure mode there is, and ``data`` is still a
    dict, so a caller cannot get an ``AttributeError`` out of an outage.
    """

    ok: bool
    status: int
    data: dict[str, Any]
    error: str = ""

    @property
    def reason(self) -> str:
        """One sentence for the screen. Never blank, never a traceback."""
        if self.ok:
            return ""
        if self.error:
            return self.error
        rejected = self.data.get("rejected")
        if isinstance(rejected, dict) and rejected.get("reason"):
            return (
                f"No question could be grounded in a real source "
                f"({rejected['reason']}). Nothing ungrounded is shown."
            )
        return str(self.data.get("error") or UNREACHABLE)


def base_url(configured: str) -> str:
    """Turn the probe URL in the config into the service root.

    The config names ``/health`` because that is what the off switch probes.
    Deriving the root here rather than adding a second setting keeps one address
    in one place; a second one is a second thing to get out of step.
    """
    url = (configured or "").strip().rstrip("/")
    if url.endswith("/health"):
        url = url[: -len("/health")]
    return url


def _call(
    url: str, payload: dict[str, Any] | None, timeout: float
) -> Reply:
    """One request. Every failure becomes a ``Reply``; nothing escapes.

    The scheme check comes first because a blank or malformed ``agent_url`` in
    the config produces a path with no scheme, and ``urllib`` raises on that
    before any socket is opened — which would be the one failure mode that
    escaped this function. No service configured is the state a fresh install
    is in, and it must read as "off", not as a traceback.
    """
    if not url.startswith(("http://", "https://")):
        return Reply(ok=False, status=0, data={}, error=UNREACHABLE)
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - a configured http(s) URL
        url,
        data=body,
        method="POST" if payload is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return Reply(
                ok=True,
                status=int(response.status),
                data=json.loads(response.read().decode("utf-8")),
            )
    except urllib.error.HTTPError as failure:
        # A 409 is the service refusing on purpose — an item the Generation gate
        # dropped, or a turn out of order — so its body is the useful part and
        # is handed back rather than discarded as an error.
        try:
            data = json.loads(failure.read().decode("utf-8"))
        except Exception:
            data = {}
        return Reply(ok=False, status=int(failure.code), data=data)
    except Exception:
        return Reply(ok=False, status=0, data={}, error=UNREACHABLE)


def start(base: str, topic_id: str, seed: int) -> Reply:
    """Open a loop over one held-out item. 409 when the gate dropped it."""
    return _call(
        f"{base}/coach/start?topic_id={topic_id}&seed={int(seed)}", {}, TIMEOUT_SECS
    )


def turn(base: str, fields: dict[str, Any]) -> Reply:
    """Advance one step. The service decides whether the step is legal."""
    return _call(f"{base}/coach/turn", fields, TIMEOUT_SECS)


def transcribe(base: str, audio_base64: str, mime: str = "audio/webm") -> Reply:
    """Speech to text, when the service has a provider for it.

    Never blocks a step. A failure here shows nothing and costs nothing: the
    recording still counted toward speak-rate, and the loop does not stop for a
    transcript nobody scores.
    """
    return _call(
        f"{base}/coach/transcribe",
        {"audio_base64": audio_base64, "mime": mime},
        TRANSCRIBE_TIMEOUT_SECS,
    )


def speak_rate(base: str) -> Reply:
    """The share of prompts spoken into, as the service has recorded it."""
    return _call(f"{base}/coach/speak-rate", None, TIMEOUT_SECS)
