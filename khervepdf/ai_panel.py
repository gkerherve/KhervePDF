"""AI Assistant dock — chat with an LLM about the open PDF.

The right-hand sidebar mirrors KhervePaint's AI panel (same providers,
settings dialog, Refresh button and chat UX). The KhervePDF twist is
the context: every message carries the active document's name, page
count, the current page's text and — when the Select Text tool has a
live selection — the selected passage, so "summarise this page" or
"what does the highlighted part mean?" just work.

The panel only *reads* the document; it never mutates the PDF.
"""

import json

from PySide6.QtCore import QSettings, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDockWidget, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

from . import ai_providers as providers
from .icons import icon

_SETTINGS = ("kherve", "KhervePDF")

#: How much page text goes into the system prompt. Full articles blow
#: past small local models' context windows; one page rarely does.
_MAX_PAGE_CHARS = 8000

SYSTEM_PROMPT = (
    "You are a research assistant inside KhervePDF, a PDF viewer and "
    "annotation editor. Help the user read, summarise, and understand "
    "the open document. Ground every answer in the document text you "
    "are given — quote it and mention page numbers when useful, and "
    "say plainly when the answer is not in the provided text.\n\n"
    "{context}"
)


class _Worker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as exc:              # pragma: no cover - network
            self.failed.emit(str(exc))


# ---------------------------------------------------------------- settings
class AiSettingsDialog(QDialog):
    """Provider / model / API-key settings, like the rest of the family."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Chat Settings")
        self.setMinimumWidth(440)
        self._settings = QSettings(*_SETTINGS)
        self._worker = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.provider_combo = QComboBox()
        for key in providers.PROVIDERS:
            self.provider_combo.addItem(providers.DISPLAY_NAMES[key], key)
        form.addRow("Provider:", self.provider_combo)

        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.refresh_btn = QToolButton()
        self.refresh_btn.setIcon(icon("refresh"))
        self.refresh_btn.setToolTip("Refresh the model list from the provider")
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.refresh_btn)
        form.addRow("Model:", model_row)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        form.addRow("API Key:", self.key_edit)

        self.base_label = QLabel("Base URL:")
        self.base_edit = QLineEdit()
        form.addRow(self.base_label, self.base_edit)

        self.help_box = QGroupBox("How to get an API key")
        help_layout = QVBoxLayout(self.help_box)
        self.help_label = QLabel()
        self.help_label.setWordWrap(True)
        help_layout.addWidget(self.help_label)
        layout.addWidget(self.help_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.provider_combo.currentIndexChanged.connect(self._load_provider)
        self.refresh_btn.clicked.connect(self._refresh)

        saved = self._settings.value("ai/provider", "Claude")
        idx = self.provider_combo.findData(saved)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self._load_provider()

    def _provider(self):
        return self.provider_combo.currentData()

    def _load_provider(self, *_):
        provider = self._provider()
        self.key_edit.setText(self._settings.value(f"ai/key/{provider}", ""))
        self.base_edit.setText(self._settings.value(f"ai/base/{provider}", ""))
        self.key_edit.setEnabled(provider in providers.NEEDS_KEY)
        show_base = provider in ("Local", "Ollama")
        self.base_label.setVisible(show_base)
        self.base_edit.setVisible(show_base)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(providers.DEFAULT_MODELS.get(provider, []))
        saved = self._settings.value(f"ai/model/{provider}", "")
        if saved:
            self.model_combo.setCurrentText(saved)
        self.model_combo.blockSignals(False)
        self.help_label.setText(providers.PROVIDER_HELP.get(provider, ""))

    def _refresh(self):
        provider = self._provider()
        key, base = self.key_edit.text(), self.base_edit.text()
        self.refresh_btn.setEnabled(False)
        self._worker = _Worker(
            lambda: providers.list_models(provider, key, base), self)
        self._worker.done.connect(self._models_ready)
        self._worker.failed.connect(self._refresh_failed)
        self._worker.start()

    def _models_ready(self, models):
        self.refresh_btn.setEnabled(True)
        if not models:
            QMessageBox.information(self, "AI Chat", "No models returned.")
            return
        current = self.model_combo.currentText()
        self.model_combo.clear()
        self.model_combo.addItems(models)
        self.model_combo.setCurrentText(current if current in models
                                        else models[0])

    def _refresh_failed(self, message):
        self.refresh_btn.setEnabled(True)
        QMessageBox.warning(self, "AI Chat",
                            f"Could not list models:\n{message}")

    def _accept(self):
        provider = self._provider()
        self._settings.setValue("ai/provider", provider)
        self._settings.setValue(f"ai/key/{provider}", self.key_edit.text())
        self._settings.setValue(f"ai/base/{provider}", self.base_edit.text())
        if self.model_combo.currentText():
            self._settings.setValue(f"ai/model/{provider}",
                                    self.model_combo.currentText())
        self.accept()


# ---------------------------------------------------------------- dock
class _ChatInput(QPlainTextEdit):
    """Multi-line input that submits on Enter (Shift+Enter = newline) and
    recalls previously sent prompts with Up/Down (at the first/last line)."""

    submitted = Signal()
    history_prev = Signal()
    history_next = Signal()
    image_pasted = Signal(object)            # a pasted QImage (screenshot)

    def insertFromMimeData(self, source):    # noqa: N802 — Qt override
        if source.hasImage():                # paste a screenshot, not text
            self.image_pasted.emit(source.imageData())
        else:
            super().insertFromMimeData(source)

    def keyPressEvent(self, event):          # noqa: N802 — Qt override
        if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and not event.modifiers() & Qt.ShiftModifier):
            self.submitted.emit()
            return
        cursor = self.textCursor()
        if event.key() == Qt.Key_Up and cursor.blockNumber() == 0:
            self.history_prev.emit()
            return
        if (event.key() == Qt.Key_Down
                and cursor.blockNumber() == self.document().blockCount() - 1):
            self.history_next.emit()
            return
        super().keyPressEvent(event)


class AiDock(QDockWidget):
    """The hideable AI sidebar. `mw` is the MainWindow — used to reach
    the active PdfTab for document context."""

    def __init__(self, mw, parent=None):
        super().__init__("AI Assistant", parent or mw)
        self._mw = mw
        self.setObjectName("AiAssistant")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self._worker = None
        self._is_busy = False
        self._think_dots = 0
        self._think_timer = QTimer(self)
        self._think_timer.setInterval(400)
        self._think_timer.timeout.connect(self._tick)
        self._history = []
        self._sent = []                 # past user prompts (Up/Down recall)
        self._hist_index = None
        self._draft = ""
        self._settings = QSettings(*_SETTINGS)
        self._font_pt = int(self._settings.value("ai/fontpt", 10))

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(2)
        header.addWidget(QLabel("<b>AI Assistant</b>"))
        self.provider_label = QLabel()
        self.provider_label.setStyleSheet("color:#888;")
        header.addWidget(self.provider_label, 1)
        self.smaller_btn = self._tool("A−", "Smaller text",
                                      lambda: self._change_font(-1))
        self.larger_btn = self._tool("A+", "Larger text",
                                     lambda: self._change_font(1))
        self.help_btn = self._tool(None, "Help", self._show_help, "help")
        self.settings_btn = self._tool(None, "AI Chat settings",
                                       self._open_settings, "settings")
        self.clear_btn = self._tool(None, "Clear chat", self._clear,
                                    "clear_chat")
        # Same in-place hide affordance as the Pages panel: a chevron
        # that hides the dock; the toolbar/View-menu toggle re-shows it.
        self.hide_btn = self._tool(None, "Hide AI panel (re-open from the "
                                   "toolbar or View menu)",
                                   self.hide, "hide_panel_r")
        for btn in (self.smaller_btn, self.larger_btn, self.help_btn,
                    self.settings_btn, self.clear_btn, self.hide_btn):
            header.addWidget(btn)
        layout.addLayout(header)

        self.transcript = QTextBrowser()
        self.transcript.setOpenExternalLinks(True)
        layout.addWidget(self.transcript, 1)

        self.thinking_label = QLabel()
        self.thinking_label.setStyleSheet("color:#2e7d4f; font-style:italic;")
        self.thinking_label.setVisible(False)
        layout.addWidget(self.thinking_label)

        # Pasted-screenshot attachment row (hidden until an image is pasted).
        self._pending_image = None
        self.attach_row = QWidget()
        attach = QHBoxLayout(self.attach_row)
        attach.setContentsMargins(0, 0, 0, 0)
        self.attach_thumb = QLabel()
        self.attach_label = QLabel("Image attached")
        self.attach_label.setStyleSheet("color:#888;")
        remove = self._tool(None, "Remove image", self._clear_image,
                            "close_x")
        attach.addWidget(self.attach_thumb)
        attach.addWidget(self.attach_label, 1)
        attach.addWidget(remove)
        self.attach_row.setVisible(False)
        layout.addWidget(self.attach_row)

        input_row = QHBoxLayout()
        self.input = _ChatInput()
        self.input.setPlaceholderText(
            "Ask about this PDF… (paste a screenshot with Ctrl+V)")
        self.input.setFixedHeight(70)
        self.send_btn = self._tool(None, "Send", self._send_or_stop, "send")
        self.send_btn.setIconSize(QSize(24, 24))
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.send_btn, 0, Qt.AlignBottom)
        layout.addLayout(input_row)

        self.setWidget(body)

        self.input.submitted.connect(self._send)
        self.input.history_prev.connect(self._history_prev)
        self.input.history_next.connect(self._history_next)
        self.input.image_pasted.connect(self._attach_image)

        self._apply_font()
        self._update_status()
        self._load_history()

    def _tool(self, text, tip, slot, glyph=None):
        btn = QToolButton()
        if glyph:
            btn.setIcon(icon(glyph))
        if text:
            btn.setText(text)
        btn.setToolTip(tip)
        btn.setAutoRaise(True)
        btn.clicked.connect(slot)
        return btn

    # ------------------------------------------------------- pdf context
    def _document_context(self) -> str:
        """The grounding text for the system prompt: document name and
        size, the current page's text, and any live Select-Text
        selection on the active tab."""
        tab = self._mw._current_pdf_tab()
        if tab is None or tab._doc is None:
            return "No document is open yet."
        doc = tab._doc
        page_idx = max(0, min(tab.current_page_index(), len(doc) - 1))
        parts = [f"Open document: \"{tab.path.name}\" "
                 f"({len(doc)} page{'s' if len(doc) != 1 else ''}). "
                 f"The user is looking at page {page_idx + 1}."]
        sel = getattr(tab, "_text_sel_text", "")
        if sel:
            parts.append("The user has selected this passage:\n---\n"
                         f"{sel[:_MAX_PAGE_CHARS]}\n---")
        try:
            page_text = doc[page_idx].get_text().strip()
        except Exception:
            page_text = ""
        if page_text:
            clipped = page_text[:_MAX_PAGE_CHARS]
            suffix = " …[truncated]" if len(page_text) > len(clipped) else ""
            parts.append(f"Text of page {page_idx + 1}:\n---\n"
                         f"{clipped}{suffix}\n---")
        else:
            parts.append(f"Page {page_idx + 1} has no extractable text "
                         "(it may be a scanned image).")
        return "\n\n".join(parts)

    # ------------------------------------------------------- image attach
    def _attach_image(self, image):
        """Hold a pasted screenshot to send with the next message."""
        if image is None or image.isNull():
            return
        self._pending_image = image
        self.attach_thumb.setPixmap(QPixmap.fromImage(image).scaledToHeight(
            36, Qt.SmoothTransformation))
        self.attach_label.setText(f"Screenshot attached "
                                  f"({image.width()}×{image.height()})")
        self.attach_row.setVisible(True)

    def _clear_image(self):
        self._pending_image = None
        self.attach_thumb.clear()
        self.attach_row.setVisible(False)

    @staticmethod
    def _image_to_b64(image) -> str:
        import base64
        from PySide6.QtCore import QBuffer, QByteArray
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QBuffer.WriteOnly)
        image.save(buf, "PNG")
        buf.close()
        return base64.b64encode(bytes(data.data())).decode("ascii")

    # ------------------------------------------------------- settings
    def _open_settings(self):
        if AiSettingsDialog(self).exec():
            self._update_status()

    def _update_status(self):
        provider = self._settings.value("ai/provider", "Claude")
        self.provider_label.setText(
            providers.DISPLAY_NAMES.get(provider, provider))

    def _change_font(self, delta):
        self._font_pt = max(7, min(28, self._font_pt + delta))
        self._settings.setValue("ai/fontpt", self._font_pt)
        self._apply_font()

    def _apply_font(self):
        for widget in (self.transcript, self.input):
            font = widget.font()
            font.setPointSize(self._font_pt)
            widget.setFont(font)

    # ------------------------------------------------------- persistence
    def _save_history(self):
        # keep the last 100 turns so the store stays small
        self._settings.setValue("ai/history",
                                json.dumps(self._history[-100:]))
        self._settings.sync()           # flush now so a hard close keeps it

    def _load_history(self):
        raw = self._settings.value("ai/history", "")
        try:
            self._history = json.loads(raw) if raw else []
        except (ValueError, TypeError):
            self._history = []
        self._sent = [m["content"] for m in self._history
                      if m.get("role") == "user"]
        if self._history:
            for msg in self._history:
                if msg.get("role") == "user":
                    self._log("you", msg.get("content", ""))
                elif msg.get("role") == "assistant":
                    self._log("ai", msg.get("content", ""))
        else:
            self._welcome()

    def _welcome(self):
        self._log("system",
                  "Hello! Ask me about the open PDF — summarise a page, "
                  "explain a passage (select it with the Select Text tool "
                  "first), or find where something is discussed. Set your "
                  "provider (Anthropic, OpenAI, Mistral, Ollama or Local) "
                  "and API key via the gear icon.")

    def _show_help(self):
        self._log("system",
                  "Every message includes the current page's text and any "
                  "Select-Text selection, so \"summarise this page\" or "
                  "\"explain the selected part\" just work. A−/A+ resize "
                  "this text; the gear sets the provider/model/key (its "
                  "refresh button lists the provider's live models); the "
                  "bin clears the chat.")

    def _clear(self):
        self.transcript.clear()
        self._history = []
        self._sent = []
        self._hist_index = None
        self._draft = ""
        self._save_history()
        self._welcome()

    # ------------------------------------------------------- transcript
    def _log(self, role, text):
        colours = {"you": "#2176c7", "ai": "#2e7d4f",
                   "system": "#888", "error": "#c0392b"}
        who = {"you": "You", "ai": "Assistant", "system": "",
               "error": "Error"}.get(role, role)
        prefix = f"<b style='color:{colours.get(role, '#000')}'>{who}:</b> " \
            if who else ""
        safe = (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace("\n", "<br>"))
        self.transcript.append(
            f"<div style='margin:4px 0;'>{prefix}{safe}</div>")

    def _busy(self, busy):
        self._is_busy = busy
        if busy:
            self._think_dots = 0
            self.thinking_label.setText("Assistant is thinking")
            self.thinking_label.setVisible(True)
            self._think_timer.start()
            self.send_btn.setIcon(icon("stop"))
            self.send_btn.setToolTip("Stop")
        else:
            self._think_timer.stop()
            self.thinking_label.setVisible(False)
            self.send_btn.setIcon(icon("send"))
            self.send_btn.setToolTip("Send")

    def _tick(self):
        self._think_dots = (self._think_dots + 1) % 4
        self.thinking_label.setText("Assistant is thinking"
                                    + "." * self._think_dots)

    def _send_or_stop(self):
        self._stop() if self._is_busy else self._send()

    def _stop(self):
        """Abandon the in-flight request (its late result is ignored)."""
        if self._worker is not None:
            for sig in (self._worker.done, self._worker.failed):
                try:
                    sig.disconnect()
                except (TypeError, RuntimeError):
                    pass
            self._worker = None
        self._busy(False)
        self._log("system", "Stopped.")

    # ------------------------------------------------------- history
    def _history_prev(self):
        if not self._sent:
            return
        if self._hist_index is None:
            self._draft = self.input.toPlainText()
            self._hist_index = len(self._sent) - 1
        elif self._hist_index > 0:
            self._hist_index -= 1
        self._set_input(self._sent[self._hist_index])

    def _history_next(self):
        if self._hist_index is None:
            return
        if self._hist_index < len(self._sent) - 1:
            self._hist_index += 1
            self._set_input(self._sent[self._hist_index])
        else:
            self._hist_index = None
            self._set_input(self._draft)

    def _set_input(self, text):
        self.input.setPlainText(text)
        cursor = self.input.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.input.setTextCursor(cursor)

    # ------------------------------------------------------- actions
    def _send(self):
        if self._is_busy:
            return
        text = self.input.toPlainText().strip()
        if not text and self._pending_image is None:
            return
        provider = self._settings.value("ai/provider", "Claude")
        model = self._settings.value(f"ai/model/{provider}", "")
        key = self._settings.value(f"ai/key/{provider}", "")
        base = self._settings.value(f"ai/base/{provider}", "")
        if not model:
            self._log("error", "Open Settings and choose a model first.")
            return
        if provider in providers.NEEDS_KEY and not key.strip():
            self._log("error", "Set your API key for this provider in "
                               "Settings (the gear icon).")
            return
        # A pasted screenshot is sent with THIS message only (not stored
        # in history, which stays text). Clear the attachment once used.
        image_b64 = None
        if self._pending_image is not None:
            image_b64 = self._image_to_b64(self._pending_image)
            self._clear_image()

        self.input.clear()
        self._sent.append(text)
        self._hist_index = None
        self._draft = ""
        self._log("you", text + ("  🖼 [screenshot]" if image_b64 else ""))
        self._history.append({"role": "user", "content": text or "(image)"})
        self._save_history()

        system = SYSTEM_PROMPT.replace("{context}", self._document_context())
        messages = [{"role": "system", "content": system}] + self._history
        self._busy(True)
        self._run(lambda: providers.chat(provider, model, messages, key,
                                         base, image=image_b64),
                  self._reply_ready)

    def _reply_ready(self, reply):
        self._busy(False)
        self._history.append({"role": "assistant", "content": reply})
        self._save_history()
        self._log("ai", reply)

    # ------------------------------------------------------- threading
    def _run(self, fn, on_done):
        worker = _Worker(fn, self)
        worker.done.connect(on_done)
        worker.failed.connect(self._on_error)
        worker.finished.connect(lambda: self._clear_worker(worker))
        self._worker = worker
        worker.start()

    def _on_error(self, message):
        self._busy(False)
        self._log("error", message)

    def _clear_worker(self, worker):
        if self._worker is worker:
            self._worker = None
