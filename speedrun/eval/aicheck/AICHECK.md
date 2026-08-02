# AI card check against H3 — the result, whichever way it came out

**The run fails the pre-registered cutoff, on two of its three conditions.**

The cutoff was written into
[`speedrun/eval/holdout/MANIFEST.md`](../holdout/MANIFEST.md) on 2026-08-02 at
08:12:41Z, before H3 existed and before a single card had been generated. It has
not been touched since, and this file was written after the numbers were in.

| the frozen condition | required | measured | |
|---|---|---|---|
| 1. correct and useful | ≥ 70% (≥ 35/50) | **52% (26/50)** | **FAIL** |
| 2. wrong | ≤ 10% (≤ 5/50) | **0% (0/50)** | PASS |
| 3. gated wrong < ungated wrong | strictly lower | **0% vs 0%** | **FAIL** |

Condition 3 has a consequence the manifest fixed in advance, in these words:
**the Generation gate is theatre and the write-up says so in those words.** So:
in this configuration the Generation gate is theatre. §4 is about exactly what
that does and does not mean, because "theatre" is a strong word and the reason
it applies here is specific and, in one direction, encouraging.

---

## 1. The three buckets

Denominator 50 throughout — the number of generation requests, not the number of
cards that came back. Three requests produced no card in each arm; dividing by 47
would quietly reward an arm for declining.

| arm | correct and useful | wrong | correct but bad teaching | no card |
|---|---|---|---|---|
| **gated** (the service, gate on) | **26 — 52%** | **0 — 0%** | **21 — 42%** | 3 — 6% |
| **ungated** (identical, gate off) | 31 — 62% | 0 — 0% | 16 — 32% | 3 — 6% |

Both arms answered the same 50 requests, over the same source, with the same
prompt and the same model (`gpt-5-2025-08-07`). The three requests that produced
nothing were **the same three in both arms** — `h3-1D-04`, `h3-1D-05`,
`h3-2B-02` — where BM25 returned passages that do not cover the target concept
and the model set `skip: true` rather than asking about whatever it had been
handed. That is the generator behaving correctly on a retrieval gap.

The ungated arm scoring *higher* on "correct and useful" than the gated arm is
not a finding about the gate. Both arms ship the same proposals here (§4); the
10-point difference is two independent samples from one non-deterministic model,
on 50 draws, and nothing in this run distinguishes it from noise.

**Item-level results:** [`out/buckets.jsonl`](out/buckets.jsonl) — one row per
card with its bucket, the rule that assigned it, and the grader's reason.

---

## 2. How the grading was done, and what it is worth

**This is model-assisted grading with a hand-checked sample. It is not human
grading throughout.** Every "52%" and "0%" above comes from a pipeline in which
a language model placed most of the cards. Read §2.3 before quoting any of them.

### 2.1 The three layers

Asking `gpt-5` — which drafted every card here — whether its own card is correct
is banned, by this ticket and by [`speedrun/agent/gate.py`](../../agent/speedrun_agent/gate.py)'s
own reasoning: a generator and a checker drawn from the same weights share a
blind spot, and the pair reads as two confirmations while being one. So:

| layer | what decides | model involved |
|---|---|---|
| **1. mechanical, against the source** | is the answer present verbatim (whitespace- and typography-folded) anywhere in the indexed book? **Not found → `wrong`.** | none |
| **2. blind model grade** | one card, its gold pair, and the passages it was drafted from, judged by **`o4-mini`** — not the `gpt-5` that wrote it — under a prompt that shares no wording with the generation prompt | yes |
| **3. mechanical teaching defects** | two options that are the same string; the answer inside the stem; an answer longer than eight words; a near-duplicate of another card in the same batch | none |

Precedence, fixed before any bucket was computed: layer 1 beats everything;
layer 2's `wrong` beats layer 3; layer 3 beats layer 2's `correct and useful`. A
card the grader cannot place, or whose response does not parse, goes to
**correct but bad teaching** — the conservative bucket the manifest chose in
advance for this exact case.

**Blinding.** The 94 cards were shuffled together under seed `20260802`, the arm
was never shown, and the grader saw an opaque `card-NNN` token rather than an id
that would have spelled the arm out.

### 2.2 The agreement rate

Two hand reads, both written **before** the automated buckets they are compared
with. The hand buckets were never revised afterwards.

| | cards | agreement |
|---|---|---|
| [`handcheck.json`](handcheck.json) — first sample, 15 per arm | 30 | **80%** (24/30) |
| [`handcheck_holdout.json`](handcheck_holdout.json) — held out, 8 per arm | 16 | **75%** (12/16) |

**Quote the 75%, not the 80%.** The grading prompt was revised once (§2.4) after
the first hand-check disagreed with the first automated pass, so an agreement
rate on those same 30 cards is fitted to them. The 16 held-out cards played no
part in that revision.

**The disagreements are almost all in one direction.** Of the 10 cards where the
hand read and the automated bucket differ, **9 are the grader calling a card
useful that a person put in bad teaching**, and 1 is the reverse. The grader is
lenient about teaching defects, so **52% is an upper estimate of the gated arm's
correct-and-useful rate, not a point estimate.**

On the 46 cards graded by hand, the two methods give:

| | correct and useful, by hand | by the pipeline |
|---|---|---|
| gated (n=23) | 26% | 52% |
| ungated (n=23) | 48% | 57% |
| both (n=46) | **37%** | 54% |

Condition 1 fails under either grading method, and by a wider margin under the
hand read. That is the one thing about this result that does not depend on the
grader.

**Both hand reads found zero wrong cards**, agreeing with layers 1 and 2. On top
of that, all 94 cards were read end to end by the same person specifically for
factual error, because "0% wrong" is the safety-relevant number and it is the
one that should not rest on a model. No card was found whose answer contradicts
the source or is false biology. The one that looked wrong on sight —
`pyruvate kinase kinase`, in `g19` — is stated in exactly those words in
OpenStax §7.7 ("phosphorylation by a kinase (pyruvate kinase kinase), resulting
in a less-active enzyme").

### 2.3 What the agreement rate does not cover

- **The human end moved between sittings.** The first hand read put 14 of 30
  cards in "useful"; the second put 3 of 16. Same person, same bucket
  definitions, two sittings, with the defect list from
  [`pset/QUALITY.md`](../pset/QUALITY.md) more firmly in mind by the second. The
  first read was not revised to match — re-reading it after seeing the automated
  buckets would have been worse — but a 75% agreement rate against a rater who
  moved that much is a soft number.
- **One vendor.** The generator is OpenAI's and so is the grader; the only key
  on the machine is an OpenAI one. `o4-mini` is a different model family from
  `gpt-5` and got a different prompt, which is real separation, but it is not the
  independent second opinion a different vendor would give.
- **46 of 94 cards were read by hand.** The other 48 carry a model's bucket and
  a 75% agreement rate, and nothing stronger.

### 2.4 Two corrections, both recorded rather than quietly applied

**The first grading pass was discarded, and it is the most interesting number in
this file.** Under the first prompt, `o4-mini` agreed with the hand read on
**13 of 30 cards — 43%** — and produced these buckets: gated 86% useful / 2%
wrong, ungated 66% useful / **24% wrong**. That would have **passed all three
conditions of the frozen cutoff.** It was wrong for two reasons, both prompt
defects rather than hard cases:

- it saw only ±700 characters around the cited phrase, and called cards `wrong`
  for facts that are simply stated elsewhere in a 350-page book — a truncated
  excerpt doing the work of a source. Every one of the 13 `wrong` verdicts said
  some version of "the passage does not mention". That artefact fell almost
  entirely on the ungated arm, purely because its citations point at the top
  retrieved chunk rather than at the sentence containing the answer — which is
  to say **the first pass "confirmed" the gate by measuring where the citations
  pointed.**
- it returned `correct_and_useful` 84 times out of 94, giving "plausible
  distractors" as its reason for cards whose distractors were two names for one
  thing.

The second prompt shows the passages the card was drafted from, says in so many
words that silence is not contradiction, and makes the grader enumerate six
specific defects before it picks a bucket. Pass 1 is kept at
[`out/grades_v1.jsonl`](out/grades_v1.jsonl) and
[`out/buckets_v1.jsonl`](out/buckets_v1.jsonl) rather than deleted, because a
blind LLM judge that reports a **PASS** on one prompt and a **FAIL** on another,
over identical cards, is evidence about LLM judges that should not be thrown
away.

**A mechanical rule was also wrong first.** Layer 3 originally flagged an option
list where one option contains another as a substring. It fired on 13 sets and
every one was a minimal pair — competitive / noncompetitive inhibition,
sympathetic / parasympathetic, thyroid / parathyroid, unipolar / pseudounipolar,
hypothalamus / thalamus. Those are the *best* distractors an item can have. The
rule now fires only on exact equality, which matches nothing in this batch; real
synonym pairs are left to the blind grader, which found 14 of them.

---

## 3. The failure modes

The prior from [`pset/QUALITY.md`](../pset/QUALITY.md) — a hand read of 28
earlier items found 18 usable, with the failures being give-away stems and
option lists naming the same thing twice — **reproduced almost exactly.** Of the
37 cards the grader put in "correct but bad teaching", the defects it cited were:

| defect | count |
|---|---|
| **a.** two options name the same thing, or one is a synonym or a superset of the answer | 14 |
| **d.** options are not the same kind of thing, or are implausible on sight | 12 |
| **b.** the question contains the answer, its definition, or a synonym of it | 7 |
| **c.** the question names one of the options, or rules one out by its wording | 7 |
| **e.** the answer is a prose fragment rather than a term | 1 |
| **f.** two facts in one card, or trivia | 1 |

Worked examples, all from the hand read:

- **`u05` / `g05`** — "Name the rule that defines DNA base pairing specificity…"
  offers both *complementary base-pairing rule* and *the base complementary
  rule*. Two options, one rule, two correct answers.
- **`g17`** — "a reaction with a negative ΔG that gives off energy" offers both
  *exergonic reaction* and *spontaneous reaction*, and the source's own sentence
  says exergonic reactions "are also referred to as spontaneous reactions".
- **`u31`** — offers *Eukarya* and *eukaryotes* as two of four options.
- **`g26` / `u26`** — offers *actin filaments* and *microfilaments*.
- **`u42`** — "Which glands lie on the posterior surface of the thyroid gland and
  produce **parathyroid hormone**?" Answer: parathyroid glands.
- **`g00`** — "…buried in the interior of a soluble protein due to their
  **hydrophobic** side chains?" Answer: nonpolar amino acids.
- **`u25`** — "…rather than the **RER**, which modifies proteins?" and *RER* is
  one of the four options.

**The gate cannot see any of these.** It asserts that an answer's characters are
in a real page; it has no opinion about whether the other three options are the
same word twice. Every one of the 37 cards above passed the gate, and every one
of them is correctly grounded. That is the gate working exactly as specified and
it is not what makes a card usable.

---

## 4. Why the gate is theatre here, and where it is not

The measurement, stated plainly:

| | gated | ungated |
|---|---|---|
| requests | 50 | 50 |
| cards shipped | 47 | 47 |
| gate rejections (`answer_not_in_retrieved_text`) | **0** | n/a |
| **answer found verbatim in that card's own retrieved chunks** | **47 / 47** | **47 / 47** |
| answer found verbatim somewhere in the book | 47 / 47 | 47 / 47 |
| **wrong** | **0** | **0** |

The middle row is the paired measurement, and it is the whole explanation. It
applies the real gate's span matcher to the *ungated* arm's own proposals, at no
extra model call, so it is free of the sampling noise that separates two runs.
**The gate would have rejected nothing in either arm.** There were no ungrounded
answers for it to catch, so it could not lower a wrong rate that was already
zero. Under the manifest's rule that is theatre, and this file says so.

Three things that follow, and one that does not:

- **It follows that the gate bought nothing *in this configuration*.** The model
  is handed four retrieved passages and told, in the service's own prompt, that
  the answer "MUST be a phrase copied verbatim - character for character - from
  one of the passages". It obeyed 94 times out of 94. A filter downstream of a
  generator that never fails has nothing to filter. The P-set run already saw
  this (0 gate rejections in 28 items) and this is the pre-registered comparison
  confirming it rather than a new surprise.
- **It follows that "0% wrong" is not the gate's achievement.** It is the
  prompt's, and the retrieval's. Whatever is keeping ungrounded answers out of
  this pipeline, it is acting before the gate.
- **It follows that the ungated control is the arm carrying the real claim**, as
  [ADR-0006](../../docs/adr/0006-retrieval-is-judged-by-yield-at-a-fixed-gate.md)
  said it would be, and the claim it carries is that this pipeline ships
  ungrounded items **0% of the time even with the gate off**.
- **It does not follow that the gate is useless.** What this run measured is a
  gate over a generator that was shown the source. The failure the gate exists
  for is a generator answering from memory —
  [`RememberedAnswerGenerator`](../../agent/speedrun_agent/generators.py)
  reproduces exactly that, and the gate does fire on it. That is a different
  arm, it was not run here, and it is not what the frozen condition asked about.
  The honest summary is narrower than "the gate is useless" and wider than
  "inconclusive": **for a grounded generator handed its sources, the gate is
  insurance with a zero claim rate, and this run cannot tell insurance from
  theatre.**

### What "ungated" means here, exactly

The two arms differ in one thing. `generate.py` swaps the gate's ruling function
for one that ships every well-formed proposal, citing the top retrieved chunk
without checking that the answer is in it — which is what a pipeline without a
gate cites. Retrieval, prompt, model, seed plan and the *generate* node's own two
checks (malformed proposal, stem containing its own answer) are identical. Making
the ungated arm cite nothing at all would have been a strawman, and would have
made the wrong rate a measurement of citation formatting.

---

## 5. H3 — what it is, since it did not exist before this ticket

50 question/answer pairs, at [`../holdout/h3_gold.jsonl`](../holdout/h3_gold.jsonl),
ledgered item by item into `MANIFEST.md` by `freeze.py --append-item --set H3` as
each was produced. `freeze.py --verify` passes: 50 ledger items match the file.

**Source, recorded into the manifest's `PENDING` slot by this ticket:** OpenStax
*Biology*, 1st edition, content version `e989ec3`, CC BY 4.0, fetched from
archive `20260604.144757`; the operative hash is the indexed corpus,
`speedrun/corpus/out/index.sqlite3`, sha256 `8e55edfc…a291235`, because the
pairs' spans are byte offsets into pages inside that file. The pairs draw on 22
chapters and cite 44 distinct pages.

**Authorship, stated exactly.** The 50 pairs were written by hand against the
passages `plan.py --passages` returns for each target, one at a time, before any
card was generated. No model wrote any of them and no generation run had
happened. "By hand" here means an agent reading the source text and writing the
question and answer, not a domain expert: that is a weaker provenance than the
manifest's phrase "drawn by hand" might suggest to a reader, and it is what
happened.

**Nothing hand-written can be wrong about the source, mechanically.**
`build_gold.py` locates every gold answer inside the chunk the pair names using
the corpus's own `spans.find_span` — the same matcher the gate uses — and
re-verifies the resulting span against the full page. A pair whose answer cannot
be located aborts the build. All 50 resolved.

**The targets.** 50 `(topic, concept)` pairs from the AAMC Outline's own topic
lists, five per Bio/Biochem category plus one each to the five categories with
the most indexed chunks, concepts taken at evenly spaced positions through each
category's list. One target list serves all three jobs — the gold pair, the
gated request and the ungated request — which is what "the same source and the
same 50 generation requests" requires.

**A retrieval finding, reported because it changed the plan.** The P-set driver
queries BM25 with `"<concept> <Outline query>"`. Run over these 50 targets, that
returns the same top chunk again and again: **14 distinct chunks for 50
targets**, because the Outline query is dozens of a category's terms and
outweighs a three-word concept. The concept alone returns **49 distinct top
chunks out of 50**. This run queries with the concept alone.
`plan.py --distinctness` prints both numbers.

**Seven of the 50 gold pairs are marked `off_concept`.** For those targets BM25
returned passages that do not cover the Outline concept — "Digestion,
mobilization, and transport of fats" returns the electron transport chain — and
the pair asks about what those passages do say. Inventing a pair the source does
not support would have put a wrong answer into the reference everything else is
graded against. The flag is on the item, so a reader can see that a retrieval
gap is a retrieval gap and not a generation gap.

---

## 6. Limits, in one place

1. **Model-assisted grading, 75% held-out agreement with a hand read**, with the
   disagreements running 9-to-1 toward the model being more generous. 52% is an
   upper estimate; the hand read of 46 cards says 37% across both arms and 26%
   for the gated arm.
2. **One vendor for both the generator and the grader.** Different family,
   different prompt, blind to arm — but not a second opinion.
3. **The gate comparison is one configuration**, with a generator handed its
   sources and told to copy verbatim. A memory-answering generator was not run.
4. **50 requests per arm.** A 10-point difference between arms on n=50 is not a
   difference.
5. **The `wrong` bucket is empty**, which means condition 2 passed on a
   measurement with no positives in it. Zero out of 50 bounds the true rate
   loosely, not tightly.
6. **The hand grader's own standard drifted** between two sittings (47% useful,
   then 19%).
7. **Nothing here is about whether a student learns more.** These buckets are a
   reviewer's judgement of card quality. The paraphrase test (H4) is where a
   student's actual recall enters.

---

## 7. Reproducing it

```
speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/plan.py --plan
speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/plan.py --distinctness
speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/build_gold.py --check
speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/build_gold.py --build
speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/generate.py --arm gated
speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/generate.py --arm ungated
speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/grade.py --mechanical
speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/grade.py --sample 30
speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/grade.py --grade
speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/grade.py --report
```

Everything except `--plan`, `--distinctness`, `--check`, `--mechanical`,
`--sample` and `--report` needs `OPENAI_API_KEY`; the key is read from a `.env`
**outside** the repository, per
[`environment.py`](../../agent/speedrun_agent/environment.py), which refuses one
found inside it.

**Cost of this run:** 100 generation calls (50 per arm, run once each) and 188
grading calls (94 cards × 2 grader prompts, the first pass being the discarded
one in §2.4). `gpt-5-2025-08-07` for generation, `o4-mini` for grading.

**`.gitignore` — entries to add, reported not applied** (this ticket does not own
`.gitignore`). Nothing here is licensed or private; these are bulk derived
artifacts, matching how `speedrun/eval/pset/out/` and
`speedrun/eval/retrieval/out/` are already handled:

```
# --- Speedrun AI card check (T-18) — see speedrun/eval/aicheck/AICHECK.md ---
# LangSmith-style traces and per-attempt logs: ~1 MB each, regenerated by
# generate.py, and nothing in AICHECK.md cites them.
speedrun/eval/aicheck/out/*_trace.jsonl
speedrun/eval/aicheck/out/*_attempts.jsonl
# The assembled grading inputs: 688 KB, entirely derived from gated.jsonl,
# ungated.jsonl and the corpus by `grade.py --mechanical`.
speedrun/eval/aicheck/out/cards.json
```

The rest of `out/` should **commit**: `gated.jsonl`, `ungated.jsonl`,
`grades_v1.jsonl`, `grades_v2.jsonl`, `buckets.jsonl` and `buckets_v1.jsonl` are
33–86 KB each and are the evidence for every number above — including the
discarded first grading pass.
