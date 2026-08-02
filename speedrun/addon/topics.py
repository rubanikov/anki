# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Topic labels on the review screen, and the rule that hides them.

A Topic label names the AAMC content category a card belongs to. Seeing it
while the question is up gives away the approach — "this is 5C" is most of the
work on a thermodynamics item — so the label is withheld until the answer is
showing.

Nothing here computes a score. The only judgement in this file is *which tags
name a Topic*, and it deliberately applies the same shape the backend does
(``<prefix>::<section>::<rest>``, all three parts non-empty) so that the label
we hide is the same string the backend attributes a card by. If those two ever
disagree, the tag hidden here is not the tag measured there, and the reviewer
would be leaking a Topic the dashboard reports on.

This module imports nothing from ``aqt`` or ``anki`` on purpose: it is the part
of the add-on with behaviour worth testing, and it should be testable without a
Qt event loop or an open collection.
"""

from __future__ import annotations

import html

#: What a redacted Topic tag is replaced with in question HTML.
TOPIC_MASK = "•••"

#: Injected on the question side. Belt to the redaction's braces: it also hides
#: a label an earlier answer render left in a persistent part of the page.
HIDE_STYLE = (
    '<style class="speedrun-hide-topic">'
    ".speedrun-topic,[data-speedrun-topic]{display:none !important;}"
    "</style>"
)


def topic_from_tag(tag: str, prefix: str) -> str | None:
    """The tag itself if it names a Topic under ``prefix``, else None.

    ``mcat::BB::amino_acids`` is a Topic. ``mcat::BB`` names a section with no
    Topic under it and is not one; neither is a tag in another namespace.
    """
    root = f"{prefix}::"
    if not tag.startswith(root):
        return None
    section, sep, remainder = tag[len(root) :].partition("::")
    if not sep or not section or not remainder:
        return None
    return tag


def topic_tags(tags: list[str], prefix: str) -> list[str]:
    """Every Topic tag on a note, longest first.

    Longest first matters for redaction: replacing ``mcat::BB::acid`` before
    ``mcat::BB::acid_base`` would leave the tail of the longer tag on screen.
    """
    found = [t for t in tags if topic_from_tag(t, prefix) is not None]
    return sorted(found, key=len, reverse=True)


def topic_label(tags: list[str], prefix: str) -> str | None:
    """The Topic a card is attributed to, if any.

    The first one, matching the backend's rule that a note carrying several
    Topic tags is counted once rather than repeatedly.
    """
    for tag in tags:
        if topic_from_tag(tag, prefix) is not None:
            return tag
    return None


def hide_topic_in_question(text: str, tags: list[str], prefix: str) -> str:
    """Strip every Topic tag out of question HTML.

    Redaction is textual because the leak is textual: a template rendering
    ``{{Tags}}`` prints ``mcat::BB::amino_acids`` straight onto the question,
    and no CSS selector reaches that. Anything the add-on itself rendered is
    caught by the style block instead.
    """
    for tag in topic_tags(tags, prefix):
        text = text.replace(tag, TOPIC_MASK)
    return HIDE_STYLE + text


def reveal_topic_in_answer(text: str, tags: list[str], prefix: str) -> str:
    """Append the Topic label, now that the question has been answered."""
    topic = topic_label(tags, prefix)
    if topic is None:
        return text
    return (
        text
        + '<div class="speedrun-topic" data-speedrun-topic="1"'
        + ' style="margin-top:1em;font-size:80%;opacity:0.7;">'
        + f"Topic: {html.escape(topic)}</div>"
    )
