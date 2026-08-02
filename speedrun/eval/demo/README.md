# Demo fixture — SYNTHETIC review history

> ## The review history in this profile was generated. It measures nothing.
>
> Every review in the demo collection was produced by `make_demo_history.py`
> from the fixed seed `20260802`. No human studied anything. The Memory score it
> puts on screen — **0.78, range 0.72 – 0.84** — is a number about a random
> number generator, and it is here **only** so a viewer can see what the
> dashboard looks like when a score exists rather than abstains.
>
> **No reported number anywhere in this project derives from this fixture.** It
> is not in `results.json`, not in `CALIBRATION.md`, not in the ablation, not in
> the parity evidence, and it never may be. The evidence that the Memory model
> works is [`speedrun/eval/calibration/`](../calibration/CALIBRATION.md), where a
> Memory score of 0.80 was measured right **79.2%** of the time on **2 334 451
> real reviews** held back from 300 real collections. That measurement exists,
> is untouched by this directory, and is the only thing that should ever be
> cited about the model.
>
> The collection carries the same warning in its own config
> (`speedrunSyntheticDemo`) and in every top-level deck description, and the
> dashboard refuses to render a page from such a profile without the banner
> across the top of it.

## Why this exists

The dashboard's argument is a contrast: one section that has cleared the give-up
rule reporting a Memory score with a range, beside sections that have not and go
on abstaining while naming exactly what they are short of. Until now that screen
could not be photographed. MileDown's `.apkg` ships with an **empty review log**,
so [`speedrun/evidence/dashboard/`](../../evidence/dashboard/README.md) shows all
twelve scores abstaining — correct, and only half the story.

Producing the other half honestly needs a person to study the deck for an hour.
There is no hour before the deadline. So the history is generated, and the whole
of this directory is the disclosure that makes that legitimate:

| | |
|---|---|
| **legitimate** | a labelled fixture that exercises the UI, so a viewer can see the shape of the product |
| **fraud** | the same data shown anywhere as evidence that the model works |

The difference is entirely the label, which is why the label is in the config
key, the deck descriptions, the generator's own output, this file, and — the one
that matters — on the screen, above every number, in a test.

## What it shows

`demo-dashboard.png` — the full page, and `demo-dashboard-scrolled.png` — the
live window scrolled down to the Bio/Biochem panel, which is the shot that shows
the banner is pinned to the viewport and cannot be scrolled away from.

| | |
|---|---|
| Collection | MileDown's MCAT Decks, imported from `speedrun/eval/deck/miledown.apkg` (read, never modified) |
| Cards / notes | 2,888 / 2,885 — unchanged, no note touched, no tag added |
| Crosswalk | `speedrun/crosswalk/miledown-bb-v1.json`, installed verbatim under `speedrunCrosswalk` |
| Mapped / unmapped | 1,098 / 1,790 — the deck's real figures, identical to the never-reviewed run |
| **Generated reviews** | **306 revlog rows across 132 cards, Bio/Biochem only** |
| Cards with FSRS memory state | 132 — computed by Anki from the generated revlog, not written by hand |
| Reviews in every other section | **0** |

and on screen:

| section | Memory | why |
|---|---|---|
| Your collection | — | denominators only |
| Chem/Phys | **Abstaining** — "Only 0 graded reviews in CP. Need 200." | never given history |
| **Bio/Biochem** | **0.78, range 0.72 – 0.84, Confidence: Low** | 306 generated reviews cleared the give-up rule |
| Psych/Soc | **Abstaining** — "Only 0 graded reviews in PS. Need 200." | never given history |
| CARS | **Abstaining** — the AAMC says there is no content knowledge to model | refused before any card is read |

Performance and Readiness abstain in **every** section including Bio/Biochem, and
that is not an accident of the fixture: no held-out item was answered, so
Performance has nothing to compute from, and Readiness waits on it. Nothing here
manufactures an attempt.

The generated per-topic figures, which are figures about the generator:

| topic | cards | reviewed | with memory state | reviews | Memory (SYNTHETIC) | range |
|---|---:|---:|---:|---:|---:|---|
| mcat::BB::1A | 123 | 15 | 15 | 37 | 0.76 | 0.69 – 0.83 |
| mcat::BB::1B | 107 | 13 | 13 | 36 | 0.75 | 0.67 – 0.84 |
| mcat::BB::1C | 62 | 7 | 7 | 10 | 0.73 | 0.64 – 0.82 |
| mcat::BB::1D | 232 | 28 | 28 | 68 | 0.77 | 0.72 – 0.82 |
| mcat::BB::2A | 62 | 7 | 7 | 20 | 0.86 | 0.77 – 0.95 |
| mcat::BB::2B | 19 | 4 | 4 | 12 | 0.85 | 0.74 – 0.95 |
| mcat::BB::2C | 54 | 6 | 6 | 18 | 0.81 | 0.69 – 0.92 |
| mcat::BB::3A | 129 | 15 | 15 | 29 | 0.78 | 0.73 – 0.84 |
| mcat::BB::3B | 310 | 37 | 37 | 76 | 0.79 | 0.76 – 0.82 |

Coverage reads 100% for Bio/Biochem because all nine content categories now have
graded history. On a real collection that would be a real 100%; here it means the
generator touched all nine, and nothing more.

## What it does **not** show

* **It is not evidence the Memory model is accurate.** It cannot be: the input
  is invented, so agreement between the score and anything would be circular.
  That question is answered, on real data, in `../calibration/`.
* **It is not evidence a student is ready.** There is no student.
* **It is not a benchmark.** Latency lives in `../bench/`, on its own synthetic
  deck with its own warning.
* **It is not a claim about the crosswalk.** The mapped/unmapped counts are the
  deck's own and were already measured without any of this — 1,098 and 1,790,
  the same as the never-reviewed run, because no note was modified.
* **The confidence label is "Low" and stays there.** 306 reviews is barely over
  the 200-review give-up rule. It was not padded up to the 400 that would print
  "Medium": a fixture tuned to look more assured than it is defeats the point.

## The banner

`speedrun/addon/render.py` reads the collection config key
`speedrunSyntheticDemo` (via `dashboard._demo_marker`) and, when it is present,
renders `render_demo_banner` as the **first element on the page, above the
title**, in red, `position: sticky` so it stays at the top of the viewport
however far the reader scrolls. It prints the seed, the generation time and the
generator path, so the fixture can be rebuilt rather than taken on trust.

The wording is fixed text in `render.py` — the config value supplies provenance
and cannot soften the warning.

Tested in `speedrun/addon/tests/test_demo_banner.py`:

* it appears when the key is set, and above the score, the range and the title
* it does **not** appear when the key is absent, and nothing else on the page
  changes
* the default is no banner, so it can never appear because a caller forgot an
  argument
* it names the real evidence, so "measures nothing" cannot be read as "nothing
  was ever measured"
* `render.DEMO_CONFIG_KEY == "speedrunSyntheticDemo"` — the one string tying the
  generator to the page

The read is deliberately from **collection config**, not add-on config: a warning
the viewer can switch off in a settings screen is not a warning.

## Reproducing

```bash
export PYTHONPATH=out/pylib
export SCRATCH=/some/throwaway/dir      # never a real ANKI_BASE, never a test's

python speedrun/eval/demo/make_demo_history.py \
    --base "$SCRATCH/ankibase-demo" --seed 20260802 \
    --stats-out speedrun/eval/demo/demo_stats.json
```

`--base` is required and has no default, so the generator cannot land in a real
profile by being run carelessly. It exits non-zero unless the fixture actually
worked: ≥ 200 graded reviews in Bio/Biochem, ≥ 30 cards given history, Memory
available, and **Chem/Phys and Psych/Soc still on zero reviews** — the contrast
is checked, not assumed.

Then photograph it, with the real app and the real add-on:

```bash
PYTHONPATH="pylib;out/pylib;qt;out/qt" out/pyenv/Scripts/python.exe \
    speedrun/eval/demo/shoot_dashboard.py \
    --base "$SCRATCH/ankibase-demo" \
    --shot speedrun/eval/demo/demo-dashboard.png \
    --shot-scrolled speedrun/eval/demo/demo-dashboard-scrolled.png \
    --out speedrun/eval/demo/shot.json
```

`shot.json` holds the page's own `innerText`, read back out of the webview, so
the words in the picture can be checked against the words the add-on rendered.

**What the seed fixes.** `random.Random(20260802)` fixes which cards are given
history, how many reviews each gets, every grade and every interval. It does not
fix absolute review timestamps, which are derived from wall-clock time, so
retrievability drifts slightly with when the fixture was built and two builds are
equivalent rather than byte-identical. Review counts, card counts and every
denominator reproduce exactly.

### How the fixture is built, and what it refuses to do

1. Import the real `.apkg` into a throwaway base. The deck file is opened
   read-only and never rewritten.
2. Install the shipped crosswalk into collection config, whole.
3. Write `speedrunSyntheticDemo` (seed, generation time, generator path,
   warning) and a `SYNTHETIC DEMO PROFILE` description onto the top-level decks.
4. Resolve which cards are Bio/Biochem using the same two rules as
   `rslib/src/speedrun/crosswalk.rs` — tags first, deck path only as a filter,
   first matching entry wins — then sample ~12% of each of the nine topics, with
   a floor of 4 cards, so every category has something in it.
5. Simulate each chosen card over a ten-week window: growing intervals, an 11%
   again-rate, 1–8 reviews. Insert the `revlog` rows and bring `reps`, `lapses`,
   `ivl` and `due` with them, because `mastery.rs` sums `card.reps` while FSRS
   reads `revlog`, and a fixture where those two disagree is a fixture that
   reports one thing and models another.
6. Reopen the collection and switch **FSRS on through
   `update_deck_configs`**, so Anki derives memory state from the generated
   revlog. `BoolKey::Fsrs` defaults to false and `mastery.rs` only accumulates
   retrievability for cards that have memory state, so without this step Memory
   abstains no matter how many reviews exist. `s`/`d` are never hand-written into
   the card `data` column: that would mean the number on screen came from this
   script rather than from the model.
7. Read the scores back through the same two backend calls the dashboard makes,
   and fail loudly if the fixture did not do what it claims.

**No note is modified. No tag is added. No held-out attempt is invented. Nothing
outside Bio/Biochem is given a single review.**

## Files

| file | what it is |
|---|---|
| `make_demo_history.py` | builds the fixture from the seed, and checks it |
| `shoot_dashboard.py` | launches real Anki on the demo base and photographs the dashboard |
| `demo_probe/` | throwaway add-on the driver loads to open the dialog and grab tiles; never shipped |
| `demo-dashboard.png` | the whole page, stitched from four tiles |
| `demo-dashboard-scrolled.png` | the live window at the Bio/Biochem panel, banner pinned |
| `demo_stats.json` | what the generator wrote and what the backend then reported — every score in it is labelled `SYNTHETIC` |
| `shot.json` | the capture report, including the page's own text |

## `.gitignore`

The generated profile lives in a throwaway `ANKI_BASE` outside the repo and
`--base` has no default, so nothing should land here. These are the guard for
when someone points it at the repo anyway:

```gitignore
# --- Speedrun demo fixture — see speedrun/eval/demo/README.md ---
# The demo profile holds SYNTHETIC review history over an imported 238 MB deck.
# It is rebuildable from the recorded seed and must never be committed — a
# collection file in the history is a fabricated review log someone can find
# without the label attached to it. Only the screenshots and the stats commit.
speedrun/eval/demo/*.anki2
speedrun/eval/demo/*.anki2-*
speedrun/eval/demo/*.colpkg
speedrun/eval/demo/*.apkg
speedrun/eval/demo/media*
speedrun/eval/demo/User */
```
