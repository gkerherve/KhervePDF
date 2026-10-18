"""Bundled fonts and the font chosen to write an edit into the PDF."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from khervepdf import font_library
from khervepdf.pdftab import PdfTab


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_every_bundled_face_exists_and_loads():
    for fam in font_library.families():
        for bold in (False, True):
            for italic in (False, True):
                p = font_library.face_file(fam, bold, italic)
                assert p is not None and p.exists(), (fam, bold, italic)
                f = fitz.Font(fontfile=str(p))
                assert f.has_glyph(ord("a"))


def test_licences_ship_with_fonts():
    d = font_library.FONT_DIR
    for lic in ("cmu/OFL.txt", "liberation/LICENSE", "carlito/OFL.txt",
                "caladea/OFL.txt", "tex-gyre/GUST-FONT-LICENSE.txt"):
        assert (d / lic).exists(), lic


@pytest.mark.parametrize("family,want", [
    ("Times New Roman", "Liberation Serif"), ("Arial", "Liberation Sans"),
    ("Calibri", "Carlito"), ("Cambria", "Caladea"),
    ("CMU Serif", "CMU Serif"), ("Palatino", "TeX Gyre Pagella"),
    ("Some Unknown Face", "Liberation Serif"),
])
def test_pdf_family(family, want):
    assert font_library.pdf_family(family, "serif") == want


def test_registered_with_qt(app):
    from PySide6.QtGui import QFontDatabase
    font_library.register_with_qt()
    fams = set(QFontDatabase.families())
    assert {"CMU Serif", "Liberation Serif", "Carlito"} <= fams


def _latex_like(tmp_path, subset: bool):
    """A PDF whose body text is set in an embedded CMU Serif."""
    path = tmp_path / "tex.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="F1", fontfile=str(
        font_library.face_file("CMU Serif")))
    page.insert_text((72, 100), "We report the measured values here",
                     fontname="F1", fontsize=10)
    if subset:
        doc.subset_fonts()
    doc.save(str(path))
    doc.close()
    return path


def _edit_line(tab, old_word, new_word):
    page = tab._doc[0]
    w = next(r for r in page.get_text("words") if r[4] == old_word)
    info = tab._find_text_block_detailed(page, (w[0] + w[2]) / 2,
                                         (w[1] + w[3]) / 2)
    old = " ".join(ln["plain"] for ln in info["lines"])
    assert tab._rewrite_single_line(page, info,
                                    old.replace(old_word, new_word))
    return {s["font"] for b in page.get_text("dict")["blocks"]
            for ln in b.get("lines", []) for s in ln["spans"]}


def test_typo_fix_reuses_embedded_subset(app, tmp_path):
    t = PdfTab(_latex_like(tmp_path, subset=True))
    try:
        fonts = _edit_line(t, "measured", "measued")   # letters on hand
        assert fonts == {"CMUSerif-Roman"}
        assert "measued" in t._doc[0].get_text()
    finally:
        t.close_doc()


def test_new_letters_fall_back_to_bundled_face(app, tmp_path):
    t = PdfTab(_latex_like(tmp_path, subset=True))
    try:
        fonts = _edit_line(t, "values", "Kz")          # K, z not in subset
        assert fonts == {"CMUSerif-Roman"}             # same face, bundled
        assert "Kz" in t._doc[0].get_text()
    finally:
        t.close_doc()


def test_detects_latex_font(app, tmp_path):
    t = PdfTab(_latex_like(tmp_path, subset=True))
    try:
        page = t._doc[0]
        w = page.get_text("words")[1]
        info = t._find_text_block_detailed(page, (w[0] + w[2]) / 2,
                                           (w[1] + w[3]) / 2)
        assert info["font"] == "CMU Serif" and info["size"] == 10.0
    finally:
        t.close_doc()
