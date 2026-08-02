# Crosswalk

The mapping from the labels a student's deck already uses to AAMC Outline
topics. Speedrun's own artifact, held apart from the collection, with a stated
error rate — never written into the student's notes.

| | |
|---|---|
| File | `miledown-bb-v1.json` |
| Covers | Bio/Biochem only (9 content categories, 1A–3B). Breadth beyond the demo section is cut #3. |
| Built from | MileDown's MCAT Deck, 2,888 cards, 182 tags — see `speedrun/eval/deck/DECK_REPORT.md` |
| Cards attributed | 1,098 of 2,888 (38%). The remaining 1,790 are Unmapped: 1,572 carry no label this file claims (almost all Chem/Phys and Psych/Soc), 218 hit an explicit refusal. |
| **Hand-checked error rate** | **6% (6 of 100), 95% CI 2.8%–12.5%** |

## How it is applied

In Rust, at read time, in `rslib/src/speedrun/crosswalk.rs`. The file is stored
in collection config under `speedrunCrosswalk` and consulted by
`speedrun_topic_mastery` before cards are grouped. Nothing writes a note, a
card, or a review — that is the Sensor rule, and it is why the mapping is a
config blob rather than a tagging pass.

- **Entries are consulted in the order written; the first match wins.** Order is
  the whole disambiguation mechanism, which is why it is data.
- **An entry matches a tag and everything beneath it.** One entry for
  `Biochemistry::DNA_and_RNA` covers its eight children.
- **`decks` narrows an entry; it never selects one.** ADR-0005 measured 26 tags
  straddling several subdecks, and in every case the tag described the content
  and the subdeck was the accident of where the author filed it. The one
  deck-restricted entry here exists because a single card tagged
  `Biology::Immune_System` sits in the Biochemistry subdeck and is about omega
  fatty acids.
- **`topic: null` is a refusal.** The label was read and found not to separate
  two categories. Its cards are counted in `cards_unmapped` and shown on screen.
  Filling one in to raise coverage is the failure this project exists to refuse.

## How the error rate was measured

1. Every card the crosswalk attributes to a Bio/Biochem category was enumerated
   — 1,098 of the deck's 2,888.
2. 100 were drawn at random (`random.seed(20260802)`).
3. Each card's **text** was read and judged against the AAMC Bio/Biochem
   outline. A card counts as an error if a different content category is the
   better home for it, including a category in another section.
4. Borderline calls were counted as errors, so the number is pessimistic.

Result: **6 errors in 100.** Every verdict is recorded in `error_sample.json`
by note id — the deck's card text is the author's and is never committed.

The six misses, with the category each card actually belongs to:

| Card | Assigned | Belongs to | Why |
|---|---|---|---|
| voltage-gated ion channel | 2C | 2A | Membrane transport, filed under the biosignaling label |
| Svedberg / sedimentation | 1B | 5C | A separation technique, filed under nucleic acids |
| diastereomers | 1D | 5D | General stereochemistry, filed under carbohydrates |
| endergonic vs exergonic | 1A | 1D | Bioenergetics, filed under enzymes |
| germ-layer origin of the GI tract | 3B | 2C | Embryogenesis, filed under digestion |
| adolescence and puberty | 2C | 7A | Psych/Soc lifespan development, filed under biology development |

Every one is a card the deck's author filed under a label that describes its
neighbours rather than itself. That is the error a label-based crosswalk makes,
and it is why the rate is reported beside mastery instead of absorbed into it:
the interval on a topic mean says nothing about whether the cards under it
belong there.

## What this rate is not

It is the rate at which *mapped* cards are mapped wrongly. It says nothing about
the 1,790 unmapped cards, which are reported separately as `cards_unmapped`, and
nothing about 9A and 9B, which no label in this deck can separate at all
(ADR-0005). A crosswalk that guessed at those would have a better-looking
coverage number and a worse error rate.
