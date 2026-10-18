"""One-shot Linux build: frozen app + a Debian package (.deb).

    python packaging/build_deb.py                 # this machine's architecture
    python packaging/build_deb.py --skip-freeze   # reuse dist/KhervePDF

Produces, in ``dist/``: ``KhervePDF_<version>_<arch>.deb`` (amd64 or arm64)
and the stable-name copy ``KhervePDF-linux-<arch>.deb``. Install with
``sudo apt install ./KhervePDF_<version>_<arch>.deb``: the one-folder build
goes to /opt/khervepdf, with a ``khervepdf`` command, a menu entry and the
icon. PyInstaller cannot cross-compile, so each architecture is built on
its own runner. Adapted from KherveSlide's packaging/build_deb.py.
"""

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent           # packaging/
_ROOT = _HERE.parent
_DIST = _ROOT / "dist"
_APP = "KhervePDF"
_PKG = "khervepdf"
_SPEC = _ROOT / "KhervePDF.spec"

# Runtime libraries a PySide6 (Qt 6) app needs from the system on X11 and
# Wayland; PyInstaller bundles Qt itself, not these.
_DEPENDS = [
    "libc6 (>= 2.35)", "libgl1", "libegl1", "libfontconfig1", "libfreetype6",
    "libdbus-1-3", "libxkbcommon0", "libxkbcommon-x11-0", "libx11-xcb1",
    "libxcb-cursor0", "libxcb-icccm4", "libxcb-image0", "libxcb-keysyms1",
    "libxcb-randr0", "libxcb-render-util0", "libxcb-shape0", "libxcb-xinerama0",
    "libxcb-xkb1", "libwayland-client0", "libwayland-cursor0", "libwayland-egl1",
]


def _run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def deb_arch() -> str:
    m = platform.machine()
    return {"x86_64": "amd64", "amd64": "amd64",
            "aarch64": "arm64", "arm64": "arm64"}.get(m) or sys.exit(
        f"unsupported architecture {m!r}")


def app_version() -> str:
    """``__version__`` from khervepdf/__init__.py (the release tag)."""
    text = (_ROOT / "khervepdf" / "__init__.py").read_text()
    version = re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)
    print(f"{_APP} {version}", flush=True)
    return version


def build_deb(version: str, arch: str) -> Path:
    stage = _ROOT / "build" / "deb" / f"{_PKG}_{version}_{arch}"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(_DIST / _APP, stage / "opt" / _PKG, symlinks=True)

    (stage / "usr" / "bin").mkdir(parents=True)
    os.symlink(f"/opt/{_PKG}/{_APP}", stage / "usr" / "bin" / _PKG)

    for size in (48, 128, 256, 512):
        d = stage / "usr/share/icons/hicolor" / f"{size}x{size}" / "apps"
        d.mkdir(parents=True)
        shutil.copy2(_HERE / "icons" / f"khervepdf_{size}.png", d / f"{_PKG}.png")

    apps = stage / "usr/share/applications"
    apps.mkdir(parents=True)
    (apps / f"{_PKG}.desktop").write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={_APP}\n"
        "GenericName=PDF editor\n"
        "Comment=PDF viewer and annotation editor with Git history\n"
        f"Exec={_PKG} %f\n"
        f"Icon={_PKG}\n"
        "Terminal=false\n"
        "Categories=Office;Viewer;\n"
        "MimeType=application/pdf;\n"
        f"StartupWMClass={_APP}\n", encoding="utf-8")

    debian = stage / "DEBIAN"
    debian.mkdir()
    size_kb = sum(p.stat().st_size for p in stage.rglob("*")
                  if p.is_file() and not p.is_symlink()) // 1024
    (debian / "control").write_text(
        f"Package: {_PKG}\n"
        f"Version: {version}\n"
        f"Architecture: {arch}\n"
        "Maintainer: Gwilherm Kerherve <gwilherm.kerherve@gmail.com>\n"
        f"Installed-Size: {size_kb}\n"
        f"Depends: {', '.join(_DEPENDS)}\n"
        "Section: text\n"
        "Priority: optional\n"
        "Homepage: https://khervetools.com/tools/khervepdf\n"
        "Description: PDF viewer and annotation editor with built-in Git history\n"
        " Tabbed PDF viewing, annotations, page operations, form filling,\n"
        " text editing, OCR and comparison; every document gets its own Git\n"
        " repository with auto-commit and a history browser.\n", encoding="utf-8")
    for name in ("postinst", "postrm"):
        script = debian / name
        script.write_text(
            "#!/bin/sh\nset -e\n"
            "command -v update-desktop-database >/dev/null 2>&1 && "
            "update-desktop-database -q /usr/share/applications || true\n"
            "command -v gtk-update-icon-cache >/dev/null 2>&1 && "
            "gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true\n",
            encoding="utf-8")
        script.chmod(0o755)

    out = _DIST / f"{_APP}_{version}_{arch}.deb"
    out.unlink(missing_ok=True)
    _run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", stage, out])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-freeze", action="store_true",
                    help="reuse the existing dist/KhervePDF folder")
    args = ap.parse_args()
    if not sys.platform.startswith("linux"):
        sys.exit("build_deb.py only runs on Linux (PyInstaller cannot cross-compile)")
    if not shutil.which("dpkg-deb"):
        sys.exit("dpkg-deb not found (sudo apt install dpkg-dev)")
    arch = deb_arch()
    version = app_version()
    if not args.skip_freeze:
        _run([sys.executable, "-m", "PyInstaller", _SPEC, "--noconfirm", "--clean"],
             cwd=_ROOT, env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    if not (_DIST / _APP / _APP).is_file():
        sys.exit(f"{_DIST / _APP / _APP} not found — did the freeze run?")
    deb = build_deb(version, arch)
    stable = _DIST / f"{_APP}-linux-{arch}.deb"
    shutil.copy2(deb, stable)
    print()
    for p in (deb, stable):
        print(f"{p.name:<40} {p.stat().st_size / 1e6:>7.1f} MB")


if __name__ == "__main__":
    main()
