# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""What the dashboard must never do.

Every test here corresponds to a way this screen could mislead someone:

- an abstention rendered as an empty box, or as an error, instead of as the
  result it is
- a mastery figure printed without the count of cards it could not account for
- a mastery figure whose unmapped count is technically present and practically
  invisible
- a number on screen that the backend did not produce
- a Topic label visible while the question it labels is still unanswered

Several tests drive the real backend on a real collection, so they assert the
sentence a student would actually read, not one this repo made up. One of those
collections carries the *shipped* crosswalk and a deck labelled the way MileDown
labels one, which is the arrangement the dashboard actually runs in. They skip
when the Python bindings are not built — run them with `PYTHONPATH=out/pylib`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import render
import topics

CROSSWALK_PATH = (
    Path(__file__).resolve().parents[2] / "crosswalk" / "miledown-bb-v1.json"
)

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
        sections.append((name, scores, mastery))
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


#: The evidence-row label, matched with its markup so that counting it cannot
#: be thrown off by the same words appearing in the explanatory note.
UNMAPPED_LABEL = '<span class="k">Unmapped cards</span>'


def test_the_unmapped_card_count_is_on_screen_for_every_section(empty_collection):
    html = _dashboard_for(empty_collection)

    # Once per section in the evidence row, and once per section *above* the
    # scores as well, plus the collection-wide panel. A mastery figure whose
    # denominator is hidden is the thing this product exists to replace, so the
    # count is shown even when it is zero.
    assert html.count(UNMAPPED_LABEL) == len(SECTIONS)
    assert html.count("cards Unmapped</span>") == len(SECTIONS) + 1
    assert "Cards unmapped" in html
    assert "Speedrun&#x27;s own cards excluded" in html


# --------------------------------------------------------------------------
# Against the real backend, with the shipped crosswalk installed
# --------------------------------------------------------------------------
#
# A deck that carries none of Speedrun's tags is the normal case — it is the
# entire reason the crosswalk exists — so a dashboard only ever exercised
# against `mcat::`-tagged notes has never been run in its own working
# conditions. These build a small collection labelled the way MileDown's deck is
# labelled, install the shipped crosswalk file unmodified, and read what comes
# back.

#: Tags copied from the shipped crosswalk, with the counts each contributes.
#: Two of them are cards the crosswalk cannot place: one label it examined and
#: refused, one it never claimed at all.
MAPPED_TAGS = {
    "MileDown::Biochemistry::Amino_Acids": 3,  # -> mcat::BB::1A
    "MileDown::Biochemistry::DNA_and_RNA::Translation": 2,  # -> mcat::BB::1B
}
UNPLACEABLE_TAGS = {
    "MileDown::Biochemistry::Lab_Techniques": 2,  # an explicit refusal
    "MileDown::General_Chemistry::Stoichiometry": 2,  # never claimed
}
UNTAGGED_CARDS = 1

MAPPED_CARDS = sum(MAPPED_TAGS.values())
UNMAPPED_CARDS = sum(UNPLACEABLE_TAGS.values()) + UNTAGGED_CARDS


@pytest.fixture
def crosswalked_collection(tmp_path):
    """A MileDown-shaped deck with the shipped crosswalk in collection config.

    Deliberately never reviewed, because the deck this mirrors never has been
    either: MileDown's `.apkg` ships with an empty review log. Every score here
    abstains for the same reason it abstains against the real 2,888-card deck.
    """
    anki = pytest.importorskip(
        "anki.collection",
        reason="Python bindings not built; run with PYTHONPATH=out/pylib",
    )
    col = anki.Collection(str(tmp_path / "collection.anki2"))

    # The file is passed through whole, extra top-level keys and all — that is
    # how it is installed for real, and a test that hand-trimmed it first would
    # not be testing the shipped artifact.
    col.set_config(
        "speedrunCrosswalk", json.loads(CROSSWALK_PATH.read_text(encoding="utf8"))
    )

    deck_id = col.decks.id("MileDown's MCAT Decks::Biochemistry")
    basic = col.models.by_name("Basic")
    counts = dict(MAPPED_TAGS)
    counts.update(UNPLACEABLE_TAGS)
    counts[""] = UNTAGGED_CARDS
    for tag, count in counts.items():
        for index in range(count):
            note = col.new_note(basic)
            note["Front"] = f"{tag or 'untagged'} {index}"
            note["Back"] = "answer"
            note.tags = [tag] if tag else []
            col.add_note(note, deck_id)

    yield col
    col.close()


def test_the_crosswalk_maps_a_decks_own_labels_without_touching_a_note(
    crosswalked_collection,
):
    col = crosswalked_collection
    before = col.db.scalar("select sum(mod) from notes")

    mastery = col._backend.topic_mastery(section="BB", tag_prefix=TAG_PREFIX)

    # Read through the crosswalk: the notes carry no `mcat::` tag at all.
    assert {topic.topic_id: topic.card_count for topic in mastery.topics} == {
        "mcat::BB::1A": MAPPED_TAGS["MileDown::Biochemistry::Amino_Acids"],
        "mcat::BB::1B": MAPPED_TAGS["MileDown::Biochemistry::DNA_and_RNA::Translation"],
    }
    assert mastery.cards_considered == MAPPED_CARDS

    # And the reading wrote nothing back. A crosswalk that tagged the notes
    # would be a mutation that syncs to the student's phone.
    assert col.db.scalar("select sum(mod) from notes") == before
    assert col.find_cards(f"tag:{TAG_PREFIX}::*") == []


def test_a_label_the_crosswalk_refused_is_counted_unmapped_not_dropped(
    crosswalked_collection,
):
    # The distinction that matters: a card the crosswalk declined to place is
    # not the same as a card that does not exist. Both refusals and never-claimed
    # labels land in the same count, and that count is reported.
    mastery = crosswalked_collection._backend.topic_mastery(
        section="BB", tag_prefix=TAG_PREFIX
    )
    assert mastery.cards_unmapped == UNMAPPED_CARDS
    assert mastery.cards_considered + mastery.cards_unmapped == (
        crosswalked_collection.card_count()
    )


def test_the_unmapped_count_is_never_narrowed_away_by_choosing_a_section(
    crosswalked_collection,
):
    # The crosswalk covers Bio/Biochem only. Asking about Chem/Phys must not
    # make the cards it cannot place disappear — "how much of your deck can we
    # not place" is a question about the deck.
    col = crosswalked_collection
    for code in ("BB", "CP", "PS", ""):
        mastery = col._backend.topic_mastery(section=code, tag_prefix=TAG_PREFIX)
        assert mastery.cards_unmapped == UNMAPPED_CARDS, code


def test_the_dashboard_prints_both_counts_where_a_reader_meets_them_first(
    crosswalked_collection,
):
    html = _dashboard_for(crosswalked_collection)

    # Both figures, in the banner, in every section — the mapped count beside
    # the unmapped one, because the comparison is what the reader needs.
    assert f"{UNMAPPED_CARDS} cards Unmapped</span>" in html
    assert f"{MAPPED_CARDS} mapped to Bio/Biochem</span>" in html
    assert "0 mapped to Chem/Phys</span>" in html

    # Above the scores, not below them. A denominator a reader reaches only
    # after the number it qualifies has already been read is not a denominator.
    banner = html.index("cards Unmapped</span>")
    assert banner < html.index("Abstaining")
    assert banner < html.index(render.SCORE_BLURBS["Memory"])

    # And it says what the count means rather than leaving a bare figure.
    assert render.UNMAPPED_NOTE in html


def test_a_crosswalked_but_unreviewed_deck_abstains_everywhere_and_says_why(
    crosswalked_collection,
):
    """The state the real deck is in today, and it is a result, not a failure.

    Mapping cards to topics does not produce a Memory score and must not look
    like it did. The crosswalk supplies a denominator; only review history
    supplies a numerator, and this deck has none.
    """
    html = _dashboard_for(crosswalked_collection)

    assert html.count(render.ABSTAINING) == 12
    assert "Only 0 graded reviews in BB. Need 200." in html
    # Not an error, not an empty state.
    assert "Could not read the collection" not in html
    assert "no reason was supplied" not in html

    # Coverage is 0% even though nine categories are reachable, because owning
    # cards about a topic is not the same as having studied it.
    mastery = crosswalked_collection._backend.topic_mastery(
        section="BB", tag_prefix=TAG_PREFIX
    )
    assert all(topic.covered is False for topic in mastery.topics)
    assert all(topic.review_count == 0 for topic in mastery.topics)


def test_the_collection_panel_never_claims_study_that_never_happened(
    crosswalked_collection,
):
    # The backend returns a topic as soon as a card is attributed to it. On an
    # imported, never-reviewed deck that is every topic the crosswalk reaches,
    # each with zero reviews — so the count beside them is of topics with cards.
    # Calling it history would be the page contradicting its own table.
    html = _dashboard_for(crosswalked_collection)
    assert "Topics with cards" in html
    assert "Topics with history" not in html


def test_the_shipped_crosswalk_reaches_every_bio_biochem_category():
    # The data file is the deliverable. The add-on installs it verbatim, so a
    # category quietly falling out of it would show up as a topic that can never
    # be covered — checked here as well as in Rust, because this is the copy the
    # dashboard is pointed at.
    crosswalk = json.loads(CROSSWALK_PATH.read_text(encoding="utf8"))
    mapped = {entry["topic"] for entry in crosswalk["entries"] if entry.get("topic")}
    assert mapped == {"1A", "1B", "1C", "1D", "2A", "2B", "2C", "3A", "3B"}
    # Refusals are load-bearing and each one carries its reasoning.
    refusals = [entry for entry in crosswalk["entries"] if not entry.get("topic")]
    assert refusals and all(entry["reason"] for entry in refusals)


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


@dataclass
class FakeMastery:
    topics: list = field(default_factory=list)
    cards_considered: int = 0
    cards_excluded: int = 0
    cards_unmapped: int = 0


def test_the_real_decks_denominator_is_readable_at_a_glance():
    # The numbers the MileDown deck actually produces. Four digits run together
    # are the difference between a count that is present and a count that is
    # read, so they are grouped — which is typography, not arithmetic.
    html = render.render_section(
        "Bio/Biochem",
        FakeSection(cards_unmapped=1790),
        FakeMastery(cards_considered=1098),
    )
    assert "1,790 cards Unmapped" in html
    assert "1,098 mapped to Bio/Biochem" in html
    # No ratio, no percentage, no total: this file did not do the subtraction
    # that would turn two backend counts into a third number.
    assert "2,888" not in html and "2888" not in html
    assert "62%" not in html and "38%" not in html


def test_a_section_with_no_mastery_response_still_prints_its_unmapped_count():
    # The unmapped count comes off the score response and is never conditional
    # on anything. Losing the mastery read must cost the mapped count only.
    html = render.render_section("Chem/Phys", FakeSection(cards_unmapped=1790))
    assert "1,790 cards Unmapped" in html
    assert "mapped to Chem/Phys" not in html


def test_the_topic_breakdown_can_be_turned_off_and_the_counts_cannot():
    mastery = FakeMastery(cards_considered=1098, topics=[_topic("mcat::BB::1A")])
    with_table = render.render_section(
        "Bio/Biochem", FakeSection(cards_unmapped=1790), mastery, True
    )
    without = render.render_section(
        "Bio/Biochem", FakeSection(cards_unmapped=1790), mastery, False
    )
    assert "mcat::BB::1A" in with_table
    assert "mcat::BB::1A" not in without
    for html in (with_table, without):
        assert "1,790 cards Unmapped" in html
        assert "1,098 mapped to Bio/Biochem" in html


@dataclass
class FakeTopic:
    topic_id: str = ""
    mean_retrievability: float = 0.0
    range_low: float = 0.0
    range_high: float = 0.0
    card_count: int = 0
    cards_with_memory_state: int = 0
    review_count: int = 0
    covered: bool = False


def _topic(topic_id: str) -> FakeTopic:
    return FakeTopic(topic_id=topic_id)


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
