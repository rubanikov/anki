# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""What the dashboard must never do.

Every test here corresponds to a way this screen could mislead someone:

- an abstention rendered as an empty box, or as an error, instead of as the
  result it is
- a mastery figure printed without the count of cards it could not account for
- a number on screen that the backend did not produce
- a Topic label visible while the question it labels is still unanswered

The first two tests drive the real backend on a real (empty) collection, so
they assert the sentence a student would actually read, not one this repo made
up. They skip when the Python bindings are not built — run them with
`PYTHONPATH=out/pylib`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
import render
import topics

TAG_PREFIX = "mcat"

SECTIONS = [
    ("Chem/Phys", "CP", 10),
    ("Bio/Biochem", "BB", 9),
    ("Psych/Soc", "PS", 12),
    ("CARS", "CARS", 0),
]


# --------------------------------------------------------------------------
# Against the real backend
# --------------------------------------------------------------------------


@pytest.fixture
def empty_collection(tmp_path):
    anki = pytest.importorskip(
        "anki.collection",
        reason="Python bindings not built; run with PYTHONPATH=out/pylib",
    )
    col = anki.Collection(str(tmp_path / "collection.anki2"))
    yield col
    col.close()


def _dashboard_for(col) -> str:
    sections = []
    for name, code, outline in SECTIONS:
        scores = col._backend.section_scores(
            section=code, tag_prefix=TAG_PREFIX, outline_topic_count=outline
        )
        mastery = col._backend.topic_mastery(section=code, tag_prefix=TAG_PREFIX)
        sections.append((name, scores, list(mastery.topics)))
    collection_mastery = col._backend.topic_mastery(section="", tag_prefix=TAG_PREFIX)
    return render.render_dashboard(sections, collection_mastery)


def test_every_score_abstains_on_an_empty_collection_and_names_its_shortfall(
    empty_collection,
):
    html = _dashboard_for(empty_collection)

    # Three scores in each of four sections, all withheld, all rendered.
    assert html.count(render.ABSTAINING) == 12

    # The reasons on screen are the backend's own, naming the specific number
    # that would resolve each one.
    assert "Only 0 graded reviews in BB. Need 200." in html
    assert (
        "Only 0 unhinted questions answered in CP. Need 20, across at least 4 topics."
        in html
    )
    assert "No readiness for PS until memory is available" in html
    # CARS says we do not model it, so its absence reads as a decision.
    assert "the AAMC states there" in html

    # Abstaining is a result, not a failure to produce one.
    assert "Could not read the collection" not in html


def test_the_unmapped_card_count_is_on_screen_for_every_section(empty_collection):
    html = _dashboard_for(empty_collection)

    # Once per section, plus the collection-wide panel. A mastery figure whose
    # denominator is hidden is the thing this product exists to replace, so the
    # count is shown even when it is zero.
    assert html.count("Unmapped cards") == len(SECTIONS)
    assert "Cards unmapped" in html
    assert "Speedrun&#x27;s own cards excluded" in html


# --------------------------------------------------------------------------
# Rendering, against stand-ins
# --------------------------------------------------------------------------


@dataclass
class FakeScore:
    available: bool = False
    estimate: float = 0.0
    range_low: float = 0.0
    range_high: float = 0.0
    abstain_reason: str = ""
    reasons: list = field(default_factory=list)
    confidence: int = 0


@dataclass
class FakeSection:
    section: str = "BB"
    memory: FakeScore = field(default_factory=FakeScore)
    performance: FakeScore = field(default_factory=FakeScore)
    readiness: FakeScore = field(default_factory=FakeScore)
    coverage_pct: float = 0.0
    graded_reviews: int = 0
    holdout_attempts: int = 0
    topics_attempted: int = 0
    cards_unmapped: int = 0
    computed_at_ms: int = 0


def test_the_estimate_is_printed_as_the_backend_produced_it():
    # Memory arrives as a probability. Rendering it as "87%" would mean this
    # file multiplied by a hundred, and the moment it computes one number it can
    # compute a different one from Android.
    section = FakeSection(
        memory=FakeScore(
            available=True, estimate=0.87, range_low=0.81, range_high=0.93, confidence=2
        )
    )
    html = render.render_section("Bio/Biochem", section)

    assert ">0.87<" in html
    assert "Range 0.81 – 0.93" in html
    assert "87%" not in html
    assert "Confidence: Medium" in html


def test_coverage_is_printed_with_the_percentage_the_backend_computed():
    html = render.render_section("Bio/Biochem", FakeSection(coverage_pct=33.0))
    assert "33%" in html


def test_an_abstention_keeps_the_reason_and_never_renders_an_empty_box():
    reason = "Only 84 graded reviews in CP. Need 200."
    html = render.render_section(
        "Chem/Phys", FakeSection(memory=FakeScore(abstain_reason=reason))
    )

    assert reason in html
    assert render.ABSTAINING in html
    # It occupies the same box an available score would.
    assert 'class="score abstained"' in html


def test_an_abstention_with_no_reason_still_says_something():
    # The backend always supplies one; if it ever stops, the screen must not
    # quietly show a blank.
    html = render.render_section("Chem/Phys", FakeSection())
    assert "no reason was supplied" in html


def test_backend_text_is_escaped_before_it_reaches_the_page():
    html = render.render_section(
        "Chem/Phys",
        FakeSection(memory=FakeScore(abstain_reason="<script>alert(1)</script>")),
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_a_failed_read_is_not_dressed_up_as_an_abstention():
    html = render.render_error("database is locked")
    assert "database is locked" in html
    assert render.ABSTAINING not in html


# --------------------------------------------------------------------------
# The Topic label during review
# --------------------------------------------------------------------------

TAGS = ["leech", "mcat::BB::amino_acids"]


def test_the_topic_label_is_withheld_while_the_question_is_showing():
    # A deck whose template renders {{Tags}} prints the Topic straight onto the
    # question. No CSS selector reaches that, so the text is redacted.
    question = "<div>What buffers blood pH?</div><div>mcat::BB::amino_acids</div>"
    out = topics.hide_topic_in_question(question, TAGS, TAG_PREFIX)

    assert "mcat::BB::amino_acids" not in out
    assert topics.TOPIC_MASK in out
    assert "What buffers blood pH?" in out
    # And anything the add-on itself rendered is hidden too.
    assert ".speedrun-topic" in out


def test_the_topic_label_comes_back_with_the_answer():
    out = topics.reveal_topic_in_answer("<div>Histidine</div>", TAGS, TAG_PREFIX)
    assert "Topic: mcat::BB::amino_acids" in out
    assert "Histidine" in out


def test_a_card_with_no_topic_gets_no_label():
    out = topics.reveal_topic_in_answer("<div>Histidine</div>", ["leech"], TAG_PREFIX)
    assert "Topic:" not in out


def test_a_longer_topic_tag_is_not_left_half_redacted():
    # Redacting "mcat::BB::acid" first would leave "•••_base" on screen, which
    # still names the category.
    tags = ["mcat::BB::acid", "mcat::BB::acid_base"]
    out = topics.hide_topic_in_question("mcat::BB::acid_base", tags, TAG_PREFIX)
    assert "acid_base" not in out
    assert "acid" not in out.replace(topics.TOPIC_MASK, "")


def test_a_tag_that_names_only_a_section_is_not_a_topic():
    # "mcat::BB" says which exam section, not which content category, so there
    # is nothing to attribute mastery to and nothing to hide.
    assert topics.topic_from_tag("mcat::BB", TAG_PREFIX) is None
    assert topics.topic_from_tag("anatomy::BB::x", TAG_PREFIX) is None
    assert topics.topic_from_tag("leech", TAG_PREFIX) is None
    assert (
        topics.topic_from_tag("mcat::BB::amino_acids", TAG_PREFIX)
        == "mcat::BB::amino_acids"
    )


def test_a_note_with_several_topic_tags_is_labelled_with_one():
    tags = ["leech", "mcat::CP::thermodynamics", "mcat::CP::kinetics"]
    assert topics.topic_label(tags, TAG_PREFIX) == "mcat::CP::thermodynamics"
