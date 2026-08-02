#!/usr/bin/env python3
"""Build the 50,000-card SYNTHETIC deck the performance bench runs against.

This deck exists to measure *latency only*. Nothing it contains is a
measurement of a person, and no number computed from it may ever be reported as
a Memory, Performance or Readiness score — see the warning below and
`BENCH.md`. It is written to a throwaway `ANKI_BASE`, never to a real profile,
and it is not committed.

Why it has to be this elaborate
-------------------------------
`SectionScores` and `TopicMastery` are only slow if the collection makes them
work. A deck of 50,000 empty cards would be answered almost entirely out of an
empty search result, and the number would flatter us. So the deck carries:

* **Review history.** ~220k `revlog` rows from a seeded simulation, which is
  what gives `reps` a real value and gives FSRS something to derive memory state
  from. `mastery.rs` calls `fsrs::current_retrievability` once per card that has
  memory state; without history that branch never runs.
* **Real FSRS memory state**, computed by Anki itself from the generated revlog
  (`update_deck_configs(fsrs=True)` → `Collection::update_memory_state`), not
  hand-written into the `data` column. That is the difference between measuring
  the real query and measuring a fixture.
* **Tags a crosswalk has to work for.** Four segments: cards carrying native
  `mcat::` topic tags, cards carrying MileDown tags the shipped crosswalk maps,
  cards carrying MileDown tags it deliberately *refuses*, and cards carrying
  labels it has never heard of. The last group is the expensive one — a miss
  scans all 38 entries — and leaving it out would understate the crosswalk.
* **Speedrun's own attempt cards**, so the contamination-guard search
  (`-"note:Speedrun::Attempt"`) and the held-out attempt query have rows to
  find rather than an empty table to skip.

Everything is drawn from `random.Random(SEED)` with the seed recorded in
`BENCH.md` and written into the collection config, so the deck is rebuildable.

Usage
-----
    python speedrun/eval/bench/gen_deck.py --base /path/to/throwaway --cards 50000

Writes `<base>/bench/collection.anki2`.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

# The label that has to survive into anything anyone looks at later.
SYNTHETIC_ROOT = "SYNTHETIC — Speedrun bench (never scored)"
SYNTHETIC_TAG = "speedrun::synthetic::bench"
SYNTHETIC_CONFIG_KEY = "speedrunSyntheticBench"

DEFAULT_SEED = 20260802

ATTEMPT_NOTETYPE = "Speedrun::Attempt"
HOLDOUT_TAG = "speedrun::holdout"

# AAMC content categories per section, from rslib/src/speedrun/thresholds.rs.
OUTLINE = {
    "BB": ["1A", "1B", "1C", "1D", "2A", "2B", "2C", "3A", "3B"],
    "CP": ["4A", "4B", "4C", "4D", "4E", "5A", "5B", "5C", "5D", "5E"],
    "PS": ["6A", "6B", "6C", "7A", "7B", "7C", "8A", "8B", "8C", "9A", "9B", "10A"],
}

# Labels the Bio/Biochem crosswalk has never heard of. Chem/Phys and Psych/Soc
# are cut #3, so a real collection is full of these and every one of them costs
# a full 38-entry scan before it is counted unmapped.
UNMAPPED_TAGS = [
    "MileDown::Chemistry::Acids_and_Bases",
    "MileDown::Chemistry::Electrochemistry",
    "MileDown::Chemistry::Thermodynamics",
    "MileDown::Chemistry::Solutions",
    "MileDown::Chemistry::Periodic_Table",
    "MileDown::OChem::Spectroscopy",
    "MileDown::OChem::Carboxylic_Acids",
    "MileDown::OChem::Separations",
    "MileDown::Physics::Circuits",
    "MileDown::Physics::Optics",
    "MileDown::Physics::Fluids",
    "MileDown::Physics::Waves_and_Sound",
    "MileDown::Physics::Kinematics",
    "MileDown::Physics::Research::Data",
    "MileDown::Behavioral::Learning_and_Memory",
    "MileDown::Behavioral::Social_Psychology",
    "MileDown::Behavioral::Identity",
    "MileDown::Behavioral::Demographics",
    "MileDown::Behavioral::Social_Inequality",
    "AnKing::Step1::Pharm",
    "leech",
]

# Card mix, as a fraction of the total. Chosen so the crosswalk is exercised in
# all three of its outcomes (map, refuse, miss) and so both the crosswalk and
# the no-crosswalk configuration have real work to do.
MIX = {
    "native": 0.20,  # carry mcat:: tags; resolved without the crosswalk
    "mapped": 0.50,  # MileDown tags the crosswalk maps to a topic
    "refused": 0.10,  # MileDown tags the crosswalk deliberately refuses
    "unmapped": 0.20,  # labels the crosswalk has never seen
}

SUBJECT_DECKS = [
    "Biochemistry",
    "Biology",
    "Chemistry",
    "Physics and Math",
    "Behavioral Sciences",
]


def crosswalk_path() -> Path:
    return Path(__file__).resolve().parents[2] / "crosswalk" / "miledown-bb-v1.json"


def load_crosswalk_tags() -> tuple[list[str], list[str]]:
    """(tags the shipped crosswalk maps, tags it refuses)."""
    data = json.loads(crosswalk_path().read_text(encoding="utf-8"))
    mapped = [e["tag"] for e in data["entries"] if e.get("topic")]
    refused = [e["tag"] for e in data["entries"] if not e.get("topic")]
    return mapped, refused


def simulate_history(rng: random.Random, now_secs: int) -> dict:
    """One card's review history, as a plausible FSRS-scheduled card.

    Not a model of anything — the point is only that intervals grow, lapses
    happen, and the resulting `revlog` is shaped like the rows the real memory
    state computation reads.
    """
    # A fifth of a real 50k deck has never been touched. Those cards still cost
    # a tag resolution but contribute no memory state, which is exactly the
    # split mastery.rs reports as `cards_with_memory_state`.
    if rng.random() < 0.18:
        return {"reviews": [], "reps": 0, "lapses": 0, "ivl": 0, "due": 0, "lrt": None}

    first_days_ago = rng.randint(30, 700)
    t = now_secs - first_days_ago * 86400
    ivl = 0
    reps = 0
    lapses = 0
    reviews = []
    # Geometric-ish: most cards a handful of reviews, a long tail of leeches.
    target_reps = min(40, 1 + int(rng.expovariate(1 / 7.0)))
    while reps < target_reps and t < now_secs:
        if reps == 0:
            ease = 3
            kind = 0  # learning
            last_ivl = 0
            new_ivl = rng.choice([1, 2, 3])
        else:
            roll = rng.random()
            if roll < 0.12:
                ease = 1  # again
            elif roll < 0.30:
                ease = 2  # hard
            elif roll < 0.85:
                ease = 3  # good
            else:
                ease = 4  # easy
            kind = 1  # review
            last_ivl = ivl
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
        new_ivl = min(new_ivl, 3650)
        reviews.append(
            {
                "ms": t * 1000,
                "ease": ease,
                "ivl": new_ivl,
                "last_ivl": last_ivl,
                "type": kind,
                "time": rng.randint(1200, 30000),
            }
        )
        reps += 1
        ivl = new_ivl
        t += max(1, int(new_ivl * 86400 * rng.uniform(0.85, 1.4)))

    if not reviews:
        return {"reviews": [], "reps": 0, "lapses": 0, "ivl": 0, "due": 0, "lrt": None}

    last = reviews[-1]
    return {
        "reviews": reviews,
        "reps": reps,
        "lapses": lapses,
        "ivl": last["ivl"],
        "lrt": last["ms"] // 1000,
    }


def build(base: Path, total_cards: int, seed: int) -> dict:
    os.environ["ANKI_BASE"] = str(base)
    import anki.lang
    from anki.collection import Collection
    from anki.utils import field_checksum, guid64, join_fields

    # `field_checksum` strips HTML through the backend's i18n instance, which
    # only exists once a language has been set.
    anki.lang.set_lang("en_US")

    col_path = base / "bench" / "collection.anki2"
    col_path.parent.mkdir(parents=True, exist_ok=True)
    if col_path.exists():
        col_path.unlink()

    rng = random.Random(seed)
    col = Collection(str(col_path))
    stats: dict = {"seed": seed, "requested_cards": total_cards}

    # The label lives in the collection too, so anyone who opens this profile is
    # told what it is before they read any number out of it.
    col.set_config(
        SYNTHETIC_CONFIG_KEY,
        {
            "synthetic": True,
            "seed": seed,
            "generator": "speedrun/eval/bench/gen_deck.py",
            "purpose": "latency measurement only",
            "warning": (
                "SYNTHETIC DECK. Generated review history. Never report a Memory, "
                "Performance or Readiness score computed from this collection."
            ),
        },
    )

    basic = col.models.by_name("Basic")
    assert basic is not None
    basic_mid = basic["id"]

    attempt = col.models.new(ATTEMPT_NOTETYPE)
    col.models.add_field(attempt, col.models.new_field("Front"))
    col.models.add_field(attempt, col.models.new_field("Back"))
    tmpl = col.models.new_template("Card 1")
    tmpl["qfmt"] = "{{Front}}"
    tmpl["afmt"] = "{{Front}}<hr id=answer>{{Back}}"
    col.models.add_template(attempt, tmpl)
    col.models.add(attempt)
    attempt_mid = col.models.by_name(ATTEMPT_NOTETYPE)["id"]

    deck_ids = {
        name: col.decks.id(f"{SYNTHETIC_ROOT}::{name}") for name in SUBJECT_DECKS
    }
    for name, did in deck_ids.items():
        deck = col.decks.get(did)
        deck["desc"] = (
            "SYNTHETIC benchmark deck. Generated, not studied. "
            "No score computed from it is valid."
        )
        col.decks.save(deck)

    mapped_tags, refused_tags = load_crosswalk_tags()
    native_tags = [
        f"mcat::{section}::{topic}"
        for section, topics in OUTLINE.items()
        for topic in topics
    ]

    counts = {k: int(total_cards * v) for k, v in MIX.items()}
    counts["native"] += total_cards - sum(counts.values())
    plan: list[tuple[str, str]] = []
    for segment, n in counts.items():
        pool = {
            "native": native_tags,
            "mapped": mapped_tags,
            "refused": refused_tags,
            "unmapped": UNMAPPED_TAGS,
        }[segment]
        for i in range(n):
            plan.append((segment, pool[i % len(pool)]))
    rng.shuffle(plan)

    now_secs = int(time.time())
    day_cutoff = col.sched.day_cutoff
    note_rows: list[tuple] = []
    card_rows: list[tuple] = []
    revlog_rows: list[tuple] = []
    used_revlog_ids: set[int] = set()

    next_id = int(time.time() * 1000)
    segment_counts = {k: 0 for k in MIX}
    total_reviews = 0
    with_history = 0

    for index, (segment, tag) in enumerate(plan):
        nid = next_id
        cid = next_id
        next_id += 1
        segment_counts[segment] += 1

        front = f"[SYNTHETIC] bench card {index} ({tag})"
        back = f"[SYNTHETIC] generated answer {index}"
        flds = join_fields([front, back])
        tags = f" {tag} {SYNTHETIC_TAG} "
        note_rows.append(
            (
                nid,
                guid64(),
                basic_mid,
                now_secs,
                -1,
                tags,
                flds,
                front,
                field_checksum(front),
                0,
                "",
            )
        )

        deck = deck_ids[SUBJECT_DECKS[index % len(SUBJECT_DECKS)]]
        history = simulate_history(rng, now_secs)
        if history["reviews"]:
            with_history += 1
            total_reviews += len(history["reviews"])
            due_secs = history["lrt"] + history["ivl"] * 86400
            due_day = int((due_secs - day_cutoff) // 86400) + col.sched.today + 1
            card_rows.append(
                (
                    cid,
                    nid,
                    deck,
                    0,
                    now_secs,
                    -1,
                    2,  # type: review
                    2,  # queue: review
                    due_day,
                    history["ivl"],
                    2500,
                    history["reps"],
                    history["lapses"],
                    0,
                    0,
                    0,
                    0,
                    json.dumps({"lrt": history["lrt"]}, separators=(",", ":")),
                )
            )
            for r in history["reviews"]:
                rid = r["ms"]
                while rid in used_revlog_ids:
                    rid += 1
                used_revlog_ids.add(rid)
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
        else:
            card_rows.append(
                (
                    cid,
                    nid,
                    deck,
                    0,
                    now_secs,
                    -1,
                    0,  # new
                    0,
                    index,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    "",
                )
            )

    # Speedrun's own attempt cards: suspended, held out, and excluded from every
    # measurement. Present so the exclusion query has rows to exclude.
    attempt_cards = 0
    for section, topics in OUTLINE.items():
        for topic in topics:
            for _ in range(12):
                nid = next_id
                cid = next_id
                next_id += 1
                front = (
                    f"[SYNTHETIC] held-out attempt {section} {topic} #{attempt_cards}"
                )
                note_rows.append(
                    (
                        nid,
                        guid64(),
                        attempt_mid,
                        now_secs,
                        -1,
                        f" mcat::{section}::{topic} {HOLDOUT_TAG} {SYNTHETIC_TAG} ",
                        join_fields([front, "graded"]),
                        front,
                        field_checksum(front),
                        0,
                        "",
                    )
                )
                card_rows.append(
                    (
                        cid,
                        nid,
                        deck_ids["Biology"],
                        0,
                        now_secs,
                        -1,
                        0,
                        -1,  # suspended
                        attempt_cards,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        "",
                    )
                )
                attempt_cards += 1

    def insert() -> None:
        col.db.executemany(
            "insert into notes (id,guid,mid,mod,usn,tags,flds,sfld,csum,flags,data)"
            " values (?,?,?,?,?,?,?,?,?,?,?)",
            note_rows,
        )
        col.db.executemany(
            "insert into cards (id,nid,did,ord,mod,usn,type,queue,due,ivl,factor,"
            "reps,lapses,left,odue,odid,flags,data)"
            " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            card_rows,
        )
        col.db.executemany(
            "insert into revlog (id,cid,usn,ease,ivl,lastIvl,factor,time,type)"
            " values (?,?,?,?,?,?,?,?,?)",
            revlog_rows,
        )

    t0 = time.perf_counter()
    col.db.transact(insert)
    stats["insert_secs"] = round(time.perf_counter() - t0, 2)

    col.close()

    # Reopened so nothing measured later is reading a cache warmed by the write
    # path above.
    col = Collection(str(col_path))

    t0 = time.perf_counter()
    fsrs_ok = True
    fsrs_error = ""
    try:
        enable_fsrs(col)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        fsrs_ok = False
        fsrs_error = f"{type(exc).__name__}: {exc}"
    stats["fsrs_secs"] = round(time.perf_counter() - t0, 2)
    stats["fsrs_ok"] = fsrs_ok
    if fsrs_error:
        stats["fsrs_error"] = fsrs_error

    stats["notes"] = col.db.scalar("select count() from notes")
    stats["cards"] = col.db.scalar("select count() from cards")
    stats["reviews"] = col.db.scalar("select count() from revlog")
    stats["cards_with_memory_state"] = col.db.scalar(
        "select count() from cards where data like '%\"s\":%'"
    )
    stats["attempt_cards"] = attempt_cards
    stats["cards_with_history"] = with_history
    stats["segments"] = segment_counts
    stats["generated_reviews"] = total_reviews
    stats["collection_bytes"] = col_path.stat().st_size
    col.close()
    return stats


def enable_fsrs(col) -> None:
    """Turn FSRS on, which makes Anki derive memory state from the revlog.

    Deliberately Anki's own path rather than writing `s`/`d` into the card data
    column ourselves: the retrievability `mastery.rs` computes has to come from
    the same code a student's collection would produce, or the benchmark is
    measuring a fixture.
    """
    from anki import deck_config_pb2

    deck_id = col.decks.id_for_name(f"{SYNTHETIC_ROOT}::Biology")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="throwaway ANKI_BASE directory")
    parser.add_argument("--cards", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--stats-out", default="")
    args = parser.parse_args()

    base = Path(args.base).resolve()
    base.mkdir(parents=True, exist_ok=True)
    stats = build(base, args.cards, args.seed)
    text = json.dumps(stats, indent=2)
    print(text)
    if args.stats_out:
        Path(args.stats_out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
