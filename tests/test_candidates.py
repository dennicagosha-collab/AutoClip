"""Режим «Авто» для числа клипов и кандидаты."""
import json
import os
import subprocess
import sys

import pytest

import autoclip
from qtwait import pump


def mom(score, marks=()):
    return {"s": score, "e": score + 20, "score": score, "marks": list(marks)}


def test_split_count_mode():
    found = [mom(x) for x in (5.0, 1.0, 3.0, 0.7, 2.0)]
    cfg = dict(autoclip.CONFIG, clips_mode="count", clips=2, max_candidates=2)
    clips, cands = autoclip.split_clips(found, cfg)
    assert [c["score"] for c in clips] == [5.0, 3.0]
    assert [c["score"] for c in cands] == [2.0, 1.0]                # потолок кандидатов


def test_split_auto_mode_threshold_ceiling_and_marks():
    found = [mom(x) for x in (5.0, 4.0, 3.0, 2.6, 2.4, 1.0)] + [mom(0.8, marks=[100.0])]
    cfg = dict(autoclip.CONFIG, clips_mode="auto", auto_min_score=2.5, auto_max=30, max_candidates=20)
    clips, cands = autoclip.split_clips(found, cfg)
    assert [c["score"] for c in clips] == [5.0, 4.0, 3.0, 2.6, 0.8]   # метка — всегда клип
    assert [c["score"] for c in cands] == [2.4, 1.0]
    cfg["auto_max"] = 3
    clips, cands = autoclip.split_clips(found, cfg)
    assert [c["score"] for c in clips] == [5.0, 4.0, 0.8]             # 2 обычных + метка = потолок
    assert [c["score"] for c in cands] == [3.0, 2.6, 2.4, 1.0]


def _video(tmp_path, dur=90):
    v = tmp_path / "запись.mp4"
    audio = f"aevalsrc='0.03*sin(2*PI*300*t)*(1+25*between(mod(t,30),10,12))':s=48000:d={dur}"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=s=270x480:r=30:d={dur}", "-f", "lavfi", "-i", audio,
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                    str(v)], check=True)
    segs = [{"s": t, "e": t + 2.4, "text": "ну вот смотри сюда",
             "words": [{"s": t + i * 0.6, "e": t + i * 0.6 + 0.5, "w": w}
                       for i, w in enumerate(["ну", "вот", "смотри", "сюда"])]}
            for t in range(0, dur, 4)]
    with open(tmp_path / "запись.transcript.json", "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False)
    return v


@pytest.fixture
def cut(tmp_path, fake_trash):
    autoclip.CONFIG.update(llm="none", clips=1, hook=False, clips_mode="count")
    return autoclip.process(str(_video(tmp_path)))


def test_process_keeps_candidates_and_builds_one(cut):
    proj = autoclip.load_project(cut)
    assert len(proj["clips"]) == 1
    cands = proj["candidates"]
    assert cands and all(not os.path.exists(os.path.join(cut, f"{k['id']}.mp4")) for k in cands)
    assert len([f for f in os.listdir(cut) if f.endswith(".mp4")]) == 1     # видео только у клипа
    k = cands[0]
    assert {"id", "start", "end", "score", "title", "text"} <= set(k)
    rec = autoclip.build_candidate(cut, k["id"])
    proj = autoclip.load_project(cut)
    assert rec["origin"] == "candidate" and rec["num"] == 2
    assert (rec["start"], rec["end"]) == (k["start"], k["end"])
    assert os.path.isfile(os.path.join(cut, rec["file"]))
    assert k["id"] not in [x["id"] for x in proj["candidates"]]
    with pytest.raises(autoclip.AutoClipError):
        autoclip.build_candidate(cut, k["id"])
    assert "Кандидаты" in open(os.path.join(cut, "отчёт.txt"), encoding="utf-8").read()


def test_auto_mode_cut(tmp_path, fake_trash):
    autoclip.CONFIG.update(llm="none", hook=False, clips_mode="auto", auto_min_score=99.0,
                           auto_min_score_plain=99.0)
    out = autoclip.process(str(_video(tmp_path)))
    proj = autoclip.load_project(out)
    assert proj["clips"] == [] and proj["candidates"]                # выше порога ничего — всё кандидаты


# ---------- окно ----------

@pytest.fixture
def win(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", lambda m: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    w = A.MainWindow()
    w.show()
    yield A, w
    w.close()


def wait_for(cond, ms=60000):
    for _ in range(ms // 50):
        if cond():
            return True
        pump(50)
    return cond()


def test_mode_switch_saved(win):
    A, w = win
    w.cut.set_mode("auto")
    assert not w.cut.count.isEnabled() and A.load_settings()["clips_mode"] == "auto"
    w.settings_page.auto_min.setValue(3.5)
    w.settings_page.auto_max.setValue(12)
    w.cut.apply_config()
    assert autoclip.CONFIG["clips_mode"] == "auto" and autoclip.CONFIG["auto_min_score"] == 3.5
    assert autoclip.CONFIG["auto_max"] == 12
    w.cut.set_mode("count")
    w.cut.apply_config()
    assert w.cut.count.isEnabled() and autoclip.CONFIG["clips_mode"] == "count"


def test_candidates_in_clip_list(win, cut):
    A, w = win
    page = w.clips
    page.load(cut)
    proj = autoclip.load_project(cut)
    n_clips, n_cands = len(proj["clips"]), len(proj["candidates"])
    assert page.list.count() == n_clips + n_cands
    last = page.list.item(page.list.count() - 1)
    assert str(last.data(0x0100)).startswith(A.CAND)                 # внизу списка
    assert last.data(A.CLIP_PATH) is None                            # без видео — не перетащить
    page.set_filter(4)                                               # «Кандидаты»
    assert page.list.count() == n_cands
    page.list.setCurrentRow(0)
    assert page.current_clip() is None and page.current_candidate()
    assert not page.btn_build.isHidden() and not page.editor.isEnabled()
    page.build_candidate()
    assert wait_for(lambda: not page.busy)
    c = page.current_clip()
    assert c and c["origin"] == "candidate" and page.btn_build.isHidden()
    assert page.filter == 0


def test_old_project_without_candidates(win, cut):
    A, w = win
    pp = os.path.join(cut, autoclip.PROJECT_FILE)
    data = json.load(open(pp, encoding="utf-8"))
    data.pop("candidates")
    data.pop("loud_z")
    json.dump(data, open(pp, "w", encoding="utf-8"), ensure_ascii=False)
    w.clips.load(cut)
    assert w.clips.list.count() == len(data["clips"])
    w.clips.set_filter(4)
    assert w.clips.list.count() == 0
