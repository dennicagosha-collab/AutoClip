import numpy as np

import autoclip


def timeline(n=600, peaks=(100, 300, 500)):
    smooth = np.zeros(n)
    loud_z = np.zeros(n)
    for p in peaks:
        smooth[p - 2:p + 3] = 3.0
        smooth[p] = 4.0
        loud_z[p] = 3.0
    return smooth, loud_z


def test_clips_have_valid_length_and_do_not_overlap():
    smooth, loud_z = timeline()
    clips = autoclip.pick_clips(smooth, loud_z, [], [], 600.0)
    assert len(clips) == 3
    c = autoclip.CONFIG
    for cl in clips:
        assert c["min_len"] * 0.8 <= cl["e"] - cl["s"] <= c["max_len"]
        assert cl["s"] <= cl["peak"] <= cl["e"]
        assert all(cl["s"] <= z <= cl["e"] for z in cl["zooms"])
    ordered = sorted(clips, key=lambda x: x["s"])
    for a, b in zip(ordered, ordered[1:]):
        assert a["e"] <= b["s"]


def test_clip_count_limit():
    smooth, loud_z = timeline()
    autoclip.CONFIG["clips"] = 2
    assert len(autoclip.pick_clips(smooth, loud_z, [], [], 600.0)) == 2


def test_taken_intervals_are_skipped():
    smooth, loud_z = timeline()
    clips = autoclip.pick_clips(smooth, loud_z, [], [], 600.0, taken=[(280, 320)])
    assert len(clips) == 2
    assert all(c["e"] <= 280 or c["s"] >= 320 for c in clips)


def test_quiet_record_gives_no_clips():
    smooth, loud_z = np.zeros(600), np.zeros(600)
    assert autoclip.pick_clips(smooth, loud_z, [], [], 600.0) == []


def test_score_parts_sum_to_score():
    loud = np.full(300, -30.0)
    loud[150:153] = -5.0
    segs = [{"s": 149.0, "e": 152.0, "text": "ахахаха блять!",
             "words": [{"s": 149.5, "e": 150.0, "w": "ахахаха"},
                       {"s": 150.2, "e": 150.6, "w": "блять!"}]}]
    smooth, loud_z, parts = autoclip.score_timeline(loud, segs, [])
    assert np.allclose(smooth, sum(parts.values()))
    assert parts["смех"][150] > 0 and parts["мат"][150] > 0
    clips = autoclip.pick_clips(smooth, loud_z, segs, [], 300.0, parts)
    assert clips and abs(sum(clips[0]["parts"].values()) - clips[0]["score"]) < 0.05


# ---------- границы клипа: не на полуслове, дать договорить ----------

import random  # noqa: E402

import pytest  # noqa: E402


def seq(*items, start=0.0):
    """Слова встык, как их ставит Whisper в сплошной речи: (слово, длительность[, пауза после])."""
    out, t = [], start
    for it in items:
        w, d = it[0], it[1]
        out.append({"s": round(t, 2), "e": round(t + d, 2), "w": w})
        t += d + (it[2] if len(it) > 2 else 0.0)
    return out


def test_end_not_on_conjunction_lets_finish():
    # «стоит ли это 140к но тут все алюминиевая.» — «но» растянут, но фраза продолжается
    words = seq(("стоит", 0.5), ("ли", 0.2), ("это", 0.2), ("140к", 0.8), ("но", 1.0),
                ("тут", 0.2), ("все", 0.2), ("алюминиевая.", 0.8, 1.5), ("ладно", 0.4),
                start=10.0)
    e = autoclip.snap_end(12.0, words, lo=5.0, hi=40.0)
    assert e >= words[7]["e"]                       # договорил «алюминиевая»
    assert e < words[8]["s"]                        # и не залез на «ладно»


def test_hidden_pause_inside_stretched_word():
    # пауз между словами нет совсем, но «команд» длится 3 с — пауза спрятана в нём
    words = seq(("ну", 0.25), ("перед", 0.4), ("команд", 3.0), ("паук", 0.45),
                ("на", 0.3), ("ну", 0.3), ("короче", 0.6), start=20.0)
    e = autoclip.snap_end(21.0, words, lo=15.0, hi=40.0)
    assert e == pytest.approx(words[2]["e"])


def test_start_at_phrase_beginning():
    words = seq(("ну", 0.3), ("ладно", 0.4, 1.2), ("смотри", 0.4), ("сюда", 0.4),
                ("вот", 0.3), start=30.0)
    s = autoclip.snap_start(31.6, words, lo=0.0, hi=40.0)    # задумано посреди «смотри»
    assert words[1]["e"] <= s <= words[2]["s"]


@pytest.mark.parametrize("seed", range(200))
def test_bounds_never_inside_word(seed):
    rnd = random.Random(seed)
    items = [(rnd.choice(["и", "а", "вот", "слово", "длинноеслово", "да."]),
              rnd.uniform(0.15, 1.5), rnd.choice([0, 0, 0, rnd.uniform(0.1, 2)]))
             for _ in range(80)]
    words = seq(*items)
    t = rnd.uniform(5, words[-1]["e"] - 5)
    lo, hi = t - 8, t + 12
    e = autoclip.snap_end(t, words, lo, hi)
    s = autoclip.snap_start(t, words, lo, hi)
    for x in (e, s):
        assert lo <= x <= hi
        assert not any(w["s"] + 0.01 < x < w["e"] - 0.01 for w in words)


def test_picked_clips_end_in_pauses():
    smooth, loud_z = timeline()
    words = []
    t = 0.0
    while t < 590:                                   # сплошная речь, пауза раз в ~9 с
        for _ in range(12):
            words.append({"s": round(t, 2), "e": round(t + 0.6, 2), "w": "слово"})
            t += 0.6
        t += 1.5
    segs = [{"s": 0, "e": 600, "text": "", "words": words}]
    for c in autoclip.pick_clips(smooth, loud_z, segs, [], 600.0):
        for x in (c["s"], c["e"]):
            assert not any(w["s"] < x < w["e"] for w in words)
        nxt = min((w["s"] for w in words if w["s"] >= c["e"]), default=600)
        prev = max(w["e"] for w in words if w["e"] <= c["e"])
        assert nxt - prev >= autoclip.PAUSE
