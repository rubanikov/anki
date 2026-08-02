# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Record what Anki's scheduler did, under three states of this add-on.

This is the instrument behind the largest claim Speedrun makes about itself:
*disable the add-on and Anki behaves exactly as it did before.* An add-on cannot
credibly test that about itself in its own process, because by the time the test
is running the add-on's directory is already on ``sys.path`` and its modules are
already imported. So this file is a **script**, run in a fresh interpreter, once
per arm:

``absent``
    Nothing of Speedrun is on ``sys.path``, nothing of Speedrun is imported.
    Stock Anki driving a collection.

``disabled``
    The add-on is installed — a real copy of ``speedrun/addon`` sits in an
    ``addons21`` directory that is on ``sys.path`` — and is never imported. That
    is precisely what Anki does with a disabled add-on: ``AddonManager.__init__``
    puts the add-ons folder on ``sys.path`` unconditionally, and ``loadAddons``
    skips any add-on whose ``meta.json`` says ``disabled``. The arm asserts
    ``speedrun`` is absent from ``sys.modules`` when it finishes.

``enabled``
    The add-on is installed *and* loaded, and every read it performs — the whole
    dashboard gather, and the Topic redaction on both sides of every card — runs
    interleaved with the review session. This arm is not required by the ticket;
    it is here because the interesting failure is not "a disabled add-on changed
    scheduling", it is "an enabled one did".

Comparing the three requires the runs to differ in nothing but the arm, which
takes some care:

- **One collection, copied.** The interval fuzz Anki applies is seeded from the
  card id and the rep count (``rslib/src/scheduler/answering/mod.rs``,
  ``get_fuzz_seed_for_id_and_reps``). Card ids are creation timestamps, so two
  collections built a second apart would legitimately schedule differently. Each
  arm therefore runs against a byte copy of one collection built once.
- **A fixed rating sequence**, and a fixed ``milliseconds_taken``, so nothing
  about the answer input varies between arms.
- **No wall clock in the compared trace.** An intraday learning card's ``due``
  is *the moment of answering* plus a delay; runs happen seconds apart, so the
  moment differs by construction and cannot be compared. The delay itself is
  fully compared, twice over: as ``scheduled_secs`` in the states the scheduler
  offered before the answer, and as ``learning_delays`` measured from the card
  afterwards. See ``OFF_SWITCHES.md`` for the exact list of what that leaves
  unasserted.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from typing import Any

ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TAG_PREFIX = "mcat"

#: Topic tags spread over three sections, plus untagged notes so the Unmapped
#: count is non-zero and the add-on has something real to do in the enabled arm.
NOTE_TAGS = [
    "mcat::BB::amino_acids",
    "mcat::BB::enzymes",
    "mcat::CP::thermodynamics",
    "mcat::CP::kinetics",
    "mcat::PS::learning_and_memory",
    "",
]

#: Fixed, and deliberately varied: Again drives cards into relearning, Easy
#: graduates them, Hard and Good move ease factors in opposite directions. A
#: sequence of all-Good would exercise one branch of the scheduler.
RATINGS = [3, 1, 2, 3, 4, 3, 1, 3, 2, 4, 3, 3, 1, 3, 4, 2, 3, 3, 4, 1]

STEPS = 20

#: Card.type / Card.queue values whose ``due`` is an epoch second rather than a
#: day number — i.e. the wall-clock ones.
INTRADAY_TYPES = (1, 3)  # CARD_TYPE_LRN, CARD_TYPE_RELEARNING

MILLISECONDS_TAKEN = 1500


# ---------------------------------------------------------------------------
# Building the collection
# ---------------------------------------------------------------------------


def build(path: str) -> None:
    """A collection with genuine review history, built once and then copied.

    The history is real: six cards are answered through the scheduler, which
    writes revlog entries and card states the same way a student would, and are
    then pulled forward with ``set_due_date`` so they are due again today. That
    leaves a queue with all three kinds in it — new, intraday learning and
    review — which is what makes queue *order* a meaningful thing to compare.
    """
    from anki.collection import Collection

    col = Collection(path)
    notetype = col.models.by_name("Basic")
    for index in range(18):
        note = col.new_note(notetype)
        note["Front"] = f"question {index}"
        note["Back"] = f"answer {index}"
        tag = NOTE_TAGS[index % len(NOTE_TAGS)]
        if tag:
            note.tags = [tag]
        col.add_note(note, 1)

    conf = col.decks.config_dict_for_deck_id(1)
    conf["new"]["perDay"] = 50
    conf["rev"]["perDay"] = 200
    col.decks.update_config(conf)

    card_ids = sorted(col.find_cards("deck:Default"))
    for card_id in card_ids[:6]:
        states = col._backend.get_scheduling_states(card_id)
        col.sched.answer_card(_answer(card_id, states, 4))
    col.sched.set_due_date(card_ids[:6], "0")
    col.close()


def _answer(card_id: int, states: Any, rating: int) -> Any:
    from anki.scheduler.v3 import CardAnswer

    new_state = {1: states.again, 2: states.hard, 3: states.good, 4: states.easy}[
        rating
    ]
    return CardAnswer(
        card_id=card_id,
        current_state=states.current,
        new_state=new_state,
        rating=rating,
        answered_at_millis=int(time.time() * 1000),
        milliseconds_taken=MILLISECONDS_TAKEN,
    )


# ---------------------------------------------------------------------------
# Recording a state
# ---------------------------------------------------------------------------


def _state_summary(state: Any) -> list[Any]:
    """Everything the scheduler is offering for one button.

    Relative by construction — days and seconds from now, never a timestamp —
    which is what makes it comparable across runs that happened at different
    moments.
    """
    normal = state.normal
    kind = normal.WhichOneof("kind")
    if kind == "new":
        return ["new", normal.new.position]
    if kind == "learning":
        learning = normal.learning
        return ["learning", learning.remaining_steps, learning.scheduled_secs]
    if kind == "review":
        review = normal.review
        return [
            "review",
            review.scheduled_days,
            round(review.ease_factor, 6),
            review.lapses,
            review.leeched,
        ]
    if kind == "relearning":
        relearning = normal.relearning
        return [
            "relearning",
            relearning.learning.remaining_steps,
            relearning.learning.scheduled_secs,
            relearning.review.scheduled_days,
            round(relearning.review.ease_factor, 6),
            relearning.review.lapses,
        ]
    return [kind or "filtered"]


def _states_summary(states: Any) -> dict[str, list[Any]]:
    return {
        button: _state_summary(getattr(states, button))
        for button in ("again", "hard", "good", "easy")
    }


def _card_summary(card: Any) -> dict[str, Any]:
    """The card row after the answer, minus the wall clock.

    ``due`` is included for new and review cards, where it is a queue position
    or a day number and therefore stable. It is omitted for learning and
    relearning cards, where it is an epoch second — see the module docstring.
    """
    row = {
        "type": card.type,
        "queue": card.queue,
        "ivl": card.ivl,
        "factor": card.factor,
        "reps": card.reps,
        "lapses": card.lapses,
        "left": card.left,
        "odue": card.odue,
        "odid": card.odid,
        "flags": card.flags,
    }
    row["due"] = None if card.type in INTRADAY_TYPES else card.due
    return row


def _last_revlog(col: Any, card_id: int) -> list[Any]:
    """The scheduling decision as Anki recorded it, for the statistics to use.

    ``id`` and ``time`` are excluded: the first is the answering timestamp, and
    the second is how long the answer took, which this script fixes anyway.
    """
    return list(
        col.db.first(
            "select ease, ivl, lastIvl, factor, type from revlog "
            "where cid = ? order by id desc limit 1",
            card_id,
        )
        or []
    )


# ---------------------------------------------------------------------------
# The arms
# ---------------------------------------------------------------------------


def install_addon(addons_root: str) -> None:
    """Copy the add-on into an ``addons21`` directory and put it on the path.

    A copy rather than a symlink, so the arm does not depend on the developer's
    profile or on junction support. The directory name is ``speedrun`` because
    that is the module name Anki would import.
    """
    target = os.path.join(addons_root, "speedrun")
    if not os.path.exists(target):
        shutil.copytree(
            ADDON_DIR, target, ignore=shutil.ignore_patterns("__pycache__", "tests")
        )
    # Exactly what AddonManager.__init__ does, and it does it whether or not any
    # given add-on is enabled.
    sys.path.insert(0, addons_root)


class _AddonUnderTest:
    """The add-on doing everything it does to a collection, or doing nothing."""

    def __init__(self, loaded: bool) -> None:
        self.loaded = loaded
        if not loaded:
            return
        from speedrun import backend, config, render, switches, topics

        self._backend = backend
        self._render = render
        self._topics = topics
        self._switches = switches
        self._conf = config.get()

    def observe(self, col: Any, card: Any) -> None:
        """Everything the add-on does while a student is reviewing.

        The whole dashboard gather plus the reviewer hook, on every single card
        rather than once — if any of it perturbed the scheduler, doing it twenty
        times would make that loud.
        """
        if not self.loaded:
            return
        prefix = self._conf["tag_prefix"]
        tags = list(card.note().tags)
        self._topics.hide_topic_in_question(card.question(), tags, prefix)
        self._topics.reveal_topic_in_answer(card.answer(), tags, prefix)

        sections = []
        for entry in self._conf["sections"]:
            code = entry["code"]
            scores = self._backend.section_scores(
                col, code, prefix, int(entry.get("outline_topic_count", 0))
            )
            mastery = self._backend.section_mastery(col, code, prefix)
            sections.append((entry.get("name", code), scores, list(mastery.topics)))
        collection_mastery = self._backend.collection_mastery(col, prefix)
        # No socket: the probe is stubbed unreachable, so this arm runs the
        # dashboard in exactly the state the `ai_enabled = false` tests describe.
        status = self._switches.read(
            self._conf, probe_service=lambda _url: False
        ).status
        self._render.render_dashboard(sections, collection_mastery, status)


def trace(
    path: str,
    arm: str,
    addons_root: str | None,
    observer: Any = None,
) -> dict[str, Any]:
    """Drive a fixed review session and record every scheduling decision.

    ``observer`` replaces the add-on with an arbitrary ``(col, card) -> None``
    callback, which is how the test suite checks that this comparison can fail:
    hand it something that genuinely disturbs the queue and the traces must
    diverge. A comparison that has never been seen to fail is not evidence.
    """
    if arm in ("disabled", "enabled"):
        assert addons_root is not None
        install_addon(addons_root)

    from anki.collection import Collection

    addon = _AddonUnderTest(loaded=arm == "enabled")

    col = Collection(path)
    steps: list[dict[str, Any]] = []
    learning_delays: list[Any] = []

    for index in range(STEPS):
        queued = col.sched.get_queued_cards(fetch_limit=1)
        if not queued.cards:
            steps.append({"queue": "empty"})
            break
        entry = queued.cards[0]
        card_id = entry.card.id
        rating = RATINGS[index % len(RATINGS)]

        step: dict[str, Any] = {
            # Queue order: which card, in which queue, with what left behind it.
            "card_id": card_id,
            "queue": int(entry.queue),
            "counts": [queued.new_count, queued.learning_count, queued.review_count],
            # Scheduling decisions: what all four buttons would do.
            "states": _states_summary(entry.states),
            "rating": rating,
        }

        card = col.get_card(card_id)
        if observer is None:
            addon.observe(col, card)
        else:
            observer(col, card)

        answered_at = int(time.time())
        col.sched.answer_card(_answer(card_id, entry.states, rating))

        answered = col.get_card(card_id)
        step["after"] = _card_summary(answered)
        step["revlog"] = _last_revlog(col, card_id)
        if answered.type in INTRADAY_TYPES:
            learning_delays.append([index, answered.due - answered_at])
        steps.append(step)

    result = {
        "arm": arm,
        "steps": steps,
        "learning_delays": learning_delays,
        # The arm's own claim about itself, checked from inside the interpreter
        # that ran it rather than assumed by the caller.
        "speedrun_imported": any(
            name == "speedrun" or name.startswith("speedrun.") for name in sys.modules
        ),
        "day_cutoff": col.sched.day_cutoff,
    }
    col.close()
    return result


def main(argv: list[str]) -> int:
    command = argv[1]
    if command == "build":
        build(argv[2])
        return 0
    if command == "trace":
        result = trace(argv[2], argv[3], argv[4] if len(argv) > 4 else None)
        print(json.dumps(result))
        return 0
    raise SystemExit(f"unknown command {command!r}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
