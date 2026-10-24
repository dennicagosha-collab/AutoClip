"""Границы клипа по речи (1.2.1): модель — только подсказка."""
import numpy as np

import autoclip


def talk(a, b, step=0.6, dur=0.45):
    """Речь подряд от a до b (слова с маленькими паузами)."""
    out, t = [], a
    while t + dur <= b:
        out.append({"s": round(t, 2), "e": round(t + dur, 2), "w": "слово"})
        t += step
    return out


def inside(t, words):
    return any(w["s"] + 0.01 < t < w["e"] - 0.01 for w in words)


def test_long_model_answer_end_after_peak():
    words = talk(10, 16) + talk(40, 45)                     # реакция 10–16, потом 24 с тишины
    s, e = autoclip.tighten_clip(14.0, 9.0, 50.0, words)
    assert e - 14.0 <= 8.0 + 0.5 and not inside(e, words)   # не дальше 8 с после пика
    assert s >= 10 - 1.5 - 0.01


def test_keeps_talking_without_pauses_up_to_15():
    words = talk(10, 40)                                    # говорит без пауз
    s, e = autoclip.tighten_clip(14.0, 9.0, 45.0, words)
    assert 14.0 + 8 < e <= 14.0 + 15 + 0.5                  # договаривает, но не дальше 15 с
    assert not inside(e, words)


def test_pause_before_peak_cut_from_start():
    words = talk(5, 8) + talk(18, 25)                       # пауза 10 с до пика
    s, e = autoclip.tighten_clip(21.0, 4.0, 26.0, words)
    assert s >= 18 - autoclip.PAD_BEFORE - 0.01 and not inside(s, words)


def test_pause_after_peak_cut_from_end():
    words = talk(10, 16) + talk(26.5, 30)                   # пауза 10 с после пика
    s, e = autoclip.tighten_clip(12.0, 9.0, 31.0, words)
    assert e <= 16 + autoclip.PAD_AFTER + 0.01


def test_leading_silence_trimmed_unless_loud():
    words = talk(20, 30)
    s, _ = autoclip.tighten_clip(25.0, 5.0, 32.0, words)
    assert abs(s - 18.5) < 0.05                             # 1,5 с до первой речи
    parts = {k: np.zeros(40) for k in ("смех", "восклицания")}
    parts["смех"][12] = 1.0                                 # смех до первых слов — от него
    s, _ = autoclip.tighten_clip(25.0, 5.0, 32.0, words, parts)
    assert abs(s - 11.7) < 0.05


def test_short_after_tighten_goes_to_candidates():
    n = 200
    smooth = np.zeros(n)
    smooth[60] = 5.0
    smooth[120] = 3.0
    segs = [{"s": 58, "e": 63, "text": "", "words": talk(58.5, 62.5)},
            {"s": 100, "e": 140, "text": "", "words": talk(100, 135)}]
    found = autoclip.pick_clips(smooth, np.zeros(n), segs, [], 200.0, limit=5)
    short = [c for c in found if c["short"]]
    assert short and short[0]["e"] - short[0]["s"] < 8
    clips, cands = autoclip.split_clips(found, dict(autoclip.CONFIG, clips_mode="count", clips=5))
    assert all(not c["short"] for c in clips) and short[0] in cands


def test_start_of_record_noise_dropped():
    segs = [{"s": 6.5, "e": 9.1, "text": "медсестра сила",
             "words": [{"s": 6.51, "e": 7.91, "w": "медсестра"}, {"s": 7.91, "e": 9.09, "w": "сила"}]},
            {"s": 40, "e": 42, "text": "ну вот", "words": [{"s": 40, "e": 40.4, "w": "ну"},
                                                            {"s": 40.5, "e": 41, "w": "вот"}]}]
    assert [sg["s"] for sg in autoclip.drop_hallucinations(segs)] == [40]
    segs2 = [{"s": 5, "e": 8, "text": "раз два три", "words": [
        {"s": 5, "e": 5.4, "w": "раз"}, {"s": 6, "e": 6.4, "w": "два"}, {"s": 7, "e": 7.4, "w": "три"}]}]
    assert autoclip.drop_hallucinations(segs2, [(20, 25)]) == []     # голоса нет — шум
    assert autoclip.drop_hallucinations(segs2, [(4.9, 7.5)]) == segs2


def test_edge_inside_stretched_word_moved_out():
    words = talk(10, 16) + [{"s": 16.2, "e": 18.1, "w": "это"}]     # Whisper растянул слово
    s, e = autoclip.tighten_clip(13.0, 9.0, 17.0, words)
    assert not inside(e, words) and e >= 18.1


def test_soft_pause_on_side_without_peak():
    words = talk(10, 20) + talk(24, 26)                             # пауза 4 с после пика
    s, e = autoclip.tighten_clip(15.0, 9.0, 27.0, words)
    assert e <= 20 + autoclip.PAD_AFTER + 0.01                      # клип ≥ 8 с — паузу отрезали
    words = talk(14, 17) + talk(21, 26)                             # отрезать — будет короче 8 с
    s, e = autoclip.tighten_clip(16.0, 12.5, 27.0, words)
    assert e > 21


def test_mostly_silent_moment_goes_to_candidates():
    words = talk(10, 12) + talk(17, 18) + talk(22, 23)            # реакции почти нет — пауза на паузе
    assert autoclip.silence_share(9.5, 23.5, words) > 0.45
    assert autoclip.silence_share(10, 16, talk(10, 16)) == 0
    n = 60
    smooth = np.zeros(n)
    smooth[17] = 5.0
    found = autoclip.pick_clips(smooth, np.zeros(n), [{"s": 10, "e": 23, "text": "", "words": words}],
                                [], 60.0, limit=3)
    assert found and all(c["short"] for c in found)
