# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The Outline: AAMC's published list of what each MCAT section tests.

The Outline is an external authority, not something Speedrun authors. This
module is the only place the repository reads it from, and `outline.json` beside
it is the only copy. Every Topic is one entry here.

Two invariants are asserted on load, because both are things a silent edit could
break and neither would be noticed by a caller:

  * exactly 31 content categories, split 9 / 10 / 12 across BB / CP / PS
  * every category identifier is unique and its foundational concept belongs to
    the same section it does

Coverage is the share of a section's Outline a student has studied. If a
category vanishes from this file, coverage silently rises for everyone. That is
the failure this module's load-time check exists to prevent.

Stdlib only: the add-on's bundled Python has nothing else, and the agent service
should be able to read the Outline without importing the corpus index.
"""

from __future__ import annotations

import dataclasses
import json
from functools import lru_cache
from pathlib import Path

OUTLINE_PATH = Path(__file__).resolve().parent / "outline.json"

#: The three sections that have content categories. CARS has none by AAMC's own
#: account of what it tests, so nothing is ever attributed to it.
SCORED_CONTENT_SECTIONS = ("BB", "CP", "PS")

#: What the Outline must contain. Hard-coded so that editing outline.json cannot
#: quietly change what "full coverage" means.
EXPECTED_CATEGORY_COUNTS = {"BB": 9, "CP": 10, "PS": 12}


class OutlineError(RuntimeError):
    """The Outline on disk is not the Outline this code was written against."""


@dataclasses.dataclass(frozen=True)
class ContentCategory:
    """One Topic — the lettered unit of the Outline, such as 1A or 5C."""

    id: str
    section: str
    foundational_concept: int
    title: str
    topics: tuple[dict, ...] = ()

    @property
    def has_topic_list(self) -> bool:
        """Whether AAMC's own topic list was captured for this category.

        False for CP and PS: only the demo section's lists were fetched, and a
        caller that reasons about topics must not mistake "not fetched" for
        "AAMC lists nothing here".
        """
        return bool(self.topics)

    def topic_titles(self) -> list[str]:
        return [t["title"] for t in self.topics]

    def all_topic_text(self) -> list[str]:
        """Every topic and subtopic string, flattened. Used for attribution."""
        out: list[str] = []
        for topic in self.topics:
            out.append(topic["title"])
            out.extend(topic.get("subtopics", ()))
        return out


@dataclasses.dataclass(frozen=True)
class Outline:
    categories: tuple[ContentCategory, ...]
    foundational_concepts: dict[int, str]
    sections: tuple[dict, ...]
    provenance: dict

    def __getitem__(self, category_id: str) -> ContentCategory:
        for category in self.categories:
            if category.id == category_id:
                return category
        raise KeyError(category_id)

    def get(self, category_id: str) -> ContentCategory | None:
        try:
            return self[category_id]
        except KeyError:
            return None

    def ids(self) -> list[str]:
        return [c.id for c in self.categories]

    def in_section(self, section: str) -> list[ContentCategory]:
        return [c for c in self.categories if c.section == section]

    def section_of(self, category_id: str) -> str:
        return self[category_id].section


def _validate(outline: Outline, fc_section: dict[int, str]) -> None:
    ids = outline.ids()
    if len(ids) != len(set(ids)):
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        raise OutlineError(f"duplicate content category ids: {duplicates}")

    total = sum(EXPECTED_CATEGORY_COUNTS.values())
    if len(ids) != total:
        raise OutlineError(f"expected {total} content categories, found {len(ids)}")

    for section, expected in EXPECTED_CATEGORY_COUNTS.items():
        found = len(outline.in_section(section))
        if found != expected:
            raise OutlineError(
                f"section {section} should have {expected} content categories, "
                f"found {found}"
            )

    for category in outline.categories:
        declared = fc_section.get(category.foundational_concept)
        if declared != category.section:
            raise OutlineError(
                f"{category.id} is in section {category.section} but its "
                f"foundational concept {category.foundational_concept} belongs "
                f"to {declared}"
            )
        if not category.id.startswith(str(category.foundational_concept)):
            raise OutlineError(
                f"{category.id} does not belong to foundational concept "
                f"{category.foundational_concept}"
            )


@lru_cache(maxsize=1)
def load_outline(path: Path | None = None) -> Outline:
    """Read and validate the Outline. Cached: it never changes at runtime."""
    source = path or OUTLINE_PATH
    data = json.loads(source.read_text(encoding="utf-8"))

    categories = tuple(
        ContentCategory(
            id=entry["id"],
            section=entry["section"],
            foundational_concept=entry["foundational_concept"],
            title=entry["title"],
            topics=tuple(entry.get("topics", ())),
        )
        for entry in data["content_categories"]
    )
    outline = Outline(
        categories=categories,
        foundational_concepts={
            fc["number"]: fc["statement"] for fc in data["foundational_concepts"]
        },
        sections=tuple(data["sections"]),
        provenance=data["provenance"],
    )
    _validate(
        outline,
        {fc["number"]: fc["section"] for fc in data["foundational_concepts"]},
    )
    return outline


def main() -> int:
    outline = load_outline()
    print(f"{len(outline.categories)} content categories")
    for section in SCORED_CONTENT_SECTIONS:
        cats = outline.in_section(section)
        with_topics = sum(1 for c in cats if c.has_topic_list)
        print(f"  {section}: {len(cats)} categories, {with_topics} with topic lists")
        for cat in cats:
            print(f"    {cat.id:<4} {cat.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
