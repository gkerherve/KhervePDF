"""Start page shown when no PDF is open.

Replaces the old empty grey tab pane: app mark, big Open / New
actions, the recent-files list and (when the updater finds one) a
"new version" banner. The background "wallpaper" is painted at runtime
from the current theme's colours — no bitmap is shipped (project rule:
no PNG/SVG for UI chrome) and it follows theme switches for free.
"""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton,
    QVBoxLayout, QWidget,
)

from . import appmark
from .icons import icon


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """Linear blend a→b by t (0..1); used to derive wallpaper tints
    from the two theme colours so every theme gets a matching wash."""
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


class WelcomePage(QWidget):
    open_requested = Signal()
    new_requested = Signal()
    recent_requested = Signal(str)
    update_requested = Signal()     # "Download update" clicked
    update_dismissed = Signal()

    def __init__(self, theme: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setAutoFillBackground(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)

        # The content sits on a translucent card so text stays legible
        # over the wallpaper in every theme.
        self._card = QFrame(self)
        self._card.setObjectName("WelcomeCard")
        self._card.setMaximumWidth(620)
        self._card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        card = QVBoxLayout(self._card)
        card.setContentsMargins(36, 32, 36, 28)
        card.setSpacing(14)

        # Update banner — hidden until the updater reports a release.
        self._banner = QFrame(self._card)
        self._banner.setObjectName("UpdateBanner")
        bl = QHBoxLayout(self._banner)
        bl.setContentsMargins(12, 8, 8, 8)
        self._banner_lbl = QLabel(self._banner)
        self._banner_lbl.setWordWrap(True)
        dl = QPushButton(icon("download"), "Download update", self._banner)
        dl.setCursor(Qt.PointingHandCursor)
        dl.clicked.connect(self.update_requested)
        x = QToolButton(self._banner)
        x.setIcon(icon("close_x"))
        x.setAutoRaise(True)
        x.setToolTip("Dismiss")
        x.clicked.connect(self._dismiss_banner)
        bl.addWidget(self._banner_lbl, 1)
        bl.addWidget(dl)
        bl.addWidget(x)
        self._banner.hide()
        card.addWidget(self._banner)

        head = QHBoxLayout()
        head.setSpacing(18)
        mark = QLabel(self._card)
        mark.setPixmap(appmark.paint(88))
        mark.setFixedSize(88, 88)
        head.addWidget(mark)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        from . import __version__
        self._title = QLabel("KhervePDF", self._card)
        self._title.setObjectName("WelcomeTitle")
        self._subtitle = QLabel(
            f"View, annotate and edit PDFs — with Git history · v{__version__}",
            self._card)
        self._subtitle.setObjectName("WelcomeSub")
        self._subtitle.setWordWrap(True)
        titles.addStretch(1)
        titles.addWidget(self._title)
        titles.addWidget(self._subtitle)
        titles.addStretch(1)
        head.addLayout(titles, 1)
        card.addLayout(head)
        card.addSpacing(6)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        self._btn_open = self._big_button("open", "Open PDF…",
                                          "Browse for a file  (Ctrl+O)")
        self._btn_open.setObjectName("PrimaryAction")
        self._btn_open.clicked.connect(self.open_requested)
        self._btn_new = self._big_button("new", "New",
                                          "Start a blank document")
        self._btn_new.clicked.connect(self.new_requested)
        actions.addWidget(self._btn_open, 1)
        actions.addWidget(self._btn_new, 1)
        card.addLayout(actions)
        card.addSpacing(8)

        self._recent_hdr = QLabel("Recent files", self._card)
        self._recent_hdr.setObjectName("WelcomeSection")
        card.addWidget(self._recent_hdr)
        self._recent_box = QVBoxLayout()
        self._recent_box.setSpacing(2)
        card.addLayout(self._recent_box)
        self._hint = QLabel("Tip: drop a PDF anywhere on this window to open it.",
                            self._card)
        self._hint.setObjectName("WelcomeHint")
        card.addSpacing(4)
        card.addWidget(self._hint)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._card, 10)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)
        self.set_theme(theme)

    # ----- construction helpers -----

    def _big_button(self, icon_name: str, text: str, tip: str) -> QPushButton:
        b = QPushButton(icon(icon_name), f"  {text}", self._card)
        b.setToolTip(tip)
        b.setMinimumHeight(52)
        b.setCursor(Qt.PointingHandCursor)
        from PySide6.QtCore import QSize
        b.setIconSize(QSize(26, 26))
        return b

    # ----- public API -----

    def set_recent(self, files: list[str]) -> None:
        """Rebuild the recent list. Files that no longer exist are kept
        but greyed out, so a file on an unmounted drive isn't silently
        forgotten; clicking one still goes through open_path, which
        reports the error."""
        while self._recent_box.count():
            item = self._recent_box.takeAt(0)
            w = item.widget()
            if w is not None:
                # Detach now: deleteLater alone leaves the old row
                # painted (at 0,0) until the event loop runs.
                w.hide()
                w.setParent(None)
                w.deleteLater()
        shown = files[:8]
        self._recent_hdr.setVisible(bool(shown))
        for p in shown:
            path = Path(p)
            b = QToolButton(self._card)
            b.setObjectName("RecentItem")
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setIcon(icon("recent_doc"))
            folder = str(path.parent)
            if len(folder) > 60:
                folder = "…" + folder[-59:]
            b.setText(f"{path.name}    {folder}")
            b.setToolTip(p)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setCursor(Qt.PointingHandCursor)
            b.setAutoRaise(True)
            b.setEnabled(path.exists())
            b.clicked.connect(lambda _c=False, s=p: self.recent_requested.emit(s))
            self._recent_box.addWidget(b)

    def show_update(self, tag: str) -> None:
        self._banner_lbl.setText(
            f"<b>KhervePDF {tag}</b> is available.")
        self._banner.show()

    def _dismiss_banner(self) -> None:
        self._banner.hide()
        self.update_dismissed.emit()

    def set_theme(self, theme: dict[str, str]) -> None:
        self._theme = theme
        t = theme
        dark = t.get("dark") == "1"
        card_bg = QColor(t["base"])
        card_bg.setAlpha(225 if dark else 235)
        border = QColor(t["page_border"])
        accent = QColor(t["accent"])
        acc_soft = QColor(accent)
        acc_soft.setAlpha(40)
        hover = QColor(accent)
        hover.setAlpha(28)
        rgba = lambda c: f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"  # noqa: E731
        self._card.setStyleSheet(f"""
            QFrame#WelcomeCard {{
                background: {rgba(card_bg)};
                border: 1px solid {border.name()};
                border-radius: 16px;
            }}
            QLabel {{ background: transparent; color: {t['text']}; }}
            QLabel#WelcomeTitle {{ font-size: 30px; font-weight: 600; }}
            QLabel#WelcomeSub {{ color: {t['text_muted']}; font-size: 13px; }}
            QLabel#WelcomeSection {{
                color: {t['text_muted']}; font-size: 11px; font-weight: 600;
                letter-spacing: 1px; text-transform: uppercase;
            }}
            QLabel#WelcomeHint {{ color: {t['text_muted']}; font-size: 11px; }}
            QPushButton {{
                font-size: 15px; padding: 8px 18px;
                border: 1px solid {border.name()}; border-radius: 10px;
                background: {t['surface']}; color: {t['text']};
            }}
            QPushButton:hover {{ border-color: {accent.name()}; background: {rgba(hover)}; }}
            QPushButton#PrimaryAction {{
                background: {accent.name()}; color: {t['highlight_text']};
                border-color: {accent.name()}; font-weight: 600;
            }}
            QPushButton#PrimaryAction:hover {{ background: {accent.lighter(112).name()}; }}
            QToolButton#RecentItem {{
                text-align: left; padding: 6px 8px; border-radius: 8px;
                color: {t['text']}; font-size: 13px; border: none;
            }}
            QToolButton#RecentItem:hover {{ background: {rgba(hover)}; }}
            QToolButton#RecentItem:disabled {{ color: {t['disabled']}; }}
            QFrame#UpdateBanner {{
                background: {rgba(acc_soft)}; border: 1px solid {accent.name()};
                border-radius: 10px;
            }}
            QFrame#UpdateBanner QPushButton {{ font-size: 13px; padding: 4px 12px; }}
        """)
        # The primary button's icon must contrast with the accent fill.
        self._btn_open.setIcon(icon("open", color=t["highlight_text"]))
        self._btn_new.setIcon(icon("new"))
        self.update()

    # ----- wallpaper -----

    def paintEvent(self, _ev) -> None:  # noqa: N802 — Qt override
        """Diagonal wash from desk to surface colour, two soft accent
        glows, and a faint dot grid — calm enough to sit behind text,
        but not a flat slab."""
        t = self._theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        desk = QColor(t["desk_bg"])
        surface = QColor(t["surface"])
        accent = QColor(t["accent"])
        accent2 = QColor(t["accent2"])

        g = QLinearGradient(0, 0, w, h)
        g.setColorAt(0.0, _mix(surface, accent, 0.10))
        g.setColorAt(0.55, desk)
        g.setColorAt(1.0, _mix(desk, accent2, 0.12))
        p.fillRect(self.rect(), g)

        for cx, cy, r, col, a in (
            (0.15 * w, 0.20 * h, 0.55 * max(w, h), accent, 70),
            (0.90 * w, 0.95 * h, 0.45 * max(w, h), accent2, 50),
        ):
            rg = QRadialGradient(QPointF(cx, cy), r)
            c0 = QColor(col); c0.setAlpha(a)
            c1 = QColor(col); c1.setAlpha(0)
            rg.setColorAt(0.0, c0)
            rg.setColorAt(1.0, c1)
            p.fillRect(self.rect(), QBrush(rg))

        # Flowing "page edge" curves across the lower half.
        line = QColor(t["text"]); line.setAlpha(18)
        p.setPen(QPen(line, 1.2))
        for i in range(7):
            path = QPainterPath()
            y0 = h * (0.55 + i * 0.06)
            path.moveTo(0, y0)
            steps = 24
            for s in range(1, steps + 1):
                x = w * s / steps
                y = y0 + math.sin(s / steps * math.pi * 2 + i * 0.6) * h * 0.04
                path.lineTo(x, y)
            p.drawPath(path)

        dot = QColor(t["text"]); dot.setAlpha(16)
        p.setPen(Qt.NoPen)
        p.setBrush(dot)
        step = 22
        for y in range(step // 2, h, step):
            for x in range(step // 2, w, step):
                p.drawEllipse(QRectF(x - 1, y - 1, 2, 2))
        p.end()
