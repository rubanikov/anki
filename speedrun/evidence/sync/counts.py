#!/usr/bin/env python3
"""Read-only counts over an Anki collection file.

The same SQL is run against all three collections in the T-09 test — desktop,
phone and the sync server's copy — so the numbers in the evidence are
comparable by construction. It opens sqlite directly rather than going through
`Collection`, because opening a collection can rewrite it, and a counting test
whose measurement mutates what it measures is worth nothing.

    python counts.py <collection.anki2> [label]
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

DECKS = ("SyncTest::Desktop", "SyncTest::Phone", "SyncTest::Conflict")


def deck_ids(db: sqlite3.Connection) -> dict[str, int]:
    ids = {}
    for did, name in db.execute("select id, name from decks"):
        # decks table stores '\x1f' as the separator
        ids[name.replace("\x1f", "::")] = did
    return ids


def counts(path: Path, label: str | None = None) -> dict:
    # Copy the database and any write-ahead log to a scratch directory before
    # reading. AnkiDroid leaves recent reviews in the -wal file, so counting the
    # .anki2 alone silently under-reports; and opening the live file to replay
    # the log would write to a collection the test is supposed to observe.
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / path.name
        shutil.copy2(path, work)
        for suffix in ("-wal", "-shm"):
            side = path.with_name(path.name + suffix)
            if side.exists():
                shutil.copy2(side, work.with_name(work.name + suffix))
        return _counts_of(work, path, label)


def _counts_of(work: Path, original: Path, label: str | None) -> dict:
    db = sqlite3.connect(work)
    path = original
    try:
        ids = deck_ids(db)
        by_deck = {}
        for deck in DECKS:
            did = ids.get(deck)
            by_deck[deck] = db.execute(
                "select count(*) from revlog where cid in"
                " (select id from cards where did = ?)",
                (did,),
            ).fetchone()[0]
        result = {
            "label": label or path.name,
            "path": str(path),
            "revlog_total": db.execute("select count(*) from revlog").fetchone()[0],
            "revlog_distinct_ids": db.execute(
                "select count(distinct id) from revlog"
            ).fetchone()[0],
            "revlog_by_deck": by_deck,
            "cards": db.execute("select count(*) from cards").fetchone()[0],
            "notes": db.execute("select count(*) from notes").fetchone()[0],
            "cards_with_reps": db.execute(
                "select count(*) from cards where reps > 0"
            ).fetchone()[0],
            "sum_card_reps": db.execute(
                "select coalesce(sum(reps), 0) from cards"
            ).fetchone()[0],
        }
        # Identified by note text, not by deck: notes added later can land in the
        # same deck, and "the first card in the deck" would then silently start
        # reporting a different card.
        row = db.execute(
            "select c.id, c.mod, c.type, c.queue, c.due, c.ivl, c.factor,"
            " c.reps, c.lapses from cards c join notes n on n.id = c.nid"
            " where n.sfld = 'Conflict 01'",
        ).fetchone()
        if row:
            keys = (
                "id",
                "mod",
                "type",
                "queue",
                "due",
                "ivl",
                "factor",
                "reps",
                "lapses",
            )
            card = dict(zip(keys, row))
            card["revlog"] = [
                dict(zip(("id", "ease", "ivl", "lastIvl", "factor", "time", "type"), r))
                for r in db.execute(
                    "select id, ease, ivl, lastIvl, factor, time, type from revlog"
                    " where cid = ? order by id",
                    (card["id"],),
                )
            ]
            result["conflict_card"] = card
        return result
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    label = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(counts(Path(sys.argv[1]), label), indent=2))
