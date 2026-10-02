"""Shared test setup.

The app keeps the user's real preferences (theme, recent files, AI
provider and API key, chat history, dock state) in QSettings under
("kherve", "KhervePDF"). Tests must never read or write that store.

On macOS ``QSettings(org, app)`` always uses the native store (the
user's real ``~/Library/Preferences`` plist) no matter what
``setDefaultFormat`` says, so redirecting it needs more than a setting:
this replaces ``PySide6.QtCore.QSettings`` — before any test module (or
khervepdf module) imports it — with a subclass that maps the
``(org, app)`` form onto a throwaway INI file.
"""
import atexit
import os
import shutil
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore

_REAL = QtCore.QSettings
_ROOT = tempfile.mkdtemp(prefix="khervepdf-test-settings-")
atexit.register(shutil.rmtree, _ROOT, ignore_errors=True)


class _IsolatedSettings(_REAL):
    def __init__(self, *args):
        if len(args) == 2 and all(isinstance(a, str) for a in args):
            org, app = args
            super().__init__(os.path.join(_ROOT, f"{org}.{app}.ini"),
                             _REAL.IniFormat)
        else:
            super().__init__(*args)


QtCore.QSettings = _IsolatedSettings

# Guard the guard: if this ever stops redirecting, fail at collection
# instead of silently touching the user's real settings.
assert QtCore.QSettings("kherve", "KhervePDF").fileName().startswith(_ROOT)
