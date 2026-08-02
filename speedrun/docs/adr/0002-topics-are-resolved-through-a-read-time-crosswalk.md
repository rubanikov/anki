# Topics are resolved through a read-time crosswalk, not by tagging the student's notes

Speedrun attributes every card to an Outline topic, and the shipped backend
derives that topic from a note tag shaped `<prefix>::<SECTION>::<topic>`. No
real MCAT deck uses our section codes, so making a real collection measurable
would mean writing our tags onto the student's notes — which modifies their
notes and syncs to their devices, breaking the Sensor rule the whole project
rests on. Instead the backend resolves each card's topic at read time through a
Crosswalk held in collection config, so the student's notes are never touched.

## Considered options

- **Adopt the deck's existing tags directly** by pointing `tag_prefix` at them.
  Free only if the deck's tags already carry our section codes in the second
  position, which no real deck does — so in practice it collapses into
  rewriting the student's tags.
- **Write `mcat::` tags onto the student's notes.** Gives the cleanest topic
  ids and needs no new code, but it is exactly the mutation the Sensor rule
  forbids, and it propagates to the student's phone.
- **Resolve the crosswalk in the desktop add-on.** Rejected because Android
  must produce identical scores offline; any mapping done in Python is
  unreachable from the phone.

## Consequences

- The crosswalk must live in Rust, beside the existing mastery query, so both
  platforms resolve topics identically without network access.
- The crosswalk is a data artifact with its own error rate. That error is
  reported alongside mastery rather than absorbed into it.
- Cards the crosswalk cannot place become Unmapped cards and are counted in the
  response. Until now they were skipped silently, which left the denominator of
  every mastery figure unstated.
