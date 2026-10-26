"""Патч 3Б.5: «Вкл / Выкл / Авто» для хука и зума."""
import numpy as np

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


def test_hook_never_a_sigh():
    """Вздох, кашель, обрывок короче 0,5 с — не хук (5.9)."""
    r = np.zeros(60)
    r[30] = 4.0
    words = [{"s": 30.1, "e": 30.4, "w": "кхм"}]
    h = autoclip.decide_hook(10, 50, r, [{"s": 30, "e": 31, "words": words}], peak=30)
    assert h["start"] is None and not h["auto"]


def test_hook_phrase_plus_laugh():
    """Короткая фраза + смех сразу после неё (голос без слов) — хук целиком."""
    r = np.zeros(60)
    r[31] = 3.0
    words = [{"s": 29.8, "e": 30.1, "w": "а"}, {"s": 30.1, "e": 30.9, "w": "блядь"}]
    h = autoclip.decide_hook(10, 50, r, [{"s": 29.8, "e": 31, "words": words}], peak=31,
                             voice=[(29.7, 31.0), (31.2, 32.2)])
    assert h["start"] <= 29.8 and 31.9 <= h["end"] <= 32.4

