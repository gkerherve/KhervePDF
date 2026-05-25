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
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QFileDialog, QLabel, QMainWindow, QMenu, QStatusBar, QTabWidget,
    QToolBar, QWidget,
)

from . import themes, version_string, last_commit_subject


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
        m_file.addAction(QAction("&New", self, shortcut="Ctrl+N",
                                 triggered=self._new))
        m_file.addAction(QAction("&Open…", self, shortcut="Ctrl+O",
                                 triggered=self._open))
        m_file.addSeparator()
        m_file.addAction(QAction("&Save", self, shortcut="Ctrl+S",
                                 triggered=self._save))
        m_file.addAction(QAction("Save &As…", self, shortcut="Ctrl+Shift+S",
                                 triggered=self._save_as))
        m_file.addSeparator()
        m_file.addAction(QAction("Export as &PNG…", self,
                                 triggered=self._noop))
        m_file.addAction(QAction("Export &Text…", self,
                                 triggered=self._noop))
        m_file.addAction(QAction("&Print…", self, shortcut="Ctrl+P",
                                 triggered=self._noop))
        m_file.addSeparator()
        m_file.addAction(QAction("&Close Tab", self, shortcut="Ctrl+W",
                                 triggered=lambda: self._close_tab(self._tabs.currentIndex())))
        m_file.addAction(QAction("E&xit", self, shortcut="Ctrl+Q",
                                 triggered=self.close))

        m_edit = mb.addMenu("&Edit")
        m_edit.addAction(QAction("&Undo", self, shortcut="Ctrl+Z",
                                 triggered=self._noop))
        m_edit.addAction(QAction("&Redo", self, shortcut="Ctrl+Y",
                                 triggered=self._noop))
        m_edit.addSeparator()
        m_edit.addAction(QAction("&Find…", self, shortcut="Ctrl+F",
                                 triggered=self._noop))

        m_view = mb.addMenu("&View")
        m_view.addAction(QAction("Zoom &In", self, shortcut="Ctrl++",
                                 triggered=self._noop))
        m_view.addAction(QAction("Zoom &Out", self, shortcut="Ctrl+-",
                                 triggered=self._noop))
        m_view.addAction(QAction("Fit &Width", self, triggered=self._noop))
        m_view.addAction(QAction("Fit &Page", self, triggered=self._noop))
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
        # Placeholder buttons — qtawesome icons land in v0.2+.
        for label in ("Open", "Save", "|",
                      "Select", "Pen", "Highlight", "Text",
                      "Line", "Arrow", "Rectangle", "Ellipse",
                      "Note", "Signature", "Redact", "|",
                      "Zoom-", "Zoom+", "Fit"):
            if label == "|":
                tb.addSeparator()
            else:
                tb.addAction(QAction(label, self, triggered=self._noop))

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
        # Placeholder until pdftab wires real page/zoom signals.
        if self._tabs.count() == 0:
            self._lbl_page.setText("—")
            self._lbl_zoom.setText("—")
        else:
            self._lbl_page.setText("Page 1 of 1")
            self._lbl_zoom.setText("100%")
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
        if w is not None:
            w.deleteLater()
        self._refresh_status()

    # ----- file actions (stubs — concrete logic in pdftab v0.3) -----

    def open_path(self, path: Path) -> None:
        placeholder = QWidget(self)
        placeholder.path = path
        self._tabs.addTab(placeholder, path.name)
        self._tabs.setCurrentWidget(placeholder)
        self._refresh_status()

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
