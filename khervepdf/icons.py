"""Runtime icon factory.

CLAUDE.md forbids shipping PNG/SVG files for UI chrome. All icons are
drawn at runtime via qtawesome (Material Design Icons, with Font
Awesome fallbacks). They are deliberately monochrome: every icon takes
the one colour of the active theme, the same look as KherveCAD.

Public API:
  * icon(name)            -> QIcon in the theme's icon colour
  * icon(name, color=...) -> QIcon with an explicit override
  * set_icon_color(c)     -> retarget new icons to a theme's colour
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
    "author": "mdi6.account-school-outline",
    "update": "mdi6.update",
    "download": "mdi6.download",
    "recent_doc": "mdi6.file-pdf-box",

    # Slideshow — the view switcher in the status bar and the on-stage
    # control bar.
    "normal_view":     "mdi6.page-layout-sidebar-left",
    "slideshow_window": "mdi6.play-box-outline",
    "slideshow_full":  "mdi6.presentation-play",
    "autoplay":        "mdi6.timer-play-outline",
    "play":            "mdi6.play",
    "pause":           "mdi6.pause",
    "prev_page":       "mdi6.skip-previous",
    "next_page":       "mdi6.skip-next",
    "loop":            "mdi6.repeat",
    "fullscreen":      "mdi6.fullscreen",
    "exit_full":       "mdi6.fullscreen-exit",

    # About-the-author page
    "link":     "mdi6.link-variant",
    "github":   "mdi6.github",
    "linkedin": "mdi6.linkedin",
    "email":    "mdi6.email-outline",
    "orcid":    "mdi6.identifier",
    "paper":    "mdi6.file-document-outline",
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
    "author": "fa5s.user-graduate",
    "update": "fa5s.sync-alt",
    "download": "fa5s.download",
    "recent_doc": "fa5s.file-pdf",

    # Slideshow
    "normal_view":     "fa5s.columns",
    "slideshow_window": "fa5s.play-circle",
    "slideshow_full":  "fa5s.desktop",
    "autoplay":        "fa5s.clock",
    "play":            "fa5s.play",
    "pause":           "fa5s.pause",
    "prev_page":       "fa5s.step-backward",
    "next_page":       "fa5s.step-forward",
    "loop":            "fa5s.redo",
    "fullscreen":      "fa5s.expand",
    "exit_full":       "fa5s.compress",

    # About-the-author page
    "link":     "fa5s.link",
    "github":   "fa5b.github",
    "linkedin": "fa5b.linkedin",
    "email":    "fa5s.envelope",
    "orcid":    "fa5s.id-card",
    "paper":    "fa5s.file-alt",
}


#: Glyph colour for every icon — set from the active theme so the whole
#: UI shares one monochrome look (same as KherveCAD).
DEFAULT_COLOR = "#444444"

# cacheKey -> (name, explicit colour). Every icon built here is
# remembered so a live theme switch can rebuild the ones carrying it
# (QAction.icon() and QAbstractButton.icon() share the QIcon data, so
# the key survives); see MainWindow._retint_icons.
_ICON_SPECS: dict[int, tuple[str, object]] = {}


def set_icon_color(color: QColor | str) -> None:
    """Called when the theme changes so new icons follow it."""
    global DEFAULT_COLOR
    DEFAULT_COLOR = QColor(color).name()


def icon_spec(ic: QIcon):
    """(name, explicit colour) an icon was built with, or None."""
    return _ICON_SPECS.get(ic.cacheKey())


def forget_icon_specs() -> None:
    """Drop the registry — called by the retint pass before it rebuilds
    every icon, so superseded icons don't pile up across theme switches."""
    _ICON_SPECS.clear()


def icon(name: str, color: QColor | str | None = None) -> QIcon:
    """Return a QIcon for a semantic action name, in the theme's single
    icon colour. Pass `color` only to force a tint where the icon sits on
    a fixed background (e.g. white on the slideshow's black stage)."""
    c = color if color is not None else DEFAULT_COLOR
    # Try the MDI glyph, then the FA5 fallback, then a generic "?" —
    # an older qtawesome raising on an unknown name must never take a
    # toolbar down with it.
    for spec in (_GLYPHS.get(name), _FALLBACK_GLYPHS.get(name),
                 "fa5s.question"):
        if not spec:
            continue
        try:
            ic = qta.icon(spec, color=c)
        except Exception:
            continue
        _ICON_SPECS[ic.cacheKey()] = (name, color)
        return ic
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
