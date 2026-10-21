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
