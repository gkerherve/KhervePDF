"""Update check against the project's GitHub releases.

Asks https://api.github.com/repos/gkerherve/KhervePDF/releases/latest
for the newest tag (``v0.71`` style) and compares it to
``khervepdf.__version__``. Networking goes through QNetworkAccessManager
so the request is asynchronous on the Qt event loop — the UI never
blocks, and there is no worker thread to tear down on exit.

Nothing is ever installed silently: a newer release only produces an
``update_available`` signal; the UI decides how to offer it, and the
"download" step just hands a URL to the system browser.
"""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QSettings, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import __version__

RELEASES_API = "https://api.github.com/repos/gkerherve/KhervePDF/releases/latest"
RELEASES_PAGE = "https://github.com/gkerherve/KhervePDF/releases/latest"

# Automatic checks are rate-limited to once a day: GitHub's anonymous
# API quota is 60 requests/hour per IP, and a daily cadence is plenty
# for a desktop app's release rhythm.
_AUTO_INTERVAL_S = 24 * 3600
_KEY_ENABLED = "updates/auto_check"
_KEY_LAST = "updates/last_check"


def parse_version(tag: str) -> tuple[int, ...]:
    """``"v0.71"`` / ``"0.71.3"`` -> ``(0, 71)`` / ``(0, 71, 3)``.

    Non-numeric suffixes (``-beta``) are ignored; an unparsable tag
    yields ``()`` which compares lower than any real version, so a
    weird tag can never trigger a bogus "update available".
    """
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", tag or "")
    if not m:
        return ()
    return tuple(int(x) for x in m.group(1).split("."))


def is_newer(remote_tag: str, local: str = __version__) -> bool:
    return parse_version(remote_tag) > parse_version(local)


@dataclass
class ReleaseInfo:
    tag: str
    page_url: str
    download_url: str  # platform asset if one matches, else page_url


def _pick_asset(assets: list[dict], page_url: str) -> str:
    """Choose the release asset for this platform: the Windows
    installer ``.exe`` or the macOS ``.dmg``. Anything else (Linux, or
    no matching asset) falls back to the release page."""
    if sys.platform.startswith("win"):
        wanted = (".exe", ".msi")
    elif sys.platform == "darwin":
        wanted = (".dmg", ".pkg")
    else:
        return page_url
    for suffix in wanted:
        for a in assets or []:
            name = str(a.get("name", "")).lower()
            url = a.get("browser_download_url")
            if url and name.endswith(suffix):
                return str(url)
    return page_url


def auto_check_enabled() -> bool:
    return QSettings("kherve", "KhervePDF").value(_KEY_ENABLED, "true") == "true"


def set_auto_check_enabled(on: bool) -> None:
    QSettings("kherve", "KhervePDF").setValue(
        _KEY_ENABLED, "true" if on else "false")


class UpdateChecker(QObject):
    """Fire-and-forget release check.

    Signals:
      * update_available(ReleaseInfo) — a newer release exists
      * up_to_date(str)               — latest tag is not newer
      * failed(str)                   — network/parse error

    Automatic checks only ever emit ``update_available``; the UI shows
    ``up_to_date``/``failed`` only for a manual check.
    """

    update_available = Signal(object)
    up_to_date = Signal(str)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None

    def maybe_check_automatically(self) -> bool:
        """Start a check if auto-checks are on and the last one was
        more than a day ago. Returns True if a request was started."""
        if not auto_check_enabled():
            return False
        s = QSettings("kherve", "KhervePDF")
        try:
            last = float(s.value(_KEY_LAST, 0) or 0)
        except (TypeError, ValueError):
            last = 0.0
        if time.time() - last < _AUTO_INTERVAL_S:
            return False
        self.check()
        return True

    def check(self) -> None:
        if self._reply is not None:  # one request in flight at a time
            return
        QSettings("kherve", "KhervePDF").setValue(_KEY_LAST, time.time())
        req = QNetworkRequest(QUrl(RELEASES_API))
        req.setRawHeader(b"Accept", b"application/vnd.github+json")
        req.setRawHeader(b"User-Agent", f"KhervePDF/{__version__}".encode())
        req.setTransferTimeout(15000)
        self._reply = self._nam.get(req)
        self._reply.finished.connect(self._on_finished)

    def _on_finished(self) -> None:
        reply, self._reply = self._reply, None
        if reply is None:
            return
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.failed.emit(reply.errorString())
                return
            data = json.loads(bytes(reply.readAll()).decode("utf-8"))
            tag = str(data.get("tag_name") or "")
            if not tag:
                self.failed.emit("No release tag in response")
                return
            page = str(data.get("html_url") or RELEASES_PAGE)
            if is_newer(tag):
                self.update_available.emit(ReleaseInfo(
                    tag=tag, page_url=page,
                    download_url=_pick_asset(data.get("assets", []), page),
                ))
            else:
                self.up_to_date.emit(tag)
        except Exception as e:  # malformed JSON etc. — stay silent-able
            self.failed.emit(str(e))
        finally:
            reply.deleteLater()
