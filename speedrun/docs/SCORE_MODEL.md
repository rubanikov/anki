# Speedrun — Score Model

Required deliverable: "Score mapping method written down, with a range." This is that document.
Every number below is either computed from held-back data or labelled as an assumption with the thing that would falsify it.

---

## 1. Memory (DOK 1)

**Definition.** Probability the student recalls a taught fact right now.

**Method.** FSRS retrievability `R` per card, from Anki's own scheduler state — we do not re-implement FSRS. Aggregated per outline topic:

```
mastery(topic) = Σ(R_i) / n     over cards mapped to topic, excluding Speedrun::Attempt notes
section_memory = Σ(w_t · mastery(t))   w_t = AAMC outline weight for topic t
```

**Range.** Bootstrap over cards (1000 resamples), report the 5th–95th percentile.

**Validation (required).** Hold back the most recent 20% of reviews by time. Predict each held-back review's outcome from `R` at that moment. Report **calibration chart + Brier score + log loss**. At 80% predicted, observed should be ~80%.

**Assumption that could sink it:** card → topic mapping. MCAT decks lack the mature tagging the medical-school decks have, and reviewers describe some content as outdated. If mapping accuracy is poor, every downstream number inherits the error. **Measured, not assumed:** hand-label 100 cards, report mapping accuracy, propagate it as an explicit uncertainty term.

---

## 2. Performance (DOK 2–3)

**Definition.** Probability of answering a *new* exam-style question correctly, with no help.

**Data.** Only `Speedrun::Attempt` notes flagged `holdout=true`. Items generated before the model was fit, never shown during coaching, never used as teaching material.

**Method.** Logistic regression — deliberately simple, because with this much data anything fancier is unfalsifiable:

```
logit p(correct) = β0
                 + β1 · topic_mastery        (from §1)
                 + β2 · dok_level            (1 / 2 / 3)
                 + β3 · topic_coverage
                 + β4 · confidence_before    (asked before the reveal, per Eva & Regehr)
                 + β5 · time_to_first_speech (see below)
```

**On timing.** Wise's work says raw speed is a two-headed signal — fast can mean "knew it cold" or "gave up." Used **only** to discard attempts where the student clearly wasn't engaging. The one timing feature we do keep is `time_to_first_speech`: the pause before they start talking is not reading time, and nobody collects it. Flagged as exploratory; if `β5`'s interval spans zero, we say so and drop it.

**Validation (required).** Train/test split fixed before fitting. Report accuracy, AUC, and calibration on held-out items. Compare against a baseline that uses memory alone — if it doesn't beat that baseline, performance is just memory wearing a hat, which is exactly what the paraphrase test is designed to catch.

---

## 3. Readiness (DOK 4)

**Definition.** Projected scaled score per section, with a range.

**Method, stated as the assumption it is.** We have no student-outcome data — the BrainLift is explicit that no study relates Anki use to MCAT scores, and that is the single biggest hole in the argument. So the mapping is built from the AAMC's own published structure, not fitted to outcomes:

1. Predict p(correct) for every item on the section's outline, weighted by the AAMC item mix: **35% recall-level, 45% concept reasoning, 20% analysis.**
2. Sum to an expected raw proportion for the section.
3. Map raw proportion → scaled 118–132 using the published percentile anchors.
4. Section total = sum of the three science sections. **CARS is never included** and the total is always labelled "3 sections, CARS not modeled."

**Range.** Three sources of uncertainty, combined and never narrowed:

| Source | Handling |
|---|---|
| Performance model interval | propagated from §2 |
| Coverage shortfall | topics with no data widen the interval toward the section mean |
| Card→topic mapping error | from §1's hand-labelled sample |
| **AAMC's own SEM** | **hard floor of ±2. Any computed interval tighter than that is widened.** |

**What would prove this wrong.** Any student with both a study history and a real AAMC practice score whose actual score falls outside our range. This is the bonus check in §10.4 — if we can get even a handful, we report it. If we can't, **we say the mapping is unvalidated**, because "we calibrated memory but cannot yet prove the projected score" scores higher than a polished number we can't back up.

---

## 4. Abstention

Enforced in `rslib/src/speedrun/thresholds.rs`. Not UI logic — the backend refuses to emit a number, and both platforms inherit it.

| Score | Requires | Else |
|---|---|---|
| Memory (section) | ≥200 graded reviews, ≥30 distinct cards | abstain |
| Performance (section) | ≥20 held-out attempts, ≥8 distinct topics | abstain |
| Readiness (section) | memory ✓, performance ✓, ≥50% outline coverage | abstain |
| CARS | — | **always abstains** |

Every abstention names the specific thing that would resolve it: *"You've covered 31% of Bio/Biochem. Need 50%. The three highest-weight topics with no data are …"*

---

## 5. What we are not claiming

- Not that the projected score is validated against real outcomes. It isn't, and we don't have the data to make it so in the time available.
- Not that the card→topic mapping is clean. It's measured and the error is propagated.
- Not that our score is more precise than the AAMC's own instrument. A reported 500 spans the 42nd to 55th percentile; on the reading section a single point covers 25 percentile points. Any product reporting one confident number is reporting noise.
