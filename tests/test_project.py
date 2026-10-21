"""Полный прогон на маленьком сгенерированном видео: нарезка → project.json → пересборка."""
import json
import os
import subprocess
import threading
import time

import pytest

import autoclip


def _make_video(path, dur=60):
    # громкие всплески на 10–12, 30–32 и 50–52 секундах
    audio = (f"aevalsrc='0.03*sin(2*PI*300*t)*(1+25*between(mod(t,20),10,12))'"
             f":s=48000:d={dur}")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=s=1080x1920:r=60:d={dur}", "-f", "lavfi", "-i", audio,
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                    str(path)], check=True)


def _fake_transcript(path, dur=60):
    segs = []
    for t0 in range(0, dur, 4):
        words = [{"s": t0 + i * 0.6, "e": t0 + i * 0.6 + 0.5, "w": w}
                 for i, w in enumerate(["ну", "вот", "смотри", "сюда"])]
        if t0 % 20 == 8:
            words[2]["w"] = "блять"
            words[3]["w"] = "ахахаха!"
        segs.append({"s": t0, "e": t0 + 2.4, "text": " ".join(w["w"] for w in words),
                     "words": words})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False)


@pytest.fixture
def video(tmp_path):
    v = tmp_path / "запись.mp4"
    _make_video(v)
    _fake_transcript(tmp_path / "запись.transcript.json")
    return v


def _probe_dur(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(p.stdout)


def test_process_writes_project_and_rebuild_works(video, fake_trash):
    autoclip.CONFIG.update(llm="none", clips=3)
    steps = []
    out_dir = autoclip.process(str(video), progress=lambda st, pct, msg: steps.append(st))
    assert set(autoclip.STAGES) <= set(steps)

    proj = autoclip.load_project(out_dir)
    assert proj["clips"]
    c = proj["clips"][0]
    for key in ("id", "file", "start", "end", "score", "score_parts", "title", "zooms",
                "hook", "status", "overrides", "created", "published"):
        assert key in c
    assert c["status"] == "new"
    assert os.path.isfile(os.path.join(out_dir, c["file"]))
    assert os.path.isfile(os.path.join(out_dir, "отчёт.txt"))

    # сдвиг начала на 2 с и выключенный зум у одного клипа
    new_start = c["start"] + 2
    t0 = time.time()
    rec = autoclip.rebuild_clip(out_dir, c["id"], start=new_start, overrides={"zoom": False})
    assert time.time() - t0 < 30
    assert rec["start"] == round(new_start, 2)
    assert rec["overrides"] == {"zoom": False}
    h = rec["hook"]
    hook_len = h["end"] - h["start"] if h["on"] else 0.0
    assert abs(_probe_dur(os.path.join(out_dir, c["file"]))
               - (rec["end"] - rec["start"] + hook_len)) < 0.2
    assert len(os.listdir(fake_trash)) == 1           # старая версия — в корзине

    saved = autoclip.load_project(out_dir)
    assert autoclip.find_clip(saved, c["id"])["start"] == rec["start"]

    # None убирает личную настройку
    rec = autoclip.rebuild_clip(out_dir, c["num"], overrides={"zoom": None})
    assert rec["overrides"] == {}


def test_recut_keeps_reviewed_clips(video, fake_trash):
    autoclip.CONFIG.update(llm="none", clips=3)
    out_dir = autoclip.process(str(video))
    proj = autoclip.load_project(out_dir)
    good = proj["clips"][0]
    good["status"] = "good"
    autoclip.save_project(proj)
    n_new = len(proj["clips"]) - 1

    autoclip.process(str(video))
    proj = autoclip.load_project(out_dir)
    assert autoclip.find_clip(proj, good["id"])["status"] == "good"
    assert os.path.isfile(os.path.join(out_dir, good["file"]))
    others = [c for c in proj["clips"] if c["id"] != good["id"]]
    assert all(c["end"] <= good["start"] or c["start"] >= good["end"] for c in others)
    assert len(os.listdir(fake_trash)) == n_new       # прежние «новые» клипы — в корзине


def test_cancel_stops_processing(video, fake_trash):
    autoclip.CONFIG.update(llm="none", clips=3)
    stop = threading.Event()

    def progress(stage, pct, msg):
        if stage == "рендер":
            stop.set()

    with pytest.raises(autoclip.Cancelled):
        autoclip.process(str(video), progress=progress, cancel=stop)


def test_missing_video_is_a_clear_error(tmp_path):
    with pytest.raises(autoclip.AutoClipError):
        autoclip.rebuild_clip(str(tmp_path), "1")
