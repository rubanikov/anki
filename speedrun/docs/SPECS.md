# Speedrun — Workstream Specs

Six workstreams. Each states what it builds, what "done" means as a checkable
condition, and which SpikyPOV row and required test it answers to. Vocabulary is
from [CONTEXT.md](../CONTEXT.md); decisions are in [docs/adr/](./adr/).

Ticket breakdown and ordering: [TICKETS.md](./TICKETS.md).

---

## WS-1 · Crosswalk and topic resolution (Rust)

**Builds.** Resolution of a card to a Topic without ever writing to the
student's notes. A Crosswalk keyed on `(deck path, tags)` lives in collection
config; the backend consults it at read time and reports what it could not
place.

Per [ADR-0002](./adr/0002-topics-are-resolved-through-a-read-time-crosswalk.md)
this must be in Rust, not the add-on: Android has to produce identical numbers
offline, and a Python-side mapping is unreachable from the phone.

**Shape**
- Crosswalk entry: `{ match: deck path glob or tag glob, topic: "mcat::BB::1A" }`
- Stored under a single collection-config key, so it syncs and is one blob
  written by one device — never concurrently by two (see the config rule in
  [ARCHITECTURE.md](./ARCHITECTURE.md))
- First matching entry wins; order is explicit in the file, not incidental
- A card matching nothing is an Unmapped card

**Done when**
- [ ] A collection whose cards carry no `mcat::` tags still produces per-topic
      mastery, with the student's notes byte-identical before and after
- [ ] `cards_unmapped` is non-zero on a partially-mapped deck and is reported
      on screen, not just in the proto
- [ ] The crosswalk's own error rate is measured on a hand-checked sample and
      published as a number
- [ ] Desktop and Android return identical `TopicMastery` for the same
      collection, offline

**Answers to** POV 5 (sensor untouched) · required test: Rust change tests

---

## WS-2 · Scores and the give-up rule (Rust)

**Builds.** The three scores, per section, each abstaining by default. Already
largely shipped; this workstream closes the gaps found while grilling.

**Fixed already** — per-section held-out attempt counting (a global count let
one section's work unlock another's), the topic requirement as a fraction of the
section rather than a flat 8, and `cards_unmapped` on both responses.

**Still open**
- Coverage uses `covered = reviews > 0` per topic. Confirm that survives contact
  with a real deck — a single review of one card should not mark a whole content
  category covered
- Readiness stays hard-abstaining until the performance→scaled-score mapping is
  validated, and says so in its reason string

**Done when**
- [ ] Every abstention names the specific shortfall and the number that would
      clear it
- [ ] No score is emitted below its threshold, asserted in tests
- [ ] No interval narrower than the AAMC's ±2 escapes, asserted in tests
- [ ] Thresholds are unreachable from the UI layer — the add-on and the Kotlin
      client cannot pass their own

**Answers to** POV 5 · the automatic-fail criterion A6 · required test: Rust
change tests

---

## WS-3 · Android evidence path

**Builds.** Proof that the Rust change reaches the phone, and bidirectional
sync. Deliberately not a designed dashboard — an abstention message on a plain
screen proves the engine, the give-up rule, and the shared numbers all arrived.

**State.** `rsdroid-release.aar` builds from the fork and contains 55
`anki/speedrun/*` classes plus `jni/x86_64/librsdroid.so`. Nothing calls them yet.

**Three artifacts, in order**
1. AnkiDroid consuming the fork's `.aar` instead of the published one
2. One Kotlin call to `SectionScores` rendering its abstention text
3. A review done on the phone appearing on desktop after sync

**Environment, reproducible** — `ANDROID_NDK_HOME` must be set explicitly;
`JAVA_HOME` must point at JDK 17; `cargo` must be on PATH; and `build_rust`'s
`cmd /c gradlew.bat` step fails here, so run
`.\gradlew.bat assembleRelease rsdroid-testing:build` directly.

**Done when**
- [ ] Three artifacts above captured as recordings
- [ ] Sync test: 10 offline phone + 10 offline desktop reviews → all 20 land
      once, no double counting
- [ ] Conflict rule written down *before* the conflict test runs
- [ ] README states the ABI shipped (`x86_64` = emulator; `arm64-v8a` needed for
      physical hardware)

**Answers to** A3 (70% cap) · required test: sync

---

## WS-4 · Add-on, coach loop, agent service

**Builds.** The desktop surface and the spoken loop. `gui_hooks` only, no
monkeypatching. LangGraph behind FastAPI, out of Anki's bundled Python.

**The loop.** Steps 1–3 (cold question · confidence before the answer · explain
aloud) plus the contrast pair are protected from cuts. Only step 1 scores.

**Non-negotiable mechanics**
- **No `<input>` element in any template with a live question on screen.** This
  is the enforcement mechanism for POV 2, not a styling preference
- Every graph node carries `{output, source_id, span}`; an output reaching the
  boundary without a source is dropped rather than displayed
- Generation gate: retrieve → generate → assert the answer's supporting span is
  in the retrieved text → ship or drop. **Asking a model to check its own item
  is banned**
- Every rejection is logged with a reason, otherwise Yield cannot be decomposed

**Done when**
- [ ] Service killed → app still starts, still scores Memory, still shows
      coverage
- [ ] `ai_enabled = false` → same
- [ ] Add-on disabled → queue order and scheduling identical to upstream Anki,
      asserted by test
- [ ] Grep proves no text input exists on a live-question template

**Answers to** POV 2, POV 3, POV 7 · A8 · required tests: AI card check,
crash/offline

---

## WS-5 · Evidence

The 38% that gets squeezed. Priority order is fixed in
[BUILD_PLAN.md](./BUILD_PLAN.md).

| Artifact | Source | Notes |
|---|---|---|
| **Ablation pre-registration** | written first, timestamped | 15 minutes, gates 15% of the grade. Blocks at ~H+3, retention test ~H+18 ([ADR-0007](./adr/0007-the-ablation-measures-delayed-retention.md)) |
| **Memory calibration** | `anki-revlogs-10k` | Brier + log loss on held-back reviews. Raw data never enters the repo ([ADR-0001](./adr/0001-calibration-uses-a-public-review-log-corpus.md)) |
| **Paraphrase test** | R-set vs P-set vs card recall | Three points on the DOK ladder. Falsifiable in both directions ([ADR-0004](./adr/0004-performance-and-the-paraphrase-test-use-separate-sets.md)) |
| **Leakage check** | script, exits 0 | Must also prove the licensed corpus is absent from the public fork |
| **Retrieval eval** | 4 arms, Yield at a fixed gate | The ungated control carries the claim, not the margin ([ADR-0006](./adr/0006-retrieval-is-judged-by-yield-at-a-fixed-gate.md)) |
| **AI card check** | H3 gold set of 50 | Cutoff recorded before looking |
| **Crash + bench** | 20 kills per app; 50k synthetic deck | Synthetic deck touches latency only, never a score |

**Done when** every artifact is committed with the command that produced it, and
every number carries a range.

---

## WS-6 · Packaging and proof

**Builds.** Installable artifacts and the evidence bundle.

**Done when**
- [ ] Desktop installer ships with the add-on **preinstalled** — a `.ankiaddon`
      the grader installs by hand fails "runs on a clean machine"
- [ ] Packaged Android build
- [ ] Clean-device run, recorded, on a machine that has never seen the project
- [ ] README: exam up front, AGPL-3.0-or-later, credit to Anki, build steps for
      both apps, upstream files touched, and the stated limitations —
      emulator-only ABI, one section fully mapped, two sections abstaining
- [ ] Traceability table with every POV in a row, each naming its falsifying
      number

**Answers to** A1, A5, A9

---

## Stated limitations — write these down, don't let them be discovered

1. Two of three sections abstain on Performance and Readiness. Deliberate
   ([ADR-0003](./adr/0003-give-up-thresholds-are-fixed-before-the-demo.md))
2. Readiness abstains even when thresholds are met, because the mapping to a
   scaled score is not validated against outcomes
3. Calibration data is not MCAT-specific — it validates the Memory model, not
   MCAT topic mastery
4. Ablation is n=1–3 and cannot distinguish. The interval is reported, and so is
   the n that would be needed
5. Crosswalk breadth is one section; other sections report Unmapped cards
6. `x86_64` only unless the arm64 pass is run
