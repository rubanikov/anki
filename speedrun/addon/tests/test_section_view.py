# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The dashboard derives each section's mastery instead of asking for it.

Benchmarking a 50,000-card deck found the page spending about half its time
scanning the collection for answers it already had: ``SectionScores`` computes a
section's mastery internally, and the page then asked the backend for that same
section's mastery again, once per section.

The collection-wide read already contains every per-section read, because every
topic carries the section it belongs to. So the page reads once and narrows.

The tests that matter here are the ones asserting the narrowed view is *equal*
to what the backend would have returned. An optimisation that quietly changes a
number is worse than the cost it saved.
"""

from __future__ import annotations

from speedrun.addon import backend

from test_dashboard import crosswalked_collection  # noqa: F401 - pytest fixture


def _sorted_topics(topics):
    return sorted((t.topic_id, t.card_count, round(t.mean_retrievability, 6)) for t in topics)


def test_the_derived_view_matches_what_the_backend_would_have_returned(
    crosswalked_collection,  # noqa: F811
):
    """The whole justification for not asking. If these ever diverge, the
    dashboard is showing a different number than the engine would."""
    col = crosswalked_collection
    whole = backend.collection_mastery(col, "mcat")

    for section in ("BB", "CP", "PS", "CARS"):
        fetched = backend.section_mastery(col, section, "mcat")
        derived = backend.section_view(whole, section)

        assert _sorted_topics(derived.topics) == _sorted_topics(fetched.topics), (
            f"{section}: derived topics differ from the backend's own"
        )
        assert derived.cards_considered == fetched.cards_considered, (
            f"{section}: derived mapped-card count differs from the backend's own"
        )


def test_the_sections_partition_the_collections_topics(
    crosswalked_collection,  # noqa: F811
):
    """No topic is claimed by two sections, and none is lost between them —
    otherwise a card could be counted twice or vanish from every panel."""
    col = crosswalked_collection
    whole = backend.collection_mastery(col, "mcat")

    seen = []
    for section in ("BB", "CP", "PS", "CARS"):
        seen.extend(t.topic_id for t in backend.section_view(whole, section).topics)

    assert len(seen) == len(set(seen)), "a topic appears in more than one section"
    assert set(seen) == {t.topic_id for t in whole.topics}, (
        "the sections do not account for every topic the collection has"
    )


def test_the_comparison_can_fail(crosswalked_collection):  # noqa: F811
    """Guard against the equality tests passing because both sides are empty.

    A deck with no mapped cards would satisfy every assertion above while
    proving nothing, so assert the fixture actually has something to compare.
    """
    col = crosswalked_collection
    whole = backend.collection_mastery(col, "mcat")
    bb = backend.section_view(whole, "BB")

    assert bb.topics, "fixture has no Bio/Biochem topics; the comparison is vacuous"
    assert bb.cards_considered > 0
    # And a wrong section really does come out different.
    assert _sorted_topics(bb.topics) != _sorted_topics(
        backend.section_view(whole, "CARS").topics
    )
