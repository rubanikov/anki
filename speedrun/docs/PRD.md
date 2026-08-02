# Speedrun — Product Requirements

**Exam: MCAT (472–528).** Three science sections modeled (Chem/Phys, Bio/Biochem, Psych/Soc). CARS is deliberately not modeled — see SpikyPOV 4.

Built on a fork of Anki (desktop) and AnkiDroid (Android), sharing one Rust engine.
Licensed AGPL-3.0-or-later. Credit to Anki.

---

## 1. The problem

Students build a 6,000-card deck, average 70% in-app, and score far below what every tool predicted. Every number a study app shows is measured **while the app is helping**. A flashcard hands you the cue. A question bank hands you five options. Percent-correct is computed on questions you chose to answer.

Speedrun measures the thing that is missing: whether knowledge survives contact with a question the student has never seen, with no help attached.

## 2. Three scores, never blended

| Score | Question | DOK | Computed from |
|---|---|---|---|
| **Memory** | Can they recall this fact right now? | 1 | FSRS retrievability over their own review log |
| **Performance** | Can they answer a *new* exam-style question? | 2–3 | Held-out, never-hinted item attempts |
| **Readiness** | What would they score today? | 4 | Performance + coverage → scaled section score |

Each ships with: point estimate, range, % of exam covered, confidence indicator, last-updated time, top reasons, and the give-up rule that applies.

**Never a single blended number.** Readiness is reported per section. A total is shown only as the sum of the three science sections, always labelled "CARS not modeled."

A **topic** throughout is one AAMC content category (1A, 5C, …) — 31 in total,
9 in Bio/Biochem, 10 in Chem/Phys, 12 in Psych/Soc. Cards are attributed to one
through a read-time crosswalk; the student's notes are never written to. See
[CONTEXT.md](../CONTEXT.md) and [ADR-0002](./adr/0002-topics-are-resolved-through-a-read-time-crosswalk.md).

## 3. The give-up rule (enforced in Rust, not in the UI)

The app abstains and says what would fix it. Thresholds are constants in `rslib/src/speedrun/thresholds.rs`.

| Score | Abstains unless | Abstention message |
|---|---|---|
| Memory (per section) | ≥ 200 graded reviews AND ≥ 30 distinct cards in that section's topics | "Not enough review history in {section}." |
| Performance (per section) | ≥ 20 held-out attempts **in that section** AND ≥ ⅓ of the section's topics attempted — BB 3, CP 4, PS 4 | "Only {n} unhinted questions answered in {section}. Need 20, across at least {m} topics." |
| Readiness (per section) | Memory AND Performance both available AND ≥ 50% of that section's outline topics covered | "You've covered {p}% of {section}. Need 50%." |
| CARS | Always abstains | "We don't model CARS knowledge, because the AAMC says there isn't any to model." |

Abstention is the default state. A score appears only when it is earned.

**Never report a range narrower than the AAMC's own ±2 points.** Any computed interval tighter than that is widened to ±2.

## 4. What the app does

### 4.1 Review (unchanged)
The student reviews their own deck in Anki. Speedrun does not alter the queue, FSRS intervals, or grading. Topic labels are hidden in the reviewer while the question is on screen (SpikyPOV 7).

### 4.2 The coach loop (desktop only)
After a review round, the agent picks concepts where the student looks like they are running on recognition, and runs a **spoken** loop:

1. **Fresh question, asked cold.** Never hinted, never explained mid-attempt. *This is the only step that scores.*
2. **Confidence, before the answer is revealed.** Never after.
3. **Explain the concept aloud.** "Explain what this question is actually testing" — not "why did you pick B."
4. **Contrast pair.** Same question, one detail changed. What changes, and why? They talk again.
5. **Revise.** They may amend what they said.
6. **Only now, the rule.** The app states it.
7. **Personal guide** for that question type, built from their own mistakes.

Steps 3–7 are teaching and are **never graded**. The agent asks once and then stays quiet.

### 4.3 Dashboard (desktop + Android)
Three scores with ranges, coverage map against the AAMC outline, abstention reasons, and the single best next thing to study.

**Unmapped cards are shown, not hidden.** Every mastery figure states how many
cards it could not place. A number computed over a third of a deck with the other
two thirds invisible is the kind of measurement this product exists to replace.

## 5. Platform split

| Capability | Desktop | Android |
|---|---|---|
| Review sessions on the shared deck | ✅ | ✅ |
| Rust engine incl. Speedrun backend methods | ✅ | ✅ |
| Three scores + ranges + give-up rule | ✅ | ✅ |
| Coverage map | ✅ | ✅ |
| Bidirectional sync, offline-tolerant | ✅ | ✅ |
| Voice coach loop | ✅ | ❌ (out of scope, stated in README) |
| AI item generation | ✅ | ❌ |

Spec §4 requires the phone to run real sessions, sync both ways, work offline, and show the same three scores under the same give-up rule. It does not require the coach. That is the deliberate scope cut.

## 6. Two off switches

| Flag | Effect | Purpose |
|---|---|---|
| Add-on disabled | Stock Anki behavior. Nothing of ours loads. | "Anki works as before"; ablation build #3 |
| `speedrun.coach_enabled = false` | Reviews, scores, coverage, dashboard all work. No spoken explain loop. | Ablation build #2 |
| `speedrun.ai_enabled = false` | No generation, no coach. Memory score, coverage, dashboard still work from the Rust engine. | Spec §3 non-negotiable: both apps run with AI off |

A test asserts that with the add-on disabled, queue order and scheduling decisions are identical to upstream Anki.

## 7. In scope / out of scope

**In scope**
- Reading the student's deck as a measuring instrument
- Diagnosing *why* something was missed, not just *that* it was
- Voice as the primary coach interaction (desktop)
- The three science sections

**Out of scope**
- Replacing Anki; authoring or modifying the student's notes, cards, or review history
- Competing on question volume
- Teaching content — this is a coach and a measuring instrument
- Any score more precise than AAMC's ±2
- **A text box on any screen with a live question.** Banned, not discouraged (SpikyPOV 2)
- Full RAG over licensed prep material and video (future; one bounded corpus for now)

## 8. AI safety gates (SpikyPOV 3)

- A generated item ships **only** if the supporting span for the correct answer is retrieved from the corpus and matched against it. No span, no ship.
- **Asking an LLM to verify its own item is banned.** The fake-organ result settles this — generator and checker share a blind spot.
- Every AI output carries `{source_id, span}` through the graph state. An output with no source is dropped, not shown.
- Corpus for v1: the AAMC content outline (all 31 content categories) plus **one** OpenStax book —
  *Biology*, 1st edition, whose CC BY 4.0 licence was read from OpenStax's own archive API at
  download time and recorded. Bio/Biochem only; the other sections have no book indexed, and
  chunks that cannot be honestly attributed to a content category are left unattributed.

## 9. Acceptance criteria (mapped to graded hard limits)

| # | Criterion | Fails → |
|---|---|---|
| A1 | Traceability table exists, every feature in a row | 60% cap overall |
| A2 | Real Rust change: 3 Rust unit tests + 1 Python test, undo intact, no corruption, one-page rationale, upstream files listed | 50% cap |
| A3 | Android runs the same engine and syncs both ways | 70% cap |
| A4 | Held-back data + rerunnable setup | 60% cap |
| A5 | Both apps install and run on a clean device | 50% cap |
| A6 | App abstains below the give-up rule; no invented readiness numbers | **automatic fail** |
| A7 | Leakage check runs clean | that score → 0 |
| A8 | Every AI output traces to a named source | AI section → 0 |
| A9 | Public fork, AGPL-3.0-or-later, credit to Anki, exam at top of README | — |

## 10. Performance targets (report p50 / p95 / worst on a 50,000-card deck)

- Button press acknowledged: p95 < 50 ms, both platforms
- Next card after grading: p95 < 100 ms
- Dashboard first load < 1 s, refresh < 500 ms, never a frozen screen
- Normal session sync < 5 s
- Memory at 50k cards: under a stated ceiling, desktop and midrange phone
- Cold start < 5 s desktop, < 4 s phone; nothing blocks the UI > 100 ms
- Zero corrupted collections across the crash test
