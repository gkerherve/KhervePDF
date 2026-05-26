"""Main window shell: menus, toolbar, status bar, tab widget.

v0.1 scaffold — concrete PDF rendering, tools, and git backend land in
subsequent commits. The shell already wires up:
  - tabbed central widget (one PDF per tab)
  - File / Edit / View / Tools / Pages / Git / Help menus
  - top toolbar with placeholder tool actions
  - status bar with page/zoom/tool/branch labels
  - theme switching across all 13 KherveTeX themes
  - title bar: KhervePDF v0.X.N+sha7 — "last commit" — <file>
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QColorDialog, QDoubleSpinBox, QFileDialog, QLabel, QMainWindow, QMenu,
    QMessageBox, QStatusBar, QTabWidget, QToolBar, QToolButton, QWidget,
)

from . import themes, version_string, last_commit_subject
from .icons import icon
from .pdftab import PdfTab


class MainWindow(QMainWindow):
    def __init__(self, theme_name: str = "Light") -> None:
        super().__init__()
        self._theme_name = theme_name
        self._theme = themes.THEMES.get(theme_name, themes.THEMES["Light"])

        self.resize(1280, 860)

        self._tabs = QTabWidget(self)
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(lambda _i: self._refresh_status())
        self.setCentralWidget(self._tabs)

        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._apply_theme_qss()
        self._update_title()

    # ----- chrome -----

    def _build_menus(self) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu("&File")
        m_file.addAction(QAction(icon("new"), "&New", self, shortcut="Ctrl+N",
                                 triggered=self._new))
        m_file.addAction(QAction(icon("open"), "&Open…", self, shortcut="Ctrl+O",
                                 triggered=self._open))
        self._m_recent = m_file.addMenu("Open &Recent")
        self._m_recent.setIcon(icon("history"))
        self._refresh_recent_menu()
        m_file.addSeparator()
        m_file.addAction(QAction(icon("save"), "&Save", self, shortcut="Ctrl+S",
                                 triggered=self._save))
        m_file.addAction(QAction(icon("save_as"), "Save &As…", self,
                                 shortcut="Ctrl+Shift+S",
                                 triggered=self._save_as))
        m_file.addSeparator()
        m_file.addAction(QAction(icon("export_png"), "Export as &PNG…", self,
                                 triggered=self._noop))
        m_file.addAction(QAction(icon("export_txt"), "Export &Text…", self,
                                 triggered=self._noop))
        m_file.addAction(QAction(icon("print"), "&Print…", self,
                                 shortcut="Ctrl+P", triggered=self._noop))
        m_file.addSeparator()
        m_file.addAction(QAction(icon("close"), "&Close Tab", self,
                                 shortcut="Ctrl+W",
                                 triggered=lambda: self._close_tab(self._tabs.currentIndex())))
        m_file.addAction(QAction("E&xit", self, shortcut="Ctrl+Q",
                                 triggered=self.close))

        m_edit = mb.addMenu("&Edit")
        m_edit.addAction(QAction(icon("undo"), "&Undo", self, shortcut="Ctrl+Z",
                                 triggered=self._noop))
        m_edit.addAction(QAction(icon("redo"), "&Redo", self, shortcut="Ctrl+Y",
                                 triggered=self._noop))
        m_edit.addSeparator()
        m_edit.addAction(QAction(icon("find"), "&Find…", self, shortcut="Ctrl+F",
                                 triggered=self._noop))

        m_view = mb.addMenu("&View")
        m_view.addAction(QAction(icon("zoom_in"), "Zoom &In", self,
                                 shortcut="Ctrl++", triggered=self._zoom_in))
        m_view.addAction(QAction(icon("zoom_out"), "Zoom &Out", self,
                                 shortcut="Ctrl+-", triggered=self._zoom_out))
        m_view.addAction(QAction(icon("fit_width"), "Fit &Width", self,
                                 triggered=self._fit_width))
        m_view.addAction(QAction(icon("fit_page"), "Fit &Page", self,
                                 triggered=self._noop))
        m_view.addSeparator()
        m_view.addAction(QAction("Rotate &Left", self, triggered=self._noop))
        m_view.addAction(QAction("Rotate &Right", self, triggered=self._noop))
        m_view.addSeparator()

        m_theme = m_view.addMenu("&Theme")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        for name in themes.THEME_NAMES:
            act = QAction(name, self, checkable=True)
            act.setChecked(name == self._theme_name)
            act.triggered.connect(lambda _checked, n=name: self._set_theme(n))
            theme_group.addAction(act)
            m_theme.addAction(act)

        m_tools = mb.addMenu("&Tools")
        for label in ("&Select", "&Pen", "&Highlight", "&Text", "&Line",
                      "&Arrow", "&Rectangle", "&Ellipse", "Sticky &Note",
                      "&Signature", "Re&dact"):
            m_tools.addAction(QAction(label, self, triggered=self._noop))

        m_pages = mb.addMenu("&Pages")
        for label in ("Insert &Blank Page", "&Delete Page",
                      "Rotate Page Left", "Rotate Page Right",
                      "&Reorder Pages…", "&Merge PDF…", "&Split…"):
            m_pages.addAction(QAction(label, self, triggered=self._noop))

        m_git = mb.addMenu("&Git")
        for label in ("Commit &Now", "&History…", "&Remote…", "&Branch…"):
            m_git.addAction(QAction(label, self, triggered=self._noop))

        m_help = mb.addMenu("&Help")
        m_help.addAction(QAction("&About KhervePDF", self,
                                 triggered=self._about))

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main", self)
        tb.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, tb)

        # Plain file/zoom actions.
        for name, tip, handler in (
            ("open",     "Open PDF (Ctrl+O)", self._open),
            ("save",     "Save (Ctrl+S)",     self._save),
        ):
            act = QAction(icon(name), tip, self, triggered=handler)
            act.setToolTip(tip)
            tb.addAction(act)
        tb.addSeparator()

        # Tool buttons — checkable, mutually exclusive. Triggering one
        # sets the active PdfTab's current tool.
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_actions: dict[str, QAction] = {}
        tools = [
            ("select",    "Select / Pan"),
            ("pen",       "Pen"),
            ("highlight", "Highlight"),
            ("text",      "Text (add new)"),
            ("edit_text", "Edit existing text"),
            ("line",      "Line"),
            ("arrow",     "Arrow"),
            ("rect",      "Rectangle"),
            ("ellipse",   "Ellipse"),
            ("note",      "Sticky Note"),
            ("signature", "Signature"),
            ("redact",    "Redact"),
        ]
        for name, tip in tools:
            act = QAction(icon(name), tip, self, checkable=True)
            act.setToolTip(tip)
            act.triggered.connect(lambda _c=False, n=name: self._set_tool(n))
            self._tool_group.addAction(act)
            self._tool_actions[name] = act
            tb.addAction(act)
        self._tool_actions["select"].setChecked(True)

        tb.addSeparator()
        # Stroke colour swatch + width spinbox edit the active tool's
        # stored color/width on the current PdfTab. Switching tools
        # refreshes both widgets to that tool's stored values.
        self._color_btn = QToolButton(self)
        self._color_btn.setToolTip("Stroke colour (for the active tool)")
        self._color_btn.clicked.connect(self._pick_color)
        tb.addWidget(self._color_btn)

        self._width_spin = QDoubleSpinBox(self)
        self._width_spin.setRange(0.5, 60.0)
        self._width_spin.setDecimals(1)
        self._width_spin.setSingleStep(0.5)
        self._width_spin.setSuffix(" pt")
        self._width_spin.setToolTip(
            "Stroke width (for pen/line/shapes) or font size (for text)"
        )
        self._width_spin.valueChanged.connect(self._set_width)
        tb.addWidget(self._width_spin)

        tb.addSeparator()
        for name, tip, handler in (
            ("zoom_out",  "Zoom Out",  self._zoom_out),
            ("zoom_in",   "Zoom In",   self._zoom_in),
            ("fit_width", "Fit Width", self._fit_width),
        ):
            act = QAction(icon(name), tip, self, triggered=handler)
            act.setToolTip(tip)
            tb.addAction(act)
        self._sync_tool_widgets()

    def _build_statusbar(self) -> None:
        sb = QStatusBar(self)
        self.setStatusBar(sb)
        self._lbl_page = QLabel("—")
        self._lbl_zoom = QLabel("100%")
        self._lbl_tool = QLabel("Select")
        self._lbl_branch = QLabel("")
        sb.addWidget(self._lbl_page)
        sb.addPermanentWidget(self._lbl_tool)
        sb.addPermanentWidget(self._lbl_zoom)
        sb.addPermanentWidget(self._lbl_branch)

    # ----- theming -----

    def _apply_theme_qss(self) -> None:
        t = self._theme
        self.setStyleSheet(themes.tab_stylesheet(t))

    def _set_theme(self, name: str) -> None:
        from PySide6.QtWidgets import QApplication
        self._theme_name = name
        self._theme = themes.apply_theme(QApplication.instance(), name)
        self._apply_theme_qss()
        QSettings("kherve", "KhervePDF").setValue("theme_name", name)

    # ----- title / status -----

    def _update_title(self) -> None:
        current = self._current_path()
        name = current.name if current else "Untitled"
        subj = last_commit_subject()
        subj_part = f' — "{subj}"' if subj else ""
        self.setWindowTitle(
            f"KhervePDF {version_string()}{subj_part} — {name}"
        )

    def _refresh_status(self) -> None:
        w = self._tabs.currentWidget()
        if isinstance(w, PdfTab):
            self._lbl_page.setText(f"Page 1 of {w.page_count()}")
            self._lbl_zoom.setText(f"{w.zoom_percent()}%")
        else:
            self._lbl_page.setText("—")
            self._lbl_zoom.setText("—")
        self._update_title()

    # ----- tab helpers -----

    def _current_path(self) -> Path | None:
        w = self._tabs.currentWidget()
        return getattr(w, "path", None) if w else None

    def _close_tab(self, idx: int) -> None:
        if idx < 0:
            return
        w = self._tabs.widget(idx)
        self._tabs.removeTab(idx)
        if isinstance(w, PdfTab):
            w.close_doc()
        if w is not None:
            w.deleteLater()
        self._refresh_status()

    # ----- file actions (stubs — concrete logic in pdftab v0.3) -----

    def open_path(self, path: Path) -> None:
        try:
            tab = PdfTab(path, self)
        except Exception as e:
            QMessageBox.critical(
                self, "Open failed",
                f"Could not open <b>{path.name}</b>:<br>{e}",
            )
            return
        self._tabs.addTab(tab, path.name)
        self._tabs.setCurrentWidget(tab)
        checked = self._tool_group.checkedAction()
        if checked is not None:
            for n, a in self._tool_actions.items():
                if a is checked:
                    tab.set_tool(n)
                    break
        self._push_recent(path)
        self._sync_tool_widgets()
        self._refresh_status()

    # ----- view actions -----

    def _current_pdf_tab(self) -> PdfTab | None:
        w = self._tabs.currentWidget()
        return w if isinstance(w, PdfTab) else None

    def _zoom_in(self) -> None:
        t = self._current_pdf_tab()
        if t:
            t.zoom_in()
            self._refresh_status()

    def _zoom_out(self) -> None:
        t = self._current_pdf_tab()
        if t:
            t.zoom_out()
            self._refresh_status()

    def _fit_width(self) -> None:
        t = self._current_pdf_tab()
        if t:
            t.fit_width()
            self._refresh_status()

    def _set_tool(self, name: str) -> None:
        t = self._current_pdf_tab()
        if t:
            t.set_tool(name)
        self._lbl_tool.setText(name.replace("_", " ").capitalize())
        self._sync_tool_widgets()

    # ----- color / width pickers -----

    def _sync_tool_widgets(self) -> None:
        """Refresh the colour swatch and width spinbox to reflect the
        active tool on the active PdfTab (or the toolbar default)."""
        t = self._current_pdf_tab()
        checked = self._tool_group.checkedAction()
        tool_name = "select"
        if checked is not None:
            for n, a in self._tool_actions.items():
                if a is checked:
                    tool_name = n
                    break
        if t is not None:
            color = t.tool_color(tool_name)
            width = t.tool_width(tool_name)
        else:
            from .pdftab import TOOL_DEFAULTS
            d = TOOL_DEFAULTS.get(tool_name, {"color": "#000000", "width": 2.0})
            color, width = d["color"], d["width"]
        self._color_btn.setIcon(self._make_color_icon(QColor(color)))
        # Block signal to avoid feedback when programmatically setting.
        self._width_spin.blockSignals(True)
        self._width_spin.setValue(float(width))
        self._width_spin.blockSignals(False)
        self._color_btn.setProperty("current_color", color)

    @staticmethod
    def _make_color_icon(color: QColor, size: int = 20) -> QIcon:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setBrush(color)
        p.setPen(QPen(QColor("#666"), 1))
        p.drawRoundedRect(1, 1, size - 2, size - 2, 3, 3)
        p.end()
        return QIcon(pm)

    def _pick_color(self) -> None:
        current = self._color_btn.property("current_color") or "#000000"
        chosen = QColorDialog.getColor(
            QColor(current), self, "Choose stroke colour",
        )
        if not chosen.isValid():
            return
        hex_str = chosen.name()
        t = self._current_pdf_tab()
        if t is not None:
            t.set_tool_color(hex_str)
        self._color_btn.setIcon(self._make_color_icon(chosen))
        self._color_btn.setProperty("current_color", hex_str)

    def _set_width(self, w: float) -> None:
        t = self._current_pdf_tab()
        if t is not None:
            t.set_tool_width(w)

    # ----- recent files -----

    def _settings(self) -> QSettings:
        return QSettings("kherve", "KhervePDF")

    def _recent_files(self) -> list[str]:
        s = self._settings()
        raw = s.value("recent_files", [])
        if isinstance(raw, str):
            return [raw] if raw else []
        return [str(p) for p in (raw or [])]

    def _push_recent(self, path: Path) -> None:
        files = [p for p in self._recent_files() if p != str(path)]
        files.insert(0, str(path))
        files = files[:10]
        self._settings().setValue("recent_files", files)
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        m = self._m_recent
        m.clear()
        files = self._recent_files()
        if not files:
            act = QAction("(empty)", self)
            act.setEnabled(False)
            m.addAction(act)
            return
        for p in files:
            label = Path(p).name
            act = QAction(label, self)
            act.setToolTip(p)
            act.triggered.connect(lambda _c=False, path=p: self.open_path(Path(path)))
            m.addAction(act)
        m.addSeparator()
        clear = QAction("Clear list", self)
        clear.triggered.connect(self._clear_recent)
        m.addAction(clear)

    def _clear_recent(self) -> None:
        self._settings().setValue("recent_files", [])
        self._refresh_recent_menu()

    def _new(self) -> None:
        self._noop()

    def _open(self) -> None:
        path_s, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF files (*.pdf);;All files (*)")
        if path_s:
            self.open_path(Path(path_s))

    def _save(self) -> None:
        self._noop()

    def _save_as(self) -> None:
        self._noop()

    def _about(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.about(
            self, "About KhervePDF",
            f"<b>KhervePDF</b> {version_string()}<br>"
            "WYSIWYG PDF viewer & annotation editor with Git history.<br>"
            "<a href='https://github.com/gkerherve/KhervePDF'>github.com/gkerherve/KhervePDF</a>",
        )

    def _noop(self) -> None:
        # Stub for actions not yet implemented in this version.
        pass
