"""What every toolbar button does, and how to use it.

Each entry is (title, what it does, [how-to steps], tip). `rich()` turns
one into the wide HTML tooltip the button shows on hover, and
`summary()` the one-line status-bar text (same scheme as KherveCAD).
"""
from __future__ import annotations

#: tooltip width in pixels — without it QToolTip lays a long paragraph
#: out on one line as wide as the screen
WIDTH = 360

_DROPDOWN = ("Click the small ▾ arrow beside the button for its colour, "
             "thickness and opacity.")

TIPS: dict[str, tuple] = {
    # ------------------------------------------------------------ file
    "open": (
        "Open PDF",
        "Opens one or more PDFs, each in its own tab. Files you open come "
        "back at the page and zoom where you left them.",
        ["Click, then pick the file(s).",
         "Or drag PDFs from Finder / Explorer onto the window.",
         "File ▸ Open Recent lists the last files you used."],
        "Opening a PDF while KhervePDF is running adds a tab to this "
        "window instead of starting a second copy."),
    "save": (
        "Save",
        "Writes your annotations, text edits and page changes into the "
        "PDF. Annotations stay editable after saving.",
        ["Click (or Ctrl+S) to save in place.",
         "File ▸ Save As… keeps the original untouched."],
        "If the PDF lives in a git repository, each save can be "
        "committed — see the Git menu to browse or compare versions."),
    "undo": (
        "Undo",
        "Takes back the last change — an annotation, a text edit, a page "
        "operation, a stamp or crop.",
        ["Click, or press Ctrl+Z. Repeat to go further back (20 steps)."],
        None),
    "redo": (
        "Redo",
        "Puts back a change you just undid.",
        ["Click, or press Ctrl+Y."],
        None),
    "image": (
        "Insert image",
        "Places a picture (PNG, JPEG…) onto the current page — a logo, "
        "a figure, a scanned signature.",
        ["Click and choose the image file.",
         "It lands on the page you are viewing; drag it with Select to "
         "move it."],
        "Copy any image and press Ctrl+V on the page to paste it "
        "directly."),
    "thumbs": (
        "Pages & contents panel",
        "Shows or hides the left panel: page thumbnails and the "
        "document's outline (table of contents).",
        ["Click a thumbnail or an outline entry to jump there.",
         "Drag thumbnails up or down to reorder pages.",
         "Pages ▸ Edit Outline… adds, renames and nests bookmarks."],
        None),
    "ai": (
        "AI assistant",
        "Shows or hides the AI panel on the right: ask questions about "
        "the open PDF and get answers grounded in its text.",
        ["Type a question and press Enter — it sees the current page and "
         "any text you selected.",
         "Ask ▾ has presets: summarise the paper, list the methods, key "
         "findings… (with page numbers).",
         "Tools ▸ Ask AI About an Area (Ctrl+Shift+A): drag a box over a "
         "figure or equation to have it explained."],
        "Choose the provider and model with the gear icon in the panel."),

    # ----------------------------------------------------- navigation
    "hand": (
        "Hand",
        "The reading tool: drag to scroll the page, and drag over text "
        "to select it.",
        ["Drag on empty page space to pan.",
         "Drag over words to select them; Ctrl+C copies.",
         "Right-click a selection to highlight, underline, edit or "
         "delete it.",
         "Hover a citation like [12] to read that reference in a popup."],
        "Double-click a word to select just that word; double-click a "
        "form field to fill it in."),
    "select": (
        "Select",
        "Picks annotations you have drawn (shapes, ink, notes, text "
        "boxes) to move or delete them; also selects text.",
        ["Click an annotation to select it, or drag a box around several.",
         "Drag a selected annotation to move it.",
         "Press Delete to remove the selection."],
        None),
    "select_text": (
        "Select text",
        "Selects text only — never pans or picks annotations — for "
        "precise copying across lines and pages.",
        ["Drag from the first word to the last; dragging past the window "
         "edge scrolls to the next page.",
         "Ctrl+C copies; Ctrl+A selects the whole page.",
         "Right-click for Copy as Image, Highlight, Edit…"],
        "View ▸ Read Aloud starts reading from the selected sentence."),
    "snapshot": (
        "Snapshot",
        "Copies an area of a page as a picture — figures, tables, "
        "equations — exactly as you see it, annotations included.",
        ["Drag a box over the area.",
         "It goes to the clipboard: paste it into slides, a document or "
         "a chat."],
        "Ask AI About an Area uses the same box but sends it to the "
        "assistant."),

    # ------------------------------------------------------- marking up
    "pen": (
        "Pen",
        "Freehand ink — circle things, write by hand, sketch.",
        ["Press and drag to draw; release to finish the stroke.",
         _DROPDOWN],
        "Use the Eraser or Select + Delete to remove a stroke."),
    "highlight": (
        "Highlight",
        "Marks text with a translucent highlighter that follows the "
        "lines of text.",
        ["Swipe over the text to highlight.",
         "Or select text first, then right-click ▸ Highlight.",
         _DROPDOWN],
        None),
    "underline": (
        "Underline",
        "Underlines the text you swipe over, line by line.",
        ["Swipe over the text.", _DROPDOWN],
        None),
    "strikeout": (
        "Strikethrough",
        "Strikes through text — the usual mark for 'delete this' when "
        "reviewing.",
        ["Swipe over the text.", _DROPDOWN],
        None),
    "text": (
        "Add text",
        "Types new text anywhere on a page — fill in a flat form, add a "
        "comment, label a figure.",
        ["Click where the text should start.",
         "Type; a small bar above the box sets font, size, bold, "
         "alignment and rotation.",
         "Click outside the box to finish.",
         _DROPDOWN],
        "Right-click a page ▸ Add Text Here does the same."),
    "edit_text": (
        "Edit existing text",
        "Rewrites text that is already in the PDF — fix a typo, change "
        "a date — keeping the original font as closely as possible.",
        ["Click on a paragraph or line.",
         "Edit it in the dialog (formatting, line breaks).",
         "OK replaces it on the page."],
        "For a few words, select them and right-click ▸ Edit Selected "
        "Text… to edit them in place."),
    "move_text": (
        "Move text",
        "Drags a whole paragraph of the PDF's own text to a new place on "
        "the page.",
        ["Press on the paragraph — a ghost outline appears.",
         "Drag it where you want it and release."],
        None),
    "line": (
        "Line",
        "Draws a straight line.",
        ["Press at the start, drag to the end, release.",
         _DROPDOWN],
        None),
    "arrow": (
        "Arrow",
        "Draws an arrow pointing at something.",
        ["Press where the tail goes, drag to the point, release.",
         _DROPDOWN],
        None),
    "rect": (
        "Rectangle",
        "Draws a box around something — or, filled, covers it.",
        ["Press at one corner, drag to the other, release.",
         _DROPDOWN + " 'Fill' gives it a solid colour."],
        None),
    "ellipse": (
        "Ellipse",
        "Draws a circle or oval around something.",
        ["Press at one corner of its bounding box and drag.",
         _DROPDOWN],
        None),
    "note": (
        "Sticky note",
        "Adds a note icon with a pop-up comment — the classic review "
        "comment.",
        ["Click where the note belongs.",
         "Type the comment in the yellow pop-up; click away to keep it.",
         "Click the note icon later to read or edit it."],
        None),
    "signature": (
        "Signature",
        "Signs the PDF with a handwritten signature you draw.",
        ["Drag a box where the signature goes.",
         "Draw your signature with the mouse or trackpad and press OK."],
        "File ▸ Digitally sign… adds a cryptographic (certificate) "
        "signature instead."),
    "erase": (
        "Eraser",
        "Removes annotations — ink, shapes, highlights, notes — by "
        "rubbing over them. It never touches the PDF's own content.",
        ["Click an annotation, or drag across several to erase them all "
         "in one go (one Undo brings them back)."],
        None),

    # ------------------------------------------------------------ zoom
    "zoom_out": (
        "Zoom out",
        "Makes the pages smaller to see more at once.",
        ["Click, or press Ctrl+−.", "Ctrl + mouse wheel zooms too."],
        None),
    "zoom_in": (
        "Zoom in",
        "Makes the pages larger for close reading.",
        ["Click, or press Ctrl++.", "Ctrl + mouse wheel zooms too."],
        None),
    "fit_width": (
        "Fit width",
        "Sizes the page to fill the window's width, and keeps it fitted "
        "when you resize the window.",
        ["Click, or press Ctrl+0."],
        "The zoom box beside it takes a typed percentage."),
    "zoom_combo": (
        "Zoom level",
        "Shows the current zoom; pick a preset or type a percentage.",
        ["Choose Fit Width or a percentage from the list.",
         "Or type a number (e.g. 140) and press Enter."],
        None),
}


def summary(key: str) -> str:
    title, what, _s, _t = TIPS[key]
    return f"{title} — {what}"


def rich(key: str, shortcut: str = "") -> str:
    """The HTML tooltip: title (+ shortcut), what it does, numbered
    steps and a tip."""
    title, what, steps, tip = TIPS[key]
    keys = (f" &nbsp;<span style='color:#8a8a8a'>{shortcut}</span>"
            if shortcut else "")
    parts = [f"<b>{title}</b>{keys}",
             f"<p style='margin:4px 0 0 0'>{what}</p>"]
    if steps:
        items = "".join(f"<li>{s}</li>" for s in steps)
        parts.append("<p style='margin:6px 0 0 0'><b>How to use</b></p>"
                     f"<ol style='margin:2px 0 0 0'>{items}</ol>")
    if tip:
        parts.append("<p style='margin:4px 0 0 0; color:#8a8a8a'>"
                     f"<i>Tip:</i> {tip}</p>")
    return (f"<table width='{WIDTH}' cellspacing='0' cellpadding='0'>"
            f"<tr><td>{''.join(parts)}</td></tr></table>")


SHORTCUTS = {
    "open": "Ctrl+O", "save": "Ctrl+S", "undo": "Ctrl+Z", "redo": "Ctrl+Y",
    "zoom_in": "Ctrl++", "zoom_out": "Ctrl+−", "fit_width": "Ctrl+0",
}


def apply(target, key: str) -> None:
    """Give a QAction / QWidget its rich tooltip and status-bar text."""
    if key not in TIPS:
        return
    target.setToolTip(rich(key, SHORTCUTS.get(key, "")))
    if hasattr(target, "setStatusTip"):
        target.setStatusTip(summary(key))
