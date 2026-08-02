# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Add-on configuration, read through Anki's own add-on config machinery.

``tag_prefix`` is the root of the tag namespace a student's deck already uses,
and it is passed straight through to the backend.

``sections`` carries each section's ``outline_topic_count`` — how many content
categories the AAMC's published Outline lists for it. That number is *not* a
Speedrun invention and is not a threshold: it is the denominator coverage is
measured against, and ``SectionScoresRequest`` requires the caller to supply it.
Supplying 0 makes readiness abstain, which is the correct behaviour when no
Outline has been loaded — so the failure mode of getting this wrong is a
withheld score, never an invented one.

``coach_enabled``, ``ai_enabled`` and ``agent_url`` are the two in-app off
switches and the address the second one probes. They are *stored* here and
*interpreted* in ``switches.py`` — nothing else in the add-on may branch on
them, because the whole claim of these switches is that measurement does not
depend on them.

Every default is chosen so that a value going missing degrades toward doing
less: an absent switch reads as on only because the shipped ``config.json``
says on, and an absent ``agent_url`` reads as no service, which is off.
"""

from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {
    "tag_prefix": "mcat",
    "sections": [
        {"code": "CP", "name": "Chem/Phys", "outline_topic_count": 10},
        {"code": "BB", "name": "Bio/Biochem", "outline_topic_count": 9},
        {"code": "PS", "name": "Psych/Soc", "outline_topic_count": 12},
        {"code": "CARS", "name": "CARS", "outline_topic_count": 0},
    ],
    "hide_topic_label_during_question": True,
    "show_topic_breakdown": True,
    "coach_enabled": True,
    "ai_enabled": True,
    "agent_url": "http://127.0.0.1:8000/health",
    "coach_topic_id": "1D",
    "coach_seed": 0,
}


def get() -> dict[str, Any]:
    """Merged defaults + whatever the user set in the add-on config screen."""
    merged = dict(DEFAULTS)
    try:
        from aqt import mw

        stored = mw.addonManager.getConfig(__name__)
    except Exception:
        stored = None
    if stored:
        merged.update(stored)
    return merged
