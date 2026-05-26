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
