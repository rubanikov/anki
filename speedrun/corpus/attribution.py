# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Which Topic a chunk is about, when that can be said honestly.

Attribution runs on the book's own structure - a section number - rather than on
the chunk's words, and the rules are hand-authored in `attribution.json` against
AAMC's published topic lists. That is a deliberately conservative design. A
keyword scorer over the same topic lists attributes everything, including the
chapters the MCAT does not test, and it is confident about all of it. Unattributed
is a real answer here, and roughly a third of the book gets it.

The rule that matters: a chunk with no honest attribution carries `[]`, and
category-filtered retrieval will not return it. It is never swept into a nearby
category to make the numbers look complete, because the two things that consume
this - coverage and the generator's category filter - are both measurements, and
a measurement whose denominator has been quietly padded is the kind of number
this project exists to distrust.
"""

from __future__ import annotations

import dataclasses
import json
import re
from functools import lru_cache
from pathlib import Path

from outline import load_outline

ATTRIBUTION_PATH = Path(__file__).resolve().parent / "attribution.json"

_SECTION_NUMBER = re.compile(r"\d+\.\d+")

UNATTRIBUTED = "unattributed"


@dataclasses.dataclass(frozen=True)
class Attribution:
    categories: tuple[str, ...]
    confidence: str
    rule: str | None
    note: str = ""

    @property
    def is_attributed(self) -> bool:
        return bool(self.categories)


NOTHING = Attribution(categories=(), confidence=UNATTRIBUTED, rule=None)


@dataclasses.dataclass(frozen=True)
class Rules:
    by_section: dict[str, Attribution]
    by_chapter: dict[str, Attribution]
    known_gaps: tuple[str, ...]
    method: str

    def for_page(self, chapter: str, section: str) -> Attribution:
        """Most specific rule wins: section, then chapter, then nothing."""
        if section and section in self.by_section:
            return self.by_section[section]
        if chapter and chapter in self.by_chapter:
            return self.by_chapter[chapter]
        return NOTHING


class AttributionError(RuntimeError):
    """A rule names a content category the Outline does not have."""


@lru_cache(maxsize=1)
def load_rules(path: Path | None = None) -> Rules:
    data = json.loads((path or ATTRIBUTION_PATH).read_text(encoding="utf-8"))
    outline = load_outline()
    known = set(outline.ids())

    by_section: dict[str, Attribution] = {}
    by_chapter: dict[str, Attribution] = {}
    for entry in data["rules"]:
        categories = tuple(entry.get("categories", ()))
        unknown = [c for c in categories if c not in known]
        if unknown:
            raise AttributionError(
                f"rule {entry} names categories not in the Outline: {unknown}"
            )
        # Nothing in this corpus may be attributed outside the demo section: the
        # book was ingested for Bio/Biochem, and a Chem/Phys or Psych/Soc claim
        # sourced from it would make a section look covered by a book that was
        # never read for it.
        outside = [c for c in categories if outline[c].section != "BB"]
        if outside:
            raise AttributionError(
                f"rule {entry} attributes a Bio/Biochem book to {outside}"
            )
        attribution = Attribution(
            categories=categories,
            confidence=entry.get("confidence", UNATTRIBUTED),
            rule=entry.get("section") or f"chapter {entry.get('chapter')}",
            note=entry.get("note", ""),
        )
        if "section" in entry:
            by_section[entry["section"]] = attribution
        elif "chapter" in entry:
            by_chapter[str(entry["chapter"])] = attribution
        else:
            raise AttributionError(f"rule has neither a section nor a chapter: {entry}")

    return Rules(
        by_section=by_section,
        by_chapter=by_chapter,
        known_gaps=tuple(data.get("known_gaps", ())),
        method=data.get("method", ""),
    )


def attribute(chapter: str, section: str) -> Attribution:
    return load_rules().for_page(chapter, section)


def attribute_chunk(
    chapter: str, section: str, heading_path: tuple[str, ...] = ()
) -> Attribution:
    """Attribution for one chunk, using its headings when the page has no number.

    Key Terms and Chapter Summary pages carry no section number, so the page
    rule can only be the chapter's - which files the summary of "6.5 Enzymes"
    under 1D along with the rest of chapter 6, when its subject is 1A. Those
    pages do keep the section number in their headings, and this reads it. The
    heading is only trusted when it names a section that has a rule of its own;
    otherwise the page's own attribution stands.
    """
    if not section:
        for heading in heading_path:
            match = _SECTION_NUMBER.match(heading)
            if match and match.group(0) in load_rules().by_section:
                return load_rules().by_section[match.group(0)]
    return attribute(chapter, section)


def coverage_report(pages: list[dict]) -> dict[str, object]:
    """How much of the book, and of the demo section's Outline, got attributed."""
    outline = load_outline()
    per_category: dict[str, int] = {c.id: 0 for c in outline.in_section("BB")}
    attributed = 0
    for page in pages:
        result = attribute(page.get("chapter", ""), page.get("section", ""))
        if result.is_attributed:
            attributed += 1
            for category in result.categories:
                per_category[category] += 1
    return {
        "pages": len(pages),
        "pages_attributed": attributed,
        "pages_unattributed": len(pages) - attributed,
        "pages_per_category": per_category,
        "categories_with_no_pages": sorted(
            c for c, n in per_category.items() if n == 0
        ),
    }
