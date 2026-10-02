"""Slideshow: present the open PDF one whole page at a time.

``SlideshowView`` is a black stage that fits a single page to the
widget and swaps it instantly for the next one — no scrolling. It can
advance by hand (click, arrow keys, wheel) or continuously on a timer,
and it is host-agnostic: MainWindow embeds it in its central stack for a
windowed show, or shows it as a frameless full-screen window.

It owns the ``fitz.Document`` it is given (an in-memory copy with the
user's annotations baked in, see ``PdfTab.slideshow_document``) and
closes it in ``dispose()``.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Optional

import fitz
from PySide6.QtCore import QElapsedTimer, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSpinBox, QToolButton, QWidget,
)

from .icons import icon

INTERVAL_MIN, INTERVAL_MAX = 1, 600     # seconds per page
_TICK_MS = 50                           # auto-advance clock resolution
_CONTROLS_HIDE_MS = 2500                # control bar / cursor idle timeout
_RESIZE_SETTLE_MS = 120                 # re-render this long after a resize
_CACHE_PAGES = 3                        # current + next + one spare
_WHEEL_STEP = 120                       # one wheel notch
_WHEEL_COOLDOWN_MS = 250                # stops trackpad momentum flipping many pages
_STAGE = QColor("#000000")
_ON_STAGE = "#ffffff"                   # icon colour on the black stage


class _ControlBar(QFrame):
    """The translucent PowerPoint-style pill at the bottom of the stage."""

    def __init__(self, view: "SlideshowView") -> None:
        super().__init__(view)
        self.setObjectName("SlideBar")
        # Clicks on the bar must not also advance the slide beneath it.
        self.setAttribute(Qt.WA_NoMousePropagation)
        self.setStyleSheet("""
            #SlideBar { background: rgba(20, 20, 20, 215); border-radius: 12px; }
            #SlideBar QToolButton { background: transparent; border: none;
                                    border-radius: 6px; padding: 4px; }
            #SlideBar QToolButton:hover { background: rgba(255, 255, 255, 45); }
            #SlideBar QToolButton:checked { background: rgba(255, 255, 255, 70); }
            #SlideBar QLabel { color: #f2f2f2; padding: 0 8px; }
            #SlideBar QSpinBox { color: #f2f2f2; background: rgba(255, 255, 255, 30);
                                 border: none; border-radius: 5px; padding: 2px 4px; }
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(2)

        self.prev = self._button("prev_page", "Previous page (←)")
        self.play = self._button("play", "")
        self.play.setCheckable(True)
        self.next = self._button("next_page", "Next page (→ / Space)")
        self.label = QLabel("", self)
        self.interval = QSpinBox(self)
        self.interval.setRange(INTERVAL_MIN, INTERVAL_MAX)
        self.interval.setSuffix(" s")
        self.interval.setKeyboardTracking(False)
        self.interval.setFocusPolicy(Qt.ClickFocus)
        self.interval.setToolTip("Seconds each page stays on screen")
        self.loop = self._button("loop", "Loop back to the first page "
                                         "after the last")
        self.loop.setCheckable(True)
        self.mode = self._button("fullscreen", "")
        self.close_btn = self._button("close_x", "End slideshow (Esc)")

        for w in (self.prev, self.play, self.next, self.label,
                  self.interval, self.loop, self.mode, self.close_btn):
            lay.addWidget(w)

    def _button(self, glyph: str, tip: str) -> QToolButton:
        b = QToolButton(self)
        b.setIcon(icon(glyph, color=_ON_STAGE))
        b.setIconSize(QSize(22, 22))
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.NoFocus)    # keys keep driving the stage
        b.setCursor(Qt.PointingHandCursor)
        return b


class SlideshowView(QWidget):
    exit_requested = Signal()
    mode_switch_requested = Signal()                # windowed <-> full screen
    page_changed = Signal(int)                      # 0-based
    settings_changed = Signal(bool, int, bool)      # continuous, seconds, loop

    def __init__(self, doc: fitz.Document, start_page: int = 0, *,
                 continuous: bool = False, interval_s: int = 5,
                 loop: bool = True, fullscreen: bool = False,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._doc: Optional[fitz.Document] = doc
        self._n = doc.page_count
        self._page = max(0, min(start_page, self._n - 1))
        self._continuous = continuous
        self._interval_ms = self._clamp_s(interval_s) * 1000
        self._loop = loop
        self._fullscreen = fullscreen
        self._cache: OrderedDict[tuple, QPixmap] = OrderedDict()
        self._progress_ms = 0
        self._wheel_acc = 0
        self._wheel_clock = QElapsedTimer()
        self._wheel_clock.start()

        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setWindowTitle("KhervePDF — Slideshow")

        self._tick_clock = QElapsedTimer()
        self._clock = QTimer(self)
        self._clock.setInterval(_TICK_MS)
        self._clock.timeout.connect(self._on_tick)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(_RESIZE_SETTLE_MS)
        self._resize_timer.timeout.connect(self._after_resize)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(_CONTROLS_HIDE_MS)
        self._hide_timer.timeout.connect(self._maybe_hide_controls)

        self._bar = _ControlBar(self)
        self._bar.prev.clicked.connect(self.prev_page)
        self._bar.next.clicked.connect(self.next_page)
        self._bar.play.clicked.connect(self.toggle_continuous)
        self._bar.interval.valueChanged.connect(self._on_interval_edited)
        self._bar.interval.editingFinished.connect(self.setFocus)
        self._bar.loop.clicked.connect(self._on_loop_clicked)
        self._bar.mode.clicked.connect(self.mode_switch_requested)
        self._bar.close_btn.clicked.connect(self.exit_requested)
        self._sync_bar()
        self._apply_clock()
        self._wake_controls()

    # ---- public API -------------------------------------------------------

    def current_page(self) -> int:
        return self._page

    def page_count(self) -> int:
        return self._n

    def is_continuous(self) -> bool:
        return self._continuous

    def interval_seconds(self) -> int:
        return self._interval_ms // 1000

    def loops(self) -> bool:
        return self._loop

    def goto(self, idx: int) -> None:
        if self._doc is None or not 0 <= idx < self._n:
            return
        self._page = idx
        # Render before restarting the countdown so the time a page is
        # shown for isn't eaten by the cost of drawing it.
        self._pixmap_for(idx)
        self._progress_ms = 0
        self._sync_bar()
        self.update()
        self.page_changed.emit(idx)
        QTimer.singleShot(0, self._prefetch)

    def next_page(self) -> None:
        if self._page + 1 < self._n:
            self.goto(self._page + 1)
        elif self._loop and self._n > 1:
            self.goto(0)

    def prev_page(self) -> None:
        if self._page > 0:
            self.goto(self._page - 1)
        elif self._loop and self._n > 1:
            self.goto(self._n - 1)

    def set_continuous(self, on: bool, *, emit: bool = True) -> None:
        if on == self._continuous:
            return
        self._continuous = on
        self._progress_ms = 0
        self._apply_clock()
        self._sync_bar()
        self.update()
        if emit:
            self._emit_settings()

    def toggle_continuous(self) -> None:
        self.set_continuous(not self._continuous)

    def set_interval(self, seconds: int, *, emit: bool = True) -> None:
        ms = self._clamp_s(seconds) * 1000
        if ms == self._interval_ms:
            return
        self._interval_ms = ms
        self._progress_ms = min(self._progress_ms, ms)
        self._sync_bar()
        if emit:
            self._emit_settings()

    def set_loop(self, on: bool, *, emit: bool = True) -> None:
        if on == self._loop:
            return
        self._loop = on
        self._sync_bar()
        if emit:
            self._emit_settings()

    def dispose(self) -> None:
        """Stop the timers and close the document. Safe to call twice."""
        for t in (self._clock, self._hide_timer, self._resize_timer):
            t.stop()
        self._cache.clear()
        doc, self._doc = self._doc, None
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass

    # ---- rendering --------------------------------------------------------

    @staticmethod
    def _clamp_s(seconds: int) -> int:
        return max(INTERVAL_MIN, min(INTERVAL_MAX, int(seconds)))

    def _key(self, idx: int) -> tuple:
        s = self.size()
        return (idx, s.width(), s.height(), self.devicePixelRatioF() or 1.0)

    def _render(self, idx: int) -> Optional[QPixmap]:
        """Rasterise page `idx` to fit the stage (whole page visible),
        at the screen's device resolution so text stays sharp."""
        if self._doc is None or self.width() < 2 or self.height() < 2:
            return None
        dpr = self.devicePixelRatioF() or 1.0
        try:
            page = self._doc.load_page(idx)
            r = page.rect
            scale = min(self.width() / r.width, self.height() / r.height)
            m = fitz.Matrix(scale * dpr, scale * dpr)
            pix = page.get_pixmap(matrix=m, alpha=False, annots=True)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format_RGB888).copy()
        except Exception:
            return None     # a broken page shows as black, the show goes on
        img.setDevicePixelRatio(dpr)
        return QPixmap.fromImage(img)

    def _pixmap_for(self, idx: int) -> Optional[QPixmap]:
        if not 0 <= idx < self._n:
            return None
        key = self._key(idx)
        pm = self._cache.get(key)
        if pm is not None:
            self._cache.move_to_end(key)
            return pm
        pm = self._render(idx)
        if pm is not None:
            self._cache[key] = pm
            while len(self._cache) > _CACHE_PAGES:
                self._cache.popitem(last=False)
        return pm

    def _stale_pixmap_for(self, idx: int) -> Optional[QPixmap]:
        """Latest cached raster of `idx` at any size — shown (scaled)
        while a resize is still in flight."""
        for key in reversed(self._cache):
            if key[0] == idx:
                return self._cache[key]
        return None

    def _prefetch(self) -> None:
        if self._doc is None or self._resize_timer.isActive() or self._n < 2:
            return
        nxt = self._page + 1
        if nxt >= self._n:
            if not self._loop:
                return
            nxt = 0
        self._pixmap_for(nxt)

    def paintEvent(self, _ev) -> None:  # noqa: N802 — Qt override
        p = QPainter(self)
        p.fillRect(self.rect(), _STAGE)
        if self._doc is not None:
            # Mid-resize: scale the old raster (cheap) instead of
            # re-rendering on every frame; _after_resize sharpens it.
            # With no earlier raster to scale (first paint) render now.
            stale = (self._stale_pixmap_for(self._page)
                     if self._resize_timer.isActive() else None)
            if stale is not None:
                p.setRenderHint(QPainter.SmoothPixmapTransform)
                dpr = stale.devicePixelRatio()
                pw, ph = stale.width() / dpr, stale.height() / dpr
                k = min(self.width() / pw, self.height() / ph)
                w, h = pw * k, ph * k
                p.drawPixmap(
                    QRectF((self.width() - w) / 2, (self.height() - h) / 2,
                           w, h),
                    stale, QRectF(stale.rect()))
            else:
                pm = self._pixmap_for(self._page)
                if pm is not None:
                    dpr = pm.devicePixelRatio()
                    x = round((self.width() - pm.width() / dpr) / 2)
                    y = round((self.height() - pm.height() / dpr) / 2)
                    p.drawPixmap(x, y, pm)
        # Thin countdown line along the bottom edge while auto-advancing.
        if self._continuous and self._interval_ms > 0:
            frac = min(1.0, self._progress_ms / self._interval_ms)
            p.fillRect(QRectF(0, self.height() - 3, self.width() * frac, 3),
                       QColor(255, 255, 255, 90))
        p.end()

    def resizeEvent(self, ev) -> None:  # noqa: N802 — Qt override
        super().resizeEvent(ev)
        self._resize_timer.start()
        self._place_bar()

    def _after_resize(self) -> None:
        self.update()
        QTimer.singleShot(0, self._prefetch)

    # ---- auto-advance -----------------------------------------------------

    def _apply_clock(self) -> None:
        if self._continuous and self._doc is not None:
            self._tick_clock.restart()
            self._clock.start()
        else:
            self._clock.stop()

    def _on_tick(self) -> None:
        self._progress_ms += self._tick_clock.restart()
        if self._progress_ms < self._interval_ms:
            self.update(0, self.height() - 3, self.width(), 3)
            return
        at_end = self._page + 1 >= self._n
        if at_end and not self._loop:
            # Nothing further to show: stop the timer, stay on the last page.
            self.set_continuous(False)
            return
        self.next_page()
        self._progress_ms = 0

    # ---- control bar ------------------------------------------------------

    def _sync_bar(self) -> None:
        b = self._bar
        b.label.setText(f"{self._page + 1} / {self._n}")
        for w, state in ((b.play, self._continuous), (b.loop, self._loop)):
            w.blockSignals(True)
            w.setChecked(state)
            w.blockSignals(False)
        b.play.setIcon(icon("pause" if self._continuous else "play",
                            color=_ON_STAGE))
        b.play.setToolTip("Pause automatic advance (P)" if self._continuous
                          else "Advance automatically (P)")
        b.interval.blockSignals(True)
        b.interval.setValue(self._interval_ms // 1000)
        b.interval.blockSignals(False)
        b.mode.setIcon(icon("exit_full" if self._fullscreen else "fullscreen",
                            color=_ON_STAGE))
        b.mode.setToolTip("Show in this window instead (F)"
                          if self._fullscreen else "Show full screen (F)")
        self._place_bar()

    def _place_bar(self) -> None:
        b = self._bar
        b.adjustSize()
        b.move((self.width() - b.width()) // 2,
               self.height() - b.height() - 24)

    def _wake_controls(self) -> None:
        if self._doc is None:       # disposed (e.g. Esc just ended the show)
            return
        self._bar.show()
        self._bar.raise_()
        self.unsetCursor()
        self._hide_timer.start()

    def _maybe_hide_controls(self) -> None:
        if self._bar.underMouse() or self._bar.interval.hasFocus():
            self._hide_timer.start()        # still in use
            return
        self._bar.hide()
        if self._fullscreen:
            self.setCursor(Qt.BlankCursor)

    def _on_interval_edited(self, seconds: int) -> None:
        self.set_interval(seconds)

    def _on_loop_clicked(self, checked: bool) -> None:
        self.set_loop(checked)

    def _emit_settings(self) -> None:
        self.settings_changed.emit(self._continuous, self.interval_seconds(),
                                   self._loop)

    # ---- input ------------------------------------------------------------

    def keyPressEvent(self, ev) -> None:  # noqa: N802 — Qt override
        if ev.modifiers() & (Qt.ControlModifier | Qt.AltModifier
                             | Qt.MetaModifier):
            super().keyPressEvent(ev)       # leave menu shortcuts alone
            return
        k = ev.key()
        if k == Qt.Key_Escape:
            self.exit_requested.emit()
        elif k in (Qt.Key_Right, Qt.Key_Down, Qt.Key_PageDown, Qt.Key_Space,
                   Qt.Key_Return, Qt.Key_Enter):
            self.next_page()
        elif k in (Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp, Qt.Key_Backspace):
            self.prev_page()
        elif k == Qt.Key_Home:
            self.goto(0)
        elif k == Qt.Key_End:
            self.goto(self._n - 1)
        elif k == Qt.Key_P:
            self.toggle_continuous()
        elif k == Qt.Key_F:
            self.mode_switch_requested.emit()
        else:
            super().keyPressEvent(ev)
            return
        self._wake_controls()
        ev.accept()

    def mousePressEvent(self, ev) -> None:  # noqa: N802 — Qt override
        self.setFocus()
        if ev.button() == Qt.LeftButton:
            self.next_page()
        elif ev.button() == Qt.RightButton:
            self.prev_page()
        self._wake_controls()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802 — Qt override
        self._wake_controls()

    def wheelEvent(self, ev) -> None:  # noqa: N802 — Qt override
        # Pages flip, never scroll. Trackpads send a stream of small
        # deltas, so accumulate to one notch and then rest briefly.
        self._wheel_acc += ev.angleDelta().y()
        if (abs(self._wheel_acc) >= _WHEEL_STEP
                and self._wheel_clock.elapsed() >= _WHEEL_COOLDOWN_MS):
            if self._wheel_acc > 0:
                self.prev_page()
            else:
                self.next_page()
            self._wheel_acc = 0
            self._wheel_clock.restart()
        self._wake_controls()
        ev.accept()

    def closeEvent(self, ev) -> None:  # noqa: N802 — Qt override
        # A full-screen show is its own window: closing it (Cmd+W,
        # Alt+F4) must go through the host so the main window is restored.
        if self.isWindow():
            ev.ignore()
            self.exit_requested.emit()
            return
        super().closeEvent(ev)
