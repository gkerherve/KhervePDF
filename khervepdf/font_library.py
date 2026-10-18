"""Fonts shipped with KhervePDF for Edit Text.

PDFs mostly embed *subset* fonts (only the letters already used), and
the popular commercial families (Times New Roman, Arial, Calibri …) may
not be redistributed. So ``khervepdf/fonts`` carries free look-alikes,
most of them metric-compatible (same letter widths, so a rewritten line
keeps its length):

  * CMU — Computer Modern Unicode, LaTeX's default face   (OFL)
  * Liberation Serif / Sans / Mono — Times / Arial / Courier New  (OFL)
  * Carlito / Caladea — Calibri / Cambria                (OFL)
  * TeX Gyre Pagella / Bonum / Schola — Palatino / Bookman /
    Century Schoolbook                                   (GUST font licence)

They are registered with Qt (so the editor can show them) and handed to
PyMuPDF as real font files when the edit is written to the page.
"""
from __future__ import annotations

from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent / "fonts"

# family → files for (regular, bold, italic, bold-italic)
_FACES: dict[str, tuple[str, str, str, str]] = {
    "CMU Serif": ("cmu/cmunrm.otf", "cmu/cmunbx.otf",
                  "cmu/cmunti.otf", "cmu/cmunbi.otf"),
    "CMU Sans Serif": ("cmu/cmunss.otf", "cmu/cmunsx.otf",
                       "cmu/cmunsi.otf", "cmu/cmunso.otf"),
    "CMU Typewriter Text": ("cmu/cmuntt.otf", "cmu/cmuntb.otf",
                            "cmu/cmunit.otf", "cmu/cmuntx.otf"),
    "Liberation Serif": tuple(f"liberation/LiberationSerif-{s}.ttf" for s in
                              ("Regular", "Bold", "Italic", "BoldItalic")),
    "Liberation Sans": tuple(f"liberation/LiberationSans-{s}.ttf" for s in
                             ("Regular", "Bold", "Italic", "BoldItalic")),
    "Liberation Mono": tuple(f"liberation/LiberationMono-{s}.ttf" for s in
                             ("Regular", "Bold", "Italic", "BoldItalic")),
    "Carlito": tuple(f"carlito/Carlito-{s}.ttf" for s in
                     ("Regular", "Bold", "Italic", "BoldItalic")),
    "Caladea": tuple(f"caladea/Caladea-{s}.ttf" for s in
                     ("Regular", "Bold", "Italic", "BoldItalic")),
    "TeX Gyre Pagella": tuple(f"tex-gyre/texgyrepagella-{s}.otf" for s in
                              ("regular", "bold", "italic", "bolditalic")),
    "TeX Gyre Bonum": tuple(f"tex-gyre/texgyrebonum-{s}.otf" for s in
                            ("regular", "bold", "italic", "bolditalic")),
    "TeX Gyre Schola": tuple(f"tex-gyre/texgyreschola-{s}.otf" for s in
                             ("regular", "bold", "italic", "bolditalic")),
}

# A system family we can show on screen but have no file for → the
# bundled face to write into the PDF (metric-compatible where one exists).
_PDF_SUBSTITUTE: dict[str, str] = {
    "times new roman": "Liberation Serif", "times": "Liberation Serif",
    "tinos": "Liberation Serif", "georgia": "Liberation Serif",
    "stix two text": "Liberation Serif", "minion pro": "Liberation Serif",
    "arial": "Liberation Sans", "helvetica": "Liberation Sans",
    "helvetica neue": "Liberation Sans", "arimo": "Liberation Sans",
    "verdana": "Liberation Sans", "tahoma": "Liberation Sans",
    "segoe ui": "Liberation Sans",
    "courier new": "Liberation Mono", "courier": "Liberation Mono",
    "menlo": "Liberation Mono", "consolas": "Liberation Mono",
    "cousine": "Liberation Mono",
    "calibri": "Carlito", "cambria": "Caladea",
    "palatino": "TeX Gyre Pagella", "palatino linotype": "TeX Gyre Pagella",
    "book antiqua": "TeX Gyre Pagella",
    "bookman old style": "TeX Gyre Bonum", "bookman": "TeX Gyre Bonum",
    "century schoolbook": "TeX Gyre Schola",
    "new century schoolbook": "TeX Gyre Schola",
    "latin modern roman": "CMU Serif", "computer modern": "CMU Serif",
    "latin modern sans": "CMU Sans Serif",
    "latin modern mono": "CMU Typewriter Text",
}
_GENERIC = {"serif": "Liberation Serif", "sans": "Liberation Sans",
            "mono": "Liberation Mono"}

_registered = False


def families() -> list[str]:
    return list(_FACES)


def register_with_qt() -> None:
    """Make the bundled families available to Qt widgets (once)."""
    global _registered
    if _registered:
        return
    from PySide6.QtGui import QFontDatabase
    for faces in _FACES.values():
        for rel in faces:
            p = FONT_DIR / rel
            if p.exists():
                QFontDatabase.addApplicationFont(str(p))
    _registered = True


def face_file(family: str, bold: bool = False,
              italic: bool = False) -> Path | None:
    """The bundled file for *family* in that style, if we ship it."""
    faces = _FACES.get(family)
    if faces is None:
        key = (family or "").lower()
        faces = next((f for n, f in _FACES.items() if n.lower() == key),
                     None)
    if faces is None:
        return None
    p = FONT_DIR / faces[int(bold) + 2 * int(italic)]
    return p if p.exists() else None


def pdf_family(family: str, generic: str = "serif") -> str:
    """Bundled family to write into the PDF for an on-screen *family*."""
    if face_file(family) is not None:
        return next(n for n in _FACES if n.lower() == family.lower())
    return _PDF_SUBSTITUTE.get((family or "").lower(),
                               _GENERIC.get(generic, "Liberation Serif"))
