"""Мастер первого запуска (P4): только на новом компьютере, ник пустой, папки и видеокарта сохраняются."""
import sys

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

import autoclip  # noqa: E402
import health  # noqa: E402


@pytest.fixture
def A(tmp_path, monkeypatch):
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    monkeypatch.setattr(autoclip, "find_obs_record_dir", lambda: str(tmp_path / "obs"))
    import app
    qapp = QApplication.instance() or QApplication([])
    app.dark_palette(qapp)
    return app


def test_need_setup_only_on_new_computer(A):
    assert A.need_setup({}, settings_existed=False)
    assert not A.need_setup({}, settings_existed=True)          # у Гоши настройки уже есть
    assert not A.need_setup({"setup_done": True}, settings_existed=False)


def test_nick_empty_by_default(A):
    assert A.DEFAULTS["nick_text"] == ""


def test_setup_saves_folders_and_gpu(A, tmp_path, monkeypatch):
    monkeypatch.setattr(health, "gpu_name", lambda: None)       # компьютер без NVIDIA
    win = A.MainWindow()
    dlg = A.SetupDialog(win)
    assert dlg.nick.text() == ""
    assert dlg.obs.text() == str(tmp_path / "obs")              # нашёл в настройках OBS
    assert dlg.dev.currentData() == "cpu"
    dlg.nick.setText("  Друг  ")
    dlg.clips.setText(str(tmp_path / "Клипы"))
    dlg.done_ok()
    s = A.load_settings()
    assert s["nick_text"] == "Друг" and s["setup_done"] is True
    assert s["clips_dir"] == str(tmp_path / "Клипы") and (tmp_path / "Клипы").is_dir()
    assert s["obs_dir"] == str(tmp_path / "obs")
    assert s["whisper_device"] == "cpu" and s["whisper_model"] == "medium"
    assert win.settings_page.clips_dir.text() == str(tmp_path / "Клипы")
    win.cut.apply_config()
    assert autoclip.CONFIG["whisper_device"] == "cpu" and autoclip.CONFIG["whisper_model"] == "medium"
    autoclip.CONFIG["whisper_device"] = "auto"
    autoclip.CONFIG["whisper_model"] = "large-v3"
    win.close()


def test_setup_gpu_found(A, monkeypatch):
    monkeypatch.setattr(health, "gpu_name", lambda: "NVIDIA GeForce RTX 5080")
    win = A.MainWindow()
    dlg = A.SetupDialog(win)
    assert dlg.dev.currentData() == "auto" and "RTX 5080" in dlg.gpu_note.text()
    dlg.done_ok()
    assert A.load_settings()["whisper_model"] == "large-v3"
    win.close()


def test_skip_marks_done(A, monkeypatch):
    monkeypatch.setattr(health, "gpu_name", lambda: None)
    win = A.MainWindow()
    A.SetupDialog(win).skip()
    assert A.load_settings()["setup_done"] is True
    win.close()


def test_cpu_only_skips_cuda(monkeypatch):
    tried = []

    class Fake:
        def __init__(self, name, device, compute_type):
            tried.append(device)

    import types
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Fake))
    monkeypatch.setitem(autoclip.CONFIG, "whisper_device", "cpu")
    autoclip._load_whisper()
    assert tried == ["cpu"]


def test_download_note_only_when_model_missing(tmp_path, monkeypatch):
    """«Первый раз скачается ~3 ГБ» — только если модели ещё нет на диске."""
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    assert not autoclip.whisper_cached("large-v3")
    snap = tmp_path / "models--Systran--faster-whisper-large-v3" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "model.bin").write_bytes(b"x")
    assert autoclip.whisper_cached("large-v3") and not autoclip.whisper_cached("medium")
