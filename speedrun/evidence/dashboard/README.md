# T-13 · The dashboard on a real collection

`dashboard-miledown-crosswalk.png` is the Speedrun dashboard, in Anki, reading
MileDown's MCAT Deck through the Bio/Biochem Crosswalk. Every number on it came
back from `SpeedrunService`; the add-on formatted them and computed none of
them.

**Read this before the picture: it is a partial result.** Every score on that
screen abstains, and it has to, because the deck has never been reviewed. See
[What it does not show](#what-it-does-not-show-and-why).

## What it shows

| | |
|---|---|
| Collection | MileDown's MCAT Decks, imported from `speedrun/eval/deck/miledown.apkg` |
| Cards | 2,888 |
| Crosswalk | `speedrun/crosswalk/miledown-bb-v1.json`, installed verbatim into collection config under `speedrunCrosswalk` |
| Review log | **empty — 0 rows in `revlog`** |
| Add-on | linked into the profile with `speedrun/addon/install.py --base <throwaway>` |

The dashboard reported:

| | mapped | unmapped |
|---|---|---|
| Your collection | 1,098 | 1,790 |
| Chem/Phys | 0 | 1,790 |
| **Bio/Biochem** | **1,098** | **1,790** |
| Psych/Soc | 0 | 1,790 |
| CARS | 0 | 0 |

and, per Bio/Biochem content category:

| 1A | 1B | 1C | 1D | 2A | 2B | 2C | 3A | 3B | total |
|---|---|---|---|---|---|---|---|---|---|
| 123 | 107 | 62 | 232 | 62 | 19 | 54 | 129 | 310 | 1,098 |

### The counts match the crosswalk's own, independently

`speedrun/crosswalk/README.md` states 1,098 of 2,888 cards attributed (38%),
1,790 unmapped, across all nine Bio/Biochem categories. That figure was measured
when the crosswalk was built, by a separate pass over the deck. The dashboard's
figures come from `speedrun_topic_mastery` in `rslib`, resolving each card at
read time. **They agree exactly** — 1,098 mapped, 1,790 unmapped, 1,098 + 1,790
= 2,888, nine categories, all nine non-empty. No expectation was adjusted to
make that true.

CARS reports 0 unmapped rather than 1,790 because the backend returns before
reading any card: the AAMC states there is no content knowledge to model there,
so there is nothing for a card to be unmapped *from*.

### The unmapped count is the first thing in every panel

1,790 of 2,888 is 62% of the deck. A reader who saw "Bio/Biochem" and a number,
with the denominator in a footer, would have read a figure about 38% of their
collection as a figure about their collection. So both counts are printed above
the scores, in every section and in the collection panel, at a size that cannot
be skimmed past — and repeated in the evidence row underneath, which lists
everything each score was and was not taken over.

`Topics with cards` in the collection panel says nine. It says *cards*, not
history: the backend returns a topic as soon as a card is attributed to it, and
every row in the per-topic table beside it reads `0` reviews and `not covered`.
Running against real data is what surfaced that label; it used to say "with
history", which the table directly under it contradicted.

### Abstention is the result, not an error

Twelve scores, twelve abstentions, each naming its own shortfall in the
backend's own words — `Only 0 graded reviews in BB. Need 200.`,
`Only 0 unhinted questions answered in BB. Need 20, across at least 3 topics.`,
`No readiness for BB until memory is available: …`. Each sits in the same box,
at the same weight and in the same position an available score would occupy.
Nothing on the page is an error state and nothing is empty.

## What it does not show, and why

**It does not show a Memory score.** Not for Bio/Biochem, not for anything.

The MileDown `.apkg` ships with a **completely empty review log** — zero rows in
`revlog`, zero cards with FSRS memory state. Memory is computed from review
history and nothing else, so with no history there is no numerator, and the
give-up rule in `rslib/src/speedrun/thresholds.rs` withholds the score and says
by how much. Coverage is 0% for the same reason: a topic with cards but no
graded history is not covered, because owning cards about something is not the
same as having studied it.

The three acceptance criteria on the ticket therefore stand as:

| Criterion | State |
|---|---|
| Unmapped count shown alongside | **done** — this screenshot |
| Other sections abstain naming their exact shortfall | **done** — this screenshot, though *all* sections abstain, not two |
| Demo section shows a real Memory score with a range | **blocked on #10 (T-11)** |

Only a human studying the deck can produce the reviews the last one needs. They
were not manufactured here: no review was synthesised, no revlog row written, no
card given a memory state, and no score fabricated. A Memory score that rose out
of invented reviews is precisely the failure this project exists to expose, and
it would have been trivially easy to produce. When #10 supplies real reviews,
this page is re-run unchanged and Bio/Biochem reports a real number while
Chem/Phys and Psych/Soc keep abstaining — the shot the ticket is really after.

## How it was produced

Nothing in the repo was modified to take this picture, and the add-on rendered
exactly what it renders for a user.

1. A throwaway `ANKI_BASE` outside the repo, seeded with one profile.
2. `col.import_anki_package(...)` on `speedrun/eval/deck/miledown.apkg`
   (238 MB, gitignored, not committed and not moved).
3. `col.set_config("speedrunCrosswalk", json.load(open(...)))` — the crosswalk
   file passed through whole. Its extra top-level keys (`error_rate`, `notes`,
   the provenance fields) are ignored by the Rust parser, so the artifact that
   is reviewed is byte-for-byte the artifact that is installed.
4. `python speedrun/addon/install.py --base <throwaway>`.
5. Anki launched on that base; **Tools → Speedrun Dashboard** opened; the page
   captured by scrolling the web view and stitching the tiles, because a window
   manager clamps a window to the screen and the page is 2,376px tall. The
   narrow strips on the right edge are the window's own scrollbar, caught at two
   tile boundaries.

The numbers were also read straight off the backend, without the renderer in the
way, and they are the same numbers.
