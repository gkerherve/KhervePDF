"""Help → The Author…: a page that is all about the person behind the app.

Everything it says lives in ``AUTHOR`` / ``PROJECTS`` below so it can be
edited in one place. Colours come from the live palette, so the page
follows whichever theme is active.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QUrl, Qt
from PySide6.QtGui import (
    QColor, QDesktopServices, QFont, QGuiApplication, QPainter, QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser,
    QVBoxLayout, QWidget,
)

from . import __version__
from .icons import icon

AUTHOR = {
    "name": "Gwilherm Kerhervé",
    "initials": "GK",
    "role": "Research Associate",
    "affiliation": "Department of Materials, Imperial College London",
    "about": (
        "Works on surface analysis and X-ray Photoelectron Spectroscopy "
        "(XPS), with a focus on materials for energy storage and "
        "catalysis. Maintains a small constellation of open-source "
        "tools, mostly for the XPS community."),
    "orcid": "0000-0002-6449-1828",
    "links": [
        ("orcid", "ORCID",
         "https://orcid.org/0000-0002-6449-1828"),
        ("link", "Imperial College profile",
         "https://www.imperial.ac.uk/people/g.kerherve"),
        ("linkedin", "LinkedIn",
         "https://www.linkedin.com/in/gwilherm-kerherve-3588b978/"),
        ("github", "GitHub",
         "https://github.com/gkerherve"),
        ("email", "Email (Imperial)",
         "mailto:g.kerherve@imperial.ac.uk"),
        ("email", "Email (personal)",
         "mailto:gwilherm.kerherve@gmail.com"),
    ],
    "paper": ("KherveFitting — open-source XPS peak fitting",
              "https://doi.org/10.1002/sia.70032", "10.1002/sia.70032"),
    "repo": "https://github.com/gkerherve/KhervePDF",
    "year": "2026",
}

PROJECTS = [
    ("KherveFitting", "peak fitting for XPS and Raman spectra"),
    ("spe-xps-reader", "open reader for PHI Instruments SPE binary files"),
    ("KherveTeX", "WYSIWYG LaTeX editor"),
    ("KherveSheet", "Origin-style scientific workbook"),
    ("KhervePlot", "scientific plotting and figure preparation"),
    ("KherveBook", "Jupyter-inspired computational notebook"),
    ("KherveSlide", "WYSIWYG slide designer that writes beamer LaTeX"),
    ("KhervePaint", "hybrid raster + vector drawing"),
    ("KherveCAD", "easy CAD with OpenSCAD as the engine"),
    ("KherveHouse", "houses and buildings in 3D, no modelling tools"),
    ("KherveMol", "chemical compounds and crystal structures in 2D / 3D"),
    ("KherveDB", "reference database for the Kherve* suite"),
    ("KherveStats", "downloads and traffic for every release"),
    ("KhervePDF", "this app — PDF viewing and annotation"),
]


def citation() -> str:
    return (f"Kerhervé, G. KhervePDF: A PDF viewer and annotation editor "
            f"with built-in Git version history (v{__version__}). "
            f"{AUTHOR['repo']}")


def _avatar(size: int, bg: QColor, fg: QColor) -> QPixmap:
    """Monogram badge, drawn at runtime like every other icon (no image
    file ships with the app)."""
    dpr = QGuiApplication.primaryScreen().devicePixelRatio() \
        if QGuiApplication.primaryScreen() else 1.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    p.drawEllipse(QRectF(0, 0, size, size))
    f = QFont(p.font())
    f.setPixelSize(int(size * 0.40))
    f.setBold(True)
    f.setLetterSpacing(QFont.PercentageSpacing, 104)
    p.setFont(f)
    p.setPen(fg)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter,
               AUTHOR["initials"])
    p.end()
    return pm


def _hex(c: QColor) -> str:
    return c.name()


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(round(a.red() * (1 - t) + b.red() * t),
                  round(a.green() * (1 - t) + b.green() * t),
                  round(a.blue() * (1 - t) + b.blue() * t))


class AuthorDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About the Author — {AUTHOR['name']}")
        self.resize(660, 760)
        pal = QApplication.palette()
        text = pal.color(pal.ColorRole.WindowText)
        base = pal.color(pal.ColorRole.Window)
        accent = pal.color(pal.ColorRole.Highlight)
        on_accent = pal.color(pal.ColorRole.HighlightedText)
        muted = _mix(text, base, 0.42)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 16)
        root.setSpacing(14)

        # ---- header: badge + name ------------------------------------
        head = QHBoxLayout()
        head.setSpacing(18)
        badge = QLabel(self)
        badge.setPixmap(_avatar(92, accent, on_accent))
        badge.setFixedSize(92, 92)
        head.addWidget(badge, 0, Qt.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        name = QLabel(AUTHOR["name"], self)
        nf = name.font()
        nf.setPointSizeF(nf.pointSizeF() * 1.9)
        nf.setBold(True)
        name.setFont(nf)
        role = QLabel(AUTHOR["role"], self)
        rf = role.font()
        rf.setPointSizeF(rf.pointSizeF() * 1.15)
        role.setFont(rf)
        aff = QLabel(AUTHOR["affiliation"], self)
        aff.setStyleSheet(f"color: {_hex(muted)};")
        names.addStretch(1)
        names.addWidget(name)
        names.addWidget(role)
        names.addWidget(aff)
        names.addStretch(1)
        head.addLayout(names, 1)
        root.addLayout(head)

        # ---- link buttons --------------------------------------------
        links = QHBoxLayout()
        links.setSpacing(6)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        for i, (glyph, label, url) in enumerate(AUTHOR["links"]):
            b = QPushButton(icon(glyph), f" {label}", self)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(url)
            b.clicked.connect(
                lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            (links if i < 3 else row2).addWidget(b)
        links.addStretch(1)
        row2.addStretch(1)
        root.addLayout(links)
        root.addLayout(row2)

        # ---- body -----------------------------------------------------
        body = QTextBrowser(self)
        body.setOpenExternalLinks(True)
        body.setFrameShape(QTextBrowser.NoFrame)
        # Blend into the dialog via the palette — a stylesheet here would
        # also restyle (and break) the native scrollbar.
        bp = body.palette()
        bp.setColor(QPalette.Base, base)
        body.setPalette(bp)
        body.setHtml(self._html(text, muted, accent))
        root.addWidget(body, 1)

        # ---- footer ---------------------------------------------------
        foot = QHBoxLayout()
        copy = QPushButton(icon("copy"), " Copy citation", self)
        copy.setToolTip("Copy a citation for KhervePDF to the clipboard")
        copy.clicked.connect(self._copy_citation)
        close = QPushButton("Close", self)
        close.setDefault(True)
        close.clicked.connect(self.accept)
        foot.addWidget(copy)
        foot.addStretch(1)
        foot.addWidget(close)
        root.addLayout(foot)

    def _copy_citation(self) -> None:
        QApplication.clipboard().setText(citation())

    @staticmethod
    def _html(text: QColor, muted: QColor, accent: QColor) -> str:
        t, m, a = _hex(text), _hex(muted), _hex(accent)
        h = f"font-size:13pt; color:{a}; margin:14px 0 4px 0;"
        projects = "".join(
            f"<tr><td style='padding:3px 16px 3px 0' valign='top'>"
            f"<b>{n}</b></td><td style='padding:3px 0; color:{m}'>{d}</td>"
            f"</tr>" for n, d in PROJECTS)
        ptitle, purl, pdoi = AUTHOR["paper"]
        return (
            f"<div style='color:{t}'>"
            f"<h3 style='{h}'>About</h3>"
            f"<p style='margin-top:0'>{AUTHOR['about']}</p>"
            f"<h3 style='{h}'>The Kherve tools</h3>"
            f"<table cellspacing='0' cellpadding='0'>{projects}</table>"
            f"<h3 style='{h}'>Publication</h3>"
            f"<p style='margin-top:0'>{ptitle}<br>"
            f"<a href='{purl}' style='color:{a}'>doi:{pdoi}</a></p>"
            f"<h3 style='{h}'>Cite KhervePDF</h3>"
            f"<p style='margin-top:0; color:{m}'>{citation()}</p>"
            f"<h3 style='{h}'>Licence</h3>"
            f"<p style='margin-top:0; color:{m}'>© {AUTHOR['year']} "
            f"{AUTHOR['name']}. KhervePDF is free software, released "
            f"under the GNU General Public License v3.</p>"
            f"</div>"
        )
