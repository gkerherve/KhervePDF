"""Document outline / table-of-contents panel.

Sits in the side panel next to the page thumbnails. Reads the PDF's
bookmark tree via `fitz.Document.get_toc()` — which returns a flat
list of `(level, title, page)` tuples — and rebuilds it as a nested
QTreeWidget. Clicking an entry emits page_clicked(idx) so the main
window can scroll the active PdfTab to that page (same handler the
thumbnails panel uses).
"""
from __future__ import annotations

from typing import Optional

import fitz
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


class OutlinePanel(QTreeWidget):
    page_clicked = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QTreeWidget.SingleSelection)
        self.itemClicked.connect(self._on_clicked)

    def set_document(self, doc: Optional[fitz.Document]) -> None:
        self.clear()
        if doc is None:
            return
        try:
            toc = doc.get_toc() or []
        except Exception:
            toc = []
        if not toc:
            # Most papers / reports don't carry a saved TOC. Auto-
            # detect by scanning for lines whose font size is
            # noticeably larger than the body — gives a usable jump
            # map without the user having to add bookmarks first.
            toc = self._auto_detect_headings(doc)
        if not toc:
            placeholder = QTreeWidgetItem(self,
                                          ["(no table of contents)"])
            placeholder.setDisabled(True)
            return
        # Build a tree from the flat (level, title, page) list. The
        # stack carries (level, parent_item) pairs so deeper entries
        # nest under the most recent parent at level - 1.
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for entry in toc:
            if len(entry) < 3:
                continue
            level = int(entry[0])
            title = str(entry[1])
            # PyMuPDF's TOC page numbers are 1-based; the rest of the
            # app uses 0-based page indices.
            page_idx = max(0, int(entry[2]) - 1)
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else self.invisibleRootItem()
            item = QTreeWidgetItem(parent, [title])
            item.setData(0, Qt.UserRole, page_idx)
            item.setToolTip(0, f"Page {page_idx + 1}")
            stack.append((level, item))
        # Expand the first two levels by default — usually chapters
        # plus their immediate sections. Anything deeper stays
        # collapsed so long TOCs don't drown the panel.
        self.expandToDepth(1)

    def _on_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        page = item.data(0, Qt.UserRole)
        if page is not None:
            self.page_clicked.emit(int(page))

    @staticmethod
    def _auto_detect_headings(doc: fitz.Document) -> list[list]:
        """Build a synthetic TOC by scanning every page for lines
        whose font size is noticeably larger than the body. Body size
        = the size with the most characters across the whole document
        (a robust proxy for "regular text"). Anything > 1.2× that
        becomes a heading; up to six size buckets are mapped to
        outline levels 1–6 by descending size.

        Tuned to be useful, not perfect — papers and reports vary
        wildly in how they style headings, but a coarse map by font
        size is better than the empty placeholder we showed before.
        """
        sizes_chars: dict[float, int] = {}
        candidates: list[tuple[int, float, str]] = []
        for page_idx in range(doc.page_count):
            try:
                page = doc.load_page(page_idx)
                d = page.get_text("dict")
            except Exception:
                continue
            for block in d.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    line_size = max(
                        float(s.get("size", 0.0)) for s in spans
                    )
                    text = "".join(s.get("text", "") for s in spans).strip()
                    if len(text) < 3:
                        continue
                    rsz = round(line_size, 1)
                    sizes_chars[rsz] = sizes_chars.get(rsz, 0) + len(text)
                    candidates.append((page_idx, rsz, text))
        if not candidates or not sizes_chars:
            return []
        body_size = max(sizes_chars, key=sizes_chars.get)
        threshold = body_size * 1.2
        # Keep headings under 200 chars — anything longer is almost
        # certainly a body line typeset in a slightly different size,
        # not a real heading.
        headings = [(p, sz, t) for p, sz, t in candidates
                    if sz > threshold and len(t) <= 200]
        if not headings:
            return []
        unique_sizes = sorted({sz for _, sz, _ in headings}, reverse=True)
        level_map = {sz: i + 1 for i, sz in enumerate(unique_sizes[:6])}
        return [[level_map[sz], t, p + 1] for p, sz, t in headings]
