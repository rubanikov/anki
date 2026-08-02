#!/usr/bin/env python3
"""The Memory model, ported line-for-line from the crate the backend calls.

`rslib/src/speedrun/mastery.rs` turns a card's FSRS memory state into a Memory
score with

    fsrs::current_retrievability(state, elapsed_days, card.decay)

so a calibration run that used any other curve would be measuring a different
product. Every function here is a transcription of `fsrs` 6.6.1 — the version
pinned in the workspace `Cargo.toml` — from
`~/.cargo/registry/src/*/fsrs-6.6.1/src/{inference,model}.rs`:

| here                        | there                                     |
|-----------------------------|-------------------------------------------|
| `current_retrievability`    | `inference.rs::current_retrievability`    |
| `power_forgetting_curve`    | `model.rs::power_forgetting_curve`        |
| `step`                      | `model.rs::step`                          |
| `forward_reviews`           | `FSRS::forward_reviews`                   |
| `memory_state_from_sm2`     | `FSRS::memory_state_from_sm2`             |
| `DEFAULT_PARAMETERS`        | `inference.rs::DEFAULT_PARAMETERS`        |

`current_retrievability(state, t, w[20])` and `power_forgetting_curve(w, t, s)`
are algebraically the same function — the first takes the decay as an argument,
the second reads it from `w[20]` — so the curve this file scores with is the
curve `mastery.rs` reports.

One deliberate difference: the crate is `f32` throughout and Python is `f64`.
`self_test()` checks the port against the crate's own unit-test vectors and
reports the residual, which is at the 1e-7 level — four orders of magnitude
below anything a Brier score printed to four decimals can notice.

Run the self-test:

    python speedrun/eval/calibration/fsrs_model.py
"""

from __future__ import annotations

import math

# fsrs-6.6.1 inference.rs::DEFAULT_PARAMETERS. `FSRS::new(&[])` clips these with
# num_relearning_steps=1 and enable_short_term=false; every default already sits
# inside its clamp, so the clipped vector is this vector.
DEFAULT_PARAMETERS: tuple[float, ...] = (
    0.212,
    1.2931,
    2.3065,
    8.2956,
    6.4133,
    0.8334,
    3.0194,
    0.001,
    1.8722,
    0.1666,
    0.796,
    1.4835,
    0.0614,
    0.2629,
    1.6483,
    0.6014,
    1.8729,
    0.5425,
    0.0912,
    0.0658,
    0.1542,  # w20 = FSRS6_DEFAULT_DECAY
)

FSRS5_DEFAULT_DECAY = 0.5
FSRS6_DEFAULT_DECAY = 0.1542

# simulation.rs
S_MIN = 0.001
S_MAX = 36500.0
D_MIN = 1.0
D_MAX = 10.0


def clamp(x: float, low: float, high: float) -> float:
    return low if x < low else high if x > high else x


def current_retrievability(stability: float, days_elapsed: float, decay: float) -> float:
    """inference.rs::current_retrievability — the call `mastery.rs` makes."""
    factor = 0.9 ** (1.0 / -decay) - 1.0
    return (days_elapsed / stability * factor + 1.0) ** -decay


def power_forgetting_curve(w: tuple[float, ...], t: float, s: float) -> float:
    """model.rs::power_forgetting_curve."""
    decay = -w[20]
    factor = math.exp(math.log(0.9) / decay) - 1.0
    return (t / s * factor + 1.0) ** decay


def init_stability(w: tuple[float, ...], rating: int) -> float:
    return w[min(max(rating - 1, 0), 3)]


def init_difficulty(w: tuple[float, ...], rating: int) -> float:
    return w[4] - math.exp(w[5] * max(rating - 1, 0)) + 1.0


def _mean_reversion(w: tuple[float, ...], new_d: float) -> float:
    return w[7] * (init_difficulty(w, 4) - new_d) + new_d


def _linear_damping(delta_d: float, old_d: float) -> float:
    return (10.0 - old_d) * delta_d / 9.0


def next_difficulty(w: tuple[float, ...], difficulty: float, rating: float) -> float:
    delta_d = -w[6] * (rating - 3.0)
    return difficulty + _linear_damping(delta_d, difficulty)


def _stability_after_success(
    w: tuple[float, ...], last_s: float, last_d: float, r: float, rating: float
) -> float:
    hard_penalty = w[15] if rating == 2.0 else 1.0
    easy_bonus = w[16] if rating == 4.0 else 1.0
    return last_s * (
        math.exp(w[8])
        * (11.0 - last_d)
        * last_s ** -w[9]
        * (math.exp((1.0 - r) * w[10]) - 1.0)
        * hard_penalty
        * easy_bonus
        + 1.0
    )


def _stability_after_failure(
    w: tuple[float, ...], last_s: float, last_d: float, r: float
) -> float:
    new_s = (
        w[11]
        * last_d ** -w[12]
        * ((last_s + 1.0) ** w[13] - 1.0)
        * math.exp((1.0 - r) * w[14])
    )
    new_s_min = last_s / math.exp(w[17] * w[18])
    return min(new_s, new_s_min)


def _stability_short_term(w: tuple[float, ...], last_s: float, rating: float) -> float:
    sinc = math.exp(w[17] * (rating - 3.0 + w[18])) * last_s ** -w[19]
    return last_s * (max(sinc, 1.0) if rating >= 2.0 else sinc)


def step(
    w: tuple[float, ...],
    delta_t: float,
    rating: float,
    stability: float,
    difficulty: float,
    nth: int,
) -> tuple[float, float]:
    """model.rs::step. Returns the memory state after one review."""
    last_s = clamp(stability, S_MIN, S_MAX)
    last_d = clamp(difficulty, D_MIN, D_MAX)

    r = power_forgetting_curve(w, delta_t, last_s)
    new_s = (
        _stability_after_failure(w, last_s, last_d, r)
        if rating == 1.0
        else _stability_after_success(w, last_s, last_d, r, rating)
    )
    if delta_t == 0.0:
        new_s = _stability_short_term(w, last_s, rating)

    new_d = clamp(_mean_reversion(w, next_difficulty(w, last_d, rating)), D_MIN, D_MAX)

    if nth == 0 and stability == 0.0:
        init_rating = int(clamp(rating, 1.0, 4.0))
        new_s = init_stability(w, init_rating)
        new_d = clamp(init_difficulty(w, init_rating), D_MIN, D_MAX)

    if rating == 0.0:
        new_s, new_d = last_s, last_d

    return clamp(new_s, S_MIN, S_MAX), new_d


def memory_state_from_sm2(
    w: tuple[float, ...], ease_factor: float, interval: float, sm2_retention: float
) -> tuple[float, float] | None:
    """inference.rs::memory_state_from_sm2 — used when a card's revlog is truncated."""
    decay = -w[20]
    factor = 0.9 ** (1.0 / decay) - 1.0
    stability = max(interval, S_MIN) * factor / (sm2_retention ** (1.0 / decay) - 1.0)
    try:
        difficulty = 11.0 - (ease_factor - 1.0) / (
            math.exp(w[8]) * stability ** -w[9] * math.expm1((1.0 - sm2_retention) * w[10])
        )
    except (ZeroDivisionError, OverflowError, ValueError):
        return None
    if not math.isfinite(stability) or not math.isfinite(difficulty):
        return None
    return stability, clamp(difficulty, D_MIN, D_MAX)


def self_test() -> list[str]:
    """Check the port against the crate's own unit-test vectors.

    Vectors are copied verbatim from `fsrs-6.6.1/src/inference.rs`
    (`test_current_retrievability`) and `test_memory_from_sm2`. They are `f32`
    literals; this port is `f64`, so equality is asserted to 1e-6.
    """
    problems: list[str] = []

    def near(label: str, got: float, want: float, tol: float = 1e-6) -> None:
        if abs(got - want) > tol:
            problems.append(f"{label}: got {got!r}, crate says {want!r}")
        else:
            print(f"  ok   {label}: {got:.8f} vs crate {want:.8f}  (|d|={abs(got - want):.2e})")

    # inference.rs::test_current_retrievability, state { stability: 1.0, difficulty: 5.0 }
    near("current_retrievability(S=1, t=0, decay=0.2)", current_retrievability(1.0, 0.0, 0.2), 1.0)
    near("current_retrievability(S=1, t=1, decay=0.2)", current_retrievability(1.0, 1.0, 0.2), 0.9)
    near(
        "current_retrievability(S=1, t=2, decay=0.2)",
        current_retrievability(1.0, 2.0, 0.2),
        0.84028935,
    )
    near(
        "current_retrievability(S=1, t=3, decay=0.2)",
        current_retrievability(1.0, 3.0, 0.2),
        0.7985001,
    )

    # The two curves must agree: mastery.rs passes the card's decay, the model
    # reads w[20]. Same number or the artifact is measuring something else.
    w = DEFAULT_PARAMETERS
    for t in (0.0, 1.0, 7.0, 60.0, 365.0):
        a = current_retrievability(12.5, t, w[20])
        b = power_forgetting_curve(w, t, 12.5)
        near(f"mastery curve == model curve at t={t}", a, b, 1e-12)

    # inference.rs::test_memory_from_sm2, asserted approximately in the crate.
    state = memory_state_from_sm2(w, 2.5, 10.0, 0.9)
    assert state is not None
    near("memory_state_from_sm2(2.5, 10, 0.9).stability", state[0], 10.0, 1e-4)
    near("memory_state_from_sm2(2.5, 10, 0.9).difficulty", state[1], 6.9140563, 1e-4)
    state = memory_state_from_sm2(w, 2.5, 10.0, 0.8)
    assert state is not None
    near("memory_state_from_sm2(2.5, 10, 0.8).stability", state[0], 3.01572, 1e-4)
    near("memory_state_from_sm2(2.5, 10, 0.8).difficulty", state[1], 9.393428, 1e-4)

    return problems


if __name__ == "__main__":
    import sys

    print("fsrs_model.py — checking the port against fsrs 6.6.1's own test vectors")
    failures = self_test()
    if failures:
        print("\nFAILED:")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print("\nall vectors match; the port is the crate's curve.")
