# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The falsifier for SpikyPOV 2: no text input on a screen with a live question.

The claim is that voice is the *mechanism* rather than the interface — that a
student cannot copy an answer into Speedrun because there is nowhere to put one.
A claim like that decays the first time somebody adds a text box "just for
debugging", so it is asserted by reading every file the add-on ships and
failing on the element itself.

Three details make this a real check rather than a gesture:

**It scans the whole add-on, not the coach.** The rule is about any template
with a live question, and the reviewer, the dashboard and anything added later
are all templates. Scoping the scan to `coach/` would let the next screen be the
exception.

**It scans this file too.** The needles are built at runtime from fragments, so
the test's own source contains none of them and is not exempted from its own
rule. An exemption list is where a check like this goes to die.

**It refuses to pass vacuously.** A page with no controls has no text inputs
either, so the last tests assert that the coach page really does present
choices, a microphone, and the confidence levels — the things that exist
*because* there is no text box.
"""

from __future__ import annotations

from pathlib import Path

import coach.page as coach_page
import pytest

ADDON_DIR = Path(__file__).resolve().parents[1]

#: The file kinds that can reach a webview. `.md` is add-on documentation shown
#: in Anki's own config dialog and never carries a question.
SCANNED_SUFFIXES = (".py", ".html", ".js", ".css", ".json")

SCANNED = sorted(
    path
    for path in ADDON_DIR.rglob("*")
    if path.suffix in SCANNED_SUFFIXES and "__pycache__" not in path.parts
)

#: Assembled rather than written, so this file contains no literal that its own
#: scan would trip over. Every way a browser accepts typed text.
BANNED: tuple[str, ...] = (
    "<" + "input",
    "<" + "textarea",
    "content" + "editable",
    "design" + "Mode",
    "createElement('" + "input')",
    'createElement("' + 'input")',
    "createElement('" + "textarea')",
    'createElement("' + 'textarea")',
)


def test_there_are_files_to_scan():
    """Guard: an empty glob would make every assertion below vacuous."""
    assert len(SCANNED) >= 8, f"only {len(SCANNED)} files found under {ADDON_DIR}"
    assert any(path.name == "page.py" for path in SCANNED)
    assert Path(__file__) in SCANNED  # this file is not exempt from its own rule


@pytest.mark.parametrize("source", SCANNED, ids=lambda p: p.name)
def test_no_template_can_accept_typed_text(source: Path):
    """The rule, as a grep. Adding a text box to any Speedrun screen fails here.

    Voice is not a convenience in this product — it is why an answer cannot be
    pasted in from a browser tab. A text box next to a live question makes every
    Performance number downstream a measurement of somebody's clipboard.
    """
    text = source.read_text(encoding="utf-8")
    lowered = text.lower()
    for needle in BANNED:
        assert needle.lower() not in lowered, (
            f"{source.relative_to(ADDON_DIR)} contains {needle!r}. No text input "
            f"may exist on a Speedrun template: voice is the mechanism that "
            f"stops an answer being copied in, not a stylistic preference."
        )


def test_the_coach_page_captures_voice_instead():
    """What replaces the text box, so the rule is met by building, not omitting."""
    markup = coach_page.page()

    assert "MediaRecorder" in markup
    assert "getUserMedia" in markup
    assert "coach:transcribe:" in markup


def test_the_coach_page_answers_and_rates_confidence_with_buttons():
    """The loop's two graded interactions exist, and both are buttons."""
    markup = coach_page.page()

    assert markup.count("<button") >= 3
    for level in ("'low'", "'medium'", "'high'"):
        assert level in markup
    assert "coach-choices" in markup


def test_the_page_tells_the_student_why_there_is_no_text_box():
    """A constraint the student cannot see reads as a missing feature."""
    assert "There is no text box" in coach_page.VOICE_NOTICE
    assert coach_page.VOICE_NOTICE in coach_page.page()


def test_service_text_reaches_the_dom_as_text_and_not_as_markup():
    """Stems come from a model; interpolating one as HTML is an injection.

    `textContent` everywhere, and no `innerHTML` anywhere — checked because the
    two are one keystroke apart and the difference is a script running inside
    the reviewer's webview.
    """
    markup = coach_page.page()

    assert "innerHTML" not in markup
    assert "textContent" in markup
