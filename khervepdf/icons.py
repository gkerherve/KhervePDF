"""Runtime icon factory.

CLAUDE.md forbids shipping PNG/SVG files for UI chrome. All icons are
drawn at runtime via qtawesome (Material Design Icons, with Font
Awesome fallbacks). Each icon is themed with a per-action
accent colour so the toolbar reads as polychrome — the same look as
KherveTeX / KherveSheet, where Save is green, Pen is blue, Redact is
red, etc.

Public API:
  * icon(name)            -> QIcon, coloured from the per-action palette
  * icon(name, color=...) -> QIcon, with an explicit override
  * set_dark(bool)        -> swap to lighter shades for dark themes
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

import qtawesome as qta


# Semantic name -> qtawesome glyph spec. Names mirror the action labels
# used by mainwindow's toolbar so callers don't have to know glyph codes.
#
# Material Design Icons (mdi6) rather than Font Awesome: FA5's solid set
# mixes filled and outline shapes of very different visual weight (a
# solid floppy next to a hairline minus), which made the toolbar look
# uneven. MDI's outline family shares one stroke weight and 24-px grid,
# and has purpose-made glyphs (text cursor, marker, vector line, hand)
# where FA only had approximations.
_GLYPHS: dict[str, str] = {
    # File
    "new":        "mdi6.file-plus-outline",
    "open":       "mdi6.folder-open-outline",
    "save":       "mdi6.content-save-outline",
    "save_as":    "mdi6.content-save-edit-outline",
    "print":      "mdi6.printer-outline",
    "export_png": "mdi6.file-image-outline",
    "export_txt": "mdi6.file-document-outline",
    "close":      "mdi6.close",

    # Edit
    "undo":   "mdi6.undo",
    "redo":   "mdi6.redo",
    "cut":    "mdi6.content-cut",
    "copy":   "mdi6.content-copy",
    "paste":  "mdi6.content-paste",
    "find":   "mdi6.magnify",

    # View / zoom
    "zoom_in":   "mdi6.magnify-plus-outline",
    "zoom_out":  "mdi6.magnify-minus-outline",
    "fit_width": "mdi6.arrow-expand-horizontal",
    "fit_page":  "mdi6.fit-to-page-outline",
    "rotate_l":  "mdi6.rotate-left",
    "rotate_r":  "mdi6.rotate-right",
    "thumbs":    "mdi6.view-grid-outline",
    "hide_panel": "mdi6.chevron-double-left",
    "hide_panel_r": "mdi6.chevron-double-right",

    # AI assistant panel
    "ai":         "mdi6.robot-outline",
    "refresh":    "mdi6.refresh",
    "send":       "mdi6.send",
    "stop":       "mdi6.stop-circle-outline",
    "settings":   "mdi6.cog-outline",
    "clear_chat": "mdi6.delete-sweep-outline",
    "help":       "mdi6.help-circle-outline",
    "close_x":    "mdi6.close",

    # Tools — select (arrow) and select_text (I-beam) must stay visually
    # distinct: they sit side by side in the toolbar.
    "select":    "mdi6.cursor-default-outline",
    "select_text": "mdi6.cursor-text",
    "hand":      "mdi6.hand-back-right-outline",
    "image":     "mdi6.image-outline",
    "edit_text": "mdi6.text-box-edit-outline",
    "move_text": "mdi6.cursor-move",
    "pen":       "mdi6.draw-pen",
    "highlight": "mdi6.marker",
    "strikeout": "mdi6.format-strikethrough-variant",
    "snapshot":  "mdi6.monitor-screenshot",
    "ocr":       "mdi6.text-recognition",
    "text":      "mdi6.format-text",
    "line":      "mdi6.vector-line",
    "arrow":     "mdi6.arrow-top-right",
    "rect":      "mdi6.rectangle-outline",
    "ellipse":   "mdi6.ellipse-outline",
    "note":      "mdi6.note-outline",
    "signature": "mdi6.signature-freehand",
    "erase":     "mdi6.eraser",

    # Pages
    "page_insert": "mdi6.file-plus",
    "page_delete": "mdi6.delete-outline",
    "page_merge":  "mdi6.set-merge",
    "page_split":  "mdi6.scissors-cutting",
    "reorder":     "mdi6.sort",

    # Git
    "commit":  "mdi6.source-commit",
    "history": "mdi6.history",
    "remote":  "mdi6.cloud-upload-outline",
    "branch":  "mdi6.source-branch",

    # Rich-text dialog
    "bold":          "mdi6.format-bold",
    "italic":        "mdi6.format-italic",
    "underline":     "mdi6.format-underline",
    "superscript":   "mdi6.format-superscript",
    "subscript":     "mdi6.format-subscript",
    "align_left":    "mdi6.format-align-left",
    "align_center":  "mdi6.format-align-center",
    "align_right":   "mdi6.format-align-right",
    "align_justify": "mdi6.format-align-justify",

    # Help / updates
    "about":  "mdi6.information-outline",
    "update": "mdi6.update",
    "download": "mdi6.download",
    "recent_doc": "mdi6.file-pdf-box",
}


# Font Awesome 5 fallbacks — the pre-v0.72 glyph set. Only used if an
# older qtawesome lacks one of the mdi6 names above, so a missing glyph
# degrades to the previous look rather than a "?" icon.
_FALLBACK_GLYPHS: dict[str, str] = {
    # File
    "new":        "fa5s.file",
    "open":       "fa5s.folder-open",
    "save":       "fa5s.save",
    "save_as":    "fa5s.file-export",
    "print":      "fa5s.print",
    "export_png": "fa5s.image",
    "export_txt": "fa5s.file-alt",
    "close":      "fa5s.times",

    # Edit
    "undo":   "fa5s.undo",
    "redo":   "fa5s.redo",
    "cut":    "fa5s.cut",
    "copy":   "fa5s.copy",
    "paste":  "fa5s.paste",
    "find":   "fa5s.search",

    # View / zoom
    "zoom_in":   "fa5s.search-plus",
    "zoom_out":  "fa5s.search-minus",
    "fit_width": "fa5s.arrows-alt-h",
    "fit_page":  "fa5s.expand",
    "rotate_l":  "fa5s.undo-alt",
    "rotate_r":  "fa5s.redo-alt",
    "thumbs":    "fa5s.th-list",
    "hide_panel": "fa5s.angle-double-left",
    "hide_panel_r": "fa5s.angle-double-right",

    # AI assistant panel
    "ai":         "fa5s.robot",
    "refresh":    "fa5s.sync-alt",
    "send":       "fa5s.paper-plane",
    "stop":       "fa5s.stop",
    "settings":   "fa5s.cog",
    "clear_chat": "fa5s.trash-alt",
    "help":       "fa5s.question-circle",
    "close_x":    "fa5s.times",

    # Tools
    "select":    "fa5s.mouse-pointer",
    "select_text": "fa5s.text-width",
    "hand":      "fa5s.hand-paper",
    "image":     "fa5s.image",
    "edit_text": "fa5s.i-cursor",
    "move_text": "fa5s.arrows-alt",
    "pen":       "fa5s.pen",
    "highlight": "fa5s.highlighter",
    "strikeout": "fa5s.strikethrough",
    "snapshot":  "fa5s.crop",
    "ocr":       "fa5s.font",
    "text":      "fa5s.font",
    "line":      "fa5s.minus",
    "arrow":     "fa5s.long-arrow-alt-right",
    "rect":      "fa5.square",
    "ellipse":   "fa5.circle",
    "note":      "fa5s.sticky-note",
    "signature": "fa5s.signature",
    "erase":     "fa5s.eraser",

    # Pages
    "page_insert": "fa5s.file-medical",
    "page_delete": "fa5s.trash",
    "page_merge":  "fa5s.object-group",
    "page_split":  "fa5s.cut",
    "reorder":     "fa5s.sort",

    # Git
    "commit":  "fa5s.code-branch",
    "history": "fa5s.history",
    "remote":  "fa5s.cloud",
    "branch":  "fa5s.code-branch",

    # Rich-text dialog
    "bold":          "fa5s.bold",
    "italic":        "fa5s.italic",
    "underline":     "fa5s.underline",
    "superscript":   "fa5s.superscript",
    "subscript":     "fa5s.subscript",
    "align_left":    "fa5s.align-left",
    "align_center":  "fa5s.align-center",
    "align_right":   "fa5s.align-right",
    "align_justify": "fa5s.align-justify",

    # Help
    "about": "fa5s.info-circle",
    "update": "fa5s.sync-alt",
    "download": "fa5s.download",
    "recent_doc": "fa5s.file-pdf",
}


# Per-action accent colours. Picked to be readable on the light Fusion
# palette and distinct from one another at a glance. set_dark() lightens
# these on dark themes.
_COLORS_LIGHT: dict[str, str] = {
    # File — green family for create/save, blue for open
    "new":        "#2e7d32",
    "open":       "#1565c0",
    "save":       "#2e7d32",
    "save_as":    "#2e7d32",
    "print":      "#37474f",
    "export_png": "#6a1b9a",
    "export_txt": "#37474f",
    "close":      "#b00020",

    # Edit — neutral greys, search blue
    "undo":  "#455a64",
    "redo":  "#455a64",
    "cut":   "#455a64",
    "copy":  "#455a64",
    "paste": "#455a64",
    "find":  "#1565c0",

    # View — teal family
    "zoom_in":   "#00838f",
    "zoom_out":  "#00838f",
    "fit_width": "#00838f",
    "fit_page":  "#00838f",
    "rotate_l":  "#00838f",
    "rotate_r":  "#00838f",
    "thumbs":    "#455a64",
    "hide_panel": "#455a64",
    "hide_panel_r": "#455a64",
    "ai":         "#7b1fa2",
    "refresh":    "#00838f",

    # Tools — semantically coloured: pen=blue, highlight=yellow, etc.
    "select":    "#37474f",
    "select_text": "#37474f",
    "hand":      "#1565c0",
    "image":     "#6a1b9a",
    "edit_text": "#5d4037",
    "move_text": "#1565c0",
    "pen":       "#1976d2",
    "highlight": "#fbc02d",
    "strikeout": "#c62828",
    "snapshot":  "#00838f",
    "ocr":       "#6a1b9a",
    "text":      "#5d4037",
    "line":      "#212121",
    "arrow":     "#212121",
    "rect":      "#388e3c",
    "ellipse":   "#7b1fa2",
    "note":      "#fbc02d",
    "signature": "#0d47a1",
    "erase":     "#c62828",

    # Pages
    "page_insert": "#2e7d32",
    "page_delete": "#c62828",
    "page_merge":  "#1565c0",
    "page_split":  "#ef6c00",
    "reorder":     "#455a64",

    # Git — Git orange / branch green
    "commit":  "#2e7d32",
    "history": "#455a64",
    "remote":  "#1565c0",
    "branch":  "#ef6c00",

    "about": "#1565c0",
    "update": "#2e7d32",
    "download": "#2e7d32",
    "recent_doc": "#c62828",

    # Rich-text dialog — neutral charcoal
    "bold":          "#212121",
    "italic":        "#212121",
    "underline":     "#212121",
    "superscript":   "#37474f",
    "subscript":     "#37474f",
    "align_left":    "#455a64",
    "align_center":  "#455a64",
    "align_right":   "#455a64",
    "align_justify": "#455a64",
}

# Lighter variants for dark themes — same hues, raised value/saturation
# so they read against a dark window background.
_COLORS_DARK: dict[str, str] = {
    "new":        "#6abf69",
    "open":       "#64b5f6",
    "save":       "#6abf69",
    "save_as":    "#6abf69",
    "print":      "#b0bec5",
    "export_png": "#ce93d8",
    "export_txt": "#b0bec5",
    "close":      "#ef9a9a",

    "undo":  "#b0bec5", "redo":  "#b0bec5",
    "cut":   "#b0bec5", "copy":  "#b0bec5", "paste": "#b0bec5",
    "find":  "#64b5f6",

    "zoom_in":   "#4dd0e1", "zoom_out":  "#4dd0e1",
    "fit_width": "#4dd0e1", "fit_page":  "#4dd0e1",
    "rotate_l":  "#4dd0e1", "rotate_r":  "#4dd0e1",
    "thumbs":    "#b0bec5",
    "hide_panel": "#b0bec5",
    "hide_panel_r": "#b0bec5",
    "ai":         "#ce93d8",
    "refresh":    "#4dd0e1",

    "select":    "#cfd8dc",
    "select_text": "#cfd8dc",
    "hand":      "#64b5f6",
    "image":     "#ce93d8",
    "edit_text": "#bcaaa4",
    "move_text": "#64b5f6",
    "pen":       "#64b5f6",
    "highlight": "#ffe082",
    "strikeout": "#ef9a9a",
    "snapshot":  "#4dd0e1",
    "ocr":       "#ce93d8",
    "text":      "#bcaaa4",
    "line":      "#eeeeee", "arrow":     "#eeeeee",
    "rect":      "#81c784",
    "ellipse":   "#ce93d8",
    "note":      "#ffe082",
    "signature": "#90caf9",
    "erase":     "#ef9a9a",

    "page_insert": "#6abf69", "page_delete": "#ef9a9a",
    "page_merge":  "#64b5f6", "page_split":  "#ffb74d",
    "reorder":     "#b0bec5",

    "commit":  "#6abf69", "history": "#b0bec5",
    "remote":  "#64b5f6", "branch":  "#ffb74d",

    "about": "#64b5f6",
    "update": "#6abf69", "download": "#6abf69", "recent_doc": "#ef9a9a",

    "bold":          "#eeeeee",
    "italic":        "#eeeeee",
    "underline":     "#eeeeee",
    "superscript":   "#cfd8dc",
    "subscript":     "#cfd8dc",
    "align_left":    "#b0bec5",
    "align_center":  "#b0bec5",
    "align_right":   "#b0bec5",
    "align_justify": "#b0bec5",
}

_dark = False


def set_dark(dark: bool) -> None:
    global _dark
    _dark = bool(dark)


def _color_for(name: str) -> str:
    palette = _COLORS_DARK if _dark else _COLORS_LIGHT
    return palette.get(name, "#cfd8dc" if _dark else "#37474f")


def icon(name: str, color: QColor | str | None = None) -> QIcon:
    """Return a themed QIcon for a semantic action name.

    With no `color`, the per-action accent from the palette is used so
    the toolbar looks polychrome. Pass `color` to force a specific tint
    (e.g. a tool's user-picked stroke colour).
    """
    c = color if color is not None else _color_for(name)
    # Try the MDI glyph, then the FA5 fallback, then a generic "?" —
    # an older qtawesome raising on an unknown name must never take a
    # toolbar down with it.
    for spec in (_GLYPHS.get(name), _FALLBACK_GLYPHS.get(name),
                 "fa5s.question"):
        if not spec:
            continue
        try:
            return qta.icon(spec, color=c)
        except Exception:
            continue
    return QIcon()


def app_icon() -> QIcon:
    """The KhervePDF mark: a white 'KPDF' wordmark above a page-with-
    magnifier symbol on a rounded red tile.

    Drawn at several sizes as stroked vector paths in ``appmark`` (the
    shared Kherve-family icon style) so the taskbar, title bar and
    Alt-Tab each get a sharp, font-independent copy.
    """
    from . import appmark
    ic = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(appmark.paint(sz))
    return ic
