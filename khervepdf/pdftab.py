"""Single-PDF tab: renders pages with PyMuPDF inside a QGraphicsView.

This is the v0.2 first cut — enough to open a PDF and scroll through its
pages with zoom in/out and fit-width. Annotation tools, search, and the
git backend layer on top of this in later commits. `document.py` becomes
the single source of truth (CLAUDE.md); for now `PdfTab` owns its own
`fitz.Document` directly until that module lands.
"""
from __future__ import annotations

from pathlib import Path

import fitz
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem, QGraphicsScene, QGraphicsView,
)


PAGE_GAP = 12  # px between stacked pages in the scene


class PdfTab(QGraphicsView):
    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self._doc: fitz.Document | None = None
        self._zoom = 1.0  # logical scale applied on top of base render DPI
        self._base_dpi = 110

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform
        )
        self.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.setBackgroundBrush(Qt.gray)
        self.setDragMode(QGraphicsView.ScrollHandDrag)

        self._open()

    # ----- doc lifecycle -----

    def _open(self) -> None:
        self._doc = fitz.open(str(self.path))
        self._render_all()

    def close_doc(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    # ----- rendering -----

    def _render_all(self) -> None:
        self._scene.clear()
        if self._doc is None:
            return
        scale = self._base_dpi / 72.0 * self._zoom
        matrix = fitz.Matrix(scale, scale)
        y = 0.0
        max_w = 0.0
        for page in self._doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = QImage(
                pix.samples, pix.width, pix.height, pix.stride,
                QImage.Format_RGB888,
            ).copy()
            item = QGraphicsPixmapItem(QPixmap.fromImage(img))
            item.setPos(0, y)
            self._scene.addItem(item)
            y += pix.height + PAGE_GAP
            max_w = max(max_w, float(pix.width))
        self._scene.setSceneRect(QRectF(0, 0, max_w, max(0.0, y - PAGE_GAP)))

    # ----- zoom -----

    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    def zoom_percent(self) -> int:
        return int(round(self._zoom * 100))

    def zoom_in(self) -> None:
        self._set_zoom(self._zoom * 1.25)

    def zoom_out(self) -> None:
        self._set_zoom(self._zoom / 1.25)

    def fit_width(self) -> None:
        if self._doc is None or self._doc.page_count == 0:
            return
        page = self._doc[0]
        page_w_pt = page.rect.width
        # viewport width in px we want to fill, minus a small margin
        view_w = max(1, self.viewport().width() - 24)
        target_px = view_w
        # base render at base_dpi -> base_dpi/72 px per pt; new zoom solves
        # target_px == (base_dpi/72)*new_zoom*page_w_pt
        new_zoom = target_px / ((self._base_dpi / 72.0) * page_w_pt)
        self._set_zoom(new_zoom)

    def _set_zoom(self, z: float) -> None:
        z = max(0.1, min(z, 8.0))
        if abs(z - self._zoom) < 1e-3:
            return
        self._zoom = z
        self._render_all()
