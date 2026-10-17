"""Side-by-side comparison of two PDFs (two files, or the open file
against one of its git commits). Words removed from the left version
are marked red, words added in the right version green; the two panes
scroll together."""
from __future__ import annotations

import fitz
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from . import doc_tools, reading

_GAP = 12
_SCALE = 1.4


class _Pane(QGraphicsView):
    def __init__(self, doc: fitz.Document, marks: dict[int, list],
                 color: QColor, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(Qt.gray)
        self.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.page_tops: list[float] = []
        y, max_w = 0.0, 0.0
        fill = QColor(color)
        fill.setAlpha(90)
        m = fitz.Matrix(_SCALE, _SCALE)
        for page in doc:
            pix = page.get_pixmap(matrix=m, alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format_RGB888).copy()
            item = QGraphicsPixmapItem(QPixmap.fromImage(reading.apply_night(img)))
            item.setPos(0, y)
            self.scene().addItem(item)
            rot = page.rotation_matrix if page.rotation else None
            for r in marks.get(page.number, []):
                if rot is not None:
                    r = r * rot
                box = QGraphicsRectItem(QRectF(r.x0 * _SCALE, y + r.y0 * _SCALE,
                                               r.width * _SCALE, r.height * _SCALE))
                box.setPen(QPen(Qt.NoPen))
                box.setBrush(QBrush(fill))
                self.scene().addItem(box)
            self.page_tops.append(y)
            y += pix.height + _GAP
            max_w = max(max_w, pix.width)
        self.scene().setSceneRect(QRectF(0, 0, max_w, max(1.0, y - _GAP)))

    def scroll_to_page(self, idx: int) -> None:
        if 0 <= idx < len(self.page_tops):
            self.verticalScrollBar().setValue(int(self.page_tops[idx]))


class CompareDialog(QDialog):
    def __init__(self, parent, doc_a: fitz.Document, label_a: str,
                 doc_b: fitz.Document, label_b: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Compare — {label_a}  ↔  {label_b}")
        self.resize(1400, 900)
        self._docs = (doc_a, doc_b)
        removed, added, stats = doc_tools.compare_documents(doc_a, doc_b)
        self._change_pages = sorted(set(removed) | set(added))
        self._ci = -1

        lay = QVBoxLayout(self)
        if stats["changed"]:
            summary = (f"<b>{stats['changed']}</b> change(s): "
                       f"<span style='color:#c62828'>{stats['removed']} word(s) "
                       f"removed</span>, <span style='color:#2e7d32'>"
                       f"{stats['added']} word(s) added</span>.")
        else:
            summary = "<b>No text differences.</b> (Images and layout are not compared.)"
        top = QHBoxLayout()
        top.addWidget(QLabel(summary), 1)
        self._sync = QCheckBox("Scroll together")
        self._sync.setChecked(True)
        top.addWidget(self._sync)
        prev_btn = QPushButton("◀ Previous change")
        next_btn = QPushButton("Next change ▶")
        prev_btn.clicked.connect(lambda: self._step(-1))
        next_btn.clicked.connect(lambda: self._step(1))
        for b in (prev_btn, next_btn):
            b.setEnabled(bool(self._change_pages))
            top.addWidget(b)
        lay.addLayout(top)

        split = QSplitter(Qt.Horizontal, self)
        self._a = _Pane(doc_a, removed, QColor("#e53935"))
        self._b = _Pane(doc_b, added, QColor("#43a047"))
        for pane, label in ((self._a, label_a), (self._b, label_b)):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(QLabel(f"<b>{label}</b>"))
            v.addWidget(pane, 1)
            split.addWidget(w)
        lay.addWidget(split, 1)
        self._a.verticalScrollBar().valueChanged.connect(
            lambda v: self._mirror(self._a, self._b, v))
        self._b.verticalScrollBar().valueChanged.connect(
            lambda v: self._mirror(self._b, self._a, v))
        self._mirroring = False

        bb = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _mirror(self, src: _Pane, dst: _Pane, value: int) -> None:
        if self._mirroring or not self._sync.isChecked():
            return
        sb, db = src.verticalScrollBar(), dst.verticalScrollBar()
        self._mirroring = True
        db.setValue(int(value / max(1, sb.maximum()) * db.maximum()))
        self._mirroring = False

    def _step(self, delta: int) -> None:
        if not self._change_pages:
            return
        self._ci = (self._ci + delta) % len(self._change_pages)
        pno = self._change_pages[self._ci]
        self._mirroring = True
        self._a.scroll_to_page(pno)
        self._b.scroll_to_page(pno)
        self._mirroring = False

    def done(self, r: int) -> None:  # noqa: D401
        super().done(r)
        for d in self._docs:
            d.close()
