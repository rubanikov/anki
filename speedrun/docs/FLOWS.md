# Speedrun — Flows

## 1. Session: review → diagnose → coach

```mermaid
flowchart TD
    A[Student reviews own deck<br/>topic label hidden] --> B[Round ends]
    B --> C{"add-on enabled?"}
    C -->|no| Z[Stock Anki. Done.]
    C -->|yes| D["SpeedrunService.TopicMastery()<br/>Rust, excludes Attempt notes"]
    D --> E{"coach_enabled<br/>AND ai_enabled<br/>AND service reachable?"}
    E -->|no| Y[Dashboard only.<br/>Scores still computed.]
    E -->|yes| F[Pick concepts that look<br/>like recognition, not understanding]
    F --> G[Coach loop]
    G --> H[Write Speedrun::Attempt note<br/>card suspended]
    H --> I["SpeedrunService.SectionScores()"]
    I --> J[Dashboard]
```

## 2. The coach loop — only step 1 scores

```mermaid
flowchart TD
    S1["1 · Fresh question, asked cold<br/><b>no hint, no explanation</b>"] --> S2
    S2["2 · How sure are you?<br/><b>before the answer is shown</b>"] --> REC
    REC[["record attempt<br/>← the only scored event"]] --> S3
    S3["3 · Explain the concept aloud<br/>not 'why did you pick B'"] --> S4
    S4["4 · Contrast pair<br/>one detail changed — what changes?"] --> S5
    S5["5 · Revise what you said"] --> S6
    S6["6 · <b>Only now</b> the app states the rule"] --> S7
    S7["7 · Personal guide from their own mistakes"] --> END([done])

    style REC fill:#2d6a4f,color:#fff
    style S3 fill:#40404a,color:#fff
    style S4 fill:#40404a,color:#fff
    style S5 fill:#40404a,color:#fff
    style S6 fill:#40404a,color:#fff
    style S7 fill:#40404a,color:#fff
```

Grey steps are **teaching and are never graded**. The agent asks once, then stays quiet — Bisra excluded studies where a researcher kept nudging, because constant prompting turns reflection into rambling.

Voice only. No text box exists on any screen showing a live question — that is the enforcement mechanism, not a preference.

## 3. Item generation — the safety gate

```mermaid
flowchart TD
    A[Need an item for topic T at DOK d] --> B[Retrieve spans from corpus<br/>AAMC outline + OpenStax]
    B --> C{spans found?}
    C -->|no| X1[["409 ungrounded<br/>abstain, do not generate"]]
    C -->|yes| D[Generate item<br/>grounded on retrieved spans]
    D --> E{"Is the correct answer's<br/>supporting span present<br/>in the retrieved text?"}
    E -->|no| X2[["drop — no span, no ship"]]
    E -->|yes| F{distractor check<br/>any dud options?}
    F -->|fail| X2
    F -->|pass| G[Attach source_id + span]
    G --> H[Ship to student]

    style X1 fill:#7f1d1d,color:#fff
    style X2 fill:#7f1d1d,color:#fff
```

**Banned:** asking an LLM whether its own item is good. The Glianorex result — models scoring 64% on questions about a fictional organ while physicians scored 27% — settles it. Generator and checker share the blind spot.

The gate is a **safety gate, not a quality dial**. Kämmer: a list containing the answer → 75%; no list → 49%; a list *missing* the answer → 43%, worse than no help at all. An ungrounded item is worse than abstaining.

## 4. Scoring pipeline and the give-up rule

```mermaid
flowchart TD
    RL[(revlog<br/>student's own reviews)] --> M[Memory: FSRS retrievability<br/>per topic, outline-weighted]
    AT[(Speedrun::Attempt notes<br/>held-out items only)] --> P[Performance: logistic model<br/>mastery · DOK · coverage · latency · confidence]
    CM[(coverage map<br/>vs AAMC outline)] --> P
    M --> P
    P --> R[Readiness: → scaled 118–132<br/>per section]

    M --> G1{"≥200 reviews<br/>≥30 cards?"}
    P --> G2{"≥20 attempts<br/>≥8 topics?"}
    R --> G3{"memory ✓ perf ✓<br/>coverage ≥50%?"}

    G1 -->|no| A1[["abstain +<br/>what would fix it"]]
    G2 -->|no| A2[["abstain +<br/>what would fix it"]]
    G3 -->|no| A3[["abstain +<br/>what would fix it"]]
    G1 -->|yes| O1[Memory + range]
    G2 -->|yes| O2[Performance + range]
    G3 -->|yes| O3[Readiness + range<br/>never narrower than ±2]

    CARS[(CARS)] --> A4[["always abstains —<br/>no knowledge to model"]]

    style A1 fill:#78350f,color:#fff
    style A2 fill:#78350f,color:#fff
    style A3 fill:#78350f,color:#fff
    style A4 fill:#78350f,color:#fff
```

Abstention is the default state. A score appears only when it is earned, and every abstention names the specific thing that would resolve it.

## 5. Sync and conflict

```mermaid
sequenceDiagram
    participant D as Desktop
    participant S as anki --syncserver
    participant P as Android

    Note over D,P: both offline
    D->>D: 10 reviews + 3 Attempt notes
    P->>P: 10 different reviews + 2 Attempt notes
    Note over D,P: reconnect
    D->>S: push (USN-tagged)
    P->>S: push (USN-tagged)
    S-->>D: merged
    S-->>P: merged
    Note over D,P: all 20 reviews land once.<br/>all 5 attempt notes survive.

    Note over D,P: conflict case — same card, both offline
    D->>S: card X, mod=T1
    P->>S: card X, mod=T2 (T2 > T1)
    S-->>S: both revlog entries retained
    S-->>S: card state ← higher mod (T2)
    S-->>D: card X @ T2

    Note over P: clock-skewed device
    P->>S: connect, mod skew > tolerance
    S-->>P: refuse, prompt resync
```

Rule written down before the test runs, per §8.

## 6. Degradation

```mermaid
flowchart LR
    A{agent service<br/>reachable?} -->|no| B[ai_enabled := false]
    A -->|yes| C{returns garbage<br/>or ungrounded?}
    C -->|yes| B
    C -->|no| D[full coach]
    B --> E["Memory score ✅<br/>Coverage map ✅<br/>Dashboard ✅<br/>Rust queries ✅<br/>Coach ❌ — says so plainly"]
```

Performance and readiness keep whatever they had, timestamped and marked stale. They do not silently drift.
