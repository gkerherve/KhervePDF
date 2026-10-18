"""Menu actions and dialogs for the reading, reference and document-
preparation features, mixed into MainWindow so mainwindow.py stays
about the window itself:

* File → Document Properties…, Compare with Another PDF…
* View → Night Reading, Remember Reading Position, Read Aloud
* Tools → Fill In Form…, Import All References to KherveRef,
  Ask AI About an Area…
* Pages → Crop Pages…, Add Stamp…, Number / Bates every page…,
  Edit Outline…
* Git → History… → Compare with current (compare_with_commit)
"""
from __future__ import annotations

import datetime
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

import fitz
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import doc_tools, git_backend, kherveref_link, reading
from .icons import icon


def _buttons(dlg: QDialog, ok_text: str = "OK") -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                          parent=dlg)
    bb.button(QDialogButtonBox.Ok).setText(ok_text)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


# ---------------------------------------------------------------- dialogs

class PropertiesDialog(QDialog):
    def __init__(self, parent, doc: fitz.Document, name: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Document properties — {name}")
        self.resize(520, 0)
        fl = QFormLayout(self)
        self._edits: dict[str, QLineEdit] = {}
        props = doc_tools.get_properties(doc)
        for key in doc_tools.META_KEYS:
            le = QLineEdit(props[key], self)
            if key == "keywords":
                le.setPlaceholderText("comma-separated")
            fl.addRow(key.capitalize() + ":", le)
            self._edits[key] = le
        info = doc.metadata or {}
        extra = (f"{doc.page_count} page(s) · PDF "
                 f"{info.get('format', '').replace('PDF ', '')}"
                 f" · created {info.get('creationDate', '') or '—'}")
        fl.addRow(QLabel(f"<span style='color:#888'>{extra}</span>"))
        fl.addRow(_buttons(self, "Apply"))

    def values(self) -> dict[str, str]:
        return {k: le.text().strip() for k, le in self._edits.items()}


class CropDialog(QDialog):
    def __init__(self, parent, page_count: int, current: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("Crop pages")
        v = QVBoxLayout(self)
        self.auto = QRadioButton("Trim each page to its content "
                                 "(removes blank margins and scan borders)")
        self.manual = QRadioButton("Trim fixed margins:")
        self.reset = QRadioButton("Remove cropping (restore full pages)")
        self.auto.setChecked(True)
        v.addWidget(self.auto)
        v.addWidget(self.manual)
        grid = QHBoxLayout()
        self.margins = []
        for label in ("Left", "Top", "Right", "Bottom"):
            sb = QDoubleSpinBox(self)
            sb.setRange(0, 500)
            sb.setSuffix(" mm")
            sb.setValue(10)
            sb.setEnabled(False)
            grid.addWidget(QLabel(label))
            grid.addWidget(sb)
            self.margins.append(sb)
        v.addLayout(grid)
        self.manual.toggled.connect(
            lambda on: [sb.setEnabled(on) for sb in self.margins])
        v.addWidget(self.reset)
        fl = QFormLayout()
        self.scope = QComboBox(self)
        self.scope.addItems(["All pages", f"Current page ({current + 1})",
                             "Page range…"])
        self.range = QLineEdit(self)
        self.range.setPlaceholderText(f"e.g. 1-3, 5 (of {page_count})")
        self.range.setEnabled(False)
        self.scope.currentIndexChanged.connect(
            lambda i: self.range.setEnabled(i == 2))
        fl.addRow("Apply to:", self.scope)
        fl.addRow("Pages:", self.range)
        v.addLayout(fl)
        v.addWidget(_buttons(self, "Crop"))

    def margins_pt(self) -> tuple[float, float, float, float]:
        return tuple(sb.value() * 72 / 25.4 for sb in self.margins)


class StampDialog(QDialog):
    def __init__(self, parent, current: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add stamp")
        fl = QFormLayout(self)
        self.text = QComboBox(self)
        self.text.setEditable(True)
        self.text.addItems(list(doc_tools.STAMPS))
        fl.addRow("Stamp:", self.text)
        self.position = QComboBox(self)
        self.position.addItems(list(doc_tools.STAMP_POSITIONS))
        fl.addRow("Position:", self.position)
        self.size = QSpinBox(self)
        self.size.setRange(8, 72)
        self.size.setValue(22)
        self.size.setSuffix(" pt")
        fl.addRow("Size:", self.size)
        self.date = QCheckBox("Add today's date", self)
        self.date.setChecked(True)
        fl.addRow(self.date)
        self.scope = QComboBox(self)
        self.scope.addItems([f"Current page ({current + 1})", "First page",
                             "All pages"])
        fl.addRow("Apply to:", self.scope)
        fl.addRow(_buttons(self, "Stamp"))

    def color(self) -> tuple[float, float, float]:
        return doc_tools.STAMPS.get(self.text.currentText().strip().upper(),
                                    (0.78, 0.16, 0.16))


class NumberingDialog(QDialog):
    STYLES = ("n / total", "Page n of total", "n", "bates")

    def __init__(self, parent, page_count: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("Number every page")
        self._total = page_count
        fl = QFormLayout(self)
        self.style = QComboBox(self)
        self.style.addItems(["1 / N", "Page 1 of N", "1",
                             "Bates (prefix + 000001)"])
        fl.addRow("Style:", self.style)
        self.prefix = QLineEdit(self)
        self.prefix.setPlaceholderText("e.g. ABC-  (optional)")
        fl.addRow("Prefix:", self.prefix)
        self.start = QSpinBox(self)
        self.start.setRange(0, 9_999_999)
        self.start.setValue(1)
        fl.addRow("Start at:", self.start)
        self.digits = QSpinBox(self)
        self.digits.setRange(1, 12)
        self.digits.setValue(6)
        fl.addRow("Bates digits:", self.digits)
        self.position = QComboBox(self)
        self.position.addItems(["bottom-center", "bottom-right",
                                "bottom-left", "top-center", "top-right",
                                "top-left"])
        fl.addRow("Position:", self.position)
        self.size = QSpinBox(self)
        self.size.setRange(6, 36)
        self.size.setValue(10)
        self.size.setSuffix(" pt")
        fl.addRow("Size:", self.size)
        self.preview = QLabel(self)
        fl.addRow("Preview:", self.preview)
        for w in (self.style, self.position):
            w.currentIndexChanged.connect(self._update)
        self.prefix.textChanged.connect(self._update)
        self.start.valueChanged.connect(self._update)
        self.digits.valueChanged.connect(self._update)
        fl.addRow(_buttons(self, "Number"))
        self._update()

    def style_key(self) -> str:
        return self.STYLES[self.style.currentIndex()]

    def _update(self, *_a) -> None:
        bates = self.style_key() == "bates"
        self.digits.setEnabled(bates)
        if bates and self.position.currentText() == "bottom-center":
            self.position.setCurrentText("bottom-right")
        first = doc_tools.page_label(0, self._total, self.style_key(),
                                     self.prefix.text(), self.start.value(),
                                     self.digits.value())
        last = doc_tools.page_label(self._total - 1, self._total,
                                    self.style_key(), self.prefix.text(),
                                    self.start.value(), self.digits.value())
        self.preview.setText(f"<code>{first}</code> … <code>{last}</code>")


class OutlineEditor(QDialog):
    """Edit the bookmark tree: add (at the current page), rename by
    double-click, drag to reorder or nest, indent/outdent, delete."""

    def __init__(self, parent, toc: list[list], page_count: int,
                 current: int, detected: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit outline (bookmarks)")
        self.resize(560, 560)
        self._pages = page_count
        self._current = current
        v = QVBoxLayout(self)
        if detected:
            v.addWidget(QLabel("This PDF has no saved outline — starting "
                               "from the headings KhervePDF detected."))
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["Title", "Page"])
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setEditTriggers(QAbstractItemView.DoubleClicked
                                  | QAbstractItemView.EditKeyPressed)
        v.addWidget(self.tree, 1)
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for lvl, title, page, *_ in toc:
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            parent_item = stack[-1][1] if stack else self.tree.invisibleRootItem()
            it = self._make_item(title, page)
            parent_item.addChild(it)
            stack.append((lvl, it))
        self.tree.expandAll()

        row = QHBoxLayout()
        for text, slot in (("Add at current page", self._add),
                           ("Add child", lambda: self._add(child=True)),
                           ("Indent →", self._indent),
                           ("← Outdent", self._outdent),
                           ("Set to current page", self._set_page),
                           ("Delete", self._delete)):
            b = QPushButton(text, self)
            b.clicked.connect(slot)
            row.addWidget(b)
        v.addLayout(row)
        v.addWidget(QLabel("<span style='color:#888'>Double-click a title "
                           "or page number to edit it; drag rows to "
                           "reorder or nest them.</span>"))
        v.addWidget(_buttons(self, "Save outline"))

    def _make_item(self, title: str, page: int) -> QTreeWidgetItem:
        it = QTreeWidgetItem([str(title), str(int(page))])
        it.setFlags(it.flags() | Qt.ItemIsEditable | Qt.ItemIsDragEnabled
                    | Qt.ItemIsDropEnabled)
        return it

    def _add(self, child: bool = False) -> None:
        it = self._make_item("New bookmark", self._current + 1)
        cur = self.tree.currentItem()
        if child and cur is not None:
            cur.addChild(it)
            cur.setExpanded(True)
        elif cur is not None and cur.parent() is not None:
            cur.parent().insertChild(cur.parent().indexOfChild(cur) + 1, it)
        elif cur is not None:
            self.tree.insertTopLevelItem(
                self.tree.indexOfTopLevelItem(cur) + 1, it)
        else:
            self.tree.addTopLevelItem(it)
        self.tree.setCurrentItem(it)
        self.tree.editItem(it, 0)

    def _take(self, it: QTreeWidgetItem) -> None:
        p = it.parent()
        if p is not None:
            p.removeChild(it)
        else:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(it))

    def _indent(self) -> None:
        it = self.tree.currentItem()
        if it is None:
            return
        p = it.parent() or self.tree.invisibleRootItem()
        i = p.indexOfChild(it)
        if i <= 0:
            return
        new_parent = p.child(i - 1)
        p.removeChild(it)
        new_parent.addChild(it)
        new_parent.setExpanded(True)
        self.tree.setCurrentItem(it)

    def _outdent(self) -> None:
        it = self.tree.currentItem()
        if it is None or it.parent() is None:
            return
        p = it.parent()
        gp = p.parent() or self.tree.invisibleRootItem()
        p.removeChild(it)
        gp.insertChild(gp.indexOfChild(p) + 1, it)
        self.tree.setCurrentItem(it)

    def _set_page(self) -> None:
        it = self.tree.currentItem()
        if it is not None:
            it.setText(1, str(self._current + 1))

    def _delete(self) -> None:
        it = self.tree.currentItem()
        if it is not None:
            self._take(it)

    def toc(self) -> list[list]:
        out: list[list] = []

        def walk(item: QTreeWidgetItem, level: int) -> None:
            for i in range(item.childCount()):
                c = item.child(i)
                try:
                    page = int(c.text(1))
                except ValueError:
                    page = 1
                page = max(1, min(page, self._pages))
                title = c.text(0).strip() or "Untitled"
                out.append([level, title, page])
                walk(c, level + 1)
        walk(self.tree.invisibleRootItem(), 1)
        return out


class FormDialog(QDialog):
    """Every form field in one table; edit values, optionally flatten."""

    def __init__(self, parent, fields: list[dict]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Fill in form")
        self.resize(640, 480)
        self._fields = fields
        v = QVBoxLayout(self)
        self.table = QTableWidget(len(fields), 3, self)
        self.table.setHorizontalHeaderLabels(["Field", "Page", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self._editors: list[QWidget] = []
        for r, f in enumerate(fields):
            name = QTableWidgetItem(f["name"] or f"({f['type']})")
            name.setFlags(name.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 0, name)
            pg = QTableWidgetItem(str(f["page"] + 1))
            pg.setFlags(pg.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 1, pg)
            if f["on_state"] is not None:
                ed = QCheckBox(self)
                ed.setChecked(f["value"] not in (None, "", "Off", False))
            elif f["options"]:
                ed = QComboBox(self)
                ed.setEditable(f["type"] == "ComboBox")
                ed.addItems([str(o if not isinstance(o, (list, tuple))
                                 else o[-1]) for o in f["options"]])
                ed.setCurrentText(str(f["value"] or ""))
            else:
                ed = QLineEdit(str(f["value"] or ""), self)
            self.table.setCellWidget(r, 2, ed)
            self._editors.append(ed)
        v.addWidget(self.table, 1)
        self.flatten = QCheckBox("Flatten after filling (burn the values "
                                 "into the page; fields can no longer be "
                                 "edited)", self)
        v.addWidget(self.flatten)
        v.addWidget(_buttons(self, "Apply"))

    def values(self) -> list:
        out = []
        for ed in self._editors:
            if isinstance(ed, QCheckBox):
                out.append(ed.isChecked())
            elif isinstance(ed, QComboBox):
                out.append(ed.currentText())
            else:
                out.append(ed.text())
        return out


class _BibFetcher(QThread):
    """Fetch BibTeX for DOIs from doi.org (content negotiation)."""
    progress = Signal(int, int)
    finished_bib = Signal(str, int)

    def __init__(self, dois: list[str], refs_text: dict[str, str],
                 parent=None) -> None:
        super().__init__(parent)
        self._dois = dois
        self._refs_text = refs_text
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        entries, fetched = [], 0
        for i, doi in enumerate(self._dois):
            if self._cancel:
                break
            self.progress.emit(i, len(self._dois))
            bib = ""
            try:
                req = urllib.request.Request(
                    "https://doi.org/" + urllib.request.quote(doi, safe="/"),
                    headers={"Accept": "application/x-bibtex; charset=utf-8",
                             "User-Agent": "KhervePDF"})
                with urllib.request.urlopen(req, timeout=12) as resp:
                    bib = resp.read().decode("utf-8", "replace").strip()
            except Exception:
                bib = ""
            if bib.startswith("@"):
                fetched += 1
            else:
                # Offline / unknown DOI: keep the DOI (KherveRef can
                # refresh it later) and the reference text as a title.
                note = self._refs_text.get(doi.lower(), "")
                title = note.replace("{", "(").replace("}", ")")[:300]
                bib = (f"@misc{{doi{i + 1},\n  doi = {{{doi}}},\n"
                       + (f"  title = {{{title}}},\n" if title else "")
                       + "}")
            entries.append(bib)
        self.progress.emit(len(self._dois), len(self._dois))
        self.finished_bib.emit("\n\n".join(entries), fetched)


# ----------------------------------------------------------------- mixin

class FeatureMixin:
    """Feature actions for MainWindow (expects its _current_pdf_tab,
    _refresh_thumbs, statusBar, _ai_dock, _tabs)."""

    # ----- menus -----

    def _menu(self, title: str) -> Optional[QMenu]:
        menu = getattr(self, "_top_menus", {}).get(title)
        if menu is not None:
            return menu
        for act in self.menuBar().actions():
            if act.text().replace("&", "") == title:
                return act.menu()
        return None

    @staticmethod
    def _before(menu: QMenu, text: str):
        for act in menu.actions():
            if act.text().replace("&", "").split("\t")[0] == text:
                return act
        return None

    def _build_feature_menus(self) -> None:
        self._read_aloud: Optional[reading.ReadAloud] = None

        m_file = self._menu("File")
        anchor = self._before(m_file, "Print…")
        acts = [
            QAction(icon("about"), "Document &Properties…", self,
                    triggered=self._edit_properties),
            QAction(icon("history"), "Compare &with Another PDF…", self,
                    triggered=self._compare_with_file),
        ]
        for a in acts:
            m_file.insertAction(anchor, a)
        m_file.insertSeparator(anchor)

        m_view = self._menu("View")
        anchor = self._before(m_view, "Theme")
        night = QMenu("&Night Reading", self)
        group = QActionGroup(self)
        group.setExclusive(True)
        self._night_actions = {}
        for mode in reading.NIGHT_MODES:
            a = QAction(mode, self, checkable=True)
            a.setChecked(mode == reading.night_mode())
            a.triggered.connect(lambda _c, m=mode: self._set_night_mode(m))
            group.addAction(a)
            night.addAction(a)
            self._night_actions[mode] = a
        night.addSeparator()
        toggle = QAction("Toggle Night Reading", self, shortcut="Ctrl+Shift+N",
                         triggered=self._toggle_night)
        night.addAction(toggle)
        m_view.insertMenu(anchor, night)
        remember = QAction("&Remember Reading Position", self, checkable=True)
        remember.setChecked(reading.remember_enabled())
        remember.toggled.connect(reading.set_remember_enabled)
        m_view.insertAction(anchor, remember)
        m_view.insertMenu(anchor, self._build_read_aloud_menu())
        m_view.insertSeparator(anchor)

        m_tools = self._menu("Tools")
        anchor = self._before(m_tools, "Add to KherveRef")
        acts = [
            QAction(icon("kherveref"), "&Import All References to KherveRef…",
                    self, triggered=self._import_all_references),
            QAction("Copy All &DOIs", self, triggered=self._copy_dois),
        ]
        for a in acts:
            m_tools.insertAction(anchor, a)
        m_tools.insertSeparator(anchor)
        m_tools.addSeparator()
        m_tools.addAction(QAction("Fill In &Form…", self,
                                  triggered=self._fill_form))
        m_tools.addAction(QAction(icon("ai"), "Ask AI About an &Area…", self,
                                  shortcut="Ctrl+Shift+A",
                                  triggered=lambda: self._tab_call(
                                      "start_ai_region")))

        m_pages = self._menu("Pages")
        m_pages.addSeparator()
        m_pages.addAction(QAction(icon("page_split"), "&Crop Pages…", self,
                                  triggered=self._crop_pages))
        m_pages.addAction(QAction(icon("signature"), "Add &Stamp…", self,
                                  triggered=self._add_stamp))
        m_pages.addAction(QAction(icon("thumbs"), "Edit &Outline…", self,
                                  triggered=self._edit_outline))

    def _build_read_aloud_menu(self) -> QMenu:
        m = QMenu("Read &Aloud", self)
        ok = reading.tts_available()
        self._act_read = QAction("Read Aloud from This Page", self,
                                 shortcut="Ctrl+Shift+R",
                                 triggered=self._read_aloud_start)
        self._act_read_pause = QAction("Pause / Resume", self,
                                       shortcut="Ctrl+Shift+Space",
                                       triggered=self._read_aloud_pause)
        self._act_read_stop = QAction("Stop Reading", self,
                                      triggered=self._read_aloud_stop)
        prev_s = QAction("Previous Sentence", self,
                         triggered=lambda: self._read_aloud_skip(-1))
        next_s = QAction("Next Sentence", self,
                         triggered=lambda: self._read_aloud_skip(1))
        for a in (self._act_read, self._act_read_pause, self._act_read_stop,
                  prev_s, next_s):
            a.setEnabled(ok)
            m.addAction(a)
        m.addSeparator()
        speed = m.addMenu("Speed")
        group = QActionGroup(self)
        for label, rate in (("Slow", -0.4), ("Normal", 0.0),
                            ("Fast", 0.3), ("Very fast", 0.6)):
            a = QAction(label, self, checkable=True)
            a.triggered.connect(lambda _c, r=rate: self._read_aloud_rate(r))
            group.addAction(a)
            speed.addAction(a)
        speed.setEnabled(ok)
        if not ok:
            m.addAction(QAction("(Text-to-speech is not available)", self,
                                enabled=False))
        return m

    # ----- reading position -----

    def _save_position(self, tab) -> None:
        if tab is None or getattr(tab, "_doc", None) is None:
            return
        if not reading.remember_enabled():
            return
        page, frac = tab.reading_position()
        reading.save_position(tab.path, page, frac, tab._zoom,
                              tab._auto_fit_width)

    def _restore_position(self, tab) -> None:
        if not reading.remember_enabled():
            return
        pos = reading.load_position(tab.path)
        if not pos or (pos["page"] == 0 and pos["frac"] < 0.01
                       and pos["fit"]):
            return
        if pos["page"] >= tab.page_count():
            return
        # After the fit-width pass that showEvent queues.
        QTimer.singleShot(80, lambda: self._apply_position(tab, pos))

    def _apply_position(self, tab, pos) -> None:
        try:
            tab.restore_position(pos)
        except RuntimeError:
            return  # tab closed meanwhile
        self.statusBar().showMessage(
            f"Back where you left off — page {pos['page'] + 1}", 4000)

    def _save_all_positions(self) -> None:
        for i in range(self._tabs.count()):
            self._save_position(self._tabs.widget(i))

    # ----- night reading -----

    def _set_night_mode(self, mode: str) -> None:
        reading.set_night_mode(mode)
        if mode != "Off":
            self._last_night = mode
        act = self._night_actions.get(mode)
        if act is not None:
            act.setChecked(True)
        if hasattr(self, "_act_night_tb"):
            self._act_night_tb.setChecked(mode != "Off")
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if hasattr(tab, "_render_all"):
                pos = tab.reading_position()
                tab._render_all()
                tab.restore_position({"page": pos[0], "frac": pos[1],
                                      "fit": True})

    def _toggle_night(self) -> None:
        if reading.night_mode() == "Off":
            self._set_night_mode(getattr(self, "_last_night", "Dark (soft)"))
        else:
            self._set_night_mode("Off")

    # ----- read aloud -----

    def _read_aloud_obj(self) -> Optional[reading.ReadAloud]:
        if self._read_aloud is None and reading.tts_available():
            self._read_aloud = reading.ReadAloud(self)
            self._read_aloud.state_changed.connect(self._on_read_state)
        return self._read_aloud

    def _read_aloud_start(self) -> None:
        tab = self._current_pdf_tab()
        ra = self._read_aloud_obj()
        if tab is None or ra is None:
            return
        page = tab.current_page_index()
        from_word = 0
        if tab._text_sel_range is not None:
            page, from_word, _hi = tab._text_sel_range
        ra.start(tab, page, from_word)

    def _toggle_read_aloud(self) -> None:
        ra = self._read_aloud
        if ra is not None and ra.is_active():
            ra.stop()
        else:
            self._read_aloud_start()
        self._sync_read_button()

    def _sync_read_button(self) -> None:
        if hasattr(self, "_act_read_tb"):
            ra = self._read_aloud
            self._act_read_tb.setChecked(bool(ra and ra.is_active()))

    def _read_aloud_pause(self) -> None:
        ra = self._read_aloud
        if ra is None or not ra.is_active():
            self._read_aloud_start()
        elif ra.is_paused():
            ra.resume()
        else:
            ra.pause()

    def _read_aloud_stop(self) -> None:
        if self._read_aloud is not None:
            self._read_aloud.stop()

    def _read_aloud_skip(self, delta: int) -> None:
        if self._read_aloud is not None:
            self._read_aloud.skip(delta)

    def _read_aloud_rate(self, rate: float) -> None:
        ra = self._read_aloud_obj()
        if ra is not None:
            ra.set_rate(rate)

    def _on_read_state(self, state: str) -> None:
        msg = {"speaking": "Reading aloud — Ctrl+Shift+Space pauses",
               "paused": "Reading paused", "stopped": "Stopped reading"}
        self._sync_read_button()
        self.statusBar().showMessage(msg.get(state, ""), 4000)

    def _stop_reading_if(self, tab) -> None:
        ra = self._read_aloud
        if ra is not None and ra.tab() is tab:
            ra.stop()

    # ----- AI -----

    def ask_ai_about_region(self, img, page_idx: int, text: str) -> None:
        prompt = (f"Explain this area of page {page_idx + 1} (a figure, "
                  "table, equation or passage — see the attached image).")
        if text:
            prompt += ("\n\nText found in the area:\n" + text[:3000])
        self._ai_dock.ask(prompt, image=img)

    # ----- document properties -----

    def _doc_tab(self):
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            QMessageBox.information(self, "KhervePDF", "Open a PDF first.")
            return None
        return t

    def _edit_properties(self) -> None:
        t = self._doc_tab()
        if t is None:
            return
        dlg = PropertiesDialog(self, t._doc, t.path.name)
        if dlg.exec() != QDialog.Accepted:
            return
        t._push_undo(include_doc=True)
        doc_tools.set_properties(t._doc, dlg.values())
        self.statusBar().showMessage(
            "Properties updated — save to keep them", 4000)

    # ----- crop -----

    def _crop_pages(self) -> None:
        t = self._doc_tab()
        if t is None:
            return
        cur = t.current_page_index()
        dlg = CropDialog(self, t.page_count(), cur)
        if dlg.exec() != QDialog.Accepted:
            return
        scope = dlg.scope.currentIndex()
        if scope == 0:
            pages = list(range(t.page_count()))
        elif scope == 1:
            pages = [cur]
        else:
            pages = self._parse_page_range(dlg.range.text(), t.page_count())
            if not pages:
                QMessageBox.warning(self, "Crop pages",
                                    "No valid pages in that range.")
                return
        t._push_undo(include_doc=True)
        if dlg.reset.isChecked():
            doc_tools.reset_crop(t._doc, pages)
            n = len(pages)
        else:
            n = doc_tools.crop_pages(
                t._doc, pages,
                None if dlg.auto.isChecked() else dlg.margins_pt())
        t._text_words_cache.clear()
        t._render_all()
        self._refresh_thumbs()
        self.statusBar().showMessage(f"Cropped {n} page(s)", 4000)

    # ----- stamp -----

    def _add_stamp(self) -> None:
        t = self._doc_tab()
        if t is None:
            return
        cur = t.current_page_index()
        dlg = StampDialog(self, cur)
        if dlg.exec() != QDialog.Accepted:
            return
        text = dlg.text.currentText().strip()
        if not text:
            return
        pages = {0: [cur], 1: [0]}.get(dlg.scope.currentIndex(),
                                       list(range(t.page_count())))
        date = (datetime.date.today().isoformat()
                if dlg.date.isChecked() else "")
        t._push_undo(include_doc=True)
        for i in pages:
            doc_tools.add_stamp(t._doc[i], text, dlg.color(),
                                dlg.position.currentText(),
                                float(dlg.size.value()), date)
        t._render_all()
        self._refresh_thumbs()
        self.statusBar().showMessage(f"Stamped {len(pages)} page(s)", 4000)

    # ----- numbering / Bates -----

    def _add_page_numbers(self) -> None:
        t = self._doc_tab()
        if t is None:
            return
        dlg = NumberingDialog(self, t.page_count())
        if dlg.exec() != QDialog.Accepted:
            return
        t._push_undo(include_doc=True)
        n = doc_tools.number_pages(
            t._doc, dlg.style_key(), dlg.prefix.text(), dlg.start.value(),
            dlg.digits.value(), dlg.position.currentText(),
            float(dlg.size.value()))
        t._render_all()
        self._refresh_thumbs()
        self.statusBar().showMessage(f"Numbered {n} page(s)", 4000)

    # ----- outline -----

    def _edit_outline(self) -> None:
        t = self._doc_tab()
        if t is None:
            return
        toc = t._doc.get_toc() or []
        detected = False
        if not toc:
            try:
                toc = self._outline._auto_detect_headings(t._doc)
            except Exception:
                toc = []
            detected = bool(toc)
        dlg = OutlineEditor(self, toc, t.page_count(),
                            t.current_page_index(), detected)
        if dlg.exec() != QDialog.Accepted:
            return
        t._push_undo(include_doc=True)
        doc_tools.write_toc(t._doc, dlg.toc())
        self._refresh_thumbs()
        self.statusBar().showMessage(
            f"Outline saved ({len(dlg.toc())} bookmark(s)) — save the PDF "
            "to keep it", 5000)

    # ----- forms -----

    def _fill_form(self) -> None:
        t = self._doc_tab()
        if t is None:
            return
        fields = doc_tools.form_fields(t._doc)
        if not fields:
            QMessageBox.information(
                self, "Fill in form",
                "This PDF has no fillable form fields.\n\nTip: use the "
                "Text tool to type onto a flat (non-fillable) form.")
            return
        dlg = FormDialog(self, fields)
        if dlg.exec() != QDialog.Accepted:
            return
        t._push_undo(include_doc=True)
        for f, value in zip(fields, dlg.values()):
            if value != f["value"]:
                doc_tools.set_field_value(t._doc, f["page"], f["xref"], value)
        if dlg.flatten.isChecked():
            doc_tools.flatten_forms(t._doc)
        t._render_all()
        self._refresh_thumbs()
        self.statusBar().showMessage(
            "Form flattened" if dlg.flatten.isChecked() else "Form filled",
            4000)

    # ----- references / DOIs -----

    def _dois_with_text(self, doc) -> tuple[list[str], dict[str, str]]:
        dois = doc_tools.find_dois(doc)
        refs_text: dict[str, str] = {}
        try:
            for ref in doc_tools.reference_list(doc).values():
                m = doc_tools.DOI_RE.search(ref["text"])
                if m:
                    refs_text[doc_tools.clean_doi(m.group(1)).lower()] = ref["text"]
        except Exception:
            pass
        return dois, refs_text

    def _copy_dois(self) -> None:
        t = self._doc_tab()
        if t is None:
            return
        dois = doc_tools.find_dois(t._doc)
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText("\n".join(dois))
        self.statusBar().showMessage(
            f"Copied {len(dois)} DOI(s) to the clipboard", 4000)

    def _import_all_references(self) -> None:
        t = self._doc_tab()
        if t is None:
            return
        if not kherveref_link.find_kherveref() and not self._kherveref_missing():
            return
        dois, refs_text = self._dois_with_text(t._doc)
        if not dois:
            QMessageBox.information(
                self, "Import references",
                "No DOIs were found in this document.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Import all references")
        dlg.resize(560, 460)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(f"Found <b>{len(dois)}</b> DOI(s). Untick any "
                           "you don't want; the rest are looked up on "
                           "doi.org and sent to KherveRef."))
        tbl = QTreeWidget(dlg)
        tbl.setHeaderLabels(["DOI", "Reference"])
        tbl.setRootIsDecorated(False)
        for d in dois:
            it = QTreeWidgetItem([d, refs_text.get(d.lower(), "")[:160]])
            it.setCheckState(0, Qt.Checked)
            tbl.addTopLevelItem(it)
        tbl.setColumnWidth(0, 220)
        v.addWidget(tbl, 1)
        v.addWidget(_buttons(dlg, "Import"))
        if dlg.exec() != QDialog.Accepted:
            return
        chosen = [tbl.topLevelItem(i).text(0) for i in range(tbl.topLevelItemCount())
                  if tbl.topLevelItem(i).checkState(0) == Qt.Checked]
        if not chosen:
            return
        self._bib_fetch = _BibFetcher(chosen, refs_text, self)
        self._bib_fetch.progress.connect(
            lambda i, n: self.statusBar().showMessage(
                f"Looking up references on doi.org… {i}/{n}"))
        self._bib_fetch.finished_bib.connect(
            lambda bib, ok, n=len(chosen), name=t.path.stem:
            self._send_bib_to_kherveref(bib, ok, n, name))
        self._bib_fetch.start()

    def _send_bib_to_kherveref(self, bib: str, fetched: int, total: int,
                               name: str) -> None:
        self._bib_fetch = None
        out_dir = Path(tempfile.mkdtemp(prefix="khervepdf-refs-"))
        safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
        bib_path = out_dir / f"References from {safe}.bib"
        bib_path.write_text(bib + "\n", encoding="utf-8")
        if kherveref_link._launch("--add", bib_path):
            self.statusBar().showMessage(
                f"Sent {total} reference(s) to KherveRef "
                f"({fetched} with full details from doi.org)", 6000)
        else:
            QMessageBox.warning(self, "KherveRef",
                                "KherveRef could not be started.")

    # ----- compare -----

    def _compare_with_file(self) -> None:
        t = self._doc_tab()
        if t is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Compare with…", str(t.path.parent), "PDF files (*.pdf)")
        if not path:
            return
        try:
            other = fitz.open(path)
        except Exception as e:
            QMessageBox.critical(self, "Compare", f"Could not open it:\n{e}")
            return
        self._show_compare(other, Path(path).name, t)

    def compare_with_commit(self, pdf_path: Path, sha: str) -> None:
        data = git_backend.file_bytes_at(pdf_path, sha)
        if data is None:
            QMessageBox.warning(self, "Compare",
                                "Could not read that commit's version.")
            return
        tab = self._tab_for(pdf_path) if hasattr(self, "_tab_for") else None
        old = fitz.open(stream=data, filetype="pdf")
        if tab is None:
            cur = fitz.open(str(pdf_path))
            from .compare_view import CompareDialog
            CompareDialog(self, old, f"{pdf_path.name} @ {sha}", cur,
                          f"{pdf_path.name} (on disk)").exec()
            return
        self._show_compare(old, f"{pdf_path.name} @ {sha}", tab,
                           old_on_left=True)

    def _show_compare(self, other: fitz.Document, other_label: str, tab,
                      old_on_left: bool = False) -> None:
        from .compare_view import CompareDialog
        # The open document as shown, unsaved annotations included.
        current = tab.slideshow_document()
        cur_label = f"{tab.path.name} (open)"
        self.statusBar().showMessage("Comparing…")
        if old_on_left:
            dlg = CompareDialog(self, other, other_label, current, cur_label)
        else:
            dlg = CompareDialog(self, current, cur_label, other, other_label)
        self.statusBar().clearMessage()
        dlg.exec()
