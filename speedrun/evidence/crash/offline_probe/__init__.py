# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Throwaway add-on: start Anki with the network amputated, open the Speedrun
dashboard, and photograph it.

Evidence for the second half of T-21 — "network pulled: AI degrades, scores
survive" — on the desktop. Pulling the machine's network is not an option here
(three other agents share the box) and would in any case only show that nothing
*got through*. Instead every socket call is replaced with one that raises before
it leaves the process, so a dashboard that renders is a dashboard that never
reached for the network at all.

The guard is installed at import time, which is before the profile opens and
before anything Speedrun does. It is deliberately not selective: `urllib`,
`requests`, sync, the update check and the add-on's own agent-service probe all
go through `socket`, and all of them are cut.

Environment:
    T21_SHOT      png to write the dashboard into
    T21_LOG       json written with what happened, including any socket attempt
"""

from __future__ import annotations

import json
import os
import socket
import time
import traceback

from aqt import gui_hooks, mw
from aqt.qt import QTimer

SHOT = os.environ.get("T21_SHOT")
LOG = os.environ.get("T21_LOG")

_attempts: list[str] = []


class NetworkUsed(RuntimeError):
    pass


def _install_network_guard() -> None:
    def refuse(*args, **kwargs):  # noqa: ANN002, ANN003
        _attempts.append("".join(traceback.format_stack()[-6:-1]))
        raise NetworkUsed("offline probe: something tried to use the network")

    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse
    socket.gethostbyname = refuse


_install_network_guard()


def _write(result: dict) -> None:
    if not LOG:
        return
    result["network_attempts"] = len(_attempts)
    result["network_attempt_stacks"] = _attempts[:3]
    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.flush()
        os.fsync(f.fileno())


def _shoot(dialog) -> None:  # noqa: ANN001
    result: dict = {"started_ms": int(time.time() * 1000)}
    try:
        # The rendered HTML, read back out of the webview, so the evidence is
        # the text the add-on actually put on screen rather than a description
        # of it.
        def got_text(text: str) -> None:
            result["dashboard_text"] = text
            if SHOT:
                dialog.grab().save(SHOT, "PNG")
                result["screenshot"] = SHOT
            _write(result)
            QTimer.singleShot(500, mw.unloadProfileAndExit)

        dialog.web.evalWithCallback("document.body.innerText", got_text)
    except Exception as exc:  # noqa: BLE001 - the failure is the evidence
        result["error"] = f"{type(exc).__name__}: {exc}"
        _write(result)


def _start(_profile=None) -> None:  # noqa: ANN001
    from speedrun import dashboard

    dialog = dashboard.SpeedrunDashboard(mw)
    dialog.show()
    # The dashboard fetches its numbers on a background op; give it time to come
    # back before reading the page.
    QTimer.singleShot(6000, lambda: _shoot(dialog))


gui_hooks.profile_did_open.append(_start)
