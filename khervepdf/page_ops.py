"""Page-level PDF operations: merge, split, insert blank, delete,
rotate. Everything mutates a `fitz.Document` in place except
`split_into_files`, which writes new PDFs to disk.

Callers (mainwindow / pdftab) are responsible for the surrounding
bookkeeping — pushing an undo snapshot, reloading annotations,
calling _render_all and _refresh_thumbs. This module only does the
fitz work.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import fitz


def merge_pdf_into(doc: fitz.Document, other_path: Path,
                   after_page_idx: int = -1) -> int:
    """Insert every page from the PDF at `other_path` into `doc`
    right after `after_page_idx`. -1 (or end of doc) appends.
    Returns the number of pages added."""
    other = fitz.open(str(other_path))
    try:
        added = other.page_count
        if after_page_idx < 0 or after_page_idx >= doc.page_count - 1:
            doc.insert_pdf(other)
        else:
            doc.insert_pdf(other, start_at=after_page_idx + 1)
        return added
    finally:
        other.close()


def delete_page(doc: fitz.Document, page_idx: int) -> bool:
    """Delete a single page. Refuses when the document would be
    emptied — PyMuPDF can't operate on a zero-page doc."""
    if not (0 <= page_idx < doc.page_count):
        return False
    if doc.page_count <= 1:
        return False
    doc.delete_page(page_idx)
    return True


def rotate_page(doc: fitz.Document, page_idx: int,
                delta_degrees: int) -> bool:
    """Rotate a single page by delta_degrees (multiples of 90).
    Wraps around 360°."""
    if not (0 <= page_idx < doc.page_count):
        return False
    page = doc[page_idx]
    new_rot = (int(page.rotation) + int(delta_degrees)) % 360
    page.set_rotation(new_rot)
    return True


def insert_blank(doc: fitz.Document, after_page_idx: int,
                 width: float, height: float) -> int:
    """Insert a blank page after `after_page_idx`. Returns the index
    of the newly inserted page."""
    new_idx = max(0, after_page_idx + 1)
    doc.new_page(pno=new_idx, width=width, height=height)
    return new_idx


def split_into_files(doc: fitz.Document, output_dir: Path,
                     basename: str) -> list[Path]:
    """Write each page of `doc` as its own PDF in `output_dir`,
    named `{basename}_p{N}.pdf`. Returns the list of written paths.
    Existing files are overwritten."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    width = len(str(doc.page_count))
    for i in range(doc.page_count):
        sub = fitz.open()
        try:
            sub.insert_pdf(doc, from_page=i, to_page=i)
            target = out_dir / f"{basename}_p{i + 1:0{width}d}.pdf"
            sub.save(str(target))
            paths.append(target)
        finally:
            sub.close()
    return paths


def extract_pages(doc: fitz.Document, indices: Iterable[int],
                  output_path: Path) -> bool:
    """Save the listed pages (0-based) to a new PDF at output_path."""
    out = fitz.open()
    try:
        for i in sorted(set(indices)):
            if 0 <= i < doc.page_count:
                out.insert_pdf(doc, from_page=i, to_page=i)
        if out.page_count == 0:
            return False
        out.save(str(output_path))
        return True
    finally:
        out.close()
