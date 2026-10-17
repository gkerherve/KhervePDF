"""Hand-drawn toolbar icons.

The main toolbar's icons are painted here with QPainter on a 24-unit
grid instead of taken from an icon font: each one is a duotone — a
crisp outline in the theme's icon colour over a soft fill of the same
colour — so the row reads as one designed set while keeping the
single-colour look the themes rely on. Nothing is shipped as an image
file (see CLAUDE.md); every size is drawn fresh, sharp on HiDPI.

`paint_icon(name, color)` returns a QIcon or None for names drawn
elsewhere (icons.py falls back to its glyph table).
"""
from __future__ import annotations

import math
from typing import Callable, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)

_SIZES = (16, 20, 24, 32, 48, 64)
_STROKE = 1.7
_FILL_ALPHA = 0.26


class _Pen:
    """Small drawing kit handed to each icon function (24-unit grid)."""

    def __init__(self, p: QPainter, color: QColor) -> None:
        self.p = p
        self.c = QColor(color)
        self.soft = QColor(color)
        self.soft.setAlphaF(_FILL_ALPHA)
        self.faint = QColor(color)
        self.faint.setAlphaF(0.12)

    def _line_pen(self, w: float = _STROKE, dash: bool = False) -> QPen:
        pen = QPen(self.c, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        if dash:
            pen.setDashPattern([1.6, 1.6])
        return pen

    def shape(self, path: QPainterPath, fill: Optional[str] = "soft",
              w: float = _STROKE, dash: bool = False,
              stroke: bool = True) -> None:
        brush = {"soft": self.soft, "faint": self.faint,
                 "solid": self.c}.get(fill or "", None)
        self.p.setBrush(brush if brush is not None else Qt.NoBrush)
        self.p.setPen(self._line_pen(w, dash) if stroke else Qt.NoPen)
        self.p.drawPath(path)

    def line(self, *pts: tuple[float, float], w: float = _STROKE,
             dash: bool = False) -> None:
        path = QPainterPath(QPointF(*pts[0]))
        for pt in pts[1:]:
            path.lineTo(QPointF(*pt))
        self.shape(path, None, w, dash)

    def dot(self, x: float, y: float, r: float = 1.2) -> None:
        path = QPainterPath()
        path.addEllipse(QPointF(x, y), r, r)
        self.shape(path, "solid", stroke=False)


def _rrect(x, y, w, h, r=2.0) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


def _poly(*pts, close=True) -> QPainterPath:
    path = QPainterPath(QPointF(*pts[0]))
    for pt in pts[1:]:
        path.lineTo(QPointF(*pt))
    if close:
        path.closeSubpath()
    return path


def _page(k: _Pen, x=5, y=3, w=14, h=18, fold=4.5, fill="faint") -> None:
    """A document sheet with a folded top-right corner."""
    k.shape(_poly((x, y), (x + w - fold, y), (x + w, y + fold),
                  (x + w, y + h), (x, y + h)), fill)
    k.line((x + w - fold, y), (x + w - fold, y + fold), (x + w, y + fold))


def _text_lines(k: _Pen, x0, x1, ys, w=1.4) -> None:
    for i, y in enumerate(ys):
        k.line((x0, y), (x1 - (2.5 if i == len(ys) - 1 else 0), y), w=w)


# ----------------------------------------------------------- the icons

def _open(k):
    k.shape(_poly((2.5, 6), (9, 6), (11, 8), (19.5, 8), (19.5, 10.5),
                  (2.5, 10.5)), "faint")
    k.shape(_poly((2.5, 19), (5.5, 10.5), (22, 10.5), (19, 19)), "soft")


def _save(k):
    k.shape(_poly((4, 3.5), (17, 3.5), (20.5, 7), (20.5, 20.5),
                  (4, 20.5)), "faint")
    k.shape(_rrect(7.5, 3.5, 8, 5, 0.8), "soft")
    k.shape(_rrect(7, 13, 10, 7.5, 1.2), "soft")
    k.line((9.5, 16), (14.5, 16), w=1.3)


def _arc_arrow(k, mirror: bool):
    s = -1 if mirror else 1
    cx = 12

    def X(x):
        return cx + s * (x - cx)
    path = QPainterPath(QPointF(X(6), 9))
    path.cubicTo(QPointF(X(10), 5.5), QPointF(X(19.5), 6.5),
                 QPointF(X(19.5), 13))
    path.cubicTo(QPointF(X(19.5), 17.5), QPointF(X(15.5), 19.5),
                 QPointF(X(11.5), 19.5))
    k.shape(path, None, w=2.0)
    k.shape(_poly((X(3.5), 4.5), (X(4), 11.5), (X(10.5), 10)), "solid",
            w=1.2)


def _undo(k):
    _arc_arrow(k, False)


def _redo(k):
    _arc_arrow(k, True)


def _image(k):
    k.shape(_rrect(3, 4.5, 18, 15, 2.2), "faint")
    k.shape(_poly((3.5, 18.5), (9, 11.5), (13, 15.5), (15.5, 13),
                  (20.5, 18.5)), "soft", w=1.4)
    path = QPainterPath()
    path.addEllipse(QPointF(15.5, 9), 1.9, 1.9)
    k.shape(path, "soft")
    k.line((19, 1.5), (19, 6.5), w=1.6)
    k.line((16.5, 4), (21.5, 4), w=1.6)


def _thumbs(k):
    k.shape(_rrect(2.5, 3.5, 7, 17, 1.5), "soft")
    for y in (5.5, 10.5, 15.5):
        k.shape(_rrect(4, y, 4, 3.5, 0.6), "solid", stroke=False)
    _page(k, 12, 3.5, 9.5, 17, 3, "faint")
    _text_lines(k, 14, 19.5, (10, 13, 16), w=1.1)


def _ai(k):
    # A chat bubble with a small spark — "ask the assistant".
    path = QPainterPath()
    path.addRoundedRect(QRectF(2.5, 4, 15, 11.5), 3.5, 3.5)
    path.moveTo(6, 15.5)
    path.lineTo(5, 20)
    path.lineTo(10, 15.5)
    k.shape(path.simplified(), "faint")
    for x in (6.5, 10, 13.5):
        k.dot(x, 9.8, 1.15)
    star = QPainterPath(QPointF(19, 2))
    for ang in range(1, 8):
        r = 4.3 if ang % 2 == 0 else 1.4
        a = math.radians(-90 + ang * 45)
        star.lineTo(QPointF(19 + r * math.cos(a), 6.3 + r * math.sin(a)))
    star.closeSubpath()
    # (start point at top tip)
    k.shape(star, "solid", w=0.8)


def _hand(k):
    path = QPainterPath(QPointF(7, 21))
    path.cubicTo(QPointF(5, 18), QPointF(3, 15.5), QPointF(3.3, 13))
    path.cubicTo(QPointF(3.6, 11.4), QPointF(5.4, 11.6), QPointF(6.5, 13))
    path.lineTo(7, 13.8)
    path.lineTo(7, 5.5)
    path.cubicTo(QPointF(7, 3.6), QPointF(9.6, 3.6), QPointF(9.6, 5.5))
    path.lineTo(9.6, 10.5)
    path.lineTo(9.6, 3.8)
    path.cubicTo(QPointF(9.6, 1.9), QPointF(12.3, 1.9), QPointF(12.3, 3.8))
    path.lineTo(12.3, 10.5)
    path.lineTo(12.3, 4.6)
    path.cubicTo(QPointF(12.3, 2.7), QPointF(15, 2.7), QPointF(15, 4.6))
    path.lineTo(15, 11)
    path.lineTo(15, 7)
    path.cubicTo(QPointF(15, 5.2), QPointF(17.6, 5.2), QPointF(17.6, 7))
    path.lineTo(17.6, 15)
    path.cubicTo(QPointF(17.6, 18.5), QPointF(16, 20), QPointF(15.5, 21))
    path.closeSubpath()
    k.shape(path, "soft", w=1.5)


def _cursor(k, x=6, y=3, sc=1.0, fill="soft"):
    def P(a, b):
        return (x + a * sc, y + b * sc)
    k.shape(_poly(P(0, 0), P(0, 15.5), P(4, 11.8), P(6.6, 17.6),
                  P(9.2, 16.4), P(6.7, 10.8), P(11.8, 10.6)), fill, w=1.5)


def _select(k):
    k.shape(_rrect(13, 12.5, 8.5, 8.5, 1.2), "faint", w=1.3, dash=True)
    _cursor(k, 4, 2.5)


def _select_text(k):
    k.shape(_rrect(3, 7.5, 13.5, 9, 1.0), "soft", stroke=False)
    _text_lines(k, 4.5, 15, (10.5, 13.5), w=1.3)
    k.line((19, 4), (19, 20), w=1.8)
    k.line((16.8, 3.5), (21.2, 3.5), w=1.6)
    k.line((16.8, 20.5), (21.2, 20.5), w=1.6)


def _snapshot(k):
    for (x, y, dx, dy) in ((3, 3, 1, 1), (21, 3, -1, 1), (3, 21, 1, -1),
                           (21, 21, -1, -1)):
        k.line((x, y + dy * 5), (x, y), (x + dx * 5, y), w=1.9)
    k.shape(_rrect(7, 8.5, 10, 8, 1.6), "soft", w=1.4)
    path = QPainterPath()
    path.addEllipse(QPointF(12, 12.5), 2.2, 2.2)
    k.shape(path, None, w=1.3)
    k.shape(_rrect(9, 7, 3.2, 1.6, 0.5), "solid", stroke=False)


def _pen(k):
    body = _poly((15.5, 3.5), (20.5, 8.5), (9, 20), (3.5, 20.5), (4, 15))
    k.shape(body, "soft", w=1.5)
    k.line((13, 6), (18, 11), w=1.4)
    k.shape(_poly((4, 15), (9, 20), (3.5, 20.5)), "solid", w=1.0)


def _marker(k, tip_fill="soft"):
    k.shape(_poly((15, 2.5), (21.5, 9), (13, 17.5), (6.5, 11)), "soft",
            w=1.5)
    k.shape(_poly((6.5, 11), (13, 17.5), (10, 19.5), (4.5, 14)), "faint",
            w=1.5)
    k.shape(_poly((4.5, 14), (10, 19.5), (6.5, 21.5), (2.5, 21.5),
                  (2.5, 17)), "solid", w=1.0)


def _highlight(k):
    k.shape(_rrect(10, 18.6, 12.5, 3.6, 0.8), "soft", stroke=False)
    _marker(k)


def _underline(k):
    path = QPainterPath(QPointF(6.5, 3))
    path.lineTo(6.5, 11)
    path.cubicTo(QPointF(6.5, 17), QPointF(17.5, 17), QPointF(17.5, 11))
    path.lineTo(17.5, 3)
    k.shape(path, None, w=2.0)
    k.line((4, 20.5), (20, 20.5), w=2.2)


def _strikeout(k):
    path = QPainterPath(QPointF(17, 6))
    path.cubicTo(QPointF(15.5, 3), QPointF(7, 3), QPointF(7, 7.5))
    path.cubicTo(QPointF(7, 10.5), QPointF(10, 11.2), QPointF(12, 11.7))
    path.moveTo(14.8, 13.5)
    path.cubicTo(QPointF(17.5, 15), QPointF(17.5, 20.5), QPointF(12, 20.5))
    path.cubicTo(QPointF(9, 20.5), QPointF(7.2, 19.5), QPointF(6.5, 17.5))
    k.shape(path, None, w=1.9)
    k.line((3, 12.5), (21, 12.5), w=2.0)


def _text(k):
    k.shape(_rrect(3, 3, 18, 18, 3), "faint", w=1.4)
    k.line((7.5, 7.5), (16.5, 7.5), w=2.2)
    k.line((12, 7.5), (12, 17), w=2.2)
    k.line((10, 17), (14, 17), w=1.6)


def _edit_text(k):
    _page(k, 3.5, 2.5, 13, 18, 4)
    _text_lines(k, 6, 13.5, (10, 13, 16), w=1.2)
    k.shape(_poly((18.5, 9), (21.5, 12), (14, 19.5), (10.5, 20.5),
                  (11.5, 17)), "soft", w=1.4)


def _move_text(k):
    k.shape(_rrect(7.5, 8, 9, 8, 1.2), "soft", w=1.3)
    _text_lines(k, 9.3, 15, (10.8, 13.4), w=1.1)
    for (x, y, dx, dy) in ((12, 2, 0, 1), (12, 22, 0, -1), (2, 12, 1, 0),
                           (22, 12, -1, 0)):
        k.shape(_poly((x, y), (x + dx * 3 + dy * 2.6, y + dy * 3 + dx * 2.6),
                      (x + dx * 3 - dy * 2.6, y + dy * 3 - dx * 2.6)),
                "solid", w=1.0)


def _line(k):
    k.line((5, 19), (19, 5), w=2.0)
    for (x, y) in ((5, 19), (19, 5)):
        path = QPainterPath()
        path.addEllipse(QPointF(x, y), 2.4, 2.4)
        k.shape(path, "soft", w=1.4)


def _arrow(k):
    k.line((4.5, 19.5), (17, 7), w=2.0)
    k.shape(_poly((20.5, 3.5), (19.3, 12), (12, 4.7)), "solid", w=1.2)


def _rect(k):
    k.shape(_rrect(3.5, 5.5, 17, 13, 1.5), "soft", w=1.8)


def _ellipse(k):
    path = QPainterPath()
    path.addEllipse(QRectF(2.5, 5, 19, 14))
    k.shape(path, "soft", w=1.8)


def _note(k):
    k.shape(_poly((4, 3.5), (20, 3.5), (20, 15), (14.5, 20.5), (4, 20.5)),
            "soft", w=1.5)
    k.shape(_poly((14.5, 20.5), (14.5, 15), (20, 15)), "solid", w=1.2)
    _text_lines(k, 7, 16.5, (8, 11.5), w=1.3)


def _signature(k):
    path = QPainterPath(QPointF(3, 15))
    path.cubicTo(QPointF(5, 5), QPointF(9, 3), QPointF(8.5, 9))
    path.cubicTo(QPointF(8, 14), QPointF(5, 18), QPointF(7.5, 16.5))
    path.cubicTo(QPointF(10, 15), QPointF(11, 10), QPointF(12.5, 12))
    path.cubicTo(QPointF(13.5, 13.5), QPointF(14.5, 14.5), QPointF(16, 12))
    path.cubicTo(QPointF(17, 10.5), QPointF(18.5, 11), QPointF(21, 12))
    k.shape(path, None, w=1.7)
    k.line((3, 20), (21, 20), w=1.3, dash=True)


def _erase(k):
    body = _poly((13.5, 3.5), (21, 11), (12, 20), (7, 20), (3, 16))
    k.shape(body, "faint", w=1.5)
    k.shape(_poly((3, 16), (8.3, 10.7), (15.8, 18.2), (12, 20), (7, 20)),
            "soft", w=1.5)
    k.line((12, 20.5), (21, 20.5), w=1.4)


def _magnifier(k, sign: str):
    path = QPainterPath()
    path.addEllipse(QPointF(10, 10), 6.8, 6.8)
    k.shape(path, "faint", w=1.8)
    k.line((15, 15), (21, 21), w=2.8)
    k.line((7, 10), (13, 10), w=1.9)
    if sign == "+":
        k.line((10, 7), (10, 13), w=1.9)


def _zoom_in(k):
    _magnifier(k, "+")


def _zoom_out(k):
    _magnifier(k, "-")


def _fit_width(k):
    _page(k, 7, 2.5, 10, 19, 3)
    _text_lines(k, 9, 15, (9, 12, 15), w=1.1)
    for x, d in ((2.5, 1), (21.5, -1)):
        k.line((x + d * 3.3, 12), (x, 12), w=1.5)
        k.shape(_poly((x, 12), (x + d * 2.6, 9.6), (x + d * 2.6, 14.4)),
                "solid", w=0.9)


def _night(k):
    path = QPainterPath()
    path.addEllipse(QPointF(11, 12.5), 8.5, 8.5)
    bite = QPainterPath()
    bite.addEllipse(QPointF(15.5, 8.5), 7, 7)
    k.shape(path.subtracted(bite), "soft", w=1.6)
    for (x, y, r) in ((18.5, 4, 1.3), (21, 9, 0.9), (15, 2.5, 0.8)):
        k.dot(x, y, r)


def _read_aloud(k):
    k.shape(_poly((3, 9.5), (7, 9.5), (12, 5), (12, 19), (7, 14.5),
                  (3, 14.5)), "soft", w=1.5)
    for r in (3.5, 7):
        path = QPainterPath()
        path.arcMoveTo(QRectF(12 - r, 12 - r, 2 * r, 2 * r), -45)
        path.arcTo(QRectF(12 - r, 12 - r, 2 * r, 2 * r), -45, 90)
        k.shape(path, None, w=1.6)


def _compare(k):
    _page(k, 2.5, 3, 9, 15, 3, "soft")
    _page(k, 12.5, 6, 9, 15, 3, "faint")
    _text_lines(k, 4.3, 9.8, (9, 12), w=1.1)
    _text_lines(k, 14.3, 19.8, (12, 15, 18), w=1.1)
    k.line((10.5, 20.5), (14, 20.5), w=1.3, dash=True)


def _ask_area(k):
    for (x, y, dx, dy) in ((2.5, 6, 1, 1), (17, 6, -1, 1), (2.5, 20.5, 1, -1),
                           (17, 20.5, -1, -1)):
        k.line((x, y + dy * 3.5), (x, y), (x + dx * 3.5, y), w=1.7)
    k.shape(_rrect(5.5, 9, 8.5, 8.5, 1), "soft", stroke=False)
    star = QPainterPath()
    for i in range(8):
        r = 4.5 if i % 2 == 0 else 1.5
        a = math.radians(-90 + i * 45)
        pt = QPointF(18.5 + r * math.cos(a), 5.5 + r * math.sin(a))
        star.moveTo(pt) if i == 0 else star.lineTo(pt)
    star.closeSubpath()
    k.shape(star, "solid", w=0.8)


def _stamp(k):
    k.shape(_rrect(9.5, 2.5, 5, 7, 2.2), "soft", w=1.5)
    k.shape(_poly((7, 9.5), (17, 9.5), (19, 13.5), (5, 13.5)), "soft",
            w=1.5)
    k.shape(_rrect(4, 13.5, 16, 3, 0.8), "solid", w=1.2)
    k.line((3, 20.5), (21, 20.5), w=1.5, dash=True)


_PAINTERS: dict[str, Callable[[_Pen], None]] = {
    "night": _night, "read_aloud": _read_aloud, "compare": _compare,
    "ask_area": _ask_area, "stamp": _stamp,
    "open": _open, "save": _save, "undo": _undo, "redo": _redo,
    "image": _image, "thumbs": _thumbs, "ai": _ai,
    "hand": _hand, "select": _select, "select_text": _select_text,
    "snapshot": _snapshot, "pen": _pen, "highlight": _highlight,
    "underline": _underline, "strikeout": _strikeout, "text": _text,
    "edit_text": _edit_text, "move_text": _move_text, "line": _line,
    "arrow": _arrow, "rect": _rect, "ellipse": _ellipse, "note": _note,
    "signature": _signature, "erase": _erase, "zoom_in": _zoom_in,
    "zoom_out": _zoom_out, "fit_width": _fit_width,
}

NAMES = frozenset(_PAINTERS)


def paint_pixmap(name: str, color, size: int,
                 disabled: bool = False) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    c = QColor(color)
    if disabled:
        c.setAlphaF(0.38)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24.0, size / 24.0)
    _PAINTERS[name](_Pen(p, c))
    p.end()
    return pm


def paint_icon(name: str, color) -> Optional[QIcon]:
    if name not in _PAINTERS:
        return None
    ic = QIcon()
    for sz in _SIZES:
        ic.addPixmap(paint_pixmap(name, color, sz), QIcon.Normal)
        ic.addPixmap(paint_pixmap(name, color, sz, True), QIcon.Disabled)
    return ic
