#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The paraphrase test harness — three points on one student, in one sitting.

    python speedrun/eval/paraphrase/run_paraphrase.py --session <name>
    python speedrun/eval/paraphrase/run_paraphrase.py --session <name> --score

**This asks a human being questions. It has no other mode of operation.** There
is no `--simulate`, no model-answers-the-items path, and there is not going to
be one: a model's accuracy on these items measures the model, and reporting it
as the paraphrase result would fabricate the one piece of evidence this project
is built on. `--selftest` exercises every code path with obviously fake typed
answers and stamps `synthetic: true` on everything it writes; `--score` refuses
to report a synthetic session as a result.

## What it presents

**Block 1 — Memory (DOK 1).** The student's own 30 cards, shown exactly as their
deck shows them. They type an answer, then see the card's answer and grade
themselves. This is recall on the card.

**Block 2 — everything else, interleaved.** The 60 Reworded cards and the 28
Held-out items in one stream, shuffled together with seed 20260802 and spread so
that the two rewordings of one fact are never within four items of each other.
Interleaving matters: if the R-set came first and the P-set last, every point of
the gap could be fatigue. Held-out items are multiple choice and grade
themselves; Reworded cards are short answer and are self-graded like the cards.

## The ordering confound, stated rather than hidden

Block 2 follows Block 1, so the student has just seen each card's answer before
meeting its rewording. That inflates R-set accuracy. It is the conservative
direction for the pre-registered claim — the target is a **gap** between card
recall and P-set accuracy, and anything that lifts the middle point makes the
three numbers *more* likely to collapse, not less. Running Block 2 first would
have contaminated card recall instead, which is the measurement the whole
project's Memory model is being checked against. The order is fixed here, in
advance, for that reason, and `--score` prints the caveat with the numbers.

## Self-grading

Free-response answers are graded by the student against the recorded answer.
That is the same judgement Anki asks for on every review, and it is the only one
available with one participant. What the harness does about it: the **typed text
is recorded verbatim**, so `--regrade` lets somebody who is not the student
re-grade all of it afterwards and the two gradings can be compared. A number
whose grader cannot be checked is not evidence.

## Resuming

The session file is append-only JSONL. Re-run with the same `--session` and the
harness picks up at the first unanswered item. Answers are flushed to disk as
they are given, so a closed terminal costs one item.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

PARAPHRASE_DIR = Path(__file__).resolve().parent
SPEEDRUN_DIR = PARAPHRASE_DIR.parents[1]
REPO_ROOT = SPEEDRUN_DIR.parent

CARDS_FILE = PARAPHRASE_DIR / "rset_cards.local.json"
RSET_FILE = PARAPHRASE_DIR / "h4_rset.jsonl"
PSET_FILE = SPEEDRUN_DIR / "eval" / "pset" / "h2_pset.jsonl"
SESSIONS_DIR = PARAPHRASE_DIR / "sessions"

sys.path.insert(0, str(PARAPHRASE_DIR))

from scoring import (  # noqa: E402
    TARGET_GAP_POINTS,
    Interval,
    cluster_bootstrap,
    newcombe,
    paired_bootstrap,
    wilson,
)

#: Block 2's shuffle. The manifest's seed, reused so one number governs the
#: whole test and nothing about the presentation order can be re-rolled either.
ORDER_SEED = 20260802
#: Minimum number of items between the two rewordings of the same card.
MIN_GAP = 4

RULE = "-" * 72


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    item_id: str
    block: str  # "card" | "rset" | "pset"
    card_id: int | None
    topic: str
    prompt: str
    answer: str
    options: tuple[str, ...] = ()

    @property
    def multiple_choice(self) -> bool:
        return bool(self.options)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_cards() -> list[Item]:
    data = json.loads(CARDS_FILE.read_text(encoding="utf-8"))["cards"]
    return [
        Item(
            item_id=f"card-{card['card_id']}",
            block="card",
            card_id=card["card_id"],
            topic=card["topic"],
            prompt=card["front"],
            answer=card["answer"],
        )
        for card in data
    ]


def load_rset() -> list[Item]:
    return [
        Item(
            item_id=row["id"],
            block="rset",
            card_id=row["card_id"],
            topic=row.get("topic", ""),
            prompt=row["prompt"],
            answer=row["answer"],
        )
        for row in read_jsonl(RSET_FILE)
        if row.get("status", "live") == "live"
    ]


def load_pset() -> list[Item]:
    return [
        Item(
            item_id=row["id"],
            block="pset",
            card_id=None,
            topic=row.get("topic", ""),
            prompt=row["stem"],
            answer=row["answer"],
            options=tuple(row["options"]),
        )
        for row in read_jsonl(PSET_FILE)
        if row.get("status", "live") == "live"
    ]


def block_two(rset: list[Item], pset: list[Item]) -> list[Item]:
    """R-set and P-set in one stream, seeded, with same-card rewordings spread out.

    Shuffle first, then emit greedily: at each step take the earliest remaining
    item whose card is not among the last `MIN_GAP` emitted. Deterministic, and
    it degrades gracefully — if nothing is far enough away it takes the first
    remaining item rather than looping.
    """
    pool = rset + pset
    random.Random(ORDER_SEED).shuffle(pool)
    ordered: list[Item] = []
    recent: list[int | None] = []
    remaining = list(pool)
    while remaining:
        pick = next(
            (i for i, item in enumerate(remaining) if item.card_id is None or item.card_id not in recent),
            0,
        )
        item = remaining.pop(pick)
        ordered.append(item)
        recent = (recent + [item.card_id])[-MIN_GAP:]
    return ordered


# --------------------------------------------------------------------------
# The session file
# --------------------------------------------------------------------------


class Session:
    """Append-only JSONL. Written as answers are given, never rewritten."""

    def __init__(self, path: Path, *, synthetic: bool = False) -> None:
        self.path = path
        self.synthetic = synthetic
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rows = read_jsonl(self.path) if self.path.exists() else []
        self.header = next((r for r in self.rows if r.get("kind") == "header"), None)

    def start(self, participant: str) -> None:
        if self.header is not None:
            return
        header = {
            "kind": "header",
            "session": self.path.stem,
            "participant": participant,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "synthetic": self.synthetic,
            "order_seed": ORDER_SEED,
            "sources": {
                "cards": {"path": str(CARDS_FILE.name), "sha256": sha256_file(CARDS_FILE)},
                "rset": {"path": str(RSET_FILE.name), "sha256": sha256_file(RSET_FILE)},
                "pset": {"path": "speedrun/eval/pset/h2_pset.jsonl", "sha256": sha256_file(PSET_FILE)},
            },
        }
        self._write(header)
        self.header = header

    def answered(self) -> set[str]:
        return {r["item_id"] for r in self.rows if r.get("kind") == "response"}

    def responses(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self.rows:
            if row.get("kind") == "response":
                latest[row["item_id"]] = row
            elif row.get("kind") == "regrade" and row["item_id"] in latest:
                latest[row["item_id"]] = {**latest[row["item_id"]], **{
                    "correct": row["correct"],
                    "regraded_by": row.get("by", ""),
                }}
        return list(latest.values())

    def record(self, row: dict[str, Any]) -> None:
        self._write(row)
        self.rows.append(row)

    def _write(self, row: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# Asking
# --------------------------------------------------------------------------

Reader = Callable[[str], str]


def console_reader(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        raise SystemExit("\nstdin closed — session saved, re-run to resume.") from None


def ask(item: Item, position: int, total: int, read: Reader) -> dict[str, Any] | None:
    """Present one item. Returns the response row, or None if the run was quit."""
    started = time.time()
    print(f"\n{RULE}\n[{position}/{total}]  {item.block}  {item.topic}\n")
    print(item.prompt)
    if item.multiple_choice:
        letters = "abcdefgh"
        for letter, option in zip(letters, item.options):
            print(f"   {letter}) {option}")
        while True:
            typed = read("\nyour answer (letter, or 'skip', or 'quit'): ").strip().lower()
            if typed in {"quit", "q"}:
                return None
            if typed == "skip":
                return _row(item, "", correct=0, skipped=True, started=started)
            if typed and typed[0] in letters[: len(item.options)]:
                chosen = item.options[letters.index(typed[0])]
                correct = int(chosen.strip().casefold() == item.answer.strip().casefold())
                print("  correct" if correct else f"  no — {item.answer}")
                return _row(item, chosen, correct=correct, skipped=False, started=started)
            print("  enter one of the letters above, or 'skip'.")

    typed = read("\nyour answer (or 'skip', or 'quit'): ").strip()
    if typed.lower() in {"quit", "q"}:
        return None
    if typed.lower() == "skip":
        print(f"  answer: {item.answer}")
        return _row(item, "", correct=0, skipped=True, started=started)
    print(f"\n  answer: {item.answer}")
    while True:
        grade = read("  did you get it? (y/n): ").strip().lower()
        if grade in {"y", "yes"}:
            return _row(item, typed, correct=1, skipped=False, started=started)
        if grade in {"n", "no"}:
            return _row(item, typed, correct=0, skipped=False, started=started)
        print("  y or n.")


def _row(item: Item, typed: str, *, correct: int, skipped: bool, started: float) -> dict[str, Any]:
    return {
        "kind": "response",
        "item_id": item.item_id,
        "block": item.block,
        "card_id": item.card_id,
        "topic": item.topic,
        "typed": typed,
        "correct": correct,
        "skipped": skipped,
        "seconds": round(time.time() - started, 1),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def present(items: Iterable[Item], session: Session, read: Reader, *, title: str) -> bool:
    """Ask every unanswered item in order. False if the participant quit."""
    items = list(items)
    done = session.answered()
    todo = [i for i in items if i.item_id not in done]
    print(f"\n\n{'=' * 72}\n{title}\n{'=' * 72}")
    if not todo:
        print("  (already complete)")
        return True
    for position, item in enumerate(todo, 1):
        row = ask(item, position, len(todo), read)
        if row is None:
            print("\nstopped. Re-run with the same --session to pick up here.")
            return False
        session.record(row)
    return True


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def score(session: Session, *, cards: list[Item], rset: list[Item]) -> dict[str, Any]:
    rows = {r["item_id"]: r for r in session.responses()}
    graded = {k: v for k, v in rows.items() if not v.get("skipped")}

    def block(name: str) -> list[dict[str, Any]]:
        return [v for v in graded.values() if v["block"] == name]

    card_rows = block("card")
    rset_rows = block("rset")
    pset_rows = block("pset")

    card = wilson(sum(r["correct"] for r in card_rows), len(card_rows))
    pset = wilson(sum(r["correct"] for r in pset_rows), len(pset_rows))

    by_card: dict[int, list[int]] = {}
    for row in rset_rows:
        by_card.setdefault(int(row["card_id"]), []).append(int(row["correct"]))
    reworded = cluster_bootstrap(list(by_card.values()))
    reworded_naive = wilson(sum(r["correct"] for r in rset_rows), len(rset_rows))

    card_by_id = {int(r["card_id"]): int(r["correct"]) for r in card_rows}
    paired = [
        card_by_id[cid] - sum(outcomes) / len(outcomes)
        for cid, outcomes in by_card.items()
        if cid in card_by_id and outcomes
    ]
    gap_reworded = paired_bootstrap(paired)
    gap_pset = newcombe(card, pset)

    return {
        "session": session.path.stem,
        "synthetic": bool(session.header and session.header.get("synthetic")),
        "counts": {
            "card_answered": len(card_rows),
            "card_expected": len(cards),
            "rset_answered": len(rset_rows),
            "rset_expected": len(rset),
            "pset_answered": len(pset_rows),
            "skipped": sum(1 for v in rows.values() if v.get("skipped")),
        },
        "card_recall": card.as_dict(),
        "reworded_accuracy": reworded.as_dict(),
        "reworded_accuracy_naive": reworded_naive.as_dict(),
        "heldout_accuracy": pset.as_dict(),
        "gap_card_minus_reworded": gap_reworded.as_dict(),
        "gap_card_minus_heldout": gap_pset.as_dict(),
        "target_gap_points": TARGET_GAP_POINTS,
        "target_met": 100 * gap_pset.point >= TARGET_GAP_POINTS
        if gap_pset.n
        else None,
    }


def print_report(result: dict[str, Any], *, cards: list[Item], rset: list[Item], pset: list[Item]) -> None:
    counts = result["counts"]
    complete = (
        counts["card_answered"] == len(cards)
        and counts["rset_answered"] == len(rset)
        and counts["pset_answered"] == len(pset)
    )
    print(f"\n{RULE}\nPARAPHRASE TEST — {result['session']}\n{RULE}")
    if result["synthetic"]:
        print(
            "\n*** SYNTHETIC SESSION. The answers in this file were typed by\n"
            "*** --selftest, not by a person. These are not results and must\n"
            "*** never be reported as any.\n"
        )
    if not complete:
        print(
            f"\nINCOMPLETE — card {counts['card_answered']}/{len(cards)}, "
            f"reworded {counts['rset_answered']}/{len(rset)}, "
            f"held-out {counts['pset_answered']}/{len(pset)}. "
            "Partial numbers below.\n"
        )

    def show(label: str, key: str) -> None:
        interval = result[key]
        print(
            f"  {label:<34} {100 * interval['point']:5.1f}%  "
            f"[{100 * interval['low']:5.1f}, {100 * interval['high']:5.1f}]  "
            f"n={interval['n']}  {interval['method']}"
        )

    print("\nthe three numbers")
    show("recall on their own card (DOK 1)", "card_recall")
    show("accuracy on reworded cards", "reworded_accuracy")
    show("  (naive, ignores clustering)", "reworded_accuracy_naive")
    show("accuracy on held-out items (DOK 2-3)", "heldout_accuracy")

    print("\nthe two gaps, in points")
    for label, key in (
        ("card - reworded (paired)", "gap_card_minus_reworded"),
        ("card - held-out (independent)", "gap_card_minus_heldout"),
    ):
        interval = result[key]
        print(
            f"  {label:<34} {100 * interval['point']:+5.1f}   "
            f"[{100 * interval['low']:+5.1f}, {100 * interval['high']:+5.1f}]  "
            f"{interval['method']}"
        )

    gap = result["gap_card_minus_heldout"]
    print(f"\npre-registered target: card - held-out >= {TARGET_GAP_POINTS:.0f} points")
    if result["target_met"] is None:
        print("  not evaluable — no answers.")
    elif result["target_met"]:
        print(f"  MET at {100 * gap['point']:+.1f} points.")
    else:
        print(f"  NOT MET at {100 * gap['point']:+.1f} points. Reported as it came out.")
    if gap["low"] <= 0 <= gap["high"]:
        print(
            "  The interval on this gap includes zero: the data are consistent with\n"
            "  the three numbers being one number, which is the falsifying finding\n"
            "  ADR-0004 says to publish."
        )
    print(
        "\ncaveats that travel with these numbers"
        "\n  - one student, one sitting. Everything here is n=1 at the person level."
        "\n  - Block 2 followed Block 1, so each card's answer was seen shortly before"
        "\n    its rewording. That inflates the middle number and therefore works"
        "\n    against the gap, not for it."
        "\n  - card recall and reworded accuracy are self-graded; --regrade lets"
        "\n    somebody else re-grade the recorded text."
        "\n  - the P-set's own wording defects are catalogued in"
        "\n    speedrun/eval/pset/QUALITY.md: about a third of those 28 items are"
        "\n    easier than the fact they test, which pushes held-out accuracy up and"
        "\n    the gap down."
    )


# --------------------------------------------------------------------------
# Regrade
# --------------------------------------------------------------------------


def regrade(session: Session, read: Reader, by: str) -> None:
    """Re-grade every free-response answer from the recorded text."""
    changed = 0
    for row in session.responses():
        if row["block"] == "pset" or row.get("skipped"):
            continue
        print(f"\n{RULE}\n{row['item_id']}\n  typed:    {row['typed']!r}\n  self-grade: {row['correct']}")
        verdict = read("  your grade (y/n/enter to keep): ").strip().lower()
        if verdict in {"y", "yes", "n", "no"}:
            correct = int(verdict in {"y", "yes"})
            if correct != row["correct"]:
                changed += 1
            session.record(
                {"kind": "regrade", "item_id": row["item_id"], "correct": correct, "by": by}
            )
    print(f"\nregraded; {changed} verdict(s) changed.")


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------


def selftest() -> int:
    """Drive every path with scripted, obviously fake answers. Proves it runs.

    The answers are the string "xxx" and a fixed alternating grade. They are not
    anybody's knowledge and the numbers they produce are not a result — the
    session is stamped `synthetic` and `--score` says so in capitals. What this
    checks is that the harness presents, records, resumes and scores.
    """
    import tempfile

    print("SELFTEST — scripted answers, synthetic session, NOT A RESULT\n")
    cards, rset, pset = load_cards(), load_rset(), load_pset()
    print(f"loaded {len(cards)} cards, {len(rset)} rewordings, {len(pset)} held-out items")

    order = block_two(rset, pset)
    assert len(order) == len(rset) + len(pset), "block 2 lost or duplicated items"
    assert {i.item_id for i in order} == {i.item_id for i in rset + pset}
    positions: dict[int, list[int]] = {}
    for index, item in enumerate(order):
        if item.card_id is not None:
            positions.setdefault(item.card_id, []).append(index)
    tight = [c for c, p in positions.items() if len(p) > 1 and min(b - a for a, b in zip(p, p[1:])) <= MIN_GAP]
    print(f"block 2: {len(order)} items, {len(tight)} card(s) with rewordings closer than {MIN_GAP + 1} apart")
    assert block_two(rset, pset) == order, "block 2 order is not deterministic"

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "selftest.jsonl"
        session = Session(path, synthetic=True)
        session.start("selftest-scripted")

        # Alternating scripted grades: y, n, y, n, ... and letter 'a' throughout.
        state = {"n": 0}

        def scripted(prompt: str) -> str:
            state["n"] += 1
            if "letter" in prompt:
                return "a"
            if "did you get it" in prompt:
                return "y" if state["n"] % 3 else "n"
            return "xxx"

        assert present(cards[:4], session, scripted, title="BLOCK 1 (selftest slice)")
        assert present(order[:6], session, scripted, title="BLOCK 2 (selftest slice)")

        # Resume: a second pass over the same items must ask nothing.
        before = len(session.rows)
        assert present(cards[:4], session, scripted, title="BLOCK 1 again")
        assert len(session.rows) == before, "resume re-asked an answered item"

        # Quit path.
        assert not present(cards[4:6], session, lambda _: "quit", title="BLOCK 1 quit path")

        result = score(session, cards=cards, rset=rset)
        print_report(result, cards=cards, rset=rset, pset=pset)
        assert result["synthetic"] is True

    # Arithmetic, on inputs whose answers can be worked out by hand.
    exact = wilson(15, 30)
    assert abs(exact.point - 0.5) < 1e-12
    assert 0.32 < exact.low < 0.34 and 0.66 < exact.high < 0.68, exact
    perfect = wilson(30, 30)
    assert perfect.high > 0.999 and perfect.low > 0.85, perfect
    zero = wilson(0, 28)
    assert zero.low < 1e-9 and zero.high < 0.13, zero
    clustered = cluster_bootstrap([[1, 1]] * 15 + [[0, 0]] * 15)
    assert abs(clustered.point - 0.5) < 1e-12
    naive = wilson(30, 60)
    assert (clustered.high - clustered.low) > (naive.high - naive.low), (
        "the cluster bootstrap must be wider than the naive Wilson when the two "
        "rewordings of a card agree perfectly"
    )
    difference = newcombe(wilson(27, 30), wilson(14, 28))
    assert difference.point > 0.39 and difference.low > 0.15, difference
    paired = paired_bootstrap([1.0] * 10 + [0.0] * 20)
    assert abs(paired.point - 1 / 3) < 1e-9

    print("\nSELFTEST OK — presentation, recording, resume, quit and scoring all ran.")
    print("Nothing above is a result. The test still needs a participant.")
    return 0


# --------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="This harness asks a human. It has no mode that answers for one.",
    )
    parser.add_argument("--session", help="session name; re-use it to resume")
    parser.add_argument("--participant", default="", help="who is sitting the test")
    parser.add_argument("--score", action="store_true", help="score a session and stop")
    parser.add_argument("--regrade", metavar="GRADER", help="re-grade the free-response answers")
    parser.add_argument("--json", type=Path, help="--score: also write the result here")
    parser.add_argument("--selftest", action="store_true", help="run every path with fake answers")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    for path in (CARDS_FILE, RSET_FILE, PSET_FILE):
        if not path.exists():
            raise SystemExit(f"missing {path}")
    if not args.session:
        parser.error("--session is required (or use --selftest)")

    cards, rset, pset = load_cards(), load_rset(), load_pset()
    session = Session(SESSIONS_DIR / f"{args.session}.jsonl")

    if args.regrade:
        if not session.rows:
            raise SystemExit(f"no session at {session.path}")
        regrade(session, console_reader, args.regrade)
        return 0

    if args.score:
        if not session.rows:
            raise SystemExit(f"no session at {session.path}")
        result = score(session, cards=cards, rset=rset)
        print_report(result, cards=cards, rset=rset, pset=pset)
        if args.json:
            args.json.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
            print(f"\nwrote {args.json}")
        return 0

    session.start(args.participant or args.session)
    order = block_two(rset, pset)
    print(__doc__.split("## What it presents")[1].split("## Self-grading")[0].strip())
    print(f"\nsession file: {session.path}")
    if not present(cards, session, console_reader, title="BLOCK 1 — your own cards"):
        return 0
    if not present(order, session, console_reader, title="BLOCK 2 — reworded cards and held-out items"):
        return 0
    result = score(session, cards=cards, rset=rset)
    print_report(result, cards=cards, rset=rset, pset=pset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
