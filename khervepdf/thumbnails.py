"""Side-panel page thumbnails for the active PdfTab.

A QListWidget docked on the left edge of the main window renders one
thumbnail per page of the active document; clicking a thumbnail
scrolls the main canvas to that page. The panel rebuilds when the
active tab changes (MainWindow listens to QTabWidget.currentChanged).

Thumbnails are rendered without annotations (annots=False, matching
the main view's rendering convention) so the panel acts as a quick
spatial map of the source pages — annotation overlays are drawn only
in the main canvas, where they're editable.
"""
from __future__ import annotations

from typing import Optional

import fitz
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem


# Logical-pixel width for each thumbnail image. ~140 keeps the panel
# narrow while staying readable at typical viewing distance.
THUMB_WIDTH = 140


class ThumbnailPanel(QListWidget):
    """Page list that emits page_clicked(idx) when a row is clicked
    and rendering_progress(current, total) while building thumbs so
    the status bar can show a loading bar."""

    page_clicked = Signal(int)
    rendering_progress = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setViewMode(QListWidget.ListMode)
        self.setIconSize(QSize(THUMB_WIDTH, int(THUMB_WIDTH * 1.4)))
        self.setSpacing(6)
        self.setMovement(QListWidget.Static)
        self.setUniformItemSizes(False)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setMinimumWidth(THUMB_WIDTH + 36)
        self.itemClicked.connect(self._on_clicked)

    def set_document(self, doc: Optional[fitz.Document]) -> None:
        """Replace the panel contents with thumbnails of every page in
        `doc`. Passing None clears the panel. Emits
        rendering_progress(i+1, total) after each page so a status-bar
        loading indicator can advance."""
        self.clear()
        if doc is None:
            self.rendering_progress.emit(0, 0)
            return
        total = doc.page_count
        for i, page in enumerate(doc):
            page_w = page.rect.width or 1.0
            # Oversample a touch (×1.4) and let scaledToWidth down-
            # sample to THUMB_WIDTH so the result reads crisp on
            # HiDPI displays.
            scale = THUMB_WIDTH / page_w * 1.4
            try:
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    alpha=False, annots=False,
                )
            except Exception:
                continue
            img = QImage(
                pix.samples, pix.width, pix.height, pix.stride,
                QImage.Format_RGB888,
            ).copy()
            pm = QPixmap.fromImage(img).scaledToWidth(
                THUMB_WIDTH, Qt.SmoothTransformation,
            )
            item = QListWidgetItem(QIcon(pm), f"  {i + 1}")
            item.setData(Qt.UserRole, i)
            item.setSizeHint(QSize(pm.width() + 24, pm.height() + 10))
            self.addItem(item)
            self.rendering_progress.emit(i + 1, total)
        # Signal completion so the status bar can clear its progress
        # indicator even if total == 0.
        self.rendering_progress.emit(total, total)

    def set_current_page(self, idx: int) -> None:
        if 0 <= idx < self.count():
            self.setCurrentRow(idx)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        idx = item.data(Qt.UserRole)
        if idx is not None:
            self.page_clicked.emit(int(idx))
