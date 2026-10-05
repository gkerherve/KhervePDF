"""A second launch hands its PDFs to the running window as tabs."""
import os
import subprocess
import sys
import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from khervepdf import single_instance

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _pdf(path: Path) -> Path:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), path.stem)
    doc.save(str(path))
    doc.close()
    return path


def _pump(until, seconds=30):
    deadline = time.monotonic() + seconds
    while not until() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


def test_request_from_another_process(qapp, monkeypatch):
    monkeypatch.setenv("KHERVEPDF_IPC_NAME", f"khervepdf-test-{os.getpid()}")
    server = single_instance.Server(qapp)
    got = []
    server.request.connect(got.append)
    code = ("import sys; from PySide6.QtCore import QCoreApplication; "
            "from khervepdf import single_instance as s; "
            "app = QCoreApplication([]); "
            "sys.exit(0 if s.send_to_running({'cmd': 'open', 'paths': ['a.pdf']}) else 1)")
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=str(ROOT))
    try:
        _pump(lambda: proc.poll() is not None and got)
        assert proc.wait(5) == 0
        assert got == [{"cmd": "open", "paths": ["a.pdf"]}]
    finally:
        if proc.poll() is None:
            proc.kill()
        server.close()


def test_nobody_running(qapp, monkeypatch):
    monkeypatch.setenv("KHERVEPDF_IPC_NAME", "khervepdf-test-nobody")
    assert not single_instance.send_to_running({"cmd": "open", "paths": []},
                                               timeout_ms=100)


def test_open_request_adds_tabs_once(qapp, tmp_path):
    from khervepdf.mainwindow import MainWindow
    a, b = _pdf(tmp_path / "a.pdf"), _pdf(tmp_path / "b.pdf")
    win = MainWindow()
    try:
        win.open_request({"cmd": "open", "paths": [str(a)]})
        win.open_request({"cmd": "open", "paths": [str(b), str(tmp_path / "gone.pdf")]})
        assert win._tabs.count() == 2 and win._current_path() == b
        win.open_request({"cmd": "open", "paths": [str(a)]})
        assert win._tabs.count() == 2 and win._current_path() == a
    finally:
        for i in range(win._tabs.count()):
            win._tabs.widget(i).setProperty("dirty", False)
        win.deleteLater()
