"""Reading, reference and document-preparation features (v0.76)."""
import fitz
import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from khervepdf import doc_tools, reading


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _paper() -> fitz.Document:
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 100), "As shown before [2] and [1,3-4]. doi:10.1000/abc.123).")
    p2 = d.new_page()
    p2.insert_text((72, 80), "References", fontsize=14)
    y = 100
    for line in ("[1] A. Smith, Nature (2020). https://doi.org/10.1038/xyz-9",
                 "[2] B. Jones, Science 2", "[3] C. Lee, a long title that",
                 "continues here", "[4] D. Who 4"):
        p2.insert_text((72, y), line)
        y += 14
    return d


def test_dois_and_reference_list():
    d = _paper()
    assert doc_tools.find_dois(d) == ["10.1000/abc.123", "10.1038/xyz-9"]
    refs = doc_tools.reference_list(d)
    assert sorted(refs) == [1, 2, 3, 4]
    assert refs[3]["text"] == "C. Lee, a long title that continues here"


@pytest.mark.parametrize("text,nums", [
    ("[3]", [3]), ("[1,3-4]", [1, 3, 4]), ("[2–5]", [2, 3, 4, 5]),
    ("no cite", []),
])
def test_parse_citation(text, nums):
    assert doc_tools.parse_citation(text) == nums


def test_properties_roundtrip():
    d = fitz.open()
    d.new_page()
    doc_tools.set_properties(d, {"title": "T", "keywords": "a, b"})
    props = doc_tools.get_properties(d)
    assert props["title"] == "T" and props["keywords"] == "a, b"


def test_crop_margins_and_reset():
    d = fitz.open()
    d.new_page(width=600, height=800)
    assert doc_tools.crop_pages(d, [0], (10, 20, 30, 40)) == 1
    assert tuple(d[0].cropbox) == (10, 20, 570, 760)
    doc_tools.reset_crop(d, [0])
    assert tuple(d[0].cropbox) == (0, 0, 600, 800)


def test_crop_to_content():
    d = fitz.open()
    p = d.new_page()
    p.insert_text((200, 300), "middle")
    doc_tools.crop_pages(d, [0])
    assert d[0].cropbox.width < 200


def test_stamp_and_bates():
    d = fitz.open()
    for _ in range(3):
        d.new_page()
    doc_tools.add_stamp(d[0], "Approved", date="2026-10-17")
    assert "APPROVED" in d[0].get_text()
    doc_tools.number_pages(d, "bates", prefix="ABC-", start=7, digits=4)
    assert "ABC-0009" in d[2].get_text()
    assert doc_tools.page_label(0, 5, "Page n of total") == "Page 1 of 5"


def test_write_toc_normalises_levels():
    d = fitz.open()
    d.new_page()
    d.new_page()
    doc_tools.write_toc(d, [[2, "x", 1], [4, "y", 2], [1, "z", 9]])
    # PyMuPDF clamps the out-of-range page to the last one.
    assert d.get_toc() == [[1, "x", 1], [2, "y", 2], [1, "z", 2]]


def test_form_fill_and_flatten():
    d = fitz.open()
    p = d.new_page()
    w = fitz.Widget()
    w.field_name = "name"
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.rect = fitz.Rect(72, 400, 250, 420)
    p.add_widget(w)
    f = doc_tools.form_fields(d)[0]
    assert doc_tools.set_field_value(d, 0, f["xref"], "Gwil")
    assert doc_tools.form_fields(d)[0]["value"] == "Gwil"
    doc_tools.flatten_forms(d)
    assert doc_tools.form_fields(d) == []
    assert "Gwil" in d[0].get_text()


def test_compare_documents():
    a = fitz.open()
    a.new_page().insert_text((72, 100), "alpha beta gamma")
    b = fitz.open(stream=a.tobytes(), filetype="pdf")
    b[0].insert_text((72, 300), "new words here")
    removed, added, stats = doc_tools.compare_documents(a, b)
    assert stats["added"] == 3 and stats["removed"] == 0
    assert len(added[0]) == 3 and not removed


def test_split_sentences_skips_abbreviations():
    d = fitz.open()
    d.new_page().insert_text((72, 100), "One two. Fig. 2 shows it! End")
    words = d[0].get_text("words")
    groups = [[words[i][4] for i in s] for s in reading.split_sentences(words)]
    assert groups == [["One", "two."], ["Fig.", "2", "shows", "it!"], ["End"]]


def test_night_modes_recolour(app):
    img = QImage(4, 4, QImage.Format_RGB888)
    img.fill(QColor("white"))
    assert reading.apply_night(img.copy(), "Invert").pixelColor(0, 0) == QColor("black")
    soft = reading.apply_night(img.copy(), "Dark (soft)").pixelColor(0, 0)
    assert soft.lightness() < 60
    sepia = reading.apply_night(img.copy(), "Sepia").pixelColor(0, 0)
    assert sepia.red() > sepia.blue()
    assert reading.apply_night(img, "Off") is img


def test_position_roundtrip(tmp_path):
    f = tmp_path / "a.pdf"
    reading.save_position(f, 4, 0.25, 1.5, False)
    assert reading.load_position(f) == {"page": 4, "frac": 0.25,
                                        "zoom": 1.5, "fit": False}
    assert reading.load_position(tmp_path / "other.pdf") is None


def test_outline_editor_indent(app):
    from khervepdf.features import OutlineEditor
    ed = OutlineEditor(None, [[1, "A", 1], [1, "B", 1], [1, "C", 2]], 2, 0, False)
    ed.tree.setCurrentItem(ed.tree.topLevelItem(1))
    ed._indent()
    assert ed.toc() == [[1, "A", 1], [2, "B", 1], [1, "C", 2]]


def test_window_remembers_position_and_cites(app, tmp_path):
    from khervepdf.mainwindow import MainWindow
    d = _paper()
    for _ in range(3):
        d.insert_page(0, text="filler page")
    f = tmp_path / "paper.pdf"
    d.save(str(f))
    mw = MainWindow()
    mw.show()
    mw.open_path(f)
    app.processEvents()
    tab = mw._current_pdf_tab()
    page = tab._doc[3]
    hit = page.search_for("[2]")[0]
    assert tab.citation_text(3, hit.x0 + 2, (hit.y0 + hit.y1) / 2) \
        .startswith("[2] B. Jones")
    tab.verticalScrollBar().setValue(tab.verticalScrollBar().maximum() // 2)
    saved = tab.reading_position()
    mw._close_tab(0)
    pos = reading.load_position(f)
    assert pos["page"] == saved[0]
    mw.close()
