# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for KhervePDF.

Builds a one-folder distribution (--onedir) so the .exe launches
instantly without extracting to a temp directory. Layout:

    KhervePDF/
        KhervePDF.exe          <- launcher (small, fast)
        _internal/             <- Python runtime, DLLs, packages

Build:
    pip install -r requirements.txt
    pip install pyinstaller
    pyinstaller KhervePDF.spec --noconfirm

The spec bundles every runtime dependency listed in requirements.txt,
including the optional pyHanko (digital signing) and its big
crypto stack (cryptography / asn1crypto / oscrypto). PyInstaller's
collect_all helper sweeps each one's submodules + data files so
pyhanko.sign.signers, pyhanko.pdf_utils.incremental_writer, etc.
are all reachable from the frozen build.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


block_cipher = None
ROOT = Path(SPECPATH)


def _bundle(name: str):
    """Run collect_all() on a package and tolerate ImportError so
    the spec keeps building when an optional package is missing
    (e.g. pyHanko not installed in the build env)."""
    try:
        return collect_all(name)
    except Exception:
        return [], [], []


# ---- Aggregate hidden imports / data / binaries ----------------------

datas: list = []
binaries: list = []
hiddenimports: list = []

# Each entry: (package_name, also_collect_submodules?)
_packages = [
    ("PySide6", False),
    ("pymupdf", False),
    ("fitz", False),
    ("pikepdf", False),
    ("pygit2", False),
    ("qtawesome", True),     # ships font files as data
    # pyHanko + its crypto stack (optional — graceful no-op if missing
    # in the build env, see digital_sign.is_available()).
    ("pyhanko", True),
    ("pyhanko_certvalidator", True),
    ("cryptography", True),
    ("asn1crypto", True),
    ("oscrypto", True),
    ("certifi", False),
    ("PIL", False),
    ("tzlocal", False),
    ("uritools", False),
    ("requests", False),
]
for pkg, sweep_submodules in _packages:
    d, b, h = _bundle(pkg)
    datas += d
    binaries += b
    hiddenimports += h
    if sweep_submodules:
        try:
            hiddenimports += collect_submodules(pkg)
        except Exception:
            pass


# ---- Analysis --------------------------------------------------------

a = Analysis(
    [str(ROOT / "KhervePDF.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + [
        # Lazy imports that PyInstaller's static analysis misses.
        "khervepdf.digital_sign",
        "khervepdf.find_bar",
        "khervepdf.git_backend",
        "khervepdf.history_dialog",
        "khervepdf.outline",
        "khervepdf.page_ops",
        "khervepdf.remote_dialog",
        "khervepdf.thumbnails",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Conflicting Qt bindings — we use PySide6.
        "PyQt5",
        "PyQt6",
        # GUI toolkits / dev tooling we don't ship.
        "tkinter",
        "test",
        "pip",
        "setuptools",
        # Heavy transitive dependencies that sneak in from the dev
        # environment.
        "scipy",
        "pandas",
        "IPython",
        "jedi",
        "parso",
        "pyarrow",
        "zmq",
        "tornado",
        "notebook",
        "jupyter",
        "docutils",
        "babel",
        "matplotlib",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)


# ---- PYZ -------------------------------------------------------------

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)


# ---- EXE -------------------------------------------------------------

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KhervePDF",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                  # GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # No .ico file in the repo (icons.app_icon() draws the KP
    # monogram at runtime); leave Windows to pick its default for
    # the .exe itself.
    icon=None,
)


# ---- COLLECT ---------------------------------------------------------

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="KhervePDF",
)
