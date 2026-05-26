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

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QImage, QKeySequence, QPainter,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
    QDialog, QDockWidget, QDoubleSpinBox, QFileDialog, QGridLayout,
    QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QProgressBar,
    QPushButton, QSlider, QStatusBar, QTabBar, QTabWidget, QToolBar,
    QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from . import digital_sign, git_backend, page_ops, themes, version_string
from .find_bar import FindBar
from .history_dialog import HistoryDialog
from .icons import app_icon, icon
from .outline import OutlinePanel
from .pdftab import PdfTab, TOOL_DEFAULTS
from .remote_dialog import RemoteDialog
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


class _DetachableTabBar(QTabBar):
    """Tab bar whose tabs can be torn off into their own KhervePDF
    process. Drag a tab outside the tab bar's vertical strip and the
    PDF the tab is hosting is opened in a new instance, then closed
    here.

    Implemented as a subclass override of the mouse-release event so
    we don't fight Qt's internal tab-reordering machinery (which uses
    press / move). The right-click menu also offers an explicit
    "Open in new window" entry — handy on touchpads where a precise
    drag-out is awkward.
    """

    def __init__(self, parent: QTabWidget) -> None:
        super().__init__(parent)
        self.setMovable(True)
        self.setUsesScrollButtons(True)
        self._tab_widget = parent
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def mouseReleaseEvent(self, ev):  # noqa: N802
        super().mouseReleaseEvent(ev)
        if ev.button() != Qt.LeftButton:
            return
        # If the mouse left the tab bar's geometry by more than a
        # small fudge, treat it as a tear-off.
        if self.rect().adjusted(-6, -6, 6, 6).contains(ev.pos()):
            return
        idx = self.tabAt(self._press_pos) if hasattr(self, "_press_pos") \
            else -1
        if idx < 0:
            idx = self.currentIndex()
        if idx < 0:
            return
        self._detach_tab(idx)

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._press_pos = ev.pos()
        super().mousePressEvent(ev)

    def _show_context_menu(self, pos) -> None:
        idx = self.tabAt(pos)
        if idx < 0:
            return
        menu = QMenu(self)
        act = menu.addAction("Open in new window")
        act.triggered.connect(lambda: self._detach_tab(idx))
        menu.exec(self.mapToGlobal(pos))

    def _detach_tab(self, idx: int) -> None:
        widget = self._tab_widget.widget(idx)
        path = getattr(widget, "path", None)
        if path is None:
            return
        import subprocess
        # sys.argv[0] points at the script the user launched
        # (KhervePDF.py or a frozen .exe). sys.executable is the
        # Python interpreter. Together they reproduce the way this
        # process was started — best chance the new process runs
        # under the same environment.
        try:
            entry = Path(sys.argv[0]).resolve()
        except Exception:
            entry = None
        if entry is not None and entry.exists() and entry.suffix == ".py":
            cmd = [sys.executable, str(entry), str(path)]
        elif entry is not None and entry.exists():
            cmd = [str(entry), str(path)]
        else:
            cmd = [sys.executable, "-m", "khervepdf", str(path)]
        try:
            subprocess.Popen(cmd, close_fds=True)
        except Exception as e:
            QMessageBox.warning(
                self.window(), "Open in new window",
                f"Could not spawn a new KhervePDF process:\n{e}",
            )
            return
        # Close this tab in the current window.
        mw = self.window()
        if hasattr(mw, "_close_tab"):
            mw._close_tab(idx)


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
        self._tabs.setTabBar(_DetachableTabBar(self._tabs))
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
        self._thumbs.page_reorder_requested.connect(self._on_page_reorder)
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
        m_file.addAction(QAction(icon("export_png"),
                                 "Export pages as &PNG / JPEG…", self,
                                 triggered=self._export_images))
        m_file.addAction(QAction(icon("export_txt"),
                                 "Export &Text…", self,
                                 triggered=self._export_text))
        m_file.addAction(QAction(icon("save_as"),
                                 "&Compress / shrink…", self,
                                 triggered=self._compress_pdf))
        m_file.addAction(QAction(icon("save_as"),
                                 "Encr&ypt / password protect…", self,
                                 triggered=self._encrypt_pdf))
        m_file.addAction(QAction(icon("signature"),
                                 "Di&gitally sign (PKCS#12)…", self,
                                 triggered=self._digitally_sign))
        m_file.addAction(QAction(icon("print"), "&Print…", self,
                                 shortcut="Ctrl+P", triggered=self._print))
        m_file.addAction(QAction(icon("print"), "Print Pre&view…", self,
                                 shortcut="Ctrl+Shift+P",
                                 triggered=self._print_preview))
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
        m_edit.addAction(QAction(icon("find"), "&Find…", self,
                                 shortcut="Ctrl+F",
                                 triggered=self._show_find_bar))

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
        m_pages.addAction(QAction(icon("page_insert"),
                                  "Insert &Blank Page", self,
                                  triggered=self._insert_blank))
        m_pages.addAction(QAction(icon("page_delete"),
                                  "&Delete Current Page", self,
                                  triggered=self._delete_page))
        m_pages.addSeparator()
        m_pages.addAction(QAction(icon("rotate_l"),
                                  "Rotate Page &Left", self,
                                  triggered=self._rotate_left))
        m_pages.addAction(QAction(icon("rotate_r"),
                                  "Rotate Page &Right", self,
                                  triggered=self._rotate_right))
        m_pages.addSeparator()
        m_pages.addAction(QAction(icon("page_merge"),
                                  "&Merge PDF(s)…", self,
                                  triggered=self._merge_pdf))
        m_pages.addAction(QAction(icon("page_split"),
                                  "&Split into one PDF per page…", self,
                                  triggered=self._split_pdf))
        m_pages.addAction(QAction(icon("page_split"),
                                  "E&xtract pages…", self,
                                  triggered=self._extract_pages))
        m_pages.addSeparator()
        m_pages.addAction(QAction(icon("text"),
                                  "&Watermark every page…", self,
                                  triggered=self._add_watermark))
        m_pages.addAction(QAction(icon("text"),
                                  "&Number every page…", self,
                                  triggered=self._add_page_numbers))

        m_git = mb.addMenu("&Git")
        m_git.addAction(QAction(icon("commit"), "Commit &Now", self,
                                triggered=self._git_commit_now))
        m_git.addAction(QAction(icon("history"), "&History…", self,
                                triggered=self._git_history))
        m_git.addAction(QAction(icon("remote"), "&Remote / Push…", self,
                                triggered=self._git_remote))

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
            ("image", "Insert image from file (Ctrl+V to paste)",
             self._insert_image_from_file),
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
        # Zoom-level selector — typeable combobox next to the zoom
        # icons. Picks between Fit Width and a set of common
        # percentages, or accepts a custom "%" entry typed in.
        self._zoom_combo = QComboBox(self)
        self._zoom_combo.setEditable(True)
        self._zoom_combo.setMaximumWidth(110)
        self._zoom_combo.setToolTip(
            "Zoom level — pick a preset or type a percentage"
        )
        # Show the magnifier icon as the combo's leading visual cue.
        zoom_label = QToolButton(self)
        zoom_label.setIcon(icon("zoom_in"))
        zoom_label.setEnabled(False)
        zoom_label.setStyleSheet(
            "QToolButton { background:transparent; border:none; }"
        )
        tb.addWidget(zoom_label)
        for label in ("Fit Width", "50%", "75%", "100%", "125%",
                      "150%", "200%", "300%", "400%"):
            self._zoom_combo.addItem(label)
        self._zoom_combo.setCurrentText("Fit Width")
        self._zoom_combo.activated.connect(
            lambda _i: self._apply_zoom_combo()
        )
        # Hitting Enter in the line edit applies the typed value.
        self._zoom_combo.lineEdit().returnPressed.connect(
            self._apply_zoom_combo
        )
        tb.addWidget(self._zoom_combo)

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
        # Keep the title compact — just version + filename. The
        # build SHA in version_string is enough to identify the
        # running code; the commit subject was too noisy.
        self.setWindowTitle(f"KhervePDF {version_string()} — {name}")

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

    def _on_page_reorder(self, source: int, target: int) -> None:
        """Drag-drop in the thumbnails panel: move page `source` so
        it ends up just before pre-move index `target` (PyMuPDF
        Document.move_page semantics — see thumbnails.dropEvent).
        Remap in-memory annotations so they follow their original
        page to the new index."""
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        n = t._doc.page_count
        if not (0 <= source < n and 0 <= target <= n):
            return
        if target == source or target == source + 1:
            return
        t._push_undo(include_doc=True)
        from dataclasses import replace
        # Compute the moved page's final 0-based index. PyMuPDF gives
        # us:
        #   source < target → final index = target - 1
        #   source > target → final index = target
        if source < target:
            moved_to = target - 1
        else:
            moved_to = target
        new_annots = []
        for a in t._annots:
            new_idx = a.page_idx
            if a.page_idx == source:
                new_idx = moved_to
            elif source < target and source < a.page_idx < target:
                new_idx = a.page_idx - 1
            elif source > target and target <= a.page_idx < source:
                new_idx = a.page_idx + 1
            new_annots.append(replace(a, page_idx=new_idx))
        t._annots = new_annots
        try:
            t._doc.move_page(source, target)
        except Exception as e:
            QMessageBox.warning(self, "Reorder",
                                f"Could not move page: {e}")
            return
        t._render_all()
        self._refresh_thumbs()

    def _refresh_status(self) -> None:
        w = self._tabs.currentWidget()
        if isinstance(w, PdfTab):
            self._lbl_page.setText(f"Page 1 of {w.page_count()}")
            self._lbl_zoom.setText(f"{w.zoom_percent()}%")
            branch = git_backend.current_branch(w.path)
            self._lbl_branch.setText(
                f"⎇ {branch}" if branch else ""
            )
        else:
            self._lbl_page.setText("—")
            self._lbl_zoom.setText("—")
            self._lbl_branch.setText("")
        # Keep the toolbar's zoom combo in step with the actual zoom
        # (the user can change it via the combo, the +/- buttons,
        # Ctrl+wheel, Ctrl±, or a window resize triggering auto-fit).
        if hasattr(self, "_zoom_combo"):
            self._sync_zoom_combo()
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

    def _apply_zoom_combo(self) -> None:
        text = self._zoom_combo.currentText().strip()
        tab = self._current_pdf_tab()
        if tab is None:
            return
        if text.lower().startswith("fit"):
            tab.fit_width()
        else:
            pct = text.rstrip("% ").strip()
            try:
                val = float(pct) / 100.0
            except ValueError:
                self._sync_zoom_combo()
                return
            tab._auto_fit_width = False
            tab._set_zoom(val)
        self._refresh_status()
        self._sync_zoom_combo()

    def _sync_zoom_combo(self) -> None:
        """Push the active tab's zoom into the combo's text. Called
        after manual zoom (buttons / Ctrl+wheel / Ctrl±) so the combo
        always reflects reality."""
        tab = self._current_pdf_tab()
        if tab is None:
            return
        text = "Fit Width" if tab._auto_fit_width \
            else f"{tab.zoom_percent()}%"
        self._zoom_combo.blockSignals(True)
        idx = self._zoom_combo.findText(text)
        if idx >= 0:
            self._zoom_combo.setCurrentIndex(idx)
        else:
            self._zoom_combo.setCurrentText(text)
        self._zoom_combo.blockSignals(False)

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

    def _show_find_bar(self) -> None:
        """Open the floating Find bar at the top of the canvas
        (lazy-instantiated). The bar searches across every page of
        the active PDF and jumps to each match with a yellow
        overlay rect."""
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        if getattr(self, "_find_bar", None) is None:
            self._find_bar = FindBar(self)
            self._find_bar.setParent(self)
        self._find_bar.set_tab(t)
        # Centre at the top of the viewport.
        x = (self.width() - max(self._find_bar.sizeHint().width(), 420)) // 2
        self._find_bar.setGeometry(x, 60,
                                   max(self._find_bar.sizeHint().width(),
                                       420),
                                   self._find_bar.sizeHint().height())
        self._find_bar.show_and_focus()
        self._find_bar.raise_()

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
        committed = git_backend.commit_file(
            saved, message=f"Save {saved.name}",
        )
        suffix = " · committed to git" if committed else ""
        self.statusBar().showMessage(f"Saved {saved}{suffix}", 4000)
        self._refresh_status()

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
        committed = git_backend.commit_file(
            saved, message=f"Save {saved.name}",
        )
        suffix = " · committed to git" if committed else ""
        self.statusBar().showMessage(f"Saved {saved}{suffix}", 4000)
        self._refresh_status()

    # ----- Pages menu -----

    def _merge_pdf(self) -> None:
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Choose PDF(s) to insert after the current page",
            str(t.path.parent), "PDF files (*.pdf);;All files (*)",
        )
        if not paths:
            return
        t._push_undo(include_doc=True)
        target_after = t.current_page_index()
        for p in paths:
            try:
                added = page_ops.merge_pdf_into(
                    t._doc, Path(p), after_page_idx=target_after,
                )
                # Shift annotations that sit on pages after the
                # insertion point so they stay attached to the same
                # visual page.
                t.shift_annot_pages(target_after + 1, added)
                target_after += added
            except Exception as e:
                QMessageBox.warning(self, "Merge",
                                    f"Failed to merge {p}:\n{e}")
        t._render_all()
        self._refresh_thumbs()
        self.statusBar().showMessage(
            f"Merged {len(paths)} PDF(s)", 4000,
        )

    def _delete_page(self) -> None:
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        if t._doc.page_count <= 1:
            QMessageBox.information(self, "Delete page",
                                    "Cannot delete the last page.")
            return
        idx = t.current_page_index()
        ok = QMessageBox.question(
            self, "Delete page",
            f"Delete page {idx + 1} of {t._doc.page_count}?",
        )
        if ok != QMessageBox.Yes:
            return
        t._push_undo(include_doc=True)
        t.drop_annots_on_page(idx)
        # Shift down everything after by -1.
        t.shift_annot_pages(idx + 1, -1)
        page_ops.delete_page(t._doc, idx)
        t._render_all()
        self._refresh_thumbs()

    def _rotate_left(self) -> None:
        self._rotate_current(-90)

    def _rotate_right(self) -> None:
        self._rotate_current(90)

    def _rotate_current(self, delta: int) -> None:
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        t._push_undo(include_doc=True)
        page_ops.rotate_page(t._doc, t.current_page_index(), delta)
        t._render_all()
        self._refresh_thumbs()

    def _insert_blank(self) -> None:
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        idx = t.current_page_index()
        # Use the current page's size as the default for the new
        # blank — keeps the document looking uniform.
        page = t._doc[idx]
        t._push_undo(include_doc=True)
        # New page goes AFTER idx, so any annotation on a page
        # after idx shifts by +1.
        t.shift_annot_pages(idx + 1, +1)
        page_ops.insert_blank(t._doc, idx,
                              page.rect.width, page.rect.height)
        t._render_all()
        self._refresh_thumbs()

    def _add_watermark(self) -> None:
        """Stamp the user's chosen text diagonally across every
        page. The text is rendered with insert_textbox at 45° on a
        page-sized rect; opacity is moderate (~30%) so the original
        content reads through."""
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        from PySide6.QtWidgets import (
            QDialog as _D, QDialogButtonBox as _DB,
            QFormLayout as _FL, QLineEdit as _LE, QSpinBox as _SB,
        )
        dlg = _D(self)
        dlg.setWindowTitle("Watermark every page")
        fl = _FL(dlg)
        text_le = _LE(dlg)
        text_le.setText("DRAFT")
        fl.addRow("Text:", text_le)
        size = _SB(dlg)
        size.setRange(20, 200)
        size.setValue(72)
        size.setSuffix(" pt")
        fl.addRow("Size:", size)
        bb = _DB(_DB.Ok | _DB.Cancel, parent=dlg)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        fl.addWidget(bb)
        if dlg.exec() != _D.Accepted:
            return
        text = text_le.text().strip()
        if not text:
            return
        import fitz as _fitz
        t._push_undo(include_doc=True)
        fontsize = float(size.value())
        for i in range(t._doc.page_count):
            page = t._doc[i]
            r = page.rect
            try:
                # 45° rotation, centred. PyMuPDF's insert_textbox
                # supports rotate=45 via the matrix-rotated rect
                # approach — we use insert_text with a manual
                # rotation matrix via the morph parameter.
                tw = _fitz.get_text_length(text, fontsize=fontsize,
                                           fontname="helv")
                cx, cy = r.x0 + r.width / 2, r.y0 + r.height / 2
                # Place baseline at the centre, rotate -45°.
                page.insert_text(
                    (cx - tw / 2, cy + fontsize / 3),
                    text, fontsize=fontsize, fontname="helv",
                    color=(0.7, 0.7, 0.7),
                    morph=(_fitz.Point(cx, cy),
                           _fitz.Matrix(45)),
                )
            except Exception:
                continue
        t._render_all()
        self.statusBar().showMessage(
            f"Watermarked {t._doc.page_count} page(s)", 4000,
        )

    def _add_page_numbers(self) -> None:
        """Stamp "N / total" at the bottom-centre of every page."""
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        import fitz as _fitz
        t._push_undo(include_doc=True)
        total = t._doc.page_count
        for i in range(total):
            page = t._doc[i]
            r = page.rect
            txt = f"{i + 1} / {total}"
            try:
                tw = _fitz.get_text_length(txt, fontsize=10,
                                            fontname="helv")
                page.insert_text(
                    (r.x0 + (r.width - tw) / 2, r.y1 - 24),
                    txt, fontsize=10, fontname="helv",
                    color=(0.2, 0.2, 0.2),
                )
            except Exception:
                continue
        t._render_all()
        self.statusBar().showMessage(
            f"Numbered {total} page(s)", 4000,
        )

    def _digitally_sign(self) -> None:
        """Add a real PKCS#7 cryptographic signature to the active
        PDF (pyHanko, see digital_sign.py). The user supplies a
        PKCS#12 (.p12 / .pfx) file containing their certificate +
        private key; we ask for the password and the optional
        reason / location / contact metadata, then write a signed
        copy."""
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        if not digital_sign.is_available():
            QMessageBox.information(
                self, "Digital signature",
                "pyHanko isn't installed.\n\n"
                "Install with:\n"
                "    pip install pyHanko\n\n"
                f"({digital_sign.import_error()})",
            )
            return
        from PySide6.QtWidgets import (
            QDialog as _D, QDialogButtonBox as _DB,
            QFormLayout as _FL, QLineEdit as _LE, QPushButton as _PB,
        )
        dlg = _D(self)
        dlg.setWindowTitle("Digitally sign PDF")
        dlg.resize(560, 0)
        fl = _FL(dlg)
        p12_le = _LE(dlg)
        p12_le.setPlaceholderText("Path to .p12 / .pfx file")
        p12_btn = _PB("Browse…", dlg)

        def _pick():
            f, _ = QFileDialog.getOpenFileName(
                dlg, "Pick certificate", "",
                "PKCS#12 (*.p12 *.pfx);;All files (*)",
            )
            if f:
                p12_le.setText(f)

        p12_btn.clicked.connect(_pick)
        from PySide6.QtWidgets import QHBoxLayout as _HL, QWidget as _W
        row = _W(dlg)
        h = _HL(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(p12_le)
        h.addWidget(p12_btn)
        fl.addRow("Certificate:", row)
        pw_le = _LE(dlg)
        pw_le.setEchoMode(_LE.Password)
        fl.addRow("Password:", pw_le)
        reason_le = _LE(dlg)
        reason_le.setPlaceholderText("e.g. Approval, Reviewed")
        fl.addRow("Reason:", reason_le)
        loc_le = _LE(dlg)
        loc_le.setPlaceholderText("e.g. Imperial College London")
        fl.addRow("Location:", loc_le)
        contact_le = _LE(dlg)
        contact_le.setPlaceholderText("e.g. e-mail")
        fl.addRow("Contact:", contact_le)
        bb = _DB(_DB.Ok | _DB.Cancel, parent=dlg)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        fl.addWidget(bb)
        if dlg.exec() != _D.Accepted:
            return
        if not p12_le.text():
            QMessageBox.warning(self, "Sign", "Need a certificate.")
            return
        # The doc may have unsaved annotations — they need to be on
        # disk before pyHanko can read them.
        if t.is_dirty():
            ok = QMessageBox.question(
                self, "Save first?",
                "There are unsaved annotations. Save them into the "
                "PDF first so they're part of what gets signed?",
            )
            if ok == QMessageBox.Yes:
                try:
                    t.save_to_pdf()
                except Exception as e:
                    QMessageBox.warning(self, "Sign",
                                        f"Save failed: {e}")
                    return
        suggested = t.path.with_name(f"{t.path.stem}_signed.pdf")
        out_s, _ = QFileDialog.getSaveFileName(
            self, "Save signed PDF as", str(suggested),
            "PDF files (*.pdf);;All files (*)",
        )
        if not out_s:
            return
        ok, msg = digital_sign.sign_pdf(
            t.path, Path(out_s),
            Path(p12_le.text()), pw_le.text(),
            reason=reason_le.text(),
            location=loc_le.text(),
            contact_info=contact_le.text(),
        )
        if ok:
            self.statusBar().showMessage(
                f"Signed → {out_s}", 6000,
            )
        else:
            QMessageBox.warning(self, "Sign failed", msg)

    def _encrypt_pdf(self) -> None:
        """Save an encrypted copy of the active PDF. Two passwords:
        the *user* password is required to open the file; the *owner*
        password unlocks restrictions (print, copy, modify). Either
        may be left blank — at least one is required."""
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        import fitz as _fitz
        from PySide6.QtWidgets import (
            QDialog as _D, QDialogButtonBox as _DB,
            QFormLayout as _FL, QLineEdit as _LE,
        )
        dlg = _D(self)
        dlg.setWindowTitle("Encrypt PDF")
        fl = _FL(dlg)
        user_pw = _LE(dlg)
        user_pw.setEchoMode(_LE.Password)
        owner_pw = _LE(dlg)
        owner_pw.setEchoMode(_LE.Password)
        fl.addRow("User password (open):", user_pw)
        fl.addRow("Owner password (edit):", owner_pw)
        from PySide6.QtWidgets import QLabel as _L
        hint = _L(
            "Leave a field empty to skip that level. At least one is "
            "required. AES-256 used; readers without the user password "
            "won't see the document at all."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#555;")
        fl.addRow(hint)
        bb = _DB(_DB.Ok | _DB.Cancel, parent=dlg)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        fl.addWidget(bb)
        if dlg.exec() != _D.Accepted:
            return
        u = user_pw.text()
        o = owner_pw.text() or u
        if not u and not o:
            QMessageBox.warning(self, "Encrypt",
                                "Need at least one password.")
            return
        suggested = t.path.with_name(f"{t.path.stem}_encrypted.pdf")
        path_s, _ = QFileDialog.getSaveFileName(
            self, "Save encrypted PDF as", str(suggested),
            "PDF files (*.pdf);;All files (*)",
        )
        if not path_s:
            return
        try:
            # AES-256 with strict permission set on the owner side
            # (block printing / copying / modifications unless owner
            # password is provided). User password — when set —
            # gates open access entirely.
            perm = (_fitz.PDF_PERM_ACCESSIBILITY |
                    _fitz.PDF_PERM_PRINT)  # screen-reader OK; print OK
            t._doc.save(
                path_s,
                encryption=_fitz.PDF_ENCRYPT_AES_256,
                owner_pw=o, user_pw=u,
                permissions=perm,
                deflate=True, garbage=4,
            )
        except Exception as e:
            QMessageBox.warning(self, "Encrypt", str(e))
            return
        self.statusBar().showMessage(
            f"Saved encrypted PDF to {path_s}", 5000,
        )

    def _compress_pdf(self) -> None:
        """Save a recompressed copy of the active PDF. Uses the
        usual PyMuPDF compaction switches (deflate=True,
        garbage=4 — clean unused objects, deduplicate streams,
        and re-compress everything) without re-encoding embedded
        images. Reports size before / after."""
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        suggested = t.path.with_name(f"{t.path.stem}_compressed.pdf")
        path_s, _ = QFileDialog.getSaveFileName(
            self, "Save compressed PDF as", str(suggested),
            "PDF files (*.pdf);;All files (*)",
        )
        if not path_s:
            return
        try:
            t._doc.save(path_s, deflate=True, deflate_images=True,
                        deflate_fonts=True, garbage=4, clean=True)
        except Exception as e:
            QMessageBox.warning(self, "Compress", str(e))
            return
        try:
            before = t.path.stat().st_size
            after = Path(path_s).stat().st_size
            pct = (1.0 - after / before) * 100 if before else 0
            self.statusBar().showMessage(
                f"Compressed: {before / 1024:.0f} KB → "
                f"{after / 1024:.0f} KB ({pct:+.0f}%)", 6000,
            )
        except Exception:
            self.statusBar().showMessage(
                f"Saved compressed copy to {path_s}", 5000,
            )

    def _export_text(self) -> None:
        """Save every page's text as a single UTF-8 .txt file. Each
        page is separated by a form-feed (\\f) so downstream tools
        (less, pagers) can show page boundaries."""
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        suggested = t.path.with_suffix(".txt")
        path_s, _ = QFileDialog.getSaveFileName(
            self, "Export text", str(suggested),
            "Text files (*.txt);;All files (*)",
        )
        if not path_s:
            return
        chunks: list[str] = []
        for i in range(t._doc.page_count):
            try:
                chunks.append(t._doc[i].get_text("text"))
            except Exception:
                chunks.append("")
        try:
            Path(path_s).write_text("\f".join(chunks), encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Export text", str(e))
            return
        self.statusBar().showMessage(
            f"Wrote text of {t._doc.page_count} page(s) to {path_s}",
            5000,
        )

    def _export_images(self) -> None:
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        # Compact one-shot dialog: format radio + DPI spinbox + page
        # range. Reuse _parse_page_range so the input format matches
        # Extract pages.
        from PySide6.QtWidgets import (
            QButtonGroup as _BG, QDialog as _D, QDialogButtonBox as _DB,
            QFormLayout as _FL, QRadioButton as _RB, QSpinBox as _SB,
        )
        from PySide6.QtWidgets import QLineEdit as _LE
        dlg = _D(self)
        dlg.setWindowTitle("Export pages as images")
        fl = _FL(dlg)
        png_rb = _RB("PNG (lossless)", dlg)
        jpg_rb = _RB("JPEG (smaller)", dlg)
        png_rb.setChecked(True)
        rbg = _BG(dlg)
        rbg.addButton(png_rb)
        rbg.addButton(jpg_rb)
        fl.addRow("Format:", png_rb)
        fl.addRow("", jpg_rb)
        dpi = _SB(dlg)
        dpi.setRange(36, 600)
        dpi.setSingleStep(36)
        dpi.setValue(150)
        dpi.setSuffix(" dpi")
        fl.addRow("Resolution:", dpi)
        pages = _LE(dlg)
        pages.setText(f"1-{t._doc.page_count}")
        fl.addRow("Pages:", pages)
        bb = _DB(_DB.Ok | _DB.Cancel, parent=dlg)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        fl.addWidget(bb)
        if dlg.exec() != _D.Accepted:
            return
        indices = self._parse_page_range(pages.text(), t._doc.page_count)
        if not indices:
            QMessageBox.warning(self, "Export images",
                                "Couldn't parse that page range.")
            return
        out_dir = QFileDialog.getExistingDirectory(
            self, "Choose output directory", str(t.path.parent),
        )
        if not out_dir:
            return
        ext = "png" if png_rb.isChecked() else "jpg"
        fmt = "png" if png_rb.isChecked() else "jpeg"
        scale = dpi.value() / 72.0
        import fitz as _fitz
        matrix = _fitz.Matrix(scale, scale)
        out_root = Path(out_dir)
        width = len(str(t._doc.page_count))
        written = 0
        for n in indices:
            try:
                pix = t._doc[n].get_pixmap(
                    matrix=matrix, alpha=False, annots=True,
                )
                out_path = (out_root /
                            f"{t.path.stem}_p{n + 1:0{width}d}.{ext}")
                pix.save(str(out_path), output=fmt)
                written += 1
            except Exception as e:
                QMessageBox.warning(
                    self, "Export images",
                    f"Page {n + 1} failed: {e}",
                )
                break
        self.statusBar().showMessage(
            f"Wrote {written} image(s) to {out_dir}", 5000,
        )

    def _extract_pages(self) -> None:
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Extract pages",
            f"Pages to extract (1–{t._doc.page_count}). "
            "Comma-separated, ranges allowed — e.g. <code>1, 3-5, 9</code>:",
            text="1-{}".format(t._doc.page_count),
        )
        if not ok or not text.strip():
            return
        indices = self._parse_page_range(text, t._doc.page_count)
        if not indices:
            QMessageBox.warning(self, "Extract",
                                "Couldn't parse that page range.")
            return
        suggested = t.path.with_name(
            f"{t.path.stem}_pages.pdf"
        )
        out_s, _ = QFileDialog.getSaveFileName(
            self, "Save extracted PDF as", str(suggested),
            "PDF files (*.pdf);;All files (*)",
        )
        if not out_s:
            return
        try:
            ok = page_ops.extract_pages(t._doc, indices, Path(out_s))
        except Exception as e:
            QMessageBox.warning(self, "Extract", str(e))
            return
        if not ok:
            QMessageBox.warning(self, "Extract",
                                "No pages were extracted.")
            return
        self.statusBar().showMessage(
            f"Extracted {len(indices)} page(s) to {out_s}", 4000,
        )

    @staticmethod
    def _parse_page_range(text: str, page_count: int) -> list[int]:
        """Parse a user-facing 1-based range string ("1, 3-5, 9")
        into a sorted unique list of 0-based indices, clamped to the
        document's page count. Bad chunks are skipped."""
        out: set[int] = set()
        for chunk in text.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "-" in chunk:
                lo_s, hi_s = chunk.split("-", 1)
                try:
                    lo = int(lo_s.strip())
                    hi = int(hi_s.strip())
                except ValueError:
                    continue
                if lo > hi:
                    lo, hi = hi, lo
                for n in range(lo, hi + 1):
                    if 1 <= n <= page_count:
                        out.add(n - 1)
            else:
                try:
                    n = int(chunk)
                except ValueError:
                    continue
                if 1 <= n <= page_count:
                    out.add(n - 1)
        return sorted(out)

    def _split_pdf(self) -> None:
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        out_dir = QFileDialog.getExistingDirectory(
            self, "Choose a folder to write the split PDFs into",
            str(t.path.parent),
        )
        if not out_dir:
            return
        try:
            paths = page_ops.split_into_files(
                t._doc, Path(out_dir), t.path.stem,
            )
        except Exception as e:
            QMessageBox.warning(self, "Split", str(e))
            return
        self.statusBar().showMessage(
            f"Wrote {len(paths)} file(s) to {out_dir}", 5000,
        )

    # ----- Insert image / paste -----

    def _insert_image_from_file(self) -> None:
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Insert image", str(t.path.parent),
            "Image files (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;"
            "All files (*)",
        )
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Insert image",
                                f"Could not read {path}.")
            return
        self._place_qimage(img)

    def keyPressEvent(self, event):  # noqa: N802
        # Ctrl+V → paste a clipboard image at the centre of the
        # current page. Lets the user copy a screenshot / figure and
        # drop it straight onto the PDF.
        if (event.key() == Qt.Key_V
                and event.modifiers() & Qt.ControlModifier):
            md = QApplication.clipboard().mimeData()
            if md.hasImage():
                img = QImage(md.imageData())
                if not img.isNull():
                    self._place_qimage(img)
                    event.accept()
                    return
        super().keyPressEvent(event)

    def _place_qimage(self, img: QImage) -> None:
        t = self._current_pdf_tab()
        if t is None or t._doc is None:
            return
        page_idx = t.current_page_index()
        page = t._doc[page_idx]
        pw, ph = page.rect.width, page.rect.height
        # Cap width at 60% of the page so big screenshots don't
        # cover everything; preserve aspect ratio.
        max_w = pw * 0.6
        max_h = ph * 0.6
        w = min(float(img.width()), max_w)
        h = img.height() * (w / max(1, img.width()))
        if h > max_h:
            h = max_h
            w = img.width() * (h / max(1, img.height()))
        x0 = (pw - w) / 2
        y0 = (ph - h) / 2
        from PySide6.QtCore import QBuffer, QByteArray
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        t.insert_image_bytes(
            bytes(ba), page_idx, (x0, y0, x0 + w, y0 + h),
            push_undo=True,
        )

    # ----- Print -----

    def _print(self) -> None:
        """File → Print: jump straight to the OS native printer
        dialog. From there the user picks printer, range, copies,
        and orientation, then hits Print. (Print Preview is a
        separate menu item for the Qt-preview workflow.)"""
        t = self._current_pdf_tab()
        if t is None or t._doc is None or t._doc.page_count == 0:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(t.path.stem)
        printer.setFromTo(1, t._doc.page_count)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._render_pdf_to_printer(printer, t)
        self.statusBar().showMessage(
            f"Sent to {printer.printerName()}", 4000,
        )

    def _print_preview(self) -> None:
        """File → Print Preview: open Qt's preview window (page
        navigation, zoom, fit-page / two-page modes). Its toolbar's
        Print button hands off to the OS native dialog for printer
        selection. Both dialogs are visible together in this flow."""
        t = self._current_pdf_tab()
        if t is None or t._doc is None or t._doc.page_count == 0:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(t.path.stem)
        printer.setFromTo(1, t._doc.page_count)
        preview = QPrintPreviewDialog(printer, self)
        preview.setWindowTitle(f"Print preview — {t.path.name}")
        preview.paintRequested.connect(
            lambda pr, tab=t: self._render_pdf_to_printer(pr, tab)
        )
        preview.exec()

    def _render_pdf_to_printer(self, printer: QPrinter,
                               tab: "PdfTab") -> None:
        """Rasterise the (selected pages of the) active PDF onto
        `printer`. PyMuPDF renders each page at a scale chosen to
        fit the printable area while preserving aspect ratio; we
        centre the image on the page. Honours fromPage / toPage."""
        if tab._doc is None:
            return
        import fitz  # local — only the print path needs it
        from_p = printer.fromPage() or 1
        to_p = printer.toPage() or tab._doc.page_count
        from_idx = max(0, from_p - 1)
        to_idx = min(tab._doc.page_count - 1, to_p - 1)
        if from_idx > to_idx:
            return
        painter = QPainter()
        if not painter.begin(printer):
            return
        try:
            first = True
            for page_idx in range(from_idx, to_idx + 1):
                if not first:
                    printer.newPage()
                first = False
                page = tab._doc[page_idx]
                page_rect_pt = page.rect
                printable = painter.viewport()
                sx = printable.width() / page_rect_pt.width
                sy = printable.height() / page_rect_pt.height
                scale = min(sx, sy)
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    alpha=False, annots=True,
                )
                img = QImage(
                    pix.samples, pix.width, pix.height, pix.stride,
                    QImage.Format_RGB888,
                ).copy()
                x = (printable.width() - pix.width) // 2
                y = (printable.height() - pix.height) // 2
                painter.drawImage(int(x), int(y), img)
        finally:
            painter.end()

    # ----- Git menu -----

    def _git_commit_now(self) -> None:
        t = self._current_pdf_tab()
        if t is None:
            return
        if not git_backend.is_available():
            QMessageBox.information(
                self, "Git",
                "pygit2 isn't installed — install it to enable Git "
                "versioning of your PDFs.",
            )
            return
        ok = git_backend.commit_file(
            t.path, message=f"Manual commit — {t.path.name}",
        )
        if ok:
            self.statusBar().showMessage(
                f"Committed {t.path.name} to git", 3000,
            )
            self._refresh_status()
        else:
            QMessageBox.warning(
                self, "Commit",
                "Nothing to commit (no changes since last commit?) "
                "or git operation failed.",
            )

    def _git_history(self) -> None:
        t = self._current_pdf_tab()
        if t is None:
            return
        if not git_backend.is_available():
            QMessageBox.information(self, "Git",
                                    "pygit2 isn't installed.")
            return
        HistoryDialog(self, t.path).exec()

    def _git_remote(self) -> None:
        t = self._current_pdf_tab()
        if t is None:
            return
        if not git_backend.is_available():
            QMessageBox.information(self, "Git",
                                    "pygit2 isn't installed.")
            return
        RemoteDialog(self, t.path).exec()

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
        for name, ver, role, _url in libraries:
            rows.append(
                "<tr>"
                f"<td valign='top' style='padding:6px 14px 6px 0'>"
                f"<b>{name}</b><br>"
                f"<span style='color:#666;font-size:9pt'>{ver}</span></td>"
                f"<td valign='top' style='padding:6px 0'>{role}</td>"
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
            f"<li><b>KherveFitting</b> — peak fitting for XPS spectra.</li>"
            f"<li><b>spe-xps-reader</b> — open reader for PHI "
            f"Instruments SPE binary files.</li>"
            f"<li><b>KherveTeX</b> — WYSIWYG LaTeX editor.</li>"
            f"<li><b>KherveSheet</b> — Origin-style scientific "
            f"workbook.</li>"
            f"<li><b>KherveDB</b> — reference database for the "
            f"Kherve* suite.</li>"
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
