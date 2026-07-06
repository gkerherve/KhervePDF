# Copyright (C) 2026 Gwilherm Kerherve
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
"""The KhervePDF application mark (window / taskbar icon).

Draws a "Kpdf" wordmark above a page-with-magnifier symbol on a rounded
red tile, in the shared Kherve-family style (cf. KherveBook / KhervePaint
/ KherveSheet): the letters are stroked vector paths — not text — so the
mark renders identically everywhere and stays crisp from 16 px to 256 px,
without depending on a system font. Uses PySide6 to match the app.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QPixmap,
                           QTransform)

#: KhervePDF red tile (the Eraser accent) with white ink.
_FILL = "#c62828"
_EDGE = "#a81f1f"
_INK = "#ffffff"

# The word is "Kpdf" (capital K, lowercase pdf), so glyphs share an
# em-box with a common baseline: p has a descender, d and f ascenders.
# Every glyph is drawn in a unit box (x, y in 0..1, y downward) using
# these lines so they align.
_CAP = 0.06     # cap / ascender top
_BASE = 0.80    # baseline
_DESC = 0.98    # descender bottom
_XT = 0.33      # x-height top


def _glyph_K():
    w = 0.82
    mid = (_CAP + _BASE) / 2 - 0.02
    p = QPainterPath()
    p.moveTo(0.0, _CAP); p.lineTo(0.0, _BASE)             # stem
    p.moveTo(0.0, mid); p.lineTo(w, _CAP)                 # upper arm
    p.moveTo(0.0, mid); p.lineTo(w, _BASE)                # lower arm
    return p, w


def _glyph_p():
    w = 0.66
    p = QPainterPath()
    p.moveTo(0.0, _XT); p.lineTo(0.0, _DESC)              # stem + descender
    p.moveTo(0.0, _XT)                                    # bowl
    p.cubicTo(w * 1.30, _XT, w * 1.30, _BASE, 0.0, _BASE)
    return p, w


def _glyph_d():
    w = 0.66
    p = QPainterPath()
    p.moveTo(w, _CAP); p.lineTo(w, _BASE)                 # ascender stem
    p.moveTo(w, _XT)                                      # bowl
    p.cubicTo(-w * 0.30, _XT, -w * 0.30, _BASE, w, _BASE)
    return p, w


def _glyph_f():
    w = 0.52
    sx = w * 0.46
    p = QPainterPath()
    p.moveTo(w * 0.92, _CAP)                              # top hook
    p.cubicTo(w * 0.48, _CAP - 0.06, sx, _CAP - 0.02, sx, _CAP + 0.14)
    p.lineTo(sx, _BASE)                                   # stem
    p.moveTo(0.0, _XT); p.lineTo(w * 0.90, _XT)           # crossbar
    return p, w


def _stroke(p, path, color, box, weight):
    t = QTransform()
    t.translate(box.x(), box.y())
    t.scale(box.width(), box.height())
    pen = QPen(QColor(color))
    pen.setWidthF(weight * box.height())
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(t.map(path))


def _tile(p, s):
    m = s * 0.06
    radius = s * 0.22
    rect = QRectF(m, m, s - 2 * m, s - 2 * m)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(_FILL))
    p.drawRoundedRect(rect, radius, radius)
    pen = QPen(QColor(_EDGE))
    pen.setWidthF(max(1.0, s * 0.02))
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect, radius, radius)
    return rect


def _wordmark(p, rect):
    items = [_glyph_K(), _glyph_p(), _glyph_d(), _glyph_f()]
    gap = 0.10
    total = sum(w for _p, w in items) + gap * (len(items) - 1)
    pad_x, pad_y = rect.width() * 0.10, rect.height() * 0.14
    ch = min(rect.height() - 2 * pad_y, (rect.width() - 2 * pad_x) / total)
    x = rect.x() + (rect.width() - total * ch) / 2.0
    top = rect.y() + (rect.height() - ch) / 2.0
    for path, gw in items:
        _stroke(p, path, _INK, QRectF(x, top, gw * ch, ch), 0.15)
        x += (gw + gap) * ch


def _page_magnifier(p, box):
    """A dog-eared page with lines of text, and a magnifier over it."""
    page = QPainterPath()
    page.moveTo(0.10, 0.05); page.lineTo(0.60, 0.05); page.lineTo(0.78, 0.23)
    page.lineTo(0.78, 0.90); page.lineTo(0.10, 0.90); page.lineTo(0.10, 0.05)
    page.moveTo(0.60, 0.05); page.lineTo(0.60, 0.23); page.lineTo(0.78, 0.23)
    for ly, lx2 in ((0.38, 0.58), (0.50, 0.66), (0.62, 0.48)):
        page.moveTo(0.20, ly); page.lineTo(lx2, ly)
    _stroke(p, page, _INK, box, 0.045)
    lens = QPainterPath()
    lens.addEllipse(QRectF(0.52, 0.52, 0.34, 0.34))
    lens.moveTo(0.83, 0.83); lens.lineTo(1.00, 1.00)          # handle
    _stroke(p, lens, _INK, box, 0.05)


def paint(size: int) -> QPixmap:
    """Render the KPDF mark at *size* px."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)
    rect = _tile(p, s)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    _wordmark(p, QRectF(x, y + h * 0.05, w, h * 0.44))
    bw, bh = w * 0.46, h * 0.38
    _page_magnifier(p, QRectF(x + (w - bw) / 2.0, y + h * 0.54, bw, bh))
    p.end()
    return pm
