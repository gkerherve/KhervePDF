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

# The page-with-magnifier schematic is a stroked vector path (font-
# independent); the "Kpdf" wordmark itself uses a normal system font.


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


def _wordmark(p, rect, text):
    """Draw *text* centred in *rect* with a normal bold system font,
    scaled up to the largest size that still fits the tile width."""
    from PySide6.QtGui import QFont, QFontMetricsF
    avail = rect.width() * 0.82
    font = QFont("Segoe UI")
    font.setBold(True)
    size = 1.0
    while size < rect.height():
        font.setPointSizeF(size + 0.5)
        fm = QFontMetricsF(font)
        if fm.horizontalAdvance(text) > avail or fm.height() > rect.height():
            break
        size += 0.5
    font.setPointSizeF(size)
    p.setFont(font)
    p.setPen(QColor(_INK))
    p.drawText(rect, Qt.AlignCenter, text)


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
    """Render the Kpdf mark at *size* px."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)
    rect = _tile(p, s)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    _wordmark(p, QRectF(x, y + h * 0.05, w, h * 0.44), "Kpdf")
    bw, bh = w * 0.46, h * 0.38
    _page_magnifier(p, QRectF(x + (w - bw) / 2.0, y + h * 0.54, bw, bh))
    p.end()
    return pm
