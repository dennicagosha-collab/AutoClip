"""Положение субтитров и сейф-зона: проверка по пикселям готового кадра."""
import subprocess

import numpy as np
import pytest

import autoclip

W, H = 1080, 1920


def text_box(tmp_path, text, **cfg_over):
    """Рамка, в которой оказались пиксели субтитра (x0, y0, x1, y1)."""
    cfg = dict(autoclip.CONFIG, **cfg_over)
    ass = tmp_path / "t.ass"
    words = [{"s": 0.0 + i * 0.1, "e": 2.0, "w": w} for i, w in enumerate(text.split())]
    autoclip.build_ass(words, W, H, str(ass), cfg)
    p = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=black:s={W}x{H}:d=1",
                        "-vf", "ass=t.ass,format=gray", "-ss", "0.6", "-frames:v", "1",
                        "-f", "rawvideo", "-"], capture_output=True, check=True, cwd=tmp_path)
    img = np.frombuffer(p.stdout, np.uint8).reshape(H, W)
    ys, xs = np.nonzero(img > 30)
    assert len(xs), "субтитр не нарисовался"
    return xs.min(), ys.min(), xs.max(), ys.max()


def safe_box():
    z = autoclip.SAFE_ZONE
    return z["left"] * W, z["top"] * H, W - z["right"] * W, H - z["bottom"] * H


@pytest.mark.parametrize("pos", list(autoclip.SUB_POSITIONS))
@pytest.mark.parametrize("text", ["НУ ВОТ СМОТРИ", "ПЕРЕЛИСТЫВАНИЕ",
                                  "ДОСТОПРИМЕЧАТЕЛЬНОСТИПЕРЕЛИСТЫВАНИЕ"])
def test_subs_stay_inside_safe_zone(tmp_path, pos, text):
    x0, y0, x1, y1 = text_box(tmp_path, text, sub_y=autoclip.SUB_POSITIONS[pos], safe_zone=True)
    l, t, r, b = safe_box()
    assert l <= x0 and x1 <= r and t <= y0 and y1 <= b


def test_positions_go_top_to_bottom(tmp_path):
    ys = [text_box(tmp_path, "НУ ВОТ", sub_y=y, safe_zone=False)[1]
          for y in autoclip.SUB_POSITIONS.values()]
    assert ys == sorted(ys) and len(set(ys)) == len(ys)


def test_without_safe_zone_bottom_is_lower(tmp_path):
    y = autoclip.SUB_POSITIONS["Снизу"]
    free = text_box(tmp_path, "НУ ВОТ", sub_y=y, safe_zone=False)
    safe = text_box(tmp_path, "НУ ВОТ", sub_y=y, safe_zone=True)
    assert free[3] > safe[3] and free[3] > H * 0.8
    assert free[3] < H                                   # но в кадре


def test_default_is_a_bit_lower_than_middle():
    assert autoclip.CONFIG["sub_y"] > autoclip.SUB_POSITIONS["Середина"]
    assert autoclip.sub_position_name(autoclip.CONFIG["sub_y"]) == "Ниже середины"


def test_safe_zone_is_per_clip_override():
    assert "safe_zone" in autoclip.OVERRIDE_KEYS and "sub_y" in autoclip.OVERRIDE_KEYS
