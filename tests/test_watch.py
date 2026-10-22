"""Слежка за папкой OBS: папка из настроек OBS, новые записи, «дописана ли», вопрос «Нарезать?»."""
import os
import subprocess
import sys
import time

import pytest

import autoclip


def make_video(path, dur):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=gray:s=64x64:r=5:d={dur}",
                    "-f", "lavfi", "-i", f"sine=d={dur}", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(path)], check=True)


@pytest.mark.parametrize("mode,section,key", [("Simple", "SimpleOutput", "FilePath"),
                                              ("Advanced", "AdvOut", "RecFilePath")])
def test_find_obs_record_dir(tmp_path, monkeypatch, mode, section, key):
    rec = tmp_path / "Записи"
    rec.mkdir()
    obs = tmp_path / "obs-studio"
    (obs / "basic" / "profiles" / "Мой").mkdir(parents=True)
    (obs / "user.ini").write_text("[Basic]\nProfile=Мой\nProfileDir=Мой\n", encoding="utf-8-sig")
    (obs / "basic" / "profiles" / "Мой" / "basic.ini").write_text(
        f"[Output]\nMode={mode}\n\n[{section}]\n{key}={str(rec).replace(os.sep, '/')}\n", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert os.path.normcase(autoclip.find_obs_record_dir()) == os.path.normcase(str(rec))


def test_find_obs_record_dir_without_obs(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert autoclip.find_obs_record_dir() is None


def test_new_recordings_filters(tmp_path):
    old = tmp_path / "старая.mp4"
    old.write_bytes(b"x")
    os.utime(old, (1000, 1000))
    since = time.time() - 5
    new = tmp_path / "новая.mp4"
    new.write_bytes(b"x")
    (tmp_path / "заметки.txt").write_text("x")
    done = tmp_path / "разобранная.mkv"
    done.write_bytes(b"x")
    autoclip.set_recording_state(str(done), "declined")
    assert autoclip.new_recordings(str(tmp_path), since) == [str(new)]
    assert autoclip.recording_state(str(done)) == "declined"


def test_growth_tracker(tmp_path):
    f = tmp_path / "запись.mp4"
    f.write_bytes(b"a" * 10)
    t = autoclip.GrowthTracker(stable=10)
    assert not t.update(str(f), now=0)
    assert not t.update(str(f), now=5)              # ещё мало ждали
    f.write_bytes(b"a" * 20)                        # OBS дописывает
    assert not t.update(str(f), now=9)
    assert not t.update(str(f), now=18)
    assert t.update(str(f), now=19.5)               # 10 с без изменений — дописана
    assert not t.update(str(tmp_path / "нет.mp4"), now=30)


def test_recording_info(tmp_path):
    v = tmp_path / "запись.mp4"
    make_video(v, 3)
    info = autoclip.recording_info(str(v))
    assert abs(info["dur"] - 3) < 0.3 and info["marks"] == 0
    bad = tmp_path / "недописана.mp4"
    bad.write_bytes(b"\x00" * 1000)
    assert autoclip.recording_info(str(bad)) is None


# ---------- окно ----------

@pytest.fixture
def win(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    w = A.MainWindow()
    yield w
    w.settings["watch"] = False
    w.close()


def test_watch_offers_long_recording_and_remembers_answers(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog
    folder = tmp_path / "Записи"
    folder.mkdir()
    started = []
    monkeypatch.setattr(win.cut, "start_or_stop", lambda: started.append(list(win.cut.files)))
    st = win.settings_page
    st.obs.setText(str(folder))
    st.min_minutes.setValue(1)
    st.cb_watch.setChecked(True)
    assert win.settings["watch"] and win.watch_timer.isActive()
    win.tracker.stable = 0                           # в тесте не ждём 10 секунд

    short, long_, other = folder / "тест.mp4", folder / "стрим.mp4", folder / "ещё.mp4"
    make_video(short, 5)
    make_video(long_, 70)
    for _ in range(2):                               # первый проход — запомнить размер
        win.scan_obs()
    assert autoclip.recording_state(str(short)) == "short"     # короткую не предлагаем
    assert [p for p, _ in win._pending] == [str(long_)]

    win.ask_pending()
    assert "стрим.mp4" in win._dialog.findChildren(type(st.p_state))[1].text()
    win._dialog.done(QDialog.Accepted)
    assert autoclip.recording_state(str(long_)) == "cut"
    assert started == [[str(long_)]]

    make_video(other, 70)
    for _ in range(2):
        win.scan_obs()
    win.ask_pending()
    win._dialog.done(QDialog.Rejected)
    assert autoclip.recording_state(str(other)) == "declined"
    for _ in range(2):                               # второй раз не спрашиваем
        win.scan_obs()
    assert win._pending == [] and win._dialog is None


def test_old_recordings_not_offered(win, tmp_path):
    folder = tmp_path / "Записи"
    folder.mkdir()
    make_video(folder / "вчерашняя.mp4", 70)
    win.settings_page.obs.setText(str(folder))
    win.settings_page.min_minutes.setValue(1)
    win.settings_page.cb_watch.setChecked(True)     # включили слежку после записи
    win.tracker.stable = 0
    for _ in range(2):
        win.scan_obs()
    assert win._pending == []
