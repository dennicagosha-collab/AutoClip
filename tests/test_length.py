"""«Длина клипов» — короче / обычно / длиннее (с 1.3.1 — окно вокруг момента, «обычно» как в 1.1)."""
import autoclip


def _words(times):
    return [{"s": t, "e": t + 0.4, "w": "слово"} for t in times]


def test_normal_is_1_1():
    base = {k: autoclip.CONFIG[k] for k in autoclip.LENGTHS["normal"]}
    assert base == autoclip.LENGTHS["normal"] == {"pre": 14.0, "post": 7.0, "min_len": 15.0, "max_len": 55.0}
    assert autoclip.CONFIG["clip_length"] == "normal"


def test_apply_length_switches_back_and_forth():
    cfg = dict(autoclip.CONFIG, clip_length="long")
    autoclip.apply_length(cfg)
    assert cfg["pre"] == 18.0 and cfg["min_len"] == 20.0
    cfg["clip_length"] = "normal"
    autoclip.apply_length(cfg)
    assert cfg["pre"] == 14.0 and cfg["post"] == 7.0
    cfg["clip_length"] = "что-то"                       # неизвестное — как «обычно»
    assert autoclip.apply_length(cfg)["pre"] == 14.0


def test_longer_gives_more_context(monkeypatch):
    # речь фразами по 1,5 с и паузами 1,6 с; пик на 60-й секунде
    words = _words([t * 0.5 for t in range(0, 300) if (t * 0.5) % 3 < 1.5])
    peak = 60.0
    lens = {}
    for var in ("short", "normal", "long"):
        cfg = autoclip.apply_length(dict(autoclip.CONFIG, clip_length=var))
        monkeypatch.setattr(autoclip, "CONFIG", cfg)
        s, e = autoclip.shape_clip(peak, peak - cfg["pre"], peak + cfg["post"], words, 150.0)
        s, e = autoclip.guard_edges(s, e, words)
        assert s <= peak <= e
        for w in words:                               # слово не режем ни в одном варианте
            assert not (w["s"] + 0.01 < s < w["e"] - 0.01)
            assert not (w["s"] + 0.01 < e < w["e"] - 0.01)
        lens[var] = e - s
    assert lens["short"] < lens["normal"] < lens["long"]


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
    assert autoclip.CONFIG["clip_length"] == "long" and autoclip.CONFIG["pre"] == 18.0
    st.length.setCurrentIndex(st.length.findData("normal"))
    win.cut.apply_config()
    assert autoclip.CONFIG["pre"] == 14.0
    win.close()
