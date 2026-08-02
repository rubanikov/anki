# Agent service

Grounded item generation, with attribution built into the structure rather than
into anyone's discipline.

A **held-out item** may be shown only if the supporting text for its correct
answer was retrieved from a real source and matched against it. That is the
**Generation gate**, and this service is the gate plus the smallest amount of
machinery needed to run one either side of it. The generator behind the gate is
replaceable; the gate is not.

---

## What runs

```
POST /item/generate?topic_id=1D&seed=0   → 200 {item, source_id, span, citation}
                                         → 409 {item: null, rejected: {reason, detail}}
GET  /health                             → what the add-on probes
GET  /gate/yield                         → Yield, decomposed by rejection reason
GET  /gate/rejections?limit=50           → the dropped attempts themselves

POST /coach/start?topic_id=1D&seed=0     → 200 a cold question, with no answer in it
                                         → 409 the gate dropped it; no fallback question
POST /coach/turn                         → 200 the next step, or 409 naming what it wants
GET  /coach/speak-rate                   → the share of prompts spoken into
POST /coach/transcribe                   → speech to text, when a key exists
```

```bash
cd speedrun/agent
uv sync                       # the gate, the graph, the stub — no provider SDK
uv sync --extra openai        # add the real generator (or --extra anthropic)
uv run speedrun-agent                    # 127.0.0.1:8000
uv run speedrun-agent --attempt 1D --seed 0   # one attempt, printed, no server
uv run pytest                 # 71 tests; the two needing a key skip without one
```

Provider SDKs are **extras** rather than dependencies: the gate is the graded
part, and it must install and run on a machine that has neither key nor SDK.

The corpus must be built first — `python speedrun/corpus/build.py --build` — and
`/health` reports what it found.

**This environment is separate on purpose.** LangGraph's dependency tree does
not belong inside Anki's bundled Python, and the phone could never run it.
Nothing under `speedrun/addon/` imports anything from here; see *Degradation*
below.

---

## The graph

```
                                    ┌──────────────┐
  START ──▶ retrieve ──▶ generate ──▶│     gate     │──▶ ship ──▶ END
              │            │        └──────┬───────┘      │
              └────────────┴───────────────┴──────────────┴──▶ drop ──▶ END
```

Four things about this shape are load-bearing.

**Generation sits between retrieval and the gate.** There is no path from a
proposal to the wire that does not pass the assertion.

**The gate is its own node.** A generator cannot skip a step it does not own.

**Every node's output is a `Carried` — `{output, source_id, span}`.** The trail
is the graph's only writable output channel and its reducer refuses anything
else, so a node's output and its provenance move together or they do not move.
There is no field to forget, because there is no other field.

**`source_id` and `span` may be `None`, and that matters.** A generated claim
genuinely has no citation; stamping the retrieved chunk's id onto it is exactly
how an invented answer would acquire one. So the `generate` node emits an
*unsourced* record, it travels as one, and `attribution.payload` — the single
function that turns a record into JSON — returns `None` for it. **An output that
reaches the boundary without a source is dropped, not displayed.** That is one
function, not a convention.

`Carried` also refuses to be half-attributed: a source without a span, or a span
citing a different page, raises at construction. The shape that would satisfy a
naive "does it have a `source_id`?" check while carrying nothing re-verifiable
is not constructible.

### The gate

`gate.rule` asks one question of the retrieved characters:

> Is the supporting text for this item's correct answer present in what
> retrieval actually returned?

It calls `corpus/spans.py`, which returns a span or `None` — never a nearest
match, because a nearest match is how an unsupported claim acquires a citation.
The span is then re-verified against the page it claims to come from, and the
quote in the response is **the source's own characters**, copied out of the
page, never the generator's string. Matching forgives whitespace, case and
typography and nothing else: a paraphrase has not *found* supporting text, it
has *written* some.

**No model is ever asked whether an item is correct.** The fake-organ result
settles why: a generator and a checker drawn from the same weights share a blind
spot, so the model that will invent an answer will also certify it — and the
pair reads as two independent confirmations while being one. An LLM
"is this correct?" step here would not add a check; it would delete the only one
there is. The gate is mechanical, and it is allowed to err in exactly one
direction: it drops items whose support is real but paraphrased. That is the
cheap error. Shipping an item whose answer is in no source is the expensive one,
and it cannot make it.

### Rejections

Every attempt is recorded — shipped ones too, because a rate needs a
denominator — with exactly one reason from a closed set:

| Reason | What it means |
| --- | --- |
| `no_retrieval` | Retrieval returned nothing. The corpus, not the generator. |
| `generator_empty` | The generator declined to propose. |
| `malformed_item` | No stem, no answer, or fewer than two distractors. |
| `answer_leaks_into_stem` | The stem contains its own answer verbatim. |
| `answer_not_in_retrieved_text` | **The gate's own rejection.** |
| `span_failed_reverification` | A span was found but did not survive re-checking. |
| `unattributed_output` | Something reached the boundary with no source. |

The set is closed because a free-text reason cannot be counted and a reason
invented at a call site is a category nobody agreed to. ADR-0006 needs the
decomposition, not the total: a retriever that fetches the wrong page and a
generator that invents an answer both show up as lower Yield and are not the
same problem.

`/gate/yield` reports `yield_per_hundred: null` before any attempt rather than
`0`. A rate over an empty denominator is an abstention.

---

## Numbers from real runs

ADR-0006's query set, run once per generator: BM25 over the built OpenStax
corpus, all nine Bio/Biochem categories at three requests each.

| Generator | Model | Attempts | Shipped | **Yield /100** |
| --- | --- | ---: | ---: | ---: |
| `gpt-5`, given the retrieved text | `gpt-5-2025-08-07` | 27 | 27 | **100.0** |
| `stub-remembered`, never reads the retrieved text | — | 27 | 16 | **59.3** |

Rejection decomposition:

| Reason | gpt-5 | stub |
| --- | ---: | ---: |
| `answer_not_in_retrieved_text` | **0** | 11 |
| every other reason | 0 | 0 |

**gpt-5 handed the sources cleared the gate on every attempt.** That is the
result; it was not tuned for. It is worth saying plainly what it does and does
not show.

It does **not** show the gate is pointless. It shows the gate is *easy to
satisfy when the generator is given the source*, which is the expected outcome
and the reason ADR-0006 has an ungated control arm at all. The number that
carries the project's claim is not the margin between retrievers — it is how
often an ungated pipeline would ship an item whose answer is in no real source.
The stub is the stand-in for exactly that condition (a generator answering from
memory rather than from the passage), and **11 of its 27 attempts — 41% — would
have shipped ungrounded with the gate switched off.** The stub is not a model,
so that is a bound on the failure mode's shape, not a measurement of any model's
ungrounded rate. Measuring the real thing means running a model *without* the
passages, which is #16's arm to run, not this ticket's.

Three caveats a reader of the 100.0 should have:

- **The three requests per category are not three different requests.** `seed`
  selects among the stub's canned claims; it is not passed to the model, so
  gpt-5 saw an identical prompt three times per topic and often returned the
  same answer. The 27 attempts contain **20 distinct citations**, all of which
  shipped — so 20/20 rather than 27/27, and the figure does not move. Making the
  three requests genuinely distinct belongs to #16, which owns the arms.
- **The gate checks grounding, not item quality.** Two of the 27 "answers" are
  whole sentences lifted verbatim from the page (`2B` seed 0, `3B` seed 1) —
  perfectly grounded and useless as multiple-choice answers. Nothing here claims
  otherwise; item quality against a cutoff is T-18's number.
- **One run, one retriever.** These are BM25 figures. Varying the retriever with
  the gate held constant is the comparison, and it is #16's.

Per topic, the stub: `1B` and `2B` shipped 3/3; `1A`, `1D`, `2A`, `2C`, `3A`
shipped 2/3; `1C` and `3B` shipped 0/3. `1A` being thin in the book (31 chunks)
did not hurt it; `3B` is the widest category and the stub's phrasing for it is
not the book's.

A small thing the gate got right on the real run: gpt-5 answered `1A` with
*"the enzyme's active site"* using a straight apostrophe; OpenStax writes it
with a curly one. The span matched — typography is folded before matching — and
the quote returned is **the page's characters**, curly apostrophe included, not
the model's.

A grounded claim and an ungrounded one, same topic, same generator:

```
$ uv run speedrun-agent --attempt 1D --seed 0
HTTP 200
  answer   "citric acid cycle"
  quote    "citric acid cycle"          ← the source's characters
  citation 58e9e038…[1350:1367] https://openstax.org/books/biology/pages/7-key-terms#fs-id1864534

$ uv run speedrun-agent --attempt 1D --seed 2
HTTP 409
  item     null
  reason   answer_not_in_retrieved_text
  detail   no span supporting 'the peroxisome of prokaryotic cells' in 8 retrieved chunks (…)
```

The second claim is false. The gate did not notice that, and does not try to —
it noticed that no real source says it, which is the only thing it can check
honestly and the only thing that has to be true before an item is shown.

### The query set, and a finding about it

ADR-0006 fixes the query set before the first run: the 31 content categories.
The first implementation used each category's Outline **title** as the query and
yielded almost nothing — AAMC titles are abstract ("Principles of bioenergetics
and fuel molecule metabolism") while the book is concrete ("citric acid cycle",
"pyruvate"), so BM25 retrieved the chapter's throat-clearing and the gate then
dropped items that were perfectly groundable. The query is now the title plus
the category's itemised topic list: still AAMC's own words, from the same file,
still fixed before the run. It is recorded here rather than quietly fixed
because it is a property of the query set that #16 will measure.

---

## Tracing

**LangSmith if a key exists; otherwise a local JSONL tracer emitting the same
record shape.** No `LANGSMITH_API_KEY` was available, so every run so far has
gone to `out/trace.jsonl` in LangSmith's own run shape — `id`, `trace_id`,
`parent_run_id`, `name`, `run_type`, `start_time`, `end_time`, `inputs`,
`outputs`, `error`, `extra`. Matching the shape is the point: when a key
appears, `LangSmithTracer` takes over, nothing that reads traces learns a second
format, and the local runs can be posted after the fact rather than thrown away.

What is traced is the attribution triple. Each node's span carries the
`{output, source_id, span}` it produced, so a trace is not "the graph ran" — it
is a re-checkable record of which characters in which page licensed the item
that shipped. `generate`'s entry carries `source_id: null`, which is the record
the boundary acts on. Rejections are traced with their reason.

`LangSmithTracer` is wired and **untested** — it has never posted a run.

---

## Degradation

The desktop app must start, score **Memory** and show **coverage** with this
service dead. That is a claim about a dependency that must not exist, so it is
asserted structurally rather than by turning the service off once:

- `tests/test_degradation.py` reads every file under `speedrun/addon/` and fails
  if any of them names `speedrun_agent`, `langgraph`, `fastapi`, `anthropic` or
  `langsmith`. No import, no dependency; the two never share an interpreter.
- It loads the add-on's `switches.py` on its own — it is stdlib-only, which is
  itself part of the proof — and runs the degraded path: an unreachable service
  yields `ai_enabled = false`, a probe that raises still yields a decision, and
  `Switches` exposes nothing a measurement could be routed through.

Memory and coverage come from the Rust engine, which never consults this
service. Killing this process removes generation and the coach loop and nothing
else.

---

## Keys

A key is read from the process environment. If it is not there, **one `.env`
outside the repository** may be consulted — `SPEEDRUN_AGENT_ENV_FILE` if set,
otherwise a short list of conventional locations. The value goes into
`os.environ` and nowhere else: not a config file, not a trace, not a rejection
record, not an artifact. `/health` reports a provider *name* and a boolean.

**A `.env` inside the repository is refused with an exception.** That check is
in code rather than in this README because the failure is silent and permanent —
a key committed once is leaked forever — and because somebody will eventually
copy the file in "just to test". Refusing loudly is what stops that copy from
appearing to work.

`tests/test_environment.py` covers all of it without a key or a network: the
in-repo refusal, the configurable path, an exported key outranking the file, the
allowlist that stops a shared dotfile setting arbitrary variables here, and a
scan of `speedrun/` for key-shaped strings (plus, when a key is present, for
that exact value).

## Which generator runs

Whichever key exists decides; with none, the stub runs and the service still
works. That fallback is load-bearing — the gate is the graded part and has to be
demonstrable, and testable, on a machine with no key at all.

| Key present | Generator | Status |
| --- | --- | --- |
| `OPENAI_API_KEY` | `OpenAIGenerator` (`gpt-5`) | **Run.** 27 attempts, numbers above. |
| `ANTHROPIC_API_KEY` | `AnthropicGenerator` (`claude-opus-5`) | Wired, **never issued a request**. |
| neither | `RememberedAnswerGenerator` | The stub. |

Both real generators are handed the retrieved passages and prompted for an
answer copied verbatim from them, with the **same prompt** — a per-provider
prompt would turn a retrieval finding into a prompt-engineering one. Reasoning
effort is left at the provider default, because a knob turned here is a knob
that has to be reported next to the Yield number, and an unturned one cannot be
accused of having been adjusted until the number looked good.

Every item records the provider's **resolved** model id — `gpt-5-2025-08-07`,
not `gpt-5` — on the candidate, in the trace, in the ledger and in the HTTP
response. An alias moves; a Yield figure attributed to one is not repeatable.

## What is stubbed

`RememberedAnswerGenerator` is the stub, and its shape is the interesting part.
A stub that lifted a phrase straight out of the retrieved chunk would pass the
gate every time and prove nothing. **It stays deliberately unlike the real
generators: it never reads the retrieved text.** That is what keeps a
key-less suite able to prove the gate can fire at all, and it is the stand-in
for the condition ADR-0006's ungated control measures — a generator answering
from memory rather than from the passage in front of it. Whether a claim ships
is decided by the corpus and the gate, not by whoever wrote the table. The
claims are hand-written stand-ins for model output, not vetted MCAT content, and
one is deliberately false.

`FixedClaimGenerator` puts one caller-supplied claim through the pipeline. It
ships in the package rather than living in a test file because ADR-0006's
ungated control arm needs the same capability.

The coach loop's session store is **in memory**, not a LangGraph checkpointer.
A restart loses any session in flight. That is stated rather than hidden: the
graded property is the step order *within* a session, and losing one loses a
teaching loop, not a score.

Not built here: the retrieval arms and the yield table are T-17's, and read
`/gate/yield`.

---

## The coach loop

Four of PRD §4.2's seven steps plus the rule statement. Revision (5) and the
personal guide (7) are cut.

| Step | What it is | Graded |
| --- | --- | --- |
| 1 | A held-out item, asked cold — no hint, no explanation | **yes, and only this** |
| 2 | Confidence, stated **before** the answer is revealed | no |
| 3 | "Explain what this question is actually testing" | no |
| 4 | The contrast pair — one detail changed | no |
| 6 | The rule, in the source's own words | no |

**The server owns the order, and that is the whole design.** Confidence given
after the answer is not a weaker measurement, it is not a measurement — it is a
memory of having been right. So the correct answer is not in any response body
until the confidence for that item is on the record. There is no flag, no query
parameter and no debug route that changes it: `Session.reveal` is the only thing
that can produce an answer, and it returns `None` until `confidence` is set.
`/coach/turn` refuses out-of-order turns with 409 and names what it wants.

That claim is asserted against the raw bytes rather than against a field. The
test walks the loop and requires that the answer *string* appears nowhere in
what a client received before step 2 — because "the reveal field is null" is
satisfied by an implementation that also leaks it somewhere else. **It caught
one:** the first draft returned the graded record as soon as the answer arrived,
which put `correct: true` on the confidence screen.

**The contrast pair changes exactly one detail, checkably.** A fixed table of
paired opposites (`prokaryotic`/`eukaryotic`, `reactant`/`product`, …) is
matched against the stem at word boundaries; the pair records the offset and the
text that was there, so the original stem can be *reconstructed* from the
contrast stem — if a second character had moved, that round trip fails. When no
pair applies, the changed detail is which option is correct, and the weaker form
is labelled `answer_swap` rather than disguised, so a reader can count how often
it was used.

**The rule is a quotation, not a composition.** It is the span the gate already
re-verified, widened to its surrounding sentence by slicing the page — the
source's own characters throughout. Asking a model to phrase a rule would put an
unchecked sentence at the end of a loop whose point is that nothing unchecked is
shown. One wrinkle, found by running it: OpenStax key-terms pages are *term*,
blank line, *definition*, so the first widening stopped on the term and said
nothing. The window now extends through the following block when the result is
under 80 characters.

**Speak-rate** is the pre-registered ablation measure: prompts spoken into over
prompts issued, logged to `out/utterances.jsonl` and reported at
`/coach/speak-rate`, with `null` rather than `0.0` over an empty denominator —
the same abstention `/gate/yield` makes.

### Speech to text

`gpt-4o-transcribe` when `OPENAI_API_KEY` exists, and **nothing** when it does
not. Transcription is an addition to the loop rather than a step in it: no step
waits on it, no score reads it, and a provider outage downgrades to
`transcribed: false` with a readable reason.

That ordering is deliberate. The tempting repair for "transcription is down" is
a text box "just for now", and a text box beside a live question is the one
thing this feature exists to forbid. The degraded state is therefore **audio
recorded, not transcribed** — speak-rate keeps its numerator and the loop still
runs.

Run end to end on 2026-08-02, with Windows SAPI standing in for a student:

```
$ POST /coach/transcribe  (289,702 bytes of WAV)
{"transcribed": true,
 "transcript": "This question is testing whether substrate-level phosphorylation
                is different from oxidative phosphorylation.",
 "model": "gpt-4o-transcribe"}
```

One bug worth recording, because reading the code would not have found it: the
provider infers the container from the **filename**, not from the bytes, and the
first run posted WAV under the recorder's default `.webm` name and came back
*"Audio file might be corrupted"*. The extension now follows the recorder's own
MIME type.

---

## Testing

Every assertion is against an HTTP status code and a JSON body. Nothing imports
a node, calls one, or knows how many there are — SPEC §Seam 2 is explicit that
node-level tests would freeze the graph's current shape while proving nothing
about the only place the rule matters.

The test that carries the ticket holds the generator constant and swaps the
corpus:

- `SUPPORTING` states the answer in the corpus's own words → 200, with a span.
- `SILENT` is the same page with that sentence replaced by prose about the same
  topic → **409, `item: null`, `answer_not_in_retrieved_text`**, and the
  rejection is on the record with the chunks that *were* retrieved (so the test
  cannot pass on a service that merely failed to retrieve).

`test_unsourced_output_never_crosses_the_boundary` sabotages the gate into
approving an item with no source, over a corpus that *does* support the claim,
and asserts the service ships nothing anyway.

71 tests. Two need a key and skip cleanly without one.

---

## Files

| | |
| --- | --- |
| `attribution.py` | `Carried`, the reducer, and `payload` — the boundary |
| `gate.py` | The assertion, and the closed set of rulings |
| `graph.py` | retrieve → generate → gate → ship/drop |
| `generators.py` | The stub, the fixed-claim control, and the OpenAI / Anthropic paths |
| `environment.py` | Key lookup, and the refusal to read one from inside the repo |
| `corpus_gateway.py` | The one place that knows where `speedrun/corpus/` is |
| `rejections.py` | The ledger Yield is computed from |
| `tracing.py` | LangSmith, or the same shape locally |
| `topics.py` | The fixed query set, taken from the Outline |
| `coach.py` | The loop's step order, the contrast pair, the rule, speak-rate |
| `coach_voice.py` | Speech to text, and the honest absence of it |
| `app.py` | The HTTP boundary |

## Not committed

`out/` holds the rejection ledger and the trace log — local runtime evidence,
regenerated by running the service. `.venv/` is this service's own environment.
Both need `.gitignore` entries; `uv.lock` **is** committed, because a
reproducible environment is the point of having a separate one.
