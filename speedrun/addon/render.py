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
</style>
"""


def _esc(value: Any) -> str:
    return html.escape(str(value))


def _num(value: float) -> str:
    """A backend float, printed. Two decimals, no rescaling of any kind."""
    return f"{value:.2f}"


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


def render_section(name: str, scores: Any, topics: Any = ()) -> str:
    """One exam section: three scores, its evidence, and its denominator."""
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
            # Always shown, including when it is zero. The count is the stated
            # denominator of every mastery figure above it.
            _evidence_item("Unmapped cards", scores.cards_unmapped),
        ]
    )
    return (
        '<div class="panel">'
        f"<h2>{_esc(name)}</h2>"
        f'<p class="sub">Section {_esc(scores.section)}</p>'
        f'<div class="scores">{boxes}</div>'
        f'<div class="evidence">{evidence}</div>'
        f"{_topic_rows(topics)}"
        "</div>"
    )


def _collection_panel(mastery: Any) -> str:
    """What the whole collection looks like before any section is scored."""
    evidence = "".join(
        [
            _evidence_item("Cards considered", mastery.cards_considered),
            _evidence_item("Cards unmapped", mastery.cards_unmapped),
            _evidence_item("Speedrun's own cards excluded", mastery.cards_excluded),
            _evidence_item("Topics with history", len(mastery.topics)),
        ]
    )
    return (
        '<div class="panel">'
        "<h2>Your collection</h2>"
        '<p class="sub">Read, never written to. These are the denominators every '
        "score below is taken over.</p>"
        f'<div class="evidence">{evidence}</div>'
        "</div>"
    )


def _computed_at(computed_at_ms: int) -> str:
    if not computed_at_ms:
        return ""
    stamp = datetime.fromtimestamp(computed_at_ms / 1000)
    return f"Computed {stamp:%Y-%m-%d %H:%M}."


def render_dashboard(sections: list[tuple[str, Any, Any]], mastery: Any) -> str:
    """The whole page.

    ``sections`` is ``[(display name, SectionScoresResponse, [TopicMastery])]``
    in the order they should appear. ``mastery`` is a collection-wide
    ``TopicMasteryResponse``.
    """
    panels = "".join(
        render_section(name, scores, topics) for name, scores, topics in sections
    )
    stamps = [
        s.computed_at_ms for _, s, _ in sections if getattr(s, "computed_at_ms", 0)
    ]
    computed = _computed_at(max(stamps)) if stamps else ""
    return (
        STYLE
        + '<div class="speedrun">'
        + "<h1>Speedrun</h1>"
        + '<p class="lede">Three scores per section, never blended. Every one of them '
        + "starts abstaining and stays that way until your review history clears the "
        + "give-up rule — which is enforced in the engine, where no screen can talk past "
        + "it. This page renders what the engine returned and computes nothing itself.</p>"
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
