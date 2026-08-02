# The paraphrase test

**Status: built, not run. The three numbers below are blank because filling them
in requires a person sitting the test, and no participant was available before
the deadline. Nothing on this page is a result.**

The obvious shortcut — have a model answer the 118 items and report its score —
is not taken and is not going to be. A model's accuracy on these items measures
the model. Reporting it as this test's result would fabricate the single piece
of evidence the whole thesis rests on, and it would be undetectable in the
artifact. `run_paraphrase.py` has no mode that answers for a student; that is a
property of the harness, not a convention.

## Why this test is the load-bearing one

The claim is that a Memory model and a Performance model are different
measurements: knowing your card is not the same as knowing the material. The
test that can falsify it is three points on **one** student, in one sitting:

| point | what it measures | DOK |
|---|---|---|
| **recall on their own card** | the card, in the words they memorised | 1 — Memory |
| **accuracy on a reworded version of that card** | the same fact, different words | ~2 |
| **accuracy on a held-out item they have never seen** | the material | 2–3 — Performance |

If the three collapse to one number, the Performance model is copying the Memory
model and the thesis is wrong. [ADR-0004](../../docs/adr/0004-performance-and-the-paraphrase-test-use-separate-sets.md)
is what makes that outcome reachable: the P-set and the R-set are **separate
sets**, because when they were one set Performance was a score on paraphrases of
cards already studied and the test could not fail.

## Pre-registered, before any of it existed

From `speedrun/eval/holdout/MANIFEST.md`, section H4, frozen `2026-08-02T08:12:41Z`:

> The paraphrase test reports three numbers with ranges, on one student: recall
> on the card, accuracy on the R-set, accuracy on the P-set. The target stated
> in advance is a **gap ≥ 15 points** between card recall and P-set accuracy.
> The gap is reported whichever way it comes out, and if the three numbers
> collapse into one, that is published as a finding.

**Target: card recall − held-out accuracy ≥ 15 points.** The harness prints
`MET` or `NOT MET` with the same emphasis either way, and prints the falsifying
finding by name when the interval on that gap includes zero.

## The three numbers

|   | accuracy | 95% interval | n | method |
|---|---|---|---|---|
| recall on their own card (DOK 1) | — | — | 30 | Wilson |
| accuracy on Reworded cards | — | — | 60, from 30 cards | cluster bootstrap over cards |
| accuracy on Held-out items (DOK 2–3) | — | — | 28 | Wilson |

| gap | points | 95% interval | method |
|---|---|---|---|
| card − reworded (paired) | — | — | bootstrap over the 30 cards |
| **card − held-out (independent)** | **—** | **—** | Newcombe hybrid score |

| | |
|---|---|
| target met? | **not evaluable — the test has not been run** |
| three numbers collapse to one? | **not evaluable — the test has not been run** |

**These are blank, not zero and not pending a rerun.** A dash here means nobody
has answered an item.

## What would run it

One command, from the repo root, with a participant at the keyboard:

```bash
python speedrun/eval/paraphrase/run_paraphrase.py --session <name> --participant <who>
```

It asks 118 questions and takes roughly 45–70 minutes. Answers are flushed to
`speedrun/eval/paraphrase/sessions/<name>.jsonl` as they are given, so it can be
stopped and resumed with the same `--session`. Then:

```bash
python speedrun/eval/paraphrase/run_paraphrase.py --session <name> --score --json result.json
```

which prints the table above with the numbers in it, and writes the same as
JSON. A third party can re-grade every free-response answer from the recorded
text:

```bash
python speedrun/eval/paraphrase/run_paraphrase.py --session <name> --regrade <grader>
```

The harness itself is runnable now, with no participant, and proves it:

```bash
python speedrun/eval/paraphrase/run_paraphrase.py --selftest
```

drives presentation, recording, resume, quit and the whole scoring path with
scripted answers, checks the interval arithmetic against hand-computable cases,
stamps `synthetic: true` on everything it writes, and prints in capitals that
none of it is a result.

## The design, in the order it happens

**Block 1 — the student's own 30 cards.** Shown exactly as their deck shows
them, blank marker and all. They type an answer, see the card's answer, and
grade themselves — the same judgement Anki asks for on every review. This is the
first number.

**Block 2 — the other 88 items, interleaved.** The 60 Reworded cards and the 28
Held-out items in one stream, shuffled together with seed `20260802` and spread
so the two rewordings of one fact are never within four items of each other. If
the R-set came first and the P-set last, part of any gap between them would just
be fatigue; interleaving spends the fatigue on both. Held-out items are multiple
choice and grade themselves. Reworded cards are short answer, self-graded.

**The ordering confound, stated rather than hidden.** Block 2 follows Block 1, so
the student has just seen each card's answer when they meet its rewording. That
inflates the middle number. It is the conservative direction for the
pre-registered claim: anything that lifts the middle point makes the three
numbers *more* likely to collapse, not less. The alternative — Block 2 first —
would contaminate card recall, which is the measurement the Memory model is
being checked against. The order is fixed here, in advance, for that reason.

## The items

**The R-set (H4) — 30 cards × 2 rewordings.** The 30 were drawn by the
manifest's frozen rule: crosswalk-mapped Bio/Biochem cards, sorted by card id
ascending, `random.Random(20260802).sample(..., 30)`. Not re-rolled; the seed is
hard-coded in `select_rset.py` rather than exposed as a flag, because a seed you
can pass on the command line is a seed you can re-roll. 1,098 of the deck's
2,888 cards are mapped, which is the number `speedrun/crosswalk/README.md`
reports, computed here independently from the `.apkg`. The rewordings were
written by the agent service's model (`gpt-5`, resolved `gpt-5-2025-08-07`), two
per card, in 30 calls, and each pair was appended to the H4 ledger in
`MANIFEST.md` before the next card started.

**Quality: 46 of the 60 are items I would show.** All 60 clear both wording-reuse
thresholds — max shared run with the card is 3 words, mean content-word overlap
0.10 — so **no reworded item is answerable by recognising the card's string**,
which is the defect that would have made this a recognition test. 14 have other
defects, 9 of them stems that describe their own answer. Every one is named with
its reason in [`QUALITY.md`](QUALITY.md), and every one pushes reworded accuracy
*up*.

**The P-set (H2) — the 28 Held-out items** from `speedrun/eval/pset/`, generated
from the corpus and never derived from a card. Their own defects are catalogued
in `speedrun/eval/pset/QUALITY.md`: about a third have a wording problem that
makes them easier than the fact they test, which pushes held-out accuracy up and
the pre-registered gap down.

## The deviation, named

The manifest's step 1 also requires an eligible card to carry **≥ 3 graded
reviews at selection time**. **It was not applied, and this is the one place
this ticket departs from the frozen rule.**

The only collection this project has is `miledown.apkg`, a pristine shared deck:
`revlog` is empty and all 2,888 cards have `reps = 0`, which
`speedrun/eval/deck/DECK_REPORT.md` flagged when it was acquired. Applied
literally, the clause leaves zero eligible cards and there is no R-set at all.
`select_rset.py` therefore applies the filter, reports that it removed
everything, and refuses to draw unless `--no-study-history` is passed — which
writes the deviation into `rset_selection.json` rather than letting it pass
silently.

This is not a shortcut around the clause. It is the same wall as the rest of the
ticket: **nobody has studied the deck because studying it needs the participant
the test is waiting on**, and recall on a card nobody has reviewed is undefined —
so the first of the three numbers needs that participant too. Point
`--collection` at a studied collection and the filter applies for real, the flag
is refused, and the draw is the manifest's rule exactly. The 30 cards would then
change, which is correct: the seeded draw is over the eligible pool, and the
eligible pool is part of the rule.

**This belongs in `MANIFEST.md` > Amendments.** That file is not this ticket's to
hand-edit, so the row is proposed rather than written; see the handover note in
the ticket report.

## Caveats that travel with any numbers this produces

- **One student, one sitting.** Everything is n = 1 at the person level. The
  intervals are on items, not on people, and no interval here says anything
  about a second student.
- **The intervals are not all the same shape, on purpose.** Card recall and
  held-out accuracy are 30 and 28 independent binary outcomes — Wilson. The
  R-set is 60 outcomes from **30 cards**, and two rewordings of one fact are not
  two independent looks at a student, so its interval is a cluster bootstrap
  over cards. The naive Wilson is printed beside it so the size of the
  correction is visible rather than asserted.
- **Self-grading.** Free-response answers are graded by the person answering
  them. The typed text is recorded verbatim precisely so that `--regrade` can
  put a second grader on the same answers and the two gradings can be compared.
- **Item defects push the same way.** The R-set defects in `QUALITY.md` and the
  P-set defects in `speedrun/eval/pset/QUALITY.md` both raise the second and
  third numbers, which narrows the gap. If the gap comes out large anyway, that
  is despite the items; if it comes out small, the items are the first
  explanation to rule out.

## Files

| file | committed | what it is |
|---|---|---|
| `select_rset.py` | yes | the manifest's selection rule, executable |
| `generate_rset.py` | yes | 30 model calls, 60 rewordings, ledgered as produced |
| `wording.py` | yes | the wording-reuse measure and its two frozen thresholds |
| `check_rewordings.py` | yes | four mechanical checks over the 60 |
| `run_paraphrase.py` | yes | the harness |
| `scoring.py` | yes | Wilson, cluster bootstrap, paired bootstrap, Newcombe |
| `rset_selection.json` | yes | the 30 card ids, topics and hashes — no card text |
| `h4_rset.jsonl` | yes | the 60 Reworded cards (mirrored to `eval/holdout/h4_rset.jsonl`) |
| `run_log.jsonl` | yes | every draft, its overlap measures, and the model id |
| `QUALITY.md`, `PARAPHRASE.md` | yes | the hand read, and this |
| `rset_cards.local.json` | **no** | the deck author's card text, which the harness reads |
| `sessions/` | **no** | a participant's answers — their own study data |
