# Held-out data manifest — the freeze

**Frozen at: `2026-08-02T08:12:41Z`** (ISO-8601, UTC)

This file was written **before any generation run, any calibration run, any
attempt, and any score existed**. Nothing had been measured when the rules below
were fixed. That ordering is the whole point of the document: a cutoff chosen
after seeing a result is not a cutoff, and a held-out set assembled after seeing
a score is not held out.

At freeze time **no data file exists**. Every hash below reads `PENDING`, and a
`PENDING` is a promise, not a number. `freeze.py --verify` fails if a data file
appears while its record still says `PENDING`, so the promise cannot be quietly
skipped.

What this manifest fixes, in advance:

- what goes into each of the four sets, and what may never go into them;
- the split rule for H1, stated precisely enough to be re-run by someone else;
- the **cutoff rule for H3**, stated before anyone looks at a result;
- the pre-registered comparison for H4;
- how an item's SHA-256 is computed, so a later edit to an item is detectable;
- which data may never enter the public fork, and why.

Verify at any time:

```
python speedrun/eval/holdout/freeze.py --verify    # exits non-zero on mismatch
```

Terms used here are the project's: **Held-out item**, **Reworded card**,
**Attempt**, **Leakage**, **P-set**, **R-set** — see `speedrun/CONTEXT.md`.

---

## The record

`state` is one of:

| state | meaning |
|---|---|
| `pending` | the data does not exist yet. The hash is a placeholder, not a number. |
| `open` | the data exists and is still being appended to. Per-item hashes are already fixed in the ledger; the file-level hash is not fixed until the set is closed. |
| `frozen` | the file-level SHA-256 is fixed. Any later change is a `--verify` failure. |

`sha256` is over the **raw bytes of the file**. `records` counts non-empty JSONL
lines. Rows in the block below are written by `freeze.py`; do not hand-edit them.

<!-- FREEZE-RECORDS:BEGIN -->
| set | path | state | sha256 | bytes | records | frozen_at (UTC) |
|---|---|---|---|---|---|---|
| PROTOCOL | speedrun/eval/holdout/freeze.py | frozen | 0ca303002325d6d62ab0fc96fa4224d9601c518f870386e0d72df4469a02dbbe | 22957 | - | 2026-08-02T08:16:07Z |
| H1 | speedrun/eval/holdout/h1_reviews.jsonl | frozen | 3563d7a6f385ac7e4277d749c943f61ef96e879a38bcaddc1f037a6f33e2e257 | 341240865 | 3781295 | 2026-08-02T16:16:28Z |
| H2 | speedrun/eval/holdout/h2_pset.jsonl | pending | PENDING | - | - | - |
| H3 | speedrun/eval/holdout/h3_gold.jsonl | pending | PENDING | - | - | - |
| H4 | speedrun/eval/holdout/h4_rset.jsonl | pending | PENDING | - | - | - |
<!-- FREEZE-RECORDS:END -->

`PROTOCOL` is `freeze.py` itself. It is hashed so the rules cannot be edited
after the fact without the change showing up in `--verify`.

**Item SHA-256.** For a set with a per-item ledger, an item's hash is

```
sha256( json.dumps(content_fields_only, sort_keys=True,
                   separators=(",", ":"), ensure_ascii=False).encode("utf-8") )
```

Only the declared content fields are covered, so bookkeeping added later — when
an item was shown, how an Attempt scored — cannot change an item's hash, while
any edit to the question or the answer does.

---

## H1 — memory-calibration reviews

**Contents.** Reviews held back from
[`open-spaced-repetition/anki-revlogs-10k`](https://huggingface.co/datasets/open-spaced-repetition/anki-revlogs-10k),
per [ADR-0001](../../docs/adr/0001-calibration-uses-a-public-review-log-corpus.md).
The corpus carries no card text and no topic tags: H1 can validate the Memory
model and can say nothing about Topics, Coverage, Performance or Readiness. The
calibration artifact must say so in its own text.

**Split rule — fixed now, so it cannot be tuned to a Brier score later.**

1. Group every review by collection (the corpus's per-user collection id).
2. Within a collection, sort reviews ascending by review timestamp. Ties break
   on `(card_id, review_th)` ascending — a total order, so the split is
   reproducible byte-for-byte by anyone with the same corpus revision.
3. The **last `ceil(0.20 × n)` reviews of each collection** are H1, held out.
   The remaining reviews are the fitting set. The split is per collection, never
   pooled across collections: a global time split would leak a user's future
   through other users' pasts.
4. Collections with `n < 5` reviews contribute nothing to H1 (fewer than 5 gives
   a held-out block of one review, which is noise, not evidence).
5. No sampling, no shuffling, no seed. The rule is deterministic.

**Corpus revision — recorded at download (T-05).** The exact Hugging Face
dataset revision (commit SHA) is recorded here, together with the SHA-256 of
each downloaded file. Without a pinned revision the split above is not
reproducible.

| field | value |
|---|---|
| dataset | `open-spaced-repetition/anki-revlogs-10k-raw` — see the note below |
| revision (commit SHA) | `197633e5ec9f4a177f285447053329db40e2eb5e` |
| downloaded file | `revlogs.7z`, 8 459 427 959 bytes, sha256 `2921e71e2d39156eef198c8516078ec7806d74443900c0a1005f3c4467389f95` |
| bytes actually fetched | 1 107 379 967 — solid block 0 only |
| per-collection file hashes | `speedrun/eval/calibration/corpus_slice.json` (300 rows: collection id, bytes, sha256) |
| collections sampled | 300 of the 1315 in block 0, `random.Random(20260802).sample`, sorted ascending as strings |
| `h1_reviews.jsonl` sha256 | see the record block above |

**Which distribution, and why.** The processed distribution named above,
`open-spaced-repetition/anki-revlogs-10k`, is **gated**: without a Hugging Face
token its parquet files return HTTP 401, and no token exists on the machine that
ran calibration. The same publisher hosts
[`anki-revlogs-10k-raw`](https://huggingface.co/datasets/open-spaced-repetition/anki-revlogs-10k-raw),
ungated, under the same `anki-revlogs-10k` licence, described by the publisher as
"the original data of open-spaced-repetition/anki-revlogs-10k" — the same
reviews from the same 10 000 collections, before the parquet conversion,
exported by Anki's own `Collection::export_dataset`. That is what was downloaded.
It is the same corpus, not a stand-in for it, and it is a closer fit to the split
rule than the processed form: the raw records carry the review's epoch-millisecond
`id`, its `review_kind` and its `ease_factor`, so "sort ascending by review
timestamp" is the record's own timestamp rather than a reconstructed day offset.

`review_th` in step 2 above does not exist as a field in the raw distribution; it
is the review's 1-based rank within its collection under exactly the total order
step 2 describes, and is written into each H1 row as `th`.

**Licence.** Individual research use is permitted; public redistribution is not.
`h1_reviews.jsonl` and every raw corpus file are therefore `.gitignore`d and must
never enter the public fork. `freeze.py --verify` demonstrates their absence from
the working tree rather than asserting it; the leakage check (T-20) extends that
to git-tracked files. The recorded hash still lets the person who ran calibration
prove locally that they scored the same bytes they froze.

---

## H2 — the P-set (Held-out items)

**Empty at freeze time. This is deliberate and is the point of the section.**
No Held-out item exists yet. What is frozen now is the *protocol*; each item's id
and SHA-256 is appended to the ledger below as it is generated, by

```
python speedrun/eval/holdout/freeze.py --append-item --set H2
```

**Contents.** New exam-style Held-out items generated from the corpus,
span-gated by the Generation gate, each mapped to one Topic.

**Rules fixed in advance:**

1. **Never derived from the student's own cards.** An item traceable to a card
   is not a Held-out item; that is what H4 is for
   ([ADR-0004](../../docs/adr/0004-performance-and-the-paraphrase-test-use-separate-sets.md)).
2. **Append before showing.** An item's id and hash must be in the ledger
   *before* the item is shown to the student. An Attempt on an item absent from
   the ledger does not count toward Performance.
3. **Never hinted, explained, or coached on** before its Attempt. Item text never
   enters the Collection, a generation prompt, or coaching material — this is
   what the leakage check tests for.
4. **Append-only.** Item content is never edited after it is appended. A needed
   correction becomes a **new id**; the old row's `status` changes from `live` to
   `retired:<reason>` and the row itself stays. Retired items are excluded from
   every score.
5. `freeze.py --close-set H2` fixes the file-level hash once the last item is in.

**Item schema.** Content fields covered by the item hash:
`id`, `topic`, `stem`, `options`, `answer`, `source_id`, `source_span`.
Anything else in the record (generation metadata, gate log references) is not
hashed and may be added later.

<!-- H2-LEDGER:BEGIN -->
| item_id | sha256 | appended_at (UTC) | status |
|---|---|---|---|
<!-- H2-LEDGER:END -->

*(Empty at freeze — as it should be. Rows are appended by `freeze.py`.)*

---

## H3 — AI card gold set

**Contents.** 50 question/answer pairs drawn by hand from **one real source**,
authored before any card generation runs, and used only as the reference the
generated cards are scored against. Gold text never enters a generation prompt
or coaching material — a gold set fed to the generator is Leakage, and the
leakage check flags H3 items exactly as it flags H2 items.

**Source — PENDING.** The exact source (book, edition, chapter range) and its
SHA-256 are recorded here when the corpus for the demo section lands (T-07). One
source only, so the check measures generation and not source variety.

**Item schema.** Content fields covered by the item hash:
`id`, `question`, `answer`, `source_id`, `source_span`.

### The cutoff rule — stated now, before any result exists

50 cards are generated from the same source and graded against H3 into the three
buckets from the test plan. Each generated card lands in exactly one bucket:

| bucket | definition |
|---|---|
| **correct and useful** | the answer matches the gold pair on the fact tested, and the card is a card a student would actually be served by reviewing: one fact, answerable from the prompt, no give-away wording. |
| **wrong** | the answer contradicts the gold pair, or states something the source does not support. |
| **correct but bad teaching** | factually right, and still bad: two facts in one card, the answer inferable from the phrasing, trivia with no bearing on the Topic, or a near-duplicate of another card in the batch. |

**Pre-registered cutoff — the run passes only if all three hold:**

1. **correct and useful ≥ 70%** (≥ 35 of 50);
2. **wrong ≤ 10%** (≤ 5 of 50);
3. the gated arm's **wrong** rate is **strictly lower** than the ungated arm's
   wrong rate on the same source and the same 50 generation requests. If it is
   not, the Generation gate is theatre and the write-up says so in those words.

**Grading procedure, also fixed now:**

- The grader sees the generated card and the gold pair, and assigns one bucket.
  Cards are graded in a shuffled order, with gated and ungated cards mixed and
  their arm hidden, so the arm cannot bias the bucket.
- Bucket boundaries are not renegotiated during grading. A card the grader
  genuinely cannot place goes to **correct but bad teaching** — the conservative
  bucket, chosen now so the tie-break cannot be chosen later.
- The percentages are reported **whether or not they clear the cutoff**, with the
  denominator (50) printed beside them. Failing the cutoff is a result, not a
  reason to move the cutoff.

These three numbers are thresholds, not measurements. **Nothing has been measured
yet.**

<!-- H3-LEDGER:BEGIN -->
| item_id | sha256 | appended_at (UTC) | status |
|---|---|---|---|
<!-- H3-LEDGER:END -->

---

## H4 — the R-set (Reworded cards)

**Contents.** 30 of the student's own cards × 2 rewordings each = 60 Reworded
cards. Feeds the paraphrase test only and **never counts toward any score**.
Added once a real deck exists (T-03) and the student has studied it (T-11).

**Selection rule — fixed now, so the 30 cannot be picked to flatter a gap.**

1. Eligible: cards in the demo section that the Crosswalk maps to a Topic and
   that carry **≥ 3 graded reviews** at selection time. Unmapped cards are not
   eligible.
2. Sort eligible cards by card id ascending, then take a sample of **30** using
   `random.Random(seed).sample(...)` with **`seed = 20260802`** — recorded here,
   in advance, so the selection is reproducible and was not re-rolled.
3. Each selected card gets exactly **2** rewordings: the same fact, restated as
   an exam-style question, with no wording carried over from the card beyond
   unavoidable technical terms.
4. A rewording that changes the fact tested is a defect, not a rewording; it is
   replaced and the replacement recorded as a new id.
5. No Reworded card is shown to the student before the paraphrase test runs.

**Item schema.** Content fields covered by the item hash:
`id`, `card_id`, `rewording_index`, `prompt`, `answer`.

**Pre-registered comparison.** The paraphrase test reports three numbers with
ranges, on one student: recall on the card, accuracy on the R-set, accuracy on
the P-set. The target stated in advance is a **gap ≥ 15 points** between card
recall and P-set accuracy. The gap is reported whichever way it comes out, and
if the three numbers collapse into one, that is published as a finding — the
Performance model would be copying the Memory model.

<!-- H4-LEDGER:BEGIN -->
| item_id | sha256 | appended_at (UTC) | status |
|---|---|---|---|
<!-- H4-LEDGER:END -->

---

## What must never enter the public fork

| kept out | why |
|---|---|
| the `anki-revlogs-10k` corpus, in any form | its licence permits individual research use and **forbids public redistribution** |
| `h1_reviews.jsonl` | it is a derivative of that corpus — the same licence applies |
| any raw review data or collection file under `speedrun/eval/holdout/` | raw review history is the student's own study data and, for H1, licensed third-party data. Only hashes and derived numbers commit. |

The `.gitignore` entries that enforce this each carry the reason as a comment.
`freeze.py --verify` checks both directions: that nothing matching those patterns
is in the working tree, and that the ignore rules are still present in
`.gitignore` — a deleted ignore rule fails the check even when no file has
appeared yet.

**Scope of that check, stated honestly:** it inspects the working tree, not git
history. The git-tracked assertion belongs to the leakage check (T-20), which
also flags near-copies of H2/H3 items in generation prompts, corpus chunks and
coaching material.

---

## Amendments

Append-only. Every change to this manifest after the freeze timestamp gets a row
here — what changed, when, and why. An empty section is the strongest state this
section can be in.

| when (UTC) | what changed | why |
|---|---|---|
| 2026-08-02 | H1: the `PENDING` corpus-revision block filled in with the pinned revision, the archive's SHA-256, the sampling rule and the per-collection hash file. | The manifest said these were to be recorded at download time. T-05 downloaded the corpus. |
| 2026-08-02 | H1: the recorded distribution is `anki-revlogs-10k-raw`, not `anki-revlogs-10k`. | The processed distribution is gated and returns HTTP 401 without a Hugging Face token. The raw distribution is the same corpus from the same publisher under the same licence, ungated. Stated rather than silently substituted; the split rule itself is unchanged. |
| 2026-08-02 | H1: noted that `review_th` is not a field in the raw distribution and is computed as the rank under the total order step 2 already fixes. | The split rule was written against the processed distribution's column names. The order it describes is unchanged; only where the number comes from is. |
