# The sensor is a real public deck, and unresolvable cards are reported rather than guessed

Speedrun measures a real learner's collection, so the demo studies a real public
MCAT deck (MileDown) rather than one we author with correct topic tags baked in.
A purpose-built deck would make every downstream number resolve perfectly and
make all of them meaningless — a deck we wrote is not a years-long record of
someone's learning, and the Sensor argument is the product.

## Consequences

- The Crosswalk keys on **tags first, with deck path only as a tiebreak** —
  corrected after measuring the actual deck. The worry that drove the original
  `(deck path, tags)` compound key was that a subject-subdeck deck would carry no
  topic tags; MileDown turns out to carry 182 hierarchical tags with every card
  tagged, against only 7 subject subdecks, so the tags carry all the granularity
  and the subdecks carry almost none. More decisively, 26 of those tags straddle
  several subdecks — `Biology::Genetics` appears under *Biology*, *Biochemistry*
  and *Behavioral* — and in every such case the tag is right and the subdeck is
  the accident of where the author filed it. Treating the two as equal halves of
  a compound key would let the accident outvote the signal.
- Where the deck genuinely cannot distinguish two content categories inside one
  subdeck, those cards are reported as Unmapped cards. Assigning them to a
  plausible category would inflate coverage invisibly, which is the failure mode
  this project exists to refuse.
- The deck is the student's, never ours: it is not redistributed and never
  committed to the public fork.
- The choice is gated on inspecting the deck's actual tag list and counting how
  many of the 31 content categories resolve. Below roughly fifteen, MileDown is
  too coarse and the AnKing MCAT deck is taken instead despite its signup cost.
  **Measured: 29 of 31 resolve** — Bio/Biochem 9/9, Chem/Phys 10/10, Psych/Soc
  10/12. The two failures are 9A and 9B, which a single 61-card tag splits
  between with nothing available to separate them; those cards are Unmapped
  rather than guessed. MileDown stands, and AnKing would have bought at most two
  more categories.
- A pristine shared deck has an **empty review log**. It is a valid Crosswalk
  input but is not a Collection in the sense Memory needs — nothing can be
  measured from it until someone has actually studied it.
