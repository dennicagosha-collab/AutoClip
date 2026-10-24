"""Патч 3Б.5: «Вкл / Выкл / Авто» для хука и зума."""
import autoclip


def _parts(n, laugh=(), shout=(), game=()):
    p = {k: [0.0] * n for k in ("смех", "восклицания", "громкость", "речь", "мат")}
    for i in laugh:
        p["смех"][i] = 1.0
    for i in shout:
        p["восклицания"][i] = 1.0
    for i in game:                       # громко, но речи нет — звук игры
        p["громкость"][i] = 3.0
    return p


def test_tri_values():
    assert autoclip.tri(True) == "auto" and autoclip.tri(True, "on") == "on"
    assert autoclip.tri(False) == "off" and autoclip.tri(None) is None
    assert autoclip.tri("on") == "on" and autoclip.tri("чепуха") == "auto"


def test_auto_zoom_only_on_voice_reaction():
    n = 60
    reaction = [0.1] * n
    for i in (12, 30, 40, 45, 50):
        reaction[i] = 3.0
    parts = _parts(n, laugh=(12, 50), shout=(45,), game=(30, 40))
    z = autoclip.auto_zooms(0, 59, reaction, parts, threshold=2.0)
    assert [p["t"] for p in z] == [12.0, 45.0, 50.0]                # игра (30, 40) — без зума
    assert z[0]["why"] == "смех" and z[1]["why"] == "крик"
    assert len(autoclip.auto_zooms(0, 59, reaction, parts, 2.0, limit=2)) == 2
    calm = autoclip.auto_zooms(0, 59, [0.1] * n, parts, threshold=2.0)
    assert calm == []                                                # спокойный клип — без зума


def test_clip_zooms_modes():
    rec = {"start": 10, "end": 40, "zooms": [15.0, 20.0, 30.0],
           "zoom_auto": [{"t": 20.0, "why": "смех"}], "overrides": {}}
    assert autoclip.clip_zooms(rec, {"zoom": "auto"}) == ([20.0], "зум: смех на 0:10")
    assert autoclip.clip_zooms(rec, {"zoom": "on"})[0] == [15.0, 20.0, 30.0]
    assert autoclip.clip_zooms(rec, {"zoom": "off"})[0] == []
    rec["overrides"]["zoom"] = "off"
    assert autoclip.clip_zooms(rec, {"zoom": "on"}) == ([], "без зума — выключен")
    rec["overrides"]["zoom"] = True                                  # старая галочка у клипа
    assert autoclip.clip_zooms(rec, {"zoom": "off"})[0] == [15.0, 20.0, 30.0]
    rec = {"start": 10, "end": 40, "zooms": [15.0], "zoom_auto": [], "overrides": {}}
    assert autoclip.clip_zooms(rec, {"zoom": "auto"}) == ([], "без зума — нет яркой реакции")
    old = {"start": 10, "end": 40, "zooms": [15.0], "overrides": {}}          # нарезка до 1.3.0
    assert autoclip.clip_zooms(old, {"zoom": True})[0] == [15.0]


def test_hook_modes():
    h = {"auto": False, "start": 12.0, "end": 13.5, "why": "нет яркой реакции в клипе"}
    rec = {"start": 10, "end": 40, "hook": h, "overrides": {}}
    assert autoclip.hook_span(rec, {"hook": "auto"}) is None
    assert autoclip.hook_span(rec, {"hook": "on"}) == (12.0, 13.5)    # «Вкл» — ставим и так
    h["auto"] = True
    assert autoclip.hook_span(rec, {"hook": "auto"}) == (12.0, 13.5)
    assert autoclip.hook_span(rec, {"hook": "off"}) is None
    rec["overrides"]["hook"] = "off"
    assert autoclip.hook_span(rec, {"hook": "on"}) is None
    rec["overrides"]["hook"] = False                                  # старая галочка у клипа
    assert autoclip.hook_span(rec, {"hook": True}) is None
    assert autoclip.clip_config({"settings": {"hook": True}}, {"overrides": {"hook": True}})["hook"] == "on"
    assert autoclip.clip_config({"settings": {"hook": True}}, {"overrides": {}})["hook"] == "auto"


def test_hook_on_wordless_reaction():
    # слова сплошняком вокруг пика нет: смех на 20-й секунде в паузе 18–23 с
    words = [{"s": 10 + k * 0.3, "e": 10 + k * 0.3 + 0.3, "w": "бла"} for k in range(27)]   # 10–18,1
    words += [{"s": 23 + k * 0.3, "e": 23 + k * 0.3 + 0.3, "w": "бла"} for k in range(20)]  # 23–29
    hs, he = autoclip._hook_window(20, 10, 30, words)
    assert hs is not None and 18.1 <= hs < he <= 23.0
    assert 1.0 <= he - hs <= 2.0
    for w in words:
        assert not (w["s"] < hs < w["e"]) and not (w["s"] < he < w["e"])


def test_hook_tries_other_bright_moment():
    # самое яркое место — посреди сплошной речи, второе по яркости — короткая фраза с паузами
    words = [{"s": 10 + k * 0.3, "e": 10 + k * 0.3 + 0.3, "w": "бла"} for k in range(34)]   # 10–20,2
    words += [{"s": 22.0, "e": 22.4, "w": "да"}, {"s": 22.5, "e": 23.0, "w": "ну"}]
    words += [{"s": 25 + k * 0.3, "e": 25 + k * 0.3 + 0.3, "w": "бла"} for k in range(16)]  # 25–30
    segs = [{"s": 10, "e": 30, "words": words}]
    reaction = [0.0] * 40
    reaction[15] = 5.0
    reaction[22] = 4.5
    h = autoclip.decide_hook(10, 30, reaction, segs, threshold=2.0)
    assert h["auto"] and h["start"] is not None
    assert 20.2 <= h["start"] and h["end"] <= 25.0
    for w in words:
        assert not (w["s"] + 0.01 < h["start"] < w["e"] - 0.01)
        assert not (w["s"] + 0.01 < h["end"] < w["e"] - 0.01)


def test_settings_tri_and_old_bool(tmp_path, monkeypatch):
    import json
    import sys
    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    with open(autoclip.SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump({"zoom": True, "hook": False}, f)            # настройки 1.2.1
    import app
    app.dark_palette(QApplication.instance() or QApplication([]))
    win = app.MainWindow()
    st = win.settings_page
    assert st.cb_zoom.currentData() == "auto" and st.cb_hook.currentData() == "off"
    st.cb_hook.setCurrentIndex(st.cb_hook.findData("on"))
    win.cut.apply_config()
    assert autoclip.CONFIG["hook"] == "on" and autoclip.CONFIG["zoom"] == "auto"
    win.close()


def test_hook_by_voice_pauses_when_words_glued():
    # Whisper поставил слова встык, а в голосе есть паузы 14,9–15,2 и 16,6–16,9
    words = [{"s": 10 + k * 0.4, "e": 10 + (k + 1) * 0.4, "w": "бла"} for k in range(50)]
    segs = [{"s": 10, "e": 30, "words": words}]
    voice = [(10.0, 14.9), (15.2, 16.6), (16.9, 30.0)]
    reaction = [0.0] * 40
    reaction[16] = 5.0
    assert autoclip.decide_hook(10, 30, reaction, segs, threshold=2.0)["start"] is None
    h = autoclip.decide_hook(10, 30, reaction, segs, threshold=2.0, voice=voice)
    assert h["auto"] and (h["start"], h["end"]) == (15.05, 16.75)
