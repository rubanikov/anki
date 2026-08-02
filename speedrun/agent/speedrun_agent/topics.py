# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The query set, taken from the Outline rather than invented here.

ADR-0006 fixes the query set before the first run: the 31 content categories,
three generation requests each. So the retrieval query for a Topic is the
Outline's own title for it — not a phrase tuned until retrieval looked good, and
never the candidate answer. A query derived from the answer would make the gate
a formality, since retrieval would be handed the very string the gate is about
to look for.

The Outline is AAMC's, loaded through the corpus's `outline.py`, which refuses
to load anything that is not 9 / 10 / 12 categories.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .corpus_gateway import CORPUS_DIR, ensure_on_path


@lru_cache(maxsize=1)
def _outline() -> Any | None:
    ensure_on_path()
    try:
        import outline  # noqa: PLC0415

        return outline.load_outline(CORPUS_DIR / "outline.json")
    except Exception:  # noqa: BLE001 - a missing Outline degrades queries, not the gate
        return None


def known(topic_id: str) -> bool:
    loaded = _outline()
    return loaded is not None and loaded.get(topic_id) is not None


@lru_cache(maxsize=64)
def query_for(topic_id: str) -> str:
    """The fixed retrieval query for a Topic: everything the Outline says about it.

    The title alone turned out to be a poor query, and that is worth recording
    rather than quietly fixing: AAMC titles are abstract ("Principles of
    bioenergetics and fuel molecule metabolism") while the book is concrete
    ("citric acid cycle", "pyruvate"), so BM25 over the title retrieves the
    chapter's throat-clearing and the gate then drops perfectly groundable
    items. Adding the category's itemised topic list — still AAMC's own words,
    from the same file, chosen before any run — closes that gap without letting
    the query drift toward what we hoped the corpus would say.

    The nine Bio/Biochem categories have topic lists; the rest fall back to the
    title, which is all the Outline records for them.
    """
    loaded = _outline()
    if loaded is None:
        return topic_id
    category = loaded.get(topic_id)
    if category is None:
        return topic_id
    return " ".join([category.title, *category.all_topic_text()])


def ids() -> list[str]:
    loaded = _outline()
    return loaded.ids() if loaded is not None else []
