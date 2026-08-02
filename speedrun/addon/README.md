# Speedrun add-on

The desktop surface. It shows three scores per section — Memory, Performance,
Readiness — with their ranges, the coverage of the AAMC Outline behind them, the
count of Unmapped cards under every figure, and, whenever a score has not
cleared its give-up rule, the abstention and the specific shortfall that would
resolve it.

**It computes none of that.** Every number, every range, every threshold
comparison and every abstention comes back from `SpeedrunService` in the Rust
backend, and this add-on formats it. That is not fastidiousness: the same
service runs on Android, offline, and the two are required to agree. A score
computed here would be a second implementation obliged to match the first
forever. The rule is strict enough to be checkable — `render.py` does not even
multiply a probability by a hundred to show it as a percentage.

Vocabulary is defined in [`../CONTEXT.md`](../CONTEXT.md); the behaviour is
specified in [`../docs/SPEC.md`](../docs/SPEC.md).

## What it does

|                                |                                                                                                                                |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| **Tools → Speedrun Dashboard** | A window with the three scores per section, coverage, the evidence counts, the unmapped card count, and a per-Topic breakdown. |
| **Reviewer**                   | The Topic label is withheld while a question is on screen and restored with the answer.                                        |

Abstention is rendered as a first-class result. It gets the same box, the same
weight and the same position an available score would, and prints the backend's
own sentence — _"Only 0 graded reviews in BB. Need 200."_ — where the number
would be. It is never an error, never a dash, never an empty panel. On a fresh
collection all twelve scores abstain, and that page is the product working, not
the product failing.

The count of Unmapped cards appears in every section and in the collection-wide
panel, including when it is zero. A mastery figure whose denominator is hidden
is the exact number this project exists to distrust, so the denominator is not
behind a disclosure triangle — it is printed *above* the scores, beside the
count of cards that were mapped, before the reader reaches the figure it
qualifies. On MileDown's deck those two numbers are 1,790 and 1,098, and a
Bio/Biochem score read without them is a claim about 38% of a collection wearing
the collection's name. See
[`../evidence/dashboard/`](../evidence/dashboard/README.md).

## How it loads

Anki imports every directory under `<profile base>/addons21/` that contains an
`__init__.py`. This add-on lives in the fork rather than in a hand-installed
`.ankiaddon`, so installing it means pointing that folder at this source tree:

```sh
python speedrun/addon/install.py            # default profile base
python speedrun/addon/install.py --base DIR # a specific ANKI_BASE
python speedrun/addon/install.py --status   # report, change nothing
```

That creates `addons21/speedrun` as a symlink (a directory junction on Windows,
which needs neither Developer Mode nor elevation) pointing here, and seeds
`meta.json` from `manifest.json`. Restart Anki and the add-on is live; edit a
file here and restart again and the edit is live, because there is no second
copy.

Doing it by hand is the same two steps: link or copy this directory to
`addons21/speedrun`, then restart.

On import, `__init__.py` registers the dialog and appends to two hooks. That is
the whole entry point.

### Only `gui_hooks`, no monkeypatching

| Hook                   | What it does                                                                             |
| ---------------------- | ---------------------------------------------------------------------------------------- |
| `main_window_did_init` | Adds **Speedrun Dashboard** to the Tools menu.                                           |
| `card_will_show`       | Redacts Topic tags from the question side; adds the Topic label back on the answer side. |

Plus `aqt.dialogs.register_dialog`, Anki's documented entry point for add-on
windows — it keeps a single copy open and tears it down when the collection
closes.

Nothing upstream is patched, wrapped or replaced. Two consequences follow, and
both are things the spec asks for. Disabling the add-on leaves stock Anki
behind, exactly, with no residue — the first of the three off switches, and the
one `test_off_switches.py` asserts by driving the same review session with the
add-on absent, present-but-disabled and loaded, and comparing what the scheduler
did. And
`card_will_show` is the one hook that sees rendered card HTML in the reviewer,
the previewer _and_ the card-layout screen, so hooking it once covers all three;
monkeypatching `Reviewer._showQuestion` would have covered one of them and would
break the next time upstream touched it.

### Why a Qt dialog and not a mediasrv page

Anki serves its Svelte screens over mediasrv, and a route there would have given
the dashboard a URL and a Playwright test. Registering a route means editing
`qt/aqt/mediasrv.py`. This fork's entire upstream diff is three lines, and that
is itself a deliverable — a URL is not worth a fourth. `AnkiWebView` renders the
same HTML with the same fonts and the same light/dark theming without touching
anything upstream.

The reads run through `QueryOp`, Anki's own helper for a background read, so the
UI never blocks and the call never races the collection. Both `SpeedrunService`
methods are pure reads: no undo entry, no mutation. Opening the dashboard
mid-review disturbs nothing.

## Configuration

Tools → Add-ons → Speedrun → Config. Defaults and explanations live in
`config.json` and `config.md`.

`coach_enabled` and `ai_enabled` are the two in-app off switches. They are
stored in `config.py` and interpreted in `switches.py` and nowhere else, because
the whole claim of these switches is that measurement does not depend on them —
a claim only as good as the number of places allowed to read them. `ai_enabled`
is the wider one: off means no generation *and* no coach, and the agent service
failing to answer produces the identical state, so the degraded path and the
chosen path are the same path. Neither switch can withhold a score, and a test
renders the dashboard under all eight combinations to prove it. The third off
switch is disabling the add-on, which is not in this file and cannot be — see
[`../eval/offswitch/OFF_SWITCHES.md`](../eval/offswitch/OFF_SWITCHES.md).

The one entry worth reading twice is `outline_topic_count` per section. It is
how many content categories the AAMC's published Outline lists — 10 for
Chem/Phys, 9 for Bio/Biochem, 12 for Psych/Soc — and `SectionScoresRequest`
requires the caller to supply it, because coverage is meaningless without a
denominator. It is the Outline, not a threshold, and it is data rather than
code for that reason. Setting it to `0` makes readiness abstain and say so, so
getting it wrong withholds a score and can never invent one.

## Files

|                                           |                                                                      |
| ----------------------------------------- | -------------------------------------------------------------------- |
| `__init__.py`                             | Entry point. Registers the dialog and the two hooks.                 |
| `dashboard.py`                            | The `QDialog` + `AnkiWebView`, and the Tools menu item.              |
| `render.py`                               | HTML. Computes nothing; formats backend output.                      |
| `backend.py`                              | The only place `SpeedrunService` is called.                          |
| `reviewer.py`                             | The `card_will_show` hook.                                           |
| `topics.py`                               | Which tags name a Topic, and how the label is hidden. Pure.          |
| `switches.py`                             | The only place `coach_enabled` and `ai_enabled` are interpreted.     |
| `config.py` / `config.json` / `config.md` | Configuration and its documentation.                                 |
| `install.py`                              | Developer convenience: link this tree into a profile.                |
| `manifest.json`                           | Add-on metadata. `meta.json` is generated from it and is not source. |
| `tests/`                                  | See below.                                                           |

`render.py`, `topics.py` and `switches.py` import nothing from `aqt` or `anki`,
which is why they are testable without a Qt event loop. `dashboard.py` and `reviewer.py` are
wiring, and are covered by the harness described below rather than by unit
tests — the spec deliberately leaves the add-on unseamed, because a seam here
would test a passthrough and would invite score logic to drift into a second
place.

## Tests

```sh
PYTHONPATH=out/pylib out/pyenv/Scripts/python.exe -m pytest speedrun/addon/tests -q
```

(`out/pyenv/bin/python` on macOS and Linux.) Forty-one tests, in two files.

`test_dashboard.py` — twenty-four. Two open a real empty collection, call the
real backend and assert the sentence a student would actually read — that all
twelve scores abstain, that each names its own shortfall, and that the unmapped
count is on screen once per section.

Six more build a collection labelled the way MileDown's deck is labelled,
install the **shipped crosswalk file verbatim** into collection config, and read
what comes back: that the deck's own tags resolve to Outline topics without a
note being touched, that a label the crosswalk *refused* is counted as unmapped
rather than dropped, that narrowing to a section cannot shrink the unmapped
count, that both counts are printed above the scores rather than below them, and
that a crosswalked-but-never-reviewed deck still abstains everywhere and says
why — which is the state the real 2,888-card deck is in today. A deck carrying
none of Speedrun's own tags is the normal case, so a dashboard only ever
exercised against `mcat::`-tagged notes had never been run in its own working
conditions.

The rest cover the renderer against stand-ins: that an estimate is printed as
the backend produced it and not rescaled, that four-figure counts are grouped
for reading but never combined into a ratio, that a section still prints its
unmapped count when the mastery read is missing, that an abstention never
renders as an empty box or as an error, that backend text is escaped, and that a
longer Topic tag is not left half-redacted on the question side.

`test_off_switches.py` — seventeen, covering all three off switches. The heavy
one builds a collection with review history, copies it, and drives the same fixed
review session in three fresh interpreters — Speedrun absent, installed but
disabled, and installed and loaded — then asserts the scheduler served the same
cards in the same order and made the same decisions in all three, field for
field. The harness is `scheduling_trace.py`, and what it does and does not
compare is written down in
[`../eval/offswitch/OFF_SWITCHES.md`](../eval/offswitch/OFF_SWITCHES.md).

`PYTHONPATH=out/pylib` is what makes the generated Python bindings importable;
without it the backend-driven tests skip and the renderer tests still run.

### Playwright does not apply

`ts/tests/e2e/` drives **mediasrv pages** with Chromium, against an Anki
launched into a throwaway `ANKI_BASE`. The dashboard is not a mediasrv page, and
a throwaway base has no `addons21/speedrun` in it, so a spec there would assert
against a window Playwright cannot reach in a profile the add-on is not
installed into. Making it applicable would mean both a mediasrv route and a
change to `qt/tests/launch_anki_for_e2e.py` — two upstream edits, for a test
already covered.

What replaced it: a headless boot of the real application. Seed a temporary
`ANKI_BASE`, run `install.py` against it, launch `tools/run.py` under
`QT_QPA_PLATFORM=offscreen`, and assert from inside the running process that the
Tools menu carries `actionSpeedrunDashboard`, that `card_will_show` has a hook
from `speedrun.reviewer`, that `dialogs.open("SpeedrunDashboard")` returns the
dialog, and that the rendered page contains twelve abstentions and four unmapped
counts. That harness is throwaway and is not committed; it is described here so
it can be rebuilt.

## Shipping it preinstalled — what upstream would have to change

**Nothing below has been done.** The fork's upstream diff is three lines —
`rslib/src/lib.rs`, `rslib/proto/src/lib.rs`, `pylib/anki/collection.py` — and
keeping it that small is worth more than saving a user one command. This section
exists so the cost is stated rather than discovered.

`AddonManager` knows exactly one search root: `ProfileManager.addonFolder()`,
i.e. `<base>/addons21`. `__init__` puts it on `sys.path`, `allAddons()` lists
it, and `addonsFolder(module)` resolves everything else — `config.json`,
`config.md`, `meta.json`, `user_files` — underneath it. An add-on shipped inside
the application is in none of those places, so nothing finds it.

**Option A — a second, read-only bundled root** (the right one, and not small).
In `qt/aqt/addons.py`: add the bundled directory to `sys.path` in `__init__`,
union it into `allAddons()`, and teach `addonsFolder(module)` to resolve a
bundled module to it. Metadata writes must keep going to the profile, so that a
bundled add-on can still be disabled and configured on a read-only install —
that is what keeps "disable Speedrun and Anki behaves exactly as before" true,
and it is a stated user story, so it cannot be traded away. Then packaging:
`qt/hatch_build.py` force-includes `speedrun/addon/` into the `aqt` wheel, the
briefcase configuration includes it in the installer, and a `build/` rule stages
it so `just run` and the wheel agree. Realistically 30–40 lines across four
upstream files, none of them one-liners.

**Option B — install once on first run.** `AnkiQt.setupAddons` already knows how
to install an `.ankiaddon`; copying a bundled bundle into the profile when it is
absent is roughly five lines in `qt/aqt/main.py`, plus the same packaging work as
Option A. Cheaper, but it leaves a copy of the add-on in every profile, drifting
from the fork it was built from — which is a strange outcome for a fork whose
add-on _is_ the fork.

**Option C — import it from `aqt/main.py` directly.** One line, and rejected. It
would stop being an add-on: not listed in the Add-ons dialog, not disablable,
and "adopting Speedrun is reversible" would go from a demonstrable claim to a
promise.

Until one of those is made, `install.py` is the supported path, and it takes one
command.

## Limitations

- The dashboard reads on open and on **Refresh**; it does not live-update while
  you review. Recomputing on every answer would put a backend call in the review
  loop for a number that moves imperceptibly.
- The Topic label is hidden textually, by redacting the tag string out of the
  rendered HTML. A template that renders the Topic in some _other_ form — a
  deck name in a header, say — is not covered, because there is nothing to match
  on. The Crosswalk (T-13) is what makes this fully solvable.
- Readiness abstains even when every threshold is met, and says so. The mapping
  from question performance to a scaled score is not validated against held-out
  outcomes, and an unvalidated projection is not going to be printed as a number.
  See `../docs/SCORE_MODEL.md`.
- `meta.json` is written by `install.py` and rewritten by Anki whenever the
  add-on is toggled or configured. It is a local artifact, not source, and
  belongs in `.gitignore` along with `speedrun/addon/__pycache__/` and
  `speedrun/addon/user_files/`.
