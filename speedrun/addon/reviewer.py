# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Withholding the Topic label while a question is on screen.

``card_will_show`` is the one hook that sees the rendered HTML for both sides of
a card, in the reviewer, the previewer and the card-layout screen alike. Hooking
it once covers all three; monkeypatching ``Reviewer._showQuestion`` would cover
one of them and would break the next time upstream touched it.

The rule: on any question side, every Topic tag is redacted out of the HTML and
the add-on's own label is hidden. On the answer side the label is added back. A
Topic names the AAMC content category — "this is 5C" is most of the work on a
thermodynamics item — so the question has to stand on its own first.

Nothing in here may throw. A measurement add-on that can break someone's review
session has cost them more than it measures, so every failure returns the card
text untouched.
"""

from __future__ import annotations

from typing import Any

from aqt import gui_hooks

from . import config, topics


def _on_card_will_show(text: str, card: Any, kind: str) -> str:
    try:
        conf = config.get()
        if not conf.get("hide_topic_label_during_question", True):
            return text
        prefix = conf["tag_prefix"]
        tags = list(card.note().tags)

        # kind is one of reviewQuestion / reviewAnswer / previewQuestion /
        # previewAnswer / clayoutQuestion / clayoutAnswer.
        if kind.endswith("Question"):
            return topics.hide_topic_in_question(text, tags, prefix)
        if kind.endswith("Answer"):
            return topics.reveal_topic_in_answer(text, tags, prefix)
        return text
    except Exception:
        return text


def register() -> None:
    gui_hooks.card_will_show.append(_on_card_will_show)
