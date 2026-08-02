# The ablation measures delayed retention, not same-session performance

The three-build comparison runs its intervention blocks early and its retention
test roughly fifteen hours later, rather than measuring immediately after each
block. The effects the product rests on are delayed-retention effects, and the
desirable-difficulties literature predicts that effortful interventions often
depress *immediate* performance while improving later retention. A same-session
ablation would therefore produce a number that is consistent with the thesis
whether it goes up or down — and it would commit, in our own headline
experiment, exactly the "measured while the app is helping" error the product
exists to attack.

## Consequences

- The blocks have to run on whatever version of the app works at the time, well
  before anything is polished. This is the entire cost of the decision and the
  reason it has to be made in advance.
- **Timing, corrected during ticket planning:** the blocks were first planned for
  H+3, but they cannot start before the corpus, the generation gate and a usable
  P-set exist — realistically H+5 to H+6, putting the retention test near H+18
  and the delay at roughly twelve hours rather than fifteen. The design survives;
  twelve hours is still a delayed measure. But the schedule is now the binding
  constraint, and below about eight hours the measure stops being meaningfully
  delayed at all. Everything else should be sequenced around reaching the blocks
  early.
- The design is within-subject and counterbalanced across three conditions —
  full coach loop, coach off with scores only, and plain Anki — on matched
  topics, with the retention test drawn from held-out items seen in no block.
- **The main number is Δ_loop = A − B**, coach on versus coach off, because it
  changes exactly one thing. A − C compares the whole app against plain Anki and
  could come out positive on the strength of the dashboard alone, attributing
  nothing; it is reported as a named secondary, never on its own.
- **This experiment does not test SpikyPOV 2.** That POV claims voice is what
  makes copying physically impossible; every arm involving the loop involves
  speaking, so voice sits on the same side of every comparison. Testing it would
  need a spoken-versus-typed arm, which nobody has ever run and which we are not
  running either — a fourth arm at n = 1–3 would make the result less
  interpretable, not more. POV 2 is falsified instead by the no-text-input
  enforcement test and by speak-rate, and the gap is stated in the write-up.
- The main number, its predicted direction, and what would falsify it are
  written down and timestamped before the first block runs.
- Immediate post-block accuracy is recorded as a manipulation check, with the
  prediction stated in advance that the coach arm will be flat or lower. Stating
  it beforehand is what stops it from becoming an excuse afterwards.
- n will be one to three and the interval will cross zero. The result is
  reported as "cannot distinguish," with the interval and the n that would be
  needed, rather than dressed up.
