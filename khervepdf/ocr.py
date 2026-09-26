"""OCR for scanned PDFs, via PyMuPDF's Tesseract bridge.

A scanned page is just a picture, so there is nothing to select, copy,
search or edit. OCR recognises the words and writes them back as an
*invisible* text layer (render mode 3) exactly over the printed words:
the page looks unchanged, but Select Text, Find, Copy and Export Text
now work on it.

PyMuPDF does not bundle Tesseract; it needs the `tesseract` program
and its language data (`tessdata`). We look for both the way PyMuPDF
does (TESSDATA_PREFIX first) plus the usual Homebrew / Linux / Windows
install locations, so a standard install works without configuration.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import fitz

_CANDIDATE_TESSDATA = [
    "/opt/homebrew/share/tessdata",
    "/usr/local/share/tessdata",
    "/usr/share/tesseract-ocr/5/tessdata",
    "/usr/share/tesseract-ocr/4.00/tessdata",
    "/usr/share/tessdata",
    r"C:\Program Files\Tesseract-OCR\tessdata",
]


def tessdata_dir() -> Optional[str]:
    env = os.environ.get("TESSDATA_PREFIX")
    if env and Path(env).is_dir():
        return env
    exe = shutil.which("tesseract")
    if exe:
        # <prefix>/bin/tesseract -> <prefix>/share/tessdata
        guess = Path(exe).resolve().parent.parent / "share" / "tessdata"
        if guess.is_dir():
            return str(guess)
    for d in _CANDIDATE_TESSDATA:
        if Path(d).is_dir():
            return d
    return None


def ocr_available() -> tuple[bool, str]:
    """(ok, message). The message explains how to install Tesseract
    when it's missing."""
    if tessdata_dir() is None:
        if sys.platform == "darwin":
            how = "Install it with Homebrew:\n\n    brew install tesseract"
        elif sys.platform.startswith("win"):
            how = ("Install it from https://github.com/UB-Mannheim/"
                   "tesseract/wiki (keep the default install folder).")
        else:
            how = "Install it with your package manager, e.g.\n\n" \
                  "    sudo apt install tesseract-ocr"
        return False, ("Text recognition needs the free Tesseract OCR "
                       "engine, which was not found.\n\n" + how)
    return True, ""


def page_has_text(page: fitz.Page) -> bool:
    return bool(page.get_text("text").strip())


def ocr_page(page: fitz.Page, language: str = "eng", dpi: int = 300) -> int:
    """Recognise the words on `page` and add them as invisible text.
    Returns the number of words added."""
    tp = page.get_textpage_ocr(language=language, dpi=dpi, full=True,
                               tessdata=tessdata_dir())
    words = page.get_text("words", textpage=tp)
    n = 0
    for x0, y0, x1, y1, text, *_ in words:
        text = text.strip()
        if not text or x1 <= x0 or y1 <= y0:
            continue
        # Size the invisible glyphs so each word spans its box: height
        # from the box, then squeeze horizontally to the box width so
        # selection highlights line up with the printed word.
        size = max(2.0, (y1 - y0) * 0.85)
        natural = fitz.get_text_length(text, fontname="helv", fontsize=size)
        base = fitz.Point(x0, y1 - (y1 - y0) * 0.2)
        morph = None
        if natural > 0:
            morph = (base, fitz.Matrix((x1 - x0) / natural, 1))
        page.insert_text(base, text, fontname="helv",
                         fontsize=size, render_mode=3, morph=morph)
        n += 1
    return n
