# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The Outline is the denominator of coverage, so it is tested like one.

Every failure here corresponds to a way a number on screen could be wrong
without anyone noticing: a lost content category makes coverage rise for
everybody, and an attribution rule pointing at a category from a section this
corpus never ingested makes that section look sourced when it is not.
"""

from __future__ import annotations

import json

import pytest

import attribution
from outline import (
    EXPECTED_CATEGORY_COUNTS,
    OUTLINE_PATH,
    OutlineError,
    load_outline,
)


@pytest.fixture(scope="module")
def outline():
    return load_outline()


def test_there_are_thirty_one_content_categories(outline):
    assert len(outline.categories) == 31


@pytest.mark.parametrize("section,count", sorted(EXPECTED_CATEGORY_COUNTS.items()))
def test_each_section_has_the_categories_aamc_says_it_has(outline, section, count):
    assert len(outline.in_section(section)) == count


def test_every_category_has_a_title(outline):
    for category in outline.categories:
        assert category.title.strip()


def test_the_demo_section_carries_aamc_topic_lists(outline):
    """Attribution is argued from these. Without them it is just assertion."""
    for category in outline.in_section("BB"):
        assert category.has_topic_list, f"{category.id} has no topic list"
        assert len(category.all_topic_text()) > 5


def test_topic_lists_outside_the_demo_section_are_absent_not_empty(outline):
    """CP and PS were never fetched. Nothing may read that as 'AAMC lists none'."""
    for section in ("CP", "PS"):
        for category in outline.in_section(section):
            assert not category.has_topic_list


def test_a_missing_category_is_refused(tmp_path):
    data = json.loads(OUTLINE_PATH.read_text(encoding="utf-8"))
    data["content_categories"] = data["content_categories"][:-1]
    broken = tmp_path / "outline.json"
    broken.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(OutlineError):
        load_outline(broken)


def test_every_attribution_rule_names_a_real_category():
    rules = attribution.load_rules()
    known = set(load_outline().ids())
    for mapping in (rules.by_section, rules.by_chapter):
        for result in mapping.values():
            assert set(result.categories) <= known


def test_no_rule_attributes_this_book_outside_the_demo_section():
    """A Bio book must never make Chem/Phys or Psych/Soc look sourced."""
    outline = load_outline()
    rules = attribution.load_rules()
    for mapping in (rules.by_section, rules.by_chapter):
        for result in mapping.values():
            for category in result.categories:
                assert outline[category].section == "BB"


def test_unattributed_is_a_real_outcome():
    """If everything is attributed, the map has stopped being a judgement."""
    rules = attribution.load_rules()
    empty = [
        r
        for mapping in (rules.by_section, rules.by_chapter)
        for r in mapping.values()
        if not r.is_attributed
    ]
    assert empty
    assert rules.known_gaps


def test_every_attribution_carries_its_reasoning():
    rules = attribution.load_rules()
    for mapping in (rules.by_section, rules.by_chapter):
        for result in mapping.values():
            assert result.note, f"rule {result.rule} has no note"
            assert result.confidence in {"high", "medium", "low", "none"}


def test_an_unnumbered_page_can_inherit_a_section_from_its_heading():
    """A chapter 6 summary paragraph about enzymes is 1A, not 1D."""
    page_level = attribution.attribute("6", "")
    chunk_level = attribution.attribute_chunk("6", "", ("Chapter Summary", "6.5 Enzymes"))
    assert page_level.categories == ("1D",)
    assert chunk_level.categories == ("1A",)


def test_a_heading_without_a_rule_leaves_the_page_attribution_alone():
    assert attribution.attribute_chunk("6", "", ("Chapter Summary",)).categories == (
        "1D",
    )
