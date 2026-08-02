#!/usr/bin/env python3
"""Measure whether a Memory score of 0.80 is right about 80% of the time.

Reads the bounded corpus slice fetched by `fetch_slice.py`, splits each
collection exactly as `speedrun/eval/holdout/MANIFEST.md` fixed in advance,
predicts every held-back review with the same FSRS formulation the backend uses
(`fsrs_model.py`, a transcription of the crate `rslib/src/speedrun/mastery.rs`
calls), and writes a reliability chart, a Brier score and a log loss — plus a
base-rate baseline, so the numbers can be judged rather than admired.

Stdlib only. No numpy, no matplotlib: the chart is emitted as SVG this file
writes itself, so the artifact is reproducible on a machine with nothing
installed.

What it reproduces from the backend, and where that lives
---------------------------------------------------------
* `.revlog` files are protobuf `anki.stats.Dataset` messages written by
  `Collection::export_dataset` (`rslib/src/scheduler/fsrs/params.rs`), holding
  `RevlogEntry`s ordered by `(cid, id)` plus the collection's `next_day_at`.
* Revlog filtering is `reviews_for_fsrs(..., training=false, ...)` from that
  same file — the path Anki uses to derive the memory state that `mastery.rs`
  reads. That means: cramming entries dropped, history before a card reset
  dropped, entries before the last group of learning steps dropped, and a
  truncated history seeded from SM2 via `memory_state_from_sm2` exactly as
  `fsrs_item_for_memory_state` does (`rslib/src/scheduler/fsrs/memory_state.rs`,
  `historical_retention = 0.9`, the deck-config default).
* `delta_t` is `days_elapsed(previous) - days_elapsed(current)` against the
  collection's own `next_day_at`, the day-boundary arithmetic Anki uses.
* A review is scored when it is not the first review of its card and its
  `delta_t > 0` — the same two conditions FSRS itself requires to form an item.
  Everything else is counted and reported, not silently dropped.

Parameters
----------
FSRS's default parameters (`fsrs 6.6.1 DEFAULT_PARAMETERS`, decay `w[20] =
0.1542`) are used for every collection. Nothing is fitted. That is the model a
student gets before they run "Optimize", and it makes the holdout split
conservative rather than load-bearing: no outcome, held out or not, touches a
parameter. The split is still applied exactly as pre-registered, so the reported
numbers are computed on precisely the pre-declared subset and on nothing else.

Usage
-----
    python speedrun/eval/calibration/calibrate.py
    python speedrun/eval/calibration/calibrate.py --limit 20   # smoke test

Exit codes: 0 ok, 1 the corpus slice is missing or unusable.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fsrs_model import (  # noqa: E402
    DEFAULT_PARAMETERS,
    D_MIN,
    clamp,
    init_difficulty,
    init_stability,
    memory_state_from_sm2,
    power_forgetting_curve,
    self_test,
    step,
)

CALIBRATION_DIR = Path(__file__).resolve().parent
REPO_ROOT = CALIBRATION_DIR.parents[2]  # .../anki
RAW_DIR = REPO_ROOT / "speedrun" / "eval" / "holdout" / "raw" / "revlogs"
H1_PATH = REPO_ROOT / "speedrun" / "eval" / "holdout" / "h1_reviews.jsonl"
RESULTS_PATH = CALIBRATION_DIR / "results.json"
CHART_PATH = CALIBRATION_DIR / "reliability.svg"
SLICE_RECORD = CALIBRATION_DIR / "corpus_slice.json"

W = DEFAULT_PARAMETERS
DECAY = W[20]
HISTORICAL_RETENTION = 0.9  # rslib/src/deckconfig/mod.rs default

HOLDOUT_FRACTION = 0.20  # MANIFEST.md H1 split rule
MIN_REVIEWS_PER_COLLECTION = 5  # MANIFEST.md H1 split rule 4

# RevlogEntry.ReviewKind (proto/anki/stats.proto)
KIND_LEARNING = 0
KIND_FILTERED = 3
KIND_MANUAL = 4

GRID = 1000  # predictions are histogrammed on a 0.001 grid
EPS = 1e-15  # log-loss clamp

# --------------------------------------------------------------------------
# protobuf: anki.stats.Dataset
# --------------------------------------------------------------------------

_MASK64 = (1 << 64) - 1
_SIGN64 = 1 << 63


def _parse_revlog_entry(buf: bytes, i: int, end: int) -> tuple[int, int, int, int, int, int]:
    """One `anki.stats.RevlogEntry` -> (id, cid, button_chosen, interval, ease_factor, kind)."""
    rid = cid = button = ease = kind = 0
    interval = 0
    while i < end:
        key = 0
        shift = 0
        while True:
            b = buf[i]
            i += 1
            key |= (b & 0x7F) << shift
            if b < 0x80:
                break
            shift += 7
        field = key >> 3
        wire = key & 7
        if wire == 0:
            val = 0
            shift = 0
            while True:
                b = buf[i]
                i += 1
                val |= (b & 0x7F) << shift
                if b < 0x80:
                    break
                shift += 7
            if field == 1:
                rid = val
            elif field == 2:
                cid = val
            elif field == 4:
                button = val
            elif field == 5:
                interval = val - (1 << 64) if val >= _SIGN64 else val
            elif field == 7:
                ease = val
            elif field == 9:
                kind = val
        elif wire == 2:
            ln = 0
            shift = 0
            while True:
                b = buf[i]
                i += 1
                ln |= (b & 0x7F) << shift
                if b < 0x80:
                    break
                shift += 7
            i += ln
        elif wire == 5:
            i += 4
        elif wire == 1:
            i += 8
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
    return rid, cid, button, interval, ease, kind


def parse_dataset(buf: bytes) -> tuple[list[tuple[int, int, int, int, int, int]], int]:
    """`anki.stats.Dataset` -> (revlog entries in stored order, next_day_at seconds)."""
    entries: list[tuple[int, int, int, int, int, int]] = []
    next_day_at = 0
    i, n = 0, len(buf)
    while i < n:
        key = 0
        shift = 0
        while True:
            b = buf[i]
            i += 1
            key |= (b & 0x7F) << shift
            if b < 0x80:
                break
            shift += 7
        field = key >> 3
        wire = key & 7
        if wire == 2:
            ln = 0
            shift = 0
            while True:
                b = buf[i]
                i += 1
                ln |= (b & 0x7F) << shift
                if b < 0x80:
                    break
                shift += 7
            if field == 1:
                entries.append(_parse_revlog_entry(buf, i, i + ln))
            i += ln
        elif wire == 0:
            val = 0
            shift = 0
            while True:
                b = buf[i]
                i += 1
                val |= (b & 0x7F) << shift
                if b < 0x80:
                    break
                shift += 7
            if field == 4:
                next_day_at = val - (1 << 64) if val >= _SIGN64 else val
        elif wire == 5:
            i += 4
        elif wire == 1:
            i += 8
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
    return entries, next_day_at


# --------------------------------------------------------------------------
# rslib/src/scheduler/fsrs/params.rs
# --------------------------------------------------------------------------
# entry = (id, cid, button, interval, ease, kind)


def _is_cramming(e: tuple[int, int, int, int, int, int]) -> bool:
    return e[5] == KIND_FILTERED and e[4] == 0


def _is_reset(e: tuple[int, int, int, int, int, int]) -> bool:
    return e[5] == KIND_MANUAL and e[4] == 0


def affects_scheduling(e: tuple[int, int, int, int, int, int]) -> bool:
    """`RevlogEntry::has_rating_and_affects_scheduling`."""
    return e[2] > 0 and not _is_cramming(e)


def _days_elapsed(review_id_ms: int, next_day_at: int) -> int:
    """`RevlogEntry::days_elapsed` — whole days before the collection's day rollover."""
    return max(0, (next_day_at - review_id_ms // 1000) // 86_400)


def reviews_for_fsrs(
    entries: list[tuple[int, int, int, int, int, int]],
) -> tuple[list[tuple[int, int, int, int, int, int]], bool] | None:
    """`reviews_for_fsrs(entries, next_day_at, training=false, ignore_revlogs_before=0)`.

    Returns the surviving entries and `revlogs_complete`, or None if the card
    contributes nothing.
    """
    first_of_last_learn = None
    first_user_grade_idx = None
    revlogs_complete = False
    for index in range(len(entries) - 1, -1, -1):
        e = entries[index]
        if _is_cramming(e):
            continue
        user_graded = e[2] > 0
        interday = e[3] >= 1 or e[3] <= -86_400
        if user_graded and interday:  # within_cutoff is always true: cutoff is 0
            first_user_grade_idx = index
        if user_graded and e[5] == KIND_LEARNING:
            first_of_last_learn = index
            revlogs_complete = True
        elif _is_reset(e):
            if first_of_last_learn is not None:
                revlogs_complete = True
                break
            elif first_user_grade_idx is not None:
                revlogs_complete = False
                break
            else:
                return None
        elif first_of_last_learn is not None:
            break

    if first_of_last_learn is not None:
        entries = entries[first_of_last_learn:]
    elif first_user_grade_idx is not None:
        entries = entries[first_user_grade_idx:]
    else:
        return None

    entries = [e for e in entries if affects_scheduling(e)]
    if not entries:
        return None
    return entries, revlogs_complete


def predictions_for_card(
    entries: list[tuple[int, int, int, int, int, int]], next_day_at: int
) -> list[tuple[int, int, int, int, float, int, bool]]:
    """Every FSRS-predictable review of one card.

    Yields `(review_id, card_id, nth, delta_t, predicted_r, observed, from_sm2)`
    where `observed` is 1 when the user pressed anything but Again.
    """
    got = reviews_for_fsrs(entries)
    if got is None:
        return []
    kept, complete = got

    days = [_days_elapsed(e[0], next_day_at) for e in kept]
    delta_ts = [0] + [days[k - 1] - days[k] for k in range(1, len(kept))]

    out: list[tuple[int, int, int, int, float, int, bool]] = []

    if complete:
        rating = kept[0][2]
        if rating == 0:
            stability, difficulty = 0.001, D_MIN
        else:
            r = int(clamp(rating, 1, 4))
            stability = clamp(init_stability(W, r), 0.001, 36500.0)
            difficulty = clamp(init_difficulty(W, r), D_MIN, 10.0)
        start = 1
        from_sm2 = False
    else:
        first = kept[0]
        ease = (2500 if first[4] == 0 else first[4]) / 1000.0
        state = memory_state_from_sm2(W, ease, float(max(first[3], 1)), HISTORICAL_RETENTION)
        if state is None:
            return []
        stability, difficulty = state
        if ease <= 1.1:
            difficulty = (ease - 0.1) * 9.0 + 1.0
        start = 1
        from_sm2 = True

    for k in range(start, len(kept)):
        rid, cid, rating, _interval, _ease, _kind = kept[k]
        delta_t = delta_ts[k]
        if delta_t > 0:
            p = power_forgetting_curve(W, float(delta_t), stability)
            out.append((rid, cid, k, delta_t, p, 1 if rating >= 2 else 0, from_sm2))
        # nth is the index within the review series the model is stepped over;
        # with an SM2 starting state the first review has already been consumed.
        nth = k if complete else k - 1
        stability, difficulty = step(W, float(delta_t), float(rating), stability, difficulty, nth)

    return out


# --------------------------------------------------------------------------
# accumulation
# --------------------------------------------------------------------------


class Bins:
    """Predictions on a 0.001 grid: enough for any binning without keeping rows."""

    def __init__(self) -> None:
        self.count = [0] * (GRID + 1)
        self.sum_p = [0.0] * (GRID + 1)
        self.sum_y = [0] * (GRID + 1)
        self.n = 0
        self.sum_brier = 0.0
        self.sum_logloss = 0.0
        self.positives = 0

    def add(self, p: float, y: int, d2: float | None = None, ll: float | None = None) -> None:
        """Record one prediction. `d2`/`ll` are passed in when several
        accumulators share the same review, so the logs are taken once."""
        g = int(p * GRID + 0.5)
        if g < 0:
            g = 0
        elif g > GRID:
            g = GRID
        self.count[g] += 1
        self.sum_p[g] += p
        self.sum_y[g] += y
        self.n += 1
        self.positives += y
        if d2 is None:
            d = p - y
            d2 = d * d
        if ll is None:
            q = p if p > EPS else EPS
            q = q if q < 1.0 - EPS else 1.0 - EPS
            ll = -(math.log(q) if y else math.log1p(-q))
        self.sum_brier += d2
        self.sum_logloss += ll

    def auc(self) -> float:
        """Area under the ROC curve, from the 0.001 grid.

        Calibration and discrimination are different questions. A model can
        rank reviews perfectly and still state the wrong probability; this
        separates "the model is miscalibrated" from "the model is not tracking
        anything", which a Brier score alone cannot do.
        """
        pos = self.positives
        neg = self.n - pos
        if not pos or not neg:
            return float("nan")
        area = 0.0
        seen_neg = 0
        for g in range(GRID + 1):
            c = self.count[g]
            if not c:
                continue
            p_g = self.sum_y[g]
            n_g = c - p_g
            area += p_g * (seen_neg + n_g / 2.0)
            seen_neg += n_g
        return area / (pos * neg)

    @property
    def brier(self) -> float:
        return self.sum_brier / self.n if self.n else float("nan")

    @property
    def log_loss(self) -> float:
        return self.sum_logloss / self.n if self.n else float("nan")

    @property
    def base_rate(self) -> float:
        return self.positives / self.n if self.n else float("nan")

    @property
    def mean_predicted(self) -> float:
        return sum(self.sum_p) / self.n if self.n else float("nan")

    def fixed_width(self, width: float = 0.1) -> list[dict]:
        nbins = int(round(1.0 / width))
        rows = []
        for b in range(nbins):
            lo, hi = b * width, (b + 1) * width
            g_lo = int(round(lo * GRID))
            g_hi = GRID if b == nbins - 1 else int(round(hi * GRID)) - 1
            c = sum(self.count[g_lo : g_hi + 1])
            sp = sum(self.sum_p[g_lo : g_hi + 1])
            sy = sum(self.sum_y[g_lo : g_hi + 1])
            rows.append(
                {
                    "low": round(lo, 3),
                    "high": round(hi, 3),
                    "count": c,
                    "mean_predicted": (sp / c) if c else None,
                    "observed": (sy / c) if c else None,
                }
            )
        return rows

    def equal_count(self, nbins: int = 10) -> list[dict]:
        """Bins holding roughly equal numbers of reviews, cut on the 0.001 grid.

        Predicted recall piles up near 1.0, so fixed-width bins leave the
        interesting region in one bucket. These cut by population instead; the
        grid means a bin boundary can only fall on a multiple of 0.001, so the
        counts are approximately, not exactly, equal.
        """
        if not self.n:
            return []
        target = self.n / nbins
        rows: list[dict] = []
        g = 0
        while g <= GRID and len(rows) < nbins:
            g_start = g
            c, sp, sy = 0, 0.0, 0
            last = len(rows) == nbins - 1
            while g <= GRID:
                c += self.count[g]
                sp += self.sum_p[g]
                sy += self.sum_y[g]
                g += 1
                if not last and c >= target:
                    break
            if c:
                rows.append(
                    {
                        "low": round(g_start / GRID, 3),
                        "high": round(min(g, GRID) / GRID, 3),
                        "count": c,
                        "mean_predicted": sp / c,
                        "observed": sy / c,
                    }
                )
        return rows

    def band(self, centre: float, half_width: float = 0.005) -> dict:
        """Observed recall among predictions within ±half_width of `centre`.

        This is the product claim asked directly: of the reviews the model
        called 0.80, how many did the student actually get right?
        """
        g_lo = max(0, int(round((centre - half_width) * GRID)))
        g_hi = min(GRID, int(round((centre + half_width) * GRID)))
        c = sum(self.count[g_lo : g_hi + 1])
        sp = sum(self.sum_p[g_lo : g_hi + 1])
        sy = sum(self.sum_y[g_lo : g_hi + 1])
        if not c:
            return {"centre": centre, "count": 0, "mean_predicted": None, "observed": None}
        # Wilson 95% interval, so a bin's noise is visible next to its number.
        phat = sy / c
        z = 1.959964
        denom = 1 + z * z / c
        centre_adj = (phat + z * z / (2 * c)) / denom
        margin = z * math.sqrt(phat * (1 - phat) / c + z * z / (4 * c * c)) / denom
        return {
            "centre": centre,
            "count": c,
            "mean_predicted": sp / c,
            "observed": phat,
            "wilson_95_low": max(0.0, centre_adj - margin),
            "wilson_95_high": min(1.0, centre_adj + margin),
        }

    def grid_rows(self) -> list[list[float]]:
        """The raw 0.001 histogram: `[predicted, count, sum_predicted, successes]`.

        Committed so anyone can re-bin these results — or disagree with the
        binning — without re-running anything or holding the corpus.
        """
        return [
            [g / GRID, self.count[g], round(self.sum_p[g], 6), self.sum_y[g]]
            for g in range(GRID + 1)
            if self.count[g]
        ]

    def ece(self, rows: list[dict]) -> float:
        if not self.n:
            return float("nan")
        return sum(
            r["count"] / self.n * abs(r["mean_predicted"] - r["observed"])
            for r in rows
            if r["count"]
        )


def constant_baseline(bins: Bins, p: float) -> dict:
    """Brier and log loss for predicting the same number for every review."""
    n, k = bins.n, bins.positives
    if not n:
        return {"prediction": p, "brier": None, "log_loss": None}
    brier = (k * (1 - p) ** 2 + (n - k) * p**2) / n
    q = min(max(p, EPS), 1 - EPS)
    ll = -(k * math.log(q) + (n - k) * math.log1p(-q)) / n
    return {"prediction": p, "brier": brier, "log_loss": ll}


# --------------------------------------------------------------------------
# the chart
# --------------------------------------------------------------------------


def render_svg(rows: list[dict], bins: Bins, baseline: dict, subtitle: str) -> str:
    """A reliability diagram, hand-written so the artifact needs no plotting library."""
    W_PX, H_PX = 720, 620
    L, R, T, B = 78, 40, 92, 190
    pw, ph = W_PX - L - R, H_PX - T - B

    def x(v: float) -> float:
        return L + v * pw

    def y(v: float) -> float:
        return T + (1.0 - v) * ph

    fg, muted, accent, grid = "#1b1f24", "#5b6672", "#0b6bcb", "#dfe3e8"
    parts: list[str] = []
    add = parts.append

    add(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W_PX}" height="{H_PX}" '
        f'viewBox="0 0 {W_PX} {H_PX}" font-family="Inter, Segoe UI, Helvetica, Arial, sans-serif">'
    )
    add(f'<rect width="{W_PX}" height="{H_PX}" fill="#ffffff"/>')
    add(
        f'<text x="{L}" y="34" font-size="19" font-weight="600" fill="{fg}">'
        "Memory calibration: predicted recall vs observed recall</text>"
    )
    add(f'<text x="{L}" y="56" font-size="12.5" fill="{muted}">{subtitle}</text>')
    add(
        f'<text x="{L}" y="74" font-size="12.5" fill="{muted}">'
        f"Brier {bins.brier:.4f} · log loss {bins.log_loss:.4f} · "
        f"base-rate baseline Brier {baseline['brier']:.4f} · "
        f"log loss {baseline['log_loss']:.4f}</text>"
    )

    for i in range(11):
        v = i / 10
        add(
            f'<line x1="{x(v):.1f}" y1="{T}" x2="{x(v):.1f}" y2="{T + ph}" '
            f'stroke="{grid}" stroke-width="1"/>'
        )
        add(
            f'<line x1="{L}" y1="{y(v):.1f}" x2="{L + pw}" y2="{y(v):.1f}" '
            f'stroke="{grid}" stroke-width="1"/>'
        )
        add(
            f'<text x="{x(v):.1f}" y="{T + ph + 18}" font-size="11" fill="{muted}" '
            f'text-anchor="middle">{v:.1f}</text>'
        )
        add(
            f'<text x="{L - 10}" y="{y(v) + 4:.1f}" font-size="11" fill="{muted}" '
            f'text-anchor="end">{v:.1f}</text>'
        )

    add(
        f'<line x1="{x(0)}" y1="{y(0)}" x2="{x(1)}" y2="{y(1)}" stroke="{muted}" '
        'stroke-width="1.4" stroke-dasharray="5 4"/>'
    )
    add(
        f'<text x="{x(0.62):.1f}" y="{y(0.58):.1f}" font-size="11" fill="{muted}" '
        'transform="rotate(-45 ' + f"{x(0.62):.1f} {y(0.58):.1f}" + ')">perfect calibration</text>'
    )

    pts = [r for r in rows if r["count"]]
    if pts:
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{x(r['mean_predicted']):.1f},{y(r['observed']):.1f}"
            for i, r in enumerate(pts)
        )
        add(f'<path d="{path}" fill="none" stroke="{accent}" stroke-width="2.2"/>')
        biggest = max(r["count"] for r in pts)
        for r in pts:
            rad = 3.0 + 7.0 * math.sqrt(r["count"] / biggest)
            add(
                f'<circle cx="{x(r["mean_predicted"]):.1f}" cy="{y(r["observed"]):.1f}" '
                f'r="{rad:.1f}" fill="{accent}" fill-opacity="0.85"/>'
            )

    add(
        f'<text x="{L + pw / 2:.0f}" y="{T + ph + 42}" font-size="12.5" fill="{fg}" '
        'text-anchor="middle">predicted recall (Memory score)</text>'
    )
    add(
        f'<text transform="translate(22 {T + ph / 2:.0f}) rotate(-90)" font-size="12.5" '
        f'fill="{fg}" text-anchor="middle">observed recall</text>'
    )

    # per-bin counts, log-scaled: the point sizes above are suggestive, this is the number
    hy, hh = T + ph + 66, 74
    add(
        f'<text x="{L}" y="{hy - 8}" font-size="12" fill="{fg}">'
        "reviews per bin (log scale)</text>"
    )
    biggest = max((r["count"] for r in rows), default=0)
    if biggest:
        lg = math.log10(biggest + 1)
        bw = pw / len(rows)
        for i, r in enumerate(rows):
            h = 0 if not r["count"] else max(1.0, hh * math.log10(r["count"] + 1) / lg)
            bx = L + i * bw
            add(
                f'<rect x="{bx + 2:.1f}" y="{hy + hh - h:.1f}" width="{bw - 4:.1f}" '
                f'height="{h:.1f}" fill="{accent}" fill-opacity="0.28"/>'
            )
            label = f"{r['count']:,}" if r["count"] else "0"
            add(
                f'<text x="{bx + bw / 2:.1f}" y="{hy + hh + 14:.1f}" font-size="9.5" '
                f'fill="{muted}" text-anchor="middle">{label}</text>'
            )
            add(
                f'<text x="{bx + bw / 2:.1f}" y="{hy + hh + 26:.1f}" font-size="9" '
                f'fill="{muted}" text-anchor="middle">{r["low"]:.1f}–{r["high"]:.1f}</text>'
            )
    add("</svg>")
    return "\n".join(parts)


# --------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="calibrate.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--limit", type=int, default=0, help="score only the first N collections")
    parser.add_argument(
        "--no-h1-file",
        action="store_true",
        help="skip writing h1_reviews.jsonl (smoke tests)",
    )
    args = parser.parse_args(argv)

    print("checking the FSRS port against the crate's own vectors")
    problems = self_test()
    if problems:
        for p in problems:
            print("  FAIL " + p)
        return 1
    print()

    if not RAW_DIR.exists():
        print(
            f"calibrate.py: {RAW_DIR} does not exist. Run fetch_slice.py first. "
            "There is no fallback: simulated reviews are disqualified.",
            file=sys.stderr,
        )
        return 1

    files = sorted(RAW_DIR.glob("*.revlog"), key=lambda p: int(p.stem))
    if args.limit:
        files = files[: args.limit]
    if not files:
        print(f"calibrate.py: no .revlog files under {RAW_DIR}", file=sys.stderr)
        return 1

    h1 = Bins()
    fit = Bins()
    # Same held-out reviews, split by how the card's starting state was derived:
    # full review history, or an SM2 seed because the history was truncated.
    h1_complete = Bins()
    h1_sm2 = Bins()
    by_collection: list[dict] = []
    stats = {
        "collections_seen": 0,
        "collections_scored": 0,
        "collections_too_small": 0,
        "reviews_total": 0,
        "reviews_held_out": 0,
        "held_out_scored": 0,
        "held_out_unscorable": 0,
        "predictions_from_sm2_start": 0,
        "cards_total": 0,
    }

    h1_out = None if args.no_h1_file else H1_PATH.open("w", encoding="utf-8", newline="\n")
    started = time.time()
    try:
        for n_file, path in enumerate(files, 1):
            collection = int(path.stem)
            entries, next_day_at = parse_dataset(path.read_bytes())
            stats["collections_seen"] += 1

            # --- MANIFEST.md H1 split rule -------------------------------
            # 1. group by collection (one file = one collection)
            # 2. sort ascending by review timestamp, ties on (card_id, review_th)
            # 3. the last ceil(0.20 * n) reviews are held out
            # 4. collections with n < 5 contribute nothing
            # 5. deterministic: no sampling, no shuffling, no seed
            graded = [e for e in entries if affects_scheduling(e)]
            reviews = sorted((e[0], e[1]) for e in graded)
            outcome = {(e[0], e[1]): (1 if e[2] >= 2 else 0) for e in graded}
            n = len(reviews)
            stats["reviews_total"] += n
            if n < MIN_REVIEWS_PER_COLLECTION:
                stats["collections_too_small"] += 1
                continue
            held = math.ceil(HOLDOUT_FRACTION * n)
            cut = n - held
            h1_keys = set(reviews[cut:])
            rank = {key: i + 1 for i, key in enumerate(reviews)}
            stats["reviews_held_out"] += held
            stats["collections_scored"] += 1

            # --- per card: reproduce Anki's memory-state derivation -------
            by_card: dict[int, list[tuple[int, int, int, int, int, int]]] = {}
            for e in entries:
                by_card.setdefault(e[1], []).append(e)
            stats["cards_total"] += len(by_card)

            scored_keys: set[tuple[int, int]] = set()
            lines: list[str] = []
            per_collection = Bins()
            for cid, card_entries in by_card.items():
                card_entries.sort(key=lambda e: e[0])
                for rid, card_id, nth, delta_t, p, y, from_sm2 in predictions_for_card(
                    card_entries, next_day_at
                ):
                    key = (rid, card_id)
                    if key in h1_keys:
                        d = p - y
                        d2 = d * d
                        q = p if p > EPS else EPS
                        q = q if q < 1.0 - EPS else 1.0 - EPS
                        ll = -(math.log(q) if y else math.log1p(-q))
                        h1.add(p, y, d2, ll)
                        per_collection.add(p, y, d2, ll)
                        scored_keys.add(key)
                        if from_sm2:
                            stats["predictions_from_sm2_start"] += 1
                            h1_sm2.add(p, y, d2, ll)
                        else:
                            h1_complete.add(p, y, d2, ll)
                        if h1_out is not None:
                            lines.append(
                                '{"c":%d,"cid":%d,"rid":%d,"th":%d,"y":%d,"dt":%d,"n":%d,"s":1}'
                                % (collection, card_id, rid, rank[key], y, delta_t, nth)
                            )
                    else:
                        fit.add(p, y)

            stats["held_out_scored"] += len(scored_keys)
            stats["held_out_unscorable"] += held - len(scored_keys)
            if per_collection.n:
                # Per collection as well as pooled: a pooled number lets the two
                # or three biggest collections speak for the other 297.
                by_collection.append(
                    {
                        "collection": collection,
                        "scored_reviews": per_collection.n,
                        "mean_predicted": per_collection.mean_predicted,
                        "observed": per_collection.base_rate,
                        "brier": per_collection.brier,
                        "log_loss": per_collection.log_loss,
                    }
                )

            if h1_out is not None:
                # Every held-back review lands in H1, so the denominator stays
                # visible: `s` marks the ones FSRS can actually be asked about.
                for key in reviews[cut:]:
                    if key in scored_keys:
                        continue
                    lines.append(
                        '{"c":%d,"cid":%d,"rid":%d,"th":%d,"y":%d,"dt":null,"n":null,"s":0}'
                        % (collection, key[1], key[0], rank[key], outcome[key])
                    )
                h1_out.write("\n".join(lines) + "\n")

            if n_file % 25 == 0 or n_file == len(files):
                el = time.time() - started
                print(
                    f"  {n_file:>4}/{len(files)} collections  "
                    f"{stats['reviews_total']:>10,} reviews  "
                    f"{h1.n:>9,} scored held-out  {el:6.1f}s"
                )
    finally:
        if h1_out is not None:
            h1_out.close()

    if h1.n == 0:
        print("calibrate.py: no held-out review could be scored", file=sys.stderr)
        return 1

    def quantiles(values: list[float]) -> dict:
        vals = sorted(values)
        if not vals:
            return {}

        def q(f: float) -> float:
            i = f * (len(vals) - 1)
            lo = int(math.floor(i))
            hi = min(lo + 1, len(vals) - 1)
            return vals[lo] + (vals[hi] - vals[lo]) * (i - lo)

        return {
            "min": vals[0],
            "p25": q(0.25),
            "median": q(0.5),
            "p75": q(0.75),
            "max": vals[-1],
            "mean": sum(vals) / len(vals),
        }

    fixed = h1.fixed_width(0.1)
    deciles = h1.equal_count(10)
    baseline_fit = constant_baseline(h1, fit.base_rate)
    baseline_h1 = constant_baseline(h1, h1.base_rate)

    subtitle = (
        f"{stats['collections_scored']} collections from anki-revlogs-10k · "
        f"{h1.n:,} held-back reviews · FSRS-6 default parameters"
    )
    CHART_PATH.write_text(render_svg(fixed, h1, baseline_fit, subtitle), encoding="utf-8")

    results = {
        "produced_by": "python speedrun/eval/calibration/calibrate.py",
        "model": {
            "source": "fsrs 6.6.1 (workspace Cargo.toml), via speedrun/eval/calibration/fsrs_model.py",
            "curve": "fsrs::current_retrievability — the call rslib/src/speedrun/mastery.rs makes",
            "parameters": "FSRS-6 DEFAULT_PARAMETERS; nothing fitted",
            "decay": DECAY,
            "historical_retention": HISTORICAL_RETENTION,
        },
        "split": {
            "rule": "speedrun/eval/holdout/MANIFEST.md, H1: last ceil(0.20 x n) reviews per collection",
            "holdout_fraction": HOLDOUT_FRACTION,
            "min_reviews_per_collection": MIN_REVIEWS_PER_COLLECTION,
            "review_population": (
                "revlog entries with a rating that affect scheduling "
                "(RevlogEntry::has_rating_and_affects_scheduling); manual reschedules, "
                "resets and cramming entries are not reviews"
            ),
        },
        "counts": stats,
        "held_out": {
            "scored_reviews": h1.n,
            "mean_predicted_recall": h1.mean_predicted,
            "observed_recall": h1.base_rate,
            "brier": h1.brier,
            "log_loss": h1.log_loss,
            "ece_fixed_width": h1.ece(fixed),
            "ece_equal_count": h1.ece(deciles),
            "auc": h1.auc(),
        },
        "per_collection": {
            "note": (
                "Pooled numbers are dominated by the largest collections. These are "
                "the same metric computed inside each collection, then summarised "
                "across collections — the convention the published FSRS benchmark uses."
            ),
            "collections": len(by_collection),
            "brier": quantiles([c["brier"] for c in by_collection]),
            "log_loss": quantiles([c["log_loss"] for c in by_collection]),
            "observed_recall": quantiles([c["observed"] for c in by_collection]),
            "mean_predicted": quantiles([c["mean_predicted"] for c in by_collection]),
            "rows": by_collection,
        },
        "held_out_by_history": {
            "complete_history": {
                "scored_reviews": h1_complete.n,
                "observed_recall": h1_complete.base_rate,
                "brier": h1_complete.brier,
                "log_loss": h1_complete.log_loss,
            },
            "sm2_seeded_history": {
                "scored_reviews": h1_sm2.n,
                "observed_recall": h1_sm2.base_rate,
                "brier": h1_sm2.brier,
                "log_loss": h1_sm2.log_loss,
            },
        },
        "fitting_set": {
            "scored_reviews": fit.n,
            "observed_recall": fit.base_rate,
            "brier": fit.brier,
            "log_loss": fit.log_loss,
        },
        "baselines": {
            "fitting_set_base_rate": baseline_fit,
            "holdout_base_rate": baseline_h1,
        },
        "claim_check": {
            "question": (
                "Of the held-back reviews the Memory model scored at x, what "
                "fraction did the student actually recall? Bands are x ± 0.005."
            ),
            "bands": [h1.band(c) for c in (0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95)],
        },
        "bins_fixed_width": fixed,
        "bins_equal_count": deciles,
        "grid": {
            "note": (
                "The raw 0.001-wide histogram every table above is derived from: "
                "[predicted, reviews, sum of predictions, reviews recalled]. "
                "Aggregate counts only — no review row, so it carries none of the "
                "corpus licence's redistribution restriction."
            ),
            "rows": h1.grid_rows(),
        },
        "chart": "speedrun/eval/calibration/reliability.svg",
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"held-back reviews scored   {h1.n:,}")
    print(f"mean predicted recall      {h1.mean_predicted:.4f}")
    print(f"observed recall            {h1.base_rate:.4f}")
    print(f"Brier score                {h1.brier:.4f}")
    print(f"log loss                   {h1.log_loss:.4f}")
    print(f"ECE (10 fixed-width bins)  {h1.ece(fixed):.4f}")
    print(f"ECE (10 equal-count bins)  {h1.ece(deciles):.4f}")
    print(f"AUC (discrimination)       {h1.auc():.4f}")
    print(
        f"baseline (fitting base rate {fit.base_rate:.4f})  "
        f"Brier {baseline_fit['brier']:.4f}  log loss {baseline_fit['log_loss']:.4f}"
    )
    print(
        f"baseline (holdout base rate {h1.base_rate:.4f})  "
        f"Brier {baseline_h1['brier']:.4f}  log loss {baseline_h1['log_loss']:.4f}"
    )
    if by_collection:
        qb = quantiles([c["brier"] for c in by_collection])
        ql = quantiles([c["log_loss"] for c in by_collection])
        print(
            f"per collection ({len(by_collection)})  Brier median {qb['median']:.4f} "
            f"[p25 {qb['p25']:.4f}, p75 {qb['p75']:.4f}]  "
            f"log loss median {ql['median']:.4f} [p25 {ql['p25']:.4f}, p75 {ql['p75']:.4f}]"
        )
    if h1_complete.n:
        print(
            f"complete-history subset      n={h1_complete.n:,}  "
            f"Brier {h1_complete.brier:.4f}  log loss {h1_complete.log_loss:.4f}  "
            f"observed {h1_complete.base_rate:.4f}"
        )
    if h1_sm2.n:
        print(
            f"SM2-seeded subset            n={h1_sm2.n:,}  "
            f"Brier {h1_sm2.brier:.4f}  log loss {h1_sm2.log_loss:.4f}  "
            f"observed {h1_sm2.base_rate:.4f}"
        )
    print()
    print("the claim, asked directly — of the reviews scored x, how many came back?")
    print("| Memory score | reviews | mean predicted | observed | Wilson 95% |")
    print("|---|---|---|---|---|")
    for c in (0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95):
        b = h1.band(c)
        if not b["count"]:
            print(f"| {c:.2f} ± 0.005 | 0 | — | — | — |")
            continue
        print(
            f"| {c:.2f} ± 0.005 | {b['count']:,} | {b['mean_predicted']:.4f} | "
            f"{b['observed']:.4f} | {b['wilson_95_low']:.4f}–{b['wilson_95_high']:.4f} |"
        )
    print()
    print("| predicted | mean predicted | observed | reviews |")
    print("|---|---|---|---|")
    for r in fixed:
        if not r["count"]:
            print(f"| {r['low']:.1f}–{r['high']:.1f} | — | — | 0 |")
        else:
            print(
                f"| {r['low']:.1f}–{r['high']:.1f} | {r['mean_predicted']:.4f} | "
                f"{r['observed']:.4f} | {r['count']:,} |"
            )
    print()
    print(f"wrote {RESULTS_PATH}")
    print(f"wrote {CHART_PATH}")
    if not args.no_h1_file:
        print(f"wrote {H1_PATH}  ({H1_PATH.stat().st_size:,} bytes, .gitignore'd)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
