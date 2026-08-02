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
