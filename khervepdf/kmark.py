# Copyright (C) 2026 Gwilherm Kerherve
# Licensed under the GNU General Public License v3.0 (see LICENSE).
"""Kherve-family application marks, in the kPlot style.

A rounded gradient tile with a soft top sheen, a one-line wordmark (the
small "k" in an accent colour, the rest in white, with a shadow) and a
shaded illustration under it. Sizes up to 32 px drop the wordmark so the
taskbar copy stays readable. ``paint(size, app)`` returns a QPixmap; the
same file is shared by KhervePDF, KherveSheet, KherveSlide, KherveTeX,
KherveNote and KherveStats.
"""

from __future__ import annotations

import math

try:
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import (QColor, QFont, QFontMetricsF,
                               QLinearGradient, QPainter, QPainterPath, QPen,
                               QPixmap, QRadialGradient)
except ImportError:  # PyQt5 apps
    from PyQt5.QtCore import QPointF, QRectF, Qt
    from PyQt5.QtGui import (QColor, QFont, QFontMetricsF, QLinearGradient,
                             QPainter, QPainterPath, QPen, QPixmap,
                             QRadialGradient)

WHITE = QColor("#ffffff")
GOLD = QColor("#ffc94a")

# app -> (wordmark after the k, tile top, tile bottom, k colour)
APPS = {
    "pdf": ("PDF", "#ef4b4b", "#8e1016", GOLD),
    "sheet": ("Sheet", "#35b866", "#11592c", GOLD),
    "slide": ("Slide", "#ffa257", "#c2470a", QColor("#2a2f6e")),
    "tex": ("TeX", "#4a8ef0", "#163b8c", GOLD),
    "note": ("Note", "#4f7cf0", "#22318f", GOLD),
    "stats": ("Stats", "#4fbe9f", "#155f4c", GOLD),
}


def _pen(c, w, cap=Qt.RoundCap):
    pen = QPen(QColor(c), w)
    pen.setCapStyle(cap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _shadow(p, path, s, alpha=80):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, alpha))
    p.drawPath(path.translated(0, s * 0.012))


def _card(p, r, s, radius=0.03, fill=None):
    """A white rounded card with a drop shadow; returns its path."""
    path = QPainterPath()
    path.addRoundedRect(r, s * radius, s * radius)
    _shadow(p, path, s)
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0, QColor(fill or "#ffffff"))
    g.setColorAt(1, QColor("#e9edf2"))
    p.setBrush(g)
    p.drawPath(path)
    return path


def _wordmark(p, tile, rest, kcol, s):
    font = QFont("Helvetica Neue")
    font.setStyleHint(QFont.SansSerif)
    font.setWeight(QFont.Black)
    font.setPixelSize(int(tile.height() * 0.26))
    fm = QFontMetricsF(font)
    total = fm.horizontalAdvance("k" + rest)
    if total > tile.width() * 0.80:
        font.setPixelSize(int(font.pixelSize() * tile.width() * 0.80 / total))
        fm = QFontMetricsF(font)
        total = fm.horizontalAdvance("k" + rest)
    x = tile.center().x() - total / 2.0
    base = tile.top() + tile.height() * 0.15 + fm.capHeight()
    for t, col in (("k", kcol), (rest, WHITE)):
        path = QPainterPath()
        path.addText(x, base, font, t)
        _shadow(p, path, s, 90)
        p.setBrush(col)
        p.drawPath(path)
        x += fm.horizontalAdvance(t)


# ----- illustrations: each draws inside box (the lower part of the tile) --


def _pdf(p, b, s):
    page = QRectF(b.left() + b.width() * 0.16, b.top(), b.width() * 0.56,
                  b.height())
    fold = page.width() * 0.26
    path = QPainterPath()
    path.moveTo(page.left(), page.top())
    path.lineTo(page.right() - fold, page.top())
    path.lineTo(page.right(), page.top() + fold)
    path.lineTo(page.right(), page.bottom())
    path.lineTo(page.left(), page.bottom())
    path.closeSubpath()
    _shadow(p, path, s)
    p.setBrush(WHITE)
    p.drawPath(path)
    ear = QPainterPath()
    ear.moveTo(page.right() - fold, page.top())
    ear.lineTo(page.right() - fold, page.top() + fold)
    ear.lineTo(page.right(), page.top() + fold)
    ear.closeSubpath()
    p.setBrush(QColor("#c9d0d8"))
    p.drawPath(ear)
    # red PDF band
    band = QRectF(page.left() - page.width() * 0.1, page.top()
                  + page.height() * 0.30, page.width() * 0.62,
                  page.height() * 0.2)
    p.setBrush(QColor("#d32f2f"))
    p.drawRoundedRect(band, s * 0.01, s * 0.01)
    f = QFont("Helvetica Neue")
    f.setWeight(QFont.Black)
    f.setPixelSize(int(band.height() * 0.72))
    p.setPen(WHITE)
    p.setFont(f)
    p.drawText(band, Qt.AlignCenter, "PDF")
    p.setPen(_pen("#aab4bf", s * 0.016))
    for i, frac in enumerate((0.62, 0.72, 0.82)):
        y = page.top() + page.height() * frac
        p.drawLine(QPointF(page.left() + page.width() * 0.14, y),
                   QPointF(page.left() + page.width() * (0.86 if i < 2 else
                                                         0.55), y))
    # magnifier
    c = QPointF(page.right() - page.width() * 0.02, page.bottom()
                - page.height() * 0.22)
    r = b.height() * 0.2
    p.setPen(_pen("#3a3f47", s * 0.04))
    p.drawLine(QPointF(c.x() + r * 0.7, c.y() + r * 0.7),
               QPointF(c.x() + r * 1.55, c.y() + r * 1.55))
    lens = QRadialGradient(c, r)
    lens.setColorAt(0, QColor(220, 240, 255, 200))
    lens.setColorAt(1, QColor(150, 200, 240, 160))
    p.setBrush(lens)
    p.setPen(_pen("#ffffff", s * 0.022))
    p.drawEllipse(c, r, r)


def _sheet(p, b, s):
    card = QRectF(b.left() + b.width() * 0.08, b.top(), b.width() * 0.84,
                  b.height())
    _card(p, card, s)
    cols, rows = 4, 5
    cw, rh = card.width() / cols, card.height() / rows
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#1f8a4c"))
    p.drawRoundedRect(QRectF(card.left(), card.top(), card.width(), rh),
                      s * 0.03, s * 0.03)
    p.drawRect(QRectF(card.left(), card.top() + rh / 2, card.width(),
                      rh / 2))
    f = QFont("Helvetica Neue")
    f.setBold(True)
    f.setPixelSize(int(rh * 0.55))
    p.setFont(f)
    p.setPen(WHITE)
    for i, ch in enumerate("ABCD"):
        p.drawText(QRectF(card.left() + i * cw, card.top(), cw, rh),
                   Qt.AlignCenter, ch)
    p.setPen(_pen("#c9d3cc", s * 0.004, Qt.FlatCap))
    for i in range(1, cols):
        x = card.left() + i * cw
        p.drawLine(QPointF(x, card.top() + rh), QPointF(x, card.bottom()))
    for j in range(2, rows):
        y = card.top() + j * rh
        p.drawLine(QPointF(card.left(), y), QPointF(card.right(), y))
    # numbers as grey dashes, one selected cell
    p.setPen(_pen("#9aa6a0", s * 0.012))
    for i in range(cols):
        for j in range(1, rows):
            y = card.top() + (j + 0.5) * rh
            p.drawLine(QPointF(card.left() + i * cw + cw * 0.25, y),
                       QPointF(card.left() + i * cw + cw * 0.75, y))
    sel = QRectF(card.left() + cw, card.top() + 2 * rh, cw, rh)
    p.setPen(_pen("#1f8a4c", s * 0.012, Qt.SquareCap))
    p.setBrush(QColor(53, 184, 102, 60))
    p.drawRect(sel)
    # chart badge
    badge = QRectF(card.right() - cw * 1.55, card.bottom() - rh * 2.4,
                   cw * 1.9, rh * 2.9)
    _card(p, badge, s, 0.02)
    p.setPen(Qt.NoPen)
    for i, h in enumerate((0.35, 0.6, 0.85)):
        g = QLinearGradient(0, badge.bottom(), 0, badge.top())
        g.setColorAt(0, QColor("#1f8a4c"))
        g.setColorAt(1, QColor("#5fd68f"))
        p.setBrush(g)
        bw = badge.width() * 0.18
        bx = badge.left() + badge.width() * (0.16 + 0.26 * i)
        bh = badge.height() * 0.72 * h
        p.drawRect(QRectF(bx, badge.bottom() - badge.height() * 0.12 - bh,
                          bw, bh))


def _slide(p, b, s):
    scr = QRectF(b.left() + b.width() * 0.06, b.top(), b.width() * 0.88,
                 b.height() * 0.80)
    # stand
    p.setPen(_pen("#5b2a08", s * 0.02))
    p.drawLine(QPointF(scr.center().x(), scr.bottom()),
               QPointF(scr.center().x(), b.bottom()))
    p.drawLine(QPointF(scr.center().x(), scr.bottom() + b.height() * 0.08),
               QPointF(scr.center().x() - b.width() * 0.14, b.bottom()))
    p.drawLine(QPointF(scr.center().x(), scr.bottom() + b.height() * 0.08),
               QPointF(scr.center().x() + b.width() * 0.14, b.bottom()))
    p.setPen(Qt.NoPen)
    _card(p, scr, s, 0.02)
    # title bar + bullet lines
    p.setBrush(QColor("#e8692a"))
    p.drawRoundedRect(QRectF(scr.left() + scr.width() * 0.07, scr.top()
                             + scr.height() * 0.12, scr.width() * 0.5,
                             scr.height() * 0.11), s * 0.008, s * 0.008)
    for i in range(3):
        y = scr.top() + scr.height() * (0.42 + 0.17 * i)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#e8692a"))
        p.drawEllipse(QPointF(scr.left() + scr.width() * 0.09, y),
                      s * 0.009, s * 0.009)
        p.setPen(_pen("#a5adb8", s * 0.014))
        p.drawLine(QPointF(scr.left() + scr.width() * 0.14, y),
                   QPointF(scr.left() + scr.width() * (0.48 - 0.06 * i), y))
    # pie chart
    c = QPointF(scr.left() + scr.width() * 0.76, scr.top()
                + scr.height() * 0.56)
    r = scr.height() * 0.30
    rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
    p.setPen(_pen("#ffffff", s * 0.006))
    start = 90 * 16
    for frac, col in ((0.45, "#e8692a"), (0.30, "#2a2f6e"),
                      (0.25, "#ffc94a")):
        p.setBrush(QColor(col))
        span = int(-frac * 360 * 16)
        p.drawPie(rect, start, span)
        start += span


def _tex(p, b, s):
    page = QRectF(b.left() + b.width() * 0.12, b.top(), b.width() * 0.76,
                  b.height())
    _card(p, page, s, 0.02)
    # serif equation
    f = QFont("Times New Roman")
    f.setStyleHint(QFont.Serif)
    f.setItalic(True)
    f.setPixelSize(int(page.height() * 0.30))
    p.setFont(f)
    p.setPen(QColor("#1d2a44"))
    eq = QRectF(page.left(), page.top() + page.height() * 0.08,
                page.width(), page.height() * 0.42)
    p.drawText(eq, Qt.AlignCenter, "∫ eˣ dx")
    # rule and text lines
    p.setPen(_pen("#2f6fe0", s * 0.008))
    p.drawLine(QPointF(page.left() + page.width() * 0.12, page.top()
                       + page.height() * 0.54),
               QPointF(page.right() - page.width() * 0.12, page.top()
                       + page.height() * 0.54))
    p.setPen(_pen("#a9b2bf", s * 0.014))
    for i, w in enumerate((0.76, 0.70, 0.52)):
        y = page.top() + page.height() * (0.68 + 0.12 * i)
        p.drawLine(QPointF(page.left() + page.width() * 0.12, y),
                   QPointF(page.left() + page.width() * w, y))


def _note(p, b, s):
    pad = QRectF(b.left() + b.width() * 0.12, b.top() + b.height() * 0.04,
                 b.width() * 0.66, b.height() * 0.96)
    _card(p, pad, s, 0.02, "#fffdf3")
    # spiral rings
    p.setPen(_pen("#5b6577", s * 0.012))
    for i in range(5):
        x = pad.left() + pad.width() * (0.14 + 0.18 * i)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(x - s * 0.015, pad.top() - s * 0.03, s * 0.03,
                         s * 0.05), 0, 180 * 16)
    p.setPen(_pen("#9fb6e8", s * 0.006, Qt.FlatCap))
    for i in range(5):
        y = pad.top() + pad.height() * (0.24 + 0.15 * i)
        p.drawLine(QPointF(pad.left() + pad.width() * 0.08, y),
                   QPointF(pad.right() - pad.width() * 0.08, y))
    # waveform on the lines
    p.setPen(_pen("#2f5fd0", s * 0.012))
    n = 13
    mid = pad.top() + pad.height() * 0.50
    for i in range(n):
        x = pad.left() + pad.width() * (0.14 + 0.72 * i / (n - 1))
        h = pad.height() * 0.30 * abs(math.sin(i * 1.3) * math.cos(i * 0.4))
        h = max(h, pad.height() * 0.03)
        p.drawLine(QPointF(x, mid - h), QPointF(x, mid + h))
    # record button
    c = QPointF(pad.right(), pad.bottom() - pad.height() * 0.12)
    r = b.height() * 0.17
    path = QPainterPath()
    path.addEllipse(c, r, r)
    _shadow(p, path, s)
    g = QRadialGradient(QPointF(c.x() - r * 0.3, c.y() - r * 0.3), r * 1.3)
    g.setColorAt(0, QColor("#ff6b6b"))
    g.setColorAt(1, QColor("#c62828"))
    p.setBrush(g)
    p.setPen(_pen("#ffffff", s * 0.016))
    p.drawEllipse(c, r, r)


def _stats(p, b, s):
    card = QRectF(b.left() + b.width() * 0.06, b.top(), b.width() * 0.88,
                  b.height())
    _card(p, card, s, 0.03)
    inner = card.adjusted(card.width() * 0.08, card.height() * 0.12,
                          -card.width() * 0.08, -card.height() * 0.12)
    p.setPen(_pen("#d3dbe0", s * 0.004, Qt.FlatCap))
    for i in range(4):
        y = inner.top() + inner.height() * i / 3
        p.drawLine(QPointF(inner.left(), y), QPointF(inner.right(), y))
    vals = (0.35, 0.55, 0.45, 0.75, 0.9)
    n = len(vals)
    bw = inner.width() / n * 0.55
    pts = []
    p.setPen(Qt.NoPen)
    for i, v in enumerate(vals):
        cx = inner.left() + inner.width() * (i + 0.5) / n
        h = inner.height() * v
        g = QLinearGradient(0, inner.bottom(), 0, inner.bottom() - h)
        g.setColorAt(0, QColor("#1e7a62"))
        g.setColorAt(1, QColor("#6fdcbc"))
        p.setBrush(g)
        p.drawRoundedRect(QRectF(cx - bw / 2, inner.bottom() - h, bw, h),
                          s * 0.006, s * 0.006)
        pts.append(QPointF(cx, inner.bottom() - h - inner.height() * 0.1))
    line = QPainterPath()
    line.moveTo(pts[0])
    for pt in pts[1:]:
        line.lineTo(pt)
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen("#ff8a3d", s * 0.014))
    p.drawPath(line)
    p.setPen(_pen("#ffffff", s * 0.008))
    p.setBrush(QColor("#ff8a3d"))
    for pt in pts:
        p.drawEllipse(pt, s * 0.016, s * 0.016)


_ART = {"pdf": _pdf, "sheet": _sheet, "slide": _slide, "tex": _tex,
        "note": _note, "stats": _stats}


def paint(size: int, app: str) -> QPixmap:
    rest, top, bot, kcol = APPS[app]
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    s = float(size)
    m = s * 0.09
    tile = QRectF(m, m, s - 2 * m, s - 2 * m)
    rad = tile.width() * 0.225
    g = QLinearGradient(tile.topLeft(), tile.bottomLeft())
    g.setColorAt(0, QColor(top))
    g.setColorAt(1, QColor(bot))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(tile, rad, rad)
    small = size <= 32
    if small:
        box = tile.adjusted(tile.width() * 0.12, tile.height() * 0.16,
                            -tile.width() * 0.12, -tile.height() * 0.16)
    else:
        _wordmark(p, tile, rest, kcol, s)
        box = QRectF(tile.left() + tile.width() * 0.10,
                     tile.top() + tile.height() * 0.46,
                     tile.width() * 0.80, tile.height() * 0.44)
    _ART[app](p, box, s)
    sheen = QRadialGradient(tile.center().x(), tile.top(), tile.width() * 0.8)
    sheen.setColorAt(0, QColor(255, 255, 255, 34))
    sheen.setColorAt(1, QColor(255, 255, 255, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(sheen)
    p.drawRoundedRect(tile, rad, rad)
    p.end()
    return pm
