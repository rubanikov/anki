# Speedrun — Tickets

Tracer-bullet slices. Each cuts a complete path and is demoable on its own.
Spec: [SPEC.md](./SPEC.md) · Decisions: [docs/adr/](./adr/) · Cut order:
[BUILD_PLAN.md](./BUILD_PLAN.md).

`[P]` protected, never cut · `[C#]` cut number from the cut order.

---

## How to run this

Six waves. Everything inside a wave is independent and can run at the same time;
a wave opens when its blockers are done, not on a clock.

| Wave | Tickets | Parallel width | Opens when |
|---|---|---|---|
| **0** | T-01 T-02 T-03 T-04 T-12 | 5 | now |
| **1** | T-05 T-06 T-07 T-09 T-11 T-15 | 6 | wave 0 items land individually |
| **2** | T-08 T-13 | 2 | T-07, T-06 |
| **3** | T-10 T-14 T-17 T-18 | 4 | T-08 |
| **4** | T-16 T-19 T-20 | 3 | T-10 |
| **5** | T-21 T-22 T-23 | 3 | T-16 + 12 h wall clock |
| **6** | T-24 T-25 T-26 T-27 T-28 | mostly serial | the rest |

**Critical path — the only chain that cannot be compressed:**

> T-01 → T-07 → T-08 → T-10 → **T-16** → *(12 h delay)* → T-23 → T-26 → T-27

**Read that path carefully, because it corrects a number in
[ADR-0007](./adr/0007-the-ablation-measures-delayed-retention.md).** The ablation
blocks were planned for ~H+3, but they cannot start before the corpus, the agent
gate, and a usable P-set exist — realistically H+5 to H+6. The retention test
then lands around H+18, giving a **~12-hour delay** rather than 15. That is still
a genuine delayed-retention measure and the design survives; the ADR's timing is
the part that was optimistic. **Everything else in the build should be scheduled
around getting to T-16 early**, because every hour T-16 slips is an hour taken
off the delay, and below roughly eight hours the measure stops being meaningfully
"delayed."

**Two tickets are pure wall-clock and must be started, not scheduled:** T-11 (an
hour of real studying) and T-23 (the retention test, 12 h after T-16). Neither
can be compressed at the end.

---

# Wave 0 — start now, nothing blocks these

## T-01 · Freeze the held-out sets `[P]`
**Blocked by:** none — can start immediately
**Delivers:** a manifest that makes every later evidence claim checkable.

Four sets — H1 calibration reviews, H2 the P-set, H3 the gold 50, H4 the R-set —
each with contents, SHA-256, timestamp, and the cutoff rule stated **before
anyone looks at a result**. H2 is empty at freeze; the manifest fixes the
protocol and item hashes are appended as they are generated.

- [ ] `MANIFEST.md` exists with hashes, timestamp, and cutoff rule
- [ ] The licensed calibration corpus is in `.gitignore`, with the reason recorded
- [ ] Twenty minutes, done before any generation runs

## T-02 · Pre-register the ablation `[P]`
**Blocked by:** none
**Delivers:** a timestamped file that makes the experiment count.

Main number, predicted direction, the falsifier, and the manipulation-check
prediction (coach arm flat or lower immediately, which is *consistent* with the
thesis).

- [ ] File committed and timestamped before block one runs
- [ ] Names what result would falsify the thesis
- [ ] Fifteen minutes

## T-03 · Acquire the deck and check tag granularity
**Blocked by:** none
**Delivers:** a decision, backed by counting rather than assumption.

Download MileDown. Count how many of the 31 content categories resolve from
`(deck path, tags)`. **Below ~15, switch to AnKing** and pay the signup cost.

- [ ] Resolvable-category count recorded as a number
- [ ] Deck choice made and written down with that number as its justification
- [ ] Deck is in `.gitignore` — it is the student's, never redistributed

## T-04 · AnkiDroid runs on the fork's engine and shows an abstention
**Blocked by:** none — the `.aar` is already built and verified
**Delivers:** the §8 claim, demonstrated end to end on the phone.

Point AnkiDroid at `rsdroid-release.aar` from the fork, call `SectionScores`
from Kotlin, render the abstention text on a plain screen. **No dashboard
design** — `[C5]` for anything beyond raw output.

- [ ] AnkiDroid builds against the fork's `.aar`
- [ ] A Kotlin call to `SectionScores` returns and its abstention text is on screen
- [ ] Recording captured
- [ ] README states the ABI shipped (`x86_64` = emulator; `arm64-v8a` is `[C1]`)

## T-12 · Add-on skeleton and dashboard rendering backend output
**Blocked by:** none — the backend already returns scores and abstentions
**Delivers:** the desktop surface, showing real abstentions immediately.

`gui_hooks` only, no monkeypatching. Three scores with ranges, coverage,
abstention reasons, and **unmapped card count on screen**. Reviewer hook hides
the topic label while a question is showing.

- [ ] Dashboard renders whatever the backend returns, computing nothing itself
- [ ] Unmapped count visible to the user, not just present in the proto
- [ ] Topic label hidden during a live question
- [ ] Add-on ships inside the fork, not as a hand-installed `.ankiaddon`

---

# Wave 1

## T-05 · Memory calibration on the public corpus `[P]`
**Blocked by:** T-01
**Delivers:** the honesty claim, as a measured number.

Reliability chart, Brier score, log loss on held-back reviews. Runs outside the
collection — the corpus has no card text, so it validates the Memory model, not
MCAT topic mastery, and the write-up must say so.

- [ ] Chart, Brier and log loss committed with the command that produced them
- [ ] Raw corpus absent from the repo
- [ ] Limitation stated in the artifact itself

## T-06 · Crosswalk: data file, Rust resolution, unmapped on screen
**Blocked by:** T-03, T-12
**Delivers:** a real deck becoming measurable without touching the student's notes.

Crosswalk keyed on `(deck path, tags)` in collection config, first-match-wins,
consulted at read time. Demo section only — `[C3]`.

- [ ] A collection whose cards carry no `mcat::` tags produces per-topic mastery
- [ ] The collection is byte-identical before and after
- [ ] `cards_unmapped` non-zero on a partially-mapped deck and visible on screen
- [ ] Crosswalk error rate measured on a hand-checked sample and published

## T-07 · Corpus index for the demo section
**Blocked by:** T-01
**Delivers:** something for the gate to check answers against.

OpenStax book for Bio/Biochem plus the full AAMC outline. Chunk, index, map
chunks to content categories, **sanitize chunk text** — a source carrying hidden
instructions must not reach the generator.

- [ ] Index built and queryable
- [ ] Chunks carry their content-category attribution
- [ ] Sanitization applied and tested with a poisoned chunk

## T-09 · Sync both ways, and the conflict rule
**Blocked by:** T-04
**Delivers:** the two-device claim, tested rather than asserted.

Self-host `anki --syncserver`, point both clients at it.

- [ ] 10 offline phone + 10 offline desktop reviews → all 20 land exactly once
- [ ] **Conflict rule written down before the conflict test runs**
- [ ] Same card graded both sides offline → documented outcome matches the rule
- [ ] A phone review appearing on desktop, recorded

## T-11 · Study the deck for real `[P]`
**Blocked by:** T-03
**Delivers:** the live demo's data. **Wall clock — start it, don't schedule it.**

About an hour of genuine review, concentrated in the demo section, so Memory
crosses 200 reviews there while other sections stay honestly below.

- [ ] ≥200 graded reviews and ≥30 distinct cards in the demo section
- [ ] Other sections left below threshold — that contrast *is* the demo

## T-15 · Off switches, proven
**Blocked by:** T-12
**Delivers:** "Anki works as before" as a test rather than a promise.

- [ ] Add-on disabled ⇒ queue order and scheduling identical to upstream, asserted by test
- [ ] `coach_enabled = false` ⇒ scores, coverage, dashboard all still work
- [ ] `ai_enabled = false` ⇒ same, with no generation and no coach

---

# Wave 2

## T-08 · Agent service: graph, gate, tracing
**Blocked by:** T-07
**Delivers:** grounded generation with attribution built into the structure.

FastAPI + LangGraph outside Anki's bundled Python. `{output, source_id, span}` on
every node. Gate: retrieve → generate → assert the answer's span is in the
retrieved text → ship or drop. **Rejections logged with reasons.** No model
checks its own item. LangSmith on.

- [ ] Tested at the HTTP boundary: a corpus lacking the answer yields no item and a logged rejection
- [ ] An output without a source never crosses the boundary
- [ ] Service killed ⇒ desktop app still starts, still scores Memory, still shows coverage

## T-13 · Dashboard on real numbers
**Blocked by:** T-06, T-11
**Delivers:** the money shot — one section reporting, two abstaining.

- [ ] Demo section shows a real Memory score with a range
- [ ] Other sections abstain naming their exact shortfall
- [ ] Unmapped count shown alongside

---

# Wave 3

## T-10 · Generate the P-set for the demo section
**Blocked by:** T-08, T-06
**Delivers:** held-out items — the only thing Performance may be computed from.

Enough gated items to support 20 attempts across ≥3 topics. **Item text written
to a desktop-side file, never to the collection.** Ids and hashes appended to the
H2 manifest as produced.

- [ ] ≥20 gated items across ≥3 topics in the demo section
- [ ] No item text anywhere in the collection — checked, not assumed
- [ ] Every item traceable to a source span

## T-14 · Coach loop: cold question, confidence, explain aloud, contrast pair
**Blocked by:** T-08, T-12
**Delivers:** the product's distinguishing interaction. Contrast pair is `[P]`;
steps 5–7 are `[C4]`.

- [ ] Confidence captured **before** the answer is revealed
- [ ] Voice capture works; only step 1 scores
- [ ] Contrast pair changes exactly one detail
- [ ] **Grep proves no `<input>` exists on any live-question template**

## T-17 · Retrieval evaluation `[C2 → 2 arms]`
**Blocked by:** T-08
**Delivers:** a comparison that can lose.

Four arms over 93 queries, Yield at a fixed gate, ungated control. Cut to
hybrid-gated + ungated control if time runs short — the control carries the claim.

- [ ] Query set and primary metric fixed **before** the first run
- [ ] Results table committed including the arm that won, whichever it was

## T-18 · AI card check on the gold set
**Blocked by:** T-08
**Delivers:** item quality as a number, against a cutoff set in advance.

- [ ] Run against H3, cutoff already recorded in the manifest
- [ ] Result reported whether or not it clears the cutoff

---

# Wave 4

## T-16 · Ablation intervention blocks `[P]` — **run as early as possible**
**Blocked by:** T-02, T-10, T-14
**Delivers:** the experiment. Every hour this slips is an hour off the delay.

Three counterbalanced blocks on matched topics: full coach · coach off, scores
only · plain Anki.

- [ ] Immediate post-block accuracy recorded as the manipulation check
- [ ] Block order counterbalanced and recorded
- [ ] Start time logged — T-23 is scheduled from it

## T-19 · Paraphrase test `[P]`
**Blocked by:** T-10, T-03
**Delivers:** the three-point DOK comparison that can falsify the thesis.

Card recall vs R-set accuracy vs P-set accuracy, same student.

- [ ] Three numbers with ranges, reported side by side
- [ ] If the three collapse to one number, that is stated as a finding

## T-20 · Leakage check, clean `[P]`
**Blocked by:** T-10
**Delivers:** proof the Performance number is uncontaminated.

Flags any H2/H3 item or near-copy in generation prompts, corpus chunks, or
coaching material.

- [ ] Exits 0, output shipped as an artifact
- [ ] Also asserts the licensed corpus is absent from the repo

---

# Wave 5

## T-21 · Crash and offline
**Blocked by:** T-09, T-12
- [ ] 20 kills per app, `check database` clean each time — zero corrupted collections
- [ ] Network pulled ⇒ AI degrades, scores survive

## T-22 · Bench on a 50k synthetic deck `[C6]`
**Blocked by:** T-12
- [ ] p50/p95/worst against every target in PRD §10
- [ ] Synthetic deck touches latency only, never a score

## T-23 · Retention test `[P]` — **wall clock, ~12 h after T-16**
**Blocked by:** T-16 + elapsed time
- [ ] Items drawn from the held-out set, seen in no block
- [ ] Result reported as "cannot distinguish" with its interval and the n that would be needed
- [ ] Actual delay recorded in hours

---

# Wave 6 — ship

## T-24 · Package both apps
**Blocked by:** T-09, T-13, T-14
- [ ] Desktop installer with the add-on **preinstalled**
- [ ] Packaged Android build

## T-25 · Clean-device run, recorded `[P]`
**Blocked by:** T-24
- [ ] Both apps installed and run on a machine that has never seen the project

## T-26 · Traceability table
**Blocked by:** T-17, T-19, T-20, T-23
- [ ] Every SpikyPOV in a row: POV → shipped feature → the number that could falsify it
- [ ] No row without a feature behind it

## T-27 · README, limitations, demo video
**Blocked by:** T-25, T-26
- [ ] Exam up front, AGPL-3.0-or-later, credit to Anki, upstream files touched
- [ ] All six stated limitations from [SPEC.md](./SPEC.md)
- [ ] Video: POV in one sentence → the feature → a review session → the Rust change → phone-to-desktop sync → three scores with ranges → AI features → results

## T-28 · Update the BrainLift "what changed"
**Blocked by:** T-26
- [ ] POV 5 reworded; RAG scope corrected
- [ ] The three unfalsifiable deliverables this planning found, and how each was rewritten to be able to lose
