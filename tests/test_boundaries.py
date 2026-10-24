"""ПАТЧ_4, 4.3: учиться на правках границ Гоши."""
import json
import os
import subprocess

import pytest

import autoclip
import boundaries


def _item(i, ds=-2.0, de=1.0):
    return {"recording": "з.mp4", "project": f"p{i}", "clip": "c01", "peak": 20.0 + i,
            "program": [10.0 + i, 30.0 + i], "gosha": [10.0 + i + ds, 30.0 + i + de]}


def test_shift_only_after_ten_edits():
    assert boundaries.default_shift([_item(i) for i in range(9)])[:2] == (None, None)
    ss, se, n = boundaries.default_shift([_item(i) for i in range(10)])
    assert (ss, se, n) == (-2.0, 1.0, 10)
    assert boundaries.default_shift([_item(i, 0.2, 0.1) for i in range(12)])[:2] == (None, None)   # незаметно
    assert boundaries.default_shift([_item(i, -30, 0) for i in range(12)])[0] == -boundaries.MAX_SHIFT


def test_apply_shift_keeps_words_and_peak():
    words = [{"s": 7.5, "e": 8.5, "w": "слово"}]
    s, e, note = boundaries.apply_shift(10.0, 30.0, 20.0, words, [], (-2.0, None, 12))
    assert s in (7.5 - autoclip.PAD_BEFORE, 7.35) or s <= 7.5         # не внутри слова
    assert e == 30.0 and "начало раньше на 2.0 с" in note and "(12)" in note
    s, e, _ = boundaries.apply_shift(10.0, 21.0, 20.0, [], [], (None, -5.0, 12))
    assert e >= 21.0 - 5.0 and e >= 20.0 + 1.0


def test_edits_become_golden():
    boundaries._save([dict(_item(1), recording="запись.mp4"), _item(2)])
    g = boundaries.golden_from_edits("запись.mp4")
    assert len(g) == 1 and g[0]["start"] == [9.0 - 1.5, 9.0 + 1.5]


def _project(tmp_path):
    dur = 40
    v = tmp_path / "запись.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=270x480:r=30:d={dur}",
                    "-f", "lavfi", "-i", f"aevalsrc='0.03*sin(2*PI*300*t)*(1+25*between(mod(t,20),10,12))':s=48000:d={dur}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(v)], check=True)
    segs = [{"s": t, "e": t + 2.4, "text": "ну вот смотри сюда",
             "words": [{"s": t + i * 0.6, "e": t + i * 0.6 + 0.5, "w": w}
                       for i, w in enumerate(["ну", "вот", "смотри", "сюда"])]} for t in range(0, dur, 4)]
    with open(tmp_path / "запись.transcript.json", "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False)
    autoclip.CONFIG.update(llm="none", clips=1, hook="off")
    return autoclip.process(str(v))


def test_rebuild_with_new_bounds_records_edit(tmp_path, fake_trash):
    cut = _project(tmp_path)
    c = autoclip.load_project(cut)["clips"][0]
    assert c["auto_start"] == c["start"]
    autoclip.rebuild_clip(cut, c["id"], start=c["start"] + 2.0)
    items = boundaries.load()
    assert len(items) == 1 and items[0]["recording"] == "запись.mp4"
    assert items[0]["program"][0] == pytest.approx(c["start"], abs=0.01)
    assert items[0]["gosha"][0] == pytest.approx(c["start"] + 2.0, abs=0.2)
    autoclip.rebuild_clip(cut, c["id"], overrides={"zoom": "off"})         # не границы — не правка
    assert len(boundaries.load()) == 1


def test_old_project_without_auto_bounds(tmp_path, fake_trash):
    cut = _project(tmp_path)
    proj = autoclip.load_project(cut)
    for c in proj["clips"]:
        c.pop("auto_start", None)
        c.pop("auto_end", None)
    autoclip.save_project(proj)
    c = proj["clips"][0]
    autoclip.rebuild_clip(cut, c["id"], end=c["end"] - 2.0)
    it = boundaries.load()[0]
    assert it["program"][1] == pytest.approx(c["end"], abs=0.01)           # границы до правки
