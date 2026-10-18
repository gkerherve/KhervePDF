"""Launch splash: the picture shown while the main window is built.

Painted at runtime with QPainter (project rule: no PNG/SVG for UI
chrome) — a red wash in the app-mark colours, a fan of stylised pages,
the Kpdf mark, the name, the tagline and the version. Rendered at the
screen's device-pixel ratio so it stays crisp on Retina displays.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QGuiApplication, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QSplashScreen

from . import appmark

W, H = 640, 380


def _page(p: QPainter, cx: float, cy: float, angle: float,
          w: float, h: float, alpha: int) -> None:
    """One tilted sheet with a folded corner and a few text lines."""
    p.save()
    p.translate(cx, cy)
    p.rotate(angle)
    r = QRectF(-w / 2, -h / 2, w, h)
    fold = w * 0.22
    path = QPainterPath()
    path.moveTo(r.left(), r.top())
    path.lineTo(r.right() - fold, r.top())
    path.lineTo(r.right(), r.top() + fold)
    path.lineTo(r.right(), r.bottom())
    path.lineTo(r.left(), r.bottom())
    path.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, alpha // 4))
    p.drawPath(path.translated(4, 6))                      # soft shadow
    p.setBrush(QColor(255, 255, 255, alpha))
    p.drawPath(path)
    p.setBrush(QColor(230, 225, 225, alpha))
    corner = QPainterPath()
    corner.moveTo(r.right() - fold, r.top())
    corner.lineTo(r.right() - fold, r.top() + fold)
    corner.lineTo(r.right(), r.top() + fold)
    corner.closeSubpath()
    p.drawPath(corner)
    pen = QPen(QColor(198, 40, 40, alpha * 2 // 3))
    pen.setWidthF(h * 0.025)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    y = r.top() + h * 0.28
    for frac in (0.62, 0.75, 0.55, 0.70, 0.40):
        p.drawLine(QPointF(r.left() + w * 0.14, y),
                   QPointF(r.left() + w * (0.14 + frac * 0.72), y))
        y += h * 0.12
    p.restore()


def paint(version: str = "", dpr: float = 1.0) -> QPixmap:
    pm = QPixmap(int(W * dpr), int(H * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    card = QPainterPath()
    card.addRoundedRect(QRectF(0, 0, W, H), 18, 18)
    p.setClipPath(card)
    bg = QLinearGradient(0, 0, W, H)
    bg.setColorAt(0.0, QColor("#e53935"))
    bg.setColorAt(0.55, QColor("#c62828"))
    bg.setColorAt(1.0, QColor("#7f1414"))
    p.fillRect(QRectF(0, 0, W, H), bg)
    glow = QRadialGradient(QPointF(W * 0.78, H * 0.38), W * 0.45)
    glow.setColorAt(0.0, QColor(255, 255, 255, 70))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillRect(QRectF(0, 0, W, H), glow)

    # Fan of pages on the right.
    for cx, cy, ang, a in ((W * 0.70, H * 0.50, -16, 150),
                           (W * 0.78, H * 0.46, -2, 200),
                           (W * 0.86, H * 0.50, 13, 255)):
        _page(p, cx, cy, ang, 130, 172, a)
    # A highlighter stroke across the front page, as if being annotated.
    hl = QPen(QColor(255, 235, 59, 150))
    hl.setWidthF(12)
    hl.setCapStyle(Qt.RoundCap)
    p.setPen(hl)
    p.drawLine(QPointF(W * 0.80, H * 0.60), QPointF(W * 0.91, H * 0.63))

    # Mark + wordmark on the left.
    mark = appmark.paint(int(96 * dpr))
    mark.setDevicePixelRatio(dpr)
    p.drawPixmap(QPointF(44, 58), mark)

    p.setPen(QColor("#ffffff"))
    f = QFont()
    f.setPixelSize(52)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(44, 168, 360, 64), Qt.AlignLeft | Qt.AlignVCenter,
               "KhervePDF")
    f2 = QFont()
    f2.setPixelSize(17)
    p.setFont(f2)
    p.setPen(QColor(255, 255, 255, 225))
    p.drawText(QRectF(46, 232, 340, 60), Qt.AlignLeft | Qt.TextWordWrap,
               "Read, annotate and edit PDFs —\nwith full Git history.")
    f3 = QFont()
    f3.setPixelSize(12)
    p.setFont(f3)
    p.setPen(QColor(255, 255, 255, 170))
    label = f"Version {version.lstrip('v')}" if version else ""
    p.drawText(QRectF(46, H - 46, 300, 20), Qt.AlignLeft, label)
    p.drawText(QRectF(W - 300, H - 46, 270, 20), Qt.AlignRight,
               "Loading…")
    p.end()
    return pm


def show(version: str = "") -> QSplashScreen:
    screen = QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    splash = QSplashScreen(paint(version, dpr), Qt.WindowStaysOnTopHint)
    splash.setAttribute(Qt.WA_TranslucentBackground)
    splash.show()
    QGuiApplication.processEvents()
    return splash
