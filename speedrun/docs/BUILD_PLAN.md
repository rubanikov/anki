# Speedrun — 24-Hour Build Plan

Hours are offsets from now (H+0), not clock times. **Cut lines are real** — when a box expires, take the fallback and move on. Everything below the "must ship" line protects a hard grading cap.

---

## Must ship — each protects a cap

| | Protects |
|---|---|
| Rust change, 3 Rust tests + 1 Python test, undo + no-corruption proof | 50% cap |
| Android on the same engine, syncing both ways | 70% cap |
| Held-out data frozen, leakage clean, rerunnable setup | 60% cap / score→0 |
| Both apps install on a clean device | 50% cap |
| Give-up rule enforced in the backend | **automatic fail** |
| Traceability table | 60% cap |
| Public fork, AGPL, credit, exam in README | — |

---

## H+0 → H+1 · Unblock everything (do these in parallel)

Nothing else can start until the first item is running.

1. **Install Rust 1.92.0.** `rustup` then let `rust-toolchain.toml` pin it. Kick off `./ninja wheels` (or `just build`) immediately after — the first anki build is long and mostly unattended.
2. **Install JDK 17+** and point `JAVA_HOME` at it. Java 8 is currently on PATH and AnkiDroid will not build.
3. **Fork both repos** on GitHub, re-point `origin`. Add AGPL-3.0-or-later notice, credit to Anki, and **"Exam: MCAT"** at the top of the README, in the first commit.
4. **Clone `ankidroid/Anki-Android-Backend`** (rsdroid) — it isn't present, and it's the only way the Rust change reaches the phone.
5. **Freeze H1/H2/H3 and write the manifest** (TEST_PLAN §0). Twenty minutes, unrecoverable if skipped.
6. Move `anki_v2/docs/` → `anki/speedrun/docs/`.

**Gate at H+1:** anki is compiling and JDK 17 is active. If anki won't compile on Windows, switch to WSL now rather than at H+6.

---

## H+1 → H+5 · The Rust change (critical path, do not parallelize away from this)

- `proto/anki/speedrun.proto` — `SpeedrunService`, two methods. Verify `rslib/proto/build.rs` picks up a new file; if it enumerates explicitly, add the entry. **Fallback: append the service to `stats.proto`**, which already hosts `StatsService`.
- `rslib/src/speedrun/` — `mastery.rs`, `scores.rs`, `thresholds.rs`.
- Both methods are **pure reads**. No `Op`, no undo entry, no mutation. This is what makes the undo/corruption proof nearly free.
- Filter `Speedrun::Attempt` notetype inside every query; expose `cards_excluded`.
- 3 Rust unit tests + 1 Python test (TEST_PLAN §1).
- Write the one-page "why this belongs in Rust" note and the list of upstream files touched.

**Gate at H+5:** `cargo test -p anki speedrun` and the Python test are green.
**If not green at H+6:** cut `SectionScores` down to memory-only and ship it. A smaller Rust change that works beats a larger one that doesn't compile.

---

## H+5 → H+10 · Android (hard box — this is where weeks die)

- Point rsdroid's anki submodule at your fork, build the `.aar` with cargo-ndk.
- Consume it from your AnkiDroid fork; Kotlin call to `TopicMastery` / `SectionScores`.
- Dashboard screen: three scores, ranges, coverage %, abstention reasons.
- Self-host `anki --syncserver`; point both clients at it.

**Cut line at H+10.** If rsdroid won't build: ship AnkiDroid on the **stock** backend with sync working and the dashboard reading what it can. You take the §8 "check it on the phone" hit but you keep the 70% cap off. Say plainly in the README which one you shipped — a stated limitation reads far better than a silent one.

---

## H+10 → H+15 · Add-on and agent (parallel with Android where possible)

- `speedrun/addon/` — dashboard, coach UI, agent client. **`gui_hooks` only, no monkeypatching.**
- Reviewer hook: hide the topic label while the question is on screen.
- Coach webview: `MediaRecorder` capture, POST to the service. **No `<input>` element in any live-question template** — that's the enforcement mechanism, not a preference.
- `speedrun/agent/` — FastAPI + LangGraph, seven nodes matching the loop steps. `{output, source_id, span}` on every node's state. LangSmith tracing on.
- Generation gate (`gate.py`): retrieve → generate → **assert the correct answer's span is in the retrieved text** → distractor check → ship or drop. No LLM self-verification.
- Corpus: AAMC outline + OpenStax (CC BY 4.0), chunked and indexed.
- Off switches wired: add-on disabled ⇒ stock Anki; `coach_enabled`; `ai_enabled`.

**Gate at H+15:** with the service killed, the app still starts, still scores memory, still shows coverage. If that doesn't hold, fix it before adding anything.

---

## H+15 → H+19 · Evidence (this is 38% of the grade — do not let it get squeezed)

Priority order if time runs short:

1. **Paraphrase test** — highest value per hour. Validates the performance model and supplies thesis evidence.
2. **Memory calibration** — chart + Brier + log loss on H1. Required, and it's what backs the honesty claim.
3. **Leakage check** — must exit 0, ship the output.
4. **AI card check** on H3, cutoff already recorded.
5. **Retrieval baseline** — grounded vs BM25 vs embeddings.
6. **Crash test** — 20 kills per app, `check database` each time.
7. **`make bench`** on the generated 50k deck.
8. **Ablation** — three builds. Underpowered is fine; state the number in advance and report the range honestly.

---

## H+19 → H+22 · Package and prove

- Desktop installer with the add-on **preinstalled** — a `.ankiaddon` the grader has to install by hand fails "runs on a clean machine."
- Packaged Android build.
- **Clean-device test.** Actually run both on a machine that has never seen this project.
- Sync tests 1–3 (TEST_PLAN §2), conflict rule already written down.

---

## H+22 → H+24 · Submit

- Proof artifacts: commit hash, clean-build recording, test output, install recording, **a phone review appearing on desktop after sync**, eval numbers.
- Demo video 3–5 min: open with the SpikyPOV in one sentence → the feature it produced → a review session → the Rust change in action → phone-to-desktop sync → the three scores with ranges → AI features → results.
- Update the BrainLift's "what changed" section (POV 5 rewording, RAG scope correction — already drafted in TRACEABILITY.md).
- README: exam up front, build instructions for both apps, architecture overview, Rust note, upstream files touched.

---

## Standing rules

- **Never ship a number without a range**, and never a range narrower than ±2. Inventing a readiness number is an automatic fail — abstaining is always the safe move.
- **When a box expires, take the fallback.** Every cut line above trades scope for a cap that stays off.
- **A failed test honestly reported scores. A polished claim you can't back up does not.** "We calibrated memory but cannot prove the projected score" is explicitly worth more than a confident number.
- Budget the proof artifacts. They are worth real points and they're the first thing that gets skipped at hour 23.
