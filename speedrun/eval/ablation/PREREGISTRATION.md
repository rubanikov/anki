# Ablation — Pre-registration

**Written at: `2026-08-02T08:11:09Z` (ISO-8601, UTC).**

**Nothing had been measured when this was written.** At the time of this
timestamp no intervention block had run, no retention test had run, no
immediate post-block accuracy had been recorded, no participant had been
recruited or assigned, and no held-out item had been attempted by anyone. The
H2 P-set was empty or unread. Every quantity in this document is a prediction,
an assumed value used for a power calculation, or a blank to be filled in
later. There are no measured numbers in this file, and there must never be —
measured numbers go in [RESULTS.md](./RESULTS.md).

The commit that introduces this file is the external check on the timestamp
above. It precedes [T-16](https://github.com/rubanikov/anki/issues/18), the
ticket that runs block one.

Vocabulary is [CONTEXT.md](../../CONTEXT.md). The design decision this
implements is
[ADR-0007](../../docs/adr/0007-the-ablation-measures-delayed-retention.md).

### Amendment, `2026-08-02T08:52Z` — before any data existed

The main number was **changed from Δ_product (A − C) to Δ_loop (A − B)**, and
§1 was rewritten to stop claiming this experiment tests SpikyPOV 2.

Both errors had the same root: the first draft treated "the spoken coach loop"
and "voice is the safety mechanism" as one claim. They are not. POV 2 is about
voice making copying physically impossible; the loop's benefit rests on
self-explanation evidence cited under it. A − C could not have attributed a
result to either, and no arm here isolates voice at all.

This amendment is recorded rather than made silently because the timestamp above
is the document's entire value. It was made while every set was still empty, no
participant had been recruited, and no block had run — the same conditions the
header asserts. Once a single number exists, nothing in this file may change
again except through RESULTS.md §7.

---

## 1. The claim being put at risk

**The coach loop earns its place.** A student who runs the loop after a review
round will answer **held-out items** better *later* than the same student
reviewing the same material for the same time without it.

This is a claim about **delayed retention**, not about same-session
performance. Measuring it immediately after the blocks would commit, in our own
headline experiment, exactly the "measured while the app was helping" error the
product exists to attack (ADR-0007).

### What this experiment does *not* test

**It does not test SpikyPOV 2.** That POV says something narrower and stranger:
*talking is the only way of working where a student physically cannot copy the
answer — choosing voice is a decision about measurement, not about user
experience.* Every arm here that involves the loop involves speaking, so voice
sits on the same side of every comparison and cannot be isolated by any of them.

The experiment that would test POV 2 is **spoken loop versus typed loop**, and
[the Brainlift records that no such study exists anywhere](../../../../brainlifts/BRAINLIFT_v3.md).
We are not running it either: a fourth arm on a design already at n = 1–3 would
make an underpowered result less interpretable, not more. That it is untested is
stated rather than papered over, and POV 2 is falsified instead by two things
this experiment does not touch — the enforcement test (no text input on any
screen with a live question; if one exists, the mechanism is not enforced) and
the speak-rate precondition in §8.

Self-explanation evidence (0.55 overall, 0.53 on transfer) is cited *under* POV
2 as support for asking students to explain. It is not the voice claim, and this
experiment tests the explaining, not the voice.

---

## 2. Design

**Within-subject, counterbalanced, three conditions on matched topics.** Every
participant runs all three conditions.

| Arm | Configuration | What the participant gets |
|---|---|---|
| **A — full coach loop** | add-on on, `speedrun.coach_enabled = true`, `speedrun.ai_enabled = true` | Review round, then the coach loop: cold question, confidence stated **before** the answer is revealed, explanation aloud, **contrast pair**, revision, then the rule |
| **B — coach off, scores only** | add-on on, `speedrun.coach_enabled = false` | Review round, plus Memory, coverage, the dashboard and its abstentions. No spoken loop |
| **C — plain Anki** | add-on disabled | Stock unmodified Anki reviewer. Nothing of ours loads |

Arm C is the status quo the product claims to beat. Arm B sits between them and
exists to separate "the loop did it" from "seeing a score did it."

**Matched topics.** Three topic-sets — **T1, T2, T3** — are assembled from the
one section whose **Crosswalk** is complete, and are fixed and written into
[RESULTS.md §1](./RESULTS.md) *before* any participant is assigned. Each
topic-set is one or more **Topics** from the AAMC **Outline**. Matching is on
three quantities, all computable from the **Collection** with no attempt data:
card count with review history, mean Memory, and **Coverage**. Sets are formed
by ranking candidate Topics on those three and dealing them round-robin into
T1/T2/T3. **Unmapped cards** are excluded from the matching and the count of
them is recorded.

**Study time is held equal:** every block is a fixed **20 minutes** of study
time, identical in all three arms. Arm A spends part of that 20 minutes in the
coach loop rather than on extra cards — that cost is part of the manipulation
and is not compensated for. Card counts will therefore differ between arms and
that difference is recorded, not corrected.

---

## 3. Randomisation and counterbalancing

A 3×3 Latin square, fixed here in advance. Participants are assigned to rows in
**order of consent** — first to consent is P1. No row is re-drawn, and no
participant is reassigned after a block has started.

| Participant | Block 1 | Block 2 | Block 3 |
|---|---|---|---|
| **P1** | **A** on T1 | **B** on T2 | **C** on T3 |
| **P2** | **B** on T3 | **C** on T1 | **A** on T2 |
| **P3** | **C** on T2 | **A** on T3 | **B** on T1 |

Across three participants this balances arm × block position, arm × topic-set,
and block position × topic-set — each pairing occurs exactly once.

**Stated now, in advance:** with n = 1 the design is *not* counterbalanced —
arm is fully confounded with block order and with topic-set. With n = 2 it is
partially counterbalanced. This is recorded as a limitation of the realised n,
not discovered afterwards. The row table above is fixed so that the confound,
when it exists, is at least a *known* confound rather than a chosen one.

**Retention-test item order** is shuffled per participant with a seeded RNG.
The seed is written into RESULTS.md before the retention session runs.

---

## 4. The main number

> **Δ_loop = delayed held-out accuracy in Arm A − delayed held-out accuracy in
> Arm B**, in percentage points, pooled over attempts across participants,
> reported with a 95% interval.

One number. Named now. Coach loop on versus coach loop off — **the same app
either way**, so scores, coverage, the dashboard and its abstentions are present
in both arms and the only difference is the loop. Measured roughly twelve hours
after the blocks, on **held-out items** the participant has never seen and that
appeared in no block.

**Why A − B and not A − C.** A − C compares the whole product against plain
Anki, so a positive result would be consistent with the loop working, the
dashboard working, the hidden topic labels working, or any combination —
it attributes nothing. A − B changes one thing. It is also the harder test, and
the one [TRACEABILITY](../../docs/TRACEABILITY.md) commits to, so it is the one
that can actually fire.

- **Interval method, fixed in advance:** Newcombe hybrid-score interval for the
  difference of two independent proportions, 95%. Per-arm accuracies are
  reported with Wilson score intervals. No other interval method may be
  substituted after the numbers exist.
- **Unit of analysis:** the attempt. Per-participant Δ values are also reported
  individually, so a pooled number cannot hide a participant who went the other
  way.
- The ±2-scaled-point widening rule applies to **Readiness**, not to this
  experiment; it is named here only so its absence is not read as an oversight.

### Secondary numbers, also pre-registered

1. **Δ_product = Arm A − Arm C** (delayed). The whole app against the status quo
   a student actually has. Reported alongside the main number every time, and
   never on its own — it cannot say *what* helped, only that something did.
   A positive Δ_product with a flat Δ_loop means the loop was not the thing.
2. **Δ_scores = Arm B − Arm C** (delayed). Whether seeing honest scores alone
   moves anything.
3. **Speak-rate** — the share of coach prompts in Arm A where the participant
   actually spoke. A mechanism precondition, not an outcome. See §8.

---

## 5. Predicted direction, and why

**Predicted: Δ_loop > 0.** Arm A ends up with higher delayed held-out accuracy
than Arm B — the loop adds something the scores and dashboard alone do not.
**Δ_product > 0** is predicted too, and by a larger margin, since it carries the
loop's effect plus whatever the rest of the app contributes.

The reasoning, stated so it can be held against us:

- The cold question is **retrieval practice on an uncued item**. Plain Anki
  practice is cue-then-answer; a held-out item arrives with no cue. Practising
  the retrieval that the test actually requires should transfer better than
  practising a different one.
- **Confidence stated before the reveal** forces a commitment, which makes the
  subsequent feedback informative rather than confirmatory.
- **Explaining aloud** is self-explanation: it exposes the gap between
  recognising a card and being able to say what it means, during the block
  rather than on exam day.
- The **contrast pair** — one detail changed — trains discrimination between
  confusable items, which is what an unseen exam-style item mostly tests.

Predicted ordering across arms: **A > B > C** on delayed accuracy, with the A–C
gap the largest of the three.

---

## 6. The falsifier

Written before any data exists, so it cannot be moved afterwards.

**Decisive falsification of the main claim:** the 95% interval for **Δ_loop**
lies entirely **below zero** — the app without the loop beats the app with it on
delayed held-out accuracy. If that happens the claim is wrong and the write-up
says so in those words.

**Directional evidence against, reported as such even when underpowered:** the
**point estimate** of Δ_loop is **≤ 0**. Given n = 1–3 the decisive test above
will almost certainly not fire in either direction (§9), so this weaker
falsifier is the one that will realistically carry information. A point estimate
at or below zero is reported as *the coach loop did not help, and the point
estimate went the wrong way* — not as noise, not as "directionally encouraging."

The loop is the expensive part of the product. If it is doing nothing, that is
the finding, and it is the reason A − B rather than A − C is the number that
governs: A − C could come out positive on the strength of the dashboard alone
and would tell us nothing about whether the loop earned its cost.

**Failure of the product-level claim, even if the loop works:** the point
estimate of **Δ_product (A − C) ≤ 0**. The loop may improve on the app without
it while the app as a whole still fails to beat plain Anki. Both numbers are
reported every time, in that order, whatever they say.

**Falsification by refusal:** speak-rate in Arm A below **50%**. Then Arm A did
not receive the manipulation and the comparison is void as evidence *for* the
thesis — reported as a mechanism failure. Stating the 50% line now stops it
from being redrawn once the number exists.

**Traps we are closing in advance.** These outcomes may **not** be reported as
support:

- Δ_product positive but Δ_loop ≤ 0, written up as if the loop were vindicated.
- Both immediate and delayed accuracy *lower* in Arm A, written up as desirable
  difficulties. Desirable difficulties predict lower-immediate-and-**higher**-
  delayed. Lower-and-lower is the thesis failing (§7).
- Any post-hoc subset of Topics, participants, or items in which the effect
  appears. Subsets are exploratory, labelled exploratory, and reported after
  the pre-registered numbers.

---

## 7. The manipulation check, and its prediction

**Measure:** immediate post-block accuracy — a short fixed set of items on that
block's Topics, attempted **within five minutes** of the block ending, before
the participant leaves. Drawn from **held-out items** reserved for the
immediate check and disjoint from the delayed retention set; no item is used
twice, in either direction.

> **Predicted now, in advance: immediate accuracy in Arm A will be FLAT OR
> LOWER than in Arm C.**

This is stated *before* the data exists precisely so that, if it happens, it is
a **prediction confirmed** rather than an excuse invented afterwards.

**Why lower-immediate-but-higher-delayed is consistent with the thesis.** This
is the desirable-difficulties pattern: interventions that make study effortful
— retrieval before restudy, discrimination between confusable cases, committing
to an answer before feedback — routinely *depress* performance measured
immediately, while *improving* retention measured later. The immediate measure
is taken while the effort is still resolving; the delayed measure is taken
after the storage benefit of that effort has had time to matter. Arm A also
spends part of its fixed 20 minutes on the loop instead of on more cards, so it
arrives at the immediate check with less raw exposure. An intervention that
looks worse immediately and better later is the signature we predict, not a
result we would need to explain away.

**And what would make it an excuse.** The manipulation check is not armour. It
is falsified as an explanation if:

- immediate accuracy in Arm A is **lower** *and* delayed accuracy in Arm A is
  also **lower** — that is not a desirable difficulty, that is the intervention
  being worse (see §6);
- immediate accuracy in Arm A is **higher** *and* delayed accuracy is higher —
  that is a real result, but it is weaker support for *this* thesis, because it
  is equally consistent with a plain effort, novelty or attention effect rather
  than the delayed-retention mechanism. It will be reported with that
  qualification attached.

Speak-rate is logged in the same session, for the same reason: if the
participants did not talk, the loop was not run.

---

## 8. The delay

- **Intervention blocks run early.** Target in the build schedule: **H+5 to
  H+6**. They cannot start before the corpus, the **Generation gate**, and a
  usable P-set exist ([T-16](https://github.com/rubanikov/anki/issues/18),
  blocked by T-02, T-10, T-14).
- **Retention test roughly 12 hours later**, landing near **H+18**
  ([T-23](https://github.com/rubanikov/anki/issues/23)). It is scheduled from
  the logged start time of block one, and it is wall clock — it cannot be
  compressed at the end.
- **ADR-0007 originally estimated ~15 hours.** That was corrected to **~12
  hours** during ticket planning, because the blocks depend on the corpus, the
  generation gate and a usable P-set, which pushes block one from H+3 to H+5/6.
  Twelve hours is still a genuine delayed-retention measure and the design
  survives; the schedule is now the binding constraint.
- **The floor, stated in advance: roughly 8 hours.** Below about eight hours
  the measure stops being meaningfully delayed. **Pre-commitment:** if the
  realised delay is under 8 h, the result is reported as a short-delay measure
  that **does not** carry the delayed-retention claim, and it says so in the
  headline rather than in a footnote.
- The **actual delay in hours** is recorded in RESULTS.md, per participant.

Both blocks and the retention test are run against whatever version of the app
works at the time, well before anything is polished. That is the entire cost of
ADR-0007 and it is accepted here.

---

## 9. Expected power, stated before the result

**n will be 1–3 participants.** With roughly 12 delayed held-out items per arm
per participant, that is 12–36 attempts per arm.

**The interval will cross zero.** As an a priori projection — computed from the
design, not from any measurement — a 95% Newcombe interval on a difference of
two proportions with 36 attempts per arm, at an assumed accuracy near 60%, is
on the order of **±22 percentage points**. Any effect this intervention could
plausibly produce (5–15 points) sits inside that. We are not going to detect
it, and we know that now.

**Sample size that would be needed** (standard two-proportion formula, 80%
power, α = 0.05, two-sided; the accuracies below are *assumed* values chosen in
advance for the calculation, not measurements):

| Effect assumed | Attempts needed **per arm** |
|---|---|
| 0.55 → 0.70 (15 points) | ≈ 165 |
| 0.55 → 0.65 (10 points) | ≈ 370 |
| 0.55 → 0.60 (5 points) | ≈ 1,530 |

**Pre-committed reporting language.** Unless the interval excludes zero, the
result is reported as:

> **"Cannot distinguish."** Δ_loop = *point estimate*, 95% interval
> *[lo, hi]*, n = *participants*, *attempts* attempts per arm. Detecting an
> effect of this size at 80% power would require ≈ *N* attempts per arm.

This sentence is written now so that an underpowered result is a **planned
outcome**, not a disappointment spun after the fact. A POV put at risk and not
confirmed beats one never tested. The point estimate and its direction are
reported in the same breath, whichever way they point.

---

## 10. Analysis pre-commitments

Fixed now, so there is nothing left to decide once the numbers exist.

1. **Retention items** are drawn from the **H2 P-set**, mapped to the same
   Topics, and appear in **no block** and in no immediate check. Their text
   never enters the **Collection**. Their ids and hashes are in
   `speedrun/eval/holdout/MANIFEST.md`.
2. **No hints, no explanations, no feedback** during the retention session.
   Topic labels are hidden while a question is on screen. No text box on any
   screen with a live question.
3. **The leakage check
   ([T-20](https://github.com/rubanikov/anki/issues/20)) must exit 0 before any
   number in RESULTS.md is reported.** A score contaminated by **Leakage** is
   void, and would be reported as void rather than quietly reissued.
4. **Item count is fixed before the retention session starts** and written into
   RESULTS.md §1. No optional stopping; no adding items after seeing results.
5. **Exclusions are fixed now.** The only exclusion rule is the disengagement
   filter: an attempt with a response time under **3 seconds**. Such attempts
   are flagged, and the main number is reported **both** with and without them,
   so the choice cannot be made after the fact. No participant is excluded
   after their data is seen, for any reason.
6. **Reporting order is fixed:** Δ_loop first, then Δ_product, then Δ_scores,
   then the manipulation check, then speak-rate, then anything exploratory —
   regardless of which of them came out best.
7. **Every deviation** from this document is written into RESULTS.md §7, with
   the reason and the date. An empty deviations section is a claim we are
   making, and it is checkable against this file's commit.
8. **RESULTS.md is filled in once.** If a number is corrected, the correction
   is added with its reason, not silently overwritten.

---

## 11. What is reported no matter what

The result — including "cannot distinguish," including a point estimate
pointing the wrong way, including a speak-rate that says nobody talked — is
reported in the README and the demo. There is no outcome of this experiment
that gets left out.
