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
    QColorDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QSizePolicy, QSlider,
    QStackedWidget, QStatusBar, QTabWidget, QToolBar, QToolButton, QWidget,
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
        self._build_tool_options_toolbar()
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
        for name, tip, handler in (
            ("zoom_out",  "Zoom Out",  self._zoom_out),
            ("zoom_in",   "Zoom In",   self._zoom_in),
            ("fit_width", "Fit Width", self._fit_width),
        ):
            act = QAction(icon(name), tip, self, triggered=handler)
            act.setToolTip(tip)
            tb.addAction(act)

    # Shared palette across all tool option panels. "Custom..." is
    # appended automatically by _make_palette_row and opens
    # QColorDialog for free-form picks.
    PALETTE = [
        "#000000", "#c62828", "#1976d2", "#2e7d32", "#7b1fa2",
        "#ef6c00", "#fbc02d", "#c2185b", "#0097a7", "#5d4037",
    ]

    def _build_tool_options_toolbar(self) -> None:
        """Per-tool options sub-toolbar (the strip below the main one).

        A QStackedWidget swaps panels when the active tool changes.
        Pen/Line/Arrow/Rect/Ellipse get a width slider + colour palette;
        Highlight gets palette + opacity slider; Text/Edit-Text get a
        font-size spinbox + palette. Tools without options (Select /
        Redact / Note / Signature) show an empty placeholder so the row
        height doesn't jump.
        """
        self.addToolBarBreak(Qt.TopToolBarArea)
        tb = QToolBar("Tool Options", self)
        tb.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, tb)
        self._opts_stack = QStackedWidget(self)
        self._opts_stack.setSizePolicy(QSizePolicy.Expanding,
                                       QSizePolicy.Preferred)
        tb.addWidget(self._opts_stack)

        self._opts_widgets: dict[str, dict] = {}
        self._opts_index: dict[str, int] = {}

        self._opts_empty = QWidget(self)
        self._opts_empty.setFixedHeight(36)
        self._opts_stack.addWidget(self._opts_empty)
        self._opts_index["__empty__"] = self._opts_stack.indexOf(self._opts_empty)

        for tool in ("pen", "line", "arrow", "rect", "ellipse"):
            panel = self._build_stroke_panel(tool)
            self._opts_index[tool] = self._opts_stack.addWidget(panel)
        self._opts_index["highlight"] = self._opts_stack.addWidget(
            self._build_highlight_panel())
        for tool in ("text", "edit_text"):
            self._opts_index[tool] = self._opts_stack.addWidget(
                self._build_text_panel(tool))

        self._opts_stack.setCurrentIndex(self._opts_index["__empty__"])

    def _make_color_button(self, color: str, on_click) -> QToolButton:
        btn = QToolButton(self)
        btn.setFixedSize(22, 22)
        btn.setStyleSheet(
            f"QToolButton {{ background:{color}; border:1px solid #555;"
            "border-radius:3px; } QToolButton:hover {border:2px solid #fff;}"
        )
        btn.setToolTip(color)
        btn.clicked.connect(lambda _c=False, c=color: on_click(c))
        return btn

    def _make_palette_row(self, tool_name: str) -> QWidget:
        w = QWidget(self)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        for color in self.PALETTE:
            lay.addWidget(self._make_color_button(
                color,
                lambda c, t=tool_name: self._apply_color_for(t, c),
            ))
        more = QToolButton(self)
        more.setFixedSize(22, 22)
        more.setText("…")
        more.setToolTip("Custom colour…")
        more.clicked.connect(lambda _c=False, t=tool_name: self._pick_custom_color(t))
        lay.addWidget(more)
        return w

    def _build_stroke_panel(self, tool: str) -> QWidget:
        w = QWidget(self)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(8)
        lay.addWidget(QLabel("Width:"))
        slider = QSlider(Qt.Horizontal, self)
        slider.setRange(1, 30)
        slider.setFixedWidth(140)
        val = QLabel("2 pt")
        val.setMinimumWidth(50)
        slider.valueChanged.connect(
            lambda v, t=tool, l=val: self._on_width_changed(t, v, l)
        )
        lay.addWidget(slider)
        lay.addWidget(val)
        lay.addSpacing(16)
        lay.addWidget(QLabel("Colour:"))
        lay.addWidget(self._make_palette_row(tool))
        lay.addStretch(1)
        self._opts_widgets[tool] = {"width_slider": slider, "width_lbl": val}
        return w

    def _build_highlight_panel(self) -> QWidget:
        w = QWidget(self)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(8)
        lay.addWidget(QLabel("Colour:"))
        lay.addWidget(self._make_palette_row("highlight"))
        lay.addSpacing(16)
        lay.addWidget(QLabel("Opacity:"))
        op = QSlider(Qt.Horizontal, self)
        op.setRange(10, 100)
        op.setFixedWidth(140)
        op_lbl = QLabel("35%")
        op_lbl.setMinimumWidth(40)
        op.valueChanged.connect(
            lambda v, l=op_lbl: self._on_opacity_changed("highlight", v, l)
        )
        lay.addWidget(op)
        lay.addWidget(op_lbl)
        lay.addStretch(1)
        self._opts_widgets["highlight"] = {"opacity": op, "opacity_lbl": op_lbl}
        return w

    def _build_text_panel(self, tool: str) -> QWidget:
        w = QWidget(self)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(8)
        lay.addWidget(QLabel("Size:"))
        spin = QDoubleSpinBox(self)
        spin.setRange(4.0, 96.0)
        spin.setDecimals(1)
        spin.setSingleStep(1.0)
        spin.setSuffix(" pt")
        spin.valueChanged.connect(
            lambda v, t=tool: self._apply_width_for(t, float(v))
        )
        lay.addWidget(spin)
        lay.addSpacing(16)
        lay.addWidget(QLabel("Colour:"))
        lay.addWidget(self._make_palette_row(tool))
        lay.addStretch(1)
        self._opts_widgets[tool] = {"size_spin": spin}
        return w

    # ----- option panel handlers -----

    def _on_width_changed(self, tool: str, v: int, lbl: QLabel) -> None:
        lbl.setText(f"{v} pt")
        self._apply_width_for(tool, float(v))

    def _on_opacity_changed(self, tool: str, v: int, lbl: QLabel) -> None:
        lbl.setText(f"{v}%")
        t = self._current_pdf_tab()
        if t is not None:
            t.set_tool_opacity(v, tool)

    def _apply_color_for(self, tool: str, color: str) -> None:
        t = self._current_pdf_tab()
        if t is not None:
            t.set_tool_color(color, tool)

    def _apply_width_for(self, tool: str, w: float) -> None:
        t = self._current_pdf_tab()
        if t is not None:
            t.set_tool_width(w, tool)

    def _pick_custom_color(self, tool: str) -> None:
        t = self._current_pdf_tab()
        if t is not None:
            current = t.tool_color(tool)
        else:
            from .pdftab import TOOL_DEFAULTS
            current = TOOL_DEFAULTS.get(tool, {"color": "#000000"})["color"]
        chosen = QColorDialog.getColor(QColor(current), self,
                                       "Choose custom colour")
        if chosen.isValid():
            self._apply_color_for(tool, chosen.name())

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
        checked = self._tool_group.checkedAction()
        if checked is not None:
            for n, a in self._tool_actions.items():
                if a is checked:
                    self._sync_tool_options(n)
                    break
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
        # Swap the options sub-toolbar to the panel for this tool.
        idx = self._opts_index.get(name, self._opts_index["__empty__"])
        self._opts_stack.setCurrentIndex(idx)
        self._sync_tool_options(name)

    def _sync_tool_options(self, tool: str) -> None:
        """Push the active tab's stored colour/width/opacity for `tool`
        into the matching option-panel widgets (blocking signals to
        avoid feedback)."""
        widgets = self._opts_widgets.get(tool)
        if not widgets:
            return
        t = self._current_pdf_tab()
        if t is not None:
            width = t.tool_width(tool)
            opacity = t.tool_opacity(tool)
        else:
            from .pdftab import TOOL_DEFAULTS
            d = TOOL_DEFAULTS.get(tool, {})
            width = d.get("width", 2.0)
            opacity = d.get("opacity", 100)
        if "width_slider" in widgets:
            s: QSlider = widgets["width_slider"]
            s.blockSignals(True)
            s.setValue(max(1, min(30, int(round(width)))))
            s.blockSignals(False)
            widgets["width_lbl"].setText(f"{int(round(width))} pt")
        if "size_spin" in widgets:
            spin: QDoubleSpinBox = widgets["size_spin"]
            spin.blockSignals(True)
            spin.setValue(float(width))
            spin.blockSignals(False)
        if "opacity" in widgets:
            op: QSlider = widgets["opacity"]
            op.blockSignals(True)
            op.setValue(int(opacity))
            op.blockSignals(False)
            widgets["opacity_lbl"].setText(f"{int(opacity)}%")

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
