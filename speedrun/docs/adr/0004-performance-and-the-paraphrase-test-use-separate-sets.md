# Performance and the paraphrase test use separate item sets

Performance is scored only on held-out items: new exam-style questions generated
from the corpus, never derived from the student's own cards. The paraphrase test
uses a second, separate set of the student's cards restated in different words,
and those rewordings never count toward any score. The two were originally one
set, which made Performance a score on paraphrases of cards the student had
already studied — precisely the failure the paraphrase test exists to detect, so
the test could not fail.

## Consequences

- The paraphrase test becomes a real three-point measurement on one student:
  card recall, then reworded-card accuracy, then new-item accuracy. If the three
  collapse to a single number, the thesis is falsified and the test says so.
- Held-out item text is stored outside the collection. Putting it in notes would
  let the student read the entire set from the card browser, and would sync
  question text to a phone that never asks questions.
- Attempts still live in the collection so they sync, but carry only item id,
  topic, confidence, result and timing — never the stem or the answer.
- Generating enough held-out items to clear one section's threshold is real
  work, and their quality has to be evidenced rather than asserted.
