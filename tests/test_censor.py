"""Патч 3Б.2: частичная / полная цензура — настройка, клип, названия файлов, старые нарезки."""
import sys

import pytest

import autoclip


def test_clip_config_censor_levels():
    old = {"settings": {"bleep": True}}                        # нарезка до 1.3.0
    new = {"settings": {"bleep": True, "censor": "partial"}}
    assert autoclip.clip_config(old, {})["censor"] == "full"
    assert autoclip.clip_config(new, {})["censor"] == "partial"
    assert autoclip.clip_config(new, {"overrides": {"censor": "full"}})["censor"] == "full"
    assert autoclip.clip_config(old, {"overrides": {"censor": "partial"}})["censor"] == "partial"


def test_file_name_keeps_mask():
    name = autoclip.safe_name("ну " + autoclip.censor_word("ебать", "partial") + " вот")
    assert "*" not in name and "еать" not in name
    assert "＊" in name


def test_title_masked_by_clip_setting():
    clip = {"title": "блять ну и хуйня"}
    assert autoclip.clip_title(clip) == "*лять ну и ху*ня"
    clip["overrides"] = {"censor": "full"}
    assert autoclip.clip_title(clip) == "б**** ну и х****"
    desc = autoclip.auto_description({"title": "пиздец"}, "tiktok", {"hashtags": "", "platform_tags": {}})
    assert desc.startswith("пи*дец")


def test_moment_title_uses_setting(monkeypatch):
    monkeypatch.setitem(autoclip.CONFIG, "censor", "full")
    assert autoclip.moment_title("ебать ну", [], 0, 1, 0) == "е**** ну"
    monkeypatch.setitem(autoclip.CONFIG, "censor", "partial")
    assert autoclip.moment_title("ебать ну", [], 0, 1, 0) == "е*ать ну"


# ---------- окно ----------

@pytest.fixture
def A(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    import app
    qapp = QApplication.instance() or QApplication([])
    app.dark_palette(qapp)
    return app


def test_settings_censor_switch(A, monkeypatch):
    monkeypatch.setitem(autoclip.CONFIG, "censor", "partial")
    win = A.MainWindow()
    st = win.settings_page
    assert st.censor.currentData() == "partial"                # по умолчанию — частичная
    st.censor.setCurrentIndex(st.censor.findData("full"))
    assert win.settings["censor"] == "full"
    win.cut.apply_config()
    assert autoclip.CONFIG["censor"] == "full"
    win.close()
