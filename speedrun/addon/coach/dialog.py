# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The coach window: a webview that records, and a bridge that carries nothing else.

A ``QDialog`` holding an ``AnkiWebView``, opened from Tools, for the same reason
the dashboard is one — a mediasrv route would mean editing an upstream file, and
this fork's upstream diff is three lines.

Two things here are not incidental.

**The microphone permission is granted on this page's own profile and nowhere
else.** ``MediaRecorder`` is the reason a student cannot copy an answer into
this screen, so the capability has to actually be there; but granting it is done
by connecting to this webview's own ``permissionRequested`` signal, not by
setting a Chromium flag on the application. Nothing outside this dialog gains a
microphone, and nothing upstream is touched.

**Every network call is off the UI thread and every one of them can fail.** The
service is reached through ``coach.client``, which cannot raise, and the results
arrive back through ``taskman``. A dead service leaves this window showing a
sentence and leaves the rest of Anki — the queue, Memory, coverage, the
dashboard — untouched, because none of them pass through here.

The window is also refused before it opens when the off switches say so:
``coach_enabled = false`` or ``ai_enabled = false`` shows the switch's own
sentence and makes no request at all.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import aqt
from aqt.qt import (
    QDialog,
    QDialogButtonBox,
    Qt,
    QVBoxLayout,
    qconnect,
)
from aqt.utils import disable_help_button, restoreGeom, saveGeom
from aqt.webview import AnkiWebView, AnkiWebViewKind

from .. import config, switches
from . import client, page

DIALOG_NAME = "SpeedrunCoach"
GEOM_KEY = "speedrunCoach"

#: What the JavaScript half may say. A closed set: the bridge carries the loop's
#: four messages and nothing that could be mistaken for a command.
READY = "coach:ready"
RESTART = "coach:restart"
TURN = "coach:turn:"
TRANSCRIBE = "coach:transcribe:"


def _grant_microphone(web: AnkiWebView) -> None:
    """Allow audio capture on this webview, on both Qt permission APIs.

    Qt 6.8 replaced ``featurePermissionRequested`` with ``permissionRequested``
    and a ``QWebEnginePermission`` object. Both are handled so the add-on does
    not silently lose its microphone on whichever Qt the profile happens to
    have, and only ``MediaAudioCapture`` is ever granted — video and screen
    capture are refused by never being mentioned.
    """
    pageobj = web.page()
    if pageobj is None:
        return

    if hasattr(pageobj, "permissionRequested"):
        from aqt.qt import QWebEnginePermission  # type: ignore[attr-defined]

        def on_permission(permission: Any) -> None:
            if permission.permissionType() == (
                QWebEnginePermission.PermissionType.MediaAudioCapture
            ):
                permission.grant()
            else:
                permission.deny()

        qconnect(pageobj.permissionRequested, on_permission)
        return

    # Qt 6.7 and earlier.
    from aqt.qt import QWebEnginePage  # type: ignore[attr-defined]

    def on_feature(origin: Any, feature: Any) -> None:
        audio = QWebEnginePage.Feature.MediaAudioCapture
        pageobj.setFeaturePermission(
            origin,
            feature,
            QWebEnginePage.PermissionPolicy.PolicyGrantedByUser
            if feature == audio
            else QWebEnginePage.PermissionPolicy.PolicyDeniedByUser,
        )

    qconnect(pageobj.featurePermissionRequested, on_feature)


class SpeedrunCoachDialog(QDialog):
    """Runs the loop. Owns no rule about what order its steps come in.

    The order lives in the service, which is what makes "confidence before the
    reveal" true of the product rather than true of this file: this window
    cannot show an answer it was not sent, and it is never sent one until the
    confidence for that item is on the record.
    """

    silentlyClose = True

    def __init__(self, mw: Any) -> None:
        QDialog.__init__(self, mw, Qt.WindowType.Window)
        self.mw = mw
        mw.garbage_collect_on_dialog_finish(self)
        self.setWindowTitle("Speedrun Coach")
        disable_help_button(self)

        conf = config.get()
        self._base = client.base_url(str(conf.get("agent_url", "")))
        self._topic_id = str(conf.get("coach_topic_id", "1D"))
        self._seed = int(conf.get("coach_seed", 0))
        self._session_id = ""

        self.web = AnkiWebView(parent=self, kind=AnkiWebViewKind.DEFAULT)
        self.web.set_title("speedrun coach")
        self.web.set_bridge_command(self._on_bridge, self)
        _grant_microphone(self.web)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        qconnect(buttons.rejected, self.reject)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 8, 8)
        layout.addWidget(self.web, 1)
        layout.addWidget(buttons)
        self.setLayout(layout)

        restoreGeom(self, GEOM_KEY, default_size=(760, 860))
        self.show()
        self.web.stdHtml(page.page(), context=self)

    # --- the bridge -------------------------------------------------------

    def _on_bridge(self, message: str) -> Any:
        """The four messages the page may send. Anything else is ignored.

        Nothing here trusts the page for anything but "the student did this".
        The step, the legality of the step and the contents of the reply all
        come from the service.
        """
        try:
            if message in (READY, RESTART):
                self._start()
            elif message.startswith(TURN):
                self._turn(json.loads(message[len(TURN) :]))
            elif message.startswith(TRANSCRIBE):
                self._transcribe(message[len(TRANSCRIBE) :])
        except Exception as exc:  # noqa: BLE001 - a webview must not crash Anki
            self._status(f"The coach could not continue: {exc}")
        return None

    # --- the loop ---------------------------------------------------------

    def _start(self) -> None:
        conf = config.get()
        self._session_id = ""
        self._status("Asking a cold question…")

        def op() -> Any:
            decided = switches.read(conf)
            if not decided.coach_allowed:
                return decided.status, None
            return None, client.start(self._base, self._topic_id, self._seed)

        self._in_background(op, self._on_started)

    def _on_started(self, result: Any) -> None:
        blocked, reply = result
        if blocked is not None:
            self._status(blocked)
            return
        if not reply.ok:
            self._status(reply.reason)
            return
        self._session_id = str(reply.data.get("session_id", ""))
        self._render(reply.data)

    def _turn(self, fields: dict[str, Any]) -> None:
        if not self._session_id:
            self._start()
            return
        audio = str(fields.pop("audio_base64", "") or "")
        payload = {
            "session_id": self._session_id,
            "spoke": bool(fields.get("spoke")),
            "audio_ms": int(fields.get("audio_ms") or 0),
        }
        for key in ("choice", "confidence"):
            if fields.get(key) is not None:
                payload[key] = fields[key]

        def op() -> Any:
            # Transcription rides along with the turn it belongs to, so a
            # transcript is recorded against the prompt that produced it — but
            # its failure never stops the turn, which is the whole point of the
            # audio-only fallback.
            if audio:
                spoken = client.transcribe(self._base, audio)
                if spoken.ok and spoken.data.get("transcript"):
                    payload["transcript"] = spoken.data["transcript"]
            return client.turn(self._base, payload)

        self._in_background(op, self._on_turned)

    def _on_turned(self, reply: Any) -> None:
        if not reply.ok:
            self._status(reply.reason)
            return
        self._render(reply.data)

    def _transcribe(self, audio: str) -> None:
        """Show what was heard, as feedback. Nothing downstream reads it."""
        if not audio:
            return

        def op() -> Any:
            return client.transcribe(self._base, audio)

        def done(reply: Any) -> None:
            text = reply.data.get("transcript") if reply.ok else None
            self._eval("transcript", text or "")

        self._in_background(op, done)

    # --- talking to the page ---------------------------------------------

    def _render(self, state: dict[str, Any]) -> None:
        self._eval("render", state)
        self._seed += 1

        def op() -> Any:
            return client.speak_rate(self._base)

        def done(reply: Any) -> None:
            if not reply.ok or reply.data.get("speak_rate") is None:
                self._eval("speakRate", "Speak-rate: no prompts yet.")
                return
            tally = reply.data
            self._eval(
                "speakRate",
                f"Speak-rate: {tally['spoken']} of {tally['prompts']} prompts "
                f"spoken ({tally['speak_rate']:.0%}).",
            )

        self._in_background(op, done)

    def _status(self, text: str) -> None:
        self._eval("status", text)

    def _eval(self, method: str, argument: Any) -> None:
        if self.web is None:
            return
        self.web.eval(f"SpeedrunCoach.{method}({json.dumps(argument)});")

    def _in_background(self, op: Callable[[], Any], done: Callable[[Any], None]) -> None:
        """Run a call off the UI thread. ``taskman`` needs no open collection.

        ``QueryOp`` would want one, and the coach must be openable — and must
        fail visibly — whether or not a collection read is available.
        """

        def wrapped() -> Any:
            return op()

        def finished(future: Any) -> None:
            try:
                done(future.result())
            except Exception as exc:  # noqa: BLE001
                self._status(f"The coach could not continue: {exc}")

        # `uses_collection=False`: these are network calls. Serialising them
        # behind collection work would make a slow model round trip look like a
        # frozen reviewer, and the coach reads nothing from the collection.
        self.mw.taskman.run_in_background(wrapped, finished, uses_collection=False)

    # --- teardown ---------------------------------------------------------

    def reject(self) -> None:
        if self.web is not None:
            self.web.cleanup()
            self.web = None  # type: ignore[assignment]
        saveGeom(self, GEOM_KEY)
        aqt.dialogs.markClosed(DIALOG_NAME)
        QDialog.reject(self)

    def closeWithCallback(self, callback: Callable[[], None]) -> None:
        self.reject()
        callback()


def open_coach() -> None:
    aqt.dialogs.open(DIALOG_NAME, aqt.mw)


def register() -> None:
    """Register the dialog and hang it off the Tools menu.

    The menu item is added unconditionally, and the switches are read when it is
    *opened* rather than when it is registered. A student who turns the coach
    back on should not have to restart Anki to find the menu again, and a
    switch consulted at import time is a switch that has to be right before the
    profile is loaded.
    """
    from aqt import gui_hooks
    from aqt.qt import QAction

    aqt.dialogs.register_dialog(DIALOG_NAME, SpeedrunCoachDialog)

    def add_menu_item() -> None:
        mw = aqt.mw
        action = QAction("Speedrun Coach", mw)
        action.setObjectName("actionSpeedrunCoach")
        qconnect(action.triggered, open_coach)
        mw.form.menuTools.addAction(action)

    gui_hooks.main_window_did_init.append(add_menu_item)
