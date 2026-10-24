"""Патч 3Б.3: «Длина клипов» — короче / обычно / длиннее."""
import autoclip


def _words(times):
    return [{"s": t, "e": t + 0.4, "w": "слово"} for t in times]


def test_normal_is_1_2_1():
    base = {k: autoclip.CONFIG[k] for k in autoclip.LENGTHS["normal"]}
    assert base == autoclip.LENGTHS["normal"]
    assert autoclip.CONFIG["clip_length"] == "normal"


def test_apply_length_switches_back_and_forth():
    cfg = dict(autoclip.CONFIG, clip_length="long")
    autoclip.apply_length(cfg)
    assert cfg["tail_after"] == 12.0 and cfg["lead_before"] == 3.0
    cfg["clip_length"] = "normal"
    autoclip.apply_length(cfg)
    assert cfg["tail_after"] == 8.0 and cfg["min_tight"] == 8.0
    cfg["clip_length"] = "что-то"                       # неизвестное — как «обычно»
    assert autoclip.apply_length(cfg)["tail_after"] == 8.0


def test_longer_gives_more_context():
    # фразы по 1,5 с и паузы 1,6 с: «короче» и «обычно» останавливаются на паузе, «длиннее» — нет
    words = _words([t * 0.5 for t in range(0, 120) if (t * 0.5) % 3 < 1.5])
    peak = 20.0
    lens = {}
    for var in ("short", "normal", "long"):
        cfg = autoclip.apply_length(dict(autoclip.CONFIG, clip_length=var))
        s, e = autoclip.tighten_clip(peak, 0.0, 55.0, words, cfg=cfg)
        assert s <= peak <= e
        for w in words:                               # слово не режем ни в одном варианте
            assert not (w["s"] + 0.01 < s < w["e"] - 0.01)
            assert not (w["s"] + 0.01 < e < w["e"] - 0.01)
        lens[var] = (s, e)
    assert lens["short"][1] < lens["normal"][1] < lens["long"][1]
    assert lens["long"][0] <= lens["normal"][0] <= lens["short"][0]


def test_settings_length_switch(monkeypatch):
    import sys
    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    import app
    app.dark_palette(QApplication.instance() or QApplication([]))
    win = app.MainWindow()
    st = win.settings_page
    assert st.length.currentData() == "normal"
    st.length.setCurrentIndex(st.length.findData("long"))
    win.cut.apply_config()
    assert autoclip.CONFIG["clip_length"] == "long" and autoclip.CONFIG["tail_after"] == 12.0
    st.length.setCurrentIndex(st.length.findData("normal"))
    win.cut.apply_config()
    assert autoclip.CONFIG["tail_after"] == 8.0
    win.close()
