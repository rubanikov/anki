# Speedrun — Test Plan

All eight required tests, plus the held-out data protocol. Every entry names the command and the artifact it produces.

---

## 0. Freeze the held-out data — do this before writing any other code

Leaked test data scores **zero**. This is unrecoverable if skipped, and it takes twenty minutes.

| Set | Contents | Frozen as |
|---|---|---|
| **H1** — memory calibration | Most recent 20% of reviews by time | `speedrun/eval/holdout/h1_reviews.jsonl` + SHA-256 |
| **H2** — performance items | 30 cards × 2 rewordings = 60 items. Never shown to the generator, never used in coaching. | `speedrun/eval/holdout/h2_items.jsonl` + SHA-256 |
| **H3** — AI card gold set | 50 question/answer pairs from one real source | `speedrun/eval/holdout/h3_gold.jsonl` + SHA-256 |

Write `speedrun/eval/holdout/MANIFEST.md` with the hashes, the timestamp, and the cutoff rule — **stated before anyone looks at results**.

---

## 1. Rust change

```bash
cargo test -p anki speedrun          # 3 unit tests
pytest pylib/tests/test_speedrun.py  # 1 Python test
```

| Test | Asserts |
|---|---|
| `mastery_excludes_attempt_notes` | `cards_excluded > 0`; mastery with and without our notes is **identical** |
| `abstains_below_thresholds` | Under 200 reviews ⇒ `available == false`, `abstain_reason` populated, no estimate emitted |
| `range_never_narrower_than_aamc_sem` | Any computed interval < ±2 is widened to ±2 |
| Python: `test_section_scores_roundtrip` | Add-on calls the backend through generated bindings, gets ranges and abstention reasons |

**Undo + corruption proof:** both methods are pure reads — no `Op`, no undo entry, no mutation. Test: snapshot `collection.anki2` hash, run 1000 mastery calls, hash again, assert unchanged; then run an undo of an unrelated operation and assert it still works.

**Also required:** one-page note on why this belongs in Rust (in `ARCHITECTURE.md` §3), the list of upstream files touched, and evidence the change runs on Android.

---

## 2. Sync

```bash
speedrun/eval/sync_test.sh
```

1. Desktop offline: 10 reviews. Phone offline: 10 *different* reviews. Reconnect.
   **Assert:** all 20 land exactly once. No lost, no double-counted.
2. Same card reviewed on both, both offline. Reconnect.
   **Assert:** the documented conflict rule picks correctly — both revlog entries retained, card state resolves to the higher `mod`.
3. Phone with a skewed clock goes offline mid-sync.
   **Assert:** refused with a resync prompt, not silently merged.

Conflict rule is written in `ARCHITECTURE.md` §7 **before** the test runs.

---

## 3. Coverage map

Every topic on the official AAMC outline marked covered / not covered, percentage on the dashboard.
**Assert:** below the 50% line the app abstains from readiness for that section.

---

## 4. Paraphrase test — the load-bearing one

30 cards, 2 reworded exam-style questions each. Compare recall on the card to accuracy on the rewordings.

```bash
python speedrun/eval/paraphrase_test.py
```

**If the numbers match, the performance model is copying the memory model.** This is the DOK 1 vs DOK 2 test run directly. Report the gap whichever way it comes out. Target stated in advance: gap ≥ 15 points.

Highest value per hour of anything on this list — it validates the performance model *and* supplies the closest thing to thesis evidence. Prioritize over polish.

---

## 5. Leakage check

```bash
python speedrun/eval/leakage_check.py    # must exit 0
```

Flags any H2/H3 item, or near-copy, appearing in generation prompts, corpus chunks, or coaching material. Near-copy = 5-gram Jaccard ≥ 0.6 or normalized exact match. **Ship the clean output as an artifact.**

---

## 6. AI card check

Generate 50 cards from one real source, score against gold set H3.

Report three buckets: **correct and useful / wrong / correct but bad teaching.**
Cutoff set before looking, recorded in the manifest.

Also run **ungated generation** as the comparison — if the gate's wrong-item rate doesn't beat ungated, the gate is theatre and we say so.

**Separately** (don't tangle these): retrieval comparison — grounded pipeline vs BM25 vs embedding search on the same query set, one script, `speedrun/eval/retrieval_baseline.py`.

---

## 7. Crash and offline

```bash
speedrun/eval/crash_test.sh    # 20 kills per app
```

- Kill each app mid-review 20 times ⇒ **zero corrupted collections**, verified by `check database` each time.
- Pull the network ⇒ AI degrades cleanly, both apps keep working and still score.
- Agent service returns garbage ⇒ treated as unreachable, `ai_enabled` false.

---

## 8. Benchmark

```bash
make bench    # 50,000-card deck
```

Prints **median, p95, and worst case** for every §10 target:

| Target | Threshold |
|---|---|
| Button press acknowledged | p95 < 50 ms, both platforms |
| Next card after grading | p95 < 100 ms |
| Dashboard first load / refresh | < 1 s / < 500 ms |
| Normal session sync | < 5 s |
| Memory at 50k cards | under a stated ceiling, desktop + midrange phone |
| Cold start | < 5 s desktop, < 4 s phone |
| UI block | nothing > 100 ms |

One number we picked ourselves does not count. The 50k deck is generated synthetically by `speedrun/bench/gen_deck.py`.

---

## 9. Thesis ablation

Three builds, same items, same study time:

1. Full app, spoken loop **on**
2. Same app, loop **off** (`speedrun.coach_enabled = false`)
3. Plain unmodified Anki

Main number — **stated in advance**: difference in held-out accuracy between builds 1 and 2, reported with a range.

**Honest expectation:** with the participants available in the time we have, this will be underpowered. "n=4, cannot distinguish" is the likely and acceptable result. It is reported as the result, not dressed up. A POV put at risk and not confirmed beats one never tested.

Also log **speak-rate** — the share of prompts where the student actually talked. If students won't speak, the mechanism fails for a reason that has nothing to do with the learning science.

---

## 10. The break-tests they will run

Confirm each is handled before submitting:

| Attack | Our answer |
|---|---|
| Memorizes wording, fails rewordings | Paraphrase test is exactly this; performance ≠ memory by construction |
| Huge deck missing a heavily weighted topic | Coverage map; readiness abstains below 50% |
| Two cards stating opposite facts | Flagged in mastery as contradictory topic evidence; widens the range |
| Source with hidden text attacking the generator | Corpus chunks sanitized; generation gated on retrieved span match |
| Tapping Good without reading | Wise-style disengagement filter drops the attempt |
| Topic with no history | Abstains; named in "what would fix it" |
| Accurate but too slow | Timing reported separately; never folded into mastery |
| AI cards correct but useless | Third bucket in the AI card check |
| Score that rose only from leakage | Leakage check + `cards_excluded` contamination test |
| AI service offline or returning garbage | Degradation path; scores still computed |
| Same card reviewed on two devices offline | Sync test #2 |
| Phone with wrong clock offline mid-sync | Sync test #3 |
| Crash mid-review | Crash test, 20× per app |
| Corrupt deck / broken images | `check database` on load; broken media reported, not fatal |
