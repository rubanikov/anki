# Would I put these in front of a student?

**46 of 60. Read by hand, item by item, after the run — not a score a checker
produced.**

`check_rewordings.py` passes all 60 on both of its thresholds. That is worth
something and it is not worth much: the mechanical check answers *did the model
copy the card's words*, and the answer is a clean no. It cannot answer the
question that decides whether a Reworded card is usable, which is whether a
student who never saw the card could answer it **only by knowing the fact**. So
this file is a hand read of every one of the 60, with the ones I would not show
named and the reason given.

Nothing here removes an item from the set. All 60 are ledgered, live, and would
be presented if the test ran — dropping items after seeing them is choosing a
set by looking at it, which is exactly what the freeze exists to stop. They are
named instead, so that anyone reading a paraphrase-test number can see which
part of the middle bar is soft.

## The run

| | |
|---|---|
| cards drawn | 30, by `MANIFEST.md`'s seeded rule (`random.Random(20260802).sample`) |
| model calls | 30 — one per card, each asked for both rewordings |
| retries for wording reuse | **0** — every first draft cleared both thresholds |
| model | `gpt-5-2025-08-07` (alias `gpt-5`, resolved id recorded on every item) |
| rewordings shipped | **60**, 2 per card, all ledgered as produced |
| rewordings I would show | **46** |

## What the mechanical check found

| | |
|---|---|
| longest run of words shared with the card | max **3**, mean 1.33 |
| items sharing a run of 3 | 2 — `h4-21-1` "a substrate analog", `h4-28-1` "from two different" |
| content-word Jaccard with the card | max **0.33**, mean 0.10 |
| prompts containing their own answer | 0 |
| the two rewordings of one card being near-copies | 0 |
| stated answer drifting from the card's | 0 flagged |

Both threshold values were fixed in `wording.py` before the run: shared run
`<= 3`, Jaccard `< 0.50`. Neither was moved afterwards. The two runs of three
are ordinary English ("a substrate analog", "from two different") rather than
the card's distinctive phrasing, which is what the threshold was set at three to
allow.

**So the defect the paraphrase test most needs to avoid — a reworded item that a
student can answer by recognising the card's string — does not appear in this
set.** That is the one strong claim this file makes.

## The 14 I would not show, and why

Three distinct defects, none of which the mechanical check can see.

### The stem describes its own answer (9 items)

The complaint `speedrun/eval/pset/QUALITY.md` makes about the P-set, in the same
words: a stem that contains its answer measures reading, not biology. The bar
used here is **the answer's distinctive morpheme appears in the stem in plain
language**, so that a student who knows nothing can assemble the answer out of
the question.

| item | answer | what is wrong with it |
|---|---|---|
| `h4-03-1` | Growth hormone-releasing hormone | The stem says "causes the adenohypophysis to increase secretion of growth hormone". "Growth hormone" plus "causes secretion" is the answer, spelled out. |
| `h4-03-2` | Growth hormone-releasing hormone | Same defect with the abbreviation: "activates somatotrophs to secrete GH". |
| `h4-05-1` | Transmembrane proteins | "Which integral membrane **proteins traverse** both leaflets…" — *traverse* + *membrane* is *transmembrane*, and *proteins* is handed over outright. |
| `h4-05-2` | Transmembrane proteins | "…passes completely through the lipid bilayer" — the same construction. |
| `h4-12-1` | isocitrate; NAD+; α-ketoglutarate; NADH; CO2 | The stem describes three of its five components: "five-carbon α-keto acid" is α-ketoglutarate, "reducing a pyridine nucleotide" is NADH, "decarboxylation" is the CO2. |
| `h4-12-2` | (same five) | Worse: "the resulting **α-keto acid**, **reduced carrier**, and **one-carbon gas** released" names three answers by description and asks for their names. |
| `h4-27-1` | malate; NAD+; oxaloacetate; NADH; H+ | "the four-carbon molecule that condenses with acetyl-CoA at the start of the next turn" is the definition of oxaloacetate; "electron-accepting coenzyme" is NAD+. |
| `h4-27-2` | (same five) | "a 4-carbon dicarboxylate with a secondary alcohol… oxidized to its 4-carbon keto form" describes both malate and oxaloacetate. |
| `h4-29-2` | Ribosomal RNA | "Which RNA class constitutes most of the **ribosome's** structural core?" The morpheme is right there. |

Held to the same bar and **accepted**: `h4-09-*` (voltage-gated ← "membrane
potential" — *voltage* never appears and *gated* has to be produced),
`h4-10-*` (passive transport ← "no ATP hydrolysis"), `h4-13-*` (motor proteins ←
"force and movement"), `h4-17-*` (totipotent ← "the entire organism plus
extraembryonic tissues"), `h4-19-*` (inversion ← "opposite orientation"),
`h4-21-*` (suicide inhibition ← "self-inactivation" — the closest of the calls I
let through), `h4-26-*` (cell differentiation). The line is thin and I have
drawn it in one place throughout rather than case by case.

### The answer space is narrowed to a coin-flip (3 items)

| item | answer | what is wrong with it |
|---|---|---|
| `h4-14-2` | adrenal medulla | "Loss of which **region of the adrenal gland**…" — the stem gives half the answer and the adrenal has two regions. 50% without knowing anything. |
| `h4-18-1` | direct | "…ionotropic receptors (**ligand-gated ion channels**) … with respect to second-messenger involvement" glosses the mechanism that *is* the answer, onto a two-value answer space. |
| `h4-18-2` | direct | "Relative to metabotropic receptors **that signal through G proteins**…" — the contrast supplies the answer to a two-value question. |

### The stem hands over the shape of the answer (2 items)

| item | answer | what is wrong with it |
|---|---|---|
| `h4-20-1` | honey, fruit, and sucrose | "Name the **two natural food sources and the single disaccharide**" tells the student the answer has exactly that shape, and there is only one disaccharide that yields fructose. Easier than the card, which asked an open question. |
| `h4-20-2` | honey, fruit, and sucrose | Same structural hint dressed in a hereditary-fructose-intolerance vignette. |

## Four defects that are in the *cards*, not the rewordings

These are not reasons to reject a rewording — the rewording is faithful — but
they are reasons to distrust the first of the three numbers, and they were not
fixable without re-rolling a seeded draw.

- **`1555192262825`** reads "[Thyroid hormone] is a precursor to [thyroid
  hormone]". Both blanks carry the hint "thyroid hormone", so the card as the
  student sees it barely poses a question. Its two rewordings (`h4-04-*`) are
  much harder than the card, which will read as a large card→reworded gap that
  is a card defect, not a memory-versus-performance finding.
- **`1556661931837`** and **`1556662098960`** are the same card template twice:
  a picture of a citric-acid-cycle reaction plus "This reaction requires […] and
  […] and produces […], […], and […]". Without the image the card is not
  answerable; with five blanks it is five facts, not one. All four of their
  rewordings are in the rejected list above, and this is why.
- **`1556905815915`**, "Fructose comes from […]" → "honey, fruit, and sucrose",
  is an open-ended list with no boundary the student can infer. Any rewording of
  it either leaves the boundary open (unanswerable) or states it (gives it
  away); the two here chose the second.
- **`1554559742290`** spells the answer "Shine-**Delgarno** sequence". The model
  copied the misspelling into both rewordings, which is correct behaviour — the
  R-set records the student's own answer — but a grader must accept
  "Shine-Dalgarno".

## Six items that are fine and still nearly free

`h4-01-*`, `h4-07-*` and `h4-22-*` come from cards whose answer is one of two
words ("reduces", "low", "voluntary"). The rewordings drop the card's explicit
"[reduces or increases]" choice, which is an improvement, but the answer space
is still about two. A student guessing scores ~50% on them. That inflates the
middle number, and the middle number is the one the thesis needs to sit *below*
card recall.

## The honest summary

The check that had to pass, passed: **no reworded item reuses the card's
wording, so nothing in this set turns the paraphrase test into a recognition
test.** The failure that remains is the same one the P-set has — nothing in this
pipeline asks whether a stem gives its own answer away, and 9 of 60 do. Every
one of the nine, plus the five others, pushes reworded accuracy **up**, which
narrows the card→reworded gap and makes the three numbers *more* likely to look
like one. If this test is ever run and the three numbers do collapse, this file
is the first place to look before concluding the Performance model is copying
the Memory model.
