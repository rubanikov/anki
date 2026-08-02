# Ablation — Results

**Template only. Every number below is blank until it is measured.**

This file is the fill-in counterpart to
[PREREGISTRATION.md](./PREREGISTRATION.md), written at
`2026-08-02T08:11:09Z` before any data existed. The structure below is fixed by
that document so that filling it in cannot drift from what was pre-registered.
Do not add, remove, or reorder sections. Deviations go in §7.

**Filled in at:** `____-__-__T__:__:__Z`
**Leakage check ([T-20](https://github.com/rubanikov/anki/issues/20)) exit
code:** `____` — *no number below may be reported unless this is 0*

---

## 1. Fixed before the run

*Written before block one. Nothing here is an outcome.*

| Item | Value |
|---|---|
| Topic-set **T1** (Topics) | `____` |
| Topic-set **T2** (Topics) | `____` |
| Topic-set **T3** (Topics) | `____` |
| Matching quantities per set (cards with history / mean Memory / Coverage) | T1 `____` · T2 `____` · T3 `____` |
| Unmapped cards excluded from matching | `____` |
| Block length (fixed at 20 min) | `____` |
| Delayed items per arm per participant | `____` |
| Immediate-check items per block | `____` |
| Retention item-order RNG seed | `____` |
| Participants recruited (n) | `____` |
| Row assignment (consent order → P1, P2, P3) | `____` |

## 2. Timing

| | P1 | P2 | P3 |
|---|---|---|---|
| Block 1 start (UTC) | `____` | `____` | `____` |
| Block 3 end (UTC) | `____` | `____` | `____` |
| Retention session start (UTC) | `____` | `____` | `____` |
| **Actual delay (hours)** | `____` | `____` | `____` |

**Delay ≥ 8 h for every participant?** `____`
*If no: the affected result is reported as a short-delay measure and does **not**
carry the delayed-retention claim (PREREGISTRATION §8).*

## 3. The main number — Δ_loop (Arm A − Arm B)

**Predicted in advance: Δ_loop > 0.**

| Arm | Correct | Attempts | Delayed held-out accuracy | Wilson 95% interval |
|---|---|---|---|---|
| **A** full coach loop | `____` | `____` | `____` | `____` |
| **B** coach off, scores only | `____` | `____` | `____` | `____` |
| **C** plain Anki | `____` | `____` | `____` | `____` |

| Number | Point estimate | Newcombe 95% interval |
|---|---|---|
| **Δ_loop = A − B** | `____` pp | `____` |
| Δ_loop = A − B | `____` pp | `____` |
| Δ_scores = B − C | `____` pp | `____` |

**Per participant** (so a pooled number cannot hide a reversal):

| | Δ_product | Δ_loop | Δ_scores |
|---|---|---|---|
| P1 | `____` | `____` | `____` |
| P2 | `____` | `____` | `____` |
| P3 | `____` | `____` | `____` |

**Excluding disengaged attempts (< 3 s):** Δ_product = `____` pp, 95% interval
`____`. Attempts dropped: `____`.

### Headline sentence

*Use the pre-committed wording (PREREGISTRATION §9) unless the interval excludes
zero:*

> **Cannot distinguish.** Δ_loop = `____` pp, 95% interval `____`, n = `____`
> participants, `____` attempts per arm. Detecting an effect of this size at 80%
> power would require ≈ `____` attempts per arm.

**Direction of the point estimate:** `____` *(positive / zero / negative)*

## 4. The falsifier — checked, not skipped

| Pre-registered falsifier | Fired? | Value |
|---|---|---|
| Δ_product 95% interval entirely below zero (decisive) | `____` | `____` |
| Δ_product point estimate ≤ 0 (directional evidence against) | `____` | `____` |
| Δ_loop point estimate ≤ 0 (mechanism, POV 2) | `____` | `____` |
| Speak-rate in Arm A < 50% (manipulation not delivered) | `____` | `____` |

**Verdict in plain words:** `____`

## 5. Manipulation check — immediate post-block accuracy

**Predicted in advance: Arm A flat or lower than Arm C.**

| Arm | Correct | Attempts | Immediate accuracy | Wilson 95% interval |
|---|---|---|---|---|
| **A** full coach loop | `____` | `____` | `____` | `____` |
| **B** coach off, scores only | `____` | `____` | `____` | `____` |
| **C** plain Anki | `____` | `____` | `____` | `____` |

| Number | Point estimate | Newcombe 95% interval |
|---|---|---|
| Immediate A − C | `____` pp | `____` |

**Prediction confirmed (A flat or lower)?** `____`

**Pattern observed** — tick exactly one, and use the pre-registered reading:

- [ ] Immediate lower, delayed higher → the predicted desirable-difficulties
      pattern. Consistent with the thesis.
- [ ] Immediate lower, delayed lower → **not** a desirable difficulty. The
      intervention was worse. Thesis fails (PREREGISTRATION §6).
- [ ] Immediate higher, delayed higher → a real result, but weaker support for
      *this* thesis; equally consistent with an effort/novelty/attention
      effect. Report with that qualification.
- [ ] Immediate higher, delayed lower → the "measured while the app is helping"
      pattern the product exists to attack, observed in our own app. Report it
      as that.

**Cards reviewed per block** (Arm A trades exposure for the loop; recorded, not
corrected): A `____` · B `____` · C `____`

## 6. Speak-rate

| | P1 | P2 | P3 | Pooled |
|---|---|---|---|---|
| Coach prompts in Arm A | `____` | `____` | `____` | `____` |
| Prompts the participant spoke on | `____` | `____` | `____` | `____` |
| **Speak-rate** | `____` | `____` | `____` | `____` |

## 7. Deviations from the pre-registration

*Every departure from [PREREGISTRATION.md](./PREREGISTRATION.md), with the
reason and the date. "None" is a claim, and it is checkable against that file's
commit.*

`____`

## 8. Exploratory, after the fact

*Anything not pre-registered goes here, below the pre-registered numbers, and is
labelled exploratory. It does not support a claim.*

`____`

## 9. How it was produced

| | |
|---|---|
| App version / commit at block time | `____` |
| Held-out manifest reference | `speedrun/eval/holdout/MANIFEST.md` |
| Command(s) | `____` |
