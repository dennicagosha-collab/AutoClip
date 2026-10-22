"""Ник в углу: место, сейф-зона, не поверх субтитров, прозрачность, своя галочка у клипа."""
import subprocess

import numpy as np
import pytest

import autoclip

W, H = 1080, 1920


def render(tmp_path, cfg_over, words=None):
    """Кадр с субтитрами и ником на чёрном фоне → (картинка, есть ли ник)."""
    cfg = dict(autoclip.CONFIG, **cfg_over)
    vf = []
    if words:
        autoclip.build_ass(words, W, H, str(tmp_path / "s.ass"), cfg)
        vf.append("ass=s.ass")
    if cfg.get("nick"):
        autoclip.build_nick_ass(W, H, str(tmp_path / "n.ass"), cfg, 2.0)
        vf.append("ass=n.ass")
    vf.append("format=gray")
    p = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=black:s={W}x{H}:d=1",
                        "-vf", ",".join(vf), "-ss", "0.6", "-frames:v", "1", "-f", "rawvideo", "-"],
                       capture_output=True, check=True, cwd=tmp_path)
    return np.frombuffer(p.stdout, np.uint8).reshape(H, W)


def box(img, rows=slice(None), cols=slice(None)):
    ys, xs = np.nonzero(img[rows, cols] > 30)
    if not len(xs):
        return None
    y0 = rows.start or 0
    x0 = cols.start or 0
    return x0 + xs.min(), y0 + ys.min(), x0 + xs.max(), y0 + ys.max()


def test_nick_top_left_inside_safe_zone(tmp_path):
    img = render(tmp_path, {"nick": True, "safe_zone": True})
    x0, y0, x1, y1 = box(img)
    z = autoclip.SAFE_ZONE
    assert x0 >= z["left"] * W - 2 and y0 >= z["top"] * H - 2       # не под кнопками
    assert x1 < W / 2 and y1 < H * 0.25                              # верхний левый угол
    assert x1 - x0 < W * 0.45                                        # небольшой


@pytest.mark.parametrize("corner", list(autoclip.NICK_CORNERS))
def test_every_corner(tmp_path, corner):
    x0, y0, x1, y1 = box(render(tmp_path, {"nick": True, "nick_corner": corner}))
    code = autoclip.NICK_CORNERS[corner]
    assert (x1 < W / 2) == (code[1] == "l")
    assert (y1 < H / 2) == (code[0] == "t")


def test_nick_off_draws_nothing(tmp_path):
    assert box(render(tmp_path, {"nick": False})) is None


def test_opacity(tmp_path):
    bright = render(tmp_path, {"nick": True, "nick_opacity": 100}).max()
    dim = render(tmp_path, {"nick": True, "nick_opacity": 40}).max()
    assert bright > 200 and dim < bright * 0.6


def test_subtitles_move_away_from_nick(tmp_path):
    """Субтитры «Сверху» попали бы на ник — их строка отодвигается ниже ника."""
    words = [{"s": 0.0, "e": 2.0, "w": "НУ"}, {"s": 0.1, "e": 2.0, "w": "ВОТ"}]
    cfg = {"nick": True, "sub_y": autoclip.SUB_POSITIONS["Сверху"], "safe_zone": True}
    nick_only = box(render(tmp_path, dict(cfg)))
    both = render(tmp_path, dict(cfg), words)
    nick_bottom = nick_only[3]
    subs = box(both, rows=slice(nick_bottom + 1, H))
    assert subs is not None
    assert box(both, rows=slice(nick_only[1], nick_bottom + 1),
               cols=slice(nick_only[2] + 1, W)) is None      # рядом с ником субтитров нет
    # без ника строка стояла бы выше
    free = box(render(tmp_path, dict(cfg, nick=False), words))
    assert subs[1] > free[1]


def test_nick_is_per_clip_option():
    assert "nick" in autoclip.OVERRIDE_KEYS
    assert {"nick", "nick_text", "nick_corner", "nick_size", "nick_opacity"} <= set(autoclip.RENDER_KEYS)
