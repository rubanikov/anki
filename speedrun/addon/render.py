# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""HTML for the dashboard.

**This module computes nothing.** Every number it prints arrives from
``SpeedrunService`` already decided: the estimate, both ends of the range, the
coverage percentage, the counts, and — when a score is withheld — the sentence
saying what would resolve it. There is no threshold comparison here, no
averaging, no unit conversion, not even a multiply by a hundred. The scores
live in Rust so that Android reproduces them offline byte for byte; arithmetic
in this file would fork that logic into two places obliged to agree forever.

The one thing it does decide is *layout*, and the layout has an opinion:
abstention is a result, not an error. An abstaining score gets the same box, the
same weight, and the same prominence as an available one — it just prints the
reason where the number would go. And the unmapped card count is on screen, in
every section, whether or not it is zero. A mastery figure whose denominator is
hidden is the exact thing this product exists to replace, so the denominator is
never behind a disclosure triangle.

That last point is why the unmapped count is not only *present* but *first*. On
the real deck this was built against, 1,790 of 2,888 cards are Unmapped and
1,098 are mapped — so a reader who saw "Bio/Biochem" and a number, with the
count tucked into a footer, would have read a figure about 38% of their
collection as though it were a figure about their collection. The counts are
therefore printed above the scores, at a size you cannot skim past, in every
section and in the collection panel.

The only string work that touches a number is the thousands separator, which is
typography rather than arithmetic: 1790 and 1,790 are the same value, and a
four-digit count that has to be read at a glance is the entire reason it is up
there.

Everything here duck-types the protobuf messages, so the renderer can be tested
against plain stand-ins without an open collection.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

CONFIDENCE_LABELS = {0: "", 1: "Low", 2: "Medium", 3: "High"}

SCORE_BLURBS = {
    "Memory": "How likely you are to recall a fact right now, from your own review history.",
    "Performance": "How well you answer exam-style questions you have never seen, with no cue.",
    "Readiness": "The scaled section score you would plausibly earn today.",
}

ABSTAINING = "Abstaining"

#: Collection config key a generated demo profile carries. Written by
#: ``speedrun/eval/demo/make_demo_history.py``; read here and nowhere else.
DEMO_CONFIG_KEY = "speedrunSyntheticDemo"

#: The sentence that has to be readable in any screenshot of this page.
#:
#: A demo profile's review history is generated, and that is defensible exactly
#: and only while it is disclosed — so the disclosure is not a footnote, not a
#: tooltip and not a colour: it is the first thing on the page, above the title,
#: and it sticks to the top of the viewport so that a screenshot of any part of
#: the page contains it. The last sentence points at the real evidence, because
#: "this measures nothing" invites the question of what does.
DEMO_BANNER_HEADLINE = "DEMO DATA — NOT A MEASUREMENT"
#: Deliberately apostrophe-free. It is printed through ``html.escape``, and a
#: warning whose text on screen differs from the constant in this file is one
#: nobody can grep for.
DEMO_BANNER_BODY = (
    "The review history in this collection was generated, not studied. "
    "The scores below illustrate the interface and measure nothing."
)
DEMO_BANNER_EVIDENCE = (
    "Calibration evidence for the Memory model is in speedrun/eval/calibration/, "
    "measured on 2.3M real reviews."
)

#: Printed under every unmapped count, so the number is never a bare figure
#: whose meaning the reader has to guess at.
UNMAPPED_NOTE = (
    "In your collection, and in none of the scores here. Speedrun could not "
    "place these cards under an Outline topic, and counts them rather than "
    "dropping them."
)

STYLE = """
<style>
.speedrun { max-width: 60rem; margin: 0 auto; padding: 1rem 1.25rem 3rem; text-align: left; }
.speedrun h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
.speedrun .lede { opacity: .75; margin: 0 0 1.5rem; font-size: .85rem; line-height: 1.5; }
.speedrun .panel {
    border: 1px solid var(--border, #ccc);
    border-radius: var(--border-radius, 6px);
    padding: .9rem 1.1rem; margin-bottom: 1.25rem;
}
.speedrun .panel > h2 { font-size: 1.05rem; margin: 0 0 .1rem; }
.speedrun .panel > .sub { font-size: .8rem; opacity: .7; margin: 0 0 .9rem; }
.speedrun .scores { display: grid; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); gap: .75rem; }
.speedrun .score {
    border: 1px solid var(--border-subtle, #e0e0e0);
    border-radius: var(--border-radius, 6px);
    padding: .7rem .8rem;
}
.speedrun .score.abstained { border-left: 3px solid var(--border, #999); }
.speedrun .score .name { font-weight: 600; font-size: .8rem; letter-spacing: .04em; text-transform: uppercase; opacity: .8; }
.speedrun .score .blurb { font-size: .72rem; opacity: .6; margin: .15rem 0 .5rem; line-height: 1.4; }
.speedrun .score .estimate { font-size: 1.7rem; font-variant-numeric: tabular-nums; line-height: 1.1; }
.speedrun .score .range { font-size: .8rem; opacity: .75; font-variant-numeric: tabular-nums; }
.speedrun .score .status { font-size: .8rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; opacity: .65; }
.speedrun .score .reason { font-size: .85rem; line-height: 1.45; margin-top: .3rem; }
.speedrun .score ul { margin: .4rem 0 0; padding-left: 1.1rem; font-size: .75rem; opacity: .7; }
.speedrun .evidence { display: flex; flex-wrap: wrap; gap: .5rem 1.75rem; margin-top: .9rem;
    padding-top: .75rem; border-top: 1px solid var(--border-subtle, #e0e0e0); }
.speedrun .evidence .item { font-size: .8rem; }
.speedrun .evidence .item .k { display: block; opacity: .6; font-size: .7rem;
    text-transform: uppercase; letter-spacing: .04em; }
.speedrun .evidence .item .v { font-variant-numeric: tabular-nums; font-size: 1rem; }
.speedrun table { width: 100%; border-collapse: collapse; margin-top: .9rem; font-size: .8rem; }
.speedrun th, .speedrun td { text-align: left; padding: .3rem .5rem; border-bottom: 1px solid var(--border-subtle, #eee); }
.speedrun th { font-weight: 600; opacity: .7; font-size: .7rem; text-transform: uppercase; letter-spacing: .04em; }
.speedrun td.num { text-align: right; font-variant-numeric: tabular-nums; }
.speedrun .foot { font-size: .75rem; opacity: .6; line-height: 1.55; margin-top: 1.5rem; }
.speedrun .empty { font-size: .8rem; opacity: .6; margin-top: .75rem; }
.speedrun .coach-status { font-size: .8rem; opacity: .7; margin: 0 0 1.25rem; line-height: 1.5; }
.speedrun .denominator {
    border-left: 3px solid var(--fg-subtle, #8a8a8a);
    background: var(--canvas-inset, rgba(128, 128, 128, .09));
    border-radius: var(--border-radius, 6px);
    padding: .6rem .85rem; margin: 0 0 .95rem;
}
.speedrun .denominator .figures { margin: 0; display: flex; flex-wrap: wrap;
    gap: .2rem 1.5rem; align-items: baseline; }
.speedrun .denominator .figures .unmapped { font-size: 1.2rem; font-weight: 700;
    font-variant-numeric: tabular-nums; line-height: 1.25; }
.speedrun .denominator .figures .mapped { font-size: .9rem; opacity: .75;
    font-variant-numeric: tabular-nums; }
.speedrun .denominator .note { margin: .35rem 0 0; font-size: .75rem; opacity: .7;
    line-height: 1.45; }
.speedrun .demo-banner {
    position: sticky; top: 0; z-index: 10;
    background: #b3261e; color: #fff;
    border: 2px solid #7f1710; border-radius: var(--border-radius, 6px);
    padding: .8rem 1rem; margin: 0 0 1.25rem;
    box-shadow: 0 2px 10px rgba(0, 0, 0, .35);
}
.speedrun .demo-banner .headline { font-size: 1.05rem; font-weight: 800;
    letter-spacing: .06em; text-transform: uppercase; margin: 0 0 .3rem; }
.speedrun .demo-banner p { margin: 0 0 .25rem; font-size: .9rem; line-height: 1.45; }
.speedrun .demo-banner .evidence-note { opacity: .92; }
.speedrun .demo-banner .provenance { margin: .35rem 0 0; font-size: .75rem;
    opacity: .85; font-variant-numeric: tabular-nums; }
</style>
"""


def _esc(value: Any) -> str:
    return html.escape(str(value))


def _num(value: float) -> str:
    """A backend float, printed. Two decimals, no rescaling of any kind."""
    return f"{value:.2f}"


def _count(value: Any) -> str:
    """A backend integer, grouped for reading. Not a computation — 1790 and
    1,790 are the same number, and this one has to survive being skimmed."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return _esc(value)


def _score_html(name: str, score: Any) -> str:
    """One score box, available or abstaining, same shape either way."""
    blurb = SCORE_BLURBS.get(name, "")
    head = f'<div class="name">{_esc(name)}</div><div class="blurb">{_esc(blurb)}</div>'

    if not getattr(score, "available", False):
        # The abstention *is* the result. It prints where the number would be,
        # in the same box, and it always carries the backend's own sentence
        # naming what would resolve it.
        reason = getattr(score, "abstain_reason", "") or (
            "The give-up rule has not been met, and no reason was supplied."
        )
        return (
            '<div class="score abstained">'
            + head
            + f'<div class="status">{ABSTAINING}</div>'
            + f'<div class="reason">{_esc(reason)}</div>'
            + "</div>"
        )

    confidence = CONFIDENCE_LABELS.get(getattr(score, "confidence", 0), "")
    parts = [
        '<div class="score">',
        head,
        f'<div class="estimate">{_num(score.estimate)}</div>',
        f'<div class="range">Range {_num(score.range_low)} – {_num(score.range_high)}</div>',
    ]
    if confidence:
        parts.append(f'<div class="range">Confidence: {_esc(confidence)}</div>')
    reasons = list(getattr(score, "reasons", []) or [])
    if reasons:
        parts.append("<ul>" + "".join(f"<li>{_esc(r)}</li>" for r in reasons) + "</ul>")
    parts.append("</div>")
    return "".join(parts)


def _evidence_item(key: str, value: Any) -> str:
    return (
        f'<div class="item"><span class="k">{_esc(key)}</span>'
        f'<span class="v">{_esc(value)}</span></div>'
    )


def _denominator(unmapped: Any, mapped: Any, mapped_label: str) -> str:
    """The unmapped count, printed where it cannot be missed.

    Both figures come from the backend — ``cards_unmapped`` off the score
    response, ``cards_considered`` off the mastery response — and neither is
    combined with the other here. They sit side by side because the comparison
    is the point, and doing the comparison for the reader would mean this file
    computing a ratio.
    """
    figures = [f'<span class="unmapped">{_count(unmapped)} cards Unmapped</span>']
    if mapped is not None:
        figures.append(
            f'<span class="mapped">{_count(mapped)} mapped to {_esc(mapped_label)}</span>'
        )
    return (
        '<div class="denominator">'
        f'<p class="figures">{"".join(figures)}</p>'
        f'<p class="note">{_esc(UNMAPPED_NOTE)}</p>'
        "</div>"
    )


def _topic_rows(topics: Any) -> str:
    rows = []
    for topic in topics:
        rows.append(
            "<tr>"
            f"<td>{_esc(topic.topic_id)}</td>"
            f'<td class="num">{_num(topic.mean_retrievability)}</td>'
            f'<td class="num">{_num(topic.range_low)} – {_num(topic.range_high)}</td>'
            f'<td class="num">{_esc(topic.card_count)}</td>'
            f'<td class="num">{_esc(topic.cards_with_memory_state)}</td>'
            f'<td class="num">{_esc(topic.review_count)}</td>'
            f"<td>{'covered' if topic.covered else 'not covered'}</td>"
            "</tr>"
        )
    if not rows:
        return ""
    return (
        "<table><thead><tr>"
        "<th>Topic</th><th>Memory</th><th>Range</th><th>Cards</th>"
        "<th>With memory state</th><th>Reviews</th><th>Coverage</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def render_section(
    name: str, scores: Any, mastery: Any = None, show_topics: bool = True
) -> str:
    """One exam section: its denominator, three scores, and its evidence.

    ``mastery`` is the section's ``TopicMasteryResponse``. It supplies the count
    of cards actually mapped into this section and the per-Topic rows; without
    one, the section still prints its unmapped count, because that number comes
    off the score response and is never optional.
    """
    mapped = getattr(mastery, "cards_considered", None) if mastery is not None else None
    topics = (
        getattr(mastery, "topics", ()) if (mastery is not None and show_topics) else ()
    )
    boxes = "".join(
        [
            _score_html("Memory", scores.memory),
            _score_html("Performance", scores.performance),
            _score_html("Readiness", scores.readiness),
        ]
    )
    evidence = "".join(
        [
            # coverage_pct arrives as a percentage. The backend named it, and
            # scaled it; we print it and add the sign.
            _evidence_item("Coverage", f"{scores.coverage_pct:.0f}%"),
            _evidence_item("Graded reviews", scores.graded_reviews),
            _evidence_item("Held-out attempts", scores.holdout_attempts),
            _evidence_item("Topics attempted", scores.topics_attempted),
            # Repeated from the banner at the top of the panel, and repeated on
            # purpose: the evidence row is the list of everything the scores
            # were taken over, and the number they were *not* taken over belongs
            # in it. Always shown, including when it is zero.
            _evidence_item("Unmapped cards", _count(scores.cards_unmapped)),
        ]
    )
    return (
        '<div class="panel">'
        f"<h2>{_esc(name)}</h2>"
        f'<p class="sub">Section {_esc(scores.section)}</p>'
        f"{_denominator(scores.cards_unmapped, mapped, name)}"
        f'<div class="scores">{boxes}</div>'
        f'<div class="evidence">{evidence}</div>'
        f"{_topic_rows(topics)}"
        "</div>"
    )


def _collection_panel(mastery: Any) -> str:
    """What the whole collection looks like before any section is scored."""
    evidence = "".join(
        [
            _evidence_item("Cards considered", _count(mastery.cards_considered)),
            _evidence_item("Cards unmapped", _count(mastery.cards_unmapped)),
            _evidence_item(
                "Speedrun's own cards excluded", _count(mastery.cards_excluded)
            ),
            # "with cards", not "with history". The backend returns a topic as
            # soon as a card is attributed to it, reviewed or not — and on a
            # freshly imported deck that is all nine of them, every one with a
            # review count of zero. Labelling that "with history" would put a
            # claim about study on screen that the numbers beside it deny.
            _evidence_item("Topics with cards", _count(len(mastery.topics))),
        ]
    )
    return (
        '<div class="panel">'
        "<h2>Your collection</h2>"
        '<p class="sub">Read, never written to. These are the denominators every '
        "score below is taken over.</p>"
        + _denominator(
            mastery.cards_unmapped, mastery.cards_considered, "an Outline topic"
        )
        + f'<div class="evidence">{evidence}</div>'
        "</div>"
    )


def _computed_at(computed_at_ms: int) -> str:
    if not computed_at_ms:
        return ""
    stamp = datetime.fromtimestamp(computed_at_ms / 1000)
    return f"Computed {stamp:%Y-%m-%d %H:%M}."


def _coach_status_html(status: str) -> str:
    """One line saying whether the coach is running, and why not if it isn't.

    Deliberately not styled as a warning. The coach being off is a supported
    configuration and a whole arm of the ablation; dressing it as a fault would
    make a working state look broken, and every number on this page is produced
    without it.
    """
    if not status:
        return ""
    return f'<p class="coach-status">{_esc(status)}</p>'


def render_demo_banner(marker: Any) -> str:
    """The synthetic-data warning, or nothing at all.

    ``marker`` is whatever sits in collection config under ``DEMO_CONFIG_KEY``
    — normally the dict ``make_demo_history.py`` wrote, carrying the seed and
    the generation time. Anything truthy raises the banner: a profile that says
    it is generated is taken at its word, because the failure mode of guessing
    wrong in that direction is a warning on a real collection, and the failure
    mode of guessing wrong the other way is a fabricated score presented as a
    measurement.

    The seed and timestamp are printed when they are there, so the reader can
    reproduce the fixture instead of taking this file's word for it. They are
    the only thing about the banner that varies; the warning itself is fixed
    text and cannot be softened by whatever wrote the config key.
    """
    if not marker:
        return ""
    provenance = ""
    if isinstance(marker, dict):
        bits = []
        if marker.get("seed") is not None:
            bits.append(f"seed {_esc(marker['seed'])}")
        if marker.get("generated_at"):
            bits.append(f"generated {_esc(marker['generated_at'])}")
        if marker.get("generator"):
            bits.append(_esc(marker["generator"]))
        if bits:
            provenance = f'<p class="provenance">{" · ".join(bits)}</p>'
    return (
        '<div class="demo-banner" role="alert">'
        f'<p class="headline">{_esc(DEMO_BANNER_HEADLINE)}</p>'
        f"<p>{_esc(DEMO_BANNER_BODY)}</p>"
        f'<p class="evidence-note">{_esc(DEMO_BANNER_EVIDENCE)}</p>'
        f"{provenance}"
        "</div>"
    )


def render_dashboard(
    sections: list[tuple[str, Any, Any]],
    mastery: Any,
    coach_status: str = "",
    show_topics: bool = True,
    demo_marker: Any = None,
) -> str:
    """The whole page.

    ``sections`` is ``[(display name, SectionScoresResponse,
    TopicMasteryResponse)]`` in the order they should appear. ``mastery`` is a
    collection-wide ``TopicMasteryResponse``.

    ``coach_status`` is one sentence from ``switches.Switches.status``. It is the
    *only* thing on this page an off switch can change: every score, range,
    coverage figure and abstention below is computed by the engine, which is
    never told what the switches say.

    ``demo_marker`` is the collection's ``speedrunSyntheticDemo`` config value,
    or ``None`` on any normal collection. When it is present every number below
    was computed from generated review history, and the banner saying so goes
    above the title — see ``render_demo_banner``.
    """
    panels = "".join(
        render_section(name, scores, section_mastery, show_topics)
        for name, scores, section_mastery in sections
    )
    stamps = [
        s.computed_at_ms for _, s, _ in sections if getattr(s, "computed_at_ms", 0)
    ]
    computed = _computed_at(max(stamps)) if stamps else ""
    return (
        STYLE
        + '<div class="speedrun">'
        # Above the title, before any number, and sticky — a disclosure a reader
        # can scroll past is not a disclosure.
        + render_demo_banner(demo_marker)
        + "<h1>Speedrun</h1>"
        + '<p class="lede">Three scores per section, never blended. Every one of them '
        + "starts abstaining and stays that way until your review history clears the "
        + "give-up rule — which is enforced in the engine, where no screen can talk past "
        + "it. This page renders what the engine returned and computes nothing itself.</p>"
        + _coach_status_html(coach_status)
        + _collection_panel(mastery)
        + panels
        + f'<p class="foot">{_esc(computed)} Scores, ranges, coverage and the give-up rule '
        + "are computed by the Speedrun backend, so your phone and this window cannot "
        + "disagree about whether you are ready. Speedrun reads your collection and never "
        + "writes to it.</p>"
        + "</div>"
    )


def render_error(message: str) -> str:
    """A backend call that failed. Distinct from an abstention on purpose."""
    return (
        STYLE
        + '<div class="speedrun"><h1>Speedrun</h1>'
        + '<div class="panel"><h2>Could not read the collection</h2>'
        + f'<p class="sub">{_esc(message)}</p>'
        + '<p class="empty">This is a failure to measure, not a measurement. '
        + "It is shown differently from an abstention because it means something "
        + "different.</p></div></div>"
    )
