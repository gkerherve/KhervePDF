"""Single-PDF tab: renders pages with PyMuPDF inside a QGraphicsView.

v0.4 — annotations live in *page* coordinates (PDF points), so they
survive zoom/scroll/re-render; per-tool colour and width are honoured;
the Text tool drops an editable text box; the Edit-Text tool rewrites a
text block on the underlying PDF page via PyMuPDF redaction + insert.

Storage model:
  * `self._annots: list[Annotation]` — geometry stored in PDF points
    on a specific page.
  * `self._page_layout` maps page index to its origin/scale in scene
    pixels, computed afresh in `_render_all()`.
  * `_scene_to_page` / `_page_to_scene` convert between the two.

When `document.py` lands these will move there and become the single
source of truth (CLAUDE.md); for now PdfTab owns them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsLineItem,
    QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsScene, QGraphicsTextItem, QGraphicsView, QInputDialog,
    QMessageBox,
)


PAGE_GAP = 12  # px between stacked pages in the scene

# Per-tool default colours and widths. The toolbar's colour swatch +
# width spinbox edit these per active tab, so the user can pick once
# per session and have it stick.
TOOL_DEFAULTS = {
    "pen":       {"color": "#1976d2", "width": 2.0},
    "highlight": {"color": "#fbc02d", "width": 14.0},
    "rect":      {"color": "#388e3c", "width": 2.0},
    "ellipse":   {"color": "#7b1fa2", "width": 2.0},
    "line":      {"color": "#212121", "width": 2.0},
    "arrow":     {"color": "#212121", "width": 2.0},
    "text":      {"color": "#000000", "width": 11.0},   # width = font pt
    "redact":    {"color": "#000000", "width": 1.0},
    "select":    {"color": "#000000", "width": 1.0},
    "edit_text": {"color": "#000000", "width": 11.0},
}


@dataclass
class Annotation:
    """Geometry in PDF points relative to a specific page.

    `pts` semantics depend on `type`:
      * pen           — polyline (n points)
      * line / arrow  — [start, end]
      * rect / ellipse / highlight / redact — [top_left, bottom_right]
      * text          — [anchor]
    """
    type: str
    page_idx: int
    color: str
    width: float
    pts: list[tuple[float, float]] = field(default_factory=list)
    text: str = ""


class _EditableTextItem(QGraphicsTextItem):
    """QGraphicsTextItem that commits its text back to the owning tab on
    focus loss, so a placed text annotation persists into self._annots
    and survives re-renders."""

    def __init__(self, tab: "PdfTab", page_idx: int,
                 anchor_pt: tuple[float, float], color: str,
                 fontsize: float, initial: str = "") -> None:
        super().__init__(initial)
        self._tab = tab
        self._page_idx = page_idx
        self._anchor_pt = anchor_pt
        self._color = color
        self._fontsize = fontsize
        self.setDefaultTextColor(QColor(color))
        f = QFont()
        f.setPointSizeF(max(4.0, fontsize))
        self.setFont(f)
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

    def focusOutEvent(self, ev):  # noqa: N802
        super().focusOutEvent(ev)
        text = self.toPlainText().strip()
        if not text:
            self._tab._cancel_text_item(self)
            return
        self._tab._commit_text_item(
            self._page_idx, self._anchor_pt, text,
            self._color, self._fontsize,
        )


class PdfTab(QGraphicsView):
    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self._doc: Optional[fitz.Document] = None
        self._zoom = 1.0
        self._base_dpi = 110
        self._tool = "select"
        # tool -> {"color": "#hex", "width": float} (per-tab state).
        self._tool_settings = {k: dict(v) for k, v in TOOL_DEFAULTS.items()}
        # Live storage of all annotations on this document.
        self._annots: list[Annotation] = []
        # page_idx -> dict(y_origin, scale, w_pt, h_pt, pixmap_h_px)
        self._page_layout: dict[int, dict] = {}
        # Preview state while dragging.
        self._drag_start: Optional[QPointF] = None
        self._drag_page: Optional[int] = None
        self._preview_item: Optional[QGraphicsItem] = None
        self._stroke_path: Optional[QPainterPath] = None
        self._stroke_pts_page: list[tuple[float, float]] = []

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
        self._page_layout.clear()
        if self._doc is None:
            return
        scale = self._base_dpi / 72.0 * self._zoom  # px per PDF point
        matrix = fitz.Matrix(scale, scale)
        y = 0.0
        max_w = 0.0
        for idx, page in enumerate(self._doc):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = QImage(
                pix.samples, pix.width, pix.height, pix.stride,
                QImage.Format_RGB888,
            ).copy()
            item = QGraphicsPixmapItem(QPixmap.fromImage(img))
            item.setPos(0, y)
            item.setZValue(-1)
            self._scene.addItem(item)
            self._page_layout[idx] = {
                "y_origin": y,
                "scale": scale,
                "w_pt": page.rect.width,
                "h_pt": page.rect.height,
                "h_px": pix.height,
                "w_px": pix.width,
            }
            y += pix.height + PAGE_GAP
            max_w = max(max_w, float(pix.width))
        self._scene.setSceneRect(QRectF(0, 0, max_w, max(0.0, y - PAGE_GAP)))
        self._replay_annots()

    def _replay_annots(self) -> None:
        for a in self._annots:
            self._draw_annot(a)

    # ----- coord conversion -----

    def _scene_to_page(self, p: QPointF) -> Optional[tuple[int, float, float]]:
        """Map a scene point to (page_idx, x_pt, y_pt). None if the
        point lies in the gap between pages."""
        for idx, lay in self._page_layout.items():
            y0 = lay["y_origin"]
            if y0 <= p.y() <= y0 + lay["h_px"] and 0 <= p.x() <= lay["w_px"]:
                scale = lay["scale"]
                return idx, p.x() / scale, (p.y() - y0) / scale
        return None

    def _page_to_scene(self, page_idx: int,
                       x_pt: float, y_pt: float) -> QPointF:
        lay = self._page_layout[page_idx]
        return QPointF(x_pt * lay["scale"],
                       lay["y_origin"] + y_pt * lay["scale"])

    def _clamp_to_page(self, page_idx: int,
                       x_pt: float, y_pt: float) -> tuple[float, float]:
        lay = self._page_layout[page_idx]
        return (max(0.0, min(x_pt, lay["w_pt"])),
                max(0.0, min(y_pt, lay["h_pt"])))

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

    def tool_color(self, name: Optional[str] = None) -> str:
        return self._tool_settings[name or self._tool]["color"]

    def tool_width(self, name: Optional[str] = None) -> float:
        return self._tool_settings[name or self._tool]["width"]

    def set_tool_color(self, color: str, name: Optional[str] = None) -> None:
        self._tool_settings[name or self._tool]["color"] = color

    def set_tool_width(self, w: float, name: Optional[str] = None) -> None:
        self._tool_settings[name or self._tool]["width"] = float(w)

    def _apply_drag_mode(self) -> None:
        if self._tool == "select":
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.viewport().setCursor(Qt.OpenHandCursor)
        else:
            self.setDragMode(QGraphicsView.NoDrag)
            cursor = Qt.IBeamCursor if self._tool in ("text", "edit_text") \
                else Qt.CrossCursor
            self.viewport().setCursor(cursor)

    # ----- annotation drawing (page-coord -> scene items) -----

    def _qcolor(self, hex_str: str, alpha: int = 255) -> QColor:
        c = QColor(hex_str)
        c.setAlpha(alpha)
        return c

    def _draw_annot(self, a: Annotation) -> None:
        if a.page_idx not in self._page_layout:
            return
        scale = self._page_layout[a.page_idx]["scale"]
        color = QColor(a.color)
        pw_px = a.width * scale

        if a.type == "pen":
            if len(a.pts) < 2:
                return
            path = QPainterPath()
            first = self._page_to_scene(a.page_idx, *a.pts[0])
            path.moveTo(first)
            for x_pt, y_pt in a.pts[1:]:
                path.lineTo(self._page_to_scene(a.page_idx, x_pt, y_pt))
            item = QGraphicsPathItem(path)
            item.setPen(QPen(color, pw_px, Qt.SolidLine,
                             Qt.RoundCap, Qt.RoundJoin))
            self._scene.addItem(item)
        elif a.type in ("line", "arrow"):
            s = self._page_to_scene(a.page_idx, *a.pts[0])
            e = self._page_to_scene(a.page_idx, *a.pts[1])
            item = QGraphicsLineItem(s.x(), s.y(), e.x(), e.y())
            item.setPen(QPen(color, pw_px, Qt.SolidLine, Qt.RoundCap))
            self._scene.addItem(item)
            if a.type == "arrow":
                self._add_arrow_head(s, e, color, pw_px)
        elif a.type == "rect":
            r = self._rect_from_pts(a)
            item = QGraphicsRectItem(r)
            item.setPen(QPen(color, pw_px))
            self._scene.addItem(item)
        elif a.type == "ellipse":
            item = QGraphicsEllipseItem(self._rect_from_pts(a))
            item.setPen(QPen(color, pw_px))
            self._scene.addItem(item)
        elif a.type == "highlight":
            r = self._rect_from_pts(a)
            item = QGraphicsRectItem(r)
            item.setPen(QPen(Qt.NoPen))
            item.setBrush(QBrush(self._qcolor(a.color, alpha=90)))
            self._scene.addItem(item)
        elif a.type == "redact":
            r = self._rect_from_pts(a)
            item = QGraphicsRectItem(r)
            item.setPen(QPen(Qt.black, 1))
            item.setBrush(QBrush(QColor(0, 0, 0, 220)))
            self._scene.addItem(item)
        elif a.type == "text":
            anchor = self._page_to_scene(a.page_idx, *a.pts[0])
            item = QGraphicsTextItem(a.text)
            f = QFont()
            f.setPointSizeF(a.width * scale * 72.0 / self._base_dpi
                            / self._zoom)
            # ^ width is stored in pt; convert back to point-size for Qt
            f.setPointSizeF(max(4.0, a.width))
            item.setFont(f)
            item.setDefaultTextColor(color)
            item.setPos(anchor)
            self._scene.addItem(item)

    def _rect_from_pts(self, a: Annotation) -> QRectF:
        p0 = self._page_to_scene(a.page_idx, *a.pts[0])
        p1 = self._page_to_scene(a.page_idx, *a.pts[1])
        return QRectF(p0, p1).normalized()

    def _add_arrow_head(self, s: QPointF, e: QPointF,
                        color: QColor, w: float) -> None:
        from math import atan2, cos, sin
        ang = atan2(e.y() - s.y(), e.x() - s.x())
        head = max(8.0, w * 3.0)
        spread = 0.5
        p1 = QPointF(e.x() - head * cos(ang - spread),
                     e.y() - head * sin(ang - spread))
        p2 = QPointF(e.x() - head * cos(ang + spread),
                     e.y() - head * sin(ang + spread))
        for p in (p1, p2):
            ln = QGraphicsLineItem(e.x(), e.y(), p.x(), p.y())
            ln.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap))
            self._scene.addItem(ln)

    # ----- mouse: drawing -----

    def mousePressEvent(self, event):  # noqa: N802
        if self._tool == "select" or event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        scene_pt = self.mapToScene(event.position().toPoint())
        mapped = self._scene_to_page(scene_pt)
        if mapped is None:
            return super().mousePressEvent(event)
        page_idx, px, py = mapped
        self._drag_start = scene_pt
        self._drag_page = page_idx
        color_hex = self.tool_color()
        width = self.tool_width()
        qcolor = QColor(color_hex)

        if self._tool == "pen":
            self._stroke_path = QPainterPath(scene_pt)
            self._stroke_pts_page = [(px, py)]
            item = QGraphicsPathItem(self._stroke_path)
            scale = self._page_layout[page_idx]["scale"]
            item.setPen(QPen(qcolor, width * scale, Qt.SolidLine,
                             Qt.RoundCap, Qt.RoundJoin))
            self._scene.addItem(item)
            self._preview_item = item
        elif self._tool in ("line", "arrow"):
            scale = self._page_layout[page_idx]["scale"]
            item = QGraphicsLineItem(scene_pt.x(), scene_pt.y(),
                                     scene_pt.x(), scene_pt.y())
            item.setPen(QPen(qcolor, width * scale, Qt.SolidLine,
                             Qt.RoundCap))
            self._scene.addItem(item)
            self._preview_item = item
        elif self._tool in ("rect", "ellipse"):
            scale = self._page_layout[page_idx]["scale"]
            cls = QGraphicsRectItem if self._tool == "rect" \
                else QGraphicsEllipseItem
            item = cls(QRectF(scene_pt, scene_pt))
            item.setPen(QPen(qcolor, width * scale))
            self._scene.addItem(item)
            self._preview_item = item
        elif self._tool == "highlight":
            item = QGraphicsRectItem(QRectF(scene_pt, scene_pt))
            item.setPen(QPen(Qt.NoPen))
            item.setBrush(QBrush(self._qcolor(color_hex, alpha=90)))
            self._scene.addItem(item)
            self._preview_item = item
        elif self._tool == "redact":
            item = QGraphicsRectItem(QRectF(scene_pt, scene_pt))
            item.setPen(QPen(Qt.black, 1))
            item.setBrush(QBrush(QColor(0, 0, 0, 220)))
            self._scene.addItem(item)
            self._preview_item = item
        elif self._tool == "text":
            self._place_text_box(page_idx, (px, py), color_hex, width)
            self._drag_start = None
            self._drag_page = None
        elif self._tool == "edit_text":
            self._edit_existing_text(page_idx, px, py)
            self._drag_start = None
            self._drag_page = None
        else:
            return super().mousePressEvent(event)
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._preview_item is None:
            return super().mouseMoveEvent(event)
        scene_pt = self.mapToScene(event.position().toPoint())
        # Lock to the page where the drag started.
        if self._tool == "pen" and self._stroke_path is not None:
            self._stroke_path.lineTo(scene_pt)
            self._preview_item.setPath(self._stroke_path)
            mapped = self._scene_to_page(scene_pt)
            if mapped is not None and mapped[0] == self._drag_page:
                self._stroke_pts_page.append((mapped[1], mapped[2]))
        elif self._tool in ("line", "arrow"):
            s = self._drag_start
            self._preview_item.setLine(s.x(), s.y(),
                                       scene_pt.x(), scene_pt.y())
        elif self._tool in ("rect", "ellipse", "highlight", "redact"):
            self._preview_item.setRect(
                QRectF(self._drag_start, scene_pt).normalized()
            )
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._preview_item is None or self._drag_page is None:
            return super().mouseReleaseEvent(event)
        scene_end = self.mapToScene(event.position().toPoint())
        page = self._drag_page
        # Convert preview into a stored Annotation in page coords.
        color = self.tool_color()
        width = self.tool_width()
        mapped_end = self._scene_to_page(scene_end)
        end_pt: tuple[float, float]
        if mapped_end is not None and mapped_end[0] == page:
            end_pt = (mapped_end[1], mapped_end[2])
        else:
            # User dragged off the page — clamp to the start page.
            lay = self._page_layout[page]
            end_pt = (
                max(0.0, min(scene_end.x() / lay["scale"], lay["w_pt"])),
                max(0.0, min((scene_end.y() - lay["y_origin"]) / lay["scale"],
                             lay["h_pt"])),
            )
        start_mapped = self._scene_to_page(self._drag_start)
        start_pt = (start_mapped[1], start_mapped[2]) if start_mapped \
            else (0.0, 0.0)
        end_pt = self._clamp_to_page(page, *end_pt)
        start_pt = self._clamp_to_page(page, *start_pt)

        if self._tool == "pen":
            if len(self._stroke_pts_page) >= 2:
                self._annots.append(Annotation(
                    type="pen", page_idx=page, color=color, width=width,
                    pts=list(self._stroke_pts_page),
                ))
        elif self._tool in ("line", "arrow", "rect", "ellipse",
                            "highlight", "redact"):
            # Skip degenerate clicks.
            if (abs(end_pt[0] - start_pt[0]) < 0.5
                    and abs(end_pt[1] - start_pt[1]) < 0.5):
                pass
            else:
                self._annots.append(Annotation(
                    type=self._tool, page_idx=page, color=color, width=width,
                    pts=[start_pt, end_pt],
                ))

        # Drop the preview; the replay path will redraw from storage so
        # the stored geometry is what gets shown going forward.
        if self._preview_item is not None:
            self._scene.removeItem(self._preview_item)
        self._preview_item = None
        self._stroke_path = None
        self._stroke_pts_page = []
        self._drag_start = None
        self._drag_page = None
        if self._annots:
            self._draw_annot(self._annots[-1])
        event.accept()

    # ----- text tool -----

    def _place_text_box(self, page_idx: int,
                        anchor_pt: tuple[float, float],
                        color: str, fontsize: float) -> None:
        scene_pt = self._page_to_scene(page_idx, *anchor_pt)
        item = _EditableTextItem(self, page_idx, anchor_pt, color, fontsize)
        item.setPos(scene_pt)
        self._scene.addItem(item)
        item.setFocus()

    def _commit_text_item(self, page_idx: int,
                          anchor_pt: tuple[float, float], text: str,
                          color: str, fontsize: float) -> None:
        self._annots.append(Annotation(
            type="text", page_idx=page_idx, color=color, width=fontsize,
            pts=[anchor_pt], text=text,
        ))
        # The editable item was a one-shot; replace by a clean render so
        # subsequent zooms recreate it from storage.
        self._render_all()

    def _cancel_text_item(self, item: _EditableTextItem) -> None:
        if item.scene() is self._scene:
            self._scene.removeItem(item)

    # ----- edit existing PDF text -----
    #
    # Reason this is its own tool, not a generic "click and type": PDFs
    # don't store editable paragraphs — they store positioned glyphs.
    # The MVP here finds the block at the click point, redacts it, and
    # re-inserts the user's new text using a default font. Font matching
    # and layout reflow are deliberately out of scope for v0.4.

    def _edit_existing_text(self, page_idx: int,
                            x_pt: float, y_pt: float) -> None:
        if self._doc is None:
            return
        page = self._doc[page_idx]
        block = self._find_text_block(page, x_pt, y_pt)
        if block is None:
            QMessageBox.information(
                self, "Edit text",
                "No editable text block at that point.",
            )
            return
        x0, y0, x1, y1, original_text = block
        new_text, ok = QInputDialog.getMultiLineText(
            self, "Edit text", "Replace this block:", original_text,
        )
        if not ok or new_text == original_text:
            return
        # White-out the original block, then re-insert with the new
        # string. Font face won't match the original — see module note.
        rect = fitz.Rect(x0, y0, x1, y1)
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()
        page.insert_textbox(
            rect, new_text,
            fontsize=11, color=(0, 0, 0), align=fitz.TEXT_ALIGN_LEFT,
        )
        self._render_all()

    def _find_text_block(self, page: fitz.Page,
                         x_pt: float, y_pt: float):
        for b in page.get_text("blocks"):
            x0, y0, x1, y1, text, *_ = b
            if (x0 <= x_pt <= x1 and y0 <= y_pt <= y1
                    and text and text.strip()):
                return x0, y0, x1, y1, text.rstrip("\n")
        return None
