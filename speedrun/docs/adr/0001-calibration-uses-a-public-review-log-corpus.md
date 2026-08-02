# Memory calibration is measured on a public review-log corpus, not on our own reviews

Calibration — the claim that a Memory score of 0.80 is right about 80% of the
time — has to be proven on real reviews held back from the model. Our own
collection has none, and a single learner studying for a few hours yields a few
hundred reviews at most: enough to run the chart, not enough for anyone to
believe it. We therefore measure calibration on
[anki-revlogs-10k](https://huggingface.co/datasets/open-spaced-repetition/anki-revlogs-10k)
(~727M real reviews from 10,000 real Anki users, the corpus FSRS itself is
benchmarked on), and use our own studying only to make the give-up rule visibly
fire on a live collection.

## Considered options

- **Our own reviews only.** Honest but underpowered; the calibration claim would
  rest on one learner and a few hundred reviews.
- **A donated collection from a real premed.** Strongest content-wise, but the
  timing is outside our control and it may simply never arrive.
- **Simulated review logs.** Rejected outright. A calibration chart built on
  invented reviews is a guess dressed as a measurement.

## Consequences

- The corpus carries no card text and no topic tags, so it can validate the
  Memory model but says nothing about MCAT topics. Coverage, Performance and
  Readiness cannot be evidenced from it, and the calibration script runs outside
  the collection rather than through `SpeedrunService`.
- Its licence permits individual research use but forbids public
  redistribution. The raw data must never enter the public fork; the leakage
  check has to demonstrate that, not assert it.
- The live demo still needs a genuinely studied collection so that one section
  crosses its threshold while the others abstain — which is the give-up rule
  doing visible work on real data.
