"""Метки из OBS: чтение глав, поиск момента до метки, приоритет в отборе."""
import json
import os
import subprocess

import numpy as np
import pytest

import autoclip


def add_chapters(src, dst, times, dur):
    """Как OBS: главы в MP4 (первая — начало файла), дальше — нажатия горячей клавиши."""
    meta = src.parent / "meta.txt"
    starts = [0.0] + list(times)
    lines = [";FFMETADATA1"]
    for i, t in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else dur
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(t * 1000)}",
                  f"END={int(end * 1000)}", f"title={'Start' if i == 0 else f'Chapter {i}'}"]
    meta.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-i", str(meta),
                    "-map_metadata", "1", "-map_chapters", "1", "-c", "copy", str(dst)], check=True)


@pytest.fixture
def plain_video(tmp_path):
    v = tmp_path / "plain.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=s=270x480:r=30:d=90", "-f", "lavfi", "-i",
                    "aevalsrc='0.03*sin(2*PI*300*t)':s=48000:d=90", "-c:v", "libx264",
                    "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(v)], check=True)
    return v


def test_read_markers_skips_file_start(tmp_path, plain_video):
    v = tmp_path / "запись.mp4"
    add_chapters(plain_video, v, [20.5, 61.0], 90)
    marks = autoclip.read_markers(str(v))
    assert [m["t"] for m in marks] == [20.5, 61.0]


def test_no_markers_no_problem(plain_video):
    assert autoclip.read_markers(str(plain_video)) == []


def flat(n=600, level=0.2):
    return np.full(n, level), np.zeros(n)


def test_marked_quiet_moment_goes_first():
    smooth, loud_z = flat()
    smooth[100] = 3.0                         # громкий момент без метки
    smooth[410] = 0.4                         # тихий, но стример поставил метку через 12 с
    autoclip.CONFIG["clips"] = 2
    clips = autoclip.pick_clips(smooth, loud_z, [], [], 600.0, marks=[{"t": 422.0, "name": ""}])
    assert len(clips) == 2
    first = clips[0]
    assert first["marks"] == [422.0]
    assert first["s"] <= 410 <= first["e"]
    assert first["parts"]["метка"] == autoclip.CONFIG["mark_bonus"]
    assert not clips[1]["marks"]


def test_mark_looks_back_window_only():
    smooth, loud_z = flat()
    smooth[300] = 2.0                         # за 25 с до метки — найдётся
    smooth[260] = 5.0                         # за 65 с — уже другой момент
    peaks = autoclip.mark_peaks(smooth, [{"t": 325.0, "name": ""}])
    assert peaks[0][0] == 300


def test_all_marks_kept_even_above_clip_count():
    smooth, loud_z = flat()
    autoclip.CONFIG["clips"] = 1
    marks = [{"t": t, "name": ""} for t in (100.0, 250.0, 400.0)]
    clips = autoclip.pick_clips(smooth, loud_z, [], [], 600.0, marks=marks)
    assert sorted(t for c in clips for t in c["marks"]) == [100.0, 250.0, 400.0]


def test_two_marks_on_one_moment_make_one_clip():
    smooth, loud_z = flat()
    smooth[200] = 2.0
    marks = [{"t": 210.0, "name": ""}, {"t": 215.0, "name": ""}]
    autoclip.CONFIG["clips"] = 1
    clips = autoclip.pick_clips(smooth, loud_z, [], [], 600.0, marks=marks)
    assert len(clips) == 1 and clips[0]["marks"] == [210.0, 215.0]


def test_process_with_obs_marks(tmp_path, plain_video, fake_trash):
    v = tmp_path / "стрим.mp4"
    add_chapters(plain_video, v, [70.0], 90)
    with open(tmp_path / "стрим.transcript.json", "w", encoding="utf-8") as f:
        json.dump([{"s": 50.0, "e": 53.0, "text": "ахахаха вот это да",
                    "words": [{"s": 50.2, "e": 50.9, "w": "ахахаха"}, {"s": 51.0, "e": 51.3, "w": "вот"},
                              {"s": 51.4, "e": 51.7, "w": "это"}, {"s": 51.8, "e": 52.2, "w": "да"}]}],
                  f, ensure_ascii=False)
    autoclip.CONFIG.update(llm="none", clips=1, hook=False)
    out = autoclip.process(str(v))
    proj = autoclip.load_project(out)
    assert proj["marks"] == [{"t": 70.0, "name": "Chapter 1"}]
    c = proj["clips"][0]
    assert c["marks"] == [70.0] and c["start"] <= 51 <= c["end"]
    assert "метка из OBS" in open(os.path.join(out, "отчёт.txt"), encoding="utf-8").read()

    autoclip.CONFIG["marks"] = False          # галочка выключена — метки не читаются
    out2 = autoclip.process(str(v))
    assert autoclip.load_project(out2)["marks"] == []
