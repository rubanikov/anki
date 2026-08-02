#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Would this rewording test the fact, or the student's memory of the string?

Four mechanical checks over all 60 Reworded cards, each stated before the run
(see `wording.py` for the two thresholds and why they exclude the answer's own
words). None of them is a verdict — `QUALITY.md` is a hand read on top — but a
mechanical pass makes the hand read arguable instead of a claim.

1. **Wording reuse.** Longest shared run of consecutive words with the card, and
   content-word Jaccard. Over threshold means the item risks being a recognition
   test.
2. **Answer given away.** The card's answer, or the rewording's own stated
   answer, appearing in the rewording's prompt. An item containing its answer
   measures nothing.
3. **Fact preserved.** The rewording's stated answer against the card's answer.
   A rewording whose answer has drifted is a defect under the manifest's rule 4,
   not a rewording. Reported as an overlap fraction, because "T4; T3" and
   "thyroxine and triiodothyronine" are the same answer in different words and
   only a human can say so.
4. **The two differ from each other.** Two identical rewordings of one card are
   one rewording, and would let a card count twice.

    speedrun/agent/.venv/Scripts/python speedrun/eval/paraphrase/check_rewordings.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PARAPHRASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PARAPHRASE_DIR))

from wording import MAX_JACCARD, MAX_SHARED_RUN, content, jaccard, overlap, tokens  # noqa: E402

CARDS_FILE = PARAPHRASE_DIR / "rset_cards.local.json"
RSET_FILE = PARAPHRASE_DIR / "h4_rset.jsonl"


def load() -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    cards = {
        c["card_id"]: c for c in json.loads(CARDS_FILE.read_text(encoding="utf-8"))["cards"]
    }
    items = [
        json.loads(line)
        for line in RSET_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return cards, items


def contains(haystack: str, needle: str) -> bool:
    """Is `needle` present in `haystack` as a run of words, ignoring case?"""
    needle_tokens = tokens(needle)
    if not needle_tokens:
        return False
    hay = tokens(haystack)
    return any(
        hay[i : i + len(needle_tokens)] == needle_tokens
        for i in range(len(hay) - len(needle_tokens) + 1)
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verbose", action="store_true", help="print every item, not just flags")
    args = parser.parse_args(argv)

    cards, items = load()
    flags: dict[str, list[str]] = {"reuse": [], "gives_answer": [], "answer_drift": [], "twins": []}
    by_card: dict[int, list[dict[str, Any]]] = {}
    runs: list[int] = []
    jaccards: list[float] = []

    for item in items:
        card = cards[item["card_id"]]
        by_card.setdefault(item["card_id"], []).append(item)
        measured = overlap(card["front"], item["prompt"], card["answer"])
        runs.append(measured.shared_run)
        jaccards.append(measured.jaccard)

        if not measured.clean:
            flags["reuse"].append(f"{item['id']}  {measured.why}")
        if contains(item["prompt"], card["answer"]) or contains(item["prompt"], item["answer"]):
            flags["gives_answer"].append(f"{item['id']}  prompt contains its own answer")
        answer_overlap = jaccard(content(item["answer"]), content(card["answer"]))
        if answer_overlap < 0.34:
            flags["answer_drift"].append(
                f"{item['id']}  card answer {card['answer']!r} vs item answer "
                f"{item['answer']!r}  (overlap {answer_overlap:.2f})"
            )
        if args.verbose:
            print(
                f"{item['id']}  run={measured.shared_run} j={measured.jaccard:.2f} "
                f"ans={answer_overlap:.2f}\n    {item['prompt']}\n    -> {item['answer']}"
            )

    for card_id, pair in by_card.items():
        if len(pair) == 2:
            similarity = jaccard(content(pair[0]["prompt"]), content(pair[1]["prompt"]))
            if similarity >= 0.75:
                flags["twins"].append(
                    f"{pair[0]['id']}/{pair[1]['id']}  the two rewordings overlap {similarity:.2f}"
                )

    total = len(items)
    print(f"\n{total} reworded cards, from {len(by_card)} cards\n")
    print(f"longest shared run with the card:  max {max(runs)}, mean {sum(runs) / total:.2f}")
    print(f"content-word Jaccard:              max {max(jaccards):.2f}, mean {sum(jaccards) / total:.2f}")
    print(f"thresholds: run <= {MAX_SHARED_RUN}, jaccard < {MAX_JACCARD}\n")

    for name, title in (
        ("reuse", f"reuse the card's wording (run > {MAX_SHARED_RUN} or jaccard >= {MAX_JACCARD})"),
        ("gives_answer", "prompt contains the answer"),
        ("answer_drift", "stated answer may have drifted from the card's (needs a human)"),
        ("twins", "the two rewordings of one card are near-copies"),
    ):
        hits = flags[name]
        print(f"{title}: {len(hits)}")
        for line in hits:
            print(f"   {line}")
        print()

    mechanically_clean = total - len({f.split()[0] for f in flags["reuse"] + flags["gives_answer"]})
    print(f"mechanically clean on checks 1 and 2: {mechanically_clean} of {total}")
    print("Check 3 is advisory and check 4 is informational; both need the hand read in QUALITY.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
