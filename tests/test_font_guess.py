"""Edit Text's font / size guess from real-world PDF font names."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from khervepdf.font_guess import guess_font, guess_size, size_text

MAC = {"Times New Roman", "Arial", "Helvetica", "Helvetica Neue",
       "Courier New", "Georgia", "Palatino", "Menlo"}


@pytest.mark.parametrize("raw,flags,family,bold,italic", [
    ("ABCDEF+TimesNewRomanPS-BoldMT", 0, "Times New Roman", True, False),
    ("TimesNewRomanPS-ItalicMT", 0, "Times New Roman", False, True),
    ("ArialMT", 0, "Arial", False, False),
    ("Arial-BoldItalicMT", 0, "Arial", True, True),
    ("Helvetica-Oblique", 0, "Helvetica", False, True),
    ("NimbusRomNo9L-Regu", 0, "Times New Roman", False, False),
    ("NimbusSanL-Bold", 0, "Helvetica", True, False),
    ("LiberationSerif", 0, "Times New Roman", False, False),
    ("QWERTY+CMR10", 0, "Times New Roman", False, False),
    ("CMBX12", 0, "Times New Roman", True, False),
    ("CMTI10", 0, "Times New Roman", False, True),
    ("CMTT10", 0, "Courier New", False, False),
    ("LMRoman10-Regular", 0, "Times New Roman", False, False),
    ("Calibri-Bold", 0, "Helvetica Neue", True, False),
    ("Cambria", 0, "Georgia", False, False),
    ("PalatinoLinotype-Roman", 0, "Palatino", False, False),
    ("Georgia-Italic", 0, "Georgia", False, True),
    ("CourierNewPSMT", 0, "Courier New", False, False),
    ("F1", 4 | 16, "Times New Roman", True, False),     # serif+bold flags
    ("T1_0", 8, "Courier New", False, False),            # mono flag
    ("F2", 0, "Helvetica", False, False),
])
def test_guess_font(raw, flags, family, bold, italic):
    g = guess_font(raw, flags, installed=MAC)
    assert (g.family, g.bold, g.italic) == (family, bold, italic)


def test_exact_when_installed():
    assert guess_font("Georgia", installed=MAC).exact
    assert not guess_font("CMR10", installed=MAC).exact


@pytest.mark.parametrize("sizes,want", [
    ({10.9589: 50}, 11.0), ({10.5: 9}, 10.5), ({9.9626: 3, 7.0: 1}, 10.0),
    ({11.37: 4}, 11.4),
])
def test_guess_size(sizes, want):
    assert guess_size(sizes) == want


def test_size_text():
    assert (size_text(11.0), size_text(10.5)) == ("11", "10.5")


def test_dialog_opens_with_detected_style(tmp_path):
    QApplication.instance() or QApplication([])
    from unittest import mock
    from khervepdf import pdftab
    path = tmp_path / "bold.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "A bold Times heading line",
                     fontsize=10.5, fontname="tibo")
    doc.save(str(path))
    doc.close()
    seen = {}

    class Probe(pdftab._EditTextDialog):
        def exec(self):
            fmt = self._editor.currentCharFormat()
            seen.update(size=self._size_combo.currentText(),
                        bold=self._bold.isChecked(),
                        label=self.findChild(pdftab.QLabel, "DetectedFont")
                        .text())
            return pdftab.QDialog.Rejected

    t = pdftab.PdfTab(path)
    try:
        w = t._doc[0].get_text("words")[1]
        with mock.patch.object(pdftab, "_EditTextDialog", Probe):
            t._edit_existing_text(0, (w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
    finally:
        t.close_doc()
    assert seen["size"] == "10.5"
    assert seen["bold"]
    assert "10.5 pt" in seen["label"] and "bold" in seen["label"]
