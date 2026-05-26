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
from PySide6.QtGui import QAction, QActionGroup, QColor
from PySide6.QtWidgets import (
    QButtonGroup, QColorDialog, QDoubleSpinBox, QFileDialog, QGridLayout,
    QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton,
    QSlider, QStatusBar, QTabWidget, QToolBar, QToolButton, QVBoxLayout,
    QWidget, QWidgetAction,
)

from . import themes, version_string, last_commit_subject
from .icons import app_icon, icon
from .pdftab import PdfTab, TOOL_DEFAULTS


# Curated colour grid used by _OptionsPopup. Office-style: a greyscale
# ramp plus a set of vivid primaries and muted shades. Click any swatch
# to apply it to the active tool's stroke colour.
_PALETTE_GRID = [
    ["#000000", "#262626", "#404040", "#595959", "#7F7F7F",
     "#A6A6A6", "#BFBFBF", "#D9D9D9", "#F2F2F2", "#FFFFFF"],
    ["#C00000", "#FF0000", "#FF6600", "#FFC000", "#FFFF00",
     "#92D050", "#00B050", "#00B0F0", "#0070C0", "#7030A0"],
    ["#7F1414", "#A6324E", "#A66232", "#A68F2F", "#638F1A",
     "#1F8F4D", "#1F718F", "#2A4D8F", "#3A2A8F", "#582D7E"],
    ["#F2D7D7", "#FAD7E0", "#FAE5D7", "#FAF6D7", "#E7FAD7",
     "#D7FAE0", "#D7F0FA", "#D7E7FA", "#D7DDFA", "#E6D7FA"],
]


class _OptionsPopup(QWidget):
    """Excel-style dropdown panel for the active tool: a colour grid,
    a Custom-colour button, and (depending on tool) width / opacity /
    font-size controls.

    A single instance lives in MainWindow and is wrapped in a QMenu via
    QWidgetAction so every drawing tool button can share it. The
    menu's `aboutToShow` triggers `refresh()`, which reads the active
    tool's settings off the active PdfTab and reconfigures which rows
    are visible."""

    def __init__(self, mw: "MainWindow") -> None:
        super().__init__(mw)
        self._mw = mw
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Colour grid
        grid = QGridLayout()
        grid.setSpacing(2)
        grid.setContentsMargins(0, 0, 0, 0)
        for r, row in enumerate(_PALETTE_GRID):
            for c, color in enumerate(row):
                btn = QToolButton(self)
                btn.setFixedSize(20, 20)
                btn.setStyleSheet(
                    f"QToolButton {{ background:{color};"
                    "border:1px solid #555; }"
                    "QToolButton:hover { border:2px solid #000; }"
                )
                btn.setToolTip(color)
                btn.clicked.connect(
                    lambda _c=False, col=color: self._apply_color(col)
                )
                grid.addWidget(btn, r, c)
        layout.addLayout(grid)

        custom_btn = QPushButton("Custom colour…", self)
        custom_btn.clicked.connect(self._on_custom)
        layout.addWidget(custom_btn)

        # Width slider row (drawing tools that have a stroke width).
        self._width_row = QWidget(self)
        wr = QHBoxLayout(self._width_row)
        wr.setContentsMargins(0, 4, 0, 0)
        wr.addWidget(QLabel("Width:"))
        self._width_slider = QSlider(Qt.Horizontal, self)
        self._width_slider.setRange(1, 30)
        self._width_slider.setFixedWidth(160)
        self._width_lbl = QLabel("2 pt")
        self._width_lbl.setMinimumWidth(48)
        self._width_slider.valueChanged.connect(self._on_width)
        wr.addWidget(self._width_slider)
        wr.addWidget(self._width_lbl)
        layout.addWidget(self._width_row)

        # Opacity slider row (pen/shapes/highlight).
        self._opacity_row = QWidget(self)
        opr = QHBoxLayout(self._opacity_row)
        opr.setContentsMargins(0, 0, 0, 0)
        opr.addWidget(QLabel("Opacity:"))
        self._opacity_slider = QSlider(Qt.Horizontal, self)
        self._opacity_slider.setRange(10, 100)
        self._opacity_slider.setFixedWidth(160)
        self._opacity_lbl = QLabel("100%")
        self._opacity_lbl.setMinimumWidth(48)
        self._opacity_slider.valueChanged.connect(self._on_opacity)
        opr.addWidget(self._opacity_slider)
        opr.addWidget(self._opacity_lbl)
        layout.addWidget(self._opacity_row)

        # Font-size row (text tools).
        self._size_row = QWidget(self)
        szr = QHBoxLayout(self._size_row)
        szr.setContentsMargins(0, 0, 0, 0)
        szr.addWidget(QLabel("Size:"))
        self._size_spin = QDoubleSpinBox(self)
        self._size_spin.setRange(4.0, 96.0)
        self._size_spin.setDecimals(1)
        self._size_spin.setSingleStep(1.0)
        self._size_spin.setSuffix(" pt")
        self._size_spin.valueChanged.connect(self._on_size)
        szr.addWidget(self._size_spin)
        szr.addStretch(1)
        layout.addWidget(self._size_row)

    def refresh(self) -> None:
        tool = self._mw._current_tool
        has_width = tool in ("pen", "line", "arrow", "rect", "ellipse")
        has_opacity = tool in ("pen", "line", "arrow", "rect", "ellipse",
                               "highlight")
        has_size = tool in ("text", "edit_text")
        self._width_row.setVisible(has_width)
        self._opacity_row.setVisible(has_opacity)
        self._size_row.setVisible(has_size)

        tab = self._mw._current_pdf_tab()
        if tab is not None:
            width = tab.tool_width(tool)
            opacity = tab.tool_opacity(tool)
        else:
            d = TOOL_DEFAULTS.get(tool, {})
            width = d.get("width", 2.0)
            opacity = d.get("opacity", 100)
        if has_width:
            self._width_slider.blockSignals(True)
            self._width_slider.setValue(max(1, min(30, int(round(width)))))
            self._width_slider.blockSignals(False)
            self._width_lbl.setText(f"{int(round(width))} pt")
        if has_size:
            self._size_spin.blockSignals(True)
            self._size_spin.setValue(float(width))
            self._size_spin.blockSignals(False)
        if has_opacity:
            self._opacity_slider.blockSignals(True)
            self._opacity_slider.setValue(int(opacity))
            self._opacity_slider.blockSignals(False)
            self._opacity_lbl.setText(f"{int(opacity)}%")

    def _apply_color(self, color: str) -> None:
        tab = self._mw._current_pdf_tab()
        if tab is not None:
            tab.set_tool_color(color, self._mw._current_tool)
        self._mw._close_options_menu()

    def _on_custom(self) -> None:
        tab = self._mw._current_pdf_tab()
        current = (tab.tool_color(self._mw._current_tool)
                   if tab is not None else "#000000")
        chosen = QColorDialog.getColor(QColor(current), self,
                                       "Choose custom colour")
        if chosen.isValid():
            if tab is not None:
                tab.set_tool_color(chosen.name(), self._mw._current_tool)
            self._mw._close_options_menu()

    def _on_width(self, v: int) -> None:
        self._width_lbl.setText(f"{v} pt")
        tab = self._mw._current_pdf_tab()
        if tab is not None:
            tab.set_tool_width(float(v), self._mw._current_tool)

    def _on_opacity(self, v: int) -> None:
        self._opacity_lbl.setText(f"{v}%")
        tab = self._mw._current_pdf_tab()
        if tab is not None:
            tab.set_tool_opacity(v, self._mw._current_tool)

    def _on_size(self, v: float) -> None:
        tab = self._mw._current_pdf_tab()
        if tab is not None:
            tab.set_tool_width(float(v), self._mw._current_tool)


class _ToolButton(QToolButton):
    """Tool button with a popup-options dropdown. Clicking the arrow
    activates this tool *before* showing the menu so the shared popup
    syncs to it — without that the popup would reflect whichever tool
    was active when the user last clicked anything else."""

    def __init__(self, mw: "MainWindow", tool: str, parent=None) -> None:
        super().__init__(parent)
        self._mw = mw
        self._tool = tool

    def showMenu(self) -> None:  # noqa: N802 — Qt override
        self._mw._activate_tool(self._tool)
        super().showMenu()


class MainWindow(QMainWindow):
    def __init__(self, theme_name: str = "Light") -> None:
        super().__init__()
        self._theme_name = theme_name
        self._theme = themes.THEMES.get(theme_name, themes.THEMES["Light"])

        self.setWindowIcon(app_icon())
        self.resize(1280, 860)

        self._tabs = QTabWidget(self)
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(lambda _i: self._refresh_status())
        self.setCentralWidget(self._tabs)

        self._current_tool = "select"
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
                                 triggered=self._undo))
        m_edit.addAction(QAction(icon("redo"), "&Redo", self, shortcut="Ctrl+Y",
                                 triggered=self._redo))
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

        # Plain file actions.
        for name, tip, handler in (
            ("open", "Open PDF (Ctrl+O)", self._open),
            ("save", "Save (Ctrl+S)",     self._save),
        ):
            act = QAction(icon(name), tip, self, triggered=handler)
            act.setToolTip(tip)
            tb.addAction(act)
        tb.addSeparator()

        # Shared options popup (used by every drawing tool with a
        # dropdown). Built once and attached to multiple tool buttons.
        self._options_menu = QMenu(self)
        self._options_popup = _OptionsPopup(self)
        qwa = QWidgetAction(self._options_menu)
        qwa.setDefaultWidget(self._options_popup)
        self._options_menu.addAction(qwa)
        self._options_menu.aboutToShow.connect(self._options_popup.refresh)

        # Tool buttons. Drawing tools that take options get a dropdown
        # arrow (MenuButtonPopup) wired to _options_menu via _ToolButton
        # so the popup syncs to the right tool.
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_buttons: dict[str, QToolButton] = {}
        OPTIONS_TOOLS = {"pen", "highlight", "line", "arrow", "rect",
                         "ellipse", "text", "edit_text"}
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
            ("erase",     "Eraser — click an annotation to delete it"),
        ]
        for name, tip in tools:
            if name in OPTIONS_TOOLS:
                btn = _ToolButton(self, name, self)
                btn.setMenu(self._options_menu)
                btn.setPopupMode(QToolButton.MenuButtonPopup)
            else:
                btn = QToolButton(self)
            btn.setIcon(icon(name))
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setAutoExclusive(False)  # QButtonGroup owns exclusivity
            btn.clicked.connect(
                lambda _c=False, n=name: self._activate_tool(n)
            )
            self._tool_group.addButton(btn)
            self._tool_buttons[name] = btn
            tb.addWidget(btn)
        self._tool_buttons["select"].setChecked(True)

        tb.addSeparator()
        for name, tip, handler in (
            ("zoom_out",  "Zoom Out",  self._zoom_out),
            ("zoom_in",   "Zoom In",   self._zoom_in),
            ("fit_width", "Fit Width", self._fit_width),
        ):
            act = QAction(icon(name), tip, self, triggered=handler)
            act.setToolTip(tip)
            tb.addAction(act)

    def _activate_tool(self, name: str) -> None:
        self._current_tool = name
        btn = self._tool_buttons.get(name)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)
        tab = self._current_pdf_tab()
        if tab is not None:
            tab.set_tool(name)
        self._lbl_tool.setText(name.replace("_", " ").capitalize())

    def _close_options_menu(self) -> None:
        if getattr(self, "_options_menu", None) is not None:
            self._options_menu.close()

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
        tab.set_tool(self._current_tool)
        self._push_recent(path)
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

    def _undo(self) -> None:
        t = self._current_pdf_tab()
        if t is not None:
            t.undo()
            self._refresh_status()

    def _redo(self) -> None:
        t = self._current_pdf_tab()
        if t is not None:
            t.redo()
            self._refresh_status()

    def _save(self) -> None:
        t = self._current_pdf_tab()
        if t is None:
            return
        try:
            saved = t.save_to_pdf()
        except Exception as e:
            QMessageBox.critical(
                self, "Save failed",
                f"Could not save:<br>{e}",
            )
            return
        self.statusBar().showMessage(f"Saved {saved}", 3000)

    def _save_as(self) -> None:
        t = self._current_pdf_tab()
        if t is None:
            return
        path_s, _ = QFileDialog.getSaveFileName(
            self, "Save PDF As", str(t.path),
            "PDF files (*.pdf);;All files (*)",
        )
        if not path_s:
            return
        try:
            saved = t.save_to_pdf(Path(path_s))
        except Exception as e:
            QMessageBox.critical(
                self, "Save failed",
                f"Could not save:<br>{e}",
            )
            return
        self.statusBar().showMessage(f"Saved {saved}", 3000)

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
