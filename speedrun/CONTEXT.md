# Speedrun

Measurement layered on top of Anki. Speedrun reads a student's review history as
evidence about what they know, and reports how ready they are for the MCAT —
abstaining whenever the evidence does not support a number.

## Language

### What we measure

**Memory**:
How likely the student is to recall a fact right now, derived from their own
review history. Answers "do they still have it?"
_Avoid_: retention, recall score, knowledge

**Performance**:
How well the student answers exam-style questions they have never seen, with no
cue attached. Answers "does it survive a real question?"
_Avoid_: accuracy, test score, practice score

**Readiness**:
The scaled section score the student would plausibly earn today. Answers "what
would happen if they sat the exam?"
_Avoid_: prediction, projection, estimate

**Score**:
Any one of the three above. Always carries a range; never blended with the
others into a single number.

**Range**:
The interval reported with every score. Never narrower than the AAMC's own ±2
scaled points.
_Avoid_: confidence interval, error bar, margin

### Abstaining

**Give-up rule**:
The evidence threshold a score must clear before it may be reported at all.
Below it the score is withheld.
_Avoid_: minimum, cutoff, gate

**Abstention**:
The state of a score whose give-up rule has not been met. It is the default
state, and it always names the specific thing that would resolve it.
_Avoid_: null, unavailable, N/A, insufficient data

**Coverage**:
The share of an exam section's official outline the student has actually
studied. Owning cards about a topic is not coverage; having reviewed them is.
_Avoid_: progress, completion, breadth

### The exam

**Section**:
One of the MCAT's four scored parts — Chem/Phys, Bio/Biochem, Psych/Soc, CARS.
Every score is reported per section, never as one overall figure.

**Topic**:
One AAMC content category — the lettered unit of the Outline, such as 1A or 5C.
The unit every card is attributed to and every score is broken down by. There
are 31 in total: 9 in Bio/Biochem, 10 in Chem/Phys, 12 in Psych/Soc.
_Avoid_: subject, content area, tag, subdeck, foundational concept

**Outline**:
The AAMC's published list of what each section tests. The external authority
coverage is measured against — not something we author.
_Avoid_: syllabus, curriculum, blueprint

**Crosswalk**:
The mapping from the labels a student's deck already uses to Outline topics.
Speedrun's own artifact, held apart from the collection, with a stated error
rate — never written into the student's notes.
_Avoid_: tagging, mapping, classification

**Unmapped card**:
A card the Crosswalk cannot attribute to a Topic. Counted and reported, never
silently dropped — a measurement whose denominator is hidden is the kind of
number this project exists to distrust.

### The student's data

**Collection**:
The student's own Anki deck, review history included. Speedrun treats it as a
sensor: read continuously, never written to.
_Avoid_: deck, database, library

**Sensor**:
The stance Speedrun takes toward the collection. We never author or modify the
student's notes, cards, or review history — our own records sit beside it,
namespaced and excluded from every measurement.

**Review**:
One grading of one card by the student in the normal course of study. The raw
evidence Memory is computed from.
_Avoid_: rep, answer, card view

**Attempt**:
One response to a held-out item. Speedrun's own record, stored separately from
the collection's cards and excluded from every measurement.
_Avoid_: review, answer, response

### Questions

**Held-out item**:
A new exam-style question the student has never seen, never derived from their
own cards, and never hinted or explained before it is attempted. The only thing
Performance is computed from. Its text never enters the Collection.
_Avoid_: test question, quiz item, practice question

**Reworded card**:
One of the student's own cards restated in different words. Used solely to test
whether Performance is merely copying Memory, and never counted toward any
score.
_Avoid_: paraphrase, variant, rephrasing

**Leakage**:
Any path by which a held-out item, or its answer, reaches the student or a
model before the attempt. A score contaminated by leakage is void.

**Coach loop**:
The spoken sequence run after a review round: cold question, confidence,
explanation aloud, contrast pair, revision, then the rule. Only the first step
is scored; the rest teach and are never graded.
_Avoid_: tutor, quiz, session

**Generation gate**:
The rule that a generated item may only be shown if the supporting text for its
correct answer was retrieved from a real source and matched against it. An item
that fails the gate is dropped, never shown and never repaired by asking a model
to check its own work.
_Avoid_: validation, filter, quality check

**Yield**:
Usable items produced per hundred generation attempts — items that survived the
Generation gate. How retrieval quality is judged, since every candidate faces the
same gate.

**Contrast pair**:
The same question with exactly one detail changed, presented so the student must
say what that change does. Speedrun's replacement for interleaving.
