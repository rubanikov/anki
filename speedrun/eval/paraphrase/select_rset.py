#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Draw the 30 cards of the R-set (H4), by the manifest's rule and nothing else.

The selection rule was frozen in `speedrun/eval/holdout/MANIFEST.md` before any
card was looked at, and this script is that rule written out:

1. Eligible: cards in the demo section that the Crosswalk maps to a Topic and
   that carry **>= 3 graded reviews** at selection time. Unmapped cards are not
   eligible.
2. Sort eligible cards by card id ascending, then take a sample of **30** using
   `random.Random(20260802).sample(...)`.

The seed is the manifest's, hard-coded here rather than exposed as a flag: a
seed you can pass on the command line is a seed you can re-roll, and the point
of writing it down in advance was that nobody re-rolls it.

**The deviation this run makes, stated up front.** Step 1's review filter cannot
be satisfied. The only Collection this project has is `miledown.apkg`, a pristine
shared deck whose `revlog` table is empty and whose 2,888 cards all have
`reps = 0` — `speedrun/eval/deck/DECK_REPORT.md` flagged this at acquisition.
Nobody has studied it, because studying it needs the participant the paraphrase
test itself is waiting on. Applied literally the rule yields **zero** eligible
cards and no R-set at all.

So the review filter is applied and reported, and when it removes everything the
draw runs over the mapped cards with `--no-study-history`, which prints the
deviation on every run and writes it into the selection file. That is not the
manifest's rule and this script does not pretend otherwise: it is the manifest's
rule with one clause that cannot be evaluated yet, named rather than deleted.
The clause is doing the same work as the rest of this ticket's scope limit — the
first of the three numbers, recall on the student's own card, is undefined for a
card nobody has reviewed, so a set drawn without study history is a set to be
used *after* someone studies it, not a shortcut around them.

Point `--collection` at a studied collection and the filter applies for real,
the deviation flag is refused, and the draw is the manifest's rule exactly.

Usage (from the repo root):

    speedrun/agent/.venv/Scripts/python speedrun/eval/paraphrase/select_rset.py --report
    speedrun/agent/.venv/Scripts/python speedrun/eval/paraphrase/select_rset.py --draw --no-study-history
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import re
import sqlite3
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PARAPHRASE_DIR = Path(__file__).resolve().parent
SPEEDRUN_DIR = PARAPHRASE_DIR.parents[1]
REPO_ROOT = SPEEDRUN_DIR.parent

DEFAULT_COLLECTION = SPEEDRUN_DIR / "eval" / "deck" / "miledown.apkg"
CROSSWALK = SPEEDRUN_DIR / "crosswalk" / "miledown-bb-v1.json"

#: Committed: card ids, topics, hashes. No card text.
SELECTION_FILE = PARAPHRASE_DIR / "rset_selection.json"
#: Not committed: the deck author's card text, which the harness needs to show
#: the student and which this project has no licence to redistribute.
CARDS_FILE = PARAPHRASE_DIR / "rset_cards.local.json"

#: MANIFEST.md, H4, selection rule step 2. Not a parameter.
SEED = 20260802
DRAW = 30
#: MANIFEST.md, H4, selection rule step 1.
MIN_GRADED_REVIEWS = 3

# --------------------------------------------------------------------------
# The collection
# --------------------------------------------------------------------------


def open_collection(path: Path) -> tuple[sqlite3.Connection, Path]:
    """A read-only handle on a collection, whether it is an `.apkg` or a db.

    Anki is never imported and no profile is touched: this is `zipfile` plus
    `sqlite3`, the same way `DECK_REPORT.md` read the deck.
    """
    if path.suffix.lower() in {".apkg", ".colpkg"}:
        tmp = Path(tempfile.mkdtemp(prefix="rset-"))
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.endswith((".anki2", ".anki21"))]
            if not names:
                raise SystemExit(f"{path} contains no collection database")
            # `collection.anki21` is the newer half of a dual-format package and
            # wins where both are present.
            name = sorted(names)[-1]
            archive.extract(name, tmp)
        return sqlite3.connect(tmp / name), tmp / name
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True), path


def deck_names(con: sqlite3.Connection) -> dict[int, str]:
    """Deck id -> full path, from either schema-11 `col.decks` or the `decks` table."""
    try:
        blob = con.execute("select decks from col").fetchone()[0]
        if blob:
            return {int(k): v["name"].replace("\x1f", "::") for k, v in json.loads(blob).items()}
    except (sqlite3.OperationalError, json.JSONDecodeError, TypeError, KeyError):
        pass
    rows = con.execute("select id, name from decks").fetchall()
    return {int(i): n.replace("\x1f", "::") for i, n in rows}


# --------------------------------------------------------------------------
# The Crosswalk, applied exactly as its README describes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    tag: str
    topic: str | None
    decks: tuple[str, ...] = ()


def load_crosswalk(path: Path) -> list[Entry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        Entry(
            tag=e["tag"].casefold(),
            topic=e.get("topic"),
            decks=tuple(d.casefold() for d in e.get("decks", ())),
        )
        for e in data["entries"]
    ]


def topic_for(tags: list[str], deck_path: str, entries: list[Entry]) -> str | None:
    """First matching entry wins; a match covers the tag and everything beneath it.

    `decks` narrows an entry and never selects one — an entry with a deck list
    simply does not apply outside those decks, and the search continues.
    Returning `None` covers both "no entry matched" and "the entry that matched
    is a refusal": neither is a mapped card, and rule 1 makes both ineligible.
    """
    folded_tags = [t.casefold() for t in tags]
    folded_deck = deck_path.casefold()
    for entry in entries:
        if entry.decks and not any(folded_deck.startswith(d) for d in entry.decks):
            continue
        for tag in folded_tags:
            if tag == entry.tag or tag.startswith(entry.tag + "::"):
                return entry.topic
    return None


# --------------------------------------------------------------------------
# Card text
# --------------------------------------------------------------------------

CLOZE = re.compile(r"\{\{c(\d+)::(.+?)\}\}", re.DOTALL)
TAGSTRIP = re.compile(r"<[^>]+>")
IMG = re.compile(r"<img[^>]*>", re.IGNORECASE)
BREAK = re.compile(r"<(br|/div|/p|/li)[^>]*>", re.IGNORECASE)


def plain(text: str) -> str:
    """HTML field -> reading text, with images marked rather than silently dropped."""
    text = IMG.sub(" [image] ", text)
    text = BREAK.sub("\n", text)
    # Tags close up rather than becoming spaces: `T<sub>4</sub>` is "T4", and a
    # subscript turned into a space reads as two words the card never had.
    # Block-level breaks are already newlines by the line above.
    text = TAGSTRIP.sub("", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln).strip()


def cloze_faces(field_text: str, ordinal: int) -> tuple[str, str]:
    """(front, answer) for the cloze card at `ordinal` (0-based, so cloze c{ord+1}).

    Anki shows the target deletion as `[...]` and reveals every other deletion,
    which is what a student actually reads, so that is what is reconstructed.
    A `::hint` is part of the prompt, not part of the answer.
    """
    target = ordinal + 1
    answers: list[str] = []

    def render(match: re.Match[str]) -> str:
        index = int(match.group(1))
        body = match.group(2)
        content, _, hint = body.partition("::")
        if index == target:
            answers.append(content)
            return f"[{hint.strip()}]" if hint.strip() else "[...]"
        return content

    front = CLOZE.sub(render, field_text)
    return plain(front), plain("; ".join(answers))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Eligibility
# --------------------------------------------------------------------------


@dataclass
class Card:
    card_id: int
    note_id: int
    ordinal: int
    topic: str
    deck: str
    tags: list[str]
    graded_reviews: int
    front: str = ""
    answer: str = ""
    extra: str = ""
    text_usable: bool = field(default=True)


def graded_review_counts(con: sqlite3.Connection) -> dict[int, int]:
    """Reviews per card, counting only *graded* ones.

    `revlog.ease = 0` is a manual reschedule or a set-due-date, not an answer;
    counting those as reviews would let a card qualify for the R-set without the
    student ever having graded it.
    """
    try:
        rows = con.execute("select cid, count(*) from revlog where ease > 0 group by cid")
    except sqlite3.OperationalError:
        return {}
    return {int(cid): int(n) for cid, n in rows}


def eligible_cards(con: sqlite3.Connection, entries: list[Entry]) -> tuple[list[Card], dict[str, int]]:
    decks = deck_names(con)
    reviews = graded_review_counts(con)
    notes = {
        int(nid): (tags, flds)
        for nid, tags, flds in con.execute("select id, tags, flds from notes")
    }
    counts = {"cards": 0, "mapped": 0, "with_reviews": 0}
    cards: list[Card] = []
    for cid, nid, did, odid, ordinal in con.execute(
        "select id, nid, did, odid, ord from cards"
    ):
        counts["cards"] += 1
        note = notes.get(int(nid))
        if note is None:
            continue
        tags = [t for t in str(note[0]).split() if t]
        deck = decks.get(int(odid) or int(did), "")
        topic = topic_for(tags, deck, entries)
        if topic is None:
            continue
        counts["mapped"] += 1
        graded = reviews.get(int(cid), 0)
        if graded >= MIN_GRADED_REVIEWS:
            counts["with_reviews"] += 1
        front, answer = cloze_faces(str(note[1]).split("\x1f")[0], int(ordinal))
        extra_field = str(note[1]).split("\x1f")
        cards.append(
            Card(
                card_id=int(cid),
                note_id=int(nid),
                ordinal=int(ordinal),
                topic=topic,
                deck=deck,
                tags=tags,
                graded_reviews=graded,
                front=front,
                answer=answer,
                extra=plain(extra_field[1]) if len(extra_field) > 1 else "",
                # A card whose prompt is a picture cannot be reworded into a
                # sentence. Recorded, never used to filter — see --draw.
                text_usable=bool(answer.strip()) and len(front.replace("[image]", "").split()) >= 4,
            )
        )
    return cards, counts


# --------------------------------------------------------------------------
# The draw
# --------------------------------------------------------------------------


def draw(cards: list[Card], *, use_review_filter: bool) -> list[Card]:
    pool = [c for c in cards if c.graded_reviews >= MIN_GRADED_REVIEWS] if use_review_filter else list(cards)
    pool.sort(key=lambda c: c.card_id)  # rule 2: ascending card id, then sample
    if len(pool) < DRAW:
        raise SystemExit(
            f"only {len(pool)} eligible card(s); the rule draws {DRAW}. "
            "Nothing here re-rolls or relaxes the rule to make a set."
        )
    return random.Random(SEED).sample(pool, DRAW)


def selection_record(picked: list[Card], counts: dict[str, int], *, collection: Path, deviated: bool) -> dict[str, Any]:
    return {
        "what": "The 30 cards of the R-set (H4), drawn by MANIFEST.md's frozen rule.",
        "rule": {
            "source": "speedrun/eval/holdout/MANIFEST.md, section H4, selection rule",
            "seed": SEED,
            "draw": DRAW,
            "min_graded_reviews": MIN_GRADED_REVIEWS,
            "sort": "card id ascending, then random.Random(seed).sample",
        },
        "collection": {
            "path": str(collection.relative_to(REPO_ROOT)) if collection.is_relative_to(REPO_ROOT) else str(collection),
            "sha256": sha256_file(collection),
            "cards": counts["cards"],
            "crosswalk_mapped": counts["mapped"],
            "mapped_with_3_or_more_graded_reviews": counts["with_reviews"],
        },
        "crosswalk": "speedrun/crosswalk/miledown-bb-v1.json",
        "deviation": (
            {
                "clause": "step 1, '>= 3 graded reviews at selection time'",
                "applied": False,
                "why": (
                    "The collection has no study history at all (revlog empty, every "
                    "card reps=0), so the clause removes every card and the rule "
                    "yields no set. It is named here rather than deleted. The first "
                    "of the paraphrase test's three numbers - recall on the student's "
                    "own card - is undefined for an unstudied card, so this set is "
                    "usable only after a participant studies the deck, which is the "
                    "same participant the test is waiting on."
                ),
                "how_to_remove": (
                    "Re-run select_rset.py --draw --collection <a studied collection>. "
                    "The filter then applies and --no-study-history is refused."
                ),
            }
            if deviated
            else {"clause": "step 1", "applied": True}
        ),
        "no_card_text": (
            "Only card ids, note ids, topics and hashes are recorded here. The deck's "
            "card text is the author's and is never committed; the harness reads it "
            "from rset_cards.local.json, which is .gitignore'd."
        ),
        "cards": [
            {
                "card_id": c.card_id,
                "note_id": c.note_id,
                "ordinal": c.ordinal,
                "topic": c.topic,
                "graded_reviews": c.graded_reviews,
                "front_sha256": sha256(c.front),
                "answer_sha256": sha256(c.answer),
                "text_usable": c.text_usable,
            }
            for c in picked
        ],
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def cards_record(picked: list[Card]) -> dict[str, Any]:
    return {
        "what": "Card text for the 30 R-set cards. NOT COMMITTED - the deck author's work.",
        "cards": [
            {
                "card_id": c.card_id,
                "topic": c.topic,
                "front": c.front,
                "answer": c.answer,
                "extra": c.extra,
                "tags": c.tags,
                "deck": c.deck,
            }
            for c in picked
        ],
    }


# --------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--collection", type=Path, default=DEFAULT_COLLECTION)
    parser.add_argument("--report", action="store_true", help="counts only; writes nothing")
    parser.add_argument("--draw", action="store_true", help="draw the 30 and write both files")
    parser.add_argument(
        "--no-study-history",
        action="store_true",
        help="the collection has no reviews: skip step 1's review filter and say so",
    )
    args = parser.parse_args(argv)

    if not args.collection.exists():
        raise SystemExit(f"no collection at {args.collection}")
    con, _ = open_collection(args.collection)
    entries = load_crosswalk(CROSSWALK)
    cards, counts = eligible_cards(con, entries)

    print(f"collection            {args.collection}")
    print(f"cards                 {counts['cards']}")
    print(f"crosswalk-mapped      {counts['mapped']}")
    print(f">= {MIN_GRADED_REVIEWS} graded reviews    {counts['with_reviews']}")

    if counts["with_reviews"] == 0 and not args.no_study_history:
        print()
        print(
            "No card in this collection has been graded even once, so the manifest's\n"
            "step-1 filter leaves nothing to draw from. This is the pristine shared\n"
            "deck DECK_REPORT.md flagged: it is a Crosswalk input, not a studied\n"
            "Collection. Re-run against a studied collection, or pass\n"
            "--no-study-history to draw without that clause and have the deviation\n"
            "recorded in rset_selection.json."
        )
        return 1 if args.draw else 0

    if args.no_study_history and counts["with_reviews"] > 0:
        raise SystemExit(
            "--no-study-history refused: this collection does have graded reviews, "
            "so the manifest's filter applies and must not be skipped."
        )

    if not args.draw:
        usable = sum(1 for c in cards if c.text_usable)
        print(f"text-usable (of mapped) {usable}")
        return 0

    picked = draw(cards, use_review_filter=not args.no_study_history)
    SELECTION_FILE.write_text(
        json.dumps(
            selection_record(picked, counts, collection=args.collection, deviated=args.no_study_history),
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    CARDS_FILE.write_text(
        json.dumps(cards_record(picked), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print()
    print(f"drew {len(picked)} cards, seed {SEED}")
    print(f"  topics: {json.dumps(_tally(picked), ensure_ascii=False)}")
    print(f"  not text-usable: {[c.card_id for c in picked if not c.text_usable] or 'none'}")
    print(f"wrote {SELECTION_FILE.relative_to(REPO_ROOT)}")
    print(f"wrote {CARDS_FILE.relative_to(REPO_ROOT)}   (must not be committed)")
    return 0


def _tally(cards: list[Card]) -> dict[str, int]:
    out: dict[str, int] = {}
    for card in cards:
        out[card.topic] = out.get(card.topic, 0) + 1
    return dict(sorted(out.items()))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
