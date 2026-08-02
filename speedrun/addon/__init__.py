# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Speedrun — measurement layered on top of Anki.

The desktop surface. It renders what ``SpeedrunService`` computed and computes
nothing itself: not a score, not a range, not a threshold comparison, not an
abstention decision. Those live in the Rust backend so the Android client
reproduces them identically offline, and any arithmetic here would fork that
logic into two places obliged to agree forever.

Everything attaches through ``gui_hooks``. Nothing upstream is patched, wrapped
or replaced, so disabling this add-on leaves stock Anki behind — the first of
the three off switches in the spec, and the one asserted rather than promised:
``tests/test_off_switches.py`` drives the same review session with Speedrun
absent, installed-but-disabled and loaded, and compares what the scheduler did.
The other two switches are configuration, read only in ``switches.py``.

See README.md for how it loads and what shipping it preinstalled would require.
"""

from __future__ import annotations


def _register() -> None:
    from . import coach, dashboard, reviewer

    dashboard.register()
    reviewer.register()
    # The coach's menu item is registered unconditionally; the off switches are
    # read when it is opened, so turning the coach back on does not require a
    # restart and a switch is never consulted before a profile exists.
    coach.register()


try:
    import aqt  # noqa: F401
except ImportError:
    # Imported outside a running Anki — by the tests in ./tests, or by tooling
    # walking the tree. There is nothing to hook onto, and refusing to import
    # would make the renderer untestable without a Qt event loop.
    pass
else:
    # Deliberately outside the try: a failure inside our own modules is a bug,
    # and Anki's add-on loader already reports it properly.
    _register()
