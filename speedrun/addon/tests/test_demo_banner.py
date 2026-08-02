# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The demo profile has to announce itself.

`speedrun/eval/demo/make_demo_history.py` writes generated review history into a
throwaway profile so the dashboard can be photographed with a Memory score on
it. That is a labelled fixture while the label is on screen and a fabricated
measurement the moment it is not, so the label is tested like any other claim
this page makes:

- it appears whenever the collection carries `speedrunSyntheticDemo`
- it does **not** appear on a collection that does not
- it is above every number, so no screenshot of a score can exclude it
- it names the real evidence, so "measures nothing" does not read as "nothing
  was ever measured"
"""

from __future__ import annotations

from dataclasses import dataclass, field

import render

MARKER = {
    "synthetic": True,
    "seed": 20260802,
    "generated_at": "2026-08-02T12:00:00Z",
    "generator": "speedrun/eval/demo/make_demo_history.py",
}


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


def _dashboard(demo_marker=None) -> str:
    """A page carrying an available Memory score — the only situation where the
    banner is load-bearing, because an abstention cannot be misread as a
    result."""
    section = FakeSection(
        memory=FakeScore(
            available=True,
            estimate=0.87,
            range_low=0.84,
            range_high=0.90,
            confidence=2,
        )
    )
    return render.render_dashboard(
        [("Bio/Biochem", section, FakeMastery(cards_considered=1098))],
        FakeMastery(cards_considered=1098, cards_unmapped=1790),
        "",
        True,
        demo_marker,
    )


def test_a_generated_collection_says_so_above_every_number():
    html = _dashboard(MARKER)

    assert render.DEMO_BANNER_HEADLINE in html
    assert render.DEMO_BANNER_BODY in html

    # Above the title, and therefore above the score, the range and the
    # denominator. A disclosure printed under the number it qualifies has
    # already failed.
    banner = html.index(render.DEMO_BANNER_HEADLINE)
    assert banner < html.index("<h1>Speedrun</h1>")
    assert banner < html.index("0.87")
    assert banner < html.index("Range 0.84")


def test_the_banner_names_the_real_evidence_rather_than_only_denying_this():
    # "Measures nothing" invites the question of what does. The answer is on
    # screen, with the number of real reviews behind it.
    html = _dashboard(MARKER)
    assert "speedrun/eval/calibration/" in html
    assert "2.3M real reviews" in html


def test_the_seed_and_generation_time_are_printed_so_it_can_be_rebuilt():
    html = _dashboard(MARKER)
    assert "seed 20260802" in html
    assert "generated 2026-08-02T12:00:00Z" in html
    assert "speedrun/eval/demo/make_demo_history.py" in html


def test_a_normal_collection_gets_no_banner():
    html = _dashboard(None)
    assert render.DEMO_BANNER_HEADLINE not in html
    assert "DEMO DATA" not in html
    # The stylesheet is shared and always present; what must be absent is the
    # element itself.
    assert '<div class="demo-banner"' not in html
    # And nothing else about the page changed.
    assert "0.87" in html
    assert "<h1>Speedrun</h1>" in html


def test_the_default_is_no_banner_so_it_can_only_appear_deliberately():
    # Every existing caller passes four arguments. The banner may never be a
    # thing that shows up because someone forgot a parameter.
    html = render.render_dashboard([], FakeMastery())
    assert render.DEMO_BANNER_HEADLINE not in html


def test_the_banner_is_keyed_off_the_collection_key_the_generator_writes():
    # The one string tying `make_demo_history.py` to this page. If it drifts,
    # the fixture goes on generating history and the page goes on printing
    # scores with nothing saying where they came from.
    assert render.DEMO_CONFIG_KEY == "speedrunSyntheticDemo"


def test_a_marker_with_no_provenance_still_raises_the_warning():
    # The warning text is fixed and does not come from the config value, so a
    # marker written by hand, or trimmed, cannot soften it.
    html = _dashboard({"synthetic": True})
    assert render.DEMO_BANNER_HEADLINE in html
    assert render.DEMO_BANNER_BODY in html
    assert '<p class="provenance">' not in html


def test_marker_text_is_escaped_before_it_reaches_the_page():
    html = _dashboard(dict(MARKER, generator="<script>alert(1)</script>"))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
