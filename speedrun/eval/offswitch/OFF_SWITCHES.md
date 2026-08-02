# Off switches — what was proven, and what was not

Speedrun has three off switches with three different blast radii. This file
records, for each, **what a test asserts**, **the command that runs it**, and
**what is left unverified** — because a partial check that reads as a total one
is worse than no check.

Everything here is produced by:

```sh
PYTHONPATH=out/pylib out/pyenv/Scripts/python.exe -m pytest speedrun/addon/tests -q
```

(`out/pyenv/bin/python` on macOS and Linux.) 31 tests: the 14 that already
covered the dashboard, plus the 17 below. The two switches' logic lives in
[`speedrun/addon/switches.py`](../../addon/switches.py); the scheduling harness
is [`speedrun/addon/tests/scheduling_trace.py`](../../addon/tests/scheduling_trace.py).

```
$ PYTHONPATH=out/pylib out/pyenv/Scripts/python.exe -m pytest speedrun/addon/tests -q
...............................                                          [100%]
31 passed in 5.34s
```

---

## Switch 1 — the add-on disabled

**Claim.** Install Speedrun, disable it, and Anki behaves exactly as it did
before: same cards in the same order, same intervals, same card state, same
revlog.

**Why this one is structural rather than a flag.** Anki disables an add-on by
never importing it. `AddonManager.__init__` puts `<base>/addons21` on `sys.path`
unconditionally; `loadAddons` then skips any add-on whose `meta.json` says
`disabled`. So a disabled add-on is a directory that is importable and never
imported — there is no Speedrun code in the process to misbehave, and no flag
anyone has to trust.

### How it is tested

One collection, built once and then **byte-copied** per arm, driven through the
same fixed 20-answer session in **three fresh interpreters**:

| arm | state |
| --- | --- |
| `absent` | nothing of Speedrun on `sys.path`, nothing imported |
| `disabled` | a real copy of `speedrun/addon` installed as `addons21/speedrun`, that directory on `sys.path`, **never imported** |
| `enabled` | installed *and* loaded, running the entire dashboard gather and both reviewer hooks against every card in the session |

The copy matters: Anki seeds its interval fuzz from the card id and the rep count
(`rslib/src/scheduler/answering/mod.rs`, `get_fuzz_seed_for_id_and_reps`), and
card ids are creation timestamps, so two collections built a second apart would
legitimately schedule differently. Ratings and `milliseconds_taken` are fixed.

Each arm reports, from inside its own interpreter, whether `speedrun` is in
`sys.modules` — so the comparison cannot pass by the arms being accidentally
identical (`test_the_arms_were_in_the_state_they_claim`).

### Asserted — compared exactly, field for field

`test_a_disabled_addon_schedules_identically_to_no_addon_at_all` compares
`absent` against `disabled`; `test_an_enabled_addon_does_not_perturb_the_scheduler_either`
compares `absent` against `enabled`. Both assert full equality of the 20-step
record, which contains, per step:

| group | fields |
| --- | --- |
| **Queue order** | the card id served, its queue (`NEW`/`LEARNING`/`REVIEW`), and the `new_count` / `learning_count` / `review_count` remaining |
| **Scheduling decisions offered** | for **all four buttons**, the state the scheduler would move the card to: new `position`; learning `remaining_steps` + `scheduled_secs`; review `scheduled_days` + `ease_factor` + `lapses` + `leeched`; relearning all of both |
| **Card state after the answer** | `type`, `queue`, `ivl`, `factor`, `reps`, `lapses`, `left`, `odue`, `odid`, `flags`, and `due` for new and review cards (a queue position or a day number) |
| **What Anki recorded** | the revlog row it wrote: `ease`, `ivl`, `lastIvl`, `factor`, `type` |

`test_the_session_the_arms_are_compared_over_is_worth_comparing` asserts the
session is worth comparing before anything is concluded from it: all three queue
kinds were served, at least three card types occurred, all four buttons were
pressed, and at least one card lapsed.

`test_the_comparison_can_fail` traces the same collection twice, once with an
"add-on" that buries a single card, and asserts the traces diverge. Run by hand,
that divergence appears at step 1 — queue kind and counts both change. A
comparison never seen to fail is not evidence.

### Asserted with a ±1 second tolerance

An intraday learning card's `due` is *the moment of answering* plus a fuzzed
delay. The arms run seconds apart, so the moment differs by construction. The
**delay** is compared, and compared twice: exactly, as `scheduled_secs` in the
states above, and again as `due` minus the second the answer was sent
(`_assert_learning_delays_match`). The ±1s covers only a clock second ticking
between reading the time and the backend reading it — nothing an add-on can
influence.

### Not asserted

- **The absolute `due` epoch second of learning and relearning cards.** It is
  wall-clock now plus the delay, and the delay is compared twice over.
- **`mod` and `usn` on cards and on the collection**, and the revlog row's `id`
  (the answering timestamp) and `time` (answer duration, which the harness pins
  at 1500 ms and so is not an observation).
- **FSRS.** The collection uses the shipped SM-2 defaults, so no FSRS memory
  state is exercised. Scheduling under FSRS is untested here.
- **Filtered decks, non-default deck presets, sibling burying** (off by default),
  **leech actions** beyond the `leeched` flag the scheduler reports, and **day
  rollover** — the session runs inside one day.
- **The comparison is against this fork with the add-on absent, not against
  pristine upstream Anki.** Whether the fork's own Rust diff leaves the scheduler
  untouched is a separate claim, resting on the upstream diff being confined to
  files that are not scheduler files. It is not asserted here.
- **The Add-ons dialog toggle itself.** The `disabled` arm reproduces Anki's
  mechanism (folder on `sys.path`, module never imported); it does not click the
  checkbox in a running Qt app.
- **`dashboard.py` and `reviewer.py` are not executed by these tests.** The
  `enabled` arm calls what they call — `backend`, `render`, `topics`, `switches`
  — but not the `QDialog` or the `gui_hooks` registration, which need a Qt event
  loop.

---

## Switch 2 — `coach_enabled = false`

**Claim.** Reviews, Memory, coverage, the dashboard and its abstentions all
work. The spoken loop does not run.

### Asserted

- `test_coach_off_stops_the_loop_and_nothing_else` — `coach_allowed` is false and
  `generation_allowed` stays **true**. The switch is scoped to the loop, which is
  what makes ablation arm B a clean comparison against arm A: the only thing that
  changed between them is the loop.
- `test_the_topic_label_stays_hidden_when_the_coach_is_off` — Topic redaction is
  measurement hygiene, not coaching ("this is 5C" is most of the answer on a
  thermodynamics item), so it deliberately does **not** consult `coach_enabled`.
  Arm B reviews with the coach off and still needs the label withheld.
- `test_no_switch_can_change_a_single_number_on_the_page` — see below.

### Not asserted

- **There is no coach loop yet** (T-14, wave 2). What is proven is that the
  single gate every coach entry point is required to pass returns false. Nothing
  yet exists to be gated, so "no spoken loop ran" is true vacuously.

---

## Switch 3 — `ai_enabled = false`

**Claim.** No generation and no coach. Memory, coverage and the dashboard still
come from the Rust engine.

### Asserted

- `test_ai_off_stops_generation_and_the_coach_with_it` — `generation_allowed` and
  `coach_allowed` are both false **even with `coach_enabled` left true**. The
  coach cannot run on items that were never generated, so the wider switch
  subsumes the narrower one.
- `test_an_unreachable_service_is_the_same_state_as_ai_off` — an unreachable
  agent service produces the identical decision to `ai_enabled = false`, per
  FLOWS §6. One disabled state, one code path, and the degraded path is exercised
  every time the chosen one is. The two are distinguishable to the student — the
  dashboard says which — but not to the code.
- `test_ai_off_does_not_open_a_socket` — with `ai_enabled = false` the probe is
  never called. A switched-off feature that still probes the network is not
  switched off; it is a feature with a timeout, and every dashboard open would
  pay it.
- `test_the_probe_treats_every_failure_as_unreachable_and_never_raises` — refused
  connection, malformed URL and empty URL all return false rather than raising.
  An empty `agent_url` is the state of a fresh install, and a fresh install must
  not show a stack trace.
- `test_reading_the_switches_cannot_raise` — a probe that throws costs the coach,
  not the page. `dashboard.py` reads the switches on its way to rendering scores
  that have nothing to do with the AI, so `switches.read` swallowing a
  misbehaving probe is what keeps a page of measurements from being lost to one.
- `test_the_dashboard_still_measures_with_ai_off_and_the_service_unreachable` —
  **the graded non-negotiable.** On a collection with genuine review history,
  with `ai_enabled = false` and no agent service in existence, the dashboard
  renders: twelve abstentions, each carrying the engine's own sentence naming the
  threshold ("… graded reviews in BB. Need 200."), coverage, the evidence counts,
  and the Unmapped card count once per section plus the collection-wide panel. It
  is not the "Could not read the collection" error page.
- `test_the_dashboard_reports_real_review_history_with_ai_off` — the engine is
  producing real numbers in that state, not abstaining its way to a page that
  happens to render: `cards_considered > 0`, at least one Topic with history, a
  non-zero Unmapped count, at least one section with `graded_reviews > 0` and at
  least one with `coverage_pct > 0`.
- `test_the_shipped_defaults_are_on_and_missing_keys_read_as_on` — `config.json`
  and `config.DEFAULTS` agree, so a switch cannot mean one thing on a fresh
  install and another after a reset. An entirely empty config yields
  `ai_enabled` true but no `agent_url`, hence unreachable, hence no coach: knowing
  nothing still ends with the AI off.

### The invariant, checked over every combination

`test_no_switch_can_change_a_single_number_on_the_page` renders the dashboard on
a studied collection under **all eight** settings of `coach_enabled` ×
`ai_enabled` × service reachable. With the one status sentence removed, all eight
pages are **byte-identical**. Every score, range, coverage figure, count and
abstention is unchanged, because none of them passes through a switch. The test
also asserts the status sentence itself took four distinct values, so the
equality above is not passing trivially.

### Not asserted

- **There is no generation yet** (T-08, T-10, wave 2), for the same reason as the
  coach: the gate is proven, the thing gated does not exist.
- **The probe is never exercised against a live agent service.** Reachability is
  injected in the switch tests, and stubbed unreachable in the `enabled`
  scheduling arm. `switches.probe` is only tested against failures.
- **`ai_enabled = false` on Android** is not covered here; this is the desktop
  add-on's test suite.

---

## Where the switches live

| | |
| --- | --- |
| `speedrun/addon/switches.py` | the only place `coach_enabled` and `ai_enabled` are interpreted |
| `speedrun/addon/config.py`, `config.json`, `config.md` | where they are stored and documented |
| `speedrun/addon/dashboard.py` | reads them **last**, after every measurement is in hand, so no score can wait on or fail because of an agent service |
| `speedrun/addon/render.py` | prints the one status sentence — the only thing on the page a switch can change |

Nothing else in the add-on may branch on them. The whole claim of these switches
is that measurement does not depend on them, and that claim is only as good as
the number of places allowed to read them.

---

## Addendum — the fork-versus-upstream half of the claim

The traces above compare **this fork with the add-on absent, disabled, and
enabled**. They do not compare the fork against pristine upstream Anki, so on
their own they cannot rule out the fork's own Rust change having moved the
scheduler. That gap is closed structurally rather than by trace, because
building and driving a second upstream tree costs more than the claim is worth:

Every upstream path the fork touches, in full:

```
README.md                     .gitignore
proto/anki/speedrun.proto     pylib/tests/test_speedrun.py
pylib/anki/collection.py      rslib/proto/src/lib.rs
rslib/src/lib.rs              rslib/src/speedrun/**
```

Three of those are one-line service registrations; the rest are new files under
a namespace of our own. **Nothing under `rslib/src/scheduler/`, no queue
builder, no FSRS path, and no revlog writer appears anywhere in the diff** —
verified by listing the diff and filtering for those paths, which returns
nothing.

So the scheduler is not modified, it is *not present in the diff at all*. That
is a stronger statement than "we changed it carefully," and it is the reason the
add-on-disabled trace is sufficient evidence for the user-facing promise.

What remains genuinely unasserted: that the registration lines cannot perturb
scheduling. They add a service to a dispatch table and nothing else, but no test
asserts it.
