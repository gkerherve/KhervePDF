"""Single-PDF tab: renders pages with PyMuPDF inside a QGraphicsView.

v0.3 — tools draw live on the scene.

The reason editing did nothing before v0.3 is that the toolbar's tool
buttons were wired to a no-op stub. PdfTab now owns a current-tool name
and intercepts mouse events on the scene: Pen drops freehand strokes,
Rectangle / Ellipse / Line drag-draw shapes, Highlight paints a
translucent yellow rectangle. Annotations live as QGraphicsItems above
the page pixmap. Persisting them back into the PDF (via PyMuPDF's
add_ink_annot / add_rect_annot / apply_redactions) lands when
`document.py` becomes the source of truth.
"""
from __future__ import annotations

from pathlib import Path

import fitz
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsLineItem,
    QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsScene, QGraphicsView,
)


PAGE_GAP = 12  # px between stacked pages in the scene

# Default per-tool stroke / fill. Mirrors the icon palette so the
# coloured pen icon matches the colour the pen actually draws.
TOOL_COLORS = {
    "pen":       QColor("#1976d2"),
    "highlight": QColor(251, 192, 45, 90),   # translucent yellow
    "rect":      QColor("#388e3c"),
    "ellipse":   QColor("#7b1fa2"),
    "line":      QColor("#212121"),
    "arrow":     QColor("#212121"),
    "redact":    QColor(0, 0, 0, 220),
}


class PdfTab(QGraphicsView):
    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self._doc: fitz.Document | None = None
        self._zoom = 1.0
        self._base_dpi = 110
        self._tool = "select"
        self._pen_width = 2.0
        self._drag_start: QPointF | None = None
        self._preview_item: QGraphicsItem | None = None
        self._stroke_path: QPainterPath | None = None

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform
        )
        self.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.setBackgroundBrush(Qt.gray)
        self._apply_drag_mode()

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
        self._preview_item = None
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
            item.setZValue(-1)  # annotations draw on top
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
        page_w_pt = self._doc[0].rect.width
        view_w = max(1, self.viewport().width() - 24)
        new_zoom = view_w / ((self._base_dpi / 72.0) * page_w_pt)
        self._set_zoom(new_zoom)

    def _set_zoom(self, z: float) -> None:
        z = max(0.1, min(z, 8.0))
        if abs(z - self._zoom) < 1e-3:
            return
        self._zoom = z
        self._render_all()

    # ----- tools -----

    def set_tool(self, name: str) -> None:
        self._tool = name
        self._apply_drag_mode()

    def current_tool(self) -> str:
        return self._tool

    def set_pen_width(self, w: float) -> None:
        self._pen_width = max(0.5, float(w))

    def _apply_drag_mode(self) -> None:
        # Select tool pans the page; any drawing tool needs raw mouse
        # events so we disable ScrollHandDrag.
        if self._tool == "select":
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.viewport().setCursor(Qt.OpenHandCursor)
        else:
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(Qt.CrossCursor)

    # ----- mouse: drawing -----

    def mousePressEvent(self, event):  # noqa: N802
        if self._tool == "select" or event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        pos = self.mapToScene(event.position().toPoint())
        self._drag_start = pos
        color = TOOL_COLORS.get(self._tool, QColor("#212121"))

        if self._tool == "pen":
            self._stroke_path = QPainterPath(pos)
            item = QGraphicsPathItem(self._stroke_path)
            item.setPen(QPen(color, self._pen_width, Qt.SolidLine,
                             Qt.RoundCap, Qt.RoundJoin))
            self._scene.addItem(item)
            self._preview_item = item
        elif self._tool in ("line", "arrow"):
            item = QGraphicsLineItem(pos.x(), pos.y(), pos.x(), pos.y())
            item.setPen(QPen(color, self._pen_width, Qt.SolidLine,
                             Qt.RoundCap))
            self._scene.addItem(item)
            self._preview_item = item
        elif self._tool == "rect":
            item = QGraphicsRectItem(QRectF(pos, pos))
            item.setPen(QPen(color, self._pen_width))
            self._scene.addItem(item)
            self._preview_item = item
        elif self._tool == "ellipse":
            item = QGraphicsEllipseItem(QRectF(pos, pos))
            item.setPen(QPen(color, self._pen_width))
            self._scene.addItem(item)
            self._preview_item = item
        elif self._tool == "highlight":
            item = QGraphicsRectItem(QRectF(pos, pos))
            item.setPen(QPen(Qt.NoPen))
            item.setBrush(QBrush(color))
            self._scene.addItem(item)
            self._preview_item = item
        elif self._tool == "redact":
            item = QGraphicsRectItem(QRectF(pos, pos))
            item.setPen(QPen(Qt.black, 1))
            item.setBrush(QBrush(color))
            self._scene.addItem(item)
            self._preview_item = item
        else:
            return super().mousePressEvent(event)
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._tool == "select" or self._preview_item is None:
            return super().mouseMoveEvent(event)
        pos = self.mapToScene(event.position().toPoint())
        if self._tool == "pen" and self._stroke_path is not None:
            self._stroke_path.lineTo(pos)
            self._preview_item.setPath(self._stroke_path)
        elif self._tool in ("line", "arrow"):
            s = self._drag_start
            self._preview_item.setLine(s.x(), s.y(), pos.x(), pos.y())
        elif self._tool in ("rect", "ellipse", "highlight", "redact"):
            self._preview_item.setRect(
                QRectF(self._drag_start, pos).normalized()
            )
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._tool == "select" or self._preview_item is None:
            return super().mouseReleaseEvent(event)
        self._preview_item = None
        self._stroke_path = None
        self._drag_start = None
        event.accept()
