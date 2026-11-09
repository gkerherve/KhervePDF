# Copyright (C) 2026 Gwilherm Kerherve
# Licensed under the GNU General Public License v3.0 (see LICENSE).
"""The KhervePDF application mark: the shared Kherve-family design in
``kmark`` (one-line "kPDF" wordmark over a shaded illustration)."""

from .kmark import paint as _paint


def paint(size: int):
    """Render the mark at *size* px (QPixmap)."""
    return _paint(size, "pdf")
