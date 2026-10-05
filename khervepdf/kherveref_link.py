"""Handing PDFs to KherveRef, the Kherve reference manager.

KherveRef is a separate app; it is found the way KherveRef finds
KhervePDF — a path the user chose, the usual install locations, then a
source checkout next to this one (run with its own venv). A running
KherveRef takes over a second launch's request and the new process
exits, so launching it detached is all that is needed either way.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings

SETTINGS = ("kherve", "KhervePDF")
PATH_KEY = "kherveref/path"


def _source_checkout() -> Path:
    return Path(__file__).resolve().parents[2] / "KherveRef" / "KherveRef.py"


def _python_for(script: Path) -> str | None:
    for venv in (".venv", "venv"):
        for rel in ("bin/python", "Scripts/python.exe"):
            cand = script.parent / venv / rel
            if cand.exists():
                return str(cand)
    return None


def _command_for(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    if path.suffix == ".app":
        exe = path / "Contents" / "MacOS" / "KherveRef"
        return [str(exe)] if exe.exists() else None
    if path.suffix == ".py":
        py = _python_for(path)
        return [py, str(path)] if py else None
    if path.is_dir():
        return None
    return [str(path)]


def candidate_paths() -> list[Path]:
    paths: list[Path] = []
    custom = QSettings(*SETTINGS).value(PATH_KEY, "", type=str)
    if custom:
        paths.append(Path(custom))
    if sys.platform == "darwin":
        paths += [Path("/Applications/KherveRef.app"),
                  Path.home() / "Applications" / "KherveRef.app"]
    elif sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(env):
                paths.append(Path(os.environ[env]) / "KherveRef" / "KherveRef.exe")
        if os.environ.get("LOCALAPPDATA"):
            paths.append(Path(os.environ["LOCALAPPDATA"]) / "Programs"
                         / "KherveRef" / "KherveRef.exe")
    paths.append(_source_checkout())
    return paths


def find_kherveref() -> list[str] | None:
    """The argv prefix that runs KherveRef, or None if it can't be found."""
    for p in candidate_paths():
        cmd = _command_for(p)
        if cmd:
            return cmd
    return None


def set_custom_path(path: str) -> bool:
    if _command_for(Path(path)) is None:
        return False
    QSettings(*SETTINGS).setValue(PATH_KEY, path)
    return True


def _launch(flag: str, pdf: Path) -> bool:
    cmd = find_kherveref()
    if not cmd:
        return False
    ok, _pid = QProcess.startDetached(
        cmd[0], cmd[1:] + [flag, str(Path(pdf).resolve())])
    return bool(ok)


def add_to_kherveref(pdf: Path) -> bool:
    """Import *pdf* into KherveRef's open library."""
    return _launch("--add", pdf)


def reveal_in_kherveref(pdf: Path) -> bool:
    """Select the reference whose attachment is *pdf*."""
    return _launch("--reveal", pdf)
