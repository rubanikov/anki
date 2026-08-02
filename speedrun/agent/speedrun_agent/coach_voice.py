# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Turning recorded speech into text — optionally, and never as a precondition.

Speech recognition is the part of the coach loop most likely to be unavailable:
it needs a key, a network and a provider that is up. So it is built as an
*addition* to the loop rather than a step inside it. The add-on records audio
with `MediaRecorder`, sends it here, and proceeds on whatever comes back —
including nothing.

That ordering is not a convenience. The one rule the coach loop exists to
enforce is that no text input exists on a screen with a live question, and the
tempting repair for "transcription is down" is a text box "just for now". A text
box is the failure this feature was built to prevent, so the degraded state is
**audio recorded, not transcribed**: speak-rate still has its numerator, the
loop still runs, and what is lost is a transcript nobody was scoring.

`Transcriber.transcribe` therefore never raises and never blocks the loop. It
returns a record with `transcribed: false` and a reason a human can read.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import io
from typing import Any

from .environment import has_key, key

#: OpenAI's speech-to-text model. Named explicitly rather than aliased for the
#: same reason item generation records a resolved model id: a speak-rate table
#: attributed to a moving alias is not repeatable.
OPENAI_TRANSCRIBE_MODEL = "gpt-4o-transcribe"

#: The container the webview's `MediaRecorder` produces on Chromium.
DEFAULT_EXTENSION = "webm"

#: The provider infers the container from the **filename**, not from the bytes,
#: so a name that disagrees with the payload is rejected as a corrupt file. That
#: is not hypothetical: the first end-to-end transcription run sent WAV bytes
#: under a `.webm` name and came back "Audio file might be corrupted". The
#: recorder's own MIME type decides the extension.
EXTENSIONS: dict[str, str] = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/flac": "flac",
}


def filename_for(mime: str) -> str:
    """A filename whose extension matches the bytes. Falls back to the recorder's."""
    base = (mime or "").split(";")[0].strip().lower()
    return f"utterance.{EXTENSIONS.get(base, DEFAULT_EXTENSION)}"

#: Bigger than any single spoken answer and small enough that a runaway
#: recorder cannot post a hundred megabytes into this process.
MAX_AUDIO_BYTES = 8 * 1024 * 1024


@dataclasses.dataclass(frozen=True)
class Transcription:
    """What came back, including when nothing did."""

    transcribed: bool
    transcript: str | None
    audio_bytes: int
    model: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class NullTranscriber:
    """The honest default: it records that audio arrived and transcribes none.

    This is what runs with no key, and it is a working configuration rather than
    a broken one — the loop's steps, the ordering rule and speak-rate are all
    unaffected. Naming it, instead of returning `None` from a factory, keeps the
    absence visible in `/health`.
    """

    name = "none"
    model = ""

    def transcribe(self, audio: bytes, *, mime: str = "") -> Transcription:
        return Transcription(
            transcribed=False,
            transcript=None,
            audio_bytes=len(audio),
            reason="no speech-to-text provider is configured",
        )


class OpenAITranscriber:
    """Speech to text with OpenAI, when a key exists.

    Nothing downstream depends on the result: no step is gated on a transcript,
    and no score reads one. It is teaching material and a record of what was
    said, which is why a failure here is downgraded to `transcribed: false`
    rather than propagated.
    """

    name = "openai"

    def __init__(self, model: str = OPENAI_TRANSCRIBE_MODEL) -> None:
        from openai import OpenAI  # noqa: PLC0415  (extra; absent without a key)

        self._client = OpenAI(api_key=key("OPENAI_API_KEY"))
        self.model = model

    def transcribe(self, audio: bytes, *, mime: str = "") -> Transcription:
        stream = io.BytesIO(audio)
        stream.name = filename_for(mime)
        try:
            result = self._client.audio.transcriptions.create(
                model=self.model, file=stream
            )
        except Exception as exc:  # noqa: BLE001 — a provider outage is not a crash
            return Transcription(
                transcribed=False,
                transcript=None,
                audio_bytes=len(audio),
                model=self.model,
                reason=f"{type(exc).__name__}: {exc}",
            )
        text = (getattr(result, "text", "") or "").strip()
        return Transcription(
            transcribed=bool(text),
            transcript=text or None,
            audio_bytes=len(audio),
            model=self.model,
            reason="" if text else "the provider returned no text",
        )


def default_transcriber() -> Any:
    """OpenAI when its key is there, the null one otherwise. Never raises."""
    if has_key("OPENAI_API_KEY"):
        try:
            return OpenAITranscriber()
        except Exception:  # noqa: BLE001 — a missing extra is not a reason to be down
            pass
    return NullTranscriber()


def decode(encoded: str) -> tuple[bytes, str]:
    """Base64 in, bytes out, with the two refusals stated rather than raised.

    The audio arrives base64-encoded because it crosses a JavaScript-to-Python
    bridge that carries strings. Oversized and malformed payloads are the two
    things a webview can send by accident, and both return a reason instead of a
    traceback.
    """
    try:
        audio = base64.b64decode(encoded or "", validate=True)
    except (binascii.Error, ValueError):
        return b"", "the audio was not valid base64"
    if not audio:
        return b"", "no audio was recorded"
    if len(audio) > MAX_AUDIO_BYTES:
        return b"", f"the recording exceeded {MAX_AUDIO_BYTES} bytes"
    return audio, ""
