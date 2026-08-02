# Speedrun — Planning Docs

**Exam: MCAT (472–528).** Three science sections modeled. CARS deliberately not modeled.
Built on forks of [ankitects/anki](https://github.com/ankitects/anki) and [ankidroid/Anki-Android](https://github.com/ankidroid/Anki-Android). AGPL-3.0-or-later. Credit to Anki.

Read in this order:

| Doc | What it settles |
|---|---|
| [PRD.md](PRD.md) | What the app is, the three scores, the give-up rule, in/out of scope, acceptance criteria |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Add-on + small fork + agent service. The Rust change. Where coach data lives and why. Toolchain state. |
| [FLOWS.md](FLOWS.md) | Session flow, the seven-step coach loop, the generation safety gate, scoring + abstention, sync/conflict, degradation |
| [SCORE_MODEL.md](SCORE_MODEL.md) | How each of the three scores is computed and validated, and what we are explicitly not claiming |
| [TRACEABILITY.md](TRACEABILITY.md) | One row per SpikyPOV → the code it forced → the number that would falsify it. **Graded at 25%.** |
| [TEST_PLAN.md](TEST_PLAN.md) | The eight required tests, the held-out data protocol, the break-tests |
| [BUILD_PLAN.md](BUILD_PLAN.md) | The 24-hour order of work, with cut lines |

Source: [../brainlifts/BRAINLIFT_v3.md](../brainlifts/BRAINLIFT_v3.md).

## The three decisions everything else follows from

1. **Anything both platforms must show is computed in `rslib`.** The add-on renders; it does not compute. Otherwise the phone cannot show the same scores offline, and §4 fails.
2. **Coach data rides Anki's own sync** — attempts as suspended `Speedrun::Attempt` notes, aggregates in `col config`. A side database would never reach the phone.
3. **Abstention is the default state.** A score appears only when it is earned. Inventing a readiness number is an automatic fail; abstaining never is.

## Known blockers as of 2026-08-02

- Rust toolchain not installed (anki pins 1.92.0) — **critical path**
- Java 8 on PATH; AnkiDroid needs JDK 17+
- Neither repo is a fork yet; both `origin` point upstream
- rsdroid (`ankidroid/Anki-Android-Backend`) not cloned — needed to ship the Rust change to the phone
