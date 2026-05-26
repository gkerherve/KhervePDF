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
from io import BytesIO
from pathlib import Path

# Make sure the project root (one directory up) is on sys.path so
# `from khervepdf.icons import app_icon` works regardless of where
# the script is invoked from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Qt's QGuiApplication is sufficient (no widgets needed) but Qt
# warns if a platform plugin isn't available — offscreen is always
# safe in a CI / headless build.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray  # noqa: E402
from PySide6.QtWidgets import QApplication      # noqa: E402

from PIL import Image  # noqa: E402


SIZES = (16, 24, 32, 48, 64, 128, 256)


def main(out_path: Path) -> int:
    app = QApplication.instance() or QApplication([])
    # Import after the QApplication exists — icons.app_icon() draws
    # via QPainter on QPixmap which needs the app instance.
    from khervepdf.icons import app_icon
    icon = app_icon()
    # PIL's ICO writer takes a single source image and resamples it
    # to every requested size — pass the largest (256×256) so each
    # sub-icon downscales rather than upscaling a 16×16. Each size
    # is still embedded as its own entry in the .ico, just rendered
    # by PIL's resize instead of QPainter; the difference is
    # invisible at typical taskbar sizes.
    pm = icon.pixmap(256, 256)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.WriteOnly)
    pm.save(buf, "PNG")
    buf.close()
    base = Image.open(BytesIO(bytes(ba))).convert("RGBA")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base.save(
        str(out_path),
        format="ICO",
        sizes=[(sz, sz) for sz in SIZES],
    )
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 \
        else Path(__file__).resolve().parent.parent / "build" / "KhervePDF.ico"
    raise SystemExit(main(target))
