"""Runtime icon factory.

CLAUDE.md forbids shipping PNG/SVG files for UI chrome. All icons are
drawn at runtime via qtawesome (Font Awesome / Material Design Icons).
A single `icon(name)` lookup maps semantic action names to glyphs so the
toolbar and menu code stay free of qtawesome specifics.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QIcon

import qtawesome as qta


# Semantic name -> qtawesome glyph spec. Names mirror the action labels
# used by mainwindow's toolbar so callers don't have to know FA codes.
_GLYPHS: dict[str, str] = {
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

    # Tools
    "select":    "fa5s.mouse-pointer",
    "pen":       "fa5s.pen",
    "highlight": "fa5s.highlighter",
    "text":      "fa5s.font",
    "line":      "fa5s.minus",
    "arrow":     "fa5s.long-arrow-alt-right",
    "rect":      "fa5.square",
    "ellipse":   "fa5.circle",
    "note":      "fa5s.sticky-note",
    "signature": "fa5s.signature",
    "redact":    "fa5s.eraser",

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

    # Help
    "about": "fa5s.info-circle",
}


def icon(name: str, color: QColor | str | None = None) -> QIcon:
    """Return a themed QIcon for a semantic action name.

    Unknown names fall back to a question-mark glyph so a missing entry
    is visible rather than silently empty.
    """
    spec = _GLYPHS.get(name, "fa5s.question")
    kwargs = {}
    if color is not None:
        kwargs["color"] = color
    return qta.icon(spec, **kwargs)
