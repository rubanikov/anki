# Retrieval evaluation — Yield at a fixed gate

**T-17 · [#16](https://github.com/rubanikov/anki/issues/16) · design fixed by
[ADR-0006](../../docs/adr/0006-retrieval-is-judged-by-yield-at-a-fixed-gate.md)**

The requirement to beat keyword or vector search cannot be met by comparing this
pipeline against vector search, because this pipeline *is* retrieval plus a gate
— a system measured against its own component. So the gate is held constant and
only the retriever varies. The declared primary metric, fixed before the first
run, is **Yield: usable items per hundred generation attempts**.

Everything except the retriever is byte-identical across arms: the same query
set, the same target concept and question type per attempt, the same prompt
(`speedrun_agent.generators.PROMPT` plus one addendum used in every arm), the
same model at the same settings, the same eight-chunk retrieval budget with four
chunks shown, and the same unmodified `speedrun_agent.gate.rule`.

Raw numbers: [`results.json`](results.json). Per-attempt ledgers and traces are
written to `out/` and are not committed — they regenerate from the command at
the bottom of this file.

---

## The headline

> **In 54 gated attempts across three retrievers, the gate rejected nothing.**
> Run the same pipeline with the gate off and it ships 39 items, of which **0
> (0%, 95% CI 0–9.0%) have an answer whose supporting text is missing from the
> passages the model was shown**, and **0 have an answer that appears on no
> indexed page at all**.

That is the control arm's number and it is not the one that was hoped for. A
model that is handed the source passages and told to copy its answer verbatim
does copy verbatim, 39 times out of 39. For this generator, in this
configuration, an ungated pipeline would have shipped nothing ungrounded, and
the gate bought no measurable safety.

A gate that never fires and a gate that is not there produce the same table, so
a second control was run to tell them apart — the shipped
`RememberedAnswerGenerator`, which answers from a fixed table and never reads
the retrieved text, which is the failure mode the gate exists for. It costs no
API calls. **Ungated, it ships 81 of 81 attempts; 37 (45.7%) have an answer that
is in none of the retrieved passages, and 9 (11.1%, 95% CI 6.0–19.8%) have an
answer that appears nowhere in the corpus at all.** The gate is working. What
this sweep shows is that a retrieval-augmented generator under a verbatim
instruction rarely gives it anything to do.

Both numbers belong in the traceability table, with the generator each was
measured under stated next to it. Neither is a property of "the pipeline"
alone.

---

## The arms

| # | arm | retriever | gate |
|---|---|---|---|
| 1 | **BM25 → gate** | SQLite FTS5 `bm25()` over chunk text, exactly as `corpus/index.py` built it | on |
| 2 | **Embeddings → gate** | OpenAI `text-embedding-3-small`, 1,536 dims, cosine over the 1,651 attributed chunks | on |
| 3 | **Hybrid → gate** | Reciprocal Rank Fusion of arms 1 and 2, k=60, depth 20 per ranking | on |
| 4 | **Hybrid, gate OFF** — the control | as arm 3 | **off** |

Arm 4 costs no generation calls. The graph puts the generator's proposal on the
attribution trail whether or not the gate accepts it, so the control is arm 3's
own proposals read with the gate's ruling ignored. That makes it a *paired*
measurement on exactly the items the gated arm was judged on, which is stronger
than a separate run would have been.

"Gate off" means the span assertion is off. The generator-side checks that live
in the `generate` node — a proposal with no stem, or one containing its own
answer — are not the gate and stay on, because an ungated pipeline would still
have them.

**Nothing was tuned.** The embedding model runs at its native dimensionality,
the fusion uses RRF's published constant, and the fusion depth was written down
before the first run. Each arm was run once. No knob was turned after seeing a
number.

---

## The query set

**Nine categories, not 31.** ADR-0006 names the 31 AAMC content categories at
three requests each. This corpus is OpenStax *Biology* 1e and it indexes the
**nine Bio/Biochem categories only** — 350 pages, 3,021 chunks, 1,651 of them
attributed to a category. The other 22 categories have no chunks at all, and
running them would have produced 66 `no_retrieval` rows and a yield table that
looked like a retrieval finding while measuring the absence of a book. **This
comparison covers Bio/Biochem and says nothing about the other two sections.**

**Two requests per category, not three.** Three requests over three generating
arms is 81 model calls; this ticket's budget was 40–60. Two is 54. The cost of
that choice is 18 attempts per arm and confidence intervals wide enough that no
two arms separate — reported below rather than hidden.

**The two requests in a category are genuinely different requests.** An earlier
sweep in this project sent one prompt repeatedly and counted the copies; three
copies of one request is one request. Following the pattern
`speedrun/eval/pset/generate_pset.py` established, every attempt differs in
three ways at once:

- a **target concept** taken from AAMC's own itemised topic list for the
  category (`corpus/outline.json`), picked by a stated rule — keep the lines
  that read as concepts rather than headings, then take two at evenly spaced
  positions through the list, so two attempts land in two different corners of
  the category;
- the **retrieved passages**, because the concept is prepended to the shared
  query, so two attempts on one category read different pages;
- the **question type**, rotated through four fixed forms across the whole plan.

The concept and the question type are identical across arms for a given
attempt, so anything that moves between arms is retrieval and nothing else. The
full plan prints without calling a model: `run_arms.py --plan`.

The 18 queries, and how far apart the arms actually landed: **BM25 and the
embedding arm share only 3.0 of their 8 retrieved chunks on average** (range
1–5). These are not two names for the same ranking.

---

## Yield

Model: `gpt-5` → resolved `gpt-5-2025-08-07`, `max_output_tokens=8000`. 18
attempts per arm.

| arm | attempts | shipped | **Yield /100** | 95% CI | `generator_empty` | gate rejections |
|---|---|---|---|---|---|---|
| BM25 → gate | 18 | 11 | **61.1** | 38.6–79.7 | 7 | **0** |
| Embeddings → gate | 18 | 14 | **77.8** | 54.8–91.0 | 4 | **0** |
| Hybrid → gate | 18 | 14 | **77.8** | 54.8–91.0 | 4 | **0** |
| **Hybrid, gate OFF (control)** | 18 | 14 | **77.8** | 54.8–91.0 | 4 | n/a |

Every shipped item in every arm had a distinct answer; none of these yields is
inflated by repeats.

### The decomposition

The rejection decomposition is the reason ADR-0006 required one. It is also
almost empty:

- **`answer_not_in_retrieved_text`: 0 in all three arms.** The gate never fired.
- **`generator_empty`: 15 of the 15 rejections.** Every drop was the model
  setting `skip: true` — the addendum tells it to skip rather than ask about
  whatever the passages happen to support, and it did.
- `malformed_item`, `answer_leaks_into_stem`, `span_failed_reverification`,
  `no_retrieval`, `unattributed_output`: 0.

Under this addendum `generator_empty` is largely a *retrieval verdict* — the
model reporting that the retrieved passages do not cover the target concept —
which is why it is the channel the arms differ through. But part of it is a
floor no retriever can move: **3 of the 18 queries were skipped by all three
arms** (`Hybridization: viability`, `Epimers and anomers`, `Cell migration`),
concepts AAMC lists that OpenStax *Biology* does not cover. Excluding those
three, the arms ship 11/15, 14/15 and 14/15.

### Which arm won

**On this sweep, embeddings and hybrid tied at 77.8 and BM25 came third at
61.1 — and none of it is statistically distinguishable.** Paired sign tests over
the 18 queries:

| comparison | wins | p |
|---|---|---|
| BM25 vs embeddings | 1 – 4 | 0.375 |
| BM25 vs hybrid | 0 – 3 | 0.25 |
| embeddings vs hybrid | 1 – 1 | 1.0 |

The honest statement is that **no arm separated from any other**, and the point
estimate favours dense retrieval. BM25 did not win here; it also was not beaten
by a margin this query set can resolve.

### BM25 wins the clean version of the comparison

The gpt-5 arms confound retrieval with the model's willingness to draft: an arm
"loses" mostly by making the model skip. The remembered-answer control removes
that confound entirely, because the claim is byte-identical across arms and the
only question left is whether retrieval surfaced the page that supports it.
Three requests per category there (27 attempts per arm), because the stub's
third claim per category is where its deliberately false ones live.

| arm | attempts | shipped | **Yield /100** | 95% CI | `answer_not_in_retrieved_text` |
|---|---|---|---|---|---|
| stub + **BM25** | 27 | 16 | **59.3** | 40.7–75.5 | 11 |
| stub + embeddings | 27 | 14 | **51.9** | 34.0–69.3 | 13 |
| stub + hybrid | 27 | 14 | **51.9** | 34.0–69.3 | 13 |

**BM25 wins that one**, by 7.4 points — and again not significantly (BM25 vs
hybrid 2–0, p=0.5; BM25 vs embeddings 3–1, p=0.625). It is reported because it
is the finding, not tuned away. The direction of the comparison reverses with
the generator, which is worth more than either result on its own: with a model
drafting from the passages, dense retrieval fed it more usable pages; with a
fixed claim to ground, BM25 found the exact terms — proline, cystine, myelin
sheath — that textbook prose is dense with. This is BM25's home ground and it
shows.

---

## The control, in full

### With gpt-5 (ADR-0006's arm 4)

| | hybrid (arm 4) | pooled over all three retrievers |
|---|---|---|
| attempts | 18 | 54 |
| ungated ships | 14 (77.8/100) | 39 (72.2/100) |
| answer **not in the retrieved passages** | **0 (0.0%)** | **0 (0.0%)** |
| answer **absent from the whole corpus** | **0 (0.0%)** | **0 (0.0%)**, 95% CI 0–9.0% |

### With the remembered-answer generator

| | stub + hybrid | pooled over all three retrievers |
|---|---|---|
| attempts | 27 | 81 |
| ungated ships | 27 (100/100) | 81 (100/100) |
| answer **not in the retrieved passages** | 13 (48.1%) | **37 (45.7%)** |
| answer **absent from the whole corpus** | 3 (11.1%) | **9 (11.1%)**, 95% CI 6.0–19.8% |

The three distinct answers absent from all 350 indexed pages:

| category | answer | the question it was offered for |
|---|---|---|
| 1C | *hemimethylated replication* | "DNA replication in which each daughter molecule keeps one parent strand is described as what?" |
| 1D | *the peroxisome of prokaryotic cells* | "In prokaryotic cells, which organelle houses the Krebs cycle?" |
| 2C | *totipotent* | "A cell that can give rise to any cell type in the body is described as what?" |

The first two are false, and an ungated pipeline ships them. The third is
**true** — it is simply not stated in *Biology* 1e in those characters, which is
the check over-reporting, exactly as it is built to. Sorting those apart is a
judgement, so all three are printed here rather than folded into a rate.

The eleven answers the gate rejected that *are* elsewhere in the corpus —
*sister chromatids*, *alveoli*, *nephron*, *fluid mosaic*, *synapse* and the
rest — are retrieval misses, not fabrications. That distinction is the whole
reason the control reports two levels instead of one.

---

## What this comparison cannot show

- **It cannot show that the gate prevents harm at the rate this project would
  like to claim.** With a retrieval-augmented generator told to copy verbatim,
  the observed ungrounded rate was 0/39, and the upper end of its interval is
  9%. The 11.1% figure is measured under a generator built to fail; it is a
  demonstration that the gate fires, not an estimate of how often a real one
  would need it.
- **It cannot separate the arms.** Nothing here reaches significance. 18
  attempts per arm was a budget decision and it bought point estimates, not
  conclusions.
- **It covers Bio/Biochem only** — 9 of 31 categories, one textbook, one
  publisher, one prose style. BM25's advantage on exact technical terms is a
  property of textbook prose, and a corpus of lecture transcripts or clinical
  notes could reverse every row above.
- **The shared query is BM25's query.** `speedrun_agent.topics.query_for`
  concatenates the category title with AAMC's itemised topic list — 150–360
  words — because the title alone was a poor *BM25* query. That string was fixed
  before this ticket and shortening it for the dense arm would have made this a
  prompt-engineering finding rather than a retrieval one, so it was left alone.
  A dense retriever given a query built for dense retrieval might do better than
  it did here; this sweep cannot say by how much.
- **"Absent from the corpus" is not "false", and "present" is not "true".** The
  check asks whether the answer's characters appear on an indexed page, under
  the gate's own folding. A true claim in the book's own different words reads
  as absent (*totipotent*); a false claim built from words the book does use
  reads as present (the stub's *phosphodiester linkage*, offered as the bond
  between amino acids, is in the corpus — about DNA).
- **Yield counts items the gate accepts, not items a student could be given.**
  The addendum here deliberately does *not* add the P-set's "short, specific
  answer" constraint, because that constraint would raise or lower every arm's
  yield for reasons unrelated to retrieval. The consequence is visible in the
  output: median answer length is 3 words, but the longest shipped answer is a
  26-word clause lifted out of the prose. Item quality is
  [`speedrun/eval/pset`](../pset/QUALITY.md)'s measurement, not this one.
- **One run per arm.** ADR-0006's `seed` makes the plan reproducible, but the
  model is not deterministic; a re-run would move these numbers by some amount
  this sweep did not measure.

---

## Cost

| what | quantity | USD |
|---|---|---|
| generation, BM25 arm | 18 calls · 24,249 in / 33,655 out | 0.367 |
| generation, embedding arm | 18 calls · 22,859 in / 31,536 out | 0.344 |
| generation, hybrid arm | 18 calls · 22,580 in / 38,665 out | 0.415 |
| one end-to-end smoke test before the sweep | 1 call | 0.005 |
| chunk embeddings, built once | 1,651 chunks · 337,875 tokens | 0.007 |
| query embeddings | ~90 queries · ~400 tokens | <0.001 |
| the two remembered-answer controls | 81 + 54 attempts, no model | 0.000 |
| **total** | **55 generation calls** | **≈ 1.14** |

Rates used: `gpt-5` $1.25/Mtok in, $10.00/Mtok out; `text-embedding-3-small`
$0.02/Mtok. Token counts are recorded in `results.json` so the arithmetic is
re-checkable. Wall clock for the paid sweep: 333 s at 3 workers.

---

## Reproducing

```bash
# 1. the query set, without calling anything
speedrun/agent/.venv/Scripts/python speedrun/eval/retrieval/run_arms.py --plan

# 2. the chunk embedding cache (~340k tokens, once)
speedrun/agent/.venv/Scripts/python speedrun/eval/retrieval/retrievers.py --build-embeddings

# 3. the sweep: three gated arms, the ungated control, the stub controls
speedrun/agent/.venv/Scripts/python speedrun/eval/retrieval/run_arms.py --run

# 3b. re-derive only the free stub controls into an existing results.json
speedrun/agent/.venv/Scripts/python speedrun/eval/retrieval/run_arms.py --run --remembered-only
```

Requires a built corpus index (`speedrun/corpus/build.py --all`) and an
`OPENAI_API_KEY` reachable through `speedrun_agent.environment` — a `.env`
outside the repository, never inside it.

`out/` holds the embedding cache (13 MB), the per-arm rejection ledgers and the
traces. It is gitignored for the same reason `speedrun/agent/out/` is: a
committed copy would be a second source of truth for what the gate did.
`results.json` is the committed artifact.
