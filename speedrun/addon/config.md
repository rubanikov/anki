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

### `coach_enabled`

Run the spoken coach loop after a review round. Turn it off and reviews, Memory,
coverage, the dashboard and every abstention carry on exactly as before — the
only thing that stops is the loop. Nothing that produces a number consults this
setting.

### `ai_enabled`

The wider switch. Off means no generation **and** no coach, because the coach
has nothing to ask without generated items. Memory, coverage and the dashboard
are computed by the Rust engine, which never sees this setting, so they are
unaffected.

Off is also what Speedrun falls back to on its own when the agent service does
not answer. There is one disabled state, not two, so the degraded path and the
chosen path are the same path.

### `agent_url`

Where the agent service is expected to answer. Speedrun probes it with a short
timeout and treats **anything** other than a healthy response — refused
connection, timeout, an error status, a page from something else on that port —
as `ai_enabled = false`. Blank means no service configured, which is the same
thing.

It is never probed when `ai_enabled` is false: a switched-off feature does not
open a socket.
