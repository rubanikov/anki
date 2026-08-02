# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Throwaway add-on that drives a real Anki desktop review session, and tells
an outside process the exact instant a review write is in flight.

It exists only for the T-21 crash evidence and is never installed into a real
profile. `crash_desktop.py` copies it into a throwaway `ANKI_BASE` before each
launch and configures it entirely through environment variables.

Why it is shaped this way
-------------------------
Killing Anki at an arbitrary moment proves nothing: almost all of a review
session is the app waiting for a keystroke, and a process killed while idle was
never going to corrupt anything. So this add-on appends a `B <n>` record
immediately before `Scheduler.answer_card` -- the call that reaches
`answer_card_raw` in the Rust backend and runs the whole review transaction --
and an `E <n>` record immediately after it returns.

The records go out with `os.write`, which is a syscall rather than a buffered
write, so the bytes are in the OS page cache before the function returns: the
killer can read them live, and they survive the process being killed. A trailing
`B` with no matching `E` is therefore both the killer's trigger and, afterwards,
the victim's own account of having died inside the review write.

A byte in a shared mmap is also maintained, and is deliberately *not* what the
killer trusts. It was the first design and it is not reliable here -- the
parent's view of the mapping lags the child's stores by enough that a stale 1
gets read after a write has finished. It is kept only as the "the reviewer is up,
you may arm now" signal, where lag does not matter.

Environment
-----------
    T21_FLAG_FILE   mmapped file, byte 0 = "inside answer_card", byte 1 = "ready"
    T21_LOG_FILE    unbuffered B/E record log
    T21_STATE_FILE  json written on startup: check-database result, counts
    T21_DECK        deck to review
    T21_MODE        "bootstrap" (create the profile and quit) or "review"
"""

from __future__ import annotations

import json
import mmap
import os
import time

from aqt import gui_hooks, mw
from aqt.qt import QTimer

FLAG_FILE = os.environ.get("T21_FLAG_FILE")
LOG_FILE = os.environ.get("T21_LOG_FILE")
STATE_FILE = os.environ.get("T21_STATE_FILE")
DECK = os.environ.get("T21_DECK", "")
MODE = os.environ.get("T21_MODE", "review")

_flag: mmap.mmap | None = None
_log_fd: int | None = None
_answers = 0


def _open_shared() -> None:
    global _flag, _log_fd
    if FLAG_FILE:
        if not os.path.exists(FLAG_FILE) or os.path.getsize(FLAG_FILE) < 8:
            with open(FLAG_FILE, "wb") as f:
                f.write(b"\0" * 8)
        fd = os.open(FLAG_FILE, os.O_RDWR | getattr(os, "O_BINARY", 0))
        _flag = mmap.mmap(fd, 8)
    if LOG_FILE:
        _log_fd = os.open(
            LOG_FILE,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0),
        )


def _record(line: str) -> None:
    if _log_fd is not None:
        # os.write, not a buffered file object: the bytes reach the OS before
        # this function returns, so they are still there after the kill.
        os.write(_log_fd, line.encode("ascii"))


def _patch_answer_card() -> None:
    """Wrap the scheduler call the reviewer makes, and nothing else."""
    from anki.scheduler.v3 import Scheduler

    if getattr(Scheduler, "_t21_patched", False):
        return
    original = Scheduler.answer_card

    def wrapped(self, input):  # noqa: A002, ANN001, ANN202
        global _answers
        _answers += 1
        n = _answers
        _record(f"B {n} {time.time():.6f}\n")
        if _flag is not None:
            _flag[0] = 1
        try:
            return original(self, input)
        finally:
            if _flag is not None:
                _flag[0] = 0
            _record(f"E {n} {time.time():.6f}\n")

    Scheduler.answer_card = wrapped
    Scheduler._t21_patched = True


def _check_database_in_app() -> dict:
    """Anki's own Check Database, run in the app before anything is written.

    This is the same `check_database` backend call `Tools -> Check Database`
    makes. It runs first thing on profile open, so the result belongs to the
    state the previous kill left behind, before this session touches anything.
    """
    t0 = time.perf_counter()
    report, ok = mw.col.fix_integrity()
    return {
        "ok": bool(ok),
        "report": report,
        "secs": round(time.perf_counter() - t0, 3),
    }


def _counts() -> dict:
    return {
        "cards": mw.col.db.scalar("select count() from cards"),
        "notes": mw.col.db.scalar("select count() from notes"),
        "revlog": mw.col.db.scalar("select count() from revlog"),
        "graves": mw.col.db.scalar("select count() from graves"),
    }


def _write_state(**extra) -> None:  # noqa: ANN003
    if not STATE_FILE:
        return
    state = {"pid": os.getpid(), "mode": MODE, **extra}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())


def _raise_limits() -> None:
    """Let the session review without hitting a daily cap.

    A kill that landed after the deck ran out of cards would be a kill at idle,
    which is the thing this test exists not to do.
    """
    from anki import deck_config_pb2

    deck_id = mw.col.decks.id_for_name(DECK) if DECK else mw.col.decks.selected()
    current = mw.col.decks.get_deck_configs_for_update(deck_id)
    configs = []
    for entry in current.all_config:
        deck_config = entry.config
        # `DeckConfig.config` is the nested message the limits live on.
        deck_config.config.new_per_day = 9999
        deck_config.config.reviews_per_day = 9999
        configs.append(deck_config)
    req = deck_config_pb2.UpdateDeckConfigsRequest(
        target_deck_id=deck_id,
        configs=configs,
        removed_config_ids=[],
        mode=deck_config_pb2.UpdateDeckConfigsMode.UPDATE_DECK_CONFIGS_MODE_NORMAL,
        card_state_customizer=current.card_state_customizer,
        limits=current.current_deck.limits,
        new_cards_ignore_review_limit=current.new_cards_ignore_review_limit,
        fsrs=current.fsrs,
    )
    mw.col.decks.update_deck_configs(req)


def _drive() -> None:
    """One step of a real review: show the answer, or grade what is showing."""
    reviewer = mw.reviewer
    if mw.state != "review":
        return
    if reviewer.state == "question":
        reviewer._showAnswer()
    elif reviewer.state == "answer":
        # Mostly "Again", so the learning queue keeps refilling and the session
        # never runs dry mid-trial.
        reviewer._answerCard(1 if _answers % 4 else 3)
        if _flag is not None and _answers >= 1:
            _flag[1] = 1  # the outside killer may arm now


def _start(_profile=None) -> None:  # noqa: ANN001
    _open_shared()
    check = _check_database_in_app()
    counts = _counts()
    _write_state(check_database=check, counts=counts, started_ms=int(time.time() * 1000))

    if MODE == "bootstrap":
        # Only here to create the profile and report the check above; leave
        # without writing. The harness does not depend on this working -- it
        # terminates the process once the state file lands -- because an app
        # that will not shut down cleanly must not be able to stall the test.
        QTimer.singleShot(300, mw.unloadProfileAndExit)
        return

    _patch_answer_card()
    try:
        _raise_limits()
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        _record(f"# raise_limits failed: {type(exc).__name__}: {exc}\n")

    if DECK:
        did = mw.col.decks.id_for_name(DECK)
        if did:
            mw.col.decks.select(did)
    mw.moveToState("review")

    timer = QTimer(mw)
    timer.setInterval(0)  # as fast as the event loop will go
    timer.timeout.connect(_drive)
    timer.start()
    mw._t21_timer = timer


gui_hooks.profile_did_open.append(_start)
