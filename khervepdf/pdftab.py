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
import html as html_mod
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz
from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import (
    QAction, QActionGroup, QBrush, QColor, QFont, QImage, QPainter,
    QPainterPath, QPen, QPixmap, QTextBlockFormat, QTextCharFormat,
    QTextCursor, QTextDocumentFragment,
)
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFontComboBox,
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsLineItem,
    QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsScene, QGraphicsTextItem, QGraphicsView, QInputDialog,
    QLabel, QMessageBox, QTextEdit, QToolBar, QVBoxLayout,
)

from .icons import icon


PAGE_GAP = 12  # px between stacked pages in the scene

# Per-tool default colours and widths. The toolbar's colour swatch +
# width spinbox edit these per active tab, so the user can pick once
# per session and have it stick.
# Per-tool defaults — colour, width (or font pt for text tools), and
# stroke opacity in percent (0-100). Highlight is translucent by
# default so it reads as a marker.
TOOL_DEFAULTS = {
    "hand":      {"color": "#000000", "width": 1.0,  "opacity": 100},
    "pen":       {"color": "#1976d2", "width": 2.0,  "opacity": 100},
    "highlight": {"color": "#fbc02d", "width": 14.0, "opacity": 35},
    "rect":      {"color": "#388e3c", "width": 2.0,  "opacity": 100, "filled": False, "fill_color": None},
    "ellipse":   {"color": "#7b1fa2", "width": 2.0,  "opacity": 100, "filled": False, "fill_color": None},
    "line":      {"color": "#212121", "width": 2.0,  "opacity": 100},
    "arrow":     {"color": "#212121", "width": 2.0,  "opacity": 100},
    "text":      {"color": "#000000", "width": 11.0, "opacity": 100},
    "erase":     {"color": "#000000", "width": 1.0,  "opacity": 100},
    "select":    {"color": "#000000", "width": 1.0,  "opacity": 100},
    "edit_text": {"color": "#000000", "width": 11.0, "opacity": 100},
    "move_text": {"color": "#000000", "width": 1.0,  "opacity": 100},
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
    filled: bool = False  # rect / ellipse interior fill
    # Optional separate fill colour for rect / ellipse. None means
    # "fall back to the stroke colour" (the v0.14 behaviour).
    fill_color: Optional[str] = None
    # Text-annotation rotation in degrees (0 / 90 / 180 / 270). 0 for
    # everything else.
    rotation: int = 0


_FONT_SIZES = [6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48]


class _EditTextDialog(QDialog):
    """Rich-text editor for replacing an existing PDF block.

    A QToolBar holds the format actions (font size, bold / italic /
    underline, super / sub, alignment); the body is a QTextEdit. On
    accept we hand the HTML to PyMuPDF's `insert_htmlbox`, which
    natively honours alignment, font sizes, and super/subscript — so
    earlier shrink-to-fit hackery is gone.
    """

    def __init__(self, parent, html_or_text: str, fontsize: float,
                 is_html: bool = False, align: str = "left",
                 preserve_line_breaks: bool = False,
                 font_family: str = "",
                 rotation: int = 0,
                 title: str = "Edit text") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 520)
        # Snapshot the inputs so toggling "Preserve line breaks" can
        # re-render the editor without re-querying the document.
        self._initial_is_html = is_html
        self._initial_content = html_or_text
        self._initial_fontsize = float(max(4.0, fontsize))
        self._initial_font_family = font_family
        layout = QVBoxLayout(self)

        # ----- Toolbar -----
        tb = QToolBar(self)
        tb.setIconSize(tb.iconSize())
        layout.addWidget(tb)

        tb.addWidget(QLabel(" Font: "))
        self._font_combo = QFontComboBox(self)
        self._font_combo.setMaximumWidth(180)
        if font_family:
            self._font_combo.setCurrentFont(QFont(font_family))
        self._font_combo.currentFontChanged.connect(self._on_font)
        tb.addWidget(self._font_combo)
        tb.addSeparator()

        tb.addWidget(QLabel(" Size: "))
        self._size_combo = QComboBox(self)
        self._size_combo.setEditable(True)
        self._size_combo.setMaximumWidth(80)
        for sz in _FONT_SIZES:
            self._size_combo.addItem(str(sz))
        self._size_combo.setCurrentText(str(int(round(max(4.0, fontsize)))))
        self._size_combo.editTextChanged.connect(self._on_size)
        tb.addWidget(self._size_combo)
        tb.addSeparator()

        self._bold = self._toggle(tb, "bold",      "Bold (Ctrl+B)",      self._on_bold)
        self._italic = self._toggle(tb, "italic",  "Italic (Ctrl+I)",    self._on_italic)
        self._underline = self._toggle(tb, "underline", "Underline (Ctrl+U)", self._on_underline)
        tb.addSeparator()
        self._super = self._toggle(tb, "superscript", "Superscript", self._on_super)
        self._sub   = self._toggle(tb, "subscript",   "Subscript",   self._on_sub)
        tb.addSeparator()

        self._align_group = QActionGroup(self)
        self._align_group.setExclusive(True)
        self._align_acts: dict[str, QAction] = {}
        for name, label, flag in (
            ("align_left",    "Align left",   Qt.AlignLeft),
            ("align_center",  "Align center", Qt.AlignHCenter),
            ("align_right",   "Align right",  Qt.AlignRight),
            ("align_justify", "Justify",      Qt.AlignJustify),
        ):
            act = QAction(icon(name), label, self, checkable=True)
            act.triggered.connect(
                lambda _c=False, f=flag: self._editor.setAlignment(f)
            )
            self._align_group.addAction(act)
            self._align_acts[name] = act
            tb.addAction(act)
        # Pre-select the alignment passed in (defaults to left). The
        # editor's QTextBlockFormat is updated after the content has
        # been loaded below so it actually takes effect.
        align_map = {
            "left":    ("align_left",    Qt.AlignLeft),
            "center":  ("align_center",  Qt.AlignHCenter),
            "right":   ("align_right",   Qt.AlignRight),
            "justify": ("align_justify", Qt.AlignJustify),
        }
        initial_act_name, self._initial_qt_align = align_map.get(
            align, align_map["left"]
        )
        self._align_acts[initial_act_name].setChecked(True)
        tb.addSeparator()

        # Rotation combobox — applies to the whole text annotation
        # on save (text reads vertically / upside down). 0° is the
        # default and matches "normal" reading direction.
        tb.addWidget(QLabel(" Rotation: "))
        self._rotation_combo = QComboBox(self)
        for deg in (0, 90, 180, 270):
            self._rotation_combo.addItem(f"{deg}°", deg)
        # Pick the entry that matches the passed-in rotation.
        for i in range(self._rotation_combo.count()):
            if self._rotation_combo.itemData(i) == int(rotation):
                self._rotation_combo.setCurrentIndex(i)
                break
        tb.addWidget(self._rotation_combo)

        # "Preserve PDF line breaks" — controls how the original
        # paragraph is displayed in the editor. State persists in
        # QSettings("kherve","KhervePDF")/preserve_line_breaks. The
        # save path always strips <br> before insert_htmlbox so the
        # rewritten text reflows naturally regardless of this state.
        tb.addSeparator()
        from PySide6.QtCore import QSettings as _QS
        from PySide6.QtWidgets import QCheckBox as _QC
        self._preserve_chk = _QC("Preserve PDF line breaks", self)
        self._preserve_chk.setToolTip(
            "Show the paragraph with the original PDF line breaks "
            "(e.g. \"flex- ibility\" on separate lines). Takes effect "
            "next time you open Edit Text."
        )
        self._preserve_chk.setChecked(bool(preserve_line_breaks))
        self._preserve_chk.toggled.connect(self._on_preserve_toggled)
        tb.addWidget(self._preserve_chk)

        # ----- Editor -----
        self._editor = QTextEdit(self)
        self._editor.setAcceptRichText(True)
        self._reload_initial_content(preserve_line_breaks)
        self._editor.currentCharFormatChanged.connect(self._sync_toolbar)
        self._editor.cursorPositionChanged.connect(self._sync_toolbar)
        layout.addWidget(self._editor, 1)

        # ----- OK / Cancel -----
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                              parent=self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)
        self._editor.setFocus()

    # ----- toolbar helpers -----

    def _toggle(self, tb: QToolBar, icon_name: str, tip: str,
                handler) -> QAction:
        act = QAction(icon(icon_name), tip, self, checkable=True)
        act.triggered.connect(handler)
        tb.addAction(act)
        return act

    def _reload_initial_content(self, preserve_line_breaks: bool) -> None:
        """(Re)load the original block into the editor with line breaks
        either preserved or flattened to spaces. Called once from
        __init__ and again from the "Preserve line breaks" toggle so
        ticking / unticking refreshes the editor view immediately.
        Any in-progress edits to the editor are replaced — the toggle
        is intended for the user to choose how they want to see the
        source paragraph before they start editing it."""
        sz = self._initial_fontsize
        if self._initial_is_html:
            display_html = self._initial_content
            if not preserve_line_breaks:
                import re as _re
                display_html = _re.sub(
                    r"<br\s*/?>", " ", display_html, flags=_re.IGNORECASE,
                )
            style = f"font-size:{sz:.1f}pt;"
            if self._initial_font_family:
                style += f" font-family:'{self._initial_font_family}';"
            self._editor.setHtml(
                f'<span style="{style}">{display_html}</span>'
            )
        else:
            self._editor.setPlainText(self._initial_content)
            cur = self._editor.textCursor()
            cur.select(QTextCursor.Document)
            fmt = QTextCharFormat()
            fmt.setFontPointSize(sz)
            cur.mergeCharFormat(fmt)
            cur.clearSelection()
            self._editor.setTextCursor(cur)
        self._editor.setFontPointSize(sz)
        # Re-apply alignment to the freshly loaded content.
        cur_align = self._editor.textCursor()
        cur_align.select(QTextCursor.Document)
        blk_fmt = QTextBlockFormat()
        blk_fmt.setAlignment(self._initial_qt_align)
        cur_align.mergeBlockFormat(blk_fmt)
        cur_align.clearSelection()
        self._editor.setTextCursor(cur_align)
        self._editor.setAlignment(self._initial_qt_align)

    def _on_preserve_toggled(self, checked: bool) -> None:
        # Persist the choice for the next dialog open …
        from PySide6.QtCore import QSettings as _QS
        _QS("kherve", "KhervePDF").setValue("preserve_line_breaks",
                                            bool(checked))
        # … and refresh the editor right now so the user sees the
        # paragraph in the new form.
        self._reload_initial_content(checked)

    def _on_font(self, font: QFont) -> None:
        # setCurrentFont() during toolbar build fires this slot before
        # _editor exists — bail out cleanly in that case.
        if not hasattr(self, "_editor"):
            return
        family = font.family()
        cur = self._editor.textCursor()
        if cur.hasSelection():
            fmt = QTextCharFormat()
            fmt.setFontFamily(family)
            cur.mergeCharFormat(fmt)
        self._editor.setFontFamily(family)

    def _on_size(self, text: str) -> None:
        try:
            sz = float(text)
        except ValueError:
            return
        if sz < 4.0 or sz > 200.0:
            return
        cur = self._editor.textCursor()
        if cur.hasSelection():
            fmt = QTextCharFormat()
            fmt.setFontPointSize(sz)
            cur.mergeCharFormat(fmt)
        self._editor.setFontPointSize(sz)

    def _on_bold(self, checked: bool) -> None:
        self._editor.setFontWeight(QFont.Bold if checked else QFont.Normal)

    def _on_italic(self, checked: bool) -> None:
        self._editor.setFontItalic(checked)

    def _on_underline(self, checked: bool) -> None:
        self._editor.setFontUnderline(checked)

    def _set_vertical_align(self, va) -> None:
        fmt = QTextCharFormat()
        fmt.setVerticalAlignment(va)
        cur = self._editor.textCursor()
        cur.mergeCharFormat(fmt)
        self._editor.mergeCurrentCharFormat(fmt)

    def _on_super(self, checked: bool) -> None:
        if checked:
            self._sub.setChecked(False)
            self._set_vertical_align(QTextCharFormat.AlignSuperScript)
        else:
            self._set_vertical_align(QTextCharFormat.AlignNormal)

    def _on_sub(self, checked: bool) -> None:
        if checked:
            self._super.setChecked(False)
            self._set_vertical_align(QTextCharFormat.AlignSubScript)
        else:
            self._set_vertical_align(QTextCharFormat.AlignNormal)

    def _sync_toolbar(self, *_args) -> None:
        fmt = self._editor.currentCharFormat()
        self._bold.setChecked(fmt.fontWeight() >= QFont.Bold)
        self._italic.setChecked(fmt.fontItalic())
        self._underline.setChecked(fmt.fontUnderline())
        va = fmt.verticalAlignment()
        self._super.setChecked(va == QTextCharFormat.AlignSuperScript)
        self._sub.setChecked(va == QTextCharFormat.AlignSubScript)
        sz = fmt.fontPointSize()
        if sz > 0:
            self._size_combo.blockSignals(True)
            self._size_combo.setCurrentText(str(int(round(sz))))
            self._size_combo.blockSignals(False)
        align = self._editor.alignment()
        mapping = {
            Qt.AlignLeft:    "align_left",
            Qt.AlignHCenter: "align_center",
            Qt.AlignRight:   "align_right",
            Qt.AlignJustify: "align_justify",
        }
        for flag, name in mapping.items():
            if align & flag:
                self._align_acts[name].setChecked(True)
                break

    def html(self) -> str:
        """Body HTML as produced by QTextEdit — fed directly to
        page.insert_htmlbox."""
        return self._editor.toHtml()

    def plain_text(self) -> str:
        return self._editor.toPlainText()

    def rotation(self) -> int:
        return int(self._rotation_combo.currentData() or 0)


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
        # Auto-fit-width: when True, the page rescales to fill the
        # viewport whenever the window resizes (set on by default and
        # on every fit_width() call; flipped off by zoom_in/out so
        # the user's chosen zoom isn't overridden by a resize).
        self._auto_fit_width = True
        self._tool = "select"
        # tool -> {"color": "#hex", "width": float} (per-tab state).
        self._tool_settings = {k: dict(v) for k, v in TOOL_DEFAULTS.items()}
        # Live storage of all annotations on this document.
        self._annots: list[Annotation] = []
        # Selection (used by the Select tool — Delete removes selected
        # annotations). Indices into self._annots.
        self._selected: set[int] = set()
        # Erase-drag state. The trail (semi-transparent red path) is
        # the visible breadcrumb showing where the eraser has passed;
        # _erase_queue collects indices of annotations the trail
        # crossed. Actual deletion is deferred to mouseReleaseEvent so
        # the trail remains visible without _render_all wiping it out
        # mid-gesture, and so the whole sweep is a single undo step.
        self._erasing = False
        self._erase_path: Optional[QPainterPath] = None
        self._erase_trail: Optional[QGraphicsPathItem] = None
        self._erase_queue: set[int] = set()
        # Select-tool marquee: dragging on blank page draws a dashed
        # rect; on release, every annotation whose bounding rect
        # intersects the marquee becomes selected.
        self._marquee_start: Optional[QPointF] = None
        self._marquee_item: Optional[QGraphicsRectItem] = None
        # Move-text drag state: the dict carries the block info, the
        # original press point, and the ghost rect rendered while the
        # user is dragging the paragraph.
        self._move_text_state: Optional[dict] = None
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
        # The view needs keyboard focus to receive Delete key presses
        # from the Select tool.
        self.setFocusPolicy(Qt.StrongFocus)
        self._apply_drag_mode()

        self._open()

    # ----- doc lifecycle -----

    def _open(self) -> None:
        self._doc = fitz.open(str(self.path))
        # Pull any existing PDF annotations into our editable model so
        # the eraser / Delete can act on them — without this, anything
        # already saved into the PDF would render as pixels and be
        # uneditable.
        self._load_pdf_annots()
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
            # annots=False so PyMuPDF doesn't render the PDF
            # annotations into the pixmap — we draw them ourselves
            # from self._annots, otherwise saved annotations would
            # appear twice and the eraser couldn't peel the bottom
            # layer off the pixmap.
            pix = page.get_pixmap(matrix=matrix, alpha=False, annots=False)
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
        for i, a in enumerate(self._annots):
            self._draw_annot(a, idx=i)

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
                # Highlights are tight per-word — without a generous
                # pad the eraser misses gaps between glyphs.
                pad = max(tol_pt, 10.0) if a.type == "highlight" else tol_pt
                x0, y0 = a.pts[0]
                x1, y1 = a.pts[1]
                xmin, xmax = min(x0, x1), max(x0, x1)
                ymin, ymax = min(y0, y1), max(y0, y1)
                if (xmin - pad <= x_pt <= xmax + pad
                        and ymin - pad <= y_pt <= ymax + pad):
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
                plain = self._strip_html(a.text)
                lines = plain.split("\n") if plain else [""]
                h = max(1, len(lines)) * a.width * 1.2
                w = (max(len(line) for line in lines) if plain else 0) \
                    * a.width * 0.55
                if x - tol_pt <= x_pt <= x + w + tol_pt \
                        and y - tol_pt <= y_pt <= y + h + tol_pt:
                    return i
            elif a.type == "note":
                # Marker is roughly 14 PDF pts wide × 12 high. Be
                # generous so a click anywhere near the marker erases.
                x, y = a.pts[0]
                if (x - tol_pt <= x_pt <= x + 14 + tol_pt
                        and y - tol_pt <= y_pt <= y + 12 + tol_pt):
                    return i
        return None

    def _note_at_scene(self, scene_pt: QPointF) -> Optional[int]:
        """Index of the top-most sticky-note annotation whose marker
        bounding rect contains the given scene point, or None."""
        for i in range(len(self._annots) - 1, -1, -1):
            a = self._annots[i]
            if a.type != "note" or a.page_idx not in self._page_layout:
                continue
            anchor = self._page_to_scene(a.page_idx, *a.pts[0])
            if (anchor.x() <= scene_pt.x() <= anchor.x() + 22
                    and anchor.y() <= scene_pt.y() <= anchor.y() + 18):
                return i
        return None

    def _edit_note(self, idx: int) -> None:
        a = self._annots[idx]
        new_text, ok = QInputDialog.getMultiLineText(
            self, "Sticky note", "Note text:", a.text,
        )
        if not ok or new_text == a.text:
            return
        self._push_undo()
        # dataclass field — replace via deepcopy-friendly assignment
        self._annots[idx] = Annotation(
            type=a.type, page_idx=a.page_idx, color=a.color,
            width=a.width, opacity=a.opacity, pts=list(a.pts),
            text=new_text,
        )
        self._render_all()

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
            # Reopen from disk and re-load the now-baked annotations
            # back into self._annots so the user can keep editing them
            # (erase, move, etc.). Without this, anything just saved
            # would become uneditable pixels.
            self._doc = fitz.open(str(target))
            self._load_pdf_annots()
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

    # ----- load PDF annotations back into self._annots -----

    def _load_pdf_annots(self) -> None:
        """Replace self._annots with annotations recovered from the
        open PDF. Called on open() and after save() so anything
        already on the page can be erased / moved / re-coloured."""
        self._annots.clear()
        if self._doc is None:
            return
        for page_idx, page in enumerate(self._doc):
            try:
                annots = list(page.annots())
            except Exception:
                continue
            for annot in annots:
                a = self._pdf_annot_to_annotation(page_idx, annot)
                if a is not None:
                    self._annots.append(a)

    @staticmethod
    def _rgb01_to_hex(rgb) -> str:
        try:
            r = int(round(float(rgb[0]) * 255))
            g = int(round(float(rgb[1]) * 255))
            b = int(round(float(rgb[2]) * 255))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return "#000000"

    def _pdf_annot_to_annotation(self, page_idx: int,
                                 annot) -> Optional[Annotation]:
        try:
            a_type = annot.type[1]
        except Exception:
            return None
        colors = annot.colors or {}
        stroke = colors.get("stroke") or (0.0, 0.0, 0.0)
        fill = colors.get("fill")
        color_hex = self._rgb01_to_hex(stroke)
        op_f = annot.opacity if annot.opacity is not None else 1.0
        opacity = max(0, min(100, int(round(op_f * 100))))
        border = annot.border or {}
        width = float(border.get("width") or 1.0) or 1.0
        rect = annot.rect

        if a_type == "Ink":
            # PyMuPDF returns annot.vertices for Ink as a list of
            # strokes, each a list of (x, y) tuples. (Older releases
            # exposed get_inklist() for the same data, but that API
            # is gone in newer PyMuPDF.)
            strokes = getattr(annot, "vertices", None) or []
            if not strokes or not isinstance(strokes[0], (list, tuple)) \
                    or not strokes[0]:
                return None
            pts = [(float(p[0]), float(p[1])) for p in strokes[0]]
            return Annotation(type="pen", page_idx=page_idx,
                              color=color_hex, width=width,
                              opacity=opacity, pts=pts)
        if a_type == "Highlight":
            return Annotation(type="highlight", page_idx=page_idx,
                              color=color_hex, width=0.0, opacity=opacity,
                              pts=[(rect.x0, rect.y0), (rect.x1, rect.y1)])
        if a_type == "Square":
            fill_hex = self._rgb01_to_hex(fill) if fill else None
            return Annotation(type="rect", page_idx=page_idx,
                              color=color_hex, width=width, opacity=opacity,
                              pts=[(rect.x0, rect.y0), (rect.x1, rect.y1)],
                              filled=fill is not None,
                              fill_color=fill_hex)
        if a_type == "Circle":
            fill_hex = self._rgb01_to_hex(fill) if fill else None
            return Annotation(type="ellipse", page_idx=page_idx,
                              color=color_hex, width=width, opacity=opacity,
                              pts=[(rect.x0, rect.y0), (rect.x1, rect.y1)],
                              filled=fill is not None,
                              fill_color=fill_hex)
        if a_type == "Line":
            verts = getattr(annot, "vertices", None) or []
            if len(verts) >= 2:
                pts = [(float(verts[0][0]), float(verts[0][1])),
                       (float(verts[1][0]), float(verts[1][1]))]
            else:
                pts = [(rect.x0, rect.y0), (rect.x1, rect.y1)]
            is_arrow = False
            try:
                le = annot.line_ends
                if le and isinstance(le, (tuple, list)) and len(le) >= 2:
                    if le[1] in ("OpenArrow", "ClosedArrow", 5, 6):
                        is_arrow = True
            except Exception:
                pass
            return Annotation(
                type="arrow" if is_arrow else "line",
                page_idx=page_idx, color=color_hex,
                width=width, opacity=opacity, pts=pts,
            )
        if a_type == "Text":
            return Annotation(type="note", page_idx=page_idx,
                              color="#fff59d", width=1.0, opacity=opacity,
                              pts=[(rect.x0, rect.y0)],
                              text=annot.info.get("content", "") if annot.info
                              else "")
        if a_type == "FreeText":
            # Recover font size from the annotation's text properties
            # when possible, otherwise fall back to 11pt.
            fontsize = 11.0
            try:
                ai = annot.info
                content = ai.get("content", "") if ai else ""
            except Exception:
                content = ""
            return Annotation(type="text", page_idx=page_idx,
                              color=color_hex, width=fontsize,
                              opacity=opacity, pts=[(rect.x0, rect.y0)],
                              text=content)
        return None

    @staticmethod
    def _strip_html(s: str) -> str:
        """Strip HTML tags from a string. Used to recover a plain-text
        representation of text annotations for width estimation,
        comparison, and add_freetext_annot fallback."""
        if not s:
            return ""
        import re as _re
        # First convert <br> to newlines so the plain form keeps the
        # visible line breaks; then strip remaining tags.
        s = _re.sub(r"<br\s*/?>", "\n", s, flags=_re.IGNORECASE)
        s = _re.sub(r"<[^>]+>", "", s)
        # Decode common HTML entities introduced by html.escape().
        s = (s.replace("&amp;", "&")
               .replace("&lt;", "<")
               .replace("&gt;", ">")
               .replace("&quot;", '"')
               .replace("&#39;", "'")
               .replace("&nbsp;", " "))
        return s

    @staticmethod
    def _hex_to_rgb01(hex_str: str) -> tuple[float, float, float]:
        s = hex_str.lstrip("#")
        return (int(s[0:2], 16) / 255.0,
                int(s[2:4], 16) / 255.0,
                int(s[4:6], 16) / 255.0)

    def _bake_into(self, doc: fitz.Document) -> None:
        """Translate every Annotation into a real PDF annotation on
        the given document. Pre-existing PDF annotations are deleted
        first — self._annots already mirrors them (loaded via
        _load_pdf_annots), so re-baking from scratch keeps the on-disk
        state exactly aligned with the in-memory model and avoids
        duplication across save cycles."""
        for page in doc:
            for annot in list(page.annots()):
                page.delete_annot(annot)
        for a in self._annots:
            if a.page_idx >= doc.page_count:
                continue
            page = doc[a.page_idx]
            rgb = self._hex_to_rgb01(a.color)
            op = max(0.0, min(1.0, a.opacity / 100.0))
            if a.type == "pen":
                # PyMuPDF wants a sequence of strokes, each a sequence
                # of (x, y) tuples — passing fitz.Point instances
                # raises "arg must be seq of seq of float pairs" on
                # newer versions.
                annot = page.add_ink_annot([
                    [(float(x), float(y)) for x, y in a.pts]
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
                if a.filled:
                    fill_rgb = (self._hex_to_rgb01(a.fill_color)
                                if a.fill_color else rgb)
                    annot.set_colors(stroke=rgb, fill=fill_rgb)
                else:
                    annot.set_colors(stroke=rgb)
                annot.set_border(width=max(0.5, a.width))
                annot.set_opacity(op)
                annot.update()
            elif a.type == "ellipse":
                rect = fitz.Rect(a.pts[0][0], a.pts[0][1],
                                 a.pts[1][0], a.pts[1][1])
                annot = page.add_circle_annot(rect)
                if a.filled:
                    fill_rgb = (self._hex_to_rgb01(a.fill_color)
                                if a.fill_color else rgb)
                    annot.set_colors(stroke=rgb, fill=fill_rgb)
                else:
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
                # Text annotations may carry either plain text (older
                # data) or HTML (added via the Add-Text dialog).
                # Rich content goes through insert_htmlbox so super /
                # subscript, bold etc. render correctly; plain text
                # uses add_freetext_annot so it stays editable as an
                # annotation after save. Rotation is supported only
                # by the freetext branch (insert_htmlbox has no
                # rotate parameter).
                fontsize = max(4.0, a.width)
                source = a.text or ""
                has_rich = bool(source) and (
                    "<sub" in source or "<sup" in source
                    or "<b>" in source or "<b " in source
                    or "<i>" in source or "<i " in source
                    or "<span" in source or "<div" in source
                    or "<p " in source or "<p>" in source
                )
                plain = self._strip_html(source) if has_rich else source
                lines = plain.split("\n") if plain else [""]
                w = max(80.0, fontsize * 0.65
                        * max(len(line) for line in lines))
                h = max(fontsize * 1.4, fontsize * 1.3 * len(lines))
                rect = fitz.Rect(a.pts[0][0], a.pts[0][1],
                                 a.pts[0][0] + w, a.pts[0][1] + h)
                if has_rich:
                    wrapped = (f'<div style="font-size:{fontsize:.1f}pt;">'
                               f'{source}</div>')
                    try:
                        page.insert_htmlbox(rect, wrapped)
                    except Exception:
                        page.insert_text(
                            (a.pts[0][0], a.pts[0][1] + fontsize),
                            plain, fontsize=fontsize, color=rgb,
                        )
                else:
                    try:
                        kwargs = dict(rect=rect, text=plain,
                                      fontsize=fontsize, text_color=rgb)
                        if a.rotation:
                            kwargs["rotate"] = a.rotation
                        annot = page.add_freetext_annot(**kwargs)
                        annot.set_opacity(op)
                        annot.update()
                    except Exception:
                        page.insert_text(
                            (a.pts[0][0], a.pts[0][1] + fontsize),
                            plain, fontsize=fontsize, color=rgb,
                        )
            elif a.type == "note":
                annot = page.add_text_annot(fitz.Point(*a.pts[0]), a.text)
                try:
                    annot.set_colors(stroke=(0.71, 0.55, 0.0))
                    annot.update()
                except Exception:
                    pass
            # Erase isn't an annotation type — it removes items from
            # self._annots at gesture time, so there's nothing to bake.

    # ----- zoom -----

    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    def zoom_percent(self) -> int:
        return int(round(self._zoom * 100))

    def zoom_in(self) -> None:
        # Manual zoom disables auto-fit so the user's choice survives
        # the next window resize.
        self._auto_fit_width = False
        self._set_zoom(self._zoom * 1.25)

    def zoom_out(self) -> None:
        self._auto_fit_width = False
        self._set_zoom(self._zoom / 1.25)

    def scroll_to_page(self, page_idx: int) -> None:
        """Center the main view on the given page (used by the side
        thumbnails panel)."""
        if page_idx not in self._page_layout:
            return
        lay = self._page_layout[page_idx]
        cx = lay["w_px"] / 2
        cy = lay["y_origin"] + min(lay["h_px"] / 2,
                                   self.viewport().height() / 2)
        self.centerOn(cx, cy)

    def fit_width(self) -> None:
        """Fit page width to viewport and re-arm auto-fit so window
        resizes keep refitting."""
        self._auto_fit_width = True
        self._apply_fit_width()

    def _apply_fit_width(self) -> None:
        if self._doc is None or self._doc.page_count == 0:
            return
        page_w_pt = self._doc[0].rect.width or 1.0
        # 24px padding so the page doesn't bleed into the scrollbar.
        view_w = self.viewport().width() - 24
        if view_w < 10:
            # Viewport isn't laid out yet — showEvent / resizeEvent
            # will retry.
            return
        new_zoom = view_w / ((self._base_dpi / 72.0) * page_w_pt)
        self._set_zoom(new_zoom)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._auto_fit_width and self._doc is not None:
            # Defer one tick so the viewport has settled to its new
            # size before we measure.
            QTimer.singleShot(0, self._apply_fit_width)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._auto_fit_width and self._doc is not None:
            QTimer.singleShot(0, self._apply_fit_width)

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

    def tool_filled(self, name: Optional[str] = None) -> bool:
        return bool(self._tool_settings[name or self._tool].get("filled", False))

    def set_tool_filled(self, val: bool, name: Optional[str] = None) -> None:
        self._tool_settings[name or self._tool]["filled"] = bool(val)

    def tool_fill_color(self, name: Optional[str] = None) -> Optional[str]:
        return self._tool_settings[name or self._tool].get("fill_color")

    def set_tool_fill_color(self, color: Optional[str],
                            name: Optional[str] = None) -> None:
        self._tool_settings[name or self._tool]["fill_color"] = color

    def _apply_drag_mode(self) -> None:
        # Hand = pan; Select = click annotations; everything else = draw.
        if self._tool == "hand":
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif self._tool == "select":
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(Qt.ArrowCursor)
        elif self._tool == "move_text":
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(Qt.SizeAllCursor)
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

    def _draw_annot(self, a: Annotation, idx: Optional[int] = None) -> None:
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
            if a.filled:
                fill = QColor(a.fill_color or a.color)
                fill.setAlpha(alpha)
                item.setBrush(QBrush(fill))
            self._scene.addItem(item)
        elif a.type == "ellipse":
            item = QGraphicsEllipseItem(self._rect_from_pts(a))
            item.setPen(QPen(color, pw_px))
            if a.filled:
                fill = QColor(a.fill_color or a.color)
                fill.setAlpha(alpha)
                item.setBrush(QBrush(fill))
            self._scene.addItem(item)
        elif a.type == "highlight":
            r = self._rect_from_pts(a)
            item = QGraphicsRectItem(r)
            item.setPen(QPen(Qt.NoPen))
            item.setBrush(QBrush(color))
            self._scene.addItem(item)
        elif a.type == "note":
            # Sticky-note marker: a small yellow rounded rect with an "N"
            # glyph, anchored at the click point. The annotation's full
            # text is shown as the item's tooltip and reachable via the
            # edit dialog (Select / Note tool + click).
            anchor = self._page_to_scene(a.page_idx, *a.pts[0])
            marker = QGraphicsRectItem(0, 0, 22, 18)
            marker.setPos(anchor)
            marker.setPen(QPen(QColor("#b58900"), 1))
            marker.setBrush(QBrush(QColor("#fff59d")))
            marker.setToolTip(a.text or "(empty note)")
            self._scene.addItem(marker)
            label = QGraphicsTextItem("N", marker)
            f = QFont()
            f.setBold(True)
            f.setPointSize(8)
            label.setFont(f)
            label.setDefaultTextColor(QColor("#5d4037"))
            label.setPos(6, 0)
        elif a.type == "text":
            anchor = self._page_to_scene(a.page_idx, *a.pts[0])
            item = QGraphicsTextItem()
            t = a.text or ""
            # Treat anything containing HTML tags as rich; setHtml
            # handles font sizes, sub/sup, bold etc. Plain text falls
            # back to setPlainText.
            if "<" in t and ">" in t:
                item.setHtml(t)
            else:
                item.setPlainText(t)
            f = QFont()
            f.setPointSizeF(max(4.0, a.width))
            item.setFont(f)
            item.setDefaultTextColor(color)
            item.setPos(anchor)
            if a.rotation:
                item.setRotation(a.rotation)
            self._scene.addItem(item)
        # If this annotation is selected by the Select tool, overlay a
        # dashed marquee so the user knows what Delete will remove.
        if idx is not None and idx in self._selected:
            self._draw_selection_box(a)

    def _annot_scene_bbox(self, a: Annotation) -> Optional[QRectF]:
        """Bounding rect (scene coords) of an annotation, used for the
        selection marquee overlay."""
        if a.page_idx not in self._page_layout:
            return None
        if a.type in ("rect", "ellipse", "highlight"):
            return self._rect_from_pts(a)
        if a.type in ("line", "arrow"):
            p0 = self._page_to_scene(a.page_idx, *a.pts[0])
            p1 = self._page_to_scene(a.page_idx, *a.pts[1])
            return QRectF(p0, p1).normalized()
        if a.type == "pen":
            if not a.pts:
                return None
            pts = [self._page_to_scene(a.page_idx, x, y) for x, y in a.pts]
            xs = [p.x() for p in pts]
            ys = [p.y() for p in pts]
            return QRectF(min(xs), min(ys),
                          max(xs) - min(xs), max(ys) - min(ys))
        if a.type == "text":
            anchor = self._page_to_scene(a.page_idx, *a.pts[0])
            scale = self._page_layout[a.page_idx]["scale"]
            lines = a.text.split("\n") if a.text else [""]
            h = max(1, len(lines)) * a.width * 1.3
            w = (max(len(line) for line in lines) if a.text else 0) \
                * a.width * 0.55
            return QRectF(anchor.x(), anchor.y(), w * scale, h * scale)
        if a.type == "note":
            anchor = self._page_to_scene(a.page_idx, *a.pts[0])
            return QRectF(anchor.x(), anchor.y(), 22, 18)
        return None

    def _make_block_marker(self, page_idx: int,
                           rect_pt: tuple[float, float, float, float]
                           ) -> Optional[QGraphicsRectItem]:
        """Add a dashed-blue translucent rectangle covering a PDF text
        block, in scene coords. Used by Edit-Text and Move-Text so the
        user can see which paragraph is being acted on. Returns the
        item so callers can remove it when done."""
        if page_idx not in self._page_layout:
            return None
        x0, y0, x1, y1 = rect_pt
        p0 = self._page_to_scene(page_idx, x0, y0)
        p1 = self._page_to_scene(page_idx, x1, y1)
        item = QGraphicsRectItem(QRectF(p0, p1).normalized())
        pen = QPen(QColor("#1976d2"), 1.5, Qt.DashLine)
        pen.setCosmetic(True)
        item.setPen(pen)
        fill = QColor("#1976d2")
        fill.setAlpha(30)
        item.setBrush(QBrush(fill))
        item.setZValue(150)
        self._scene.addItem(item)
        return item

    def _draw_selection_box(self, a: Annotation) -> None:
        bbox = self._annot_scene_bbox(a)
        if bbox is None:
            return
        bbox = bbox.adjusted(-3, -3, 3, 3)
        item = QGraphicsRectItem(bbox)
        pen = QPen(QColor("#1976d2"), 1.5, Qt.DashLine)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setBrush(QBrush(Qt.NoBrush))
        item.setZValue(100)
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
        # Always check first whether the click landed on a sticky-note
        # marker — even in Select mode, a click on a note should open
        # its edit dialog instead of starting a pan.
        if event.button() == Qt.LeftButton:
            scene_pt0 = self.mapToScene(event.position().toPoint())
            mapped0 = self._scene_to_page(scene_pt0)
            if mapped0 is not None:
                note_idx = self._note_at_scene(scene_pt0)
                if note_idx is not None and self._tool in ("select", "note"):
                    self._edit_note(note_idx)
                    event.accept()
                    return
        if self._tool == "hand" or event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        scene_pt = self.mapToScene(event.position().toPoint())
        mapped = self._scene_to_page(scene_pt)
        if mapped is None:
            # Click in the gap between pages — clear selection if any.
            if self._tool == "select" and self._selected:
                self._selected.clear()
                self._render_all()
            return super().mousePressEvent(event)
        page_idx, px, py = mapped
        if self._tool == "select":
            ctrl = bool(event.modifiers() & Qt.ControlModifier)
            idx = self._find_annot_at(page_idx, px, py)
            if idx is not None:
                # Click on annotation: single-select, or Ctrl-click to
                # toggle into the existing selection.
                if ctrl:
                    if idx in self._selected:
                        self._selected.discard(idx)
                    else:
                        self._selected.add(idx)
                else:
                    self._selected = {idx}
                self._render_all()
            else:
                # Empty space: begin a marquee. mouseReleaseEvent
                # decides whether the gesture was a click (clear
                # selection) or a real drag (select intersecting
                # annotations).
                self._marquee_start = scene_pt
                rect = QRectF(scene_pt, scene_pt)
                self._marquee_item = QGraphicsRectItem(rect)
                pen = QPen(QColor("#1976d2"), 1.0, Qt.DashLine)
                pen.setCosmetic(True)
                self._marquee_item.setPen(pen)
                fill = QColor("#1976d2")
                fill.setAlpha(40)
                self._marquee_item.setBrush(QBrush(fill))
                self._marquee_item.setZValue(200)
                self._scene.addItem(self._marquee_item)
            event.accept()
            return
        self._drag_start = scene_pt
        self._drag_page = page_idx
        color_hex = self.tool_color()
        width = self.tool_width()
        opacity = self.tool_opacity()
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
            if self.tool_filled():
                fc_hex = self.tool_fill_color() or color_hex
                fill = QColor(fc_hex)
                fill.setAlpha(int(opacity * 255 / 100))
                item.setBrush(QBrush(fill))
            self._scene.addItem(item)
            self._preview_item = item
        elif self._tool == "highlight":
            item = QGraphicsRectItem(QRectF(scene_pt, scene_pt))
            item.setPen(QPen(Qt.NoPen))
            item.setBrush(QBrush(self._qcolor(color_hex, alpha=90)))
            self._scene.addItem(item)
            self._preview_item = item
        elif self._tool == "erase":
            # Eraser: queue deletions while showing a red trail. The
            # deletion happens on mouseReleaseEvent in one batch so
            # the trail remains visible during the gesture and the
            # whole sweep is a single undo step.
            self._erasing = True
            self._selected.clear()
            self._erase_queue = set()
            self._erase_path = QPainterPath(scene_pt)
            pen = QPen(QColor("#c62828"), 4.0,
                       Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            pen.setCosmetic(True)
            self._erase_trail = QGraphicsPathItem(self._erase_path)
            self._erase_trail.setPen(pen)
            self._erase_trail.setOpacity(0.5)
            self._erase_trail.setZValue(200)
            self._scene.addItem(self._erase_trail)
            idx = self._find_annot_at(page_idx, px, py)
            if idx is not None:
                self._erase_queue.add(idx)
            self._drag_start = None
            self._drag_page = None
            self._preview_item = None
            event.accept()
            return
        elif self._tool == "note":
            # Prompt for the note's body; on accept, store an anchor +
            # the text. The marker is drawn from storage so it'll
            # survive zoom/scroll like every other annotation.
            text, ok = QInputDialog.getMultiLineText(
                self, "New sticky note", "Note text:", "",
            )
            if ok and text.strip():
                self._push_undo()
                self._annots.append(Annotation(
                    type="note", page_idx=page_idx,
                    color="#fff59d", width=1.0,
                    pts=[(px, py)], text=text,
                ))
                self._render_all()
            self._drag_start = None
            self._drag_page = None
            self._preview_item = None
            event.accept()
            return
        elif self._tool == "text":
            self._add_text_at(page_idx, (px, py),
                              color_hex, width, opacity)
            self._drag_start = None
            self._drag_page = None
            self._preview_item = None
            event.accept()
            return
        elif self._tool == "edit_text":
            self._edit_existing_text(page_idx, px, py)
            self._drag_start = None
            self._drag_page = None
        elif self._tool == "move_text":
            # Find the paragraph at the click point and start a drag.
            # mouseMoveEvent re-positions the dashed preview; release
            # commits the move (redact original + insert at new rect).
            if self._doc is None:
                event.accept()
                return
            info = self._find_text_block_detailed(
                self._doc[page_idx], px, py)
            if info is None:
                event.accept()
                return
            preview = self._make_block_marker(page_idx, info["rect"])
            if preview is None:
                event.accept()
                return
            scale = self._page_layout[page_idx]["scale"]
            self._move_text_state = {
                "info": info,
                "page_idx": page_idx,
                "preview": preview,
                "start_scene": scene_pt,
                "orig_rect_scene": preview.rect(),
                "scale": scale,
            }
            self._drag_start = None
            self._drag_page = None
            event.accept()
            return
        else:
            return super().mousePressEvent(event)
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._tool == "move_text" and self._move_text_state is not None:
            state = self._move_text_state
            scene_pt = self.mapToScene(event.position().toPoint())
            delta = scene_pt - state["start_scene"]
            r = state["orig_rect_scene"]
            state["preview"].setRect(
                QRectF(r.x() + delta.x(), r.y() + delta.y(),
                       r.width(), r.height())
            )
            event.accept()
            return
        if self._tool == "select" and self._marquee_item is not None:
            scene_pt = self.mapToScene(event.position().toPoint())
            self._marquee_item.setRect(
                QRectF(self._marquee_start, scene_pt).normalized()
            )
            event.accept()
            return
        if self._tool == "erase" and self._erasing:
            scene_pt = self.mapToScene(event.position().toPoint())
            if self._erase_path is not None and self._erase_trail is not None:
                self._erase_path.lineTo(scene_pt)
                self._erase_trail.setPath(self._erase_path)
            mapped = self._scene_to_page(scene_pt)
            if mapped is not None:
                page_idx, px, py = mapped
                idx = self._find_annot_at(page_idx, px, py)
                if idx is not None:
                    self._erase_queue.add(idx)
            event.accept()
            return
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
        if self._tool == "move_text" and self._move_text_state is not None:
            state = self._move_text_state
            self._move_text_state = None
            self._scene.removeItem(state["preview"])
            scene_pt = self.mapToScene(event.position().toPoint())
            scale = state["scale"]
            dx_pt = (scene_pt.x() - state["start_scene"].x()) / scale
            dy_pt = (scene_pt.y() - state["start_scene"].y()) / scale
            # Anything under ~1pt in either axis is treated as a stray
            # click and dropped — no destructive redact.
            if abs(dx_pt) < 1.0 and abs(dy_pt) < 1.0:
                event.accept()
                return
            info = state["info"]
            page_idx = state["page_idx"]
            page = self._doc[page_idx] if self._doc is not None else None
            if page is None:
                event.accept()
                return
            x0, y0, x1, y1 = info["rect"]
            new_rect = fitz.Rect(x0 + dx_pt, y0 + dy_pt,
                                 x1 + dx_pt, y1 + dy_pt)
            # Clamp to page bounds so insert_htmlbox always has a
            # valid target rect.
            page_r = page.rect
            new_rect &= page_r
            if new_rect.is_empty:
                event.accept()
                return
            self._push_undo(include_doc=True)
            page.add_redact_annot(fitz.Rect(x0, y0, x1, y1), fill=(1, 1, 1))
            page.apply_redactions()
            html_body = info.get("html") or html_mod.escape(info["text"])
            # Strip <br> from the recovered html so insert_htmlbox
            # reflows naturally at the destination rather than baking
            # in the original visual breaks (which inflate line spacing
            # and overflow the rect).
            import re as _re
            html_body = _re.sub(r"<br\s*/?>", " ", html_body,
                                flags=_re.IGNORECASE)
            sz = max(4.0, info["size"])
            align = info.get("align", "left")
            font = info.get("font", "")
            # text-align is on the wrapping <div> so justify / center
            # / right preserved from the original block apply to the
            # rewrapped lines at the new location. font-family carries
            # the detected source font so insert_htmlbox uses it (or
            # the closest MuPDF fallback).
            font_css = f"font-family:'{font}';" if font else ""
            wrapped = (f'<div style="text-align:{align};'
                       f'font-size:{sz:.1f}pt;{font_css}">'
                       f'{html_body}</div>')
            try:
                page.insert_htmlbox(new_rect, wrapped)
            except AttributeError:
                fitz_align = {
                    "left": 0, "center": 1, "right": 2, "justify": 3,
                }.get(align, 0)
                page.insert_textbox(new_rect, info["text"],
                                    fontsize=info["size"],
                                    color=info["color"],
                                    align=fitz_align)
            self._render_all()
            event.accept()
            return
        if self._tool == "select" and self._marquee_item is not None:
            marquee = self._marquee_item.rect()
            ctrl = bool(event.modifiers() & Qt.ControlModifier)
            self._scene.removeItem(self._marquee_item)
            self._marquee_item = None
            self._marquee_start = None
            if marquee.width() < 3 and marquee.height() < 3:
                # No real drag — treat as a click on blank page and
                # clear selection (unless Ctrl-held — then no-op).
                if not ctrl:
                    self._selected.clear()
            else:
                hits = set()
                for i, a in enumerate(self._annots):
                    bbox = self._annot_scene_bbox(a)
                    if bbox is not None and marquee.intersects(bbox):
                        hits.add(i)
                if ctrl:
                    self._selected ^= hits  # toggle into existing selection
                else:
                    self._selected = hits
            self._render_all()
            event.accept()
            return
        if self._tool == "erase" and self._erasing:
            self._erasing = False
            # Remove the visible trail.
            if self._erase_trail is not None:
                self._scene.removeItem(self._erase_trail)
            self._erase_trail = None
            self._erase_path = None
            queue = list(self._erase_queue)
            self._erase_queue = set()
            if queue:
                self._push_undo()
                for i in sorted(queue, reverse=True):
                    if 0 <= i < len(self._annots):
                        del self._annots[i]
                self._render_all()
            event.accept()
            return
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
                filled = (self._tool in ("rect", "ellipse")
                          and self.tool_filled())
                fc = self.tool_fill_color() if filled else None
                self._annots.append(Annotation(
                    type=self._tool, page_idx=page, color=color, width=width,
                    pts=[start_pt, end_pt], opacity=opacity, filled=filled,
                    fill_color=fc,
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
        for i, a in enumerate(self._annots[n_before:], start=n_before):
            self._draw_annot(a, idx=i)
        event.accept()

    # ----- keyboard: Delete clears selected annotations -----

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self._selected:
            self._push_undo()
            for i in sorted(self._selected, reverse=True):
                if 0 <= i < len(self._annots):
                    del self._annots[i]
            self._selected.clear()
            self._render_all()
            event.accept()
            return
        if event.key() == Qt.Key_Escape and self._selected:
            self._selected.clear()
            self._render_all()
            event.accept()
            return
        # Ctrl + (or =) zooms in; Ctrl - zooms out; Ctrl 0 fits width.
        if event.modifiers() & Qt.ControlModifier:
            if event.key() in (Qt.Key_Plus, Qt.Key_Equal):
                self.zoom_in()
                event.accept()
                return
            if event.key() == Qt.Key_Minus:
                self.zoom_out()
                event.accept()
                return
            if event.key() == Qt.Key_0:
                self.fit_width()
                event.accept()
                return
        super().keyPressEvent(event)

    def wheelEvent(self, event):  # noqa: N802
        # Ctrl + wheel zooms; without Ctrl, the default scroll
        # behaviour pans the document.
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

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

    def _add_text_at(self, page_idx: int,
                     anchor_pt: tuple[float, float],
                     color: str, fontsize: float, opacity: int) -> None:
        """Add Text tool: open the Edit-Text dialog with an empty
        editor at the click point, then store the result as a text
        annotation. Replaces the inline _EditableTextItem flow whose
        focusOutEvent → _render_all sequence had a habit of freeing
        the item while Qt was still on the focus call stack
        (0xC0000005 access-violation crash)."""
        dlg = _EditTextDialog(
            self, "", fontsize,
            is_html=False, align="left",
            preserve_line_breaks=False,
            font_family="",
            rotation=0,
            title="Add text",
        )
        if dlg.exec() != QDialog.Accepted:
            return
        html = dlg.html()
        plain = dlg.plain_text().strip()
        if not plain:
            return
        self._push_undo()
        self._annots.append(Annotation(
            type="text", page_idx=page_idx, color=color,
            width=fontsize, opacity=opacity,
            pts=[anchor_pt], text=html,
            rotation=dlg.rotation(),
        ))
        self._render_all()

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
        # Visual feedback: draw a dashed rectangle around the block
        # being edited so the user sees which paragraph the dialog
        # will replace. Removed in `finally:` regardless of accept /
        # cancel — and _render_all() will rebuild the scene on accept
        # anyway.
        marker = self._make_block_marker(page_idx, info["rect"])
        try:
            initial = info.get("html") or info["text"]
            dlg = _EditTextDialog(
                self, initial, info["size"],
                is_html=("html" in info),
                align=info.get("align", "left"),
                preserve_line_breaks=self._preserve_line_breaks(),
                font_family=info.get("font", ""),
            )
            if dlg.exec() != QDialog.Accepted:
                return
        finally:
            if marker is not None and marker.scene() is self._scene:
                self._scene.removeItem(marker)
        html = dlg.html()
        new_plain = dlg.plain_text()
        # Normalise both sides — Qt represents <br> as   in
        # plain text while our reader uses \n — and skip if the body
        # is identical to what we loaded.
        def _norm(s: str) -> str:
            return s.replace(" ", "\n").strip()
        if _norm(new_plain) == _norm(info["text"]):
            return
        # Doc is about to be mutated — undo entry must include doc bytes.
        self._push_undo(include_doc=True)
        rect = fitz.Rect(*info["rect"])
        # White out the original glyphs by rewriting the page content
        # stream so the new text doesn't sit on top of the old.
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()
        # insert_htmlbox understands font sizes, super/sub
        # (vertical-align:super), bold/italic, and CSS text-align — the
        # dialog's QTextEdit emits all of these so we don't have to
        # carry them as separate parameters. Returns (spare_height,
        # scale); when scale < 1 the engine had to shrink to fit and
        # we extend the rect downward and retry so the user's chosen
        # font size is honoured instead of silently shrunk.
        # Strip <br> before passing to insert_htmlbox: the engine's
        # per-line spacing for explicit breaks is taller than the
        # original PDF leading, which made the rewritten text overflow
        # into the next paragraph. Letting insert_htmlbox reflow
        # naturally produces tight lines that fit the original rect.
        import re as _re
        html = _re.sub(r"<br\s*/?>", " ", html, flags=_re.IGNORECASE)
        html = html.replace(" ", " ")
        try:
            spare, scale = page.insert_htmlbox(rect, html)
            if scale < 0.999:
                page_h = page.rect.height
                grown = fitz.Rect(rect.x0, rect.y0,
                                  rect.x1, min(page_h, rect.y1 + rect.height * 4))
                page.add_redact_annot(rect, fill=(1, 1, 1))
                page.apply_redactions()
                page.insert_htmlbox(grown, html)
        except AttributeError:
            # PyMuPDF too old for insert_htmlbox — fall back to plain text.
            page.insert_textbox(
                rect, new_plain, fontsize=info["size"], color=info["color"],
            )
        self._render_all()

    def _find_text_block_detailed(self, page: fitz.Page,
                                  x_pt: float, y_pt: float):
        """Locate the text block at (x_pt, y_pt) and return its HTML
        text plus the first span's font size and colour for the editor.

        Two transformations on top of `get_text("dict")`:

          * **Visual wraps → one paragraph** — PDF dict "lines" are
            visual wraps, not paragraph breaks. By default we stitch
            them with a single space (hyphens at line ends are kept
            verbatim — "flex- ibility" rather than "flexibility" — so
            the soft break is still visible). The user can flip the
            "Preserve PDF Line Breaks" toggle in the View menu to
            join with `<br>` instead, keeping the source layout
            exactly as the editor view.
          * **Superscript / subscript spans** — spans whose `size` is
            smaller than the dominant line size and whose baseline
            (`origin[1]`) sits above or below the line baseline are
            wrapped in `<sup>` / `<sub>` HTML, so the editor shows
            them with proper baseline shift and `insert_htmlbox`
            renders them back correctly on save. PyMuPDF flag bit 0
            (TEXT_FONT_SUPERSCRIPT) is also honoured when present.
        """
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            if block.get("type") != 0:
                continue
            x0, y0, x1, y1 = block["bbox"]
            if not (x0 <= x_pt <= x1 and y0 <= y_pt <= y1):
                continue
            # PyMuPDF often groups several visually-distinct paragraphs
            # into one "block" (e.g. running prose, indented children).
            # Split the block's lines into paragraphs using indentation
            # and vertical gaps, then act only on the paragraph the
            # user actually clicked into.
            all_lines = [ln for ln in block.get("lines", [])
                         if ln.get("spans")]
            paragraphs = self._split_lines_into_paragraphs(all_lines)
            if not paragraphs:
                continue
            target_para = None
            for para in paragraphs:
                p_y_top = min(ln["bbox"][1] for ln in para)
                p_y_bot = max(ln["bbox"][3] for ln in para)
                if p_y_top <= y_pt <= p_y_bot:
                    target_para = para
                    break
            if target_para is None:
                # Click sat between paragraph bounds — fall back to the
                # nearest by vertical distance.
                target_para = min(
                    paragraphs,
                    key=lambda p: abs(
                        ((p[0]["bbox"][1] + p[-1]["bbox"][3]) / 2) - y_pt
                    ),
                )
            # Recompute the block-relative rect: width = block column,
            # height = the chosen paragraph only.
            p_y0 = min(ln["bbox"][1] for ln in target_para)
            p_y1 = max(ln["bbox"][3] for ln in target_para)
            line_htmls: list[str] = []
            line_plains: list[str] = []
            first_span = None
            for line in target_para:
                spans = line.get("spans", [])
                if not spans:
                    continue
                # Dominant line size — used to tell normal text from
                # smaller super/subscript spans.
                max_size = max(s.get("size", 0.0) for s in spans) or 1.0
                normal = [s for s in spans
                          if s.get("size", 0.0) >= max_size * 0.9]
                if normal:
                    baseline = sum(s["origin"][1] for s in normal) / len(normal)
                else:
                    baseline = sum(s["origin"][1] for s in spans) / len(spans)
                if first_span is None:
                    first_span = normal[0] if normal else spans[0]
                parts: list[str] = []
                plain_parts: list[str] = []
                for s in spans:
                    text = s.get("text", "")
                    if not text:
                        continue
                    plain_parts.append(text)
                    esc = html_mod.escape(text)
                    size = s.get("size", max_size)
                    origin_y = s.get("origin", (0.0, baseline))[1]
                    flags = int(s.get("flags", 0))
                    smaller = size < max_size * 0.85
                    is_super = (flags & 1) or (
                        smaller and origin_y < baseline - 1.0)
                    is_sub = smaller and origin_y > baseline + 1.0
                    if is_super:
                        parts.append(f"<sup>{esc}</sup>")
                    elif is_sub:
                        parts.append(f"<sub>{esc}</sub>")
                    else:
                        parts.append(esc)
                if not parts:
                    continue
                line_htmls.append("".join(parts).rstrip())
                line_plains.append("".join(plain_parts).rstrip())
            if first_span is None or not line_htmls:
                continue
            # Always carry the original line breaks as <br> /\n in
            # the returned info. _EditTextDialog flattens them to
            # spaces when its "Preserve line breaks" checkbox is
            # unticked. Saving always strips <br> before
            # insert_htmlbox so the engine can reflow the paragraph
            # cleanly (otherwise <br> forces tall line-spacing that
            # overflows into the next block).
            paragraph_html = "<br>".join(line_htmls)
            paragraph_plain = "\n".join(line_plains)
            raw_color = int(first_span.get("color", 0))
            r = ((raw_color >> 16) & 0xff) / 255.0
            g = ((raw_color >> 8) & 0xff) / 255.0
            b = (raw_color & 0xff) / 255.0
            # Dominant font + size measured across the paragraph the
            # user actually clicked (not the whole block — adjacent
            # paragraphs may use a different font or weight).
            dom_font_raw, dom_size = self._dominant_font_and_size_lines(
                target_para,
                fallback_size=float(first_span.get("size", 11.0)),
            )
            # Alignment detected on a synthetic block-like dict so the
            # heuristic only sees the chosen paragraph's lines.
            align = self._detect_alignment(
                {"bbox": (x0, p_y0, x1, p_y1), "lines": target_para},
                dom_size,
            )
            font = self._clean_font_name(dom_font_raw)
            return {
                "rect": (x0, p_y0, x1, p_y1),
                "html": paragraph_html.rstrip(),
                "text": paragraph_plain.rstrip(),
                "size": dom_size,
                "color": (r, g, b),
                "align": align,
                "font": font,
            }
        return None

    @staticmethod
    def _split_lines_into_paragraphs(lines: list) -> list[list]:
        """Group a block's visual lines into paragraphs.

        Heuristics (one is enough to start a new paragraph):
          * The line's left edge is noticeably further right than the
            block's main left margin — a first-line indent.
          * The vertical gap to the previous line is larger than the
            typical line spacing — blank-line separation.

        Tolerance scales with the block's median line height so 8pt
        body text and 14pt headings are judged on the same relative
        scale.
        """
        if not lines:
            return []
        from collections import Counter
        # Body left margin = most common rounded line.x0. Round to
        # integer to absorb sub-point jitter.
        rounded_starts = [round(line["bbox"][0]) for line in lines]
        body_x0 = Counter(rounded_starts).most_common(1)[0][0]
        # Typical line height — used to scale indent and gap thresholds.
        heights = sorted(line["bbox"][3] - line["bbox"][1] for line in lines)
        median_h = heights[len(heights) // 2] if heights else 12.0
        indent_threshold = body_x0 + max(4.0, median_h * 0.6)
        gap_threshold = median_h * 0.6
        paragraphs: list[list] = []
        current: list = []
        prev_y1 = None
        for line in lines:
            lx0, ly0, _lx1, ly1 = line["bbox"]
            starts_new = False
            if current:
                if lx0 > indent_threshold:
                    starts_new = True
                elif prev_y1 is not None and (ly0 - prev_y1) > gap_threshold:
                    starts_new = True
            if starts_new:
                paragraphs.append(current)
                current = []
            current.append(line)
            prev_y1 = ly1
        if current:
            paragraphs.append(current)
        return paragraphs

    @staticmethod
    def _dominant_font_and_size_lines(lines: list, fallback_size: float
                                      ) -> tuple[str, float]:
        """Same as _dominant_font_and_size but takes a list of lines
        (a paragraph) instead of a whole block."""
        font_chars: dict[str, int] = {}
        size_chars: dict[float, int] = {}
        for line in lines:
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text:
                    continue
                n = len(text)
                f = span.get("font") or ""
                font_chars[f] = font_chars.get(f, 0) + n
                s = round(float(span.get("size", fallback_size)), 1)
                size_chars[s] = size_chars.get(s, 0) + n
        if not font_chars:
            return ("", fallback_size)
        dom_font = max(font_chars, key=font_chars.get)
        dom_size = max(size_chars, key=size_chars.get) if size_chars \
            else fallback_size
        return dom_font, float(dom_size)

    @staticmethod
    def _dominant_font_and_size(block, fallback_size: float
                                ) -> tuple[str, float]:
        """Pick the font name + size that covers the most characters
        in the block. Paragraphs sometimes have small sup/sub spans
        with a different (smaller) font; weighting by character count
        keeps those from hijacking the detection."""
        font_chars: dict[str, int] = {}
        size_chars: dict[float, int] = {}
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text:
                    continue
                n = len(text)
                f = span.get("font") or ""
                font_chars[f] = font_chars.get(f, 0) + n
                # Bucket sizes to 0.1pt — float keys are otherwise hash-
                # equal only when bit-identical.
                s = round(float(span.get("size", fallback_size)), 1)
                size_chars[s] = size_chars.get(s, 0) + n
        if not font_chars:
            return ("", fallback_size)
        dom_font = max(font_chars, key=font_chars.get)
        dom_size = max(size_chars, key=size_chars.get) if size_chars \
            else fallback_size
        return dom_font, float(dom_size)

    @staticmethod
    def _clean_font_name(font: str) -> str:
        """Normalise a PDF font name down to a family Qt and MuPDF
        can recognise.

        PDF names carry a lot of decoration:
          * 6-char subset prefix: "ABCDEF+TimesNewRomanPSMT"
          * Style suffixes after "," "-" or via terms appended
            directly (BoldItalic, Oblique, …)
          * Adobe TrueType markers MT / PS / Std / Pro
          * CamelCase rather than spaces ("TimesNewRoman")
        We strip / normalise each of those so the result is something
        like "Times New Roman" rather than "ABCDEF+TimesNewRomanPSMT".
        """
        if not font:
            return ""
        # Strip subset prefix (six uppercase letters + "+")
        if "+" in font:
            font = font.split("+", 1)[1]
        # Strip explicit style suffix after a separator. Try multiple
        # separators because PDFs aren't consistent.
        for sep in (",", "-", "_"):
            if sep in font:
                base = font.split(sep, 1)[0]
                if base:
                    font = base
                    break
        # Strip only the font-tech markers that aren't part of any
        # family name (MT = MultipleMaster TrueType, PS = PostScript,
        # MS = Microsoft). Things like "Pro", "Std", "Light", "Roman"
        # ARE legitimate name fragments (Minion Pro, Adobe Caslon
        # Pro, Times New Roman) and stripping them mangles the
        # detection.
        changed = True
        while changed:
            changed = False
            for suffix in ("MT", "PS", "MS"):
                if font.endswith(suffix) and len(font) > len(suffix):
                    font = font[: -len(suffix)]
                    changed = True
        # CamelCase → spaces ("TimesNewRoman" → "Times New Roman").
        import re as _re
        font = _re.sub(r"(?<=[a-z])(?=[A-Z])", " ", font)
        # Insert a space between consecutive uppercase + lower
        # ("ABCRoman" → "ABC Roman").
        font = _re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", font)
        return font.strip()

    @staticmethod
    def _preserve_line_breaks() -> bool:
        """Read the global "Preserve PDF Line Breaks" toggle (View
        menu). When True, Edit-Text / Move-Text stitch visual lines
        with <br>; otherwise they join with a space."""
        return bool(QSettings("kherve", "KhervePDF").value(
            "preserve_line_breaks", False, type=bool))

    @staticmethod
    def _detect_alignment(block, fontsize: float) -> str:
        """Infer one of "left" / "center" / "right" / "justify" from
        the per-line bboxes within a text block.

        Heuristic — measure each line's gap to the block's left and
        right edges:
          * all gaps small on both sides → justify (last line excepted)
          * only left gaps small → left
          * only right gaps small → right
          * left gap ≈ right gap on every line → center
        Tolerance scales with font size so a 24pt heading isn't
        held to the same px budget as 9pt body text.
        """
        bx0, _, bx1, _ = block["bbox"]
        block_w = bx1 - bx0
        if block_w <= 1.0:
            return "left"
        lines = [ln for ln in block.get("lines", []) if ln.get("spans")]
        if not lines:
            return "left"
        tol = max(2.0, fontsize * 0.4)
        left_gaps: list[float] = []
        right_gaps: list[float] = []
        for ln in lines:
            lx0, _, lx1, _ = ln["bbox"]
            left_gaps.append(lx0 - bx0)
            right_gaps.append(bx1 - lx1)
        # Justify: every line but optionally the last reaches both
        # edges. Need at least two lines for "justify" to be meaningful.
        if len(lines) >= 2:
            filled = sum(
                1 for lg, rg in zip(left_gaps, right_gaps)
                if lg < tol and rg < tol
            )
            if filled >= len(lines) - 1:
                return "justify"
        left_flush = all(lg < tol for lg in left_gaps)
        right_flush = all(rg < tol for rg in right_gaps)
        if left_flush and right_flush:
            return "justify"
        if left_flush:
            return "left"
        if right_flush:
            return "right"
        if all(abs(lg - rg) < tol for lg, rg in zip(left_gaps, right_gaps)):
            return "center"
        return "left"
