# Speedrun — Specification

Vocabulary is defined in [CONTEXT.md](../CONTEXT.md). Decisions are recorded in
[docs/adr/](./adr/). Execution order is in [TICKETS.md](./TICKETS.md).

---

## Problem Statement

A premed builds a six-thousand-card deck, averages 70% in Anki, feels ready, and
scores far below what every tool predicted.

Nothing they used was lying. Every number they saw was measured **while
something was helping them**. A flashcard hands over the cue before asking for
the answer. A question bank hands over five options, one of which is right.
Percent-correct is computed over questions the student chose to attempt, at a
moment they chose to attempt them. Anki's own headline figures make it worse:
"mature cards" counts cards the scheduler decided to wait three weeks on — a
setting, not knowledge — and "estimated total knowledge" multiplies card count by
recall probability, so adding three thousand junk cards makes it go up.

So the student has no way to answer the only question that matters: *does any of
this survive contact with a question nobody prepared me for?* They find out on
exam day, once, for six hundred dollars.

Worse, the tools that could tell them are structurally unable to. A study app's
incentive is to show a rising number. Nothing in the market will say "we don't
know yet."

## Solution

Speedrun treats the student's existing Anki collection as a **sensor** — a
years-long record of what one person actually learned and how well it stuck,
which no testing company has — and reports three separate numbers over it,
never blended:

- **Memory** — can they recall this fact right now? Read from their own review
  history through FSRS.
- **Performance** — can they answer a **held-out item**: a new exam-style
  question, never seen, never hinted, never derived from their own cards?
- **Readiness** — what would they score today, given performance and how much of
  the AAMC outline they have actually covered?

Every one of them starts **abstaining**, and stays that way until the evidence
clears a **give-up rule** enforced in the backend where no interface can talk
past it. An abstention always names the specific shortfall and the number that
would clear it: *"Only 84 graded reviews in Chem/Phys. Need 200."*

Around that sits a **coach loop** that runs after review: a cold question, a
confidence rating taken **before** the answer is revealed, an explanation spoken
aloud, and a **contrast pair** — the same question with one detail changed.
Only the cold question scores. The rest teach and are never graded.

The product's distinguishing behaviour is what it refuses to do. It will show
one section reporting three real scores while two sections say exactly how many
attempts short they are — because that is the truth, and because a dashboard
that always has a number for you is a dashboard that is guessing.

## User Stories

### Measuring what is known

1. As a premed, I want my Memory score computed from my own review history, so that it reflects what I actually studied rather than what an app assumed about me.
2. As a premed, I want Memory reported per section, so that I can see Bio/Biochem is solid while Chem/Phys is not.
3. As a premed, I want Memory broken down per Topic, so that I know which content category to open next.
4. As a premed, I want every score to carry a range, so that I can see how uncertain it is rather than trusting a point estimate.
5. As a premed, I want a range never narrower than the AAMC's own ±2 points, so that the app cannot claim more precision than the exam itself has.
6. As a premed, I want topics with cards but no review history counted as *not covered*, so that owning cards about something is never mistaken for having studied it.
7. As a premed, I want cards that have no FSRS memory state left out of the mean rather than assigned a made-up value, so that the average is over real evidence.
8. As a premed, I want to see how many of my cards could not be placed on the outline, so that I know what fraction of my deck the score is actually about.
9. As a premed, I want a topic with two cards unable to swing my section average, so that a tiny topic cannot distort the picture.
10. As a premed, I want Speedrun's own records excluded from my mastery numbers, so that the app cannot inflate the score it is grading me on.
11. As a premed, I want to see the count of excluded records, so that the exclusion is something I can check rather than something I am told.

### Being told nothing, honestly

12. As a premed, I want the app to refuse to show a score it cannot support, so that I am never misled into thinking I am ready.
13. As a premed, I want every abstention to name the exact shortfall, so that I know what to do next instead of just being blocked.
14. As a premed, I want the give-up thresholds enforced in the engine rather than the screen, so that no part of the app can route around them.
15. As a premed, I want the same thresholds applied on my phone as on my desktop, so that the two never disagree about whether I am ready.
16. As a premed, I want the performance threshold to mean the same thing in every section, so that a section with more topics is not held to a stricter standard by accident.
17. As a premed, I want held-out attempts counted within the section they belong to, so that work in Psych/Soc never unlocks a score for Bio/Biochem.
18. As a premed, I want CARS to say plainly that we do not model it, so that its absence reads as a decision rather than an oversight.
19. As a premed, I want Readiness to abstain while its mapping to a scaled score is unvalidated, so that I am never given a projected MCAT number nobody has checked.
20. As a premed, I want the reason for that abstention stated in the app, so that I understand it is a limitation and not a bug.

### The coach loop

21. As a premed, I want the coach to pick concepts where I look like I am running on recognition, so that my time goes where it is weakest.
22. As a premed, I want to be asked a fresh question cold, so that the measurement happens before any help arrives.
23. As a premed, I want to state my confidence **before** the answer is revealed, so that my calibration is measured rather than remembered.
24. As a premed, I want to explain aloud what a question is testing, so that I find out whether I understand it or merely recognise it.
25. As a premed, I want a contrast pair with exactly one detail changed, so that I have to say what that detail does rather than pattern-match the whole question.
26. As a premed, I want steps after the cold question never to be graded, so that I can think out loud without being punished for it.
27. As a premed, I want the rule stated only after I have tried to state it, so that I am not handed the answer before I have reached for it.
28. As a premed, I want the coach to ask once and then be quiet, so that it does not talk me out of my own reasoning.
29. As a premed, I want no text box anywhere near a live question, so that I cannot quietly copy an answer instead of producing one.
30. As a premed, I want topic labels hidden while a question is on screen, so that the label does not give away the approach.

### Trusting the AI

31. As a premed, I want every generated question checked against a real source before it reaches me, so that I never study something invented.
32. As a premed, I want an item dropped rather than shown when its answer cannot be found in a source, so that silence is preferred to a plausible fabrication.
33. As a premed, I want the model forbidden from checking its own work, so that a generator and its checker cannot share a blind spot.
34. As a premed, I want every AI output to carry the source it came from, so that I can go read the passage myself.
35. As a premed, I want rejected items logged with a reason, so that the gate's behaviour can be inspected rather than assumed.
36. As a premed, I want the app to keep working when the AI service is down, so that an outage costs me the coach and not my scores.
37. As a premed, I want to turn AI off entirely and still get Memory, coverage and the dashboard, so that the measurement does not depend on a model.

### Two devices

38. As a premed, I want to review on my phone and see it reflected on my desktop, so that studying on the bus counts.
39. As a premed, I want reviews done offline on either device to survive and land exactly once, so that no work is lost or double-counted.
40. As a premed, I want the same three scores on my phone as on my desktop, so that I do not have to wonder which one is right.
41. As a premed, I want scores computed on the phone without a network connection, so that the dashboard works where I actually study.
42. As a premed, I want a documented rule for what happens when I grade the same card on both devices offline, so that the outcome is predictable.

### My collection is mine

43. As a premed, I want Speedrun never to modify my notes, cards, or review history, so that my deck stays exactly what it was.
44. As a premed, I want topic attribution done without writing tags onto my notes, so that using Speedrun leaves no trace in my collection.
45. As a premed, I want Speedrun's own records kept in a separate namespace with suspended cards, so that they never enter my study queue.
46. As a premed, I want held-out question text never stored in my collection, so that I cannot accidentally read the test in the card browser.
47. As a premed, I want to disable Speedrun entirely and have Anki behave exactly as it did before, so that adopting it is reversible.
48. As a premed, I want the queue order and scheduling to be provably identical to upstream Anki when Speedrun is off, so that "reversible" is a tested claim rather than a promise.

### Evidence I can check

49. As a sceptical user, I want the Memory model's calibration proven on held-back real reviews, so that "80% means 80%" is measured rather than asserted.
50. As a sceptical user, I want to see whether my performance on new items differs from my recall on my own cards, so that I know whether the two scores measure different things at all.
51. As a sceptical user, I want that comparison able to come out against the product, so that the test is worth running.
52. As a sceptical user, I want a leakage check that proves no held-out item reached the generator or the coach, so that the performance number is not contaminated.
53. As a sceptical user, I want the retrieval evaluation able to show a simpler baseline winning, so that the comparison is not rigged.
54. As a sceptical user, I want the main experimental number and its predicted direction written down before the experiment runs, so that it cannot be chosen after the fact.
55. As a sceptical user, I want the experiment to measure delayed retention rather than same-session performance, so that it is not making the exact error the product exists to attack.
56. As a sceptical user, I want an underpowered result reported as "cannot distinguish" with its interval, so that a weak result is stated rather than dressed up.
57. As a sceptical user, I want every stated limitation written in the README, so that I learn them from the authors rather than by discovering them.

### Operating it

58. As a grader, I want both apps to install and run on a machine that has never seen the project, so that the build is real.
59. As a grader, I want the list of upstream files touched, so that I can see how invasive the fork is.
60. As a grader, I want the Rust change demonstrably running on the phone, so that "shares one engine" is shown rather than claimed.
61. As a grader, I want performance numbers reported as p50/p95/worst on a large deck, so that the app is shown to hold up at scale.
62. As a grader, I want the app to survive being killed mid-review without corrupting the collection, so that it is safe to actually use.
63. As a grader, I want every SpikyPOV traceable to a shipped feature and a number that could falsify it, so that the claims are accountable.

## Implementation Decisions

### Where the numbers are computed

All three scores, the give-up rule, coverage, topic attribution and the unmapped
count live in the **Rust backend**, exposed as `SpeedrunService` over protobuf.
The desktop add-on and the Android client both consume that service and render
what it returns; neither computes a score. This is what makes identical offline
numbers on two platforms true by construction rather than by discipline, and it
is why no seam exists inside either client.

Both methods are **pure reads** — no `Op`, no undo entry, no mutation. That is
what makes the undo-intact and no-corruption proofs nearly free.

### Topic attribution

A **Topic** is one AAMC content category — 31 in total, 9 in Bio/Biochem, 10 in
Chem/Phys, 12 in Psych/Soc. Cards are attributed through a **Crosswalk** keyed on
`(deck path, tags)`, stored in collection config and consulted at read time.
Notes are never written to. Where the deck genuinely cannot distinguish two
categories, the affected cards become **Unmapped cards** and are counted, so
every mastery figure carries a stated denominator.

The crosswalk is a single config blob written by one device. Nothing that two
devices write independently may live in config — that rule is why attempts do
not.

### Where Speedrun's own data lives

- **Attempts** → notes of a dedicated notetype, cards suspended, in their own
  deck. They sync natively and merge per-record, which is exactly the shape of
  the two-devices-offline test. Every score query filters the notetype out.
- **Aggregates, crosswalk, thresholds config** → collection config.
- **Held-out item text** → a desktop-side file, **never the collection**. In the
  collection the student could read the entire held-out set from the card
  browser, and it would ship question text to a phone that never asks questions.
- **Never** a new SQLite table (Anki's sync protocol would not replicate it and a
  schema change risks a forced one-way full sync) and **never** the revlog
  (contaminating the memory model is the sensor corruption the whole stance
  exists to prevent).

### Thresholds

Constants and functions in the backend. Memory needs ≥200 graded reviews and ≥30
distinct cards in the section. Performance needs ≥20 held-out attempts **in that
section** across ≥⅓ of the section's topics — a fraction rather than a flat
count, so the rule means the same thing everywhere. Readiness needs both plus
≥50% coverage, and then still abstains, because the mapping from question
performance to a scaled score is not validated against outcomes.

Any interval computed tighter than ±2 scaled points is widened to ±2.

### The agent

A separate FastAPI service running LangGraph, outside Anki's bundled Python —
its dependency tree does not belong in a Qt app and the phone could never run
it. Graph state carries `{output, source_id, span}` on every node, so source
attribution is structural rather than something a developer remembers to log; an
output reaching the boundary without a source is dropped. Nodes map onto the
coach steps. LangSmith for traces.

**Generation gate:** retrieve → generate → assert the supporting span for the
correct answer is present in the retrieved text → ship or drop. Rejections are
logged with reasons, because Yield cannot be decomposed otherwise. Asking a model
to verify its own item is banned.

### Off switches

Three, with different blast radii: add-on disabled (stock Anki, nothing of ours
loads), `coach_enabled = false` (scores and dashboard work, no spoken loop), and
`ai_enabled = false` (no generation or coach; Memory, coverage and dashboard
still work from the engine).

### Evaluation

Calibration runs against a public review-log corpus rather than our own reviews,
outside the collection entirely. Retrieval is judged by **Yield** — usable items
per hundred attempts — with the gate held constant and only the retriever
varying, plus an ungated control arm that carries the actual claim. The ablation
measures **delayed retention**, with intervention blocks early and the retention
test roughly fifteen hours later.

## Testing Decisions

**What makes a good test here:** it asserts a behaviour a user could observe or a
grader could check, and it fails if the specific misbehaviour we are afraid of
returns. Tests are written at the highest seam that can see the behaviour. A test
that reaches inside a module to check how it computed something is worse than no
test, because it makes the module harder to change without making it more
correct.

Every test in this project should be traceable to a way the product could
mislead someone. The four already written are the model:

- a score emitted below its threshold
- an abstention with no reason attached
- an interval narrower than the instrument's own error
- our own records inflating the number we grade ourselves on

**Seam 1 — `SpeedrunService`.** Carries almost all coverage: score computation,
thresholds, per-section counting, abstention text, crosswalk resolution,
exclusion and unmapped counting. Prior art is in place — Rust unit tests
alongside each module, plus a pylib test that calls through the generated
bindings and so proves the proto contract as well as the logic. New tests join
those files rather than starting new suites.

The undo/corruption proof also lives here: hash the collection, run a thousand
mastery calls, hash again, assert unchanged, then undo an unrelated operation and
assert it still works.

**Seam 2 — the agent service's HTTP boundary.** The generation gate is tested
through the service, not node by node: given a corpus where the answer is absent,
the response must contain no item and must record a rejection with a reason.
Node-level tests would freeze the graph's shape and would not prove the gate
holds at the boundary, which is the only place it matters.

**Seam 3 — eval script CLIs.** Each script's committed artifact is the
assertion: the calibration chart with its Brier score, the leakage check's clean
exit, the paraphrase test's three-way comparison, the retrieval table. These are
run once and reviewed, not asserted in CI.

**Deliberately unseamed:** the add-on and the Kotlin client. Both render backend
output. A seam there would test a passthrough and would invite score logic to
drift into two places that must agree offline.

**Cross-platform equality** is asserted by construction rather than by a test
harness spanning both: the same backend, the same thresholds, the same proto.
The demonstration is a recording of the same collection producing the same
numbers on both.

## Out of Scope

- **Replacing Anki.** Reviewing, scheduling, and FSRS are untouched.
- **Authoring or modifying the student's notes, cards, or review history.**
- **Competing on question volume.** The held-out set is small on purpose.
- **Teaching content.** This is a coach and an instrument, not a course.
- **Any score more precise than the AAMC's own ±2.**
- **A text box on any screen with a live question.** Banned, not discouraged.
- **Modelling CARS knowledge**, by the AAMC's own account of what it tests.
- **A validated readiness projection.** The mapping exists; it is not backed by
  outcome data, so it does not ship as a number.
- **The voice coach on Android.** Desktop only, stated in the README.
- **AI item generation on Android.**
- **Full retrieval over licensed prep material and video.** One bounded corpus
  for now.
- **A designed Android dashboard.** Raw score output proves the same claim.

## Further Notes

**The demo will show two sections abstaining.** That is not a gap; it is the
product's central behaviour on screen, and it was chosen deliberately. The one
change that must never be made under deadline pressure is lowering a threshold so
more sections report.

**Three deliverables were unfalsifiable as originally planned** and were
rewritten: the paraphrase test compared a set against itself, the retrieval
comparison measured a system against its own component, and the ablation measured
a construct whose movement in either direction would have been consistent with
the thesis. Each rewrite makes it possible to lose. That is the point.

**The corpus used for calibration cannot be redistributed.** Its absence from the
public fork is something the leakage check must demonstrate, not assert.
