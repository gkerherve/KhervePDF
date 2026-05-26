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
from typing import Optional

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QColorDialog, QDockWidget,
    QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSlider,
    QStatusBar, QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
    QWidgetAction,
)

from . import themes, version_string, last_commit_subject
from .icons import app_icon, icon
from .outline import OutlinePanel
from .pdftab import PdfTab, TOOL_DEFAULTS
from .thumbnails import ThumbnailPanel


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
        self._color_buttons: dict[str, QToolButton] = {}
        for r, row in enumerate(_PALETTE_GRID):
            for c, color in enumerate(row):
                btn = QToolButton(self)
                self._style_swatch(btn, color, selected=False)
                btn.setToolTip(color)
                btn.clicked.connect(
                    lambda _c=False, col=color: self._apply_color(col)
                )
                grid.addWidget(btn, r, c)
                self._color_buttons[color.lower()] = btn
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

        # Fill toggle + fill-colour swatch — rect / ellipse only.
        self._fill_row = QWidget(self)
        fr = QHBoxLayout(self._fill_row)
        fr.setContentsMargins(0, 0, 0, 0)
        self._fill_check = QCheckBox("Fill shape", self)
        self._fill_check.toggled.connect(self._on_fill)
        fr.addWidget(self._fill_check)
        # Small coloured square — click to pick a different fill
        # colour (otherwise the stroke colour is used).
        self._fill_color_btn = QToolButton(self)
        self._fill_color_btn.setFixedSize(22, 22)
        self._fill_color_btn.setToolTip(
            "Fill colour — defaults to stroke colour; click to override"
        )
        self._fill_color_btn.clicked.connect(self._on_fill_color)
        fr.addWidget(self._fill_color_btn)
        fr.addStretch(1)
        layout.addWidget(self._fill_row)

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

    @staticmethod
    def _style_swatch(btn: QToolButton, color: str, *, selected: bool) -> None:
        """Apply the small coloured-square stylesheet to a swatch
        button. When `selected`, the border is thicker and stays so on
        hover — to mark which colour the active tool currently uses."""
        btn.setFixedSize(20, 20)
        if selected:
            btn.setStyleSheet(
                f"QToolButton {{ background:{color};"
                "border:3px solid #000; }"
                "QToolButton:hover { border:3px solid #000; }"
            )
        else:
            btn.setStyleSheet(
                f"QToolButton {{ background:{color};"
                "border:1px solid #555; }"
                "QToolButton:hover { border:2px solid #000; }"
            )

    def _mark_active_color(self, current: str) -> None:
        cur = current.lower() if current else ""
        for color, btn in self._color_buttons.items():
            self._style_swatch(btn, color, selected=(color == cur))

    def refresh(self) -> None:
        """Sync slider/spin values from the active tool's stored state.

        Every row stays *visible* on every tool — toggling visibility
        inside a QMenu/QWidgetAction proved unreliable (the menu
        caches size on first show, so rows that become visible later
        get clipped). Instead, each row's controls are enabled only
        when they apply to the active tool, so the menu height stays
        constant and the user can see at a glance what's available."""
        tool = self._mw._current_tool
        is_text = tool in ("text", "edit_text")
        is_shape = tool in ("rect", "ellipse")
        self._width_row.setVisible(True)
        self._opacity_row.setVisible(True)
        self._size_row.setVisible(True)
        self._fill_row.setVisible(True)
        self._width_row.setEnabled(not is_text)
        self._opacity_row.setEnabled(not is_text)
        self._size_row.setEnabled(is_text)
        self._fill_row.setEnabled(is_shape)

        tab = self._mw._current_pdf_tab()
        if tab is not None:
            width = tab.tool_width(tool)
            opacity = tab.tool_opacity(tool)
            current_color = tab.tool_color(tool)
        else:
            d = TOOL_DEFAULTS.get(tool, {})
            width = d.get("width", 2.0)
            opacity = d.get("opacity", 100)
            current_color = d.get("color", "")
        self._mark_active_color(current_color)
        self._width_slider.blockSignals(True)
        self._width_slider.setValue(max(1, min(30, int(round(width)))))
        self._width_slider.blockSignals(False)
        self._width_lbl.setText(f"{int(round(width))} pt")
        self._size_spin.blockSignals(True)
        self._size_spin.setValue(float(width))
        self._size_spin.blockSignals(False)
        self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(int(opacity))
        self._opacity_slider.blockSignals(False)
        self._opacity_lbl.setText(f"{int(opacity)}%")
        if is_shape:
            filled = tab.tool_filled(tool) if tab is not None else False
            self._fill_check.blockSignals(True)
            self._fill_check.setChecked(bool(filled))
            self._fill_check.blockSignals(False)
            self._fill_color_btn.setEnabled(bool(filled))
            fc = (tab.tool_fill_color(tool)
                  if tab is not None else None) or current_color
            self._update_fill_swatch(fc)
        # Nudge the QMenu to re-measure when rows toggle.
        self.adjustSize()
        menu = getattr(self._mw, "_options_menu", None)
        if menu is not None:
            menu.adjustSize()

    def _apply_color(self, color: str) -> None:
        tool = self._mw._current_tool
        tab = self._mw._current_pdf_tab()
        if tab is not None:
            tab.set_tool_color(color, tool)
        # Update the toolbar tool button icon's tint so the user can
        # see at a glance what colour their pen / line / rect will
        # draw with.
        self._mw._refresh_tool_icon(tool)
        self._mark_active_color(color)
        self._mw._close_options_menu()

    def _on_custom(self) -> None:
        tool = self._mw._current_tool
        tab = self._mw._current_pdf_tab()
        current = (tab.tool_color(tool) if tab is not None else "#000000")
        chosen = QColorDialog.getColor(QColor(current), self,
                                       "Choose custom colour")
        if chosen.isValid():
            if tab is not None:
                tab.set_tool_color(chosen.name(), tool)
            self._mw._refresh_tool_icon(tool)
            self._mark_active_color(chosen.name())
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

    def _on_fill(self, checked: bool) -> None:
        tab = self._mw._current_pdf_tab()
        if tab is not None:
            tab.set_tool_filled(checked, self._mw._current_tool)
        self._fill_color_btn.setEnabled(checked)

    def _on_fill_color(self) -> None:
        tool = self._mw._current_tool
        tab = self._mw._current_pdf_tab()
        if tab is None:
            return
        current = tab.tool_fill_color(tool) or tab.tool_color(tool)
        chosen = QColorDialog.getColor(QColor(current), self,
                                       "Choose fill colour")
        if chosen.isValid():
            tab.set_tool_fill_color(chosen.name(), tool)
            self._update_fill_swatch(chosen.name())

    def _update_fill_swatch(self, color: Optional[str]) -> None:
        c = color or "#888888"
        self._fill_color_btn.setStyleSheet(
            f"QToolButton {{ background:{c}; border:1px solid #555;"
            "border-radius:3px; } "
            "QToolButton:hover { border:2px solid #000; }"
        )


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
    # Drawing tools that take a colour / width / opacity popup. Their
    # toolbar icons re-tint to the active tool colour; other tools
    # (hand, select, note, signature, erase) keep their palette tint.
    OPTIONS_TOOLS = frozenset({
        "pen", "highlight", "line", "arrow", "rect", "ellipse",
        "text", "edit_text",
    })

    def __init__(self, theme_name: str = "Light") -> None:
        super().__init__()
        self._theme_name = theme_name
        self._theme = themes.THEMES.get(theme_name, themes.THEMES["Light"])

        self.setWindowIcon(app_icon())
        self.resize(1280, 860)
        # Accept PDFs dragged from the file manager onto the window.
        self.setAcceptDrops(True)

        self._tabs = QTabWidget(self)
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        # Empty pane shouldn't be a white slab — match the grey of the
        # PdfTab viewport so "no document open" reads the same as
        # "document open but with margin around the page".
        self._tabs.setStyleSheet(
            "QTabWidget::pane { background-color: #808080; border: none; }"
        )
        self.setCentralWidget(self._tabs)

        self._current_tool = "hand"
        # Side panel — a QTabWidget holding the page thumbnails and the
        # document outline (TOC) — lives in a dock so the user can
        # hide/move it. Built before the menus so View → Show Side
        # Panel can hook its toggleViewAction.
        self._thumbs = ThumbnailPanel(self)
        self._outline = OutlinePanel(self)
        self._side_tabs = QTabWidget(self)
        self._side_tabs.addTab(self._thumbs, "Pages")
        self._side_tabs.addTab(self._outline, "Contents")
        self._thumbs_dock = QDockWidget("Document", self)
        self._thumbs_dock.setObjectName("PagesDock")
        self._thumbs_dock.setWidget(self._side_tabs)
        self._thumbs_dock.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
        )
        self.addDockWidget(Qt.LeftDockWidgetArea, self._thumbs_dock)
        self._thumbs.page_clicked.connect(self._goto_page)
        self._outline.page_clicked.connect(self._goto_page)
        # Thumbnail rendering reports progress so the status-bar
        # loading bar can show how much of a long PDF has been
        # rasterised into the side panel.
        self._thumbs.rendering_progress.connect(self._on_render_progress)
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
        # Zoom shortcuts mirror the browser convention: Ctrl++ /
        # Ctrl+= for zoom in (= is the unshifted key on most US
        # keyboards), Ctrl+- for zoom out, Ctrl+0 for fit to width.
        zoom_in_act = QAction(icon("zoom_in"), "Zoom &In", self)
        zoom_in_act.setShortcuts([QKeySequence("Ctrl++"),
                                  QKeySequence("Ctrl+=")])
        zoom_in_act.triggered.connect(self._zoom_in)
        m_view.addAction(zoom_in_act)
        zoom_out_act = QAction(icon("zoom_out"), "Zoom &Out", self,
                               shortcut="Ctrl+-", triggered=self._zoom_out)
        m_view.addAction(zoom_out_act)
        fit_width_act = QAction(icon("fit_width"), "Fit &Width", self,
                                shortcut="Ctrl+0",
                                triggered=self._fit_width)
        m_view.addAction(fit_width_act)
        m_view.addAction(QAction(icon("fit_page"), "Fit &Page", self,
                                 triggered=self._noop))
        m_view.addSeparator()
        m_view.addAction(QAction("Rotate &Left", self, triggered=self._noop))
        m_view.addAction(QAction("Rotate &Right", self, triggered=self._noop))
        m_view.addSeparator()
        toggle_thumbs = self._thumbs_dock.toggleViewAction()
        toggle_thumbs.setText("Show Page &Thumbnails")
        toggle_thumbs.setIcon(icon("thumbs"))
        m_view.addAction(toggle_thumbs)
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

        # Plain file actions + undo/redo (mirrored from the Edit menu
        # so the user has fast keyboard-or-mouse access).
        for name, tip, handler in (
            ("open", "Open PDF (Ctrl+O)", self._open),
            ("save", "Save (Ctrl+S)",     self._save),
            ("undo", "Undo (Ctrl+Z)",     self._undo),
            ("redo", "Redo (Ctrl+Y)",     self._redo),
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
        tools = [
            ("hand",      "Hand — pan the document"),
            ("select",    "Select — click an annotation; Delete removes it"),
            ("pen",       "Pen"),
            ("highlight", "Highlight"),
            ("text",      "Text (add new)"),
            ("edit_text", "Edit existing text"),
            ("move_text", "Move a paragraph — drag to reposition"),
            ("line",      "Line"),
            ("arrow",     "Arrow"),
            ("rect",      "Rectangle"),
            ("ellipse",   "Ellipse"),
            ("note",      "Sticky Note"),
            ("signature", "Signature"),
            ("erase",     "Eraser — click an annotation to delete it"),
        ]
        for name, tip in tools:
            if name in self.OPTIONS_TOOLS:
                btn = _ToolButton(self, name, self)
                btn.setMenu(self._options_menu)
                btn.setPopupMode(QToolButton.MenuButtonPopup)
                # Tint the icon to the tool's stored default colour so
                # the toolbar reads as the user's palette at a glance.
                default_color = TOOL_DEFAULTS.get(name, {}).get("color")
                btn.setIcon(icon(name, color=default_color)
                            if default_color else icon(name))
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
        self._tool_buttons["hand"].setChecked(True)

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

    def _refresh_tool_icon(self, tool: str) -> None:
        """Re-tint a tool button's icon to the colour currently picked
        for that tool on the active tab. Only applies to drawing tools
        that take a colour (OPTIONS_TOOLS) — hand / select / note /
        signature / erase keep their semantic palette colour."""
        if tool not in self.OPTIONS_TOOLS:
            return
        btn = self._tool_buttons.get(tool)
        if btn is None:
            return
        tab = self._current_pdf_tab()
        color = (tab.tool_color(tool) if tab is not None
                 else TOOL_DEFAULTS.get(tool, {}).get("color"))
        if color:
            btn.setIcon(icon(tool, color=color))

    def _build_statusbar(self) -> None:
        sb = QStatusBar(self)
        self.setStatusBar(sb)
        self._lbl_page = QLabel("—")
        self._lbl_zoom = QLabel("100%")
        self._lbl_tool = QLabel("Select")
        self._lbl_branch = QLabel("")
        # Progress bar — hidden when idle, shown while opening a PDF
        # or rendering thumbnails. Determinate when total > 0,
        # indeterminate (busy) when range == (0, 0).
        self._progress = QProgressBar(self)
        self._progress.setMaximumWidth(180)
        self._progress.setMaximumHeight(14)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        sb.addWidget(self._lbl_page)
        sb.addPermanentWidget(self._progress)
        sb.addPermanentWidget(self._lbl_tool)
        sb.addPermanentWidget(self._lbl_zoom)
        sb.addPermanentWidget(self._lbl_branch)

    def _on_render_progress(self, current: int, total: int) -> None:
        """Slot for ThumbnailPanel.rendering_progress — drives the
        status-bar progress bar while the side panel rasterises a
        document's pages."""
        if total <= 0 or current >= total:
            self._progress.setVisible(False)
            self._progress.setRange(0, 100)
            self._progress.setValue(0)
            return
        self._progress.setRange(0, total)
        self._progress.setValue(current)
        self._progress.setVisible(True)

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

    def _on_tab_changed(self, _idx: int) -> None:
        self._refresh_status()
        self._refresh_thumbs()

    def _refresh_thumbs(self) -> None:
        tab = self._current_pdf_tab()
        doc = getattr(tab, "_doc", None) if tab is not None else None
        self._thumbs.set_document(doc)
        self._outline.set_document(doc)

    def _goto_page(self, page_idx: int) -> None:
        tab = self._current_pdf_tab()
        if tab is not None:
            tab.scroll_to_page(page_idx)

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

    # ----- drag & drop -----

    @staticmethod
    def _pdf_urls(mime) -> list[Path]:
        """Return the list of .pdf file paths in a QMimeData drop, in
        the order they appeared. Non-PDF URLs are filtered out — we
        don't want a stray .docx silently ignored to surprise the
        user, but rejecting at the dragEnter stage is the friendlier
        UX, so this helper is shared by both events."""
        paths: list[Path] = []
        if not mime.hasUrls():
            return paths
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            if p.suffix.lower() == ".pdf" and p.is_file():
                paths.append(p)
        return paths

    def dragEnterEvent(self, event):  # noqa: N802 — Qt override
        if self._pdf_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802 — Qt override
        # Needed so the drop cursor stays "copy" the whole way across
        # the window; without it some Qt platforms revert to "no-drop"
        # mid-drag.
        if self._pdf_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802 — Qt override
        paths = self._pdf_urls(event.mimeData())
        if not paths:
            event.ignore()
            return
        for p in paths:
            self.open_path(p)
        event.acceptProposedAction()

    def _close_tab(self, idx: int) -> None:
        if idx < 0:
            return
        w = self._tabs.widget(idx)
        self._tabs.removeTab(idx)
        if isinstance(w, PdfTab):
            w.close_doc()
        if w is not None:
            w.deleteLater()
        self._refresh_thumbs()
        self._refresh_status()

    # ----- file actions (stubs — concrete logic in pdftab v0.3) -----

    def open_path(self, path: Path) -> None:
        # Indeterminate progress while fitz.open + the first render
        # run — these are fast for small PDFs but can take a moment
        # for hundreds of pages.
        self._progress.setRange(0, 0)
        self._progress.setVisible(True)
        QApplication.processEvents()
        try:
            tab = PdfTab(path, self)
        except Exception as e:
            self._progress.setVisible(False)
            self._progress.setRange(0, 100)
            QMessageBox.critical(
                self, "Open failed",
                f"Could not open <b>{path.name}</b>:<br>{e}",
            )
            return
        # Reset to determinate; the thumbnail rendering signal will
        # take over from here.
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        self._tabs.addTab(tab, path.name)
        self._tabs.setCurrentWidget(tab)
        tab.set_tool(self._current_tool)
        self._push_recent(path)
        # Refresh all tinted tool icons to match this tab's tool
        # settings (each PdfTab keeps its own colour state).
        for t in self.OPTIONS_TOOLS:
            self._refresh_tool_icon(t)
        self._refresh_thumbs()
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
        """Rich About dialog: app + author bio + every library the
        running app actually loads, each with a one-line description
        of why it's here. Same shape as KherveTeX's About so the suite
        feels consistent."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser

        def _ver(modname: str) -> str:
            try:
                mod = __import__(modname)
                return getattr(mod, "__version__", "") or "(unknown)"
            except Exception:
                return "not installed"

        import sys
        py_ver = sys.version.split()[0]

        libraries = [
            ("PySide6", _ver("PySide6"),
             "Official Qt for Python bindings — drives the entire GUI: "
             "tabs, toolbar, options popup, the QGraphicsView canvas, "
             "the rich-text Edit-Text dialog.",
             "https://doc.qt.io/qtforpython-6/"),
            ("PyMuPDF (fitz)", _ver("pymupdf"),
             "Page-level access to PDFs — rasterising pages for the "
             "view, loading / baking annotations (ink, rect, ellipse, "
             "line, highlight, sticky-note, free-text), redaction and "
             "HTML-box insertion for the Edit-Text feature.",
             "https://pymupdf.readthedocs.io/"),
            ("pikepdf", _ver("pikepdf"),
             "Higher-level PDF library used for page-level operations "
             "(merge, split, reorder) that fall outside PyMuPDF's "
             "comfort zone.",
             "https://pikepdf.readthedocs.io/"),
            ("pygit2", _ver("pygit2"),
             "libgit2 bindings — surfaces the per-document Git "
             "metadata in the title bar (commit count + short SHA + "
             "subject of HEAD).",
             "https://www.pygit2.org/"),
            ("qtawesome", _ver("qtawesome"),
             "Font Awesome / Material Design Icons glyphs rendered as "
             "QIcons at runtime — every toolbar and menu icon. No "
             "PNG/SVG files ship with the app.",
             "https://github.com/spyder-ide/qtawesome"),
        ]

        rows = []
        for name, ver, role, url in libraries:
            rows.append(
                "<tr>"
                f"<td valign='top' style='padding:6px 14px 6px 0'>"
                f"<b>{name}</b><br>"
                f"<span style='color:#666;font-size:9pt'>{ver}</span></td>"
                f"<td valign='top' style='padding:6px 0'>{role}<br>"
                f"<a href='{url}'>{url}</a></td>"
                "</tr>"
            )
        lib_table = (
            "<table cellpadding='0' cellspacing='0' "
            "style='border-collapse:collapse'>"
            + "".join(rows) +
            "</table>"
        )

        html = (
            f"<h2 style='margin-bottom:2pt'>KhervePDF "
            f"{version_string()}</h2>"
            f"<p style='color:#666;margin-top:0'>WYSIWYG PDF viewer &amp; "
            f"annotation editor with Git history.</p>"
            f"<p><a href='https://github.com/gkerherve/KhervePDF'>"
            f"github.com/gkerherve/KhervePDF</a> &nbsp;·&nbsp; "
            f"GPL-3.0</p>"
            f"<hr>"
            f"<h3>About the author</h3>"
            f"<p><b>Gwilherm Kerherv&eacute;</b> &nbsp;—&nbsp; "
            f"Research Associate, Department of Materials, "
            f"<a href='https://www.imperial.ac.uk/materials/'>"
            f"Imperial College London</a>.</p>"
            f"<p>Works on surface analysis and X-ray Photoelectron "
            f"Spectroscopy (XPS), with a focus on materials for energy "
            f"storage and catalysis. Maintains a small constellation "
            f"of open-source tools, mostly for the XPS community:</p>"
            f"<ul>"
            f"<li><a href='https://github.com/gkerherve/KherveFitting'>"
            f"KherveFitting</a> — peak fitting for XPS spectra.</li>"
            f"<li><a href='https://github.com/gkerherve/spe_reader'>"
            f"spe-xps-reader</a> — open reader for PHI Instruments "
            f"SPE binary files.</li>"
            f"<li><a href='https://github.com/gkerherve/KherveTeX'>"
            f"KherveTeX</a> — WYSIWYG LaTeX editor.</li>"
            f"<li><a href='https://github.com/gkerherve/KherveSheet'>"
            f"KherveSheet</a> — Origin-style scientific workbook.</li>"
            f"<li><b>KhervePDF</b> — this app: PDF viewing &amp; "
            f"annotation with the same look &amp; feel as the rest "
            f"of the suite.</li>"
            f"</ul>"
            f"<p>KhervePDF was built to round out the trio: write "
            f"papers in KherveTeX, crunch and plot data in "
            f"KherveSheet, and mark up PDFs (referee reports, "
            f"reading lists, manuscripts) in KhervePDF — all "
            f"sharing the same themes, the same icon style, and the "
            f"same per-document Git history.</p>"
            f"<p>"
            f"<a href='mailto:g.kerherve@imperial.ac.uk'>"
            f"g.kerherve@imperial.ac.uk</a> &nbsp;·&nbsp; "
            f"<a href='mailto:gwilherm.kerherve@gmail.com'>"
            f"gwilherm.kerherve@gmail.com</a>"
            f"</p>"
            f"<hr>"
            f"<h3>Libraries</h3>"
            f"<p style='color:#666;margin-bottom:6pt'>Python "
            f"{py_ver}</p>"
            f"{lib_table}"
            f"<p style='color:#888;margin-top:14pt;font-size:9pt'>"
            f"Every toolbar icon is drawn at runtime via qtawesome — "
            f"no .ico / .png / .svg ships with the app. Annotations "
            f"round-trip through real PDF annotation objects "
            f"(ink, square, circle, line, highlight, text, "
            f"free-text), so files stay editable across save cycles "
            f"and in other PDF readers."
            f"</p>"
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("About KhervePDF")
        dlg.resize(720, 760)
        browser = QTextBrowser(dlg)
        browser.setOpenExternalLinks(True)
        browser.setHtml(html)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        layout = QVBoxLayout(dlg)
        layout.addWidget(browser, 1)
        layout.addWidget(buttons)
        dlg.exec()

    def _noop(self) -> None:
        # Stub for actions not yet implemented in this version.
        pass
