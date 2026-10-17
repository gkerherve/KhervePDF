"""One-shot Windows build of KhervePDF: exe + portable zip + Inno installer.

    python packaging/build_installer.py

The Python twin of build_release.ps1, so the same build runs on a
GitHub ``windows-latest`` runner (.github/workflows/windows-build.yml).
Produces, in ``dist/``: ``KhervePDF_<ver>.zip`` (root folder
``KhervePDF/``), ``Setup_KhervePDF_<ver>.exe`` and the stable-name copy
``KhervePDF-Setup.exe`` that the website and the updater link to.
"""

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DIST = _ROOT / "dist"
_APP = "KhervePDF"

# PySide6 bulk a QtWidgets app never touches (same lists as build_release.ps1).
_STRIP_DIRS = ("qml", "translations", "metatypes", "include", "typesystems",
               "glue", "scripts", "doc", "support", "lib", "QtAsyncio", "resources")
_KEEP_PLUGINS = ("platforms", "styles", "imageformats", "iconengines",
                 "platforminputcontexts", "tls")
_ISCC = (r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
         r"C:\Program Files\Inno Setup 6\ISCC.exe",
         os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"))


def _run(cmd, **kwargs):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, cwd=_ROOT, **kwargs)


def app_version() -> str:
    text = (_ROOT / "khervepdf" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def strip_pyside(folder: Path) -> None:
    pyside = folder / "_internal" / "PySide6"
    for d in _STRIP_DIRS:
        shutil.rmtree(pyside / d, ignore_errors=True)
    plugins = pyside / "plugins"
    if plugins.is_dir():
        for d in plugins.iterdir():
            if d.is_dir() and d.name not in _KEEP_PLUGINS:
                shutil.rmtree(d)


def make_zip(folder: Path, out: Path) -> None:
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                zf.write(p, Path(_APP) / p.relative_to(folder))


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("build_installer.py builds the Windows installer; "
                         "on macOS use packaging/build_macos.py")
    version = app_version()
    print(f"Building {_APP} v{version}", flush=True)
    _run([sys.executable, "tools/generate_icon.py", "build/KhervePDF.ico"])
    _run([sys.executable, "-m", "PyInstaller", "KhervePDF.spec", "--noconfirm", "--clean"])
    folder = _DIST / _APP
    strip_pyside(folder)

    zip_path = _DIST / f"{_APP}_{version}.zip"
    make_zip(folder, zip_path)

    iscc = next((c for c in _ISCC if Path(c).is_file()), None) or shutil.which("iscc")
    if not iscc:
        raise SystemExit("Inno Setup 6 (ISCC.exe) not found")
    _run([iscc, f"/DMyAppVersion={version}", f"/O{_DIST}", "KhervePDF_setup.iss"])
    setup = _DIST / f"Setup_{_APP}_{version}.exe"
    shutil.copy2(setup, _DIST / f"{_APP}-Setup.exe")

    for p in (setup, _DIST / f"{_APP}-Setup.exe", zip_path):
        print(f"{p.name:<36} {p.stat().st_size / 1e6:>7.1f} MB")


if __name__ == "__main__":
    main()
