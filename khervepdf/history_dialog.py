"""History dialog — list of git commits for the active PDF.

The user can click a row and Restore to roll the working-copy PDF
back to that version. Restore is destructive (overwrites the current
file on disk) so the dialog prompts for confirmation. Refreshes
automatically after restore so the new HEAD shows up.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from . import git_backend


class HistoryDialog(QDialog):
    def __init__(self, parent, pdf_path: Path) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Git history — {pdf_path.name}")
        self.resize(720, 460)
        self._path = pdf_path

        layout = QVBoxLayout(self)
        header = QLabel(self)
        branch = git_backend.current_branch(pdf_path) or "(no branch)"
        header.setText(f"<b>{pdf_path.name}</b> on branch "
                       f"<code>{branch}</code>")
        layout.addWidget(header)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(["SHA", "Date", "Author", "Subject"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.itemDoubleClicked.connect(self._on_double)
        layout.addWidget(self._tree, 1)

        actions = QHBoxLayout()
        self._restore_btn = QPushButton("Restore to selected", self)
        self._restore_btn.clicked.connect(self._restore_selected)
        actions.addWidget(self._restore_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        bb = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        layout.addWidget(bb)

        self._reload()

    def _reload(self) -> None:
        self._tree.clear()
        entries = git_backend.history(self._path, limit=200)
        for sha, author, ts, subject in entries:
            dt = time.strftime("%Y-%m-%d %H:%M",
                               time.localtime(ts))
            item = QTreeWidgetItem([sha, dt, author, subject])
            item.setData(0, Qt.UserRole, sha)
            self._tree.addTopLevelItem(item)
        # Column widths — SHA narrow, subject wide.
        for col, w in ((0, 80), (1, 130), (2, 140)):
            self._tree.setColumnWidth(col, w)

    def _on_double(self, item: QTreeWidgetItem, _col: int) -> None:
        self._restore_selected()

    def _restore_selected(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        sha = item.data(0, Qt.UserRole)
        if not sha:
            return
        ok = QMessageBox.question(
            self, "Restore?",
            f"Restore <b>{self._path.name}</b> to commit "
            f"<code>{sha}</code>?<br>"
            "The current file on disk will be overwritten.",
        )
        if ok != QMessageBox.Yes:
            return
        if git_backend.restore_to_commit(self._path, sha):
            # Commit the restored state so subsequent saves show a
            # clean history rather than dangling "uncommitted
            # changes" in the index.
            git_backend.commit_file(
                self._path, message=f"Restore to {sha}",
            )
            self._reload()
            QMessageBox.information(
                self, "Restored",
                "File reverted. Close and reopen the tab to view.",
            )
        else:
            QMessageBox.warning(self, "Restore failed",
                                "Could not check out that commit.")
