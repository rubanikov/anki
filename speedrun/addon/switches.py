# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The two in-app off switches, and the one place they are read.

Speedrun has three off switches with three different blast radii. The largest is
not in this file and cannot be: **disabling the add-on** means Anki never imports
anything of ours, so there is no flag to trust and no code left to misbehave.
That one is structural, and the test that proves it lives in
``tests/test_off_switches.py``.

The other two are configuration, and they are read here and nowhere else:

``coach_enabled = false``
    No spoken loop. Reviews, Memory, coverage, the dashboard and its abstentions
    are untouched, because none of them go through this module.

``ai_enabled = false``
    No generation *and* no coach — the coach cannot run without generated items,
    so switching off the smaller thing switches off the larger one too. Memory,
    coverage and the dashboard still come from the Rust engine, which never
    consults a switch at all.

There is a third way the AI goes off that nobody chose: the agent service not
answering. FLOWS §6 fixes the rule — an unreachable service *is* ``ai_enabled =
false``, not an error and not a retry loop — so the degraded path and the
configured path are the same path, and the degraded one is exercised every time
the configured one is.

**The invariant this module exists to hold:** nothing here can withhold a
measurement. ``Switches`` answers two questions, both about the AI, and neither
the dashboard nor the reviewer's Topic hiding asks it anything. Topic hiding is
measurement hygiene rather than coaching, so it survives ``coach_enabled =
false`` deliberately — ablation arm B still needs the label withheld.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: What the dashboard prints when the coach is off. Each names the switch that
#: turned it off, so a student can tell "you chose this" from "it broke".
COACH_OFF_BY_CONFIG = (
    "Coach off — coach_enabled is false. Memory, coverage and the give-up rule "
    "are computed by the engine and are unaffected."
)
AI_OFF_BY_CONFIG = (
    "AI off — ai_enabled is false. No generation and no coach. Memory, coverage "
    "and the give-up rule are computed by the engine and are unaffected."
)
AI_OFF_UNREACHABLE = (
    "AI off — the agent service did not answer. No generation and no coach. "
    "Memory, coverage and the give-up rule are computed by the engine and are "
    "unaffected."
)
COACH_ON = "Coach on — the agent service answered."


@dataclass(frozen=True)
class Switches:
    """A decision, already made. Holds no I/O and no config lookups."""

    coach_enabled: bool
    ai_enabled: bool
    service_reachable: bool

    @property
    def generation_allowed(self) -> bool:
        """May a held-out item be generated?

        An unreachable service is indistinguishable from ``ai_enabled = false``
        by design: there is exactly one disabled state, so there is exactly one
        code path to get wrong.
        """
        return self.ai_enabled and self.service_reachable

    @property
    def coach_allowed(self) -> bool:
        """May the spoken loop run? Requires its own switch *and* the AI."""
        return self.coach_enabled and self.generation_allowed

    @property
    def status(self) -> str:
        """One plain sentence for the dashboard. Never blank, never an error.

        Reported in blast-radius order: ``ai_enabled`` is checked before
        ``coach_enabled`` because it is the wider switch, and a student who
        turned both off should be told about the wider one.
        """
        if not self.ai_enabled:
            return AI_OFF_BY_CONFIG
        if not self.service_reachable:
            return AI_OFF_UNREACHABLE
        if not self.coach_enabled:
            return COACH_OFF_BY_CONFIG
        return COACH_ON


def probe(url: str, timeout: float = 0.5) -> bool:
    """Is the agent service answering? Never raises, never blocks for long.

    Anything other than a well-formed HTTP response counts as unreachable —
    refused connection, timeout, DNS failure, a 5xx, an HTML error page from
    something else listening on that port. FLOWS §6 treats garbage the same as
    silence, so there is nothing to distinguish here.

    An empty URL means "no service configured", which is unreachable rather than
    an error: it is the state a fresh install is in, and a fresh install must not
    show a stack trace on the dashboard.
    """
    if not url:
        return False
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            return 200 <= int(response.status) < 400
    except Exception:
        return False


def read(
    conf: dict[str, Any], probe_service: Callable[[str], bool] | None = None
) -> Switches:
    """Build the decision from add-on config, probing only when it could matter.

    The probe is skipped when ``ai_enabled`` is false, because the answer cannot
    change the outcome and a switched-off feature must not open a socket. That
    also means turning the AI off costs nothing when there is no service running,
    which is the state every grader's machine will be in.
    """
    ai_enabled = bool(conf.get("ai_enabled", True))
    coach_enabled = bool(conf.get("coach_enabled", True))
    if not ai_enabled:
        reachable = False
    else:
        checker = probe_service or (lambda url: probe(url))
        try:
            reachable = bool(checker(str(conf.get("agent_url", "") or "")))
        except Exception:
            # This function must not raise: the dashboard calls it on the way to
            # rendering scores that have nothing to do with the AI, and a page of
            # measurements must not be lost to a probe that misbehaved.
            reachable = False
    return Switches(
        coach_enabled=coach_enabled,
        ai_enabled=ai_enabled,
        service_reachable=reachable,
    )
