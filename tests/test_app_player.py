"""Просмотр клипа: не играет сам, показывает первый кадр, пуск — пробелом или кликом."""
import subprocess
import sys

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import autoclip  # noqa: E402


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    w = A.MainWindow()
    w.show()
    yield w
    w.close()


@pytest.fixture
def project(tmp_path):
    out = tmp_path / "запись_clips"
    out.mkdir()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=s=270x480:r=30:d=4", "-f", "lavfi", "-i", "sine=d=4",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                    str(out / "01_тест.mp4")], check=True)
    vinfo = {"w": 270, "h": 480, "dur": 4.0, "fps": 30.0}
    proj = autoclip.new_project(str(tmp_path / "запись.mp4"), vinfo, str(out),
                                str(tmp_path / "запись.transcript.json"))
    clip = {"s": 0.0, "e": 4.0, "peak": 2.0, "score": 3.0, "zooms": [], "parts": {},
            "title": "тест", "reason": ""}
    proj["clips"] = [autoclip.make_clip_record(clip, 1, "01_тест.mp4")]
    autoclip.save_project(proj)
    return str(out)


def wait_for(cond, ms=5000):
    for _ in range(ms // 50):
        if cond():
            return True
        QTest.qWait(50)
    return cond()


def test_clip_opens_paused_on_first_frame(win, project):
    win.finished(project)                 # как после нарезки: открываются клипы
    win.go("clips")
    pl = win.clips.player
    assert wait_for(lambda: pl.video.videoSink().videoFrame().isValid())
    QTest.qWait(500)
    assert pl.player.playbackState() != QMediaPlayer.PlayingState
    assert pl.player.position() < 200

    win.activateWindow()
    win.raise_()
    if QTest.qWaitForWindowActive(win, 2000):
        win.clips.list.setFocus()
        QTest.keyClick(win.clips.list, Qt.Key_Space)    # пробел — только в активном окне
    else:
        QTest.mouseClick(pl.btn_play, Qt.LeftButton)
    assert wait_for(lambda: pl.player.playbackState() == QMediaPlayer.PlayingState)
    QTest.mouseClick(pl.video, Qt.LeftButton)
    assert wait_for(lambda: pl.player.playbackState() == QMediaPlayer.PausedState)
