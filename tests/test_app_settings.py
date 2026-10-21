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

    cut.cb_subs.setChecked(False)
    cut.cb_zoom.setChecked(False)
    cut.cb_bleep.setChecked(False)
    cut.sound.setCurrentText("буп")
    cut.count.setValue(7)
    cut.cam.setCurrentText("Вебка снизу")
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
              "cam": "Вебка снизу", "preset": "Мой 720p30", "llm": "none",
              "ollama_model": "llama3:8b", "obs_dir": r"D:\OBS", "nick_text": "Gosha",
              "hashtags": "#стрим #игры"}
    assert {k: saved.get(k) for k in expect} == expect
    assert saved.get("geometry")

    # новое окно показывает сохранённое
    win2 = A.MainWindow()
    assert not win2.cut.cb_subs.isChecked()
    assert win2.cut.sound.currentText() == "буп"
    assert win2.cut.count.value() == 7
    assert win2.cut.cam.currentText() == "Вебка снизу"
    assert win2.cut.preset.currentText() == "Мой 720p30"
    assert win2.settings_page.llm.currentText() == "Без модели"
    assert win2.settings_page.nick.text() == "Gosha"
    win2.close()
