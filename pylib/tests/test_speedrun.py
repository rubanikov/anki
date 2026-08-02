# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""End-to-end check that the Rust measurement layer is reachable from Python.

The add-on renders scores; it never computes them. This test is the proof that
the boundary works, and that the give-up rule is enforced on the far side of it
where no UI can talk its way past.
"""

from tests.shared import getEmptyCol


def test_speedrun_backend_enforces_the_give_up_rule():
    col = getEmptyCol()

    # A real card exists, but nothing has been reviewed and it carries no
    # topic tag. There is nothing to measure.
    note = col.newNote()
    note["Front"] = "foo"
    col.addNote(note)

    mastery = col._backend.topic_mastery(section="", tag_prefix="mcat")
    assert list(mastery.topics) == []
    assert mastery.cards_considered == 0
    # Speedrun's own attempt cards are excluded by construction; none exist yet.
    assert mastery.cards_excluded == 0

    scores = col._backend.section_scores(
        section="BB", tag_prefix="mcat", outline_topic_count=0
    )

    # Three scores, reported separately, none of them invented.
    for score in (scores.memory, scores.performance, scores.readiness):
        assert not score.available
        assert score.estimate == 0.0
        # Abstaining silently is not good enough — it has to say what would fix it.
        assert score.abstain_reason

    assert "graded reviews" in scores.memory.abstain_reason
    assert "unhinted questions" in scores.performance.abstain_reason
    assert scores.graded_reviews == 0
    assert scores.holdout_attempts == 0
    assert scores.computed_at_ms > 0

    col.close()


def test_speedrun_never_models_cars():
    col = getEmptyCol()

    scores = col._backend.section_scores(
        section="CARS", tag_prefix="mcat", outline_topic_count=100
    )

    # The reading section has no content knowledge to model, by the AAMC's own
    # definition, so the knowledge machinery refuses to run on it at all.
    assert not scores.memory.available
    assert not scores.performance.available
    assert not scores.readiness.available
    assert "AAMC" in scores.readiness.abstain_reason
    assert scores.coverage_pct == 0.0

    col.close()


def test_speedrun_measures_a_deck_that_carries_none_of_our_tags():
    """The Crosswalk, end to end: a real deck's own labels read as topics.

    The deck here is shaped like MileDown's — a `MileDown::` tag hierarchy under
    subject subdecks, and not one `mcat::` tag anywhere. Making it measurable by
    writing our tags onto these notes would sync to the student's phone and
    break the Sensor rule, so the mapping is installed beside the collection and
    applied at read time instead.
    """
    col = getEmptyCol()

    biochem = col.decks.id("MileDown's MCAT Decks::Biochemistry")
    physics = col.decks.id("MileDown's MCAT Decks::Physics and Math")

    def add(deck_id, tags):
        note = col.newNote()
        note["Front"] = "q"
        note.tags = list(tags)
        col.add_note(note, deck_id)

    add(biochem, ["MileDown::Biochemistry::Amino_Acids"])
    add(biochem, ["MileDown::Biochemistry::DNA_and_RNA::Translation"])
    # Research design is a reasoning skill, not one of the 31 content
    # categories. Nothing should ever place it.
    add(physics, ["MileDown::Physics::Research::Data"])

    # Before the crosswalk: nothing is measurable, and the whole deck is
    # reported as unmapped rather than quietly skipped.
    mastery = col._backend.topic_mastery(section="BB", tag_prefix="mcat")
    assert list(mastery.topics) == []
    assert mastery.cards_unmapped == 3

    col.set_config(
        "speedrunCrosswalk",
        {
            "id": "test-bb",
            "entries": [
                {
                    "tag": "MileDown::Biochemistry::Amino_Acids",
                    "section": "BB",
                    "topic": "1A",
                },
                {
                    "tag": "MileDown::Biochemistry::DNA_and_RNA",
                    "section": "BB",
                    "topic": "1B",
                },
                {
                    "tag": "MileDown::Physics::Research",
                    "topic": None,
                    "reason": "A reasoning skill, not a content category.",
                },
            ],
        },
    )

    mastery = col._backend.topic_mastery(section="BB", tag_prefix="mcat")

    assert [topic.topic_id for topic in mastery.topics] == [
        "mcat::BB::1A",
        "mcat::BB::1B",
    ]
    assert mastery.cards_considered == 2
    # Non-zero, and on a partially mapped deck: the refused card is counted so
    # that the mastery above has a stated denominator.
    assert mastery.cards_unmapped == 1
    assert mastery.cards_excluded == 0

    # The notes are exactly as the student left them.
    for note_id in col.find_notes(""):
        assert not any(tag.startswith("mcat") for tag in col.get_note(note_id).tags)

    col.close()
