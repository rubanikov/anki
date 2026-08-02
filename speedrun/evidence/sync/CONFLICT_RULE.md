# The conflict rule

**Written before the conflict test was run.** Derived by reading the fork's sync
code, not by observing a run. The observed outcome is recorded separately, in
`RESULTS.md`. This file is not edited after the test — if reality disagrees with
it, the disagreement is the result.

Sources read (paths relative to the repo root):

- `rslib/src/sync/collection/chunks.rs` — `apply_chunk`, `merge_revlog`,
  `add_or_update_card_if_newer`, `add_or_update_note_if_newer`
- `rslib/src/storage/revlog/add.sql` — the revlog insert
- `rslib/src/sync/collection/changes.rs` — `apply_changes`, config handling
- `rslib/src/sync/collection/sanity.rs` — the post-sync count check
- `rslib/src/sync/collection/normal.rs`, `start.rs`, `meta.rs`, `status.rs` —
  ordering, `pending_usn`, `local_is_newer`, clock check

The setting throughout: both devices are synced to a common baseline, both go
offline, both make changes, then both sync back — one first, one second.

---

## R1 — Reviews are additive. Nothing is overwritten, nothing is counted twice.

Every grading writes one `revlog` row whose id is the epoch **millisecond** of
the review. Sync merges revlog with

```sql
INSERT OR IGNORE INTO revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) ...
```

(`rslib/src/storage/revlog/add.sql`, called from `merge_revlog` with
`uniquify = false`). Two reviews made on two devices have different millisecond
ids, so neither collides: **both rows survive, on both devices and on the
server.** `OR IGNORE` is also what makes the merge idempotent — a row that
arrives twice is inserted once, so re-syncing cannot double count.

**Prediction:** 10 reviews done offline on the phone plus 10 done offline on the
desktop = **exactly 20 revlog rows** on the phone, on the desktop, and on the
server after both sync. Not 19, not 21, not 40.

This holds even for reviews of the *same* card (see R2) — the losing device
loses its scheduling state, but its revlog row still lands.

Residual risk, stated so it is not a surprise: if two devices happened to write
reviews in the *same millisecond*, the second row to arrive is silently ignored
and one review is lost. With reviews driven by hand this is not expected to
occur.

## R2 — Card scheduling state is last-writer-wins by card `mod`, at whole-second resolution. Only one of the two gradings survives.

`add_or_update_card_if_newer` (`rslib/src/sync/collection/chunks.rs`):

```rust
let proceed = if let Some(existing_card) = self.storage.get_card(entry.id)? {
    !existing_card.usn.is_pending_sync(pending_usn) || existing_card.mtime < entry.mtime
} else { true };
```

Read as a rule: **the incoming copy replaces the local one unless the local copy
has an unsynced change of its own *and* its `mod` is greater than or equal to the
incoming `mod`.** The same function runs on the client (applying the server's
chunk, `pending_usn = -1`) and on the server (applying a client's chunk,
`pending_usn = that client's usn at its last sync`), so the rule is symmetric.

Therefore, when the same card is graded on both devices while both are offline:

1. **The grading with the larger `cards.mod` wins.** `mod` is
   `TimestampSecs` — whole seconds, taken from each device's own clock.
2. **A tie is broken in favour of the copy that is already there** — i.e. the
   device that synced *first*. The comparison is strictly `<`, so an equal `mod`
   does not displace the incumbent.
3. **The loser's grading is discarded entirely for scheduling purposes.** The
   card row is replaced wholesale, so `due`, `ivl`, `factor`, `reps`, `lapses`,
   `queue`, `type`, `left` and the FSRS memory state inside `data` all come from
   the winner alone. In particular, a *new* card graded once on each device ends
   with **`reps = 1`, not 2**.
4. **The two gradings are not merged, not averaged, and not surfaced.** There is
   no conflict dialog, no duplicate card, no error, no warning. The loss is
   silent. The only trace that the losing grading ever happened is its revlog
   row (R1).
5. Convergence: after both devices have synced, phone, desktop and server all
   hold the winner's card row. The device that lost adopts the winner's copy on
   its next sync, because by then its own copy is no longer pending
   (`!is_pending_sync` → `proceed = true` unconditionally).

**Concrete prediction for the conflict test.** One card `C`, both sides at a
common baseline, both offline. Desktop grades `C` at wall-clock `T_d`, phone
grades `C` at `T_p`, with `T_p > T_d` by more than a second. After both sync, in
either sync order:

- desktop, phone and server all show `C` with the **phone's** answer reflected in
  `due` / `ivl` / `queue` / `type`;
- `C.reps == 1`;
- **two** revlog rows exist for `C`, one with the desktop's ease and one with the
  phone's;
- no error and no user-visible prompt on either device.

Bound on how wrong "newer" can be: `online_sync_status_check`
(`rslib/src/sync/collection/status.rs`) aborts the sync with `ClockIncorrect` if
the client's clock differs from the server's by more than 300 seconds, so the
`mod` comparison can only be misled by under five minutes of clock skew.

## R3 — Two Attempt notes created independently both survive. Neither overwrites the other.

Attempts are notes (`speedrun/docs/SPEC.md`, "Where Speedrun's own data lives").
Notes created independently on two devices get different ids (epoch milliseconds,
uniquified against the local table) and different guids. On the receiving side,
`add_or_update_note_if_newer` finds no existing row with that id and takes the
`else { true }` branch: a plain insert. Nothing is compared, nothing is
overwritten.

**Prediction:** N attempts made offline on the phone and M made offline on the
desktop yield **N + M** attempt notes on both devices and on the server, each
retaining its own fields. Their (suspended) cards likewise. There is no
field-level merge, and none is needed, because the two devices never write the
same record.

This is the entire reason attempts are notes rather than a config key. Config
takes the opposite path: `apply_changes` calls
`set_all_config`, which begins `delete from config` and re-inserts the **whole**
map from whichever side has the newer collection `mod`. Config is a single blob
with whole-blob last-writer-wins semantics. Had attempts lived there, the second
device's map would replace the first's outright and one device's attempts would
vanish. Hence the SPEC rule: *nothing that two devices write independently may
live in config*.

Residual risk, stated in advance: two notes created in the same millisecond on
two devices would collide on id. The later arrival is dropped (existing row is
pending on the server, mtimes tie, `existing.mtime < entry.mtime` is false), its
cards are then orphaned, and the end-of-sync sanity check (R4) fails and forces a
one-way full sync. Not expected here.

## R4 — A sync is all or nothing.

The client wraps the whole exchange in one transaction (`normal.rs`), and before
finalising, `sanity_check` compares client and server counts of cards, notes,
revlog, notetypes, decks and deck configs. A mismatch rolls the transaction back
and marks the schema modified, forcing a full one-way sync rather than leaving a
half-merged collection. So a sync that reports success has already proved the
counts agree end to end — which is exactly the assertion the counting test makes,
made by the engine itself.

---

## What would falsify each rule

| Rule | Falsified by observing |
| --- | --- |
| R1 | any revlog total other than 20 after the counting test; or a review vanishing from the losing device in the conflict test |
| R2 | both gradings surviving in the card row (`reps == 2`), an averaged interval, a duplicate card, a conflict prompt, a sync error, or the *earlier* `mod` winning |
| R3 | fewer than N + M attempt notes after sync, or an attempt note's fields changed by the other device |
| R4 | a sync reporting success while the two sides disagree on counts |
