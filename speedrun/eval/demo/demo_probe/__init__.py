# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Throwaway add-on: open the Speedrun dashboard on the demo profile and
photograph it.

Loaded only into the throwaway `ANKI_BASE` built by `make_demo_history.py`, by
`shoot_dashboard.py`. It is not shipped, is never installed into a real profile,
and does nothing but drive the real dashboard and grab pixels — every number and
every word in the picture comes from the add-on and the backend.

Two pictures, because the page is taller than any window:

* **full** — the whole page, stitched from tiles. The banner is switched from
  `position: sticky` to `static` for the duration, so it appears once, at the
  top of the document, where it actually sits. Left sticky it would be painted
  over the top of every tile and would hide the content behind it.
* **scrolled** — the live window, sticky restored, scrolled down to the
  Bio/Biochem panel. This is the one that shows the banner is not merely *at*
  the top of the page but pinned to the top of the *viewport*, so a reader who
  scrolls to the Memory score cannot leave the warning behind.

Environment:
    DEMO_SHOT           png for the full-page capture
    DEMO_SHOT_SCROLLED  png for the scrolled live window
    DEMO_LOG            json report; its existence is how the driver knows we
                        finished
"""

from __future__ import annotations

import json
import os
import time

from aqt import gui_hooks, mw
from aqt.qt import QColor, QImage, QPainter, QTimer

SHOT = os.environ.get("DEMO_SHOT")
SHOT_SCROLLED = os.environ.get("DEMO_SHOT_SCROLLED")
LOG = os.environ.get("DEMO_LOG")

WIDTH = 1060
HEIGHT = 980
#: The dashboard reads the collection on a background op; nothing may be grabbed
#: until it has come back.
GATHER_MS = 9000
#: Long enough for the compositor to have painted the new scroll position.
SETTLE_MS = 700


def _write(result: dict) -> None:
    if not LOG:
        return
    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.flush()
        os.fsync(f.fileno())


class Shooter:
    def __init__(self, dialog) -> None:  # noqa: ANN001
        self.dialog = dialog
        self.result: dict = {"started_ms": int(time.time() * 1000)}
        self.tiles: list[tuple[float, QImage]] = []
        self.top = 0
        self.prev_top = -1.0
        self.scale = 1.0
        self.page_height = 0

    # -- full page ---------------------------------------------------------

    def start(self) -> None:
        self.dialog.web.evalWithCallback(
            """(() => {
                const b = document.querySelector('.demo-banner');
                if (b) { b.dataset.wasPosition = getComputedStyle(b).position;
                         b.style.position = 'static'; }
                // The grabbed widget is a little shorter than window.innerHeight,
                // so the last scroll position stops short of the true bottom.
                // Padding pushes the real end of the page into reach; the slack
                // shows up as empty space under the footer and nothing else.
                document.body.style.paddingBottom = '160px';
                return JSON.stringify({
                    scrollHeight: document.documentElement.scrollHeight,
                    viewport: window.innerHeight,
                    clientWidth: document.documentElement.clientWidth,
                    banner: !!b,
                    text: document.body.innerText,
                });
            })()""",
            self._measured,
        )

    def _measured(self, raw: str) -> None:
        page = json.loads(raw)
        self.result["dashboard_text"] = page["text"]
        self.result["banner_in_dom"] = page["banner"]
        self.page_height = page["scrollHeight"]
        pix = self.dialog.web.grab()
        self.scale = pix.width() / max(1, page["clientWidth"])
        self.result["page_px"] = {
            "height": self.page_height,
            "viewport": page["viewport"],
            "device_scale": round(self.scale, 3),
        }
        self.top = 0
        self._next_tile()

    def _next_tile(self) -> None:
        self.dialog.web.eval(f"window.scrollTo(0, {self.top});")
        QTimer.singleShot(SETTLE_MS, self._read_scroll)

    def _read_scroll(self) -> None:
        # Where the page *actually* went, not where it was asked to go. The
        # last scroll is clamped, and a stitch that assumed otherwise would
        # duplicate a strip or leave a white seam through the page.
        self.dialog.web.evalWithCallback("window.scrollY", self._grab_tile)

    def _grab_tile(self, scrolled) -> None:  # noqa: ANN001
        top = float(scrolled or 0)
        image = self.dialog.web.grab().toImage()
        self.tiles.append((top, image))
        tile_css = image.height() / self.scale
        # Stop at the bottom, and stop again if the page refused to scroll any
        # further — a capture loop that cannot end is worse than a short page.
        stalled = top <= self.prev_top
        self.prev_top = top
        if stalled or top + tile_css >= self.page_height - 1 or len(self.tiles) >= 24:
            self._stitch()
            return
        # Overlap by a few pixels: identical content overwrites identical
        # content, which is the one failure mode that leaves no trace.
        self.top = int(top + tile_css) - 8
        self._next_tile()

    def _stitch(self) -> None:
        width = max(image.width() for _, image in self.tiles)
        height = max(
            int(round(top * self.scale)) + image.height() for top, image in self.tiles
        )
        canvas = QImage(width, height, QImage.Format.Format_RGB32)
        canvas.fill(QColor("white"))
        painter = QPainter(canvas)
        for top, image in self.tiles:
            painter.drawImage(0, int(round(top * self.scale)), image)
        painter.end()
        if SHOT:
            canvas.save(SHOT, "PNG")
            self.result["screenshot"] = SHOT
            self.result["screenshot_px"] = [width, height]
        self.result["tiles"] = len(self.tiles)
        self._scrolled()

    # -- the live window, banner pinned ------------------------------------

    def _scrolled(self) -> None:
        self.dialog.web.eval(
            """(() => {
                const b = document.querySelector('.demo-banner');
                if (b) { b.style.position = b.dataset.wasPosition || 'sticky'; }
                document.body.style.paddingBottom = '';
                const panels = document.querySelectorAll('.panel');
                const target = panels[2] || panels[panels.length - 1];
                if (target) { target.scrollIntoView(true); }
            })()"""
        )
        QTimer.singleShot(SETTLE_MS, self._grab_scrolled)

    def _grab_scrolled(self) -> None:
        if SHOT_SCROLLED:
            self.dialog.grab().save(SHOT_SCROLLED, "PNG")
            self.result["screenshot_scrolled"] = SHOT_SCROLLED
        self.finish()

    def finish(self) -> None:
        self.result["finished_ms"] = int(time.time() * 1000)
        _write(self.result)
        QTimer.singleShot(500, mw.unloadProfileAndExit)


_shooter: Shooter | None = None


def _start(_profile=None) -> None:  # noqa: ANN001
    global _shooter
    from speedrun import dashboard

    dialog = dashboard.SpeedrunDashboard(mw)
    dialog.resize(WIDTH, HEIGHT)
    dialog.show()
    _shooter = Shooter(dialog)
    QTimer.singleShot(GATHER_MS, _shooter.start)


gui_hooks.profile_did_open.append(_start)
