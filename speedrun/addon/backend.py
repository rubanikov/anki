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
    """Topic mastery within one section."""
    return col._backend.topic_mastery(section=section, tag_prefix=tag_prefix)


def section_scores(
    col: Any, section: str, tag_prefix: str, outline_topic_count: int
) -> Any:
    """The three scores for one section, with their ranges and abstentions."""
    return col._backend.section_scores(
        section=section,
        tag_prefix=tag_prefix,
        outline_topic_count=outline_topic_count,
    )
