"""Звук на мат не должен заезжать на соседние слова без мата."""
import subprocess

import numpy as np
import pytest

import autoclip


def _rms(path, a, b):
    """Громкость звука готового клипа на отрезке [a, b] секунд."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}",
                        "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                       capture_output=True, check=True)
    x = np.frombuffer(p.stdout, dtype=np.int16).astype(float) / 32768
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


@pytest.fixture
def silent_video(tmp_path):
    v = tmp_path / "тихо.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=s=270x480:r=30:d=6", "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=stereo", "-t", "6", "-c:v", "libx264",
                    "-preset", "ultrafast", "-c:a", "aac", str(v)], check=True)
    return v


@pytest.fixture
def long_sound(tmp_path):
    # свой звук пользователя длиннее слова — как «бумага.mp3»
    s = tmp_path / "длинный.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=1000:sample_rate=48000:duration=1.5", "-ac", "2", str(s)],
                   check=True)
    return s


def test_bleep_sound_stops_before_next_clean_word(tmp_path, silent_video, long_sound,
                                                  fake_trash):
    segs = [{"s": 1.0, "e": 2.4, "text": "блять ну вот", "words": [
        {"s": 1.0, "e": 1.4, "w": "блять"},
        {"s": 1.5, "e": 1.9, "w": "ну"},
        {"s": 2.0, "e": 2.4, "w": "вот"}]}]
    cfg = dict(autoclip.CONFIG, subs=False, zoom=False, bleep=True,
               bleep_sound=str(long_sound), preset="TikTok 1080p60")
    out = tmp_path / "клип.mp4"
    bl = autoclip.render_clip(str(silent_video), {"s": 0.0, "e": 5.0, "zooms": []}, segs,
                              {"w": 270, "h": 480, "fps": 30.0, "dur": 6.0}, str(out),
                              str(tmp_path), cfg)
    assert bl == 1
    assert _rms(out, 1.05, 1.35) > 0.05           # на мате звук есть
    assert _rms(out, 1.52, 1.9) < 0.005           # на «ну» его уже нет
    assert _rms(out, 2.0, 2.4) < 0.005


def test_bleep_spans_respect_neighbours():
    words = [{"s": 0.5, "e": 0.98, "w": "ну"},
             {"s": 1.0, "e": 1.4, "w": "сука"},
             {"s": 1.42, "e": 1.8, "w": "вот"},
             {"s": 3.0, "e": 3.3, "w": "блять"}]
    spans = autoclip.bleep_spans(words, total=5.0, pad=0.06)
    assert len(spans) == 2
    (a1, b1, until1), (a2, b2, until2) = spans
    assert a1 >= 0.98 and b1 <= 1.42 and until1 <= 1.42   # не трогает «ну» и «вот»
    assert a2 == pytest.approx(2.94) and b2 == pytest.approx(3.36)
    assert until2 == 5.0                                  # дальше слов нет — до конца клипа
