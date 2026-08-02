### `tag_prefix`

Root of the tag namespace your deck already uses, e.g. `mcat`. A card is
attributed to the first tag it carries under `<tag_prefix>::<section>::`.
Speedrun never writes tags onto your notes; it only reads the ones already
there.

### `sections`

One entry per MCAT section. `outline_topic_count` is how many content
categories the AAMC's published Outline lists for that section — 10 for
Chem/Phys, 9 for Bio/Biochem, 12 for Psych/Soc. Coverage is measured against
it.

Setting it to `0` means "no Outline loaded", and readiness will abstain and say
so. That is the intended failure mode: getting this number wrong withholds a
score, it never invents one.

CARS is listed with `0` because the AAMC states there is no content knowledge to
model there, and the backend refuses to run the knowledge machinery on it at
all.

### `hide_topic_label_during_question`

Withhold the Topic label while a question is on screen, and restore it with the
answer. The label names the content category, which gives away the approach.
Turn it off only if you are not being measured.

### `show_topic_breakdown`

Include the per-Topic table under each section. Turning it off skips one backend
read per section.
