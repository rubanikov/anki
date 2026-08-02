# Would I put these in front of a student?

**18 of 28. Read by hand, item by item, after the run — not a score the gate
produced.**

The Generation gate proves an answer is **grounded**: the string is in a real
page and the citation re-verifies. It says nothing about whether the item is a
usable exam question, and the previous sweep is the proof — two of its 27
"answers" were whole sentences lifted out of the prose, perfectly cited and
useless. So this file is a hand read of every item, with the ones I would not
show named and the reason given. It is not the pre-registered cutoff: **that is
H3's, and H3 is a different set with a different rule.** Nothing here is compared
against a threshold, because no threshold for H2 was fixed in advance.

## The run

| | |
|---|---|
| generation calls | 36 (plus 2 while wiring the driver up) |
| items shipped by the gate | 28 |
| dropped | 9, all `generator_empty` — the model declined or its response did not complete |
| dropped by the gate itself (`answer_not_in_retrieved_text`) | **0** |
| suppressed as a duplicate of an item already in the set | 1 |
| items in the P-set | **28, across all 9 Bio/Biochem categories** |
| distinct citations | 28 of 28, from 18 distinct source pages |
| model | `gpt-5-2025-08-07` |

Zero gate rejections is the same finding the agent's README already records and
does not flatter anything: a model handed the passages and told to copy verbatim
usually copies verbatim. What the gate bought here is that all 28 answers are
byte-for-byte the source's own characters — checked, not asserted.

**The distinctness defect is fixed.** The previous sweep sent one prompt three
times per Topic and got 20 distinct citations from 27 attempts. Every attempt
here carried a different target concept, different retrieved passages and a
different question type: 28 items, 28 distinct prompts, 28 distinct citations,
and the one item that came back a near-copy of an earlier one was caught and
dropped rather than counted twice.

**The verbatim-sentence defect is fixed.** Answer length is 1–6 words, mean 2.2.
Not one answer is a sentence.

## The 18 I would show

`h2-1A-01` `h2-1A-03` `h2-1B-01` `h2-1B-03` `h2-1C-01` `h2-1C-02` `h2-1C-04`
`h2-1D-01` `h2-1D-03` `h2-2A-01` `h2-2A-02` `h2-2B-01` `h2-2B-03` `h2-2C-01`
`h2-2C-02` `h2-3A-01` `h2-3A-03` `h2-3B-01`

Several of these are easy — `h2-1C-04` (gametes) and `h2-2B-01` (Bacteria and
Archaea) are first-week recall — but easy is a difficulty problem, not a defect,
and an exam section contains easy questions. The ten below are different: each
has something wrong with the item itself.

## The 10 I would not, and why

| item | answer | what is wrong with it |
|---|---|---|
| `h2-1A-02` | denature | The stem asks for a *process* and the answer is a verb. "What process do high temperatures induce" / "denature" does not parse as a question and its answer. |
| `h2-1B-02` | initiation site for transcription | The stem says "in transcription initiation"; the answer says "initiation site for transcription". The stem hands over most of its own answer. |
| `h2-1C-03` | evolutionary (Darwinian) fitness | The stem ends "rather than simple fecundity", and `fecundity` is one of the four options. A stem that eliminates its own distractor is testing reading, not biology. |
| `h2-1D-02` | glycolysis | Two of the three distractors — "citric acid cycle" and "Krebs cycle" — are the same thing under two names. A student who knows that gets information from the option list. |
| `h2-2A-03` | packages lipids and proteins | Options are not the same kind of thing: two verb phrases, one noun phrase ("storage and transport compartments"). The grammar sorts them before the biology does. |
| `h2-2B-02` | clones | "…two daughter cells that are what, genetically?" is not how an item is worded, and the distractors (zygotes, spores, gametes) are cell types where the answer is a relationship. |
| `h2-2A-04` | Centrosome | The stem names "centrioles" and "centrioles" is one of the options. Also doubly-worded: "which structure is being described if it serves as…". |
| `h2-2C-03` | apoptosis | The stem contains "programmed cell death", which is the definition of the answer. Recall of a synonym, not of a concept. |
| `h2-3A-02` | neurons, muscle cells, and endocrine cells | The answer is a three-item list and the distractor lists are implausible on sight ("glial cells, adipocytes, and lymphocytes"). Guessable without knowing anything. |
| `h2-3B-02` | rib cage | Trivial, and dressed in a vignette that adds nothing ("a cardiothoracic resident notes that the heart is shielded by a curved, multi-bone structure"). The stem describes the rib cage and then asks which structure that is. |

## What that means for Performance

Nothing in this file removes an item from the set. All 28 are ledgered, live, and
eligible: the give-up rule counts **attempts on gated items**, and dropping the
ten now — after seeing them — would be choosing a set after looking at it, which
is the habit the freeze exists to prevent. They are named here instead, so that
anyone reading a Performance number can see that roughly **a third of the set has
a wording defect that makes it easier than the fact it is testing**. If
Performance comes out high, that is one of the reasons to distrust it.

The honest summary of the failure mode that remains: the gate stops ungrounded
answers, and the prompt now stops sentence-shaped ones, but **nothing in this
pipeline checks whether the stem gives the answer away**. That check is
mechanical enough to build — the service already drops an item whose stem
contains its answer verbatim, and the ten above are mostly near-misses of exactly
that rule — and it is not built here.
