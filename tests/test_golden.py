"""Эталон границ (ПАТЧ_4, 4.1): логика проверки — быстро; сама проверка на записи — медленно,
только с ключом --golden (py -3.13 -m pytest tests/test_golden.py --golden) и если запись есть."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import golden_check  # noqa: E402

M = {"name": "м", "anchor": 20.0, "start": [None, 12.0], "end": [28.0, 32.0], "must": [10.0, 25.0]}


def test_judge_ok_and_fails():
    ok = golden_check.judge(M, [{"s": 9.5, "e": 30.0}], [])
    assert ok[1] == "клип" and ok[2] == []
    late = golden_check.judge(M, [], [{"s": 15.0, "e": 40.0}])
    assert late[1] == "кандидат" and late[2] == ["начало", "конец", "нет нужного куска"]
    assert golden_check.judge(M, [{"s": 30, "e": 50}], [])[2] == ["момент не найден"]


def test_summary_counts_dead_and_cut_words():
    words = [{"s": 9.8, "e": 10.4, "w": "а"}]
    dead = [True] * 5 + [False] * 15
    s = golden_check.summary([{"s": 0.0, "e": 10.0}], words, dead)
    assert s["n"] == 1 and s["cut_words"] == 1 and abs(s["dead"] - 0.5) < 1e-9


def test_golden_file_valid():
    rec, moments = golden_check.load_golden(os.path.join(golden_check.GOLDEN_DIR, "123123123.json"))
    assert rec.endswith(".mp4") and len(moments) >= 6
    for m in moments:
        assert m["start"][1] is None or m["start"][1] <= m["anchor"] <= (m["end"][0] or 1e9)


@pytest.mark.golden
def test_golden_on_recording(request):
    if not request.config.getoption("--golden"):
        pytest.skip("медленная проверка на записи — с ключом --golden")
    path = os.path.join(golden_check.GOLDEN_DIR, "123123123.json")
    rec, moments, meta = golden_check.load_golden(path, with_meta=True)
    video = golden_check.find_video(golden_check.RECORDINGS, meta)
    if not video:
        pytest.skip("записи нет")
    rows, _ = golden_check.run_once(video, moments)
    bad = [(m["name"], b) for m, c, k, b in rows if b]
    assert not bad, bad
