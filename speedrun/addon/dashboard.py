# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The dashboard window.

A ``QDialog`` holding an ``AnkiWebView``, opened from Tools. It is a Qt dialog
rather than a mediasrv page for one reason: mediasrv routes are registered by
Anki's own web server module, and adding one means editing an upstream file.
The fork's upstream diff is three lines, and keeping it that way is worth more
than a URL. An ``AnkiWebView`` gives the same HTML, the same fonts and the same
light/dark theming without touching anything upstream.

The reads happen on a background thread through ``QueryOp``, which is Anki's own
helper for exactly this: a read that must not block the UI and must not race the
collection.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import aqt
from aqt.operations import QueryOp
from aqt.qt import (
    QDialog,
    QDialogButtonBox,
    Qt,
    QVBoxLayout,
    qconnect,
)
from aqt.utils import disable_help_button, restoreGeom, saveGeom
from aqt.webview import AnkiWebView, AnkiWebViewKind

from . import backend, config, render, switches

DIALOG_NAME = "SpeedrunDashboard"
GEOM_KEY = "speedrunDashboard"


def _gather(col: Any, conf: dict[str, Any]) -> Any:
    """Every backend read the page needs, done off the UI thread.

    Returns whatever ``render.render_dashboard`` takes, so the success callback
    has nothing left to decide.

    The off switches are read here too, and read *last*, after every measurement
    is already in hand. That ordering is the point: probing the agent service can
    hang for the length of its timeout, and no score on this page may wait on a
    service, or fail because one is missing. ``switches.read`` cannot raise, so
    the page cannot be lost to an absent agent either.
    """
    prefix = conf["tag_prefix"]
    show_topics = conf.get("show_topic_breakdown", True)

    sections = []
    for entry in conf["sections"]:
        code = entry["code"]
        scores = backend.section_scores(
            col, code, prefix, int(entry.get("outline_topic_count", 0))
        )
        topics = (
            backend.section_mastery(col, code, prefix).topics if show_topics else ()
        )
        sections.append((entry.get("name", code), scores, list(topics)))

    mastery = backend.collection_mastery(col, prefix)
    return sections, mastery, switches.read(conf).status


class SpeedrunDashboard(QDialog):
    """Renders backend output. Holds no score logic of its own."""

    # aqt.DialogManager contract: close immediately when the collection closes.
    silentlyClose = True

    def __init__(self, mw: Any) -> None:
        QDialog.__init__(self, mw, Qt.WindowType.Window)
        self.mw = mw
        mw.garbage_collect_on_dialog_finish(self)
        self.setWindowTitle("Speedrun")
        disable_help_button(self)

        self.web = AnkiWebView(parent=self, kind=AnkiWebViewKind.DEFAULT)
        self.web.set_title("speedrun dashboard")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        refresh = buttons.addButton("Refresh", QDialogButtonBox.ButtonRole.ActionRole)
        assert refresh is not None
        refresh.setAutoDefault(False)
        qconnect(refresh.clicked, self.refresh)
        qconnect(buttons.rejected, self.reject)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 8, 8)
        layout.addWidget(self.web, 1)
        layout.addWidget(buttons)
        self.setLayout(layout)

        restoreGeom(self, GEOM_KEY, default_size=(900, 800))
        self.show()
        self.refresh()

    def refresh(self) -> None:
        if self.mw.col is None:
            self._set_html(render.render_error("No collection is open."))
            return
        conf = config.get()

        def on_success(result: Any) -> None:
            sections, mastery, coach_status = result
            self._set_html(render.render_dashboard(sections, mastery, coach_status))

        def on_failure(exc: Exception) -> None:
            self._set_html(render.render_error(str(exc)))

        QueryOp(
            parent=self,
            op=lambda col: _gather(col, conf),
            success=on_success,
        ).failure(on_failure).with_progress(
            "Reading your collection…"
        ).run_in_background()

    def _set_html(self, body: str) -> None:
        if self.web is not None:
            self.web.stdHtml(body, context=self)

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


def open_dashboard() -> None:
    aqt.dialogs.open(DIALOG_NAME, aqt.mw)


def register() -> None:
    """Register the dialog and hang it off the Tools menu.

    ``register_dialog`` is Anki's documented entry point for add-on windows: it
    keeps a single copy open and tears it down when the collection closes.
    """
    from aqt import gui_hooks
    from aqt.qt import QAction

    aqt.dialogs.register_dialog(DIALOG_NAME, SpeedrunDashboard)

    def add_menu_item() -> None:
        mw = aqt.mw
        action = QAction("Speedrun Dashboard", mw)
        action.setObjectName("actionSpeedrunDashboard")
        qconnect(action.triggered, open_dashboard)
        mw.form.menuTools.addAction(action)

    gui_hooks.main_window_did_init.append(add_menu_item)
