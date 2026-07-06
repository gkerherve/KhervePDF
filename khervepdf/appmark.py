# Copyright (C) 2026 Gwilherm Kerherve
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
"""The KhervePDF application mark (window / taskbar icon).

Draws a "KPDF" wordmark above a page-with-magnifier symbol on a rounded
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

# Each glyph is built in a unit box (x, y in 0..1, y downward); caps fill
# the box height. "KPDF" is all capitals (PDF is an initialism).


def _glyph_K():
    w = 0.82
    p = QPainterPath()
    p.moveTo(0.0, 0.0); p.lineTo(0.0, 1.0)
    p.moveTo(0.0, 0.52); p.lineTo(w, 0.0)
    p.moveTo(0.0, 0.52); p.lineTo(w, 1.0)
    return p, w


def _glyph_P():
    w = 0.70
    p = QPainterPath()
    p.moveTo(0.0, 0.0); p.lineTo(0.0, 1.0)
    p.moveTo(0.0, 0.0)
    p.cubicTo(w * 1.25, 0.02, w * 1.25, 0.52, 0.0, 0.54)
    return p, w


def _glyph_D():
    w = 0.72
    p = QPainterPath()
    p.moveTo(0.0, 0.0); p.lineTo(0.0, 1.0)
    p.moveTo(0.0, 0.0)
    p.cubicTo(w * 1.35, 0.05, w * 1.35, 0.95, 0.0, 1.0)
    return p, w


def _glyph_F():
    w = 0.62
    p = QPainterPath()
    p.moveTo(0.0, 0.0); p.lineTo(0.0, 1.0)
    p.moveTo(0.0, 0.0); p.lineTo(w, 0.0)
    p.moveTo(0.0, 0.47); p.lineTo(w * 0.82, 0.47)
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
    items = [_glyph_K(), _glyph_P(), _glyph_D(), _glyph_F()]
    gap = 0.10
    total = sum(w for _p, w in items) + gap * (len(items) - 1)
    pad_x, pad_y = rect.width() * 0.11, rect.height() * 0.22
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
