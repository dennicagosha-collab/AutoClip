"""Обложка клипа: момент, выбор кадра (лицо, резкость, не тёмный), файл рядом с клипом."""
import json
import os
import subprocess

import numpy as np
import pytest

import autoclip


def test_cover_moment_is_brightest_reaction_inside_clip():
    r = np.zeros(100)
    r[30] = 5.0                                   # ярче, но вне клипа
    r[55] = 2.0
    clip = {"start": 40.0, "end": 70.0}
    assert autoclip.cover_moment(clip, r) == pytest.approx(55.5)
    assert autoclip.cover_moment(clip, []) == pytest.approx(55.0)    # нет данных — середина


@pytest.mark.parametrize("fy,zone", [(0.30, (0, 240)), (0.70, (240, 480)), (0.50, (0, 480))])
def test_webcam_zone(fy, zone):
    assert autoclip.webcam_zone({"zoom_focus_y": fy}, 480) == zone


class FakeDetector:
    """Находит «лицо» в кадрах, где в зоне есть светлый квадрат."""
    def detectMultiScale(self, img, **kw):
        return [(10, 10, 40, 40)] if (img == 255).sum() > 1000 else []


def _frame(level, noise=0, square=False):
    rnd = np.random.default_rng(1)
    f = np.full((480, 270), level, np.float32) + rnd.normal(0, noise, (480, 270))
    if square:
        f[50:90, 50:90] = 255
    return np.clip(f, 0, 255).astype(np.uint8)


def test_face_beats_sharpness_and_dark_loses():
    det = FakeDetector()
    sharp = autoclip.score_cover_frame(_frame(120, noise=40), det)
    face = autoclip.score_cover_frame(_frame(120, noise=5, square=True), det)
    dark = autoclip.score_cover_frame(_frame(5, noise=40), det)
    assert face[1] and not sharp[1]
    assert face[0] > sharp[0] > dark[0]


def test_face_only_counts_in_webcam_zone():
    det = FakeDetector()
    f = _frame(120, square=True)                  # «лицо» в верхней половине
    assert autoclip.score_cover_frame(f, det, zone=(0, 240))[1]
    assert not autoclip.score_cover_frame(f, det, zone=(240, 480))[1]


# ---------- настоящая нарезка ----------

def _video(tmp_path, dur=40):
    v = tmp_path / "запись.mp4"
    audio = f"aevalsrc='0.03*sin(2*PI*300*t)*(1+25*between(t,20,22))':s=48000:d={dur}"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=s=540x960:r=30:d={dur}", "-f", "lavfi", "-i", audio,
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                    str(v)], check=True)
    segs = [{"s": 19.0, "e": 22.0, "text": "ну вот смотри",
             "words": [{"s": 19.5, "e": 20.0, "w": "ну"}, {"s": 20.2, "e": 20.6, "w": "вот"},
                       {"s": 20.8, "e": 21.4, "w": "смотри"}]}]
    with open(tmp_path / "запись.transcript.json", "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False)
    return v


def test_cover_made_rebuilt_and_trashed(tmp_path, fake_trash):
    autoclip.CONFIG.update(max_silence_share=1.0)          # синтетика — фразы с паузами, это не тишина
    autoclip.CONFIG.update(llm="none", clips=1, hook=False)
    out = autoclip.process(str(_video(tmp_path)))
    proj = autoclip.load_project(out)
    c = proj["clips"][0]
    cv = c["cover"]
    path = os.path.join(out, cv["file"])
    assert cv["file"] == os.path.splitext(c["file"])[0] + ".jpg" and os.path.isfile(path)
    assert c["start"] <= cv["t"] <= c["end"]                       # кадр из самого клипа
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    assert p.stdout.strip() == "1080,1920"                         # размер как у клипа
    assert "обложка:" in open(os.path.join(out, "отчёт.txt"), encoding="utf-8").read()

    autoclip.rebuild_clip(out, c["id"], start=c["start"] + 2)
    assert os.path.isfile(path)
    assert any(f.endswith(".jpg") for f in os.listdir(fake_trash))  # старая — в корзину

    autoclip.set_status(out, c["id"], "rejected")
    assert not os.path.exists(path)                                # вместе с клипом
