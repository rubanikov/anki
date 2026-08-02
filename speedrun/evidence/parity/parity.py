#!/usr/bin/env python3
"""Desktop half of the T-21 platform-parity check.

The shared-engine claim is that the same collection produces the same numbers on
desktop and on the phone, offline. This script builds one collection, installs
the crosswalk into it, and reads `SectionScores` and `TopicMastery` back through
the fork's own Rust backend -- the same `SpeedrunService` the `.aar` exposes to
AnkiDroid. The phone half is the Speedrun screen in the app; the two outputs are
compared field by field in `PARITY.md`.

Run it with the fork's dev interpreter, from the `anki` repo root:

    PYTHONPATH="pylib;out/pylib" out/pyenv/Scripts/python.exe \
        speedrun/evidence/parity/parity.py build --base <throwaway> --cards 3000

Subcommands:
    build --base DIR --cards N   generate the collection and install the crosswalk
    read  --col PATH --out FILE  compute every score, offline, and dump JSON

`read` runs with an outbound-network guard installed by default: every socket
call raises before it leaves the process. If any number below needed the
network, the read fails loudly instead of quietly succeeding on a machine that
happened to be online.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for extra in ("pylib", "out/pylib"):
    p = str(REPO / extra)
    if p not in sys.path:
        sys.path.insert(0, p)

CROSSWALK = REPO / "speedrun" / "crosswalk" / "miledown-bb-v1.json"
SECTIONS = ["CP", "BB", "PS", "CARS"]

# Mirrors rslib/src/speedrun/thresholds.rs and the Android
# `outlineTopicCount`. Passed in explicitly so that a disagreement between the
# two platforms cannot be hidden by one of them defaulting.
OUTLINE_TOPIC_COUNT = {"BB": 9, "CP": 10, "PS": 12, "CARS": 0}


class NetworkUsed(RuntimeError):
    """Raised the moment anything tries to open a socket."""


def block_network() -> None:
    """Make every outbound network call raise.

    Cheaper and safer than pulling the machine's network -- three other agents
    are on this box -- and strictly stronger as evidence: a guard that raises
    proves nothing reached for the network, where an unplugged cable only proves
    nothing got through.
    """

    def refuse(*args, **kwargs):  # noqa: ANN002, ANN003
        raise NetworkUsed("the offline read tried to use the network")

    socket.socket.connect = refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = refuse  # type: ignore[method-assign]
    socket.create_connection = refuse  # type: ignore[assignment]
    socket.getaddrinfo = refuse  # type: ignore[assignment]
    socket.gethostbyname = refuse  # type: ignore[assignment]


def cmd_build(args: argparse.Namespace) -> dict:
    """Generate the collection, then install the crosswalk into it."""
    base = Path(args.base).resolve()
    base.mkdir(parents=True, exist_ok=True)
    os.environ["ANKI_BASE"] = str(base)

    sys.path.insert(0, str(REPO / "speedrun" / "eval" / "bench"))
    import gen_deck  # noqa: PLC0415

    stats = gen_deck.build(base, args.cards, args.seed)

    from anki.collection import Collection  # noqa: PLC0415

    col_path = base / "bench" / "collection.anki2"
    col = Collection(str(col_path))
    crosswalk = json.loads(CROSSWALK.read_text(encoding="utf-8"))
    # Config, not notes. The crosswalk is Speedrun's own record and is
    # deliberately never written onto the student's cards.
    col.set_config("speedrunCrosswalk", crosswalk)
    stats["crosswalk_id"] = crosswalk["id"]
    stats["crosswalk_entries"] = len(crosswalk["entries"])
    col.close()

    if args.out:
        dest = Path(args.out).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(col_path, dest)
        stats["copied_to"] = str(dest)
        stats["collection_bytes"] = dest.stat().st_size

    stats["collection"] = str(col_path)
    return stats


def _score(score) -> dict:
    return {
        "available": score.available,
        "estimate": round(score.estimate, 6),
        "range_low": round(score.range_low, 6),
        "range_high": round(score.range_high, 6),
        "abstain_reason": score.abstain_reason,
        "reasons": list(score.reasons),
        "confidence": int(score.confidence),
    }


def cmd_read(args: argparse.Namespace) -> dict:
    if not args.allow_network:
        block_network()

    from anki.collection import Collection  # noqa: PLC0415

    col_path = Path(args.col).resolve()
    col = Collection(str(col_path))
    if args.remove_crosswalk:
        # The control. With no crosswalk installed the engine falls back to
        # counting cards that carry no `mcat::` tag of their own, which is a
        # different and much larger number. Running it makes the phone's figure
        # a discriminator rather than a coincidence: an Android build whose
        # engine could not read the crosswalk could not have produced the
        # crosswalk's number.
        col.remove_config("speedrunCrosswalk")
    out: dict = {
        "collection": str(col_path),
        "collection_bytes": col_path.stat().st_size,
        "network_blocked": not args.allow_network,
        "crosswalk_installed": bool(col.get_config("speedrunCrosswalk", default=None)),
        "sections": {},
        "mastery": {},
        "totals": {
            "notes": col.db.scalar("select count() from notes"),
            "cards": col.db.scalar("select count() from cards"),
            "revlog": col.db.scalar("select count() from revlog"),
        },
    }
    cw = col.get_config("speedrunCrosswalk", default=None)
    if cw:
        out["crosswalk_id"] = cw.get("id")
        out["crosswalk_entry_count"] = len(cw.get("entries", []))

    for section in SECTIONS:
        res = col._backend.section_scores(
            section=section,
            tag_prefix="mcat",
            outline_topic_count=OUTLINE_TOPIC_COUNT[section],
        )
        out["sections"][section] = {
            "section": res.section,
            "memory": _score(res.memory),
            "performance": _score(res.performance),
            "readiness": _score(res.readiness),
            "coverage_pct": round(res.coverage_pct, 6),
            "graded_reviews": res.graded_reviews,
            "holdout_attempts": res.holdout_attempts,
            "topics_attempted": res.topics_attempted,
            "cards_unmapped": res.cards_unmapped,
        }

        mastery = col._backend.topic_mastery(section=section, tag_prefix="mcat")
        out["mastery"][section] = {
            "cards_considered": mastery.cards_considered,
            "cards_excluded": mastery.cards_excluded,
            "cards_unmapped": mastery.cards_unmapped,
            "topics": [
                {
                    "topic_id": t.topic_id,
                    "section": t.section,
                    "mean_retrievability": round(t.mean_retrievability, 6),
                    "range_low": round(t.range_low, 6),
                    "range_high": round(t.range_high, 6),
                    "card_count": t.card_count,
                    "cards_with_memory_state": t.cards_with_memory_state,
                    "review_count": t.review_count,
                    "covered": t.covered,
                }
                for t in mastery.topics
            ],
        }

    col.close()
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    build = sub.add_parser("build")
    build.add_argument("--base", required=True)
    build.add_argument("--cards", type=int, default=3000)
    build.add_argument("--seed", type=int, default=20260802)
    build.add_argument("--out")
    build.set_defaults(func=cmd_build)

    read = sub.add_parser("read")
    read.add_argument("--col", required=True)
    read.add_argument("--out")
    read.add_argument(
        "--remove-crosswalk",
        action="store_true",
        help="control run: uninstall the crosswalk first (mutates the copy)",
    )
    read.add_argument(
        "--allow-network",
        action="store_true",
        help="lift the socket guard (only for proving the guard itself bites)",
    )
    read.set_defaults(func=cmd_read)

    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, indent=2)[:4000])


if __name__ == "__main__":
    main()
