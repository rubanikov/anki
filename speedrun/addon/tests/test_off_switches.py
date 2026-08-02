# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The three off switches, as tests rather than as promises.

Speedrun makes three claims about being switched off, and they carry more than
politeness. The graded non-negotiable is that both apps run with AI off. Arms B
and C of the ablation *are* ``coach_enabled`` on versus off, so if that switch
does not cleanly isolate the spoken loop the headline number of the experiment
measures nothing. And "adopting Speedrun is reversible" is a claim to a user
about their own collection.

| switch | what must still work |
| --- | --- |
| add-on disabled | stock Anki — scheduling untouched, nothing of ours loaded |
| ``coach_enabled = false`` | everything except the spoken loop |
| ``ai_enabled = false`` | the same, and no generation either |

The first is checked by running a real review session in three fresh
interpreters and comparing what the scheduler did. That harness is
``scheduling_trace.py``; what it can and cannot compare is written down there and
in ``../../eval/offswitch/OFF_SWITCHES.md``, because a partial check that reads
as a total one would be worse than no check at all.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest
import render
import scheduling_trace
import switches

TAG_PREFIX = "mcat"

SECTIONS = [
    ("Chem/Phys", "CP", 10),
    ("Bio/Biochem", "BB", 9),
    ("Psych/Soc", "PS", 12),
    ("CARS", "CARS", 0),
]

TRACE_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "scheduling_trace.py"
)

#: A learning card's ``due`` is the second it was answered plus a delay. The
#: delay is compared exactly, in two independent places; this tolerance covers
#: only the case where a second boundary falls between reading the clock and the
#: backend reading it, which no add-on can influence.
CLOCK_TOLERANCE_SECS = 1


# --------------------------------------------------------------------------
# Switch 1 — the add-on disabled
# --------------------------------------------------------------------------


def _anki_env() -> dict[str, str]:
    anki = pytest.importorskip(
        "anki.collection",
        reason="Python bindings not built; run with PYTHONPATH=out/pylib",
    )
    pylib_root = os.path.dirname(os.path.dirname(os.path.abspath(anki.__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [pylib_root] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    return env


def _run(args: list[str], env: dict[str, str]) -> str:
    done = subprocess.run(
        [sys.executable, TRACE_SCRIPT, *args],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture(scope="module")
def traces(tmp_path_factory) -> dict[str, dict]:
    """One collection, three fresh interpreters, three recorded sessions.

    Built once and copied, because Anki seeds its interval fuzz from the card id
    and the card id is a creation timestamp: two collections built a second apart
    would schedule differently for reasons that have nothing to do with this
    add-on.
    """
    env = _anki_env()
    root = tmp_path_factory.mktemp("offswitch")
    base = str(root / "base.anki2")
    _run(["build", base], env)

    results = {}
    for arm in ("absent", "disabled", "enabled"):
        collection = str(root / f"{arm}.anki2")
        shutil.copy(base, collection)
        addons_root = str(root / f"{arm}-addons21")
        os.makedirs(addons_root, exist_ok=True)
        results[arm] = json.loads(_run(["trace", collection, arm, addons_root], env))
    return results


def test_the_session_the_arms_are_compared_over_is_worth_comparing(traces):
    # A trace of two new cards would prove nothing. Assert the session actually
    # exercised the scheduler before trusting any comparison built on it.
    steps = traces["absent"]["steps"]
    assert len(steps) == scheduling_trace.STEPS
    assert all("after" in step for step in steps)

    # All three queue kinds were served: new, intraday learning, review.
    assert {step["queue"] for step in steps} == {0, 1, 2}
    # Cards moved between states rather than sitting in one.
    assert len({step["after"]["type"] for step in steps}) >= 3
    # Every button was pressed, so every branch of the scheduler was taken.
    assert {step["rating"] for step in steps} == {1, 2, 3, 4}
    # Something lapsed, which is the branch that rewrites an interval downward.
    assert any(step["after"]["lapses"] > 0 for step in steps)


def test_the_arms_were_in_the_state_they_claim(traces):
    # Each arm reports, from inside its own interpreter, whether Speedrun was
    # imported. Without this the comparison could pass by all three arms being
    # accidentally identical.
    assert traces["absent"]["speedrun_imported"] is False
    assert traces["disabled"]["speedrun_imported"] is False
    assert traces["enabled"]["speedrun_imported"] is True


def test_a_disabled_addon_schedules_identically_to_no_addon_at_all(traces):
    """The claim: install Speedrun, disable it, and Anki is the Anki you had.

    "Disabled" here is what Anki means by it. ``AddonManager.__init__`` puts the
    add-ons folder on ``sys.path`` whether or not any add-on in it is enabled,
    and ``loadAddons`` then skips the disabled ones — so a disabled add-on is a
    directory that is importable and never imported. The ``disabled`` arm
    reproduces exactly that.
    """
    absent, disabled = traces["absent"], traces["disabled"]

    # Queue order: the same cards, in the same order, out of the same queues,
    # with the same counts left behind them.
    assert [s["card_id"] for s in absent["steps"]] == [
        s["card_id"] for s in disabled["steps"]
    ]
    assert [s["queue"] for s in absent["steps"]] == [
        s["queue"] for s in disabled["steps"]
    ]
    assert [s["counts"] for s in absent["steps"]] == [
        s["counts"] for s in disabled["steps"]
    ]

    # Scheduling decisions: what each of the four buttons offered before the
    # answer, the card row after it, and the revlog entry Anki wrote.
    assert [s["states"] for s in absent["steps"]] == [
        s["states"] for s in disabled["steps"]
    ]
    assert [s["after"] for s in absent["steps"]] == [
        s["after"] for s in disabled["steps"]
    ]
    assert [s["revlog"] for s in absent["steps"]] == [
        s["revlog"] for s in disabled["steps"]
    ]

    # Belt and braces: the whole record, field for field.
    assert absent["steps"] == disabled["steps"]

    _assert_learning_delays_match(absent, disabled)


def test_an_enabled_addon_does_not_perturb_the_scheduler_either(traces):
    """The stronger claim, and the one with a plausible failure mode.

    A disabled add-on changing scheduling would take a genuinely weird bug. An
    *enabled* one doing it takes only a backend read that is not as pure as it
    says — ``topic_mastery`` opening a write transaction, a render call touching
    the card timer, an undo entry landing in the queue. The ``enabled`` arm runs
    the entire dashboard gather and both reviewer hooks against every card in the
    session, so any of that would show up here.
    """
    absent, enabled = traces["absent"], traces["enabled"]
    assert absent["steps"] == enabled["steps"]
    _assert_learning_delays_match(absent, enabled)


def test_the_comparison_can_fail(tmp_path):
    """A comparison that has never been seen to fail is not evidence.

    The same collection, traced twice: once untouched, once with an add-on that
    does one mild, entirely plausible thing — burying a card. If the two traces
    matched, every assertion above would be decoration.
    """
    pytest.importorskip(
        "anki.collection",
        reason="Python bindings not built; run with PYTHONPATH=out/pylib",
    )
    base = str(tmp_path / "base.anki2")
    scheduling_trace.build(base)

    clean_path = str(tmp_path / "clean.anki2")
    shutil.copy(base, clean_path)
    clean = scheduling_trace.trace(clean_path, "absent", None)

    def bury_something(col, _card):
        col.sched.bury_cards([sorted(col.find_cards("deck:Default"))[-1]])

    dirty_path = str(tmp_path / "dirty.anki2")
    shutil.copy(base, dirty_path)
    dirty = scheduling_trace.trace(dirty_path, "absent", None, observer=bury_something)

    assert clean["steps"] != dirty["steps"]


def _assert_learning_delays_match(left: dict, right: dict) -> None:
    """Intraday learning delays, the one comparison with a tolerance.

    ``due`` for a learning card is *the moment of answering* plus a fuzzed delay.
    The arms run seconds apart, so the moment differs by construction; the delay
    does not, and is what is compared. It is already compared exactly as
    ``scheduled_secs`` inside ``states`` above — this is the same number read
    back off the card, and the ±1s is the clock, not the scheduler.
    """
    assert [index for index, _ in left["learning_delays"]] == [
        index for index, _ in right["learning_delays"]
    ]
    assert left["learning_delays"], "session produced no intraday learning cards"
    for (_, a), (_, b) in zip(left["learning_delays"], right["learning_delays"]):
        assert abs(a - b) <= CLOCK_TOLERANCE_SECS


# --------------------------------------------------------------------------
# Switches 2 and 3 — the decision
# --------------------------------------------------------------------------


def _switches(**overrides) -> switches.Switches:
    conf = {"coach_enabled": True, "ai_enabled": True, "agent_url": "http://x"}
    conf.update(overrides)
    reachable = conf.pop("reachable", True)
    return switches.read(conf, probe_service=lambda _url: reachable)


def test_coach_off_stops_the_loop_and_nothing_else():
    off = _switches(coach_enabled=False)
    assert off.coach_allowed is False
    # Generation keeps running: the switch is scoped to the spoken loop, which
    # is what makes ablation arm B a clean comparison against arm A.
    assert off.generation_allowed is True
    assert off.status == switches.COACH_OFF_BY_CONFIG


def test_ai_off_stops_generation_and_the_coach_with_it():
    off = _switches(ai_enabled=False)
    assert off.generation_allowed is False
    # The coach cannot run on items that were never generated, so the wider
    # switch subsumes the narrower one even with coach_enabled left true.
    assert off.coach_enabled is True
    assert off.coach_allowed is False
    assert off.status == switches.AI_OFF_BY_CONFIG


def test_an_unreachable_service_is_the_same_state_as_ai_off():
    down = _switches(reachable=False)
    chosen = _switches(ai_enabled=False)
    assert down.generation_allowed == chosen.generation_allowed is False
    assert down.coach_allowed == chosen.coach_allowed is False
    # Distinguishable to the student — it says which one — but one code path.
    assert down.status == switches.AI_OFF_UNREACHABLE


def test_ai_off_does_not_open_a_socket():
    # A switched-off feature that still probes the network is not switched off:
    # it is a feature with a timeout, and every dashboard open would pay it.
    probed = []
    switches.read(
        {"ai_enabled": False, "agent_url": "http://x"},
        probe_service=lambda url: probed.append(url) or True,
    )
    assert probed == []


def test_the_probe_treats_every_failure_as_unreachable_and_never_raises():
    # Refused connection on a port nothing is listening on.
    assert switches.probe("http://127.0.0.1:9/health", timeout=0.25) is False
    # Not a URL at all.
    assert switches.probe("not-a-url", timeout=0.25) is False
    # No service configured — the state of a fresh install, not an error.
    assert switches.probe("", timeout=0.25) is False


def test_reading_the_switches_cannot_raise():
    # The dashboard calls read() on its way to rendering scores that have
    # nothing to do with the AI. A probe that throws must cost the coach, not
    # the page.
    def explode(_url):
        raise RuntimeError("the probe misbehaved")

    decided = switches.read({"ai_enabled": True}, probe_service=explode)
    assert decided.service_reachable is False
    assert decided.coach_allowed is False


def test_both_switches_on_and_the_service_up_is_the_only_way_to_the_coach():
    on = _switches()
    assert on.coach_allowed is True
    assert on.generation_allowed is True
    assert on.status == switches.COACH_ON


def test_the_shipped_defaults_are_on_and_missing_keys_read_as_on():
    import config

    assert config.DEFAULTS["coach_enabled"] is True
    assert config.DEFAULTS["ai_enabled"] is True

    with open(
        os.path.join(os.path.dirname(TRACE_SCRIPT), "..", "config.json"),
        encoding="utf8",
    ) as handle:
        shipped = json.load(handle)
    # config.json is what the user sees in the config screen; DEFAULTS is what
    # applies if it is missing. They disagreeing would be a switch that means
    # one thing on a fresh install and another after a reset.
    for key in ("coach_enabled", "ai_enabled", "agent_url"):
        assert shipped[key] == config.DEFAULTS[key]

    # An empty config is not a licence to run the AI silently — but it is also
    # not a reason to withhold the loop from someone who never opened the config
    # screen. Absent reads as on; absent agent_url reads as unreachable, so the
    # net effect of knowing nothing is still no coach.
    unconfigured = switches.read({})
    assert unconfigured.ai_enabled is True
    assert unconfigured.service_reachable is False
    assert unconfigured.coach_allowed is False


# --------------------------------------------------------------------------
# What the switches must never reach: the measurement
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def studied_collection(tmp_path_factory):
    """A collection with genuine review history, not an empty one.

    An empty collection would make "the dashboard still works with AI off" a
    weaker claim than it needs to be — everything abstains on an empty
    collection whatever the switches say. This one has revlog entries and
    Topic-tagged cards, so Memory and coverage have something to report.
    """
    pytest.importorskip(
        "anki.collection",
        reason="Python bindings not built; run with PYTHONPATH=out/pylib",
    )
    path = str(tmp_path_factory.mktemp("studied") / "collection.anki2")
    scheduling_trace.build(path)
    scheduling_trace.trace(path, "absent", None)
    return path


def _dashboard(path: str, conf: dict) -> str:
    from anki.collection import Collection

    col = Collection(path)
    try:
        sections = []
        for name, code, outline in SECTIONS:
            scores = col._backend.section_scores(
                section=code, tag_prefix=TAG_PREFIX, outline_topic_count=outline
            )
            mastery = col._backend.topic_mastery(section=code, tag_prefix=TAG_PREFIX)
            sections.append((name, scores, mastery))
        collection_mastery = col._backend.topic_mastery(
            section="", tag_prefix=TAG_PREFIX
        )
        status = switches.read(
            conf, probe_service=lambda _url: bool(conf.get("reachable"))
        ).status
        return render.render_dashboard(sections, collection_mastery, status)
    finally:
        col.close()


def test_the_dashboard_still_measures_with_ai_off_and_the_service_unreachable(
    studied_collection,
):
    """The graded non-negotiable: the app runs with AI off.

    Not "starts". Runs, and still measures — the scores are engine output, and
    the engine has never heard of these switches.
    """
    html = _dashboard(
        studied_collection,
        {"ai_enabled": False, "coach_enabled": False, "reachable": False},
    )

    # Not an error page. This is the failure mode being guarded against: a
    # missing agent service turning the whole dashboard into a stack trace.
    assert "Could not read the collection" not in html

    # Memory, and the give-up rule that governs it, still arrive from the engine.
    # The count is not pinned: it depends on the queue order of the session that
    # built this collection. What is pinned is that the engine counted the
    # reviews, compared them to the threshold, and said which threshold.
    assert "graded reviews in BB. Need 200." in html
    assert html.count(render.ABSTAINING) == 12

    # Coverage, its denominator, and the evidence counts are all on screen.
    assert "Coverage" in html
    assert html.count('<span class="k">Unmapped cards</span>') == len(SECTIONS)
    assert html.count("cards Unmapped</span>") == len(SECTIONS) + 1
    assert "Cards unmapped" in html
    assert "Cards considered" in html

    # And the coach says so plainly rather than pretending it ran.
    assert switches.AI_OFF_BY_CONFIG in html


def test_the_dashboard_reports_real_review_history_with_ai_off(studied_collection):
    # The point of doing this on a studied collection: the engine is genuinely
    # producing per-Topic numbers with the AI switched off, not just abstaining
    # its way to a page that happens to render.
    from anki.collection import Collection

    col = Collection(studied_collection)
    try:
        mastery = col._backend.topic_mastery(section="", tag_prefix=TAG_PREFIX)
        assert mastery.cards_considered > 0
        assert list(mastery.topics), "no Topic had review history to report"
        # The Unmapped denominator is real too: some notes carry no Topic tag.
        assert mastery.cards_unmapped > 0

        scored = [
            col._backend.section_scores(
                section=code, tag_prefix=TAG_PREFIX, outline_topic_count=outline
            )
            for _, code, outline in SECTIONS
            if code != "CARS"
        ]
        # Reviews counted and coverage measured against the Outline, with the
        # AI switched off and no agent service in existence.
        assert any(s.graded_reviews > 0 for s in scored)
        assert any(s.coverage_pct > 0 for s in scored)
    finally:
        col.close()


def test_no_switch_can_change_a_single_number_on_the_page(studied_collection):
    """The invariant, checked over every combination rather than argued.

    Eight settings of the two switches and the service probe. The page they
    produce differs in exactly one line — the sentence saying whether the coach
    is running. Every score, range, coverage figure, count and abstention is
    byte-identical, because none of them passed through a switch.
    """
    pages = {}
    for coach in (True, False):
        for ai in (True, False):
            for reachable in (True, False):
                conf = {
                    "coach_enabled": coach,
                    "ai_enabled": ai,
                    "agent_url": "http://x",
                    "reachable": reachable,
                }
                html = _dashboard(studied_collection, conf)
                status = switches.read(
                    conf, probe_service=lambda _url, r=reachable: r
                ).status
                pages[(coach, ai, reachable)] = html.replace(
                    render._coach_status_html(status), ""
                )

    distinct = set(pages.values())
    assert len(distinct) == 1, "an off switch changed the measurement"

    # And the status line really did vary, so the comparison above is not
    # passing because every page was identical to begin with.
    statuses = {
        switches.read(
            {"coach_enabled": c, "ai_enabled": a, "agent_url": "http://x"},
            probe_service=lambda _url, r=r: r,
        ).status
        for c in (True, False)
        for a in (True, False)
        for r in (True, False)
    }
    assert len(statuses) == 4


def test_the_topic_label_stays_hidden_when_the_coach_is_off():
    # Hiding the Topic during a question is measurement hygiene, not coaching:
    # "this is 5C" is most of the answer on a thermodynamics item. Ablation arm
    # B reviews with the coach off and still needs the label withheld, so this
    # deliberately does not consult coach_enabled.
    import topics

    conf = {"coach_enabled": False, "ai_enabled": False}
    assert switches.read(conf).coach_allowed is False
    question = "<div>What buffers blood pH?</div><div>mcat::BB::amino_acids</div>"
    out = topics.hide_topic_in_question(question, ["mcat::BB::amino_acids"], TAG_PREFIX)
    assert "mcat::BB::amino_acids" not in out
    assert topics.TOPIC_MASK in out
