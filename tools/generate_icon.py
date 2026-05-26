"""Generate KhervePDF.ico from the runtime app_icon().

Single source of truth for the red "KP" monogram lives in
khervepdf.icons.app_icon() — that draws the icon at 7 sizes via
QPainter. This script renders each of those into a PNG, stuffs them
into a single multi-resolution .ico, and writes the result to the
path supplied on the command line (defaults to build/KhervePDF.ico).

PyInstaller's KhervePDF.spec runs this before the actual Analysis
so the bootloader .exe gets the proper Windows icon. Inno Setup
uses the same file for SetupIconFile.

CLAUDE.md says "no PNG / SVG / .ico files for UI chrome in the
repo" — this .ico is a build artifact (written to build/, which is
gitignored), not shipped as a hand-drawn asset.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make sure the project root (one directory up) is on sys.path so
# `from khervepdf.icons import app_icon` works regardless of where
# the script is invoked from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# DO NOT force QT_QPA_PLATFORM=offscreen here — the offscreen
# plugin on Windows loads zero font families (QFontDatabase
# returns []), so QPainter.drawText produces tofu rectangles
# instead of "KP" letters. Use the native platform plugin (Qt
# picks it automatically) so the system font catalog is available.
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QBuffer, QByteArray  # noqa: E402
from PySide6.QtWidgets import QApplication      # noqa: E402


SIZES = (16, 24, 32, 48, 64, 128, 256)


def main(out_path: Path) -> int:
    app = QApplication.instance() or QApplication([])
    from khervepdf.icons import app_icon
    icon = app_icon()
    # Render each size *natively* via QPainter and grab the PNG
    # bytes. PIL's ICO writer can't reliably embed pre-rendered
    # per-size images (append_images is unreliable for ICO), so
    # we hand-write the ICO container.
    pngs_by_size: dict[int, bytes] = {}
    for sz in SIZES:
        pm = icon.pixmap(sz, sz)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.WriteOnly)
        pm.save(buf, "PNG")
        buf.close()
        pngs_by_size[sz] = bytes(ba)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(_compose_ico(pngs_by_size))


def _compose_ico(pngs_by_size: dict[int, bytes]) -> bytes:
    """Build an ICO with one PNG-encoded entry per size.

    ICO file layout:
      ICONDIR  (6 bytes): reserved(2)=0, type(2)=1, count(2)
      ICONDIRENTRY × N (16 bytes each):
        bWidth(1), bHeight(1) — 0 means 256 (max), else the pixel
        size; bColorCount(1)=0 (>=256 colors), bReserved(1)=0,
        wPlanes(2)=1, wBitCount(2)=32 (RGBA), dwBytesInRes(4),
        dwImageOffset(4).
      Image data: the PNG bytes back-to-back.
    """
    import struct
    sizes = sorted(pngs_by_size.keys())
    n = len(sizes)
    out = bytearray()
    out += struct.pack("<HHH", 0, 1, n)  # ICONDIR
    data_offset = 6 + 16 * n
    for sz in sizes:
        data = pngs_by_size[sz]
        # 0 in bWidth/bHeight means 256 — the format's escape hatch
        # for that single corner case.
        w = h = 0 if sz == 256 else sz
        out += struct.pack(
            "<BBBBHHII",
            w, h, 0, 0,
            1, 32,
            len(data),
            data_offset,
        )
        data_offset += len(data)
    for sz in sizes:
        out += pngs_by_size[sz]
    return bytes(out)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 \
        else Path(__file__).resolve().parent.parent / "build" / "KhervePDF.ico"
    raise SystemExit(main(target))
