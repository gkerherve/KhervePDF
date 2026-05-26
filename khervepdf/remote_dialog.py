"""Remote dialog — set the origin URL and push the active PDF to it.

Push is delegated to the system `git` CLI (see git_backend.push) so
authentication uses whatever the user already has configured — SSH
keys, Git Credential Manager, gh, libsecret, etc. — instead of
re-implementing the pygit2 credential dance per platform.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from . import git_backend


class RemoteDialog(QDialog):
    def __init__(self, parent, pdf_path: Path) -> None:
        super().__init__(parent)
        self.setWindowTitle("Git remote")
        self.resize(540, 220)
        self._path = pdf_path
        layout = QVBoxLayout(self)

        intro = QLabel(self)
        branch = git_backend.current_branch(pdf_path) or "(no branch)"
        intro.setText(
            f"<b>{pdf_path.name}</b> &nbsp;·&nbsp; "
            f"branch <code>{branch}</code><br>"
            "Set the remote URL (e.g. "
            "<code>https://github.com/&lt;user&gt;/&lt;repo&gt;.git</code> "
            "or <code>git@github.com:&lt;user&gt;/&lt;repo&gt;.git</code>) "
            "then click Push."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self._url_edit = QLineEdit(self)
        self._url_edit.setPlaceholderText(
            "https://github.com/<user>/<repo>.git"
        )
        existing = git_backend.get_remote(pdf_path, "origin") or ""
        self._url_edit.setText(existing)
        form.addRow("Origin URL:", self._url_edit)
        layout.addLayout(form)

        actions = QHBoxLayout()
        save_btn = QPushButton("Save URL", self)
        save_btn.clicked.connect(self._save_remote)
        actions.addWidget(save_btn)
        push_btn = QPushButton("Save && Push", self)
        push_btn.clicked.connect(self._push)
        actions.addWidget(push_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        bb = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        layout.addWidget(bb)

    def _save_remote(self) -> bool:
        url = self._url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Remote",
                                "Please enter a URL.")
            return False
        ok = git_backend.set_remote(self._path, url, "origin")
        if not ok:
            QMessageBox.warning(self, "Remote",
                                "Could not save the remote URL.")
        return ok

    def _push(self) -> None:
        if not self._save_remote():
            return
        ok, msg = git_backend.push(self._path, "origin")
        if ok:
            QMessageBox.information(self, "Push",
                                    msg or "Pushed.")
        else:
            QMessageBox.warning(self, "Push failed",
                                msg or "Push failed.")
