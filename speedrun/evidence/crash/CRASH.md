# Crash and offline behaviour (T-21)

**Verdict: 40 hard kills, 40 clean databases, zero corrupted collections.**
Twenty against Anki desktop, twenty against AnkiDroid, with Anki's own Check
Database run after every single one, plus an independent `sqlite3` check the app
was not responsible for. Both apps also start, compute Memory, and show coverage
and abstentions with the network gone and no agent service running.

Two things are stated plainly rather than smoothed over:

* **The desktop kills landed inside the review transaction and the Android kills
  did not.** On desktop the process is frozen inside `answer_card` and the
  victim's own log proves it, 20 times out of 20. On Android no trigger
  available over adb is fast enough — 61–111 ms late, measured — so those 20
  kills landed between transactions, on a collection whose most recent reviews
  existed only in the write-ahead log. §3 says exactly what each half does and
  does not prove.
* **One of the twenty Android kills landed at idle.** A system dialog stole
  focus and that session graded nothing. It is in the table, marked, and counted
  against the run rather than dropped from it. §5.
* **The first attempt at this test was wrong and was thrown away.** §6.

---

## 1. What was killed, and how

| | Desktop | Android |
|---|---|---|
| App | `aqt` (Anki 26.08) with a Qt window, real reviewer, real deck | AnkiDroid `2.25.0alpha2-debug` on `Medium_Tablet` (`sdk_gtablet_x86_64`) |
| Engine | fork `rslib` | same `rslib` through `rsdroid-release.aar` built the same day |
| Collection | 8,372 cards · 35,605 reviews · 4,619 due today · 1,411 new | the same file, pushed to the device |
| Review driven by | an add-on timer calling `Reviewer._showAnswer` / `_answerCard` | `input keyevent 62`, the app's own show-answer / Good binding |
| Kill | Win32 `NtSuspendProcess` then `TerminateProcess` | `kill -9` |
| Check after every kill | AnkiDroid/Anki `check_database`, plus `pragma quick_check` and `integrity_check` on a copy | same |

The collection is the synthetic bench deck (`speedrun/eval/bench/gen_deck.py`,
seed 210) with the crosswalk installed. Nothing here reports a score, so its
being generated does not matter; what matters is that it carries 35,605 real
`revlog` rows and real FSRS memory state, so every answer is a real scheduling
write against a realistically sized database.

`docs/TEST_PLAN.md` §7 names `speedrun/eval/crash_test.sh` for this. That file
does not exist and was not written: this ticket owns `speedrun/evidence/**`, and
a shell script would have had to reimplement the process-freezing the desktop
half needs. The harnesses below are the same test under a different path, and
`TEST_PLAN.md` should be pointed at them.

### Commands

```sh
# desktop
PYTHONPATH="pylib;out/pylib;qt;out/qt" out/pyenv/Scripts/python.exe \
  speedrun/evidence/crash/crash_desktop.py \
  --base <throwaway> --col <scratch>/crash-source.anki2 --trials 20 \
  --out speedrun/evidence/crash/desktop-kills.json

# android
out/pyenv/Scripts/python.exe speedrun/evidence/crash/crash_android.py \
  --col <scratch>/crash-source.anki2 --trials 20 \
  --scratch <scratch>/android-scratch \
  --out speedrun/evidence/crash/android-kills.json

# desktop, network amputated, dashboard photographed
PYTHONPATH="pylib;out/pylib;qt;out/qt" out/pyenv/Scripts/python.exe \
  speedrun/evidence/crash/offline_desktop.py \
  --base <throwaway> --col <scratch>/parity-collection.anki2 \
  --shot speedrun/evidence/crash/desktop-dashboard-offline.png \
  --out speedrun/evidence/crash/desktop-offline.json
```

## 2. How the desktop kill was forced to land mid-write

A kill at an arbitrary moment proves nothing. Almost all of a review session is
the app waiting for a keystroke, and a process killed while idle was never going
to corrupt anything. So:

1. The `autoreview` add-on wraps `Scheduler.answer_card` — the call that reaches
   `answer_card_raw` in the Rust backend and runs the whole review transaction —
   and writes `B <n>` immediately before it and `E <n>` immediately after. The
   records go out with `os.write`, a syscall, so they are in the OS page cache
   before the call returns: readable live by another process, and still there
   after the writer is killed.
2. The killer spins on that log. When the last record is a `B` with no matching
   `E`, it calls `NtSuspendProcess`, which freezes every thread where it stands.
3. It reads the log again. Still an unterminated `B` means the process is
   stopped *inside* the write. Only then does `TerminateProcess` fire.

The freeze is what makes the claim true. `TerminateProcess` on its own is a
request, not an instant death: fired at a write it loses about half the time,
because the victim finishes its transaction in the microseconds before Windows
gets round to the kill — measured, in the run whose results are in §6. A frozen
process cannot finish, so what reaches the disk is a genuinely half-written
review.

**All 20 desktop trials ended with the victim's own last record being an
unterminated `B`.** That line was written by Anki, from inside `answer_card`, and
no `E` ever followed it.

## 3. What each half proves

| | Desktop | Android |
|---|---|---|
| Kill during a live review session, reviews being written continuously | yes, 20/20 | yes, 19/20 (§5, trial 14) |
| Kill landed **inside** the review transaction | **yes, 20/20** | **no, 0/20** |
| Collection's recent reviews existed only in the write-ahead log at kill time | yes, 6.4–6.6 MB of log | yes, 1.0–10.6 MB of log; 11 reviews measured (§5) |
| Check Database clean afterwards | 20/20 | 20/20 |

On Android the write cannot be caught. Two triggers were tried:

* **The app's own log line.** `Reviewer.answerCardInner` prints
  `answerCardInner: <card id> <rating>` on the line immediately before it calls
  into the backend. Watching for it with `logcat | grep -m1` and freezing in the
  same on-device shell arrives **61–111 ms late**, mean 86 ms across the 19
  trials that graded anything (`freeze_lag_ms` per trial). The transaction is
  long over.
* **Injecting the keypress myself** and freezing a tuned delay later, sweeping
  0 / 4 / 12 / 30 ms. This does not help either: `input keyevent` waits for the
  app to finish handling the event, and the review has committed by the time it
  returns.

`inotifyd` on the collection's write-ahead log was tried first and does not work
at all: the collection lives under `/storage/emulated/0`, and inotify delivers
no events for writes through that FUSE mount. Verified against a control file on
`/data/local/tmp`, where the same command works.

Two device settings were changed to make the screen readable at all, neither of
which touches the app or the engine: the three animation scales are set to 0
(`uiautomator dump` refuses with "could not get idle state" while anything is
animating), and any leftover `input keyevent` loop is killed before the run —
one left behind by an interrupted earlier attempt kept AnkiDroid at 123% CPU and
made every screen read fail until it was found.

So the honest position is: the "killed inside a transaction" property is
demonstrated on desktop, 20/20, against the same `rslib` engine, the same
`journal_mode=wal`, and the same `answer_card` code path the phone runs. On
Android what is demonstrated is that the app survives `SIGKILL` during an active
review session while the main database file is stale and correctness depends on
replaying the log — which the numbers in §5 show is not a hypothetical.

## 4. Desktop: 20 kills

`answers` is how many cards that session had graded before the kill; `last
record` is the victim's own final log line. `wal` is the size of the
write-ahead log left behind. In-app Check Database is Anki's own
`Tools -> Check Database`, run by the add-on at the *next* profile open, before
that session writes anything — so each row's in-app result is the verdict on the
previous row's kill.

| # | soak (s) | answers | last record | wal (bytes) | quick_check | integrity_check | Anki check_database | in-app check_database (next start) |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.91 | 50 | `B 51` | 6,431,352 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 2 | 2.85 | 119 | `B 120` | 6,447,832 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 3 | 2.65 | 118 | `B 119` | 6,456,072 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 4 | 2.07 | 95 | `B 96` | 6,464,312 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 5 | 1.10 | 56 | `B 57` | 6,472,552 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 6 | 3.23 | 127 | `B 128` | 6,480,792 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 7 | 3.29 | 133 | `B 134` | 6,484,912 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 8 | 2.20 | 97 | `B 98` | 6,501,392 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 9 | 2.17 | 88 | `B 89` | 6,505,512 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 10 | 1.17 | 57 | `B 58` | 6,517,872 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 11 | 0.31 | 25 | `B 26` | 6,521,992 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 12 | 1.67 | 72 | `B 73` | 6,526,112 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 13 | 2.47 | 96 | `B 97` | 6,526,112 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 14 | 0.56 | 35 | `B 36` | 6,538,472 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 15 | 3.24 | 131 | `B 132` | 6,538,472 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 16 | 1.16 | 58 | `B 59` | 6,546,712 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 17 | 1.16 | 57 | `B 58` | 6,554,952 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 18 | 0.46 | 30 | `B 31` | 6,554,952 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 19 | 3.99 | 141 | `B 142` | 6,554,952 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |
| 20 | 3.03 | 123 | `B 124` | 6,571,432 | ok | ok | Database rebuilt and optimized. | Database rebuilt and optimized. |

A twenty-first launch after kill 20 ran Anki's own Check Database one more time:
**Database rebuilt and optimized**, clean.

Nothing was lost that should have survived. The collection started with 35,605
reviews; after the twentieth kill it held 37,314, the count rose strictly
monotonically across all twenty kills, and the card and note counts never moved
from 8,372. `graves` — Anki's record of deletions — stayed at 0 throughout: no
kill caused anything to be deleted on the way back up.

Raw per-trial records, including the full check reports and the exit codes:
`desktop-kills.json`.

## 5. Android: 20 kills

The device was in airplane mode for all twenty, so these are also twenty offline
starts. `answered` is how many cards the app's own log says it graded that
session; `committed` is how many of those reached the database; `lag` is how far
behind the app's write announcement the freeze landed. In-app Check Database is
AnkiDroid's own, run on the device from the deck picker at the *next* launch,
before that session writes anything — so each row's result is the verdict on the
previous row's kill.

| # | soak (s) | answered | committed | lag (ms) | wal (bytes) | quick_check | integrity_check | in-app check_database (next start) |
|---|---|---|---|---|---|---|---|---|
| 1 | 1.82 | 10 | 10 | 80.1 | 6,431,352 | ok | ok | Database rebuilt and optimized. |
| 2 | 4.45 | 17 | 17 | 74.1 | 9,706,752 | ok | ok | Database rebuilt and optimized. |
| 3 | 4.17 | 17 | 17 | 61.3 | 10,118,752 | ok | ok | Database rebuilt and optimized. |
| 4 | 3.40 | 19 | 19 | 90.8 | 10,188,792 | ok | ok | Database rebuilt and optimized. |
| 5 | 2.08 | 10 | 10 | 71.8 | 10,320,632 | ok | ok | Database rebuilt and optimized. |
| 6 | 4.96 | 16 | 16 | 86.0 | 1,062,992 | ok | ok | Database rebuilt and optimized. |
| 7 | 5.04 | 24 | 24 | 99.6 | 7,514,912 | ok | ok | Database rebuilt and optimized. |
| 8 | 3.56 | 19 | 19 | 111.0 | 10,604,912 | ok | ok | Database rebuilt and optimized. |
| 9 | 3.53 | 19 | 19 | 69.5 | 10,604,912 | ok | ok | Database rebuilt and optimized. |
| 10 | 2.18 | 11 | 11 | 80.5 | 10,604,912 | ok | ok | Database rebuilt and optimized. |
| 11 | 1.02 | 11 | 11 | 111.2 | 10,604,912 | ok | ok | Database rebuilt and optimized. |
| 12 | 2.86 | 17 | 17 | 64.9 | 10,604,912 | ok | ok | Database rebuilt and optimized. |
| 13 | 3.93 | 18 | 18 | 92.9 | 10,604,912 | ok | ok | Database rebuilt and optimized. |
| **14** | 1.35 | **0** | **0** | — | 10,604,912 | ok | ok | Database rebuilt and optimized. |
| 15 | 4.97 | 19 | 19 | 82.1 | 10,604,912 | ok | ok | Database rebuilt and optimized. |
| 16 | 2.16 | 11 | 11 | 84.3 | 10,604,912 | ok | ok | Database rebuilt and optimized. |
| 17 | 2.16 | 11 | 11 | 75.8 | 10,604,912 | ok | ok | Database rebuilt and optimized. |
| 18 | 1.21 | 12 | 12 | 102.7 | 10,604,912 | ok | ok | Database rebuilt and optimized. |
| 19 | 5.99 | 18 | 18 | 104.8 | 10,604,912 | ok | ok | Database rebuilt and optimized. |
| 20 | 4.69 | 18 | 18 | 88.5 | 10,604,912 | ok | ok | Database rebuilt and optimized. |

A twenty-first launch after kill 20 ran AnkiDroid's own Check Database once
more: **Database rebuilt and optimized**, clean.

The collection went from 35,605 reviews to 35,902 across the twenty kills, and
the card and note counts never moved from 8,372.

**Trial 14 was a kill at idle, and it counts as one.** It answered nothing: the
record shows `revlog_before == revlog_after == 35813`, and `top_after_kill`
names `com.google.android.calendar/.launch.oobe.WhatsNewFullScreen` — an
unrelated system app put a full-screen dialog over the reviewer, so the key
events went to that instead. AnkiDroid was still killed and the check after it
was still clean, but that trial proves nothing about writes in flight. Nineteen
of the twenty Android kills were during a session that was actively grading
cards; one was not.

**The freeze never caught a transaction.** `lag` is the measured distance
between the app announcing a write and the freeze arriving: 61–111 ms, mean 86
ms over the 19 trials that answered anything. Every announced answer had
committed. §3.

**The write-ahead log was carrying real work.** `revlog_without_wal` in
`android-kills.json` is *not* usable evidence of this — it was recorded after
the checking code had already let sqlite replay and checkpoint the copy, so it
equals the recovered count in every row. That is a bug in the harness, since
fixed, and the column should be ignored for this run. Measured separately
instead, on a fresh kill with the fix in place:

```
wal bytes on device                  : 10,604,912
revlog in collection.anki2 alone     : 35,902
revlog after replaying the log       : 35,913
reviews that existed only in the log :     11
```

So at the moment of the kill the main database file was eleven reviews stale and
the collection was correct only if the log replayed. It did, twenty times out of
twenty.

Raw per-trial records: `android-kills.json`.

## 6. The run that was thrown away

The first complete desktop attempt is not in this file, and this is why.

* **It killed the wrong process.** `out/pyenv/Scripts/python.exe` is a virtualenv
  trampoline: it launches a second process, and *that* is Anki. Suspending and
  terminating the launcher does nothing to the app. The harness had been
  reporting that it froze writes it never touched.
* **Three of its trials answered nothing.** The add-on tried to raise the deck's
  daily limits and hit a proto field-path error (`DeckConfig.new_per_day` — the
  limits live on the nested `DeckConfig.config`), so the error was logged and the
  cap stayed at 200 reviews a day. By trial 9 the deck had run dry and the app
  sat on an empty queue. Those were kills at idle, which is the exact thing this
  test exists not to do.
* **Half its kills landed after the write.** Before the freeze step existed, the
  killer fired `TerminateProcess` on the edge of a write and the victim finished
  the transaction first in 4 trials out of 8.

All three are fixed: the kill targets the pid found by walking the process tree,
the limits are raised host-side before the app ever opens the collection, and
the kill freezes and confirms before terminating. The results in §4 are from the
rebuilt harness.

Two further things surfaced while doing this and are worth knowing, though
neither is a Speedrun defect:

* **Anki's single-instance key is machine-wide.** `AnkiApp.KEY` is
  `anki<checksum(username)>`, ignoring `ANKI_BASE`, so a second Anki hands its
  arguments to the first and exits. Anything running two profiles at once needs
  `ANKI_SINGLE_INSTANCE_KEY`.
* **Anki can hang before opening a profile.** `setupProfile` runs only once both
  webviews report `_domDone`, and under load QtWebEngine sometimes never gets
  there: the window is up, the profile never opens, and the app sits there. Seen
  repeatedly on a loaded machine. The harness retries and counts it
  (`stalled_launches_before_this_one`); in the run in §4 it happened zero times.

## 7. Offline behaviour

The requirement is that with no network and no agent service the app still
starts, still computes Memory, and still shows coverage and abstentions.

**No agent service was running.** T-08's service (`speedrun/agent`, `127.0.0.1:8000`)
was not up: `Get-NetTCPConnection -LocalPort 8000` returned nothing on the host,
and the emulator had no network at all, so it could not have reached one either.
That is the condition the ticket asks for, and at the moment it is also just the
truth.

### Desktop

Anki was started with every socket call replaced by one that raises before it
leaves the process — `socket.socket.connect`, `connect_ex`, `create_connection`,
`getaddrinfo`, `gethostbyname`. This is stronger evidence than pulling the
machine's network, which would only show that nothing *got through*, and it does
not disturb the other agents sharing this box.

Result (`desktop-offline.json`, screenshot `desktop-dashboard-offline.png`):

* The app started, opened the profile, and rendered the Speedrun dashboard.
* **Exactly one network attempt was made and refused**: the add-on's probe of the
  agent service, from `switches.probe` via `urllib`. The captured stack is in the
  JSON. Nothing else in the app reached for the network.
* The page says, at the top: *"AI off — the agent service did not answer. No
  generation and no coach. Memory, coverage and the give-up rule are computed by
  the engine and are unaffected."*
* Every score still rendered, from the engine: Memory `0.71 (0.68 – 0.74)` for
  Bio/Biochem with `Confidence: High`, coverage `100%`, `6944` graded reviews,
  `947` unmapped cards, the full per-topic table, and Performance and Readiness
  abstaining with the engine's own sentences. CARS abstained on all three with
  the AAMC sentence, offline, exactly as it does online.

Those are the same numbers the online read produced in
`../parity/desktop.json`. The AI degraded to a one-line notice; not one score
moved.

### Android

Airplane mode on, wifi and mobile data disabled:

```
$ adb shell settings get global airplane_mode_on   -> 1
$ adb shell dumpsys connectivity | grep 'Active default network'
      Active default network: none
$ adb shell ping -c 1 -W 2 8.8.8.8
      connect: Network is unreachable
```

In that state the app started, opened the collection, and the Speedrun screen
computed and displayed all twelve scores — Memory available for all three
modelled sections, coverage for each, `947` unmapped cards, and CARS abstaining
with the AAMC sentence. The airplane-mode icon is in the status bar of the
screenshot. Evidence is in `../parity/`
(`phone-speedrun-scores-offline.png`, `phone-scores.txt`), because the same
screen is the parity evidence; every number on it matches desktop.

The whole Android crash run in §5 also ran with the device in airplane mode, so
those twenty launches and twenty database checks are themselves twenty more
offline starts.

## 8. What failed, and what is untested

* **No collection corrupted, on either platform, in 40 kills.** No trial produced
  a `quick_check` or `integrity_check` result other than `ok`, and no run of
  Check Database reported a problem to fix.
* **Android kills could not be landed inside a transaction.** §3. This is a limit
  of what adb can observe, stated rather than worked around, and it means the
  Android half of this evidence is weaker than the desktop half.
* **One Android trial killed an idle app.** Trial 14: a Google Calendar
  full-screen dialog took focus, the key events went to it, and the session
  graded nothing. Counted, marked in the table, and not re-run — 19 of 20, not
  20 of 20.
* **`revlog_without_wal` in `android-kills.json` is wrong** and must be ignored.
  It was recorded after sqlite had already replayed the log into the copy. The
  harness is fixed; the number the claim rests on was measured separately and is
  in §5.
* **One collection, one deck size, one device.** Everything here is x86_64 on an
  emulator with an 8,372-card collection. An arm64 phone, a slower disk, a
  collection ten times the size, and a real power cut (as opposed to `SIGKILL`,
  which does not lose what is already in the OS page cache) are all untested.
  `SIGKILL` proves the process cannot corrupt the file by dying; it does not
  prove the *device* cannot corrupt it by losing power mid-`fsync`.
* **Check Database repairs as it checks.** It reports first and the reports are
  recorded verbatim, so a repair would be visible — but the independent
  `sqlite3` check is run first, on a copy, precisely so there is one measurement
  that cannot have been fixed by the act of measuring.
* **The reviewer was driven by a robot.** On desktop through the real
  `Reviewer._answerCard`, on Android through the app's real key bindings; neither
  reaches behind the UI to the scheduler. But no human hesitated, edited a note,
  or opened the browser mid-session.

## Files

| | |
|---|---|
| `crash_desktop.py` | the desktop harness: freeze-confirm-kill, then both checks |
| `autoreview/` | throwaway add-on that drives the session and marks the write |
| `crash_android.py` | the Android harness |
| `offline_desktop.py`, `offline_probe/` | starts Anki with the network amputated and photographs the dashboard |
| `desktop-kills.json`, `android-kills.json` | every trial's raw record |
| `desktop-offline.json` | the offline dashboard's text, plus the refused network call |
| `desktop-dashboard-offline.png` | the dashboard, rendered offline |
