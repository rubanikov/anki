#!/usr/bin/env python3
"""Kill Anki desktop mid-review, twenty times, and check the database after each.

The app under test is the real thing: `aqt` with a Qt window, a real reviewer, a
real deck, and the review write running on Anki's own background op thread. The
`autoreview` add-on beside this file drives the session and writes a `B <n>`
record immediately before entering `Scheduler.answer_card` and an `E <n>` record
immediately after it returns. This script spins on that log; the moment it sees
a `B` with no matching `E` it calls `NtSuspendProcess`, re-reads the log to
confirm the process is frozen inside the write, and only then calls
`TerminateProcess`.

The freeze is what makes the kill land where it is claimed to. `TerminateProcess`
on its own is a request, not an instant death, and fired at a write it loses
roughly half the time -- the victim finishes its transaction in the microseconds
before Windows gets round to it. A frozen process cannot finish, so what reaches
the disk is a genuinely half-written review.

Three things are recorded per trial, and none of them is the killer's own
opinion of when it fired:

* the victim's `B <n>` / `E <n>` log, written with `os.write` so it survives the
  kill. A trailing `B` with no `E` is the process saying, in its own last
  syscall, that it died inside the review write.
* `pragma integrity_check` run by plain sqlite3 on a *copy* of the collection
  and its write-ahead log, so the check cannot itself repair what it measures.
* Anki's own Check Database (`Collection.fix_integrity`, the call behind
  `Tools -> Check Database`), run on the live collection.

Usage:

    PYTHONPATH="pylib;out/pylib;qt;out/qt" out/pyenv/Scripts/python.exe \
        speedrun/evidence/crash/crash_desktop.py \
        --base <throwaway> --col <collection.anki2> --trials 20 \
        --out speedrun/evidence/crash/desktop-kills.json
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ADDON_SRC = HERE / "autoreview"
PROFILE = "User 1"
DECK = "SYNTHETIC — Speedrun bench (never scored)"

PROCESS_TERMINATE = 0x0001
PROCESS_SUSPEND_RESUME = 0x0800
SYNCHRONIZE = 0x00100000
KILL_ACCESS = PROCESS_TERMINATE | PROCESS_SUSPEND_RESUME | SYNCHRONIZE


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_char * 260),
    ]


def child_pid(parent: int, timeout: float = 60.0) -> int:
    """The pid of the process the launcher actually started.

    `out/pyenv/Scripts/python.exe` is a virtualenv trampoline: it spawns a
    second process, and that second process is Anki. Suspending or terminating
    the trampoline does nothing to the app -- an earlier version of this harness
    did exactly that and reported freezing writes it had never touched. Every
    kill below targets the pid found here.
    """
    kernel32 = ctypes.windll.kernel32
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        found = None
        if kernel32.Process32First(snapshot, ctypes.byref(entry)):
            while True:
                if entry.th32ParentProcessID == parent:
                    found = entry.th32ProcessID
                    break
                if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                    break
        kernel32.CloseHandle(snapshot)
        if found:
            return found
        time.sleep(0.1)
    # No trampoline in play: the launcher is the app.
    return parent


def kill_tree(pid: int) -> None:
    """Take down a launcher and whatever it started, and wait for it to go."""
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
        check=False,
    )


def _unicase(a: str, b: str) -> int:
    """Stand-in for Anki's `unicase` collation.

    sqlite refuses to touch an index built with a collation it does not know, so
    a plain `sqlite3` connection cannot run `integrity_check` on an Anki
    collection at all without one. This is a case-insensitive compare, which is
    what `unicase` is; it is not guaranteed to order every exotic string exactly
    as the Rust crate does, which is why `quick_check` -- the structural check,
    which needs no collation -- is reported beside it.
    """
    x, y = a.casefold(), b.casefold()
    return (x > y) - (x < y)


def sqlite_integrity_check(col: Path) -> dict:
    """sqlite's own checks on a copy of the collection and its write-ahead log.

    A copy because opening the live file would let sqlite recover the log, which
    is a repair; this test is supposed to observe damage, not fix it. The `-shm`
    is deliberately not copied: it is scratch state belonging to a process that
    no longer exists, and sqlite rebuilds it from the log.
    """
    wal = col.with_name(col.name + "-wal")
    wal_bytes = wal.stat().st_size if wal.exists() else 0
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / col.name
        shutil.copy2(col, work)
        if wal.exists():
            shutil.copy2(wal, work.with_name(work.name + "-wal"))
        db = sqlite3.connect(str(work))
        db.create_collation("unicase", _unicase)
        out: dict = {"wal_bytes": wal_bytes}
        for pragma in ("quick_check", "integrity_check"):
            try:
                out[pragma] = [r[0] for r in db.execute(f"pragma {pragma}")]
            except sqlite3.DatabaseError as exc:
                out[pragma] = [f"{type(exc).__name__}: {exc}"]
        try:
            out["counts"] = {
                t: db.execute(f"select count() from {t}").fetchone()[0]
                for t in ("cards", "notes", "revlog")
            }
        except sqlite3.DatabaseError as exc:
            out["counts"] = {"error": f"{type(exc).__name__}: {exc}"}
        db.close()
    out["ok"] = out.get("quick_check") == ["ok"] and out.get("integrity_check") == ["ok"]
    return out


def anki_check_database(col: Path) -> dict:
    """Anki's own Check Database, headless, on the live collection."""
    from anki.collection import Collection

    t0 = time.perf_counter()
    try:
        collection = Collection(str(col))
    except Exception as exc:  # noqa: BLE001 - a collection that will not open is the finding
        return {"opened": False, "ok": False, "report": f"{type(exc).__name__}: {exc}"}
    report, ok = collection.fix_integrity()
    counts = {
        t: collection.db.scalar(f"select count() from {t}")
        for t in ("cards", "notes", "revlog")
    }
    collection.close()
    return {
        "opened": True,
        "ok": bool(ok),
        "report": report,
        "counts": counts,
        "secs": round(time.perf_counter() - t0, 3),
    }


def read_log(path: Path) -> dict:
    """Classify where the kill landed, from the victim's own last record."""
    if not path.exists():
        return {"answers": 0, "last": None, "died_inside_write": False}
    text = path.read_text(encoding="ascii", errors="replace")
    lines = [line for line in text.splitlines() if line[:1] in "BE"]
    answers = sum(1 for line in lines if line.startswith("E"))
    last = lines[-1] if lines else None
    return {
        "answers_completed": answers,
        "answers_started": sum(1 for line in lines if line.startswith("B")),
        "last_record": last,
        "died_inside_write": bool(last and last.startswith("B")),
    }


def launch(base: Path, env_extra: dict, log_name: str = "anki") -> subprocess.Popen:
    env = dict(os.environ)
    env["ANKI_BASE"] = str(base)
    # Anki's single-instance key is `anki<checksum(username)>` -- the same for
    # every profile and every base folder on the machine. Without a private key
    # this launch hands its arguments to whatever other Anki the user happens to
    # be running and then exits, so the test would be killing nothing. Not a
    # Speedrun bug; a fact about running the app twice at once.
    env["ANKI_SINGLE_INSTANCE_KEY"] = f"t21crash{os.getpid()}"
    env["PYTHONPATH"] = os.pathsep.join(
        str(REPO / p) for p in ("pylib", "out/pylib", "qt", "out/qt")
    )
    env.update({k: str(v) for k, v in env_extra.items()})
    # Kept rather than discarded: if a launch hangs, what the app printed on the
    # way is the only account of why.
    base.mkdir(parents=True, exist_ok=True)
    log = open(base / f"{log_name}.log", "ab")  # noqa: SIM115
    return subprocess.Popen(
        [sys.executable, "-c", "import aqt; aqt.run()"],
        env=env,
        cwd=str(REPO),
        stdout=log,
        stderr=subprocess.STDOUT,
    )


def wait_for_flag(flag_path: Path, index: int, timeout: float) -> bool:
    """Wait for the add-on to raise a byte in the shared file.

    Only used for "the reviewer is up and has graded a card, you may arm now",
    where the mapping's lag between the two processes does not matter. The kill
    itself is decided from the add-on's record log, not from here.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(flag_path, "rb") as f:
                data = f.read(8)
            if len(data) >= 8 and data[index]:
                return True
        except OSError:
            pass
        time.sleep(0.01)
    return False


def spin_and_kill(log_path: Path, pid: int, timeout: float) -> tuple[bool, float, int]:
    """Freeze the process inside the review write, confirm it, then kill it.

    `TerminateProcess` alone is a request, not an instant death: fired on the
    edge of a write it still loses about half the time, because the victim
    finishes its transaction in the microseconds before Windows gets round to
    the kill. Half the trials would then be kills at a quiescent moment, which
    prove nothing.

    So the kill is done in three steps, all of them observable:

    1. spin on the victim's own record log until its last line is a `B` with no
       matching `E`, which is the process being inside `Scheduler.answer_card`;
    2. `NtSuspendProcess`, which freezes every thread where it stands;
    3. read the log again. Still an unterminated `B` means the process is
       stopped *inside* the write. Then `TerminateProcess`.

    A frozen process cannot finish its transaction, so what hits the disk is a
    genuinely half-written review -- the state a power cut leaves behind, which
    is the thing being tested. If the byte reads 0 the process slipped out in
    time; it is resumed and the loop waits for the next write rather than
    counting a miss as a hit.

    Returns (killed_inside_write, kill_time, attempts_needed).
    """
    fd = os.open(str(log_path), os.O_RDONLY | getattr(os, "O_BINARY", 0))
    kernel32 = ctypes.windll.kernel32
    ntdll = ctypes.windll.ntdll
    handle = kernel32.OpenProcess(KILL_ACCESS, False, pid)
    if not handle:
        raise OSError(f"OpenProcess failed for pid {pid}")

    def last_record() -> str:
        """The victim's most recent flushed record.

        Read from the log rather than from a shared mmap byte. The byte was
        tried first and is not trustworthy here: the parent's view of it lags
        the child's stores enough that a stale 1 gets read after the write has
        already finished, which is how the earlier version of this function
        reported freezing inside writes it had actually missed. The log is
        written with `os.write`, so what the parent reads back through the page
        cache is what the child has actually done.
        """
        size = os.fstat(fd).st_size
        if size == 0:
            return ""
        os.lseek(fd, max(0, size - 64), os.SEEK_SET)
        tail = os.read(fd, 64).decode("ascii", "replace")
        lines = [line for line in tail.splitlines() if line[:1] in "BE"]
        return lines[-1] if lines else ""

    deadline = time.time() + timeout
    attempts = 0
    try:
        while time.time() < deadline:
            if last_record().startswith("B"):
                attempts += 1
                ntdll.NtSuspendProcess(handle)
                if last_record().startswith("B"):
                    t = time.time()
                    kernel32.TerminateProcess(handle, 1)
                    return True, t, attempts
                ntdll.NtResumeProcess(handle)
        # Never froze one inside a write: kill anyway and let the victim's log
        # say so, so the trial is reported rather than retried out of existence.
        t = time.time()
        kernel32.TerminateProcess(handle, 1)
        return False, t, attempts
    finally:
        os.close(fd)


def run_once(base: Path, state: Path, env_extra: dict, log_name: str) -> dict:
    """Start the app, wait for it to report, then take it down.

    Used for the launches whose only job is to run Anki's own Check Database and
    say what it found. The process is terminated rather than asked to quit: a
    shutdown that hangs under load would stall the test, and by the time the
    state file exists the check has already been run and written.

    Retried, because Anki calls `setupProfile` only once both of its webviews
    report `_domDone`, and on a loaded machine QtWebEngine sometimes never gets
    there. That is a start-up stall with no collection open and nothing written,
    so a retried launch is the same launch -- but it is recorded, because a
    number that needed three attempts should say so.
    """
    for attempt in range(1, 5):
        if state.exists():
            state.unlink()
        proc = launch(base, {**env_extra, "T21_STATE_FILE": state}, log_name=log_name)
        deadline = time.time() + 120
        stalled = True
        while time.time() < deadline:
            if state.exists() or proc.poll() is not None:
                stalled = False
                break
            time.sleep(0.2)
        if stalled:
            kill_tree(proc.pid)
            proc.wait(timeout=60)
            time.sleep(2)
            continue
        # Let it try to shut down on its own first; take it down if it will not.
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid)
            proc.wait(timeout=30)
        if state.exists():
            try:
                result = json.loads(state.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                result = {"parse_error": True}
            result["launch_attempts"] = attempt
            return result
    log = (base / f"{log_name}.log").read_text(errors="replace")
    raise RuntimeError(f"{log_name} never reported in 4 attempts; app said:\n{log}")


def raise_limits(col_path: Path) -> dict:
    """Lift the daily caps in the collection before the app ever opens it.

    Out of the box the deck offers 200 reviews and 20 new cards a day. Twenty
    review sessions exhaust that, and a kill after the reviewer has run out of
    cards is a kill at idle -- exactly the kind this test exists not to do. An
    earlier run of this harness raised the limits from inside the add-on
    instead, hit a proto field-path error, and produced three trials that
    answered nothing; doing it here, before the app starts, means the sessions
    cannot depend on that working.
    """
    from anki import deck_config_pb2
    from anki.collection import Collection

    col = Collection(str(col_path))
    deck_id = col.decks.id_for_name(DECK)
    current = col.decks.get_deck_configs_for_update(deck_id)
    configs = []
    for entry in current.all_config:
        deck_config = entry.config
        # `DeckConfig.config` is the nested message the limits live on.
        deck_config.config.new_per_day = 9999
        deck_config.config.reviews_per_day = 9999
        configs.append(deck_config)
    col.decks.update_deck_configs(
        deck_config_pb2.UpdateDeckConfigsRequest(
            target_deck_id=deck_id,
            configs=configs,
            removed_config_ids=[],
            mode=deck_config_pb2.UpdateDeckConfigsMode.UPDATE_DECK_CONFIGS_MODE_NORMAL,
            card_state_customizer=current.card_state_customizer,
            limits=current.current_deck.limits,
            new_cards_ignore_review_limit=current.new_cards_ignore_review_limit,
            fsrs=current.fsrs,
        )
    )
    col.decks.select(deck_id)
    counts = {
        "cards": col.db.scalar("select count() from cards"),
        "due_today": col.db.scalar(
            "select count() from cards where queue = 2 and due <= ?", col.sched.today
        ),
        "new": col.db.scalar("select count() from cards where queue = 0"),
        "revlog": col.db.scalar("select count() from revlog"),
    }
    col.close()
    return counts


def bootstrap(base: Path, source: Path) -> dict:
    """Create the profile with a throwaway launch, then plant the collection."""
    base.mkdir(parents=True, exist_ok=True)
    addons = base / "addons21"
    addons.mkdir(parents=True, exist_ok=True)
    dest = addons / "t21_autoreview"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ADDON_SRC, dest)
    (dest / "meta.json").write_text(
        json.dumps({"name": "T-21 autoreview", "disabled": False, "mod": 0}),
        encoding="utf-8",
    )

    state = base / "t21-state-bootstrap.json"
    run_once(base, state, {"T21_MODE": "bootstrap"}, log_name="anki-bootstrap")

    col = base / PROFILE / "collection.anki2"
    col.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        side = col.with_name(col.name + suffix)
        if side.exists():
            side.unlink()
    shutil.copy2(source, col)
    return raise_limits(col)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--col", required=True)
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=21)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    base = Path(args.base).resolve()
    source = Path(args.col).resolve()
    for _ in range(10):
        if not base.exists():
            break
        # A leftover Anki from an interrupted run keeps a handle on the
        # collection. Better to wait for it to go than to test a base that is
        # half the previous run's.
        shutil.rmtree(base, ignore_errors=True)
        time.sleep(1)
    if base.exists():
        raise RuntimeError(f"{base} is still in use; a previous Anki is running")
    seed_counts = bootstrap(base, source)
    print(f"seed collection: {seed_counts}", flush=True)

    col = base / PROFILE / "collection.anki2"
    flag = base / "t21-flag.bin"
    trials = []

    for trial in range(1, args.trials + 1):
        log = base / f"t21-answers-{trial:02d}.log"
        state = base / f"t21-state-{trial:02d}.json"
        # A launch that never reaches the reviewer never opened the collection
        # and never wrote to it, so it is a launch that did not happen rather
        # than a kill that missed. The count of them is reported all the same.
        stalled_launches = 0
        for attempt in range(1, 6):
            for path in (flag, log, state):
                if path.exists():
                    path.unlink()
            with open(flag, "wb") as f:
                f.write(b"\0" * 8)

            t_launch = time.time()
            proc = launch(
                base,
                {
                    "T21_MODE": "review",
                    "T21_FLAG_FILE": flag,
                    "T21_LOG_FILE": log,
                    "T21_STATE_FILE": state,
                    "T21_DECK": DECK,
                },
                log_name=f"anki-trial-{trial:02d}",
            )
            ready = wait_for_flag(flag, 1, timeout=100)
            if ready:
                break
            stalled_launches += 1
            kill_tree(proc.pid)
            proc.wait(timeout=60)
            time.sleep(2)

        # Let the session run a random while first, so the twenty kills are not
        # all the same kill at the same point in the same session.
        soak = rng.uniform(0.3, 4.0)
        time.sleep(soak)
        victim_pid = child_pid(proc.pid, timeout=30)
        inside, t_kill, freeze_attempts = spin_and_kill(log, victim_pid, timeout=30)
        try:
            rc = proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid)
            rc = proc.wait(timeout=60)
        kill_tree(proc.pid)

        # Give Windows a moment to release the file handles the dead process
        # held, then look at what it left behind.
        time.sleep(1.0)
        victim = read_log(log)
        sqlite_result = sqlite_integrity_check(col)
        anki_result = anki_check_database(col)
        in_app = {}
        if state.exists():
            try:
                in_app = json.loads(state.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                in_app = {"parse_error": True}

        record = {
            "trial": trial,
            "launcher_pid": proc.pid,
            "anki_pid": victim_pid,
            "reached_review": ready,
            "stalled_launches_before_this_one": stalled_launches,
            "soak_secs": round(soak, 2),
            "session_secs": round(t_kill - t_launch, 2),
            "killed_inside_write": inside and victim["died_inside_write"],
            "killer_froze_process_inside_write": inside,
            "freeze_attempts": freeze_attempts,
            "victim_log": victim,
            "exit_code": rc,
            "sqlite_integrity_check": sqlite_result,
            "anki_check_database": {
                k: v for k, v in anki_result.items() if k != "report"
            },
            "anki_check_database_report": anki_result.get("report", ""),
            "in_app_check_database_at_next_start": in_app.get("check_database"),
            "in_app_counts_at_start": in_app.get("counts"),
        }
        trials.append(record)
        print(
            f"trial {trial:2d}  inside_write={record['killed_inside_write']}  "
            f"answers={victim.get('answers_completed')}  "
            f"sqlite_ok={sqlite_result['ok']}  anki_ok={anki_result.get('ok')}",
            flush=True,
        )

    # One more launch so the last kill's damage is also seen by Anki's own
    # in-app Check Database, not only by the headless one.
    final = run_once(
        base,
        base / "t21-state-final.json",
        {"T21_MODE": "bootstrap"},
        log_name="anki-final",
    )

    out = {
        "collection_source": str(source),
        "seed_counts": seed_counts,
        "base": str(base),
        "deck": DECK,
        "trials": trials,
        "final_in_app_check_database": final.get("check_database"),
        "final_counts": final.get("counts"),
        "summary": {
            "trials": len(trials),
            "killed_inside_write": sum(1 for t in trials if t["killed_inside_write"]),
            "stalled_launches_total": sum(
                t.get("stalled_launches_before_this_one", 0) for t in trials
            ),
            "sqlite_clean": sum(
                1 for t in trials if t["sqlite_integrity_check"]["ok"]
            ),
            "anki_check_database_clean": sum(
                1 for t in trials if t["anki_check_database"].get("ok")
            ),
        },
    }
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out["summary"], indent=2))


if __name__ == "__main__":
    main()
