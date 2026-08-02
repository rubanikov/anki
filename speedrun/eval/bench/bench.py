#!/usr/bin/env python3
"""Time the Speedrun backend against the 50,000-card SYNTHETIC deck.

Reports p50 / p95 / worst for every PRD section 10 target that can be reached
from Python without a GUI, and prints — rather than omits — the ones that
cannot. A target that is quietly dropped from a performance report is the exact
failure this project exists to oppose, so `unmeasured` is a first-class output
of this script and appears in `results.json` alongside the numbers.

What is timed
-------------
* `TopicMastery` and `SectionScores`, per section — the two backend calls the
  dashboard waits on, and the only two Speedrun adds to Anki.
* The dashboard's whole gather, which is what the "< 1 s first load / < 500 ms
  refresh" target is actually about: four sections × (scores + mastery), plus
  the collection-wide mastery. This calls the add-on's own `backend.py`, so it
  is the real sequence and not a re-creation of it.
* Opening the collection, as the backend component of cold start.
* The backend half of "next card after grading": `answer_card` followed by
  `get_queued_cards`. Rendering is not included and the number must not be read
  as if it were.

Every phase discards `--warmup` iterations before it records anything.

Usage
-----
    python speedrun/eval/bench/bench.py --base /path/to/throwaway --out results.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # .../speedrun
ADDON = REPO / "addon"
CROSSWALK = REPO / "crosswalk" / "miledown-bb-v1.json"
CROSSWALK_CONFIG_KEY = "speedrunCrosswalk"

# PRD section 10 targets this script cannot reach, and why. Written down here so
# the report cannot be assembled without them.
UNMEASURED = [
    {
        "target": "Button press acknowledged: p95 < 50 ms, both platforms",
        "why": (
            "The acknowledgement is a Qt/WebView repaint. Nothing in the Python "
            "API observes the moment a button visibly responds, and no number "
            "produced here may stand in for it."
        ),
    },
    {
        "target": "Next card after grading: p95 < 100 ms (end to end)",
        "why": (
            "Only the backend half is measured below (answer_card + "
            "get_queued_cards). Question rendering, the WebView round trip and "
            "the repaint are not included, so the measured number is a lower "
            "bound on the target, never a pass for it."
        ),
    },
    {
        "target": "Dashboard never a frozen screen; nothing blocks the UI > 100 ms",
        "why": (
            "A property of the Qt event loop. dashboard.py runs the gather on a "
            "QueryOp background thread, which is a structural argument, not a "
            "measurement. Needs a GUI harness."
        ),
    },
    {
        "target": "Normal session sync < 5 s",
        "why": "Requires an AnkiWeb account and a sync server. Not run here.",
    },
    {
        "target": "Cold start < 5 s desktop, < 4 s phone",
        "why": (
            "Process launch, Qt init and the main window are outside this "
            "script. Collection open time is measured below as one component of "
            "it and is not the whole target."
        ),
    },
    {
        "target": "Memory at 50k cards on a midrange phone",
        "why": "Android. Desktop peak working set is measured below; the phone is not.",
    },
    {
        "target": "Zero corrupted collections across the crash test",
        "why": (
            "The crash test is a separate exercise with its own kill/restart "
            "harness. `--integrity` here only checks that the generated "
            "collection is well formed, which is not that test."
        ),
    },
]


def percentiles(samples_ms: list[float]) -> dict:
    """p50 / p95 / worst, plus everything needed to argue with them.

    p95 is nearest-rank rather than interpolated: with 30 samples an
    interpolated p95 invents a value that was never observed, and the sample
    count is reported so the reader can see how thin the tail is.
    """
    ordered = sorted(samples_ms)
    n = len(ordered)
    p95_index = min(n - 1, math.ceil(0.95 * n) - 1)
    return {
        "n": n,
        # With n <= 20, nearest-rank p95 IS the maximum. Stated rather than
        # hidden, because "p95" reads as if a tail were sampled when it wasn't.
        "p95_is_max": p95_index == n - 1,
        "p50_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(ordered[p95_index], 2),
        "worst_ms": round(ordered[-1], 2),
        "best_ms": round(ordered[0], 2),
        "mean_ms": round(statistics.fmean(ordered), 2),
        # Every sample, in the order it was taken. A benchmark on a machine
        # other work is running on can be quietly wrong, and the only defence is
        # letting the reader see the spread.
        "samples_ms": [round(x, 2) for x in samples_ms],
    }


def timed(fn, reps: int, warmup: int) -> list[float]:
    for _ in range(warmup):
        fn()
    out = []
    for _ in range(reps):
        start = time.perf_counter()
        fn()
        out.append((time.perf_counter() - start) * 1000.0)
    return out


def gather(col, conf: dict, addon_backend) -> None:
    """The dashboard's backend reads — the real ones, not a copy of them.

    This used to hold its own transcription of the sequence, and when the
    dashboard stopped fetching per-section mastery the transcription did not.
    The report was then timing a code path that no longer existed, and timing it
    slower than the real one. Calling `backend.dashboard_reads` means the two
    cannot drift apart again.

    Off-switch probing is deliberately not included: it is a network call to the
    agent service, it is done last precisely so no score waits on it, and timing
    it here would attribute an HTTP timeout to the measurement layer.
    """
    addon_backend.dashboard_reads(col, conf["sections"], conf["tag_prefix"])


def set_crosswalk(col, enabled: bool) -> str:
    """Install or remove the shipped crosswalk, always explicitly.

    Removing it matters as much as installing it: the crosswalk lives in
    collection config, so a run that only ever installed would leave the next
    "no crosswalk" run measuring a collection that still had one.
    """
    if not enabled:
        col.remove_config(CROSSWALK_CONFIG_KEY)
        return ""
    data = json.loads(CROSSWALK.read_text(encoding="utf-8"))
    col.set_config(CROSSWALK_CONFIG_KEY, data)
    return data["id"]


def load_snapshot() -> dict:
    """What else the machine was doing. Recorded because it can invalidate a run.

    Three agents share this box and one of them may be compiling Rust. A
    benchmark that does not say how loaded the machine was is not reproducible,
    and a fast number taken on a busy machine is luckier than it looks.
    """
    try:
        import psutil
    except ImportError:
        return {}
    busy = []
    for proc in psutil.process_iter(["name", "cpu_percent"]):
        try:
            if (proc.info.get("cpu_percent") or 0) > 20.0:
                busy.append(proc.info["name"])
        except psutil.Error:
            continue
    return {
        "cpu_percent_1s": psutil.cpu_percent(interval=1.0),
        "busy_processes": sorted(set(busy))[:10],
    }


def peak_rss_mb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None) or info.rss
    return round(peak / (1024 * 1024), 1)


def measure(col_path: Path, crosswalk: bool, args, addon_backend, conf) -> dict:
    from anki.collection import Collection

    results: dict = {
        "crosswalk_installed": crosswalk,
        "load_before": load_snapshot(),
    }
    prefix = conf["tag_prefix"]
    sections = [entry["code"] for entry in conf["sections"]]

    # --- cold: a fresh open, then the first gather, repeated ---------------
    open_ms: list[float] = []
    first_gather_ms: list[float] = []
    for i in range(args.cold_reps + args.cold_warmup):
        start = time.perf_counter()
        col = Collection(str(col_path))
        open_elapsed = (time.perf_counter() - start) * 1000.0
        crosswalk_id = set_crosswalk(col, crosswalk)
        if crosswalk_id:
            results["crosswalk_id"] = crosswalk_id
        start = time.perf_counter()
        gather(col, conf, addon_backend)
        gather_elapsed = (time.perf_counter() - start) * 1000.0
        col.close()
        if i >= args.cold_warmup:
            open_ms.append(open_elapsed)
            first_gather_ms.append(gather_elapsed)
    results["collection_open"] = percentiles(open_ms)
    results["dashboard_first_load"] = percentiles(first_gather_ms)
    results["dashboard_first_load"]["scope"] = (
        "First gather after a freshly opened Collection, in a process that has "
        "already opened it once. The SQLite page cache is new; the OS file "
        "cache is not. A genuinely cold disk would be slower than this."
    )

    # --- warm: one open, repeated calls ------------------------------------
    col = Collection(str(col_path))
    set_crosswalk(col, crosswalk)

    # Denominators, so the latencies below are attached to a known amount of work.
    mastery = col._backend.topic_mastery(section="", tag_prefix=prefix)
    results["work"] = {
        "cards_considered": mastery.cards_considered,
        "cards_excluded": mastery.cards_excluded,
        "cards_unmapped": mastery.cards_unmapped,
        "topics_resolved": len(mastery.topics),
        "total_cards": col.card_count(),
    }

    results["topic_mastery"] = {}
    results["section_scores"] = {}
    for section in [""] + sections:
        label = section or "ALL"
        results["topic_mastery"][label] = percentiles(
            timed(
                lambda s=section: col._backend.topic_mastery(
                    section=s, tag_prefix=prefix
                ),
                args.reps,
                args.warmup,
            )
        )
    for entry in conf["sections"]:
        code = entry["code"]
        outline = int(entry.get("outline_topic_count", 0))
        results["section_scores"][code] = percentiles(
            timed(
                lambda c=code, o=outline: col._backend.section_scores(
                    section=c, tag_prefix=prefix, outline_topic_count=o
                ),
                args.reps,
                args.warmup,
            )
        )

    results["dashboard_refresh"] = percentiles(
        timed(
            lambda: gather(col, conf, addon_backend),
            args.gather_reps,
            args.gather_warmup,
        )
    )
    results["peak_rss_mb"] = peak_rss_mb()
    results["load_after"] = load_snapshot()
    col.close()
    return results


def measure_grading(col_path: Path, args, scratch: Path) -> dict:
    """Backend half of "next card after grading", on a throwaway copy.

    A copy because answering cards writes revlog rows and moves due dates, and
    the deck every other number in this report was measured against has to stay
    the deck that was generated from the seed.
    """
    from gen_deck import SYNTHETIC_ROOT

    from anki.collection import Collection
    from anki.scheduler.v3 import CardAnswer

    copy_path = scratch / "grading-copy.anki2"
    if copy_path.exists():
        copy_path.unlink()
    shutil.copy2(col_path, copy_path)
    col = Collection(str(copy_path))

    # The queue is built for the selected deck, and a fresh collection has
    # `Default` selected — which holds none of the synthetic cards.
    root = col.decks.id_for_name(SYNTHETIC_ROOT)
    if root:
        col.decks.select(root)

    samples: list[float] = []
    skipped = 0
    total = args.grade_reps + args.warmup
    for i in range(total):
        queued = col.sched.get_queued_cards(fetch_limit=1)
        if not queued.cards:
            skipped = total - i
            break
        entry = queued.cards[0]
        card = col.get_card(entry.card.id)
        # The reviewer starts this timer when the question is shown; it only
        # feeds `milliseconds_taken`, so it is set outside the timed region.
        card.start_timer()
        start = time.perf_counter()
        answer = col.sched.build_answer(
            card=card, states=entry.states, rating=CardAnswer.GOOD
        )
        col.sched.answer_card(answer)
        col.sched.get_queued_cards(fetch_limit=1)
        elapsed = (time.perf_counter() - start) * 1000.0
        if i >= args.warmup:
            samples.append(elapsed)

    counts = col.sched.counts()
    col.close()
    copy_path.unlink(missing_ok=True)

    if not samples:
        return {
            "error": "no cards were due; nothing graded",
            "queue_counts": list(counts),
        }
    out = percentiles(samples)
    out["cards_left_unanswered_in_run"] = skipped
    out["scope"] = "backend only: answer_card + get_queued_cards, no rendering"
    return out


def detect_build_profile(declared: str) -> dict:
    """Work out which Rust build is actually loaded, rather than trusting a flag.

    The build profile is the single most load-bearing caveat in this report: a
    debug number that misses a target says nothing about whether a release build
    misses it. Leaving that label to a command-line argument means the report can
    be wrong in the direction that flatters us, so the loaded extension is hashed
    and compared against both built artifacts.

    Falls back to the declared value when neither matches — a stale or
    hand-copied bridge is possible — but says so, so the uncertainty is visible.
    """
    import hashlib

    root = Path(__file__).resolve().parents[3]
    loaded = root / "out" / "pylib" / "anki" / "_rsbridge.pyd"
    if not loaded.exists():
        loaded = loaded.with_suffix(".so")

    def digest(path: Path) -> str | None:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None

    loaded_hash = digest(loaded)
    matches = {
        profile: digest(root / "out" / "rust" / profile / name)
        for profile in ("release", "debug")
        for name in ("rsbridge.dll", "librsbridge.so", "librsbridge.dylib")
        if (root / "out" / "rust" / profile / name).exists()
    }
    detected = next((p for p, h in matches.items() if h and h == loaded_hash), None)

    return {
        "profile": detected or declared,
        "detected": detected is not None,
        "declared": declared,
        "loaded_extension": str(loaded),
        "loaded_sha256": loaded_hash,
        "note": (
            "Detected by hashing the loaded extension against the built artifacts."
            if detected
            else "NOT detected — no built artifact matched the loaded extension, so "
            "the declared value is reported and may be wrong."
        ),
    }


def machine() -> dict:
    info = {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python": sys.version.split()[0],
    }
    try:
        import psutil

        info["logical_cpus"] = psutil.cpu_count(logical=True)
        info["physical_cpus"] = psutil.cpu_count(logical=False)
        info["ram_gb"] = round(psutil.virtual_memory().total / (1024**3), 1)
    except ImportError:
        pass
    try:
        import anki.buildinfo

        info["anki_version"] = anki.buildinfo.version
        info["anki_buildhash"] = anki.buildinfo.buildhash
    except Exception:  # noqa: BLE001
        pass
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="throwaway ANKI_BASE directory")
    parser.add_argument("--reps", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--gather-reps", type=int, default=10)
    parser.add_argument("--gather-warmup", type=int, default=2)
    parser.add_argument("--cold-reps", type=int, default=5)
    parser.add_argument("--cold-warmup", type=int, default=1)
    parser.add_argument("--grade-reps", type=int, default=50)
    parser.add_argument(
        "--integrity",
        action="store_true",
        help="run Anki's own database check once, to show the generated "
        "collection is well formed (this is NOT the crash test)",
    )
    parser.add_argument(
        "--build-profile",
        default="debug",
        help="rsbridge build profile these numbers came from; recorded verbatim",
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    base = Path(args.base).resolve()
    os.environ["ANKI_BASE"] = str(base)
    sys.path.insert(0, str(ADDON))

    import anki.lang

    anki.lang.set_lang("en_US")

    import backend as addon_backend  # speedrun/addon/backend.py
    import config as addon_config  # speedrun/addon/config.py

    conf = addon_config.get()
    col_path = base / "bench" / "collection.anki2"
    if not col_path.exists():
        print(f"no collection at {col_path}; run gen_deck.py first", file=sys.stderr)
        return 1

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "build_profile": detect_build_profile(args.build_profile)["profile"],
        "build": detect_build_profile(args.build_profile),
        "machine": machine(),
        "collection": {
            "path": str(col_path),
            "bytes": col_path.stat().st_size,
            "synthetic": True,
            "warning": (
                "SYNTHETIC deck, generated by speedrun/eval/bench/gen_deck.py. "
                "Latency only. No Memory, Performance or Readiness value computed "
                "from it is recorded here or may ever be reported."
            ),
        },
        "iterations": {
            "warm_reps": args.reps,
            "warm_warmup_discarded": args.warmup,
            "gather_reps": args.gather_reps,
            "gather_warmup_discarded": args.gather_warmup,
            "cold_reps": args.cold_reps,
            "cold_warmup_discarded": args.cold_warmup,
            "grade_reps": args.grade_reps,
            "grade_warmup_discarded": args.warmup,
        },
        "runs": {},
        "unmeasured": UNMEASURED,
    }

    if args.integrity:
        from anki.collection import Collection

        print("# database check", file=sys.stderr)
        # On a copy: "check database" repairs what it finds, and the deck every
        # other number here was measured against has to stay the deck the seed
        # produced.
        check_path = col_path.parent / "integrity-copy.anki2"
        check_path.unlink(missing_ok=True)
        shutil.copy2(col_path, check_path)
        col = Collection(str(check_path))
        start = time.perf_counter()
        problems, ok = col.fix_integrity()
        report["database_check"] = {
            "ok": ok,
            "problems": problems,
            "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
            "note": (
                "Run on a copy. Shows the generated collection is well formed. "
                "It is NOT the crash test, which is a separate exercise."
            ),
        }
        col.close()
        check_path.unlink(missing_ok=True)

    for label, crosswalk in (("no_crosswalk", False), ("crosswalk", True)):
        print(f"# run: {label}", file=sys.stderr)
        report["runs"][label] = measure(col_path, crosswalk, args, addon_backend, conf)

    print("# run: grading", file=sys.stderr)
    report["next_card_after_grading"] = measure_grading(col_path, args, base / "bench")

    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
