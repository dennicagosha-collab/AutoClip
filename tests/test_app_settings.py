"""Все настройки окна переживают закрытие и повторный запуск."""
import json
import sys

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import autoclip  # noqa: E402


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    # окно забирает print и лог себе — после теста возвращаем
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    return A


def test_all_settings_survive_restart(app_module):
    A = app_module
    win = A.MainWindow()
    win.show()
    cut, st = win.cut, win.settings_page

    st.cb_subs.setChecked(False)
    st.cb_zoom.setChecked(False)
    st.cb_bleep.setChecked(False)
    st.sound.setCurrentText("буп")
    cut.count.setValue(7)
    st.cam.setCurrentText("Вебка снизу")
    st.sub_pos.setCurrentText("Снизу")
    st.cb_safe.setChecked(False)
    st.p_name.setText("Мой 720p30")
    st.p_w.setValue(720)
    st.p_h.setValue(1280)
    st.p_fps.setValue(30)
    st.add_preset()
    cut.preset.setCurrentText("Мой 720p30")
    st.llm.setCurrentText("Без модели")
    # поля печатаем как человек и закрываем окно, не уходя из поля
    for field, text in ((st.ollama, "llama3:8b"), (st.obs, r"D:\OBS"),
                        (st.nick, "Gosha"), (st.tags, "#стрим #игры")):
        field.setFocus()
        field.selectAll()
        field.insert(text)          # QTest.keyClicks падает на русских буквах
    win.close()
    QApplication.processEvents()

    with open(autoclip.SETTINGS_PATH, encoding="utf-8") as f:
        saved = json.load(f)
    expect = {"subs": False, "zoom": False, "bleep": False, "sound": "буп", "clips": 7,
              "cam": "Вебка снизу", "sub_pos": "Снизу", "safe_zone": False, "preset": "Мой 720p30", "llm": "none",
              "ollama_model": "llama3:8b", "obs_dir": r"D:\OBS", "nick_text": "Gosha",
              "hashtags": "#стрим #игры"}
    assert {k: saved.get(k) for k in expect} == expect
    assert saved.get("geometry")

    # новое окно показывает сохранённое
    win2 = A.MainWindow()
    assert not win2.settings_page.cb_subs.isChecked()
    assert win2.settings_page.sound.currentText() == "буп"
    assert win2.cut.count.value() == 7
    assert win2.settings_page.cam.currentText() == "Вебка снизу"
    assert win2.settings_page.sub_pos.currentText() == "Снизу"
    assert not win2.settings_page.cb_safe.isChecked()
    win2.cut.apply_config()
    assert autoclip.CONFIG["sub_y"] == autoclip.SUB_POSITIONS["Снизу"]
    assert autoclip.CONFIG["safe_zone"] is False
    assert win2.cut.preset.currentText() == "Мой 720p30"
    assert win2.settings_page.llm.currentText() == "Без модели"
    assert win2.settings_page.nick.text() == "Gosha"
    win2.close()


def test_main_page_has_no_clip_options(app_module):
    """На «Нарезке» только запись, число клипов, пресет и кнопка — без галочек и раскладки."""
    win = app_module.MainWindow()
    for name in ("cb_subs", "cb_zoom", "cb_hook", "cb_bleep", "cb_marks", "cb_safe", "sound",
                 "sub_pos", "cam"):
        assert not hasattr(win.cut, name), name
        assert hasattr(win.settings_page, name), name
    win.close()


def test_clips_page_empty_on_start(app_module, tmp_path):
    """При запуске «Клипы» пустые, даже если нарезки уже были."""
    out = tmp_path / "запись_clips"
    out.mkdir()
    proj = autoclip.new_project(str(tmp_path / "запись.mp4"), {"w": 270, "h": 480, "dur": 10.0,
                                "fps": 30.0}, str(out), str(tmp_path / "t.json"))
    autoclip.save_project(proj)
    with open(autoclip.SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump({"recent": [str(out / "project.json")]}, f)
    win = app_module.MainWindow()
    win.show()
    for _ in range(10):
        QApplication.processEvents()
    page = win.clips
    assert page.proj is None and page.list.count() == 0
    assert page.projects.currentIndex() == -1 and page.projects.count() == 1
    page.load(page.projects.itemData(0))                 # выбрал сам — открылась
    assert page.proj is not None and page.projects.currentIndex() == 0
    win.close()


def test_windows_do_not_show_on_screen(app_module):
    """При тестах окна рисуются в памяти и не всплывают на мониторе."""
    assert QApplication.platformName() == "offscreen"
