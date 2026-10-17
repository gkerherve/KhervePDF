"""One-shot macOS build of KhervePDF: .app + signature + DMG.

    python packaging/build_macos.py               # this Mac's architecture
    python packaging/build_macos.py --skip-freeze

Produces, in ``dist/``: ``KhervePDF-<ver>-macOS-<arch>.dmg``, the stable
``KhervePDF-macOS-<arch>.dmg`` copy, a ``.sha256`` next to each and
``KhervePDF-macOS-<arch>.json`` (size, hash, signing mode, for latest.json),
following docs/MACOS_INSTALLER_SPEC.md of the khervefitting-web repo.
Adapted from KherveTeX's packaging/build_macos.py.

Signing: ``MAC_SIGN_IDENTITY`` gives a Developer ID build (hardened
runtime + packaging/macos/entitlements.plist), unset it is ad hoc.
``MAC_NOTARY_PROFILE`` notarises and staples. PyInstaller cannot
cross-compile, so each architecture is built on its own runner.
"""

import argparse
import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent           # packaging/
_ROOT = _HERE.parent                              # project root
_DIST = _ROOT / "dist"
_APP = "KhervePDF"
_SPEC = _ROOT / "KhervePDF.spec"
_ARCHES = ("arm64", "x86_64")
_GREEN = "#C62828"                                # the KhervePDF red


def _run(cmd, **kwargs):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kwargs)


# --------------------------------------------------------------- version
def app_version() -> str:
    """``__version__`` from khervepdf/__init__.py: the release tag is
    ``v<__version__>`` (the commit count is only shown from a checkout)."""
    import re
    text = (_ROOT / "khervepdf" / "__init__.py").read_text()
    version = re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)
    print(f"{_APP} {version}", flush=True)
    return version


def make_icns() -> Path:
    """build/KhervePDF.icns from packaging/icons/khervepdf_<n>.png."""
    icons = _HERE / "icons"
    out = _ROOT / "build" / f"{_APP}.icns"
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / f"{_APP}.iconset"
        iconset.mkdir()
        for n in (16, 32, 128, 256, 512):
            shutil.copy2(icons / f"khervepdf_{n}.png", iconset / f"icon_{n}x{n}.png")
            shutil.copy2(icons / f"khervepdf_{n * 2}.png" if (icons / f"khervepdf_{n * 2}.png").is_file()
                         else icons / f"khervepdf_{n}.png",
                         iconset / f"icon_{n}x{n}@2x.png")
        _run(["iconutil", "-c", "icns", iconset, "-o", out])
    return out


def freeze() -> None:
    _run([sys.executable, "-m", "PyInstaller", _SPEC, "--noconfirm", "--clean"],
         cwd=_ROOT)


# ------------------------------------------------------------------ sign
def _is_macho(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            magic = fh.read(4)
    except OSError:
        return False
    return magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe",
                     b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce", b"\xbe\xba\xfe\xca")


def sign(app: Path, identity: str) -> None:
    """Inside-out: nested Mach-O files (deepest first), then the main
    executable, then the bundle. No ``--deep``, which Apple discourages.

    It has to run last: any edit inside the bundle invalidates a signature
    applied before it. Apple Silicon kills an unsigned Mach-O at launch.
    """
    adhoc = identity in ("", "-")
    base = ["codesign", "--force", "--sign", "-" if adhoc else identity]
    if not adhoc:
        base += ["--timestamp", "--options", "runtime",
                 "--entitlements", _HERE / "macos" / "entitlements.plist"]
    else:
        base += ["--timestamp=none"]
    main_exe = app / "Contents" / "MacOS" / _APP
    nested = [p for p in app.rglob("*")
              if p.is_file() and not p.is_symlink() and p != main_exe
              and _is_macho(p)]
    nested.sort(key=lambda p: len(p.parts), reverse=True)
    print(f"Signing {len(nested)} nested binaries "
          f"({'ad hoc' if adhoc else identity})", flush=True)
    for i in range(0, len(nested), 200):       # batches keep the command short
        subprocess.run([str(c) for c in base + nested[i:i + 200]], check=True,
                       stdout=subprocess.DEVNULL)
    _run(base + [main_exe])
    _run(base + [app])
    _run(["codesign", "--verify", "--strict", "--verbose=2", app])


# ------------------------------------------------------------------- DMG
def dmg_background(version: str, adhoc: bool, out_dir: Path):
    """660x400 background (+ @2x): the app name, an arrow from the app to
    Applications and, for an ad hoc build, the first-launch instruction.
    Drawn with Qt (already in the build environment) rather than Pillow.
    Returns the path of a Retina-aware TIFF, or the 1x PNG as a fallback."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage,
                               QPainter, QPen, QPolygonF)
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841

    paths = []
    for scale in (1, 2):
        img = QImage(660 * scale, 400 * scale, QImage.Format_RGB32)
        img.fill(QColor(247, 250, 249))
        dpm = int(72 * scale / 0.0254)
        img.setDotsPerMeterX(dpm)
        img.setDotsPerMeterY(dpm)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.scale(scale, scale)
        green = QColor(_GREEN)
        p.fillRect(0, 0, 660, 56, green)
        p.setPen(QColor("white"))
        font = QFont()
        font.setPixelSize(24)
        font.setBold(True)
        p.setFont(font)
        p.drawText(24, 0, 612, 56, Qt.AlignVCenter | Qt.AlignLeft,
                   f"{_APP} {version}")
        # arrow from the app icon (x 170) to Applications (x 490), y 190
        p.setPen(QPen(green, 6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(250, 190, 396, 190)
        p.setPen(Qt.NoPen)
        p.setBrush(green)
        p.drawPolygon(QPolygonF([QPointF(396, 174), QPointF(426, 190),
                                 QPointF(396, 206)]))
        p.setPen(QColor(60, 60, 60))
        font = QFont()
        font.setPixelSize(17)
        p.setFont(font)
        p.drawText(0, 285, 660, 30, Qt.AlignCenter,
                   f"Drag {_APP} to Applications")
        if adhoc:
            p.setPen(QColor(150, 90, 0))
            font.setPixelSize(13)
            p.setFont(font)
            p.drawText(0, 321, 660, 30, Qt.AlignCenter,
                       "First time: right-click the app in Applications "
                       "and choose Open")
        p.setPen(QColor(120, 120, 120))
        font.setPixelSize(12)
        p.setFont(font)
        p.drawText(0, 361, 660, 30, Qt.AlignCenter, "khervetools.com")
        p.end()
        path = out_dir / ("background.tiff" if scale == 1 else "background@2x.tiff")
        img.save(str(path), "TIFF")
        paths.append(path)

    both = out_dir / "background-both.tiff"
    try:
        _run(["tiffutil", "-cathidpicheck", paths[0], paths[1], "-out", both],
             stdout=subprocess.DEVNULL)
        return both
    except (subprocess.CalledProcessError, FileNotFoundError):
        return paths[0]


def make_dmg(app: Path, version: str, arch: str, adhoc: bool) -> Path:
    out = _DIST / f"{_APP}-{version}-macOS-{arch}.dmg"
    out.unlink(missing_ok=True)
    icns = _ROOT / "build" / f"{_APP}.icns"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        stage = tmp / "stage"
        stage.mkdir()
        # ditto, not copytree: it preserves the symlinks inside the Qt
        # framework tree, which a naive copy would flatten into duplicates.
        _run(["ditto", app, stage / app.name])
        if shutil.which("create-dmg"):
            bg = dmg_background(version, adhoc, tmp)
            cmd = ["create-dmg", "--volname", f"{_APP} {version}",
                   "--background", bg, "--window-pos", "200", "120",
                   "--window-size", "660", "400", "--icon-size", "112",
                   "--text-size", "13", "--icon", app.name, "170", "190",
                   "--hide-extension", app.name, "--app-drop-link", "490", "190",
                   "--format", "ULFO", "--no-internet-enable"]
            if icns.is_file():
                cmd += ["--volicon", icns]
            # create-dmg lays the window out through Finder (AppleScript); a
            # CI runner has no GUI session, so there it skips that step.
            if os.environ.get("CI"):
                cmd.insert(1, "--skip-jenkins")
            _run(cmd + [out, stage])
        else:
            print("create-dmg not found (brew install create-dmg): "
                  "making a plain disk image", flush=True)
            (stage / "Applications").symlink_to("/Applications")
            _run(["hdiutil", "create", "-volname", f"{_APP} {version}",
                  "-srcfolder", stage, "-fs", "HFS+", "-format", "UDZO",
                  "-imagekey", "zlib-level=9", "-ov", out])
    return out


def verify_dmg(dmg: Path, adhoc: bool) -> None:
    """Mount it read-only and check what a user would find."""
    _run(["hdiutil", "verify", dmg], stdout=subprocess.DEVNULL)
    with tempfile.TemporaryDirectory() as mnt:
        _run(["hdiutil", "attach", dmg, "-mountpoint", mnt, "-nobrowse",
              "-readonly", "-noautoopen"], stdout=subprocess.DEVNULL)
        try:
            app = Path(mnt) / f"{_APP}.app"
            if not (app / "Contents" / "MacOS" / _APP).is_file():
                raise SystemExit(f"{dmg.name}: no {_APP}.app inside")
            if not (Path(mnt) / "Applications").exists():
                raise SystemExit(f"{dmg.name}: no Applications link inside")
            _run(["codesign", "--verify", "--strict", app])
        finally:
            _run(["hdiutil", "detach", mnt, "-force"], stdout=subprocess.DEVNULL)


def notarize(dmg: Path, app: Path, profile: str) -> None:
    _run(["xcrun", "notarytool", "submit", dmg, "--keychain-profile", profile, "--wait"])
    _run(["xcrun", "stapler", "staple", dmg])
    _run(["xcrun", "stapler", "staple", app])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-freeze", action="store_true",
                        help="reuse the existing dist/KhervePDF.app")
    args = parser.parse_args()

    if sys.platform != "darwin":
        raise SystemExit("build_macos.py only runs on macOS "
                         "(PyInstaller cannot cross-compile)")
    arch = platform.machine()
    if arch not in _ARCHES:
        raise SystemExit(f"unsupported architecture {arch!r}")

    identity = os.environ.get("MAC_SIGN_IDENTITY", "").strip()
    profile = os.environ.get("MAC_NOTARY_PROFILE", "").strip()
    adhoc = not identity

    version = app_version()
    make_icns()
    if not args.skip_freeze:
        freeze()
    app = _DIST / f"{_APP}.app"
    if not app.is_dir():
        raise SystemExit(f"{app} not found — did PyInstaller's BUNDLE run?")
    # the spec stamps it again; the DMG name must agree with what About says
    bundled = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    if bundled["CFBundleShortVersionString"] != version:
        raise SystemExit(f"Info.plist says {bundled['CFBundleShortVersionString']}, "
                         f"khervepdf/__init__.py says {version}")

    sign(app, identity)
    dmg = make_dmg(app, version, arch, adhoc)
    if not adhoc:
        _run(["codesign", "--force", "--sign", identity, "--timestamp", dmg])
        if profile:
            notarize(dmg, app, profile)
        else:
            print("MAC_NOTARY_PROFILE not set: signed but NOT notarised.")
    verify_dmg(dmg, adhoc)

    stable = _DIST / f"{_APP}-macOS-{arch}.dmg"
    shutil.copy2(dmg, stable)
    digest = sha256(dmg)
    for path in (dmg, stable):
        Path(str(path) + ".sha256").write_text(f"{digest}  {path.name}\n")
    entry = {"app": _APP, "version": version, "arch": arch, "file": dmg.name,
             "stable_file": stable.name, "sha256": digest,
             "size": dmg.stat().st_size, "minimum_macos": "11.0",
             "signed": "ad-hoc" if adhoc else "developer-id",
             "notarized": bool(not adhoc and profile)}
    (_DIST / f"{_APP}-macOS-{arch}.json").write_text(json.dumps(entry, indent=2))

    print()
    print(f"{_APP} {version} ({arch}, {'ad hoc' if adhoc else 'Developer ID'})")
    for path in (dmg, stable):
        print(f"{path.name:<44} {path.stat().st_size / 1e6:>7.1f} MB")
    print(f"sha256 {digest}")


if __name__ == "__main__":
    main()
