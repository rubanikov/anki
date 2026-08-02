# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The coach loop's desktop half.

Four of PRD §4.2's seven steps plus the rule statement: a cold question asked
with no hint, a confidence stated **before** the answer is revealed, an
explanation spoken aloud, and a contrast pair — the same question with exactly
one detail changed. Revision and the personal guide are cut, and the cut is
recorded rather than hidden.

Three files, split by what they need to import:

| | |
| --- | --- |
| ``page.py`` | The HTML and the browser half. No ``aqt`` — so the grep test is cheap. |
| ``client.py`` | The four HTTP calls, none of which can raise. Stdlib only. |
| ``dialog.py`` | The Qt window, the microphone permission, and the bridge. |

The rule this feature exists to enforce is that **no text input element may
exist on a template with a live question on screen**. It is enforced by a test
that reads every file the add-on ships, not by review — see
``../tests/test_no_text_input.py``.
"""

from __future__ import annotations


def register() -> None:
    from . import dialog

    dialog.register()
