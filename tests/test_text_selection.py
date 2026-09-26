"""Selecting part of the PDF text and editing it in place.

Covers the reader-style workflow: select words (with any text-capable
tool), then replace, delete, highlight or copy just that span, and
paste clipboard text onto the page.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from khervepdf.pdftab import PdfTab


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def tab(app, tmp_path):
    path = tmp_path / "para.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 100),
        "The quick brown fox jumps over the dog\n"
        "until the experiment finally converges\n"
        "which we report in the last section",
        fontsize=11,
    )
    doc.save(str(path))
    doc.close()
    t = PdfTab(path)
    yield t
    t.close_doc()


def _select(tab, first: str, last: str, nth: int = 0):
    words = tab._page_words(0)
    lo = [i for i, w in enumerate(words) if w[4] == first][nth]
    hi = next(i for i, w in enumerate(words) if i >= lo and w[4] == last)
    tab._text_sel_page = 0
    tab._update_text_selection(0, lo, hi)


def _text(tab):
    return " ".join(tab._doc[0].get_text().split())


def test_selection_text_and_range(tab):
    _select(tab, "brown", "jumps")
    assert tab._text_sel_text == "brown fox jumps"
    assert tab._text_sel_range is not None


def test_replace_selected_words(tab):
    _select(tab, "brown", "fox")
    assert tab.replace_selected_text("red cat")
    assert "The quick red cat jumps over the dog" in _text(tab)
    # Other lines untouched.
    assert "until the experiment finally converges" in _text(tab)


def test_repeated_word_hits_the_chosen_occurrence(tab):
    # Second "the" (line 2), not the first one on line 1.
    _select(tab, "the", "the", nth=1)
    assert tab.replace_selected_text("our")
    t = _text(tab)
    assert "over the dog" in t
    assert "until our experiment" in t


def test_delete_selected_text_and_undo(tab):
    _select(tab, "finally", "finally")
    tab.delete_selected_text()
    assert "finally" not in _text(tab)
    tab.undo()
    assert "finally" in _text(tab)


def test_select_all_and_highlight(tab):
    assert tab.select_all_text()
    n = len(tab._page_words(0))
    assert tab.highlight_selection()
    assert sum(a.type == "highlight" for a in tab._annots) == n


def test_copy_as_image(tab):
    _select(tab, "quick", "fox")
    assert tab.copy_selection_as_image()
    assert not QApplication.clipboard().image().isNull()


def test_paste_text_annotation(tab):
    assert tab.paste_text("hello world", at=(0, 100.0, 300.0))
    a = tab._annots[-1]
    assert a.type == "text" and a.text == "hello world"
    assert a.pts == [(100.0, 300.0)]


def test_underline_and_strikeout_roundtrip(tab, tmp_path):
    _select(tab, "quick", "fox")
    assert tab.mark_selection("underline")
    _select(tab, "dog", "dog")
    assert tab.mark_selection("strikeout")
    out = tab.save_to_pdf(tmp_path / "marked.pdf")
    kinds = sorted(a.type[1] for a in fitz.open(str(out))[0].annots())
    assert kinds == ["StrikeOut", "Underline", "Underline", "Underline"]


def test_selection_across_pages(app, tmp_path):
    path = tmp_path / "two.pdf"
    doc = fitz.open()
    for body in ("end of page one", "start of page two"):
        doc.new_page().insert_text((72, 100), body, fontsize=11)
    doc.save(str(path))
    t = PdfTab(path)
    try:
        w1 = t._page_words(1)
        t._text_sel_page = 0
        t._text_sel_anchor = 2  # "page" on page 1
        t._extend_text_selection(1, (w1[1][0] + w1[1][2]) / 2, w1[1][1] + 2)
        assert t._text_sel_text == "page one\n\nstart of"
        assert t._text_sel_range is None  # multi-page: no in-place edit
        assert t.highlight_selection()
        assert {a.page_idx for a in t._annots} == {0, 1}
    finally:
        t.close_doc()


def test_inline_editor_replaces_frozen_range(tab):
    _select(tab, "brown", "brown")
    tab.edit_selected_text()
    ed = tab._inline_replace
    assert ed is not None
    ed.setPlainText("green")
    _select(tab, "dog", "dog")  # selection moves before the commit
    ed.finish(True)
    t = _text(tab)
    assert "quick green fox" in t and "the dog" in t


def test_snapshot_region(tab):
    assert tab.copy_region_as_image(0, fitz.Rect(60, 80, 300, 140))
    assert not QApplication.clipboard().image().isNull()


def test_rotated_page_selection_edit_and_annots(app, tmp_path):
    path = tmp_path / "rot.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "hello rotated world", fontsize=11)
    page.set_rotation(90)
    doc.save(str(path))
    doc.close()
    t = PdfTab(path)
    try:
        page = t._doc[0]
        # Word boxes are in display space: on the rendered pixmap the
        # word's box must contain dark (text) pixels.
        w = t._page_words(0)[0]
        pix = page.get_pixmap(dpi=72)
        dark = [pix.pixel(x, y)[0] < 128
                for x in range(int(w[0]), int(w[2]))
                for y in range(int(w[1]), int(w[3]))]
        assert any(dark)
        _select(t, "rotated", "rotated")
        assert t._text_sel_text == "rotated"
        assert t.highlight_selection()
        disp = t._annots[-1].pts
        out = t.save_to_pdf(tmp_path / "rot_out.pdf")
        t2 = PdfTab(out)
        try:
            back = t2._annots[-1].pts
            # PDF highlight rects carry ~3pt of viewer padding; what
            # matters is that the mark comes back where it was drawn,
            # not rotated 90° away.
            assert all(abs(a - b) < 5.0 for p, q in zip(disp, back)
                       for a, b in zip(p, q))
        finally:
            t2.close_doc()
        _select(t, "rotated", "rotated")
        assert t.replace_selected_text("turned")
        assert "hello turned world" in " ".join(t._doc[0].get_text().split())
    finally:
        t.close_doc()
