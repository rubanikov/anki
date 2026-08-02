# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The only place the add-on talks to ``SpeedrunService``.

Both calls are pure reads: they add no undo entry and mutate nothing, which is
what lets the dashboard be opened during a review without disturbing the
scheduler or the undo stack.

Keeping the calls in one file is the seam that makes "the add-on computes
nothing" checkable rather than asserted — everything above this module receives
protobuf messages it can only format.
"""

from __future__ import annotations

from typing import Any


def collection_mastery(col: Any, tag_prefix: str) -> Any:
    """Topic mastery across every section. Carries the collection-wide
    denominators: cards considered, cards excluded, cards unmapped."""
    return col._backend.topic_mastery(section="", tag_prefix=tag_prefix)


def section_mastery(col: Any, section: str, tag_prefix: str) -> Any:
    """Topic mastery within one section, read straight from the backend.

    Kept for callers that want one section and nothing else. The dashboard does
    not use it: it needs every section anyway, and asking per section made the
    engine scan the whole collection once more for each one. See
    :func:`section_view`.
    """
    return col._backend.topic_mastery(section=section, tag_prefix=tag_prefix)


class SectionView:
    """One section's slice of a collection-wide ``TopicMasteryResponse``.

    Exposes the two fields the page reads off a section's mastery — its topics
    and the number of cards mapped into it — without a second backend call.
    """

    __slots__ = ("topics", "cards_considered")

    def __init__(self, topics: list[Any]) -> None:
        self.topics = topics
        self.cards_considered = sum(t.card_count for t in topics)


def section_view(mastery: Any, section: str) -> SectionView:
    """Narrow a collection-wide mastery response to one section.

    Every topic already carries the section it belongs to, so the collection-wide
    read contains every per-section read as a subset. Asking the backend again
    per section made each of the four sections rescan the whole collection — on a
    50k-card deck that was measured as roughly half the dashboard's total cost,
    and it is redundant at any build profile.
    """
    wanted = section.upper()
    return SectionView(
        [t for t in mastery.topics if (t.section or "").upper() == wanted]
    )


def section_scores(
    col: Any, section: str, tag_prefix: str, outline_topic_count: int
) -> Any:
    """The three scores for one section, with their ranges and abstentions."""
    return col._backend.section_scores(
        section=section,
        tag_prefix=tag_prefix,
        outline_topic_count=outline_topic_count,
    )
