"""KhervePDF application entry: QApplication + theme bootstrap + crash log."""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSettings
from PySide6.QtWidgets import QApplication

from . import single_instance, themes
from .icons import app_icon


def _install_crash_log() -> None:
    log_path = Path(tempfile.gettempdir()) / "khervepdf_crash.log"

    def _hook(exc_type, exc, tb):
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write("--- KhervePDF crash ---\n")
            traceback.print_exception(exc_type, exc, tb, file=fh)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook


class _FileOpenFilter(QObject):
    """macOS delivers Finder's "Open" / "Open with" on the running app
    as a FileOpen event rather than a new process."""

    def __init__(self, win):
        super().__init__(win)
        self._win = win

    def eventFilter(self, obj, event):  # noqa: N802 — Qt override
        if event.type() == QEvent.FileOpen and event.file():
            self._win.open_request({"cmd": "open", "paths": [event.file()]})
            return True
        return False


def main() -> int:
    _install_crash_log()
    app = QApplication(sys.argv)
    app.setApplicationName("KhervePDF")
    app.setOrganizationName("kherve")
    app.setWindowIcon(app_icon())

    settings = QSettings("kherve", "KhervePDF")
    theme_name = settings.value("theme_name", "Light") or "Light"
    themes.apply_theme(app, theme_name)

    paths = [str(Path(a).resolve()) for a in sys.argv[1:]
             if not a.startswith("-") and Path(a).exists()]
    # Already running: the PDFs open as tabs there, and this launch ends.
    if single_instance.send_to_running({"cmd": "open", "paths": paths}):
        return 0

    from .mainwindow import MainWindow
    win = MainWindow(theme_name=theme_name)
    server = single_instance.Server(app)
    server.request.connect(win.open_request)
    app.installEventFilter(_FileOpenFilter(win))
    # Open files passed on the command line / by file association
    # *before* showing the window, so the welcome page never flashes.
    for p in paths:
        win.open_path(Path(p))
    win.show()
    # Centre on the primary screen now that frameGeometry is known.
    screen = app.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        fg = win.frameGeometry()
        fg.moveCenter(avail.center())
        win.move(fg.topLeft())

    return app.exec()
