#!/usr/bin/env python3
"""Generate SYNTHETIC review history for the demo, and label it so loudly that
nobody can mistake it for a measurement.

Why this exists
---------------
The dashboard's whole argument is the contrast between a section that has
cleared the give-up rule and sections that have not: Bio/Biochem reporting a
Memory score with a range while Chem/Phys and Psych/Soc go on abstaining and
naming their shortfall. Producing that screen honestly needs a human to study
MileDown's deck for an hour, and there is no hour left before the deadline.

So the history is generated. That is legitimate *exactly and only* to the extent
that it is disclosed, so this script does three things at once:

1. writes plausible review history for Bio/Biochem cards only,
2. writes ``speedrunSyntheticDemo`` into collection config, carrying the seed
   and the generation time, and
3. leaves the dashboard no choice but to print a banner saying so — the add-on
   reads that config key and renders the warning above every number on the page
   (``speedrun/addon/render.py``).

**No number computed from this collection is evidence of anything.** The real
evidence for the Memory model is `speedrun/eval/calibration/`, measured on 2.3
million *real* held-back reviews. This fixture never feeds it, never appears in
it, and must never be cited beside it. See `README.md` next to this file.

What is and is not touched
--------------------------
* Bio/Biochem cards only — the ones the shipped crosswalk maps into BB. Chem/Phys
  and Psych/Soc are left exactly as imported, with no reviews at all, so they
  keep abstaining. That contrast is the product's argument and it would be
  destroyed by reviewing everything.
* **No note is modified.** No tag is added, no field edited. The mapped and
  unmapped counts on screen stay the deck's real 1,098 / 1,790, so the only
  fabricated thing in the profile is the review log.
* The real ``.apkg`` is read, never written.
* Everything lands in a throwaway ``ANKI_BASE`` given by ``--base``, which has no
  default on purpose. Nothing is written to a real profile or to any profile
  another test uses.

Memory state is computed by Anki itself
---------------------------------------
FSRS is switched on through ``update_deck_configs``, which makes Anki derive
memory state from the generated revlog. Writing ``s``/``d`` into the card ``data``
column by hand would produce a screen that agrees with nothing: ``mastery.rs``
only accumulates retrievability for cards that have memory state, and
``BoolKey::Fsrs`` defaults to false, so without this step Memory abstains no
matter how many reviews exist.

Usage
-----
    python speedrun/eval/demo/make_demo_history.py \
        --base /path/to/throwaway --seed 20260802 \
        --stats-out speedrun/eval/demo/demo_stats.json

Then link the add-on into that base (``speedrun/addon/install.py --base …``) and
open Tools → Speedrun Dashboard.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEEDRUN = HERE.parents[1]

#: The label that has to survive into anything anyone looks at later. The
#: dashboard keys its banner off this exact string.
DEMO_CONFIG_KEY = "speedrunSyntheticDemo"

DEMO_WARNING = (
    "DEMO DATA — NOT A MEASUREMENT. The review history in this collection was "
    "generated, not studied. The scores it produces illustrate the interface and "
    "measure nothing. Calibration evidence for the Memory model is in "
    "speedrun/eval/calibration/, measured on 2.3M real reviews."
)

DEFAULT_SEED = 20260802
DEFAULT_APKG = SPEEDRUN / "eval" / "deck" / "miledown.apkg"
CROSSWALK_PATH = SPEEDRUN / "crosswalk" / "miledown-bb-v1.json"
CROSSWALK_CONFIG_KEY = "speedrunCrosswalk"

#: The section that reports. Everything else is left untouched so it abstains.
DEMO_SECTION = "BB"

#: The give-up rule, restated here only so this script can *check* it cleared
#: rather than assume. The rule itself lives in
#: rslib/src/speedrun/thresholds.rs and nothing here can talk past it.
MIN_GRADED_REVIEWS = 200
MIN_DISTINCT_CARDS = 30

#: Share of each Bio/Biochem topic's cards that get history, with a floor so
#: that every one of the nine content categories has something in it. A student
#: who had studied only two topics would produce a screen that says so, which is
#: a different (and less useful) demo than one showing the section as a whole.
SAMPLE_FRACTION = 0.12
MIN_CARDS_PER_TOPIC = 4

#: The study window. Roughly ten weeks of intermittent revision — long enough
#: for intervals to grow and for retrievability to have decayed unevenly across
#: topics, which is what makes the per-topic table worth looking at.
FIRST_REVIEW_DAYS_AGO = (70, 6)


# --------------------------------------------------------------------------
# Topic resolution, mirroring rslib/src/speedrun/crosswalk.rs
# --------------------------------------------------------------------------
#
# The backend resolves topics at read time and never writes a tag. This script
# has to know which cards are Bio/Biochem *before* the backend runs, so it
# reimplements the same two rules — tags first, deck path only as a filter;
# first matching entry wins — and then checks its answer against the backend
# afterwards (`verify`), so a drift between the two shows up as a failure
# rather than as a quietly wrong fixture.


def tag_in_namespace(namespace: str, tag: str) -> bool:
    """True if ``tag`` is ``namespace`` or sits beneath it."""
    if not namespace:
        return False
    head, rest = tag[: len(namespace)], tag[len(namespace) :]
    if head.lower() != namespace.lower():
        return False
    return rest == "" or rest.startswith("::")


def topic_from_tags(tags: list[str], prefix: str) -> tuple[str, str] | None:
    """A topic the note names itself, e.g. ``mcat::BB::1A``. MileDown's deck has
    none — this is here because the backend checks it first and a fixture that
    skipped the check would be resolving a different question."""
    for tag in tags:
        parts = tag.split("::")
        if (
            len(parts) >= 3
            and parts[0].lower() == prefix.lower()
            and parts[1]
            and parts[2]
        ):
            return tag, parts[1]
    return None


def resolve(
    entries: list[dict], tags: list[str], deck_path: str, prefix: str
) -> tuple[str, str] | None:
    """``(topic_id, section)`` for one card, or ``None`` for an unmapped card."""
    native = topic_from_tags(tags, prefix)
    if native:
        return native
    for entry in entries:
        decks = entry.get("decks") or []
        if decks and not any(tag_in_namespace(deck, deck_path) for deck in decks):
            continue
        if not any(tag_in_namespace(entry["tag"], tag) for tag in tags):
            continue
        # A refusal stops resolution just as a mapping does: the card is
        # unmapped, and no looser entry further down may claim it.
        topic, section = entry.get("topic"), entry.get("section") or ""
        if not topic or not section:
            return None
        return f"{prefix}::{section}::{topic}", section
    return None


# --------------------------------------------------------------------------
# The generated history
# --------------------------------------------------------------------------


def simulate_card(rng: random.Random, now_secs: int) -> dict:
    """One card's review history for a student revising over ten weeks.

    Not a model of anyone. Intervals grow, some answers are wrong, and the
    resulting rows are shaped like the ones Anki's own FSRS code reads — which
    is all that is required of them, because nothing downstream of here is a
    claim about a person.
    """
    days_ago = rng.randint(FIRST_REVIEW_DAYS_AGO[1], FIRST_REVIEW_DAYS_AGO[0])
    t = now_secs - days_ago * 86400
    ivl = 0
    reps = 0
    lapses = 0
    reviews: list[dict] = []
    target_reps = max(1, min(8, 1 + int(rng.expovariate(1 / 2.6))))

    while reps < target_reps and t < now_secs:
        if reps == 0:
            ease, kind, last_ivl = 3, 0, 0  # learning
            new_ivl = rng.choice([1, 2, 3])
        else:
            roll = rng.random()
            if roll < 0.11:
                ease = 1  # again
            elif roll < 0.28:
                ease = 2  # hard
            elif roll < 0.86:
                ease = 3  # good
            else:
                ease = 4  # easy
            kind, last_ivl = 1, ivl  # review
            if ease == 1:
                lapses += 1
                kind = 2  # relearn
                new_ivl = max(1, int(ivl * 0.4))
            elif ease == 2:
                new_ivl = max(1, int(ivl * 1.2))
            elif ease == 3:
                new_ivl = max(1, int(ivl * rng.uniform(2.0, 2.8)))
            else:
                new_ivl = max(1, int(ivl * rng.uniform(3.0, 4.2)))
        new_ivl = min(new_ivl, 365)
        reviews.append(
            {
                "ms": t * 1000,
                "ease": ease,
                "ivl": new_ivl,
                "last_ivl": last_ivl,
                "type": kind,
                "time": rng.randint(2000, 45000),
            }
        )
        reps += 1
        ivl = new_ivl
        t += max(1, int(new_ivl * 86400 * rng.uniform(0.9, 1.5)))

    last = reviews[-1]
    return {
        "reviews": reviews,
        "reps": reps,
        "lapses": lapses,
        "ivl": last["ivl"],
        "lrt": last["ms"] // 1000,
    }


# --------------------------------------------------------------------------
# Building the profile
# --------------------------------------------------------------------------


def open_collection(base: Path, profile: str, apkg: Path, keep: bool):
    """A throwaway profile with the real deck imported. The `.apkg` is read."""
    os.environ["ANKI_BASE"] = str(base)
    import anki.lang
    from anki.collection import Collection

    anki.lang.set_lang("en_US")

    col_path = base / profile / "collection.anki2"
    col_path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not (keep and col_path.exists())
    if fresh and col_path.exists():
        col_path.unlink()

    col = Collection(str(col_path))
    if fresh:
        from anki.import_export_pb2 import (
            ImportAnkiPackageOptions,
            ImportAnkiPackageRequest,
        )

        if not apkg.exists():
            raise SystemExit(
                f"deck not found: {apkg}\n"
                "It is gitignored (238 MB) — see speedrun/eval/deck/DECK_REPORT.md."
            )
        col.import_anki_package(
            ImportAnkiPackageRequest(
                package_path=str(apkg),
                options=ImportAnkiPackageOptions(
                    merge_notetypes=False,
                    with_scheduling=False,
                    with_deck_configs=False,
                ),
            )
        )
    return col, col_path, fresh


def install_crosswalk(col) -> dict:
    """The shipped crosswalk, passed through whole — extra top-level keys and
    all. Trimming it here would mean the fixture is built against a file nobody
    reviewed."""
    crosswalk = json.loads(CROSSWALK_PATH.read_text(encoding="utf-8"))
    col.set_config(CROSSWALK_CONFIG_KEY, crosswalk)
    return crosswalk


def mark_collection(col, seed: int, generated_at: float) -> dict:
    """The label, in the collection itself.

    The dashboard keys its banner off this, so removing the marker to make the
    screen look cleaner also removes the data's only claim to legitimacy. That
    is the intended coupling.
    """
    marker = {
        "synthetic": True,
        "seed": seed,
        "generated_at": datetime.fromtimestamp(generated_at, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "generated_at_ms": int(generated_at * 1000),
        "generator": "speedrun/eval/demo/make_demo_history.py",
        "section": DEMO_SECTION,
        "purpose": "demo fixture: show what the dashboard looks like when a score exists",
        "warning": DEMO_WARNING,
        "real_evidence": "speedrun/eval/calibration/ — 0.80 predicted vs 79.2% observed on 2.3M real reviews",
    }
    col.set_config(DEMO_CONFIG_KEY, marker)
    return marker


def label_decks(col) -> int:
    """Say it on the deck screen too, before anyone opens the dashboard."""
    labelled = 0
    for deck in col.decks.all_names_and_ids():
        if "::" in deck.name:
            continue
        full = col.decks.get(deck.id)
        if full is None:
            continue
        full["desc"] = (
            "SYNTHETIC DEMO PROFILE. The review history in this collection was "
            "generated by speedrun/eval/demo/make_demo_history.py, not studied. "
            "No score computed from it measures anything."
        )
        col.decks.save(full)
        labelled += 1
    return labelled


def bio_biochem_cards(col, entries: list[dict], prefix: str) -> dict[str, list[int]]:
    """Card ids per Bio/Biochem topic, resolved the way the backend resolves
    them. Cards in other sections, and cards the crosswalk refuses, are simply
    absent — they are what keeps the rest of the dashboard abstaining."""
    deck_names = {d.id: d.name for d in col.decks.all_names_and_ids()}
    rows = col.db.all(
        "select c.id, c.did, c.odid, n.tags from cards c join notes n on n.id = c.nid"
    )
    by_topic: dict[str, list[int]] = {}
    for cid, did, odid, tags in rows:
        deck_path = deck_names.get(odid or did, "")
        resolved = resolve(entries, tags.split(), deck_path, prefix)
        if not resolved:
            continue
        topic_id, section = resolved
        if section.upper() != DEMO_SECTION:
            continue
        by_topic.setdefault(topic_id, []).append(cid)
    for cids in by_topic.values():
        cids.sort()
    return dict(sorted(by_topic.items()))


def write_history(col, rng: random.Random, by_topic: dict[str, list[int]]) -> dict:
    """Insert the revlog rows and bring each reviewed card's counters with them.

    ``mastery.rs`` sums ``card.reps`` for graded reviews, and FSRS derives memory
    state from ``revlog``, so the two have to agree or the screen reports one
    thing and the model another.
    """
    now_secs = int(time.time())
    day_cutoff = col.sched.day_cutoff
    today = col.sched.today

    revlog_rows: list[tuple] = []
    card_rows: list[tuple] = []
    used_ids: set[int] = set()
    per_topic: dict[str, dict[str, int]] = {}

    for topic_id, cids in by_topic.items():
        take = max(MIN_CARDS_PER_TOPIC, round(len(cids) * SAMPLE_FRACTION))
        take = min(take, len(cids))
        chosen = rng.sample(cids, take)
        reviews_here = 0
        for cid in sorted(chosen):
            history = simulate_card(rng, now_secs)
            reviews_here += history["reps"]
            due_secs = history["lrt"] + history["ivl"] * 86400
            due_day = int((due_secs - day_cutoff) // 86400) + today + 1
            card_rows.append(
                (
                    2,  # type: review
                    2,  # queue: review
                    due_day,
                    history["ivl"],
                    2500,
                    history["reps"],
                    history["lapses"],
                    now_secs,
                    json.dumps({"lrt": history["lrt"]}, separators=(",", ":")),
                    cid,
                )
            )
            for r in history["reviews"]:
                rid = r["ms"]
                while rid in used_ids:
                    rid += 1
                used_ids.add(rid)
                revlog_rows.append(
                    (
                        rid,
                        cid,
                        -1,
                        r["ease"],
                        r["ivl"],
                        r["last_ivl"],
                        2500,
                        r["time"],
                        r["type"],
                    )
                )
        per_topic[topic_id] = {
            "cards_in_topic": len(cids),
            "cards_reviewed": take,
            "reviews": reviews_here,
        }

    def insert() -> None:
        col.db.executemany(
            "update cards set type=?, queue=?, due=?, ivl=?, factor=?, reps=?,"
            " lapses=?, mod=?, usn=-1, data=? where id=?",
            card_rows,
        )
        col.db.executemany(
            "insert into revlog (id,cid,usn,ease,ivl,lastIvl,factor,time,type)"
            " values (?,?,?,?,?,?,?,?,?)",
            revlog_rows,
        )

    col.db.transact(insert)
    return {
        "cards_reviewed": len(card_rows),
        "reviews_written": len(revlog_rows),
        "per_topic": per_topic,
    }


def enable_fsrs(col) -> None:
    """Turn FSRS on so Anki derives memory state from the generated revlog.

    Deliberately Anki's own path. ``BoolKey::Fsrs`` defaults to false, and
    ``mastery.rs`` only accumulates retrievability for cards that have memory
    state, so without this the demo's Memory score abstains however many reviews
    exist — and hand-writing ``s``/``d`` into the ``data`` column would mean the
    number on screen came from this script rather than from the model the
    calibration measured.
    """
    from anki import deck_config_pb2

    deck_id = col.decks.all_names_and_ids()[0].id
    for deck in col.decks.all_names_and_ids():
        if deck.name.startswith("MileDown"):
            deck_id = deck.id
            break
    current = col.decks.get_deck_configs_for_update(deck_id)
    req = deck_config_pb2.UpdateDeckConfigsRequest(
        target_deck_id=deck_id,
        configs=[entry.config for entry in current.all_config],
        removed_config_ids=[],
        mode=deck_config_pb2.UpdateDeckConfigsMode.UPDATE_DECK_CONFIGS_MODE_NORMAL,
        card_state_customizer=current.card_state_customizer,
        limits=current.current_deck.limits,
        new_cards_ignore_review_limit=current.new_cards_ignore_review_limit,
        fsrs=True,
        apply_all_parent_limits=current.apply_all_parent_limits,
        fsrs_reschedule=False,
        fsrs_health_check=False,
    )
    col.decks.update_deck_configs(req)


def verify(col, prefix: str) -> dict:
    """Ask the backend what it now sees, through the same two calls the
    dashboard makes.

    The scores are read back so this script can *check the fixture works* — that
    BB clears the rule and that CP and PS still do not. They are labelled
    ``synthetic`` everywhere they are written, and no number here may be
    reported as a measurement of anything.
    """
    outline = {"CP": 10, "BB": 9, "PS": 12, "CARS": 0}
    out: dict = {"synthetic": True, "sections": {}}
    for code, count in outline.items():
        scores = col._backend.section_scores(
            section=code, tag_prefix=prefix, outline_topic_count=count
        )
        mastery = col._backend.topic_mastery(section=code, tag_prefix=prefix)
        out["sections"][code] = {
            "graded_reviews": scores.graded_reviews,
            "cards_mapped": mastery.cards_considered,
            "cards_unmapped": scores.cards_unmapped,
            "cards_with_memory_state": sum(
                t.cards_with_memory_state for t in mastery.topics
            ),
            "coverage_pct": round(scores.coverage_pct, 1),
            "memory_available": scores.memory.available,
            "memory_estimate_SYNTHETIC": round(scores.memory.estimate, 4),
            "memory_range_SYNTHETIC": [
                round(scores.memory.range_low, 4),
                round(scores.memory.range_high, 4),
            ],
            "memory_confidence": scores.memory.confidence,
            "memory_abstain_reason": scores.memory.abstain_reason,
            "performance_abstain_reason": scores.performance.abstain_reason,
            "readiness_abstain_reason": scores.readiness.abstain_reason,
        }
        if code == DEMO_SECTION:
            out["sections"][code]["topics_SYNTHETIC"] = [
                {
                    "topic": t.topic_id,
                    "cards": t.card_count,
                    "with_memory_state": t.cards_with_memory_state,
                    "reviews": t.review_count,
                    "mean_retrievability": round(t.mean_retrievability, 4),
                    "range": [round(t.range_low, 4), round(t.range_high, 4)],
                    "covered": t.covered,
                }
                for t in mastery.topics
            ]
    collection = col._backend.topic_mastery(section="", tag_prefix=prefix)
    out["collection"] = {
        "cards_mapped": collection.cards_considered,
        "cards_unmapped": collection.cards_unmapped,
        "cards_excluded": collection.cards_excluded,
        "topics_with_cards": len(collection.topics),
    }
    return out


def build(args) -> dict:
    base = Path(args.base).resolve()
    base.mkdir(parents=True, exist_ok=True)
    generated_at = time.time()
    rng = random.Random(args.seed)

    col, col_path, fresh = open_collection(
        base, args.profile, Path(args.apkg).resolve(), args.keep
    )
    stats: dict = {
        "synthetic": True,
        "warning": DEMO_WARNING,
        "seed": args.seed,
        "generated_at": datetime.fromtimestamp(generated_at, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "generator": "speedrun/eval/demo/make_demo_history.py",
        "base": str(base),
        "profile": args.profile,
        "deck": str(Path(args.apkg).resolve()),
        "imported": fresh,
    }

    crosswalk = install_crosswalk(col)
    stats["crosswalk"] = crosswalk.get("id", "")
    stats["marker"] = mark_collection(col, args.seed, generated_at)
    stats["decks_labelled"] = label_decks(col)

    stats["notes"] = col.db.scalar("select count() from notes")
    stats["cards"] = col.db.scalar("select count() from cards")
    reviews_before = col.db.scalar("select count() from revlog")
    stats["reviews_before"] = reviews_before

    by_topic = bio_biochem_cards(col, crosswalk["entries"], args.prefix)
    stats["bb_topics_found"] = len(by_topic)
    stats["bb_cards_found"] = sum(len(v) for v in by_topic.values())

    written = write_history(col, rng, by_topic)
    stats.update(written)

    # Reopened so the memory-state pass is not reading a cache warmed by the
    # write above, and so a corrupt write would surface here rather than in the
    # screenshot.
    col.close()
    from anki.collection import Collection

    col = Collection(str(col_path))
    enable_fsrs(col)

    stats["reviews_total"] = col.db.scalar("select count() from revlog")
    stats["cards_with_memory_state"] = col.db.scalar(
        "select count() from cards where data like '%\"s\":%'"
    )
    stats["backend_SYNTHETIC"] = verify(col, args.prefix)
    col.close()

    demo = stats["backend_SYNTHETIC"]["sections"][DEMO_SECTION]
    failures = []
    if demo["graded_reviews"] < MIN_GRADED_REVIEWS:
        failures.append(
            f"{demo['graded_reviews']} graded reviews in {DEMO_SECTION};"
            f" the give-up rule needs {MIN_GRADED_REVIEWS}"
        )
    if written["cards_reviewed"] < MIN_DISTINCT_CARDS:
        failures.append(
            f"{written['cards_reviewed']} cards given history;"
            f" the give-up rule needs {MIN_DISTINCT_CARDS}"
        )
    if not demo["memory_available"]:
        failures.append(f"Memory still abstains: {demo['memory_abstain_reason']}")
    for quiet in ("CP", "PS"):
        section = stats["backend_SYNTHETIC"]["sections"][quiet]
        if section["memory_available"] or section["graded_reviews"]:
            failures.append(
                f"{quiet} was given history and stopped abstaining; the demo's"
                " whole point is the contrast"
            )
    stats["ok"] = not failures
    stats["failures"] = failures
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        required=True,
        help="throwaway ANKI_BASE directory. No default: this must never land "
        "in a real profile or in one another test uses.",
    )
    parser.add_argument("--profile", default="User 1")
    parser.add_argument("--apkg", default=str(DEFAULT_APKG))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--prefix", default="mcat")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="reuse an existing collection in --base instead of reimporting",
    )
    parser.add_argument("--stats-out", default="")
    args = parser.parse_args()

    stats = build(args)
    text = json.dumps(stats, indent=2)
    print(text)
    if args.stats_out:
        Path(args.stats_out).write_text(text + "\n", encoding="utf-8")
    if not stats["ok"]:
        print(
            "\nFIXTURE DID NOT BUILD:", *stats["failures"], sep="\n  ", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
