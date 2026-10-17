"""The updater offers each platform its own installer from a release."""
from khervepdf.updater import _pick_asset, is_newer

PAGE = "https://github.com/gkerherve/KhervePDF/releases/latest"
ASSETS = [{"name": n, "browser_download_url": f"https://x/{n}"} for n in (
    "KhervePDF-0.79-macOS-arm64.dmg", "KhervePDF-0.79-macOS-x86_64.dmg",
    "KhervePDF-macOS-arm64.dmg", "KhervePDF-macOS-x86_64.dmg",
    "KhervePDF_0.79.zip", "KhervePDF-Setup.exe", "Setup_KhervePDF_0.79.exe",
    "latest.json")]


def test_windows_gets_the_stable_installer():
    assert _pick_asset(ASSETS, PAGE, "win32") == "https://x/KhervePDF-Setup.exe"


def test_each_mac_gets_its_own_architecture():
    assert _pick_asset(ASSETS, PAGE, "darwin", "arm64") == "https://x/KhervePDF-macOS-arm64.dmg"
    assert _pick_asset(ASSETS, PAGE, "darwin", "x86_64") == "https://x/KhervePDF-macOS-x86_64.dmg"


def test_a_release_without_mac_assets_falls_back_to_the_page():
    win_only = [a for a in ASSETS if not a["name"].endswith(".dmg")]
    assert _pick_asset(win_only, PAGE, "darwin", "arm64") == PAGE
    assert _pick_asset(ASSETS, PAGE, "linux") == PAGE


def test_version_comparison():
    assert is_newer("v0.79", "0.71")
    assert not is_newer("v0.79", "0.79")
    assert is_newer("v0.100", "0.99")
