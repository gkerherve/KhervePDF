"""Floating Find bar — Ctrl+F search across the whole PDF.

Floats over the top of the active PdfTab, hosts a QLineEdit and
Next / Prev buttons. The search walks pages via `page.search_for`
and collects every match as (page_idx, fitz.Rect). On Next/Prev,
the active PdfTab scrolls to the page and a yellow highlight rect
is drawn over the match. The bar closes on Escape.
"""
from __future__ import annotations

from typing import Optional

import fitz
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import (
    QFrame, QGraphicsRectItem, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QToolButton,
)


class FindBar(QFrame):
    """Floating search input. Operates on whatever PdfTab the
    MainWindow tells it about via set_tab()."""

    closed = Signal()

    def __init__(self, parent) -> None:
        super().__init__(parent, Qt.SubWindow)
        self.setObjectName("FindBar")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "#FindBar { background:#fffce6; border:1px solid #b58900;"
            "border-radius:4px; }"
            "QPushButton, QToolButton { padding:2px 6px; }"
        )
        self._tab = None  # set via set_tab
        self._matches: list[tuple[int, fitz.Rect]] = []
        self._idx = -1  # current match index
        self._scene_marker: Optional[QGraphicsRectItem] = None

        h = QHBoxLayout(self)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(6)
        h.addWidget(QLabel("Find:", self))
        self._input = QLineEdit(self)
        self._input.setMinimumWidth(220)
        self._input.returnPressed.connect(self._on_next)
        self._input.textChanged.connect(self._on_text_changed)
        h.addWidget(self._input)
        self._count_lbl = QLabel("", self)
        self._count_lbl.setMinimumWidth(80)
        h.addWidget(self._count_lbl)
        prev_btn = QPushButton("Prev", self)
        prev_btn.clicked.connect(self._on_prev)
        h.addWidget(prev_btn)
        next_btn = QPushButton("Next", self)
        next_btn.clicked.connect(self._on_next)
        h.addWidget(next_btn)
        close_btn = QToolButton(self)
        close_btn.setText("✕")
        close_btn.clicked.connect(self.hide)
        h.addWidget(close_btn)

    def set_tab(self, tab) -> None:
        self._clear_marker()
        self._tab = tab
        self._matches = []
        self._idx = -1
        self._count_lbl.setText("")

    def show_and_focus(self) -> None:
        self.show()
        self._input.setFocus()
        self._input.selectAll()

    # ----- search -----

    def _run_search(self) -> None:
        self._clear_marker()
        self._matches = []
        self._idx = -1
        text = self._input.text().strip()
        if not text or self._tab is None or self._tab._doc is None:
            self._count_lbl.setText("")
            return
        for page_idx in range(self._tab._doc.page_count):
            try:
                rects = self._tab._doc[page_idx].search_for(text)
            except Exception:
                rects = []
            for r in rects:
                self._matches.append((page_idx, fitz.Rect(r)))
        if not self._matches:
            self._count_lbl.setText("0 matches")
            return
        self._count_lbl.setText(f"1 / {len(self._matches)}")
        self._idx = 0
        self._goto_match()

    def _on_text_changed(self, _text: str) -> None:
        self._run_search()

    def _on_next(self) -> None:
        if not self._matches:
            return
        self._idx = (self._idx + 1) % len(self._matches)
        self._count_lbl.setText(
            f"{self._idx + 1} / {len(self._matches)}"
        )
        self._goto_match()

    def _on_prev(self) -> None:
        if not self._matches:
            return
        self._idx = (self._idx - 1) % len(self._matches)
        self._count_lbl.setText(
            f"{self._idx + 1} / {len(self._matches)}"
        )
        self._goto_match()

    def _goto_match(self) -> None:
        if not (0 <= self._idx < len(self._matches)):
            return
        page_idx, rect = self._matches[self._idx]
        tab = self._tab
        if tab is None or page_idx not in tab._page_layout:
            tab.scroll_to_page(page_idx) if tab else None
            return
        self._clear_marker()
        # Convert PDF-pt rect to scene rect
        p0 = tab._page_to_scene(page_idx, rect.x0, rect.y0)
        p1 = tab._page_to_scene(page_idx, rect.x1, rect.y1)
        from PySide6.QtCore import QRectF
        scene_rect = QRectF(p0, p1).normalized()
        item = QGraphicsRectItem(scene_rect)
        pen = QPen(QColor("#b58900"), 1.5)
        pen.setCosmetic(True)
        item.setPen(pen)
        fill = QColor("#fff176")
        fill.setAlpha(150)
        item.setBrush(QBrush(fill))
        item.setZValue(300)
        tab._scene.addItem(item)
        self._scene_marker = item
        # Scroll the view so the match is visible.
        tab.centerOn(scene_rect.center())

    def _clear_marker(self) -> None:
        if self._scene_marker is not None and self._tab is not None:
            try:
                self._tab._scene.removeItem(self._scene_marker)
            except Exception:
                pass
        self._scene_marker = None

    def hideEvent(self, ev):  # noqa: N802
        super().hideEvent(ev)
        self._clear_marker()
        self.closed.emit()

    def keyPressEvent(self, ev):  # noqa: N802
        if ev.key() == Qt.Key_Escape:
            self.hide()
            ev.accept()
            return
        super().keyPressEvent(ev)
