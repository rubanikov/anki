# T-09 · Two-device sync, observed

What actually happened when the tests in `CONFLICT_RULE.md` were run.
`CONFLICT_RULE.md` was written first and has not been touched since; its
SHA-256 was `517c60b47d9642c9136ef4bbb752887037921c60f885008e1b0380e2c952f6b2`
when written at 2026-08-02 15:45:23 UTC, and it is still that now. Nothing
below was allowed to change it.

**Verdict: all four rules held. No prediction had to be corrected.**

## Setup

Self-hosted sync server, from the fork, run through its documented entry point
(`anki --syncserver`, i.e. `anki.syncserver.run_sync_server` → `SimpleServer`
in `rslib/src/sync/http_server/`):

```
SYNC_USER1=speedrun:speedrun SYNC_BASE=<scratch>/syncbase \
SYNC_HOST=0.0.0.0 SYNC_PORT=27701 \
out/pyenv/Scripts/python.exe -c "import sys; sys.path.extend(['out/pylib','out/qt']); \
    from anki.syncserver import run_sync_server; run_sync_server()"
```

| | what | endpoint |
| --- | --- | --- |
| Desktop | fork's pylib backend, driven headlessly by `sync_test.py` | `http://127.0.0.1:27701/` |
| Phone | AnkiDroid `com.ichi2.anki.debug` 2.25.0alpha2 on the fork's `.aar`, `Medium_Tablet` emulator | `http://127.0.0.1:27701/` via `adb reverse tcp:27701 tcp:27701` |
| Server | same `rslib` sync code both clients run | binds `0.0.0.0:27701` |

The phone logged in through its own UI (Sync → Log in → speedrun/speedrun); the
server's log shows the resulting `/sync/hostKey` request. `10.0.2.2` was not
reachable from this emulator image, so `adb reverse` provides the route instead;
the sync traffic is otherwise unchanged.

Fixture: 21 Basic notes in `SyncTest::Desktop` (10), `SyncTest::Phone` (10) and
`SyncTest::Conflict` (1), uploaded once from the desktop and downloaded once by
the phone, so both devices started from a byte-identical baseline.

"Offline" is enforced, not simulated: `adb reverse --remove-all` before each
offline phase, verified with `nc 127.0.0.1 27701` → `Connection refused`, and
restored only when the phase ended.

## The counting test — 10 + 10 = 20, exactly once

All figures from `counts.py`, the same SQL run against all three databases.

| stage | revlog total | distinct revlog ids | `SyncTest::Desktop` | `SyncTest::Phone` | cards with reps > 0 | Σ card.reps |
| --- | --- | --- | --- | --- | --- | --- |
| baseline — desktop | 0 | 0 | 0 | 0 | 0 | 0 |
| baseline — phone | 0 | 0 | 0 | 0 | 0 | 0 |
| baseline — server | 0 | 0 | 0 | 0 | 0 | 0 |
| offline — desktop after its 10 | 10 | 10 | 10 | 0 | 10 | 10 |
| offline — phone after its 10 | 10 | 10 | 0 | 10 | 10 | 10 |
| after both synced — desktop | **20** | **20** | 10 | 10 | 20 | 20 |
| after both synced — phone | **20** | **20** | 10 | 10 | 20 | 20 |
| after both synced — server | **20** | **20** | 10 | 10 | 20 | 20 |

Twenty reviews in, twenty out, on every copy. `revlog_total == revlog_distinct_ids`
rules out duplicate rows; `Σ card.reps == 20` over 20 distinct cards rules out a
review being counted twice against one card. **R1 holds.**

Sync order was phone → desktop → phone. The desktop's `sync_collection` returned
`NO_CHANGES` — the post-sync state, meaning the exchange completed and nothing
was left pending.

## The conflict test — same card, both sides, both offline

Card `Conflict 01`, id `1785685662723`, identical on both devices at the start.

| | device | button | card `mod` | revlog id |
| --- | --- | --- | --- | --- |
| first | desktop | Again (ease 1) | 1785687034 (11:10:34) | 1785687034860 |
| second | phone | Easy (ease 4) | 1785687120 (11:12:00) | 1785687120741 |

86 seconds apart, phone later. Sync order: **desktop first, phone second** — so
the winner predicted by `mod` is the device that synced *last*, and a naive
"first writer wins" or "server always wins" would have produced a different
answer.

### Predicted (written in advance) vs observed

| prediction from `CONFLICT_RULE.md` | observed |
| --- | --- |
| the phone's grading is reflected in `due`/`ivl`/`queue`/`type` on all three | card is `type=2`, `queue=2`, `ivl=4`, `factor=2500`, `mod=1785687120` — the Easy answer — on desktop, phone and server |
| `reps == 1` | `reps == 1` |
| two revlog rows for the card, one ease from each device | two rows: ease 1 (desktop) and ease 4 (phone) |
| no error, no prompt, no duplicate card | none; both syncs ended `sanityCheck2` → `finish`, HTTP 200 |
| the loser adopts the winner on its next sync | after the desktop's next sync it held the phone's card row; all three then identical |

Intermediate state confirms the mechanism rather than just the outcome: after the
desktop synced but before the phone did, the server held the **desktop's** card
(`mod=1785687034`, `type=1`, `ivl=0`) and 21 revlog rows. The phone's sync then
replaced the card — because `1785687034 < 1785687120` — and added the 22nd revlog
row without disturbing the desktop's. **R2 holds, including the direction of the
comparison and the silence of the loss.**

The desktop's Card Info for this card
(`desktop-card-info-conflict-card.png`) is the whole result in one picture:
Reviews **1**, Interval **4 days**, Ease **250%**, and beneath it two review rows
— `11:12 rating 4` and `11:10 rating 1`. Two reviews recorded, one scheduling
state surviving, exactly as written down beforehand.

## R3 — two Attempt notes created independently

Both devices offline, each created notes standing in for Attempts: one on the
desktop (`Attempt made on DESKTOP`) and two on the phone (`Attempt made on
PHONE`, plus `Attempt` — a first attempt at typing that AnkiDroid saved; kept,
because an extra independently-created note is exactly what the rule is about).

After both synced, all three copies hold **24 notes and 24 cards** (21 fixture +
3), and all three Attempt notes survive with distinct ids, distinct guids and
their own field text:

```
1785687569517  LzRWP]&|?R  Attempt made on DESKTOP   (desktop)
1785687636090  xh00Eb]S./  Attempt                   (phone)
1785687695487  B3F(EOj?:>  Attempt made on PHONE     (phone)
```

Nothing was overwritten and nothing needed merging. **R3 holds** — N + M notes
in, N + M out, which is the property the SPEC relies on when it puts Attempts in
notes rather than in collection config.

## R4 — no half state

Every sync in this run ended with `/sync/sanityCheck2` followed by
`/sync/finish`, both HTTP 200; no sync was rolled back and no forced full sync
was triggered after the initial upload/download. The sanity check compares
card/note/revlog/notetype/deck/deck-config counts between client and server, so
each successful sync is itself an assertion that the two sides agree — and the
independently computed table above agrees with it. **R4 holds.**

## Caveats a reader should know

- The two devices ran on one host, so their clocks agree to well under the 300 s
  skew that `online_sync_status_check` would have rejected. The conflict result
  therefore tests the comparison rule, not clock-skew behaviour.
- One card, one conflict. The rule claims to be general because it is read off
  `add_or_update_card_if_newer`, which is the only path either side takes; the
  test confirms that reading rather than sampling the space.
- The tie case in R2 (equal `mod`, incumbent wins) was derived from the strict
  `<` in the source and was **not** exercised — provoking a same-second grading
  on two devices by hand is not reliable. Stated so it is not mistaken for a
  tested claim.
- The `desktop-*.png` screenshots are of Anki desktop opened on the post-sync
  desktop collection; the sync itself was performed by `sync_test.py` against
  the same backend, not by clicking Sync in that window.

## Files

| file | what |
| --- | --- |
| `CONFLICT_RULE.md` | the rule, written before any test ran; unmodified |
| `RESULTS.md` | this file |
| `sync_test.py` | desktop driver: init / sync / review / note / counts |
| `counts.py` | read-only counts, run against all three collections |
| `counts.json` | machine-generated counts at each stage |
| `desktop-after-sync-phone-reviews.png` | desktop Anki, `deck:SyncTest::Phone` — Phone 01–10 each showing Reviews 1, none of which happened on the desktop |
| `desktop-card-info-conflict-card.png` | desktop Card Info for the conflict card: Reviews 1, two review rows (rating 4 @ 11:12 from the phone, rating 1 @ 11:10 from the desktop) |
| `desktop-deck-list-after-sync.png` | desktop deck list after sync |
| `phone-after-10-offline-reviews.png` | the phone's reviewer immediately after its 10th offline review — counts read 0 new / 10 learning, and none of the 10 had reached the server yet |
| `phone-conflict-card-answer.png` | phone showing the conflict card's answer before grading it Easy |

---

## Addendum — what R2 means for Speedrun's own counting

The final state is the interesting one: **22 revlog rows but 21 total `card.reps`.**
The conflict card carries two review rows and `reps = 1`, because scheduling
state is last-writer-wins while the revlog is additive.

That matters here because `mastery.rs` accumulates `review_count` from
`card.reps`, not from revlog rows. So after a conflict, Speedrun counts one
fewer review than actually happened.

**The error runs in the safe direction.** Under-counting reviews means the
give-up rule holds Memory back slightly longer than strictly necessary — the
score abstains when it might have reported. An over-count would have been the
dangerous direction, letting a score appear on less evidence than claimed.

It is worth knowing rather than fixing. Reading counts from the revlog instead
would double-count nothing and would be more accurate, but it would also mean
Memory's evidence base and FSRS's own view of the card disagree, and FSRS is
what produces the retrievability the score is built on. Consistency with the
model beats a marginally larger denominator.

Scale: one lost rep per conflicting card, and only for cards graded on two
devices while both were offline. On a real collection that is rare.
