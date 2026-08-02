# Deck acquisition and tag-granularity check (T-03)

**Verdict: use MileDown. 29 of the 31 AAMC content categories resolve from
`(deck path, tags)`.** The two that do not are 9A and 9B, which the deck fuses
into a single tag. This number is derived from the actual `.apkg` file, not from
a description of it.

## 1. What was obtained

| | |
|---|---|
| Deck | MileDown's MCAT Anki Deck |
| File | `speedrun/eval/deck/miledown.apkg` (**not committed** — see §8) |
| Size | 238,374,412 bytes |
| SHA-256 | `7bee1879210a529e8f2002b65e8f892c6690a9824704c4f1474f8f753b7b58e4` |
| Origin | Google Drive mirror (file id `1neyVXp_prnmVManHHCB6lZOOL6xEykPE`), the copy linked from the deck's public distribution pages |
| Read how | `zipfile` + `sqlite3` from the Python stdlib. Anki was never installed and the deck was never imported into a profile. |

AnkiWeb's own download endpoint (`/svc/shared/download-deck/<id>`) now rejects
unattended requests — it returns `400 missing field 't'`, a bot-check token the
SPA supplies. The Drive mirror was used instead. The file is a legacy-format
`.apkg`: a zip holding one `collection.anki2` (SQLite schema 11) plus 2,553
numbered media blobs.

**Caveat worth flagging: `revlog` is empty.** This is a pristine shared deck with
zero review history, as every freshly downloaded shared deck is. It is a valid
*Crosswalk* input, but it is not on its own a *Collection* in the CONTEXT.md
sense — anything that computes Memory needs a collection that has actually been
studied.

## 2. The structure actually observed

**2,885 notes / 2,888 cards. One notetype. Seven subdecks. 182 tags. Every
single card carries at least one tag (0 untagged).**

Notetype: `Cloze-MileDown-b279e`, cloze, fields `Text` / `Extra`, one template.

Deck tree:

```
MileDown's MCAT Decks
├── Behavioral            828
├── Biology               604
├── Biochemistry          515
├── Physics and Math      313
├── Organic Chemistry     287
├── General Chemistry     250
└── Essential Equations    91
```

Seven subject subdecks is exactly the coarse organisation ADR 0005 warned about —
seven buckets cannot express 31 categories. **The tags are what rescue the deck.**
They are a three-to-four-level hierarchy under a `MileDown::` root, e.g.

```
MileDown::Biochemistry::Metabolism::Citric_Acid_Cycle    28 cards
MileDown::OChem::Spectroscopy::NMR                       16 cards
MileDown::Behavioral::Social::Social_Stratification      24 cards
MileDown::Physics::Electrostatics::Equations             24 cards
```

The full 182-tag list with per-tag card counts, all 219 observed
`(deck path, tag)` pairs, and the deck tree are in `deck_labels.json` beside this
file.

**The deck path is nearly worthless as a key; the tag carries all the signal.**
26 of the 182 tags appear under two or more subdecks — `MileDown::Biology::Genetics`
turns up under *Biology*, *Biochemistry* and *Behavioral*;
`MileDown::General_Chemistry::Acids_and_Bases::pH_and_pKa` under four subdecks.
In every such case the tag describes the content correctly and the subdeck is
the accident. ADR 0002/0005 keep the compound `(deck path, tags)` key, which is
right in general, but for this deck the crosswalk should let the **tag dominate**
and use the deck path only as a tiebreak on the handful of tags too generic to
stand alone.

## 3. How the count was made

Rule applied, per the ticket: a category is resolvable only if at least one label
maps to it **and not to a sibling category**. Operationally, and stated so it can
be argued with:

> A label *resolves* category X if ≥80% of the cards carrying that label belong
> to X, and no other single category takes a systematic block of ≥15% of them.
> A category is *resolvable* if at least one label resolves it.

Card text was read for every contested label rather than inferred from the tag
name — the tag `Behavioral::Social::Social_Structure` reads like a clean 9A and
turns out not to be.

## 4. The number

**29 of 31.**

| Section | Resolvable | Unresolvable |
|---|---|---|
| Bio/Biochem | 9 / 9 | — |
| Chem/Phys | 10 / 10 | — |
| Psych/Soc | 10 / 12 | 9A, 9B |

Per-category, with the label that carries it and the card count a draft
crosswalk attributes to it:

| Cat | Resolving label(s) | Cards |
|---|---|---|
| 1A | `Biochemistry::Amino_Acids`, `::Proteins`, `::Enzymes*` | 133 |
| 1B | `Biochemistry::DNA_and_RNA*` | 111 |
| 1C | `Biology::Genetics`, `::Evolution`, `Reproduction::Meiosis` | 69 |
| 1D | `Biochemistry::Metabolism*`, `::Lipid_Metabolism`, `::Carbohydrates` | 235 |
| 2A | `Biochemistry::Cell_Membrane`, `Biology::Parts_of_Cell`, `::Cytoskeleton`, `::Tissues` | 62 |
| 2B | `Biology::Viruses_and_Bacteria` | 23 |
| 2C | `Biology::Development`, `Reproduction::Mitosis`, `Biochemistry::Biosignaling` | 78 |
| 3A | `Biology::Nervous_System*`, `Biology::Endocrine` | 134 |
| 3B | `Biology::Cardiovascular_System`, `::Respiratory_System*`, `::Immune_System*`, `::Digestion*`, `::Kidney`, `::Muscular_System*`, `::Skin` | 309 |
| 4A | `Physics::Kinematics*`, `::Dynamics`, `::Energy`, `::Work`, `::Mechanics*` | 60 |
| 4B | `Physics::Fluids*` | 35 |
| 4C | `Physics::Circuits`, `::Electrostatics*`, `::Magnetism`, `General_Chemistry::Electrochemistry`, `::REDOX` | 111 |
| 4D | `Physics::Light*`, `::Sound`, `::Waves*`, `OChem::Spectroscopy*` | 113 |
| 4E | `Physics::Nuclear_Phenomena`, `General_Chemistry::Atomic_Structure*`, `::Periodic_Table*` | 76 |
| 5A | `General_Chemistry::Acids_and_Bases*`, `::Solutions*` | 101 |
| 5B | `General_Chemistry::Bonding`, `::Intermolecular_Forces`, `OChem::Bonding` | 51 |
| 5C | `OChem::Separations`, `Biochemistry::Lab_Techniques` | 42 |
| 5D | `OChem::Alcohols`, `::Aldehydes_and_Ketones`, `::Carboxylic_Acids*`, `::Reactions`, `::Isomers`, `Biochemistry::Lipids` | 224 |
| 5E | `General_Chemistry::Thermochemistry*`, `::Chemical_Kinetics*`, `::Equilibrium`, `Physics::Thermodynamics` | 82 |
| 6A | `Behavioral::Sensation_and_Perception*` | 128 |
| 6B | `Behavioral::Attention`, `::Cognition*`, `::Consciousness*`, `::Memory`, `::Language`, `::Intelligence` | 184 |
| 6C | `Behavioral::Emotion`, `::Emotions`, `::Stress` | 25 |
| 7A | `Behavioral::Personality`, `::Disorders`, `::Motivation`, `::Biology_and_Behavior*` | 197 |
| 7B | `Behavioral::Social::Socialization` | 43 |
| 7C | `Behavioral::Learning`, `::Attitudes` | 30 |
| 8A | `Behavioral::Identity` | 12 |
| 8B | `Behavioral::Social::Social_Perception` | 30 |
| 8C | `Behavioral::Social::Social_Interaction` | 45 |
| **9A** | **none** | **0** |
| **9B** | **none** | **0** |
| 10A | `Behavioral::Social::Social_Stratification` | 24 |

Draft-crosswalk totals: 2,646 of 2,888 cards attributed, **242 Unmapped
(8.4%)**, 113 cards landing in more than one category. The mapping above is a
sketch made to produce this count — the real Crosswalk is a later ticket and
should be built and error-rated on its own terms.

## 5. Worked example — resolvable

**5C, Separation and purification methods.** The tag
`MileDown::OChem::Separations` carries 26 cards. Their content is extraction,
distillation, chromatography, recrystallisation. No other of the 31 categories
claims separations: 5D is functional-group reactivity, 5B is bonding, 1A's
"analytical methods" is protein-specific and lives under
`Biochemistry::Lab_Techniques`. One label, one category, ~100% clean. 5C
resolves.

The same shape holds for the whole science half: `Biology::Viruses_and_Bacteria`
→ 2B and nothing else; `Physics::Nuclear_Phenomena` → 4E and nothing else.

## 6. Worked example — unresolvable

**9A (Understanding social structure) and 9B (Demographic characteristics and
processes).** The only candidate label is
`MileDown::Behavioral::Social::Social_Structure`, 61 cards. Reading all 61:

- ~36 are 9A — functionalism, conflict theory, symbolic interactionism, social
  constructionism, rational choice, feminist theory; social institutions
  (education, religion, government, economy, medicine); culture, norms, rituals,
  material vs. symbolic culture.
- ~19 are 9B — *Demographics*, *Fertility rate*, *Birth and mortality rate*,
  *Migration*, *Demographic transition*, *Social movements*, *Globalization*,
  *Urbanization*, *Fecundity*, *Baby boomers*, *Age stratification*, *Life course
  theory*, *Pluralistic society*, *Gender role / non-binary / agender / gender
  fluid*, *Racial formation theory*, *Gender schema theory*.
- ~6 are 10A — bourgeoisie, proletariat, patriarchy, objectification, ghetto,
  intersectional theory.

That is 59% / 31% / 10%. There is no sub-tag, no second tag, and no subdeck
that separates the 9B block from the 9A block — both sit under the *Behavioral*
subdeck (and, for a few, *Physics and Math*, which is simply wrong and further
evidence the deck path is not a usable key). A crosswalk rule
`Social_Structure → 9A` would be wrong for a third of its cards and would report
9B as fully uncovered while silently inflating 9A.

Per ADR 0005 these 60 cards are **Unmapped**, and both 9A and 9B are recorded as
unresolvable. Coverage for Psych/Soc is therefore reported over 10 categories
with 2 named as un-measurable, not over 12.

## 7. Labels that resolve to nothing

242 cards carry no resolving label. They cluster:

| Cards | Label | Why |
|---|---|---|
| 60 | `Behavioral::Social::Social_Structure` | fused 9A/9B/10A — §6 |
| 32 | `Behavioral::Development` | splits across 8A identity formation and 7A lifespan development |
| 32 + 28 | `Physics::Research`, `Physics::Research::Data` | research design and statistics — a *Scientific Inquiry and Reasoning Skill*, not one of the 31 content categories at all |
| 31 | `Behavioral::Social::Social_Behavior` | splits 7B (animal social behaviour, mating, foraging) / 8C (attraction, attachment, altruism) |
| 20 | `Behavioral::Behavior` | catch-all — cognitive dissonance (7C), compliance (7B), aggression (8C), paradox of choice (6B) |
| 35 | `Physics::Mathematics::*` | arithmetic and trig skills — no content category |
| 8 + 5 | `General_Chemistry::Constants`, `All_MCAT_Equations` | bare constants and cross-cutting formulas |

The equation tags are mostly *not* a problem: 88 of the 93
`All_MCAT_Equations` cards also carry a specific topic tag
(`Physics::Electrostatics::Equations`, `General_Chemistry::Thermochemistry::Equations`, …)
and resolve through it. Only 5 are bare.

## 8. Recommendation

**Take MileDown.** The gate was "MileDown if roughly 15 or more categories
resolve, otherwise AnKing". 29 resolve — nearly double the threshold, and the
two failures are a named, bounded, honestly-reportable pair rather than diffuse
mush. Paying the AnkiHub signup cost for AnKing would buy at most 2 more
categories and would trade a freely-mirrored file for a gated one.

The deck's tag hierarchy is finer than ADR 0005 assumed. That ADR's premise —
"a deck organised by subject subdeck carries no topic tags at all" — is true of
MileDown's *subdecks* and false of its *tags*. The ADR's conclusion still stands;
its worry did not materialise. The consequence for the Crosswalk ticket is that
the compound key should be tag-first with deck path as tiebreak, because 26 tags
straddle subdecks and the tag is right every time.

## 9. Files and `.gitignore`

Created by this ticket:

- `speedrun/eval/deck/miledown.apkg` — the deck. **Must not be committed.**
- `speedrun/eval/deck/deck_labels.json` — every deck path and tag with card
  counts, plus all 219 `(deck path, tag)` pairs. Input to the Crosswalk ticket.
- `speedrun/eval/deck/DECK_REPORT.md` — this file.

`.gitignore` entries needed (this ticket does not own `.gitignore`; the
orchestrator must add them):

```gitignore
# Student decks — never redistributed, never in the public fork
speedrun/eval/deck/*.apkg
speedrun/eval/deck/*.anki2
speedrun/eval/deck/*.colpkg
```

`deck_labels.json` and this report contain only label names and counts — no card
text, no media — and are safe to commit.
