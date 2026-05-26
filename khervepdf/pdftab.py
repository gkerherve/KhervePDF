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

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsLineItem,
    QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsScene, QGraphicsTextItem, QGraphicsView, QMessageBox,
    QPlainTextEdit, QVBoxLayout,
)


PAGE_GAP = 12  # px between stacked pages in the scene

# Per-tool default colours and widths. The toolbar's colour swatch +
# width spinbox edit these per active tab, so the user can pick once
# per session and have it stick.
# Per-tool defaults — colour, width (or font pt for text tools), and
# stroke opacity in percent (0-100). Highlight is translucent by
# default so it reads as a marker.
TOOL_DEFAULTS = {
    "pen":       {"color": "#1976d2", "width": 2.0,  "opacity": 100},
    "highlight": {"color": "#fbc02d", "width": 14.0, "opacity": 35},
    "rect":      {"color": "#388e3c", "width": 2.0,  "opacity": 100},
    "ellipse":   {"color": "#7b1fa2", "width": 2.0,  "opacity": 100},
    "line":      {"color": "#212121", "width": 2.0,  "opacity": 100},
    "arrow":     {"color": "#212121", "width": 2.0,  "opacity": 100},
    "text":      {"color": "#000000", "width": 11.0, "opacity": 100},
    "erase":     {"color": "#000000", "width": 1.0,  "opacity": 100},
    "select":    {"color": "#000000", "width": 1.0,  "opacity": 100},
    "edit_text": {"color": "#000000", "width": 11.0, "opacity": 100},
    # Tools that don't have option panels still need defaults so the
    # mousePressEvent lookup doesn't KeyError.
    "note":      {"color": "#fbc02d", "width": 1.0,  "opacity": 100},
    "signature": {"color": "#0d47a1", "width": 1.0,  "opacity": 100},
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
    opacity: int = 100  # percent, 0-100


_ALIGN_LABELS = ["Left", "Center", "Right", "Justify"]
_ALIGN_TO_FITZ = {
    "Left":    0,  # fitz.TEXT_ALIGN_LEFT
    "Center":  1,  # fitz.TEXT_ALIGN_CENTER
    "Right":   2,  # fitz.TEXT_ALIGN_RIGHT
    "Justify": 3,  # fitz.TEXT_ALIGN_JUSTIFY
}


class _EditTextDialog(QDialog):
    """Replacement editor for an existing PDF text block. Offers font
    size and alignment in addition to the raw text — without these the
    only choice was the original size, which often pushed the new text
    out of the box and produced empty output."""

    def __init__(self, parent, text: str, fontsize: float,
                 align: str = "Left") -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit text")
        self.resize(560, 380)
        layout = QVBoxLayout(self)

        self._text_edit = QPlainTextEdit(text, self)
        layout.addWidget(self._text_edit, 1)

        form = QFormLayout()
        self._size = QDoubleSpinBox(self)
        self._size.setRange(4.0, 96.0)
        self._size.setSingleStep(0.5)
        self._size.setSuffix(" pt")
        self._size.setValue(max(4.0, fontsize))
        form.addRow("Font size:", self._size)

        self._align = QComboBox(self)
        self._align.addItems(_ALIGN_LABELS)
        if align in _ALIGN_LABELS:
            self._align.setCurrentText(align)
        form.addRow("Alignment:", self._align)
        layout.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                              parent=self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)
        self._text_edit.setFocus()

    def values(self) -> tuple[str, float, int]:
        """Return (text, fontsize, fitz_align_int)."""
        return (
            self._text_edit.toPlainText(),
            float(self._size.value()),
            _ALIGN_TO_FITZ.get(self._align.currentText(), 0),
        )


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
        # 144 DPI ≈ 2x the historical 72 DPI baseline — combined with
        # devicePixelRatio oversampling in _render_all, text reads
        # crisp on both 1x and HiDPI displays.
        self._base_dpi = 144
        self._tool = "select"
        # tool -> {"color": "#hex", "width": float} (per-tab state).
        self._tool_settings = {k: dict(v) for k, v in TOOL_DEFAULTS.items()}
        # Live storage of all annotations on this document.
        self._annots: list[Annotation] = []
        # Undo/redo: each entry is a state snapshot. Annotation-only
        # actions snapshot just the annot list (cheap); actions that
        # mutate the underlying PDF (edit_text) also snapshot doc bytes.
        # Cap stacks to 20 entries to bound memory.
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._max_undo = 20
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
        # Render at logical_scale * dpr internally and tag the resulting
        # QImage with the device pixel ratio so QGraphicsPixmapItem
        # scales it back to logical pixels — page reads sharp on HiDPI
        # without bloating scene coordinates.
        dpr = self.devicePixelRatioF() or 1.0
        logical_scale = self._base_dpi / 72.0 * self._zoom
        render_scale = logical_scale * dpr
        matrix = fitz.Matrix(render_scale, render_scale)
        y = 0.0
        max_w = 0.0
        for idx, page in enumerate(self._doc):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = QImage(
                pix.samples, pix.width, pix.height, pix.stride,
                QImage.Format_RGB888,
            ).copy()
            img.setDevicePixelRatio(dpr)
            pm = QPixmap.fromImage(img)
            item = QGraphicsPixmapItem(pm)
            item.setTransformationMode(Qt.SmoothTransformation)
            item.setPos(0, y)
            item.setZValue(-1)
            self._scene.addItem(item)
            # Logical (scene-space) dimensions are the raw pixmap size
            # divided by dpr — same units as scene_to_page coordinates.
            w_logical = pix.width / dpr
            h_logical = pix.height / dpr
            self._page_layout[idx] = {
                "y_origin": y,
                "scale": logical_scale,
                "w_pt": page.rect.width,
                "h_pt": page.rect.height,
                "h_px": h_logical,
                "w_px": w_logical,
            }
            y += h_logical + PAGE_GAP
            max_w = max(max_w, w_logical)
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

    # ----- hit-test (for the eraser) -----

    @staticmethod
    def _dist_to_segment(p0: tuple[float, float], p1: tuple[float, float],
                         p: tuple[float, float]) -> float:
        x0, y0 = p0
        x1, y1 = p1
        x, y = p
        dx, dy = x1 - x0, y1 - y0
        if dx == 0 and dy == 0:
            return ((x - x0) ** 2 + (y - y0) ** 2) ** 0.5
        t = ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        px, py = x0 + t * dx, y0 + t * dy
        return ((x - px) ** 2 + (y - py) ** 2) ** 0.5

    def _find_annot_at(self, page_idx: int,
                       x_pt: float, y_pt: float,
                       tol_pt: float = 4.0) -> Optional[int]:
        """Index of the top-most annotation containing (x_pt, y_pt) in
        PDF points on page_idx, or None. Top-most = last in self._annots
        (later annotations render on top, so the eraser should pick them
        first). Tolerance widens the hit area so a thin line is still
        clickable."""
        for i in range(len(self._annots) - 1, -1, -1):
            a = self._annots[i]
            if a.page_idx != page_idx or not a.pts:
                continue
            if a.type in ("rect", "ellipse", "highlight"):
                x0, y0 = a.pts[0]
                x1, y1 = a.pts[1]
                xmin, xmax = min(x0, x1), max(x0, x1)
                ymin, ymax = min(y0, y1), max(y0, y1)
                if (xmin - tol_pt <= x_pt <= xmax + tol_pt
                        and ymin - tol_pt <= y_pt <= ymax + tol_pt):
                    return i
            elif a.type in ("line", "arrow"):
                if self._dist_to_segment(a.pts[0], a.pts[1],
                                         (x_pt, y_pt)) <= max(tol_pt, a.width):
                    return i
            elif a.type == "pen":
                for j in range(len(a.pts) - 1):
                    if self._dist_to_segment(a.pts[j], a.pts[j + 1],
                                             (x_pt, y_pt)) <= max(tol_pt,
                                                                  a.width):
                        return i
            elif a.type == "text":
                x, y = a.pts[0]
                lines = a.text.split("\n") if a.text else [""]
                # Rough bbox — Qt fonts vary, but this is generous
                # enough that the eraser feels forgiving.
                h = max(1, len(lines)) * a.width * 1.2
                w = (max(len(line) for line in lines) if a.text else 0) \
                    * a.width * 0.55
                if x - tol_pt <= x_pt <= x + w + tol_pt \
                        and y - tol_pt <= y_pt <= y + h + tol_pt:
                    return i
        return None

    # ----- undo / redo -----
    #
    # Snapshot-based. Every state-changing tool MUST call _push_undo()
    # before mutating self._annots or the underlying fitz.Document; see
    # the "Undo/Redo invariant" section in CLAUDE.md.

    def _snapshot(self, include_doc: bool = False) -> dict:
        return {
            "annots": copy.deepcopy(self._annots),
            "doc_bytes": (self._doc.tobytes()
                          if include_doc and self._doc else None),
        }

    def _push_undo(self, include_doc: bool = False) -> None:
        self._undo_stack.append(self._snapshot(include_doc))
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo(self) -> None:
        if not self._undo_stack:
            return
        snap = self._undo_stack.pop()
        # The forward state pushed to the redo stack must mirror the
        # snap we're about to apply — if the undo entry carries doc
        # bytes, the redo entry must too.
        self._redo_stack.append(
            self._snapshot(include_doc=snap.get("doc_bytes") is not None)
        )
        self._restore(snap)

    def redo(self) -> None:
        if not self._redo_stack:
            return
        snap = self._redo_stack.pop()
        self._undo_stack.append(
            self._snapshot(include_doc=snap.get("doc_bytes") is not None)
        )
        self._restore(snap)

    def _restore(self, snap: dict) -> None:
        self._annots = snap["annots"]
        doc_bytes = snap.get("doc_bytes")
        if doc_bytes is not None:
            if self._doc is not None:
                self._doc.close()
            self._doc = fitz.open(stream=doc_bytes, filetype="pdf")
        self._render_all()

    # ----- save -----

    def is_dirty(self) -> bool:
        """True if there are unsaved annotations to bake into the PDF."""
        return bool(self._annots) or self.can_undo()

    def save_to_pdf(self, dest: Optional[Path] = None) -> Path:
        """Bake every Annotation into the underlying PDF and write it.

        Saving in-place to `self.path` goes via a tempfile + os.replace
        so a failed save can't clobber the original. Save-As keeps the
        current in-memory annotations untouched by baking into a deep
        copy of the document.
        """
        if self._doc is None:
            raise RuntimeError("No document open")
        target = Path(dest) if dest is not None else self.path
        in_place = target == self.path

        if in_place:
            doc = self._doc
            self._bake_into(doc)
            tmp = target.with_suffix(target.suffix + ".kpdftmp")
            doc.save(str(tmp), deflate=True, garbage=4)
            doc.close()
            self._doc = None
            os.replace(str(tmp), str(target))
            # Reopen from disk so subsequent edits see the baked PDF.
            self._doc = fitz.open(str(target))
            # The annots have been baked into the PDF — clear them so
            # the next save doesn't double-write.
            self._annots.clear()
            self._undo_stack.clear()
            self._redo_stack.clear()
        else:
            # Save As — work on a copy so the current session keeps its
            # editable annotations.
            doc_copy = fitz.open(stream=self._doc.tobytes(), filetype="pdf")
            try:
                self._bake_into(doc_copy)
                doc_copy.save(str(target), deflate=True, garbage=4)
            finally:
                doc_copy.close()
        self._render_all()
        return target

    @staticmethod
    def _hex_to_rgb01(hex_str: str) -> tuple[float, float, float]:
        s = hex_str.lstrip("#")
        return (int(s[0:2], 16) / 255.0,
                int(s[2:4], 16) / 255.0,
                int(s[4:6], 16) / 255.0)

    def _bake_into(self, doc: fitz.Document) -> None:
        """Translate every Annotation into a real PDF annotation on
        the given document. Redactions are queued per page and applied
        at the end so the page content stream is rewritten once."""
        for a in self._annots:
            if a.page_idx >= doc.page_count:
                continue
            page = doc[a.page_idx]
            rgb = self._hex_to_rgb01(a.color)
            op = max(0.0, min(1.0, a.opacity / 100.0))
            if a.type == "pen":
                annot = page.add_ink_annot([
                    [fitz.Point(x, y) for x, y in a.pts]
                ])
                annot.set_colors(stroke=rgb)
                annot.set_border(width=max(0.5, a.width))
                annot.set_opacity(op)
                annot.update()
            elif a.type == "highlight":
                rect = fitz.Rect(a.pts[0][0], a.pts[0][1],
                                 a.pts[1][0], a.pts[1][1])
                annot = page.add_highlight_annot(rect)
                annot.set_colors(stroke=rgb)
                annot.set_opacity(op)
                annot.update()
            elif a.type == "rect":
                rect = fitz.Rect(a.pts[0][0], a.pts[0][1],
                                 a.pts[1][0], a.pts[1][1])
                annot = page.add_rect_annot(rect)
                annot.set_colors(stroke=rgb)
                annot.set_border(width=max(0.5, a.width))
                annot.set_opacity(op)
                annot.update()
            elif a.type == "ellipse":
                rect = fitz.Rect(a.pts[0][0], a.pts[0][1],
                                 a.pts[1][0], a.pts[1][1])
                annot = page.add_circle_annot(rect)
                annot.set_colors(stroke=rgb)
                annot.set_border(width=max(0.5, a.width))
                annot.set_opacity(op)
                annot.update()
            elif a.type in ("line", "arrow"):
                p1 = fitz.Point(*a.pts[0])
                p2 = fitz.Point(*a.pts[1])
                annot = page.add_line_annot(p1, p2)
                annot.set_colors(stroke=rgb)
                annot.set_border(width=max(0.5, a.width))
                annot.set_opacity(op)
                if a.type == "arrow":
                    # Newer PyMuPDF accepts string ending names; guard
                    # because the constant set has shifted across versions.
                    try:
                        annot.set_line_ends("None", "OpenArrow")
                    except Exception:
                        pass
                annot.update()
            elif a.type == "text":
                page.insert_text(
                    (a.pts[0][0], a.pts[0][1] + max(4.0, a.width)),
                    a.text, fontsize=max(4.0, a.width), color=rgb,
                )
            # Erase isn't an annotation type — it removes items from
            # self._annots at gesture time, so there's nothing to bake.

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

    def tool_opacity(self, name: Optional[str] = None) -> int:
        return int(self._tool_settings[name or self._tool].get("opacity", 100))

    def set_tool_color(self, color: str, name: Optional[str] = None) -> None:
        self._tool_settings[name or self._tool]["color"] = color

    def set_tool_width(self, w: float, name: Optional[str] = None) -> None:
        self._tool_settings[name or self._tool]["width"] = float(w)

    def set_tool_opacity(self, op: int, name: Optional[str] = None) -> None:
        self._tool_settings[name or self._tool]["opacity"] = \
            max(0, min(100, int(op)))

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
        alpha = int(max(0, min(100, a.opacity)) * 255 / 100)
        color = QColor(a.color)
        color.setAlpha(alpha)
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
            item.setBrush(QBrush(color))
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
        elif self._tool == "erase":
            # Eraser: click on the topmost annotation under the cursor
            # and remove it (with undo). Doesn't create a preview item
            # — the gesture finishes on press.
            idx = self._find_annot_at(page_idx, px, py)
            if idx is not None:
                self._push_undo()
                del self._annots[idx]
                self._render_all()
            self._drag_start = None
            self._drag_page = None
            self._preview_item = None
            event.accept()
            return
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
        opacity = self.tool_opacity()
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
        n_before = len(self._annots)
        # Snapshot before the mutation so undo restores pre-gesture
        # state. We pop the snapshot if the gesture turned out to be a
        # no-op (degenerate click, sub-pixel drag).
        self._push_undo()

        if self._tool == "pen":
            if len(self._stroke_pts_page) >= 2:
                self._annots.append(Annotation(
                    type="pen", page_idx=page, color=color, width=width,
                    pts=list(self._stroke_pts_page), opacity=opacity,
                ))
        elif self._tool == "highlight":
            self._commit_highlight(page, start_pt, end_pt, color, opacity)
        elif self._tool in ("line", "arrow", "rect", "ellipse"):
            if (abs(end_pt[0] - start_pt[0]) < 0.5
                    and abs(end_pt[1] - start_pt[1]) < 0.5):
                pass
            else:
                self._annots.append(Annotation(
                    type=self._tool, page_idx=page, color=color, width=width,
                    pts=[start_pt, end_pt], opacity=opacity,
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
        # If nothing was actually added, the undo snapshot pushed above
        # would just restore the same state — drop it to keep Ctrl+Z
        # meaningful.
        if len(self._annots) == n_before and self._undo_stack:
            self._undo_stack.pop()
        for a in self._annots[n_before:]:
            self._draw_annot(a)
        event.accept()

    # ----- highlight: snap to words -----

    def _commit_highlight(self, page_idx: int,
                          start_pt: tuple[float, float],
                          end_pt: tuple[float, float],
                          color: str, opacity: int = 35) -> None:
        """Highlight behaves like a marker: it covers the text you
        swiped over, not an empty rectangle. We pull every word whose
        bbox intersects the drag rect and create one tight highlight
        annotation per word. If the swipe hits no text (e.g. a figure
        or blank area), fall back to a freeform rect so the gesture
        isn't silently dropped."""
        if self._doc is None:
            return
        x0 = min(start_pt[0], end_pt[0])
        y0 = min(start_pt[1], end_pt[1])
        x1 = max(start_pt[0], end_pt[0])
        y1 = max(start_pt[1], end_pt[1])
        if (x1 - x0) < 0.5 and (y1 - y0) < 0.5:
            return
        drag = fitz.Rect(x0, y0, x1, y1)
        page = self._doc[page_idx]
        added = 0
        for w in page.get_text("words"):
            wx0, wy0, wx1, wy1, *_ = w
            wrect = fitz.Rect(wx0, wy0, wx1, wy1)
            if drag.intersects(wrect):
                pad = (wy1 - wy0) * 0.08
                self._annots.append(Annotation(
                    type="highlight", page_idx=page_idx,
                    color=color, width=0.0,
                    pts=[(wx0, wy0 - pad), (wx1, wy1 + pad)],
                    opacity=opacity,
                ))
                added += 1
        if added == 0:
            self._annots.append(Annotation(
                type="highlight", page_idx=page_idx,
                color=color, width=0.0,
                pts=[(x0, y0), (x1, y1)], opacity=opacity,
            ))

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
        self._push_undo()
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
        info = self._find_text_block_detailed(page, x_pt, y_pt)
        if info is None:
            QMessageBox.information(
                self, "Edit text",
                "No editable text block at that point.",
            )
            return
        dlg = _EditTextDialog(self, info["text"], info["size"], align="Left")
        if dlg.exec() != QDialog.Accepted:
            return
        new_text, requested_size, fitz_align = dlg.values()
        if new_text == info["text"] and abs(requested_size - info["size"]) < 0.1:
            return
        # Doc is about to be mutated — undo entry must include doc bytes.
        self._push_undo(include_doc=True)
        rect = fitz.Rect(*info["rect"])
        # White out the original glyphs by rewriting the page content
        # stream — without apply_redactions the new text would sit on
        # top of the old.
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()
        # Start from the size the user picked. insert_textbox returns
        # >=0 when all text fits; on overflow, shrink in 0.5pt steps
        # before falling back to a baseline insert_text.
        fontsize = max(4.0, requested_size)
        color = info["color"]
        inserted = False
        while fontsize >= 4.0:
            rc = page.insert_textbox(
                rect, new_text, fontsize=fontsize, color=color,
                align=fitz_align,
            )
            if rc >= 0:
                inserted = True
                break
            fontsize -= 0.5
        if not inserted:
            page.insert_text(
                (rect.x0, rect.y0 + max(4.0, requested_size)),
                new_text, fontsize=max(4.0, requested_size), color=color,
            )
        self._render_all()

    def _find_text_block_detailed(self, page: fitz.Page,
                                  x_pt: float, y_pt: float):
        """Locate the text block at (x_pt, y_pt) and pull the first
        span's font size and colour so the replacement matches roughly.
        get_text("blocks") only returns the bbox+text — we need the
        richer dict form to recover font metrics."""
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            if block.get("type") != 0:
                continue
            x0, y0, x1, y1 = block["bbox"]
            if not (x0 <= x_pt <= x1 and y0 <= y_pt <= y1):
                continue
            lines_text: list[str] = []
            first_span = None
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                if first_span is None:
                    first_span = spans[0]
                lines_text.append("".join(s.get("text", "") for s in spans))
            if first_span is None or not lines_text:
                continue
            raw_color = int(first_span.get("color", 0))
            r = ((raw_color >> 16) & 0xff) / 255.0
            g = ((raw_color >> 8) & 0xff) / 255.0
            b = (raw_color & 0xff) / 255.0
            return {
                "rect": (x0, y0, x1, y1),
                "text": "\n".join(lines_text).rstrip(),
                "size": float(first_span.get("size", 11.0)),
                "color": (r, g, b),
            }
        return None
