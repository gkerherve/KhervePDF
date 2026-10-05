from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from khervepdf import kherveref_link as krl

_SOURCE_CHECKOUT = krl._source_checkout


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    QSettings(*krl.SETTINGS).remove(krl.PATH_KEY)
    # Keep the real install locations out of reach so results don't
    # depend on what this machine has installed.
    monkeypatch.setattr(krl.sys, "platform", "linux")
    monkeypatch.setattr(krl, "_source_checkout",
                        lambda: tmp_path / "nowhere" / "KherveRef.py")
    yield
    QSettings(*krl.SETTINGS).remove(krl.PATH_KEY)


def _checkout(root: Path, venv_rel: str = "bin/python") -> tuple[Path, Path]:
    script = root / "KherveRef" / "KherveRef.py"
    script.parent.mkdir(parents=True)
    script.write_text("")
    py = script.parent / ".venv" / venv_rel
    py.parent.mkdir(parents=True)
    py.write_text("")
    return script, py


def _app(root: Path) -> Path:
    app = root / "KherveRef.app"
    exe = app / "Contents" / "MacOS" / "KherveRef"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    return app


def test_not_found(tmp_path):
    assert krl.find_kherveref() is None
    assert krl.add_to_kherveref(tmp_path / "a.pdf") is False


def test_sibling_checkout_runs_with_its_own_venv(monkeypatch, tmp_path):
    script, py = _checkout(tmp_path)
    monkeypatch.setattr(krl, "_source_checkout", lambda: script)
    assert krl.find_kherveref() == [str(py), str(script)]


def test_windows_style_venv(monkeypatch, tmp_path):
    script, py = _checkout(tmp_path, "Scripts/python.exe")
    monkeypatch.setattr(krl, "_source_checkout", lambda: script)
    assert krl.find_kherveref() == [str(py), str(script)]


def test_checkout_without_venv_is_skipped(monkeypatch, tmp_path):
    script = tmp_path / "KherveRef" / "KherveRef.py"
    script.parent.mkdir()
    script.write_text("")
    monkeypatch.setattr(krl, "_source_checkout", lambda: script)
    assert krl.find_kherveref() is None


def test_source_checkout_is_sibling_of_this_repo():
    repo = Path(krl.__file__).resolve().parents[1]
    assert _SOURCE_CHECKOUT() == repo.parent / "KherveRef" / "KherveRef.py"


def test_windows_install_locations(monkeypatch, tmp_path):
    monkeypatch.setattr(krl.sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "PF"))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LAD"))
    paths = krl.candidate_paths()
    assert tmp_path / "PF" / "KherveRef" / "KherveRef.exe" in paths
    assert (tmp_path / "LAD" / "Programs" / "KherveRef"
            / "KherveRef.exe") in paths
    exe = tmp_path / "LAD" / "Programs" / "KherveRef" / "KherveRef.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert krl.find_kherveref() == [str(exe)]


def test_macos_install_locations(monkeypatch):
    monkeypatch.setattr(krl.sys, "platform", "darwin")
    paths = krl.candidate_paths()
    assert Path("/Applications/KherveRef.app") in paths
    assert Path.home() / "Applications" / "KherveRef.app" in paths


def test_custom_path_validation(monkeypatch, tmp_path):
    assert krl.set_custom_path(str(tmp_path / "missing.exe")) is False
    assert krl.set_custom_path(str(tmp_path)) is False
    empty_app = tmp_path / "Empty.app"
    empty_app.mkdir()
    assert krl.set_custom_path(str(empty_app)) is False
    assert QSettings(*krl.SETTINGS).value(krl.PATH_KEY, "") in ("", None)

    app = _app(tmp_path)
    assert krl.set_custom_path(str(app)) is True
    assert krl.find_kherveref() == [
        str(app / "Contents" / "MacOS" / "KherveRef")]


def test_custom_path_wins_over_checkout(monkeypatch, tmp_path):
    script, _py = _checkout(tmp_path / "src")
    monkeypatch.setattr(krl, "_source_checkout", lambda: script)
    exe = tmp_path / "KherveRef.exe"
    exe.write_text("")
    assert krl.set_custom_path(str(exe))
    assert krl.find_kherveref() == [str(exe)]


@pytest.mark.parametrize("fn, flag", [
    (krl.add_to_kherveref, "--add"),
    (krl.reveal_in_kherveref, "--reveal"),
])
def test_launch_argv(monkeypatch, tmp_path, fn, flag):
    script, py = _checkout(tmp_path)
    monkeypatch.setattr(krl, "_source_checkout", lambda: script)
    calls = []

    def fake(program, args):
        calls.append((program, list(args)))
        return True, 4242

    monkeypatch.setattr(krl.QProcess, "startDetached", staticmethod(fake))
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert getattr(krl, fn.__name__)(pdf) is True
    assert calls == [(str(py), [str(script), flag, str(pdf.resolve())])]


def test_launch_failure_reported(monkeypatch, tmp_path):
    script, _py = _checkout(tmp_path)
    monkeypatch.setattr(krl, "_source_checkout", lambda: script)
    monkeypatch.setattr(krl.QProcess, "startDetached",
                        staticmethod(lambda program, args: (False, 0)))
    assert krl.reveal_in_kherveref(tmp_path / "x.pdf") is False
