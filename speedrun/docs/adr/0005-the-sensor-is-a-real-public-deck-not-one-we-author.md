# The sensor is a real public deck, and unresolvable cards are reported rather than guessed

Speedrun measures a real learner's collection, so the demo studies a real public
MCAT deck (MileDown) rather than one we author with correct topic tags baked in.
A purpose-built deck would make every downstream number resolve perfectly and
make all of them meaningless — a deck we wrote is not a years-long record of
someone's learning, and the Sensor argument is the product.

## Consequences

- The Crosswalk keys on **deck path and tags together**, not tags alone. A deck
  organised by subject subdeck carries no topic tags at all, and a tags-only
  lookup would mark every card unmapped.
- Where the deck genuinely cannot distinguish two content categories inside one
  subdeck, those cards are reported as Unmapped cards. Assigning them to a
  plausible category would inflate coverage invisibly, which is the failure mode
  this project exists to refuse.
- The deck is the student's, never ours: it is not redistributed and never
  committed to the public fork.
- The choice is gated on inspecting the deck's actual tag list and counting how
  many of the 31 content categories resolve. Below roughly fifteen, MileDown is
  too coarse and the AnKing MCAT deck is taken instead despite its signup cost.
