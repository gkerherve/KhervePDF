"""Auto-detected outline for PDFs that carry no bookmarks."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from khervepdf.outline import OutlinePanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _doc_with_heading_sizes(sizes: list[float]) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page()
    body = "Body text line that is long enough to dominate the count"
    y = 60
    for i, sz in enumerate(sizes):
        y += 40
        page.insert_text((72, y), f"Heading number {i} at {sz}", fontsize=sz)
    for _ in range(8):
        y += 12
        page.insert_text((72, y), body, fontsize=7.5)
    return doc


def test_more_than_six_heading_sizes_does_not_raise():
    # Regression: eight distinct heading sizes used to KeyError in
    # _auto_detect_headings and abort opening the document.
    doc = _doc_with_heading_sizes([30, 26, 22, 19, 16, 14, 12, 9.3])
    toc = OutlinePanel._auto_detect_headings(doc)
    assert len(toc) == 8
    assert [e[0] for e in toc] == [1, 2, 3, 4, 5, 6, 6, 6]


def test_panel_builds_for_many_heading_sizes(app):
    panel = OutlinePanel()
    panel.set_document(_doc_with_heading_sizes([30, 26, 22, 19, 16, 14, 12, 9.3]))
    assert panel.topLevelItemCount() >= 1
    assert panel.topLevelItem(0).isDisabled() is False


def test_detection_failure_falls_back_to_placeholder(app, monkeypatch):
    def boom(_doc):
        raise RuntimeError("detector blew up")

    monkeypatch.setattr(OutlinePanel, "_auto_detect_headings",
                        staticmethod(boom))
    panel = OutlinePanel()
    panel.set_document(_doc_with_heading_sizes([20]))
    assert panel.topLevelItem(0).text(0) == "(no table of contents)"
