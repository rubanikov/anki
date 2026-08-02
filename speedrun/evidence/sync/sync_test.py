#!/usr/bin/env python3
"""Desktop side of the T-09 two-device sync test.

Drives a real Anki collection through the fork's own backend: the same
rslib sync code AnkiDroid runs, just without the Qt window in the way, so
every count in the evidence comes from the engine rather than from a
screenshot someone read off by eye.

Run it with the fork's dev interpreter, from the repo root:

    SYNC_ENDPOINT=http://127.0.0.1:27701/ \\
    out/pyenv/Scripts/python.exe speedrun/evidence/sync/sync_test.py counts <col>

Subcommands:
    init <col>                      create the test collection and decks
    sync <col>                      normal sync (full up/down if required)
    review <col> <deck> <n> <ease>  answer n cards of <deck> with <ease> (1-4)
    note <col> <deck> <front>       add one note (stands in for an Attempt)
    notes <col> <substring>         list notes whose sort field matches
    counts <col>                    revlog/card/note counts, as JSON
    card <col> <front>              one card's scheduling state, as JSON
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for extra in ("pylib", "out/pylib"):
    p = str(REPO / extra)
    if p not in sys.path:
        sys.path.insert(0, p)

from anki.collection import Collection  # noqa: E402
from anki.scheduler.v3 import CardAnswer  # noqa: E402

ENDPOINT = os.environ.get("SYNC_ENDPOINT", "http://127.0.0.1:27701/")
USER = os.environ.get("SYNC_TEST_USER", "speedrun")
PASSWORD = os.environ.get("SYNC_TEST_PASS", "speedrun")

DESKTOP_DECK = "SyncTest::Desktop"
PHONE_DECK = "SyncTest::Phone"
CONFLICT_DECK = "SyncTest::Conflict"

RATINGS = {
    1: CardAnswer.AGAIN,
    2: CardAnswer.HARD,
    3: CardAnswer.GOOD,
    4: CardAnswer.EASY,
}


def cmd_init(col: Collection) -> dict:
    basic = col.models.by_name("Basic")
    made = {}
    for deck, count in ((DESKTOP_DECK, 10), (PHONE_DECK, 10), (CONFLICT_DECK, 1)):
        did = col.decks.id(deck)
        short = deck.split("::")[-1]
        for i in range(count):
            note = col.new_note(basic)
            note["Front"] = f"{short} {i + 1:02d}"
            note["Back"] = f"answer {short.lower()} {i + 1:02d}"
            col.add_note(note, did)
        made[deck] = count
    return {"decks": made}


def cmd_sync(col: Collection) -> dict:
    auth = col.sync_login(USER, PASSWORD, ENDPOINT)
    out = col.sync_collection(auth, False)
    result = {"required": _required_name(out.required)}
    if out.required in (out.FULL_SYNC, out.FULL_UPLOAD, out.FULL_DOWNLOAD):
        upload = out.required != out.FULL_DOWNLOAD
        col.full_upload_or_download(
            auth=auth, server_usn=out.server_media_usn, upload=upload
        )
        result["full_sync"] = "upload" if upload else "download"
    return result


def _required_name(value: int) -> str:
    from anki import sync_pb2

    return sync_pb2.SyncCollectionResponse.ChangesRequired.Name(value)


def cmd_review(col: Collection, deck: str, count: int, ease: int) -> dict:
    did = col.decks.id_for_name(deck)
    if did is None:
        raise SystemExit(f"no such deck: {deck}")
    col.decks.select(did)
    answered = []
    for _ in range(count):
        queued = col.sched.get_queued_cards(fetch_limit=1)
        if not queued.cards:
            raise SystemExit(f"{deck} ran out of cards after {len(answered)}")
        qc = queued.cards[0]
        card = col.get_card(qc.card.id)
        card.start_timer()
        answer = col.sched.build_answer(
            card=card, states=qc.states, rating=RATINGS[ease]
        )
        col.sched.answer_card(answer)
        answered.append({"card_id": card.id, "front": card.note().fields[0]})
        # keep revlog ids (epoch ms) comfortably distinct
        time.sleep(0.05)
    return {"deck": deck, "ease": ease, "answered": answered}


def cmd_note(col: Collection, deck: str, front: str) -> dict:
    """Add one note, standing in for an Attempt record created on this device."""
    did = col.decks.id(deck)
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = front
    note["Back"] = "created offline"
    col.add_note(note, did)
    return {"note_id": note.id, "guid": note.guid, "front": front, "deck": deck}


def cmd_notes(col: Collection, like: str) -> dict:
    rows = col.db.all(
        "select id, guid, sfld from notes where sfld like ? order by id", f"%{like}%"
    )
    return {
        "matching": [dict(zip(("id", "guid", "front"), r)) for r in rows],
        "count": len(rows),
        "notes_total": col.db.scalar("select count() from notes"),
    }


def cmd_counts(col: Collection) -> dict:
    db = col.db
    per_deck = {}
    for deck in (DESKTOP_DECK, PHONE_DECK, CONFLICT_DECK):
        did = col.decks.id_for_name(deck)
        per_deck[deck] = db.scalar(
            "select count() from revlog where cid in (select id from cards where did = ?)",
            did,
        )
    return {
        "revlog_total": db.scalar("select count() from revlog"),
        "revlog_by_deck": per_deck,
        "cards": db.scalar("select count() from cards"),
        "notes": db.scalar("select count() from notes"),
        "cards_with_reps": db.scalar("select count() from cards where reps > 0"),
        "sum_card_reps": db.scalar("select coalesce(sum(reps), 0) from cards"),
    }


def cmd_card(col: Collection, front: str) -> dict:
    row = col.db.first(
        "select c.id, c.mod, c.type, c.queue, c.due, c.ivl, c.factor, c.reps,"
        " c.lapses, c.usn from cards c join notes n on n.id = c.nid"
        " where n.sfld = ?",
        front,
    )
    if row is None:
        raise SystemExit(f"no card with front {front!r}")
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
        "usn",
    )
    card = dict(zip(keys, row))
    card["revlog"] = [
        dict(zip(("id", "ease", "ivl", "lastIvl", "factor", "time", "type"), r))
        for r in col.db.all(
            "select id, ease, ivl, lastIvl, factor, time, type from revlog"
            " where cid = ? order by id",
            card["id"],
        )
    ]
    return card


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2:
        raise SystemExit(__doc__)
    command, path, rest = args[0], args[1], args[2:]
    col = Collection(path)
    try:
        if command == "init":
            result = cmd_init(col)
        elif command == "sync":
            result = cmd_sync(col)
        elif command == "review":
            result = cmd_review(col, rest[0], int(rest[1]), int(rest[2]))
        elif command == "note":
            result = cmd_note(col, rest[0], rest[1])
        elif command == "notes":
            result = cmd_notes(col, rest[0])
        elif command == "counts":
            result = cmd_counts(col)
        elif command == "card":
            result = cmd_card(col, rest[0])
        else:
            raise SystemExit(f"unknown command: {command}")
    finally:
        col.close()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
