"""Reading comfort: remembered reading position, night reading modes
and read-aloud (system text-to-speech with the spoken sentence
highlighted on the page)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QGraphicsRectItem

_SETTINGS = ("kherve", "KhervePDF")

# ----- reading position -----

def _pos_key(path: Path) -> str:
    h = hashlib.sha1(str(Path(path).resolve()).encode("utf-8")).hexdigest()
    return f"positions/{h[:16]}"


def save_position(path: Path, page: int, frac: float, zoom: float,
                  fit: bool) -> None:
    QSettings(*_SETTINGS).setValue(
        _pos_key(path), f"{int(page)},{frac:.4f},{zoom:.4f},{int(bool(fit))}")


def load_position(path: Path) -> Optional[dict]:
    raw = QSettings(*_SETTINGS).value(_pos_key(path), "")
    try:
        page, frac, zoom, fit = str(raw).split(",")
        return {"page": int(page), "frac": float(frac),
                "zoom": float(zoom), "fit": fit == "1"}
    except ValueError:
        return None


def remember_enabled() -> bool:
    return QSettings(*_SETTINGS).value("view/remember_position",
                                       "true") == "true"


def set_remember_enabled(on: bool) -> None:
    QSettings(*_SETTINGS).setValue("view/remember_position",
                                   "true" if on else "false")


# ----- night reading -----

NIGHT_MODES = ("Off", "Invert", "Dark (soft)", "Sepia")
_night: Optional[str] = None


def night_mode() -> str:
    global _night
    if _night is None:
        v = QSettings(*_SETTINGS).value("view/night_mode", "Off")
        _night = v if v in NIGHT_MODES else "Off"
    return _night


def set_night_mode(mode: str) -> None:
    global _night
    _night = mode if mode in NIGHT_MODES else "Off"
    QSettings(*_SETTINGS).setValue("view/night_mode", _night)


def apply_night(img: QImage, mode: Optional[str] = None) -> QImage:
    """Recolour a rendered page for night reading. Only the on-screen
    pixmap changes — the PDF, printing and exports are untouched."""
    mode = night_mode() if mode is None else mode
    if mode == "Off" or img.isNull():
        return img
    if img.format() != QImage.Format_RGB32:
        dpr = img.devicePixelRatio()
        img = img.convertToFormat(QImage.Format_RGB32)
        img.setDevicePixelRatio(dpr)
    if mode in ("Invert", "Dark (soft)"):
        img.invertPixels()
    if mode == "Invert":
        return img
    p = QPainter(img)
    if mode == "Dark (soft)":
        # Lift the black background to a dark slate and take the edge
        # off pure-white text.
        p.setCompositionMode(QPainter.CompositionMode_Lighten)
        p.fillRect(img.rect(), QColor("#22262e"))
        p.setCompositionMode(QPainter.CompositionMode_Darken)
        p.fillRect(img.rect(), QColor("#d9d6cf"))
    else:  # Sepia
        p.setCompositionMode(QPainter.CompositionMode_Multiply)
        p.fillRect(img.rect(), QColor("#f3e3c3"))
    p.end()
    return img


# ----- read aloud -----

_SENT_END = re.compile(r"[.!?]['\")\]]*$")


def split_sentences(words: list) -> list[list[int]]:
    """Group word indices into sentences: a word ending in . ! or ?
    closes one, as does a gap between blocks (headings, captions)."""
    out: list[list[int]] = []
    cur: list[int] = []
    prev_block = None
    for i, w in enumerate(words):
        if cur and prev_block is not None and w[5] != prev_block:
            out.append(cur)
            cur = []
        cur.append(i)
        prev_block = w[5]
        text = w[4]
        # "e.g." / "Fig." / initials are not sentence ends.
        if _SENT_END.search(text) and len(text.rstrip(".")) > 2 \
                and text.lower() not in ("fig.", "eq.", "ref.", "refs.",
                                         "e.g.", "i.e.", "et.", "al.",
                                         "vs.", "approx.", "no."):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _sentence_text(words: list, idx: list[int]) -> str:
    text = " ".join(words[i][4] for i in idx)
    # Re-join words hyphenated across a line break.
    return re.sub(r"(\w)- (\w)", r"\1\2", text)


def tts_available() -> bool:
    try:
        from PySide6.QtTextToSpeech import QTextToSpeech  # noqa: F401
        return True
    except Exception:
        return False


class ReadAloud(QObject):
    """Speaks a PdfTab sentence by sentence from a starting page,
    highlighting the sentence being read and following it across
    pages. One instance per window; start() replaces any running read."""

    state_changed = Signal(str)   # "speaking" | "paused" | "stopped"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtTextToSpeech import QTextToSpeech
        self._tts = QTextToSpeech(self)
        self._tts.stateChanged.connect(self._on_state)
        self._tab = None
        self._page = 0
        self._sentences: list[list[int]] = []
        self._words: list = []
        self._si = 0
        self._items: list[QGraphicsRectItem] = []
        self._active = False
        self._paused = False
        s = QSettings(*_SETTINGS)
        self.set_rate(float(s.value("read_aloud/rate", 0.0)))

    # public API
    def is_active(self) -> bool:
        return self._active

    def is_paused(self) -> bool:
        return self._paused

    def tab(self):
        return self._tab

    def rate(self) -> float:
        return self._tts.rate()

    def set_rate(self, rate: float) -> None:
        rate = max(-1.0, min(1.0, rate))
        self._tts.setRate(rate)
        QSettings(*_SETTINGS).setValue("read_aloud/rate", rate)

    def start(self, tab, page: int, from_word: int = 0) -> None:
        self.stop()
        self._tab = tab
        self._active = True
        self._paused = False
        self._load_page(page, from_word)
        self.state_changed.emit("speaking")
        self._speak_current()

    def pause(self) -> None:
        if self._active and not self._paused:
            self._paused = True
            self._tts.pause()
            self.state_changed.emit("paused")

    def resume(self) -> None:
        if self._active and self._paused:
            self._paused = False
            self._tts.resume()
            self.state_changed.emit("speaking")

    def stop(self) -> None:
        was = self._active
        self._active = False
        self._paused = False
        self._tts.stop()
        self._clear_highlight()
        self._tab = None
        if was:
            self.state_changed.emit("stopped")

    def skip(self, delta: int) -> None:
        """Jump `delta` sentences forward/back."""
        if not self._active:
            return
        self._si = max(-1, self._si + delta - 1)
        self._tts.stop()   # Ready state advances by one

    # internals
    def _load_page(self, page: int, from_word: int = 0) -> None:
        self._page = page
        self._words = self._tab._page_words(page)
        self._sentences = split_sentences(self._words)
        self._si = 0
        if from_word:
            for k, s in enumerate(self._sentences):
                if s and s[-1] >= from_word:
                    self._si = k
                    break

    def _speak_current(self) -> None:
        tab = self._tab
        if not self._active or tab is None or tab._doc is None:
            self.stop()
            return
        while self._si >= len(self._sentences):
            if self._page + 1 >= tab.page_count():
                self.stop()
                return
            self._load_page(self._page + 1)
        idx = self._sentences[self._si]
        self._highlight(idx)
        self._tts.say(_sentence_text(self._words, idx))

    def _on_state(self, state) -> None:
        from PySide6.QtTextToSpeech import QTextToSpeech
        if state == QTextToSpeech.State.Ready and self._active \
                and not self._paused:
            self._si += 1
            # Let the engine settle before queueing the next sentence.
            QTimer.singleShot(0, self._speak_current)

    def _clear_highlight(self) -> None:
        for it in self._items:
            try:
                if it.scene() is not None:
                    it.scene().removeItem(it)
            except RuntimeError:
                pass   # already deleted by a re-render
        self._items = []

    def _highlight(self, idx: list[int]) -> None:
        self._clear_highlight()
        tab = self._tab
        if self._page not in tab._page_layout:
            return
        fill = QColor("#43a047")
        fill.setAlpha(80)
        first = None
        for i in idx:
            w = self._words[i]
            tl = tab._page_to_scene(self._page, w[0], w[1])
            br = tab._page_to_scene(self._page, w[2], w[3])
            r = QGraphicsRectItem(QRectF(tl, br).normalized())
            r.setPen(QPen(Qt.NoPen))
            r.setBrush(QBrush(fill))
            r.setZValue(140)
            tab.scene().addItem(r)
            self._items.append(r)
            first = first or r
        if first is not None:
            tab.ensureVisible(first, 40, 120)
