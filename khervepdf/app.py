"""KhervePDF application entry: QApplication + theme bootstrap + crash log."""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from . import themes
from .icons import app_icon
from .mainwindow import MainWindow


def _install_crash_log() -> None:
    log_path = Path(tempfile.gettempdir()) / "khervepdf_crash.log"

    def _hook(exc_type, exc, tb):
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write("--- KhervePDF crash ---\n")
            traceback.print_exception(exc_type, exc, tb, file=fh)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook


def main() -> int:
    _install_crash_log()
    app = QApplication(sys.argv)
    app.setApplicationName("KhervePDF")
    app.setOrganizationName("kherve")
    app.setWindowIcon(app_icon())

    settings = QSettings("kherve", "KhervePDF")
    theme_name = settings.value("theme_name", "Light") or "Light"
    themes.apply_theme(app, theme_name)

    win = MainWindow(theme_name=theme_name)
    win.show()
    # Centre on the primary screen now that frameGeometry is known.
    screen = app.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        fg = win.frameGeometry()
        fg.moveCenter(avail.center())
        win.move(fg.topLeft())

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        path = Path(args[0])
        if path.exists():
            win.open_path(path)

    return app.exec()
