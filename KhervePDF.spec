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


# ---- Generate the Windows .ico from the runtime app_icon() -----------

# Single source of truth for the red "KP" monogram lives in
# khervepdf/icons.py. tools/generate_icon.py renders it at all 7
# sizes (16..256) into a multi-resolution ICO under build/. The
# resulting file is referenced by the EXE() block below and by
# KhervePDF_setup.iss's SetupIconFile.
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")   # no exe icon on Linux
ICON_PATH = ROOT / "build" / ("KhervePDF.icns" if IS_MAC else "KhervePDF.ico")
# On macOS packaging/build_macos.py writes the .icns before freezing.
if not IS_MAC and not IS_LINUX and not ICON_PATH.exists():
    import subprocess as _sp
    _sp.run(
        [sys.executable, str(ROOT / "tools" / "generate_icon.py"),
         str(ICON_PATH)],
        check=True,
    )


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
# On macOS collect_all("PySide6") drags in every Qt framework (WebEngine,
# Quick, Designer .app bundles) — 430 MB, and nested .app bundles that
# break codesign. PyInstaller's own PySide6 hooks collect exactly the
# modules the app imports, so rely on them there.
if IS_MAC:
    _packages = [p for p in _packages if p[0] != "PySide6"]
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

# Strip PySide6 directories that a pure QtWidgets app never touches.
# collect_all("PySide6") sweeps everything; drop the bulk here.
_strip_prefixes = (
    "PySide6/qml",
    "PySide6/resources",
    "PySide6/translations",
    "PySide6/metatypes",
    "PySide6/include",
    "PySide6/typesystems",
    "PySide6/glue",
    "PySide6/scripts",
    "PySide6\\qml",
    "PySide6\\resources",
    "PySide6\\translations",
    "PySide6\\metatypes",
    "PySide6\\include",
    "PySide6\\typesystems",
    "PySide6\\glue",
    "PySide6\\scripts",
)
# Also strip plugin subdirectories we don't need (keep platforms,
# styles, imageformats, iconengines, platforminputcontexts, tls).
_strip_plugins = (
    "plugins/assetimporters", "plugins/canbus", "plugins/designer",
    "plugins/generic", "plugins/geometryloaders", "plugins/geoservices",
    "plugins/multimedia", "plugins/networkinformation", "plugins/position",
    "plugins/qmllint", "plugins/qmltooling", "plugins/renderers",
    "plugins/renderplugins", "plugins/sceneparsers",
    "plugins/scxmldatamodel", "plugins/sensors", "plugins/sqldrivers",
    "plugins/texttospeech", "plugins/vectorimageformats", "plugins/webview",
)
_strip_plugins_all = tuple(
    p.replace("/", sep)
    for sep in ("/", "\\")
    for p in _strip_plugins
)
_all_strip = _strip_prefixes + tuple(
    f"PySide6/{p}" for p in _strip_plugins
) + tuple(
    f"PySide6\\{p}" for p in _strip_plugins
)


def _prune(pairs):
    """Filter (source, dest_dir) tuples by dest_dir prefix."""
    return [
        (src, dest) for src, dest in pairs
        if not any(dest.startswith(pfx) for pfx in _all_strip)
    ]


datas = _prune(datas)
# Edit Text's bundled fonts (CMU, Liberation, Carlito/Caladea, TeX Gyre)
# — font_library resolves them next to its own module.
datas += [(str(ROOT / "khervepdf" / "fonts"), "khervepdf/fonts")]
binaries = _prune(binaries)


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
        # PySide6 modules we don't use — KhervePDF only needs
        # QtCore, QtGui, QtWidgets, QtPrintSupport, QtSvg, QtNetwork.
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtBluetooth",
        "PySide6.QtCharts",
        "PySide6.QtConcurrent",
        "PySide6.QtDataVisualization",
        "PySide6.QtDesigner",
        "PySide6.QtGraphs",
        "PySide6.QtHttpServer",
        "PySide6.QtLocation",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtNetworkAuth",
        "PySide6.QtNfc",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtPositioning",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtQuickControls2",
        "PySide6.QtQuickWidgets",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtSerialBus",
        "PySide6.QtSerialPort",
        "PySide6.QtSpatialAudio",
        "PySide6.QtSql",
        "PySide6.QtStateMachine",
        "PySide6.QtTest",
        "PySide6.QtTextToSpeech",
        "PySide6.QtUiTools",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
        "PySide6.QtXml",
        "PySide6.QtAsyncio",
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
    upx=not IS_MAC,              # UPX corrupts Mach-O signatures
    console=False,                  # GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # The .ico is generated above from icons.app_icon() — same red
    # KP monogram the app draws at runtime, baked into the .exe's
    # Windows resource section so Explorer / the taskbar pick it up.
    icon=None if IS_LINUX else str(ICON_PATH),
)


# ---- COLLECT ---------------------------------------------------------

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=not IS_MAC,
    upx_exclude=[],
    name="KhervePDF",
)


# ---- BUNDLE (macOS) --------------------------------------------------

if IS_MAC:
    import re as _re
    _ver = _re.search(r'__version__\s*=\s*"([^"]+)"',
                      (ROOT / "khervepdf" / "__init__.py").read_text()).group(1)
    try:
        import subprocess as _sp
        _build = _sp.run(["git", "rev-list", "--count", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        _build = _ver
    app = BUNDLE(
        coll,
        name="KhervePDF.app",
        icon=str(ICON_PATH),
        bundle_identifier="com.kerherve.khervepdf",
        info_plist={
            "CFBundleName": "KhervePDF",
            "CFBundleDisplayName": "KhervePDF",
            "CFBundleShortVersionString": _ver,
            "CFBundleVersion": _build,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHumanReadableCopyright": "\u00a9 2026 Gwilherm Kerherve",
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "PDF document",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["com.adobe.pdf"],
            }],
        },
    )
