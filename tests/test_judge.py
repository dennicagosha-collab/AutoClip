"""0.1.7: модель — главный судья клипов; хук — её цитата из этого же клипа; мат не даёт баллов."""
import json

import numpy as np

import autoclip
import judge


def _seg(words, spk="me"):
    ws = [dict(w, spk=spk) for w in words]
    return {"s": ws[0]["s"], "e": ws[-1]["e"], "text": " ".join(w["w"] for w in ws), "words": ws, "spk": spk}


SEGS = [_seg([{"s": 100.0, "e": 100.4, "w": "короче"}, {"s": 100.5, "e": 101.0, "w": "иду"}]),
        _seg([{"s": 106.0, "e": 106.4, "w": "Ты"}, {"s": 106.5, "e": 106.9, "w": "куда,"},
              {"s": 107.0, "e": 107.5, "w": "блядь,"}, {"s": 107.6, "e": 108.2, "w": "полез?"}]),
        _seg([{"s": 112.0, "e": 112.5, "w": "ну"}, {"s": 112.6, "e": 113.4, "w": "всё"}], spk="team")]


def test_score_is_weighted_and_clamped():
    assert judge.score_of({"hook": 10, "payoff": 10, "standalone": 10, "emotion": 10}) == 10.0
    assert judge.score_of({"hook": 0, "payoff": 99, "standalone": 1, "emotion": 1}) in (4.1, 4.2)   # 0,3+3,5+0,15+0,2


def test_clip_text_has_times_and_speakers():
    t = judge.clip_text(SEGS, 104.0, 114.0)
    assert "[2] Я: Ты куда, блядь, полез?" in t and "Друг: ну всё" in t
    assert "перед этим" in t and "иду" in t                 # реплика перед клипом — для понимания


def test_hook_from_quote_inside_clip():
    a, b = judge.hook_from_quote("Ты куда блядь полез", 100.0, 115.0, SEGS)
    assert 105.8 <= a <= 106.0 and 108.2 <= b <= 108.7       # края в паузах, слова не режутся
    assert judge.hook_from_quote("куда полез", 109.0, 115.0, SEGS) is None   # вне клипа — нельзя (правило 5)
    assert judge.hook_from_quote("совсем другие слова тут", 100.0, 115.0, SEGS) is None


def test_decide_hook_by_judge():
    c = {"s": 100.0, "e": 115.0, "judge": {"hook_quote": "Ты куда, блядь, полез?"}}
    h = judge.decide_hook(c, SEGS)
    assert h["auto"] and 100.0 <= h["start"] < h["end"] <= 115.0 and "модель" in h["why"]
    assert not judge.decide_hook(dict(c, judge={"hook_quote": ""}), SEGS)["auto"]
    assert not judge.decide_hook(dict(c, s=105.0), SEGS)["auto"]           # клип и так с этого начинается
    assert judge.decide_hook({"s": 1, "e": 2}, SEGS) is None                # судьи не было — старое правило


def test_judge_clips_sets_scores(monkeypatch):
    found = [{"s": 100.0, "e": 115.0, "score": 3.0, "title": "", "reason": ""},
             {"s": 200.0, "e": 215.0, "score": 4.0, "title": "", "reason": ""}]
    asked = []

    def ask(prompt, mode, cancel=None):
        asked.append(prompt)
        return json.dumps({"clips": [
            {"id": 1, "hook": 9, "payoff": 8, "standalone": 7, "emotion": 9, "hook_quote": "куда полез",
             "why": "резкое начало и смешной итог", "title": "Куда полез"},
            {"id": 2, "hook": 2, "payoff": 2, "standalone": 3, "emotion": 2, "hook_quote": "",
             "why": "просто переговоры", "title": "Переговоры"}]})
    monkeypatch.setattr(judge, "ask", ask)
    n = judge.judge_clips(found, SEGS, "ollama", (["взял это"], ["выкинул это"]))
    assert n == 2
    assert found[1]["judge"]["value"] > 7 > 3 > found[0]["judge"]["value"]   # №1 в запросе — лучший по звуку
    assert all(c["score"] == c["judge"]["value"] for c in found)
    assert "ВЗЯЛ" in asked[0] and "ВЫКИНУЛ" in asked[0] and "выкинул это" in asked[0]
    assert all(c["reason"] for c in found)


def test_judge_silence_keeps_old(monkeypatch):
    found = [{"s": 100.0, "e": 115.0, "score": 3.0}]
    monkeypatch.setattr(judge, "ask", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    assert judge.judge_clips(found, SEGS, "ollama") == 0 and found[0]["score"] == 3.0 and "judge" not in found[0]


def test_mat_does_not_add_score():
    loud = np.full(60, -20.0)
    calm = [_seg([{"s": 10.0 + i * 0.5, "e": 10.4 + i * 0.5, "w": "слово"} for i in range(6)])]
    swear = [_seg([{"s": 10.0 + i * 0.5, "e": 10.4 + i * 0.5, "w": "блять"} for i in range(6)])]
    a, _, _ = autoclip.score_timeline(loud, calm, [])
    b, _, parts = autoclip.score_timeline(loud, swear, [])
    assert np.allclose(a, b)                                  # мат — не плюс к оценке места
    assert parts["мат"].max() > 0                             # но как реакция он виден (хук, зум)


def test_forecast_uses_judge():
    import forecast
    f = {"loud": 0, "laugh": 0, "mat": 0, "excl": 0, "speech": 0, "llm": 0}
    assert forecast.predict(f, 3.0, None, 8.0)["value"] == 8.0
    assert forecast.predict(f, 3.0, None, 2.0)["value"] == 2.0


def test_taste_bad(tmp_path, monkeypatch):
    import store
    data = {"items": {"a": {"rating": "bad", "text": "скучно", "date": "2026-11-01"},
                      "b": {"rating": "post", "text": "смешно", "date": "2026-11-02"},
                      "c": {"rating": "bad", "text": "переговоры", "date": "2026-11-03"}}}
    monkeypatch.setattr(store, "load", lambda: data)
    assert store.taste_bad(3) == ["переговоры", "скучно"]


def test_api_key_from_settings(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setitem(autoclip.CONFIG, "anthropic_key", "")
    assert autoclip.anthropic_key() == ""
    import secret
    monkeypatch.setitem(autoclip.CONFIG, "anthropic_key", secret.protect("sk-ant-test"))
    assert autoclip.anthropic_key() == "sk-ant-test"
    monkeypatch.setattr(autoclip, "_ollama_alive", lambda: True)
    assert autoclip.pick_llm("auto") == "anthropic"           # ключ есть — Claude, даже если Ollama запущена
