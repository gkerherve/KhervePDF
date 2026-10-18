"""The Edit-Text single-line fast path (_rewrite_single_line).

The promise under test: an edit confined to one visual line rewrites
only that line — every other line of the paragraph keeps its exact
glyph boxes — and anything more complex refuses (returns False)
without touching the document.
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


def _info(tab):
    page = tab._doc[0]
    wf = next(r for r in page.get_text("words") if r[4] == "finally")
    info = tab._find_text_block_detailed(
        page, (wf[0] + wf[2]) / 2, (wf[1] + wf[3]) / 2)
    assert info is not None and len(info["lines"]) == 3
    return page, info


def _word_boxes(page):
    return {r[4]: r[:4] for r in page.get_text("words")}


def test_single_line_edit_keeps_other_lines(tab):
    page, info = _info(tab)
    before = _word_boxes(page)
    old = " ".join(ln["plain"] for ln in info["lines"])
    assert tab._rewrite_single_line(page, info,
                                    old.replace("finally", "finaly"))
    after_text = page.get_text()
    assert "finaly" in after_text and "finally" not in after_text
    # Words on the two untouched lines keep their exact boxes.
    after = _word_boxes(page)
    for token in ("quick", "brown", "report", "section"):
        assert token in after, f"{token} vanished"
        assert all(abs(a - b) < 0.01
                   for a, b in zip(after[token], before[token])), \
            f"{token} moved"


def test_multiline_change_falls_back_untouched(tab):
    page, info = _info(tab)
    before = page.get_text()
    old = " ".join(ln["plain"] for ln in info["lines"])
    new = old.replace("quick", "slow").replace("section", "chapter")
    assert not tab._rewrite_single_line(page, info, new)
    assert page.get_text() == before, "fallback must not mutate the page"


def test_too_long_line_falls_back(tab):
    page, info = _info(tab)
    before = page.get_text()
    old = " ".join(ln["plain"] for ln in info["lines"])
    new = old.replace("finally", "finally " + "very " * 40 + "slowly")
    assert not tab._rewrite_single_line(page, info, new)
    assert page.get_text() == before


def test_reflow_keeps_colour_and_background(app, tmp_path):
    """The full-paragraph path must not paint a white box over a
    tinted background, and must keep the original text colour."""
    path = tmp_path / "tinted.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(60, 80, 400, 200), color=None,
                   fill=(1, 0.95, 0.7))
    page.insert_textbox(fitz.Rect(72, 90, 330, 190),
                        "Blue serif words that will be rewritten across "
                        "several lines of this tinted panel.",
                        fontsize=11, fontname="tiro", color=(0.1, 0.2, 0.6))
    doc.save(str(path))
    doc.close()
    t = PdfTab(path)
    try:
        page = t._doc[0]
        w = next(r for r in page.get_text("words") if r[4] == "serif")
        info = t._find_text_block_detailed(
            page, (w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
        html = ("<html><body><p><span style=\"font-family:'"
                + info["font"] + "'; font-size:11pt;\">Totally new "
                "wording that is clearly longer than the original "
                "paragraph so it has to grow downward a bit.</span>"
                "</p></body></html>")
        t._reflow_paragraph(page, info, html, "")
        spans = [s for b in page.get_text("dict")["blocks"]
                 for ln in b.get("lines", []) for s in ln["spans"]]
        assert spans and all(s["color"] == 0x1a3399 for s in spans)
        assert all(s["size"] == pytest.approx(11.0) for s in spans)
        assert "Totally" in page.get_text()
        pix = page.get_pixmap(clip=fitz.Rect(300, 95, 320, 105))
        r, g, b = pix.pixel(5, 5)
        assert (r, g, b) != (255, 255, 255), "white box painted"
    finally:
        t.close_doc()
