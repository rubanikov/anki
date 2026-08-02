#!/usr/bin/env python3
"""Kill AnkiDroid mid-review, twenty times, and check the database after each.

Same test as `crash_desktop.py`, against the app that actually runs on a phone.
The differences are all forced by the platform:

* **Driving the review.** AnkiDroid maps `KEYCODE_SPACE` to "show answer" on the
  question side and to "Good" on the answer side, so one stream of key events is
  a real review session going through the real reviewer -- not a script calling
  the scheduler behind the UI's back.
* **Finding the write, and failing to.** There is no add-on mechanism on
  Android, so two triggers were tried and both are measurably too late. The
  app's own log line (`Reviewer.answerCardInner`, printed immediately before the
  call into the backend) arrives through `logcat` about 150 ms after the fact --
  recorded per trial as `freeze_lag_ms`. Injecting the grading keypress and
  freezing a tuned delay later does not do better: `input keyevent` waits for the
  app to finish handling the event, and the review has committed by the time it
  returns, at every delay from 0 to 30 ms. **No Android kill in this run landed
  inside a transaction**, and `frozen_inside_write` says so per trial rather than
  quietly claiming otherwise. That property is demonstrated on the desktop half,
  against the same `rslib` engine and the same sqlite WAL configuration.
* **Proving where it landed.** The number of answers the app announced is
  compared with the number of reviews that actually reached the database. Equal
  means the last transaction committed before the kill; one short would mean it
  did not. `revlog_without_wal` records how much of the collection existed only
  in the write-ahead log at the moment of the kill -- which is what makes the
  recovery on the next launch load-bearing rather than decorative.
* **Checking the database.** `KEYCODE_C` on the deck picker is AnkiDroid's own
  Check Database shortcut, so the check runs in the app, on the device, against
  the collection the kill just left behind. Its result dialog is read back off
  the screen. `pragma quick_check`/`integrity_check` is also run host-side on a
  pulled copy, so there is one measurement the app is not responsible for.

Usage:

    python speedrun/evidence/crash/crash_android.py \
        --col <collection.anki2> --trials 20 --out android-kills.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for _extra in ("pylib", "out/pylib"):
    _p = str(REPO / _extra)
    if _p not in sys.path:
        sys.path.insert(0, _p)

ADB = os.environ.get(
    "ADB",
    str(Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb.exe"),
)
PKG = "com.ichi2.anki.debug"
COL_DIR = f"/storage/emulated/0/Android/data/{PKG}/files/AnkiDroid"
COL = f"{COL_DIR}/collection.anki2"
WAL = f"{COL}-wal"

KEYCODE_C = 31  # deck picker: Check Database
KEYCODE_SPACE = 62  # reviewer: show answer / Good
DECK_MATCH = "SYNTHETIC"


def adb(*args: str, timeout: int = 120) -> str:
    out = subprocess.run(
        [ADB, *args], capture_output=True, text=True, timeout=timeout, encoding="utf-8"
    )
    return (out.stdout or "") + (out.stderr or "")


def sh(cmd: str, timeout: int = 120) -> str:
    return adb("shell", cmd, timeout=timeout)


def pid_of() -> int | None:
    out = sh(f"pidof {PKG}").strip()
    return int(out.split()[0]) if out.split() else None


def top_activity() -> str:
    out = sh("dumpsys activity activities | grep -m1 ResumedActivity")
    m = re.search(r"com\.ichi2\.anki\.debug/([\w.]+)", out)
    return m.group(1) if m else out.strip()


def ui_dump(attempts: int = 8) -> ET.Element | None:
    """The screen, as a tree.

    Retried, because `uiautomator dump` refuses with "could not get idle state"
    whenever anything on screen is still animating -- and on a loaded host the
    emulator's animations can take seconds to settle. A failed dump is a failure
    to observe, never a fact about the app, so it is retried rather than
    reported.
    """
    for _ in range(attempts):
        sh("rm -f /sdcard/t21-ui.xml")
        out = sh("uiautomator dump /sdcard/t21-ui.xml")
        if "could not get idle state" in out:
            time.sleep(2.0)
            continue
        xml = sh("cat /sdcard/t21-ui.xml")
        start = xml.find("<?xml")
        if start < 0:
            time.sleep(1.0)
            continue
        try:
            return ET.fromstring(xml[start:])
        except ET.ParseError:
            time.sleep(1.0)
    return None


def find_node(root: ET.Element | None, predicate) -> ET.Element | None:  # noqa: ANN001
    if root is None:
        return None
    for node in root.iter("node"):
        if predicate(node):
            return node
    return None


def tap_node(node: ET.Element) -> None:
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
    if not m:
        raise RuntimeError(f"unparsable bounds {node.get('bounds')}")
    x1, y1, x2, y2 = (int(v) for v in m.groups())
    sh(f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}")


def all_text(root: ET.Element | None) -> list[str]:
    if root is None:
        return []
    return [n.get("text", "") for n in root.iter("node") if n.get("text")]


def wait_for(check, timeout: float, poll: float = 0.5):  # noqa: ANN001
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = check()
        if value:
            return value
        time.sleep(poll)
    return None


def launch_app() -> bool:
    sh(f"am start -n {PKG}/com.ichi2.anki.IntentHandler")
    if not wait_for(lambda: "DeckPicker" in top_activity(), timeout=120, poll=1.0):
        return False
    # A half-open navigation drawer never settles, and nothing can be read off
    # the screen until it does. BACK closes it and is harmless otherwise.
    if ui_dump(attempts=3) is None:
        sh("input keyevent 4")
        time.sleep(2.0)
    return ui_dump(attempts=8) is not None


CONFIRM_MESSAGE = "This may take a long time"


def _positive_button(root: ET.Element | None) -> ET.Element | None:
    return find_node(root, lambda n: n.get("resource-id", "") == "android:id/button1")


def _dialog_message(root: ET.Element | None) -> str:
    node = find_node(root, lambda n: n.get("resource-id", "") == "android:id/message")
    return node.get("text", "") if node is not None else ""


def check_database_in_app() -> dict:
    """AnkiDroid's own Check Database, from the deck picker, on the device.

    `KEYCODE_C` is the app's own shortcut for it, so this is the same code path
    as the menu entry: a confirmation dialog, then the backend's `check_database`
    against the live collection, then a dialog printing what it found.
    """
    sh(f"input keyevent {KEYCODE_C}")

    confirm = wait_for(
        lambda: (lambda r: r if CONFIRM_MESSAGE in _dialog_message(r) else None)(
            ui_dump()
        ),
        timeout=30,
        poll=0.5,
    )
    if confirm is None:
        return {"ok": None, "error": "no confirm dialog", "screen": all_text(ui_dump())}
    button = _positive_button(confirm)
    if button is None:
        return {"ok": None, "error": "no OK button", "screen": all_text(confirm)}
    tap_node(button)

    # The check runs, then reports. Anything other than the confirmation still
    # on screen is the result.
    def result() -> str | None:
        # The progress dialog ("Checking cards...") also has a message and would
        # otherwise be read as the answer. Only the result dialog has a button.
        root = ui_dump()
        message = _dialog_message(root)
        if not message or CONFIRM_MESSAGE in message:
            return None
        if _positive_button(root) is None:
            return None
        return message

    message = wait_for(result, timeout=300, poll=1.0)
    if message is None:
        return {"ok": None, "error": "no result dialog", "screen": all_text(ui_dump())}
    # AnkiDroid prints the backend's own report verbatim. A clean run says the
    # database was rebuilt and optimised and nothing else; anything the check
    # had to repair is listed with it.
    ok = message.strip() == "Database rebuilt and optimized."
    dismiss = _positive_button(ui_dump())
    if dismiss is not None:
        tap_node(dismiss)
    time.sleep(1.0)
    return {"ok": ok, "report": message}


def start_review() -> bool:
    """Deck list -> study options -> reviewer, by tapping what a student taps."""
    deck = find_node(
        ui_dump(),
        lambda n: n.get("resource-id", "") == f"{PKG}:id/deck_name"
        and DECK_MATCH in n.get("text", ""),
    )
    if deck is None:
        return False
    tap_node(deck)
    time.sleep(2.0)
    if "Reviewer" in top_activity():
        return True
    study = find_node(
        ui_dump(),
        lambda n: n.get("resource-id", "") == f"{PKG}:id/studyoptions_start",
    )
    if study is None:
        return False
    tap_node(study)
    return bool(wait_for(lambda: "Reviewer" in top_activity(), timeout=60, poll=0.5))


ANSWER_FLAG = "/data/local/tmp/t21-answering"


def answer_stream(count: int) -> subprocess.Popen:
    """A continuous review session, on the device, until the flag file goes.

    Stopped by deleting the flag rather than by killing the adb client: killing
    the client leaves the on-device loop running, and a stray `input keyevent`
    loop makes the screen permanently un-idle, which breaks every later read.
    """
    keys = " ".join([str(KEYCODE_SPACE)] * count)
    sh(f"touch {ANSWER_FLAG}")
    return subprocess.Popen(
        [
            ADB,
            "shell",
            f"while [ -f {ANSWER_FLAG} ]; do input keyevent {keys}; done",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_answer_stream(proc: subprocess.Popen) -> None:
    sh(f"rm -f {ANSWER_FLAG}")
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


ANSWER_LOG_TAG = "Reviewer"
ANSWER_LOG_MARKER = "answerCardInner"


def capture_answer_log(path: Path) -> subprocess.Popen:
    """Record the app's own log of every card it answers, for the whole trial."""
    return subprocess.Popen(
        [ADB, "shell", f"logcat -T 1 -s {ANSWER_LOG_TAG}:D"],
        stdout=open(path, "w", encoding="utf-8", errors="replace"),  # noqa: SIM115
        stderr=subprocess.DEVNULL,
        text=True,
    )


def revlog_rows(scratch: Path) -> int | None:
    """The number of reviews that have actually reached the database.

    Pulls the collection and its write-ahead log and counts in a copy, so the
    count includes committed-but-not-yet-checkpointed reviews and nothing is
    written back to the device.
    """
    work = scratch / "probe"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    adb("pull", COL, str(work / "collection.anki2"))
    if "No such file" not in sh(f"ls {WAL}"):
        adb("pull", WAL, str(work / "collection.anki2-wal"))
    db = sqlite3.connect(str(work / "collection.anki2"))
    db.create_collation("unicase", _unicase)
    try:
        return db.execute("select count() from revlog").fetchone()[0]
    except sqlite3.DatabaseError:
        return None
    finally:
        db.close()


def announced_answers(log: Path) -> int:
    if not log.exists():
        return 0
    return sum(
        1
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
        if ANSWER_LOG_MARKER in line
    )


def stop_after_injected_answer(pid: int, delay_s: float) -> str:
    """Answer one card and freeze the app `delay_s` later, all on the device.

    The logcat trigger below is the obvious way to find the write and it is
    measurably too slow: `logcat` delivery plus a `grep` runs about 150 ms
    behind the line it is watching for, and the transaction is long over by
    then (measured, and reported per trial as `freeze_lag_ms`).

    So the trigger is moved to the only event whose timing this harness
    controls: the keypress that causes the write. Two key events go in -- show
    the answer, then grade it -- and `SIGSTOP` follows a tuned delay later,
    inside the window between the app receiving the grade and the review
    transaction committing. The delay is swept across attempts because that
    window is a property of the device, not something to guess once; a freeze
    counts only when the review the app announced is confirmed missing from the
    database.
    """
    script = (
        f"input keyevent {KEYCODE_SPACE}; input keyevent {KEYCODE_SPACE}; "
        f"sleep {delay_s}; kill -STOP {pid}; echo STOPPED $(date +%s.%N)"
    )
    out = subprocess.run(
        [ADB, "shell", script], capture_output=True, text=True, timeout=120
    )
    return (out.stdout or "").strip()


def arm_stopper(pid: int) -> subprocess.Popen:
    """SIGSTOP the app on its own announcement that it is about to write.

    The Android half of the desktop harness's freeze-confirm-kill. `SIGKILL` on
    its own consistently lands *after* the commit here -- logcat delivery plus a
    grep is slower than the transaction -- so the process is frozen first and the
    kill only follows once the freeze is confirmed to have caught a write that
    never completed. A stopped process cannot finish its transaction, so what is
    on disk when `SIGKILL` arrives is a genuinely half-written review.

    Both halves run on the device, in one shell, so nothing crosses the adb link
    between the app announcing the write and the process being frozen.
    """
    script = (
        f"logcat -T 1 -s {ANSWER_LOG_TAG}:D | grep -m1 {ANSWER_LOG_MARKER} >/dev/null; "
        f"kill -STOP {pid}; echo STOPPED $(date +%s.%N)"
    )
    return subprocess.Popen(
        [ADB, "shell", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def arm_killer(pid: int) -> subprocess.Popen:
    """SIGKILL the app on its own announcement that it is about to write.

    `Reviewer.answerCardInner` logs `answerCardInner: <card id> <rating>` on the
    line immediately before `sched.answerCard(...)`, which is the call into the
    Rust backend that opens and commits the review transaction. Watching for that
    line and killing on it puts the kill inside the write rather than near it.

    Both halves run on the device, in one shell: `logcat | grep -m1` exits the
    moment the line appears and `kill -9` is the next command, so nothing
    crosses the adb link between the app announcing the write and the process
    dying. Arming this from the host instead would add tens of milliseconds --
    longer than the transaction it is trying to interrupt.

    (`inotifyd` on the collection's write-ahead log was tried first and is not
    usable: the collection lives under `/storage/emulated/0`, and inotify
    delivers no events for writes through that FUSE mount. Verified against a
    control file on `/data/local/tmp`, where the same command works.)
    """
    script = (
        f"logcat -T 1 -s {ANSWER_LOG_TAG}:D | grep -m1 {ANSWER_LOG_MARKER} >/dev/null; "
        f"kill -9 {pid}; echo KILLED $(date +%s.%N)"
    )
    return subprocess.Popen(
        [ADB, "shell", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _unicase(a: str, b: str) -> int:
    x, y = a.casefold(), b.casefold()
    return (x > y) - (x < y)


def host_side_check(work_dir: Path) -> dict:
    """sqlite's own checks on a pulled copy of the collection and its log."""
    col = work_dir / "collection.anki2"
    db = sqlite3.connect(str(col))
    db.create_collation("unicase", _unicase)
    out: dict = {}
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
    out["ok"] = out["quick_check"] == ["ok"] and out["integrity_check"] == ["ok"]
    return out


def pull_and_check(scratch: Path, trial: int, tag: str = "after") -> dict:
    work = scratch / f"pull-{trial:02d}-{tag}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    adb("pull", COL, str(work / "collection.anki2"))
    wal_bytes = 0
    if "No such file" not in sh(f"ls {WAL}"):
        adb("pull", WAL, str(work / "collection.anki2-wal"))
        p = work / "collection.anki2-wal"
        wal_bytes = p.stat().st_size if p.exists() else 0
    # How much of the collection was still only in the log when the app died.
    # Taken *before* the check below: opening a copy that has its log beside it
    # makes sqlite replay and checkpoint it, which would delete the very
    # difference this is trying to measure.
    revlog_without_wal = None
    if wal_bytes:
        bare = work / "no-wal" / "collection.anki2"
        bare.parent.mkdir(exist_ok=True)
        shutil.copy2(work / "collection.anki2", bare)
        db = sqlite3.connect(str(bare))
        db.create_collation("unicase", _unicase)
        try:
            revlog_without_wal = db.execute(
                "select count() from revlog"
            ).fetchone()[0]
        except sqlite3.DatabaseError as exc:
            revlog_without_wal = f"{type(exc).__name__}: {exc}"
        db.close()

    result = host_side_check(work)
    result["wal_bytes_on_device"] = wal_bytes
    result["revlog_without_wal"] = revlog_without_wal
    return result


def raise_limits(col_path: Path) -> dict:
    """Lift the daily caps in the collection before it goes on the phone.

    Out of the box the deck offers 200 reviews a day, which twenty review
    sessions would exhaust; a kill after the reviewer has run out of cards is a
    kill at idle, and idle kills are the thing this test is not. Done host-side
    with Anki's own `update_deck_configs` rather than by editing the config blob,
    and to the collection both platforms start from.
    """
    from anki import deck_config_pb2
    from anki.collection import Collection

    col = Collection(str(col_path))
    deck_id = col.decks.id_for_name(
        next(d.name for d in col.decks.all_names_and_ids() if DECK_MATCH in d.name)
    )
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
    }
    col.close()
    return counts


def freeze_lag_ms(log: Path, stop_output: str) -> float | None:
    """Milliseconds between the app announcing a write and the freeze landing.

    The gap the Android half of this test cannot close: `logcat` delivery plus a
    `grep` is slower than the transaction it is trying to interrupt. Measured
    rather than estimated, and reported, because a number that says "we were
    forty milliseconds late" is worth more than a claim that we were not.
    """
    match = re.search(r"STOPPED\s+([0-9.]+)", stop_output)
    if not match or not log.exists():
        return None
    stopped_at = float(match.group(1))
    lines = [
        line
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
        if ANSWER_LOG_MARKER in line
    ]
    if not lines:
        return None
    stamp = re.match(r"(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)\.(\d+)", lines[-1])
    if not stamp:
        return None
    month, day, hour, minute, second, millis = (int(g) for g in stamp.groups())
    now = time.localtime(stopped_at)
    announced = time.mktime(
        (now.tm_year, month, day, hour, minute, second, 0, 0, now.tm_isdst)
    ) + millis / 1000.0
    return round((stopped_at - announced) * 1000.0, 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--col", required=True, help="collection to seed the phone with")
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--seed", type=int, default=21)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    scratch = Path(args.scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)

    # Seed the device with the same collection the desktop run started from.
    seed = scratch / "android-seed.anki2"
    shutil.copy2(Path(args.col).resolve(), seed)
    counts = raise_limits(seed)
    print(f"seed collection: {counts}", flush=True)
    sh(f"am force-stop {PKG}")
    sh(f"rm -f {ANSWER_FLAG}")
    # A key-event loop left behind by an interrupted run keeps the screen
    # permanently un-idle, which makes `uiautomator dump` refuse and every read
    # below fail. Clear any before starting.
    sh("pkill -9 -f 'input keyevent' || true")
    # Animations are the other reason a dump refuses. Turning them off is a
    # device setting; it changes nothing about the app or the engine.
    for scale in ("window_animation_scale", "transition_animation_scale",
                  "animator_duration_scale"):
        sh(f"settings put global {scale} 0")
    time.sleep(2)
    sh(f"rm -f {COL} {COL}-wal {COL}-shm")
    adb("push", str(seed), COL)
    sh(f"chown u0_a213:ext_data_rw {COL} || true")

    trials = []
    for trial in range(1, args.trials + 1):
        record: dict = {"trial": trial}
        if not launch_app():
            record["error"] = f"app did not reach the deck picker: {top_activity()}"
            trials.append(record)
            continue

        # Anki's own Check Database, on the device, for the state the previous
        # kill left behind. Runs before this session writes anything.
        record["in_app_check_database"] = check_database_in_app()

        if not start_review():
            record["error"] = f"could not enter the reviewer: {top_activity()}"
            trials.append(record)
            continue

        # The revlog as it stands before this session answers anything. Taken
        # after the check above, so the comparison at the end of the trial is
        # against the state the review actually started from.
        before = pull_and_check(scratch, trial, tag="before")
        record["revlog_before"] = before["counts"].get("revlog")

        pid = pid_of()
        record["pid"] = pid
        answer_log = scratch / f"answers-{trial:02d}.log"
        capture = capture_answer_log(answer_log)
        keys = answer_stream(40)
        # Let the session get going, for a different length of time each trial,
        # so twenty kills are not the same kill twenty times.
        soak = rng.uniform(1.0, 6.0)
        time.sleep(soak)
        record["soak_secs"] = round(soak, 2)

        # Freeze on the app's announcement of a write, then check whether the
        # freeze actually caught one: the review it announced has to be missing
        # from the database. If it committed anyway, let the app go and wait for
        # the next write rather than counting a miss as a hit.
        t0 = time.time()
        frozen_inside = False
        freeze_attempts = 0
        # The answer stream is stopped first: the freeze below has to be the
        # only thing answering, or a key event from the loop lands during the
        # confirmation and the counts stop meaning anything.
        stop_answer_stream(keys)
        delays = [0.0, 0.004, 0.012, 0.03]
        for freeze_attempts, delay in enumerate(delays, start=1):
            record["stop_output"] = stop_after_injected_answer(pid, delay)
            record["freeze_delay_s"] = delay
            # Let the log capture catch up with what the app announced before it
            # was frozen; a stopped process adds nothing after this.
            time.sleep(0.6)
            announced = announced_answers(answer_log)
            committed = revlog_rows(scratch)
            if (
                committed is not None
                and record["revlog_before"] is not None
                and announced > 0
                and committed - record["revlog_before"] == announced - 1
            ):
                frozen_inside = True
                break
            sh(f"kill -CONT {pid}")
        record["freeze_attempts"] = freeze_attempts
        record["frozen_inside_write"] = frozen_inside
        record["freeze_lag_ms"] = freeze_lag_ms(answer_log, record.get("stop_output", ""))

        sh(f"kill -9 {pid}")
        record["kill_wait_secs"] = round(time.time() - t0, 2)
        time.sleep(2)
        capture.terminate()
        time.sleep(0.5)

        record["process_gone"] = pid_of() != pid
        record["top_after_kill"] = top_activity()
        after = pull_and_check(scratch, trial, tag="after")
        record["host_side_check"] = after
        record["revlog_after"] = after["counts"].get("revlog")

        # The victim's own account of how many cards it answered, against how
        # many reviews actually reached the database. One short means the last
        # transaction never committed: the process died inside the write.
        announced = announced_answers(answer_log)
        record["answers_announced"] = announced
        if record["revlog_before"] is not None and record["revlog_after"] is not None:
            committed = record["revlog_after"] - record["revlog_before"]
            record["reviews_committed"] = committed
            record["died_inside_write"] = announced > 0 and committed == announced - 1
        trials.append(record)
        print(
            f"trial {trial:2d}  killed={record['process_gone']}  "
            f"answered={announced} committed={record.get('reviews_committed')} "
            f"inside_write={record.get('died_inside_write')}  "
            f"in_app_ok={record['in_app_check_database'].get('ok')}  "
            f"host_ok={after['ok']}  wal={after['wal_bytes_on_device']}",
            flush=True,
        )

    # One more launch so the last kill is also seen by the app's own check.
    final = {}
    if launch_app():
        final = check_database_in_app()

    out = {
        "package": PKG,
        "collection_source": str(Path(args.col).resolve()),
        "seed_counts": counts,
        "trials": trials,
        "final_in_app_check_database": final,
        "summary": {
            "trials": len(trials),
            "killed": sum(1 for t in trials if t.get("process_gone")),
            "in_app_clean": sum(
                1 for t in trials if (t.get("in_app_check_database") or {}).get("ok")
            ),
            "host_side_clean": sum(
                1 for t in trials if (t.get("host_side_check") or {}).get("ok")
            ),
            "died_inside_write": sum(1 for t in trials if t.get("died_inside_write")),
            "frozen_inside_write": sum(
                1 for t in trials if t.get("frozen_inside_write")
            ),
        },
    }
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out["summary"], indent=2))


if __name__ == "__main__":
    sys.exit(main())
