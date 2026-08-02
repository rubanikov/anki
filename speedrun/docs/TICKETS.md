# Speedrun — Tickets

Dependency-ordered. **Blocks** names what cannot start until this lands.
Specs: [SPECS.md](./SPECS.md). Cut order: [BUILD_PLAN.md](./BUILD_PLAN.md).

`[P]` = protected, never cut. `[C#]` = cut number from the cut order.

---

## Now — nothing else can start behind these

### T-01 · Freeze the held-out sets and write the manifest `[P]`
Twenty minutes, unrecoverable if skipped. Three sets, hashes, timestamp, and the
cutoff rule stated **before** anyone looks at a result.
- H1 — calibration reviews held back from `anki-revlogs-10k`
- H2 — **P-set**: held-out items. Empty at freeze time; the manifest fixes the
  *protocol*, and each item's id and hash are appended as it is generated
- H3 — gold set of 50, cutoff recorded
- H4 — **R-set**: rewordings, added once the deck exists
> Also add the licensed corpus to `.gitignore` and record why
**Blocks** T-06, T-12, T-14, everything in WS-5

### T-02 · Pre-register the ablation `[P]`
Main number, predicted direction, falsifier, and the manipulation-check
prediction (coach arm flat or lower immediately). Timestamped before block one.
Fifteen minutes, gates 15% of the grade.
**Blocks** T-16

### T-03 · Acquire the deck and check tag granularity
Download MileDown. Count how many of the 31 content categories resolve from
`(deck path, tags)`. **Below ~15, switch to AnKing** and pay the signup.
**Blocks** T-04, T-05, T-13

---

## Critical path

### T-04 · Build the crosswalk for the demo section `[C3]`
Bio/Biochem first — 9 categories, heaviest deck coverage. LLM-assisted,
hand-checked on a sample, error rate published as a number. Other sections'
cards stay Unmapped, reported honestly.
**Depends** T-03 · **Blocks** T-05, T-13

### T-05 · Crosswalk resolution in Rust
Collection-config crosswalk, first-match-wins, consulted before topic grouping.
Notes never written. `cards_unmapped` already lands on both responses.
Tests: an untagged deck still produces mastery; the collection is byte-identical
before and after.
**Depends** T-04 · **Blocks** T-13, T-15

### T-06 · Corpus index for the demo section
OpenStax book for Bio/Biochem plus the full AAMC outline. Chunk, index, and map
chunks to content categories. Sanitize chunk text — a source carrying hidden
instructions must not reach the generator.
**Depends** T-01 · **Blocks** T-07, T-08

### T-07 · Agent service: graph, gate, tracing
FastAPI + LangGraph, out of Anki's bundled Python. `{output, source_id, span}`
on every node. Generation gate with **logged rejection reasons**. No model
checking its own item. LangSmith tracing on.
**Depends** T-06 · **Blocks** T-08, T-09, T-14

### T-08 · Generate the P-set for the demo section
Enough gated items to support 20 attempts across ≥3 topics. Item text is written
to a desktop-side file, **never to the collection**. Append ids and hashes to the
H2 manifest as they are produced.
**Depends** T-06, T-07 · **Blocks** T-11, T-16

---

## Android — runs in parallel, hard cut at H+2 from start

### T-09 · AnkiDroid consumes the fork's `.aar`
Point the AnkiDroid build at `rsdroid/build/outputs/aar/rsdroid-release.aar`.
Already built and verified carrying 55 speedrun classes.
**Blocks** T-10

### T-10 · One Kotlin call to `SectionScores`, rendered
Plain screen showing the abstention text. Proves engine + give-up rule + shared
numbers reached the phone. **No dashboard design.** `[C5]` for anything beyond this.
**Depends** T-09 · **Blocks** T-11

### T-11 · Sync both ways, and the conflict rule
Self-host `anki --syncserver`, point both clients at it. Ten offline reviews each
side → all 20 land once. **Write the conflict rule down before running the
conflict test.**
**Depends** T-10

---

## Desktop surface

### T-12 · Add-on skeleton and dashboard
`gui_hooks` only. Three scores with ranges, coverage, abstention reasons,
`cards_unmapped` **on screen**. Reviewer hook hides the topic label while a
question is showing.
**Depends** T-01

### T-13 · Wire the dashboard to real numbers
**Depends** T-05, T-12

### T-14 · Coach loop, steps 1–3 plus the contrast pair `[P for contrast pair]`
Voice capture in a webview. **No `<input>` on any live-question template** —
that is the POV 2 enforcement mechanism. Steps 5–7 are `[C4]`.
**Depends** T-07

### T-15 · Off switches, proven
`add-on disabled` ⇒ queue order and scheduling identical to upstream, asserted by
test. `coach_enabled`, `ai_enabled` wired.
**Depends** T-05

---

## Evidence — 38% of the grade

### T-16 · Ablation blocks, ~H+3 `[P]`
Three counterbalanced blocks. Retention test at ~H+18 on items seen in no block.
**Depends** T-02, T-08 · **must start early — this is the whole point**

### T-17 · Memory calibration on H1 `[P]`
Brier + log loss + reliability chart. Runs outside the collection.
**Depends** T-01

### T-18 · Paraphrase test `[P]`
Card recall vs R-set vs P-set. Report the gaps; if all three collapse, say so.
**Depends** T-08

### T-19 · Leakage check, clean `[P]`
Flags any H2/H3 item or near-copy in prompts, corpus chunks, or coaching
material. Also asserts the licensed corpus is absent from the repo. Ship the
clean output.
**Depends** T-08

### T-20 · Retrieval eval `[C2 → 2 arms]`
Four arms, 93 queries, Yield at a fixed gate. Cut to hybrid-gated + ungated
control if time runs short — the control carries the claim.
**Depends** T-07

### T-21 · AI card check on H3
Gold set of 50, cutoff already recorded.
**Depends** T-07

### T-22 · Crash and offline
20 kills per app, `check database` each time. Network pulled → AI degrades, scores
survive.
**Depends** T-11, T-12

### T-23 · Bench on a 50k synthetic deck `[C6]`
p50/p95/worst against every target in PRD §10.

---

## Ship

### T-24 · Package both apps
Installer with the add-on **preinstalled**.

### T-25 · Clean-device run, recorded `[P]`
A machine that has never seen this project.
**Depends** T-24

### T-26 · Traceability table complete `[P]`
Every POV in a row with its falsifying number. 25% section.

### T-27 · README, limitations, demo video
Exam up front, AGPL, credit, upstream files touched, and the six stated
limitations from SPECS.md. Video: POV in one sentence → the feature → a review
session → the Rust change → phone-to-desktop sync → three scores with ranges →
AI features → results.

### T-28 · Update the BrainLift "what changed" section
POV 5 reworded, RAG scope corrected, and the three findings this planning session
produced: the ablation construct problem, the retrieval self-comparison problem,
and the paraphrase test that could not fail.
