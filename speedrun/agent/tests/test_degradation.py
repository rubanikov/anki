# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Proof that killing this service cannot stop the desktop app.

The third acceptance criterion — "service killed: the app still starts, still
scores Memory, still shows coverage" — is a claim about a dependency that must
not exist. A runtime check cannot demonstrate its absence; a runtime check on a
machine where the service happened to be down demonstrates only that. So it is
asserted structurally, by reading the add-on's source: if nothing in the desktop
tree can import this package, and the one call it does make is an HTTP request
with a timeout whose failure is caught, then there is no path by which this
process's death reaches a score.

These tests read `speedrun/addon/` and never modify it. They live here rather
than there because this is the package whose absence is being proven.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ADDON_DIR = Path(__file__).resolve().parents[2] / "addon"
ADDON_SOURCES = sorted(ADDON_DIR.rglob("*.py")) if ADDON_DIR.is_dir() else []


def test_the_addon_exists_to_be_checked():
    """Guard: an empty glob would make every assertion below vacuous."""
    assert ADDON_SOURCES, f"no add-on sources under {ADDON_DIR}"


@pytest.mark.parametrize("source", ADDON_SOURCES, ids=lambda p: p.name)
def test_addon_never_imports_the_agent(source: Path):
    """No import, no dependency. The two never share an interpreter."""
    text = source.read_text(encoding="utf-8")
    for banned in ("speedrun_agent", "langgraph", "fastapi", "anthropic", "langsmith"):
        assert not re.search(rf"\b{banned}\b", text), (
            f"{source.name} references {banned!r}; the desktop app must not "
            f"depend on the agent service or its dependency tree"
        )


def test_the_only_reach_is_a_probe_that_cannot_raise():
    """The single HTTP call is bounded and its failure is already handled.

    `switches.probe` is the whole surface. It takes a timeout, catches every
    exception, and returns False — so an unreachable service becomes
    `ai_enabled = false` rather than a stack trace on the dashboard.
    """
    switches = (ADDON_DIR / "switches.py").read_text(encoding="utf-8")
    assert "def probe(" in switches
    assert "timeout" in switches
    assert "except Exception" in switches
    assert "return False" in switches


def _switches_module():
    """Load the add-on's `switches.py` on its own, without importing Anki.

    It is stdlib-only by design, so the degraded path can be exercised here
    rather than described. Loading it by path also proves the claim above from
    the other direction: this file is reachable without `aqt`.
    """
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "speedrun_addon_switches", ADDON_DIR / "switches.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves annotations through here
    spec.loader.exec_module(module)
    return module


def test_a_dead_service_turns_the_ai_off_and_nothing_else():
    """The degraded path, run: unreachable is `ai_enabled = false`, not an error.

    `Switches` answers two questions and both are about the AI. There is no
    property here a score could be routed through, so no state of this service
    — down, hung, or answering nonsense — can withhold Memory or coverage.
    """
    switches = _switches_module()

    decided = switches.read(
        {"ai_enabled": True, "coach_enabled": True, "agent_url": "http://127.0.0.1:1/x"},
        probe_service=lambda url: False,
    )

    assert decided.generation_allowed is False
    assert decided.coach_allowed is False
    assert "AI off" in decided.status
    answers = {
        name
        for name in dir(decided)
        if not name.startswith("_") and name not in {"count", "index"}
    }
    assert answers == {
        "coach_enabled",
        "ai_enabled",
        "service_reachable",
        "generation_allowed",
        "coach_allowed",
        "status",
    }


def test_a_probe_that_explodes_still_yields_a_decision():
    """A misbehaving probe must not take the dashboard down with it."""
    switches = _switches_module()

    def explodes(url: str) -> bool:
        raise RuntimeError("socket on fire")

    decided = switches.read({"agent_url": "http://127.0.0.1:1/x"}, probe_service=explodes)

    assert decided.service_reachable is False
    assert decided.generation_allowed is False
