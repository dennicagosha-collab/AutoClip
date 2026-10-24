"""Стиль субтитров: цвета, режим, обводка, положение, свои шрифты, сохранённые стили, предпросмотр."""
import os
import re
import subprocess

import pytest

import autoclip
from fontfile import renamed_font

WIN_FONT = r"C:\Windows\Fonts\comic.ttf"


def test_ass_color():
    assert autoclip.ass_color("#FFE600") == "&H0000E6FF"
    assert autoclip.ass_color("#102030", 0x80) == "&H80302010"
    assert autoclip.ass_color("мусор") == "&H00FFFFFF"


def _words(text, start=0.0):
    return [{"s": start + i * 0.4, "e": start + i * 0.4 + 0.3, "w": w} for i, w in enumerate(text.split())]


def test_ass_uses_style(tmp_path):
    cfg = dict(autoclip.CONFIG, sub_color="#00FF00", sub_hl_color="#FF0000", sub_outline_color="#0000FF",
               sub_outline=14, sub_font="Verdana")
    p = tmp_path / "a.ass"
    autoclip.build_ass(_words("раз два три"), 1080, 1920, str(p), cfg)
    t = p.read_text(encoding="utf-8-sig")
    assert "Style: Main,Verdana,82,&H0000FF00,&H0000FF00,&H00FF0000," in t
    assert ",1,14,2,5," in t                                         # толщина обводки
    assert "{\\c&H0000FF&}" in t and "{\\c&H00FF00&}" in t            # подсветка и обратно
    cfg["sub_mode"] = "single"
    autoclip.build_ass(_words("раз два три"), 1080, 1920, str(p), cfg)
    lines = [ln for ln in p.read_text(encoding="utf-8-sig").splitlines() if ln.startswith("Dialogue")]
    assert len(lines) == 3 and all(len(re.sub(r"\{[^}]*\}", "", ln.split(",,", 1)[1]).split()) == 1
                                   for ln in lines)                 # по одному слову


def test_default_position_unchanged_and_x_clamped():
    cfg = dict(autoclip.CONFIG, safe_zone=True)
    left, top, right, bottom = autoclip.frame_area(1080, 1920, cfg)
    lay = autoclip.subs_layout(1080, 1920, cfg)
    assert lay["x"] == int((left + right) / 2)                       # как было до стилей
    lay = autoclip.subs_layout(1080, 1920, dict(cfg, sub_x=0.0))
    assert lay["x"] >= left + 2 * lay["fs"] - 1                      # не вытащить за сейф-зону
    lay = autoclip.subs_layout(1080, 1920, dict(cfg, sub_x=0.3))
    assert lay["x"] == int(0.3 * 1080) and lay["room"] == pytest.approx(2 * (0.3 * 1080 - left))


def test_saved_styles(tmp_path):
    assert [s["name"] for s in autoclip.load_styles()] == ["Обычный"]
    autoclip.save_style("Жёлтый", dict(autoclip.BUILTIN_STYLE, sub_color="#FFFF00", sub_size=90))
    st = autoclip.get_style("Жёлтый")
    assert st["sub_color"] == "#FFFF00" and st["sub_size"] == 90
    autoclip.save_style("Жёлтый", dict(st, sub_size=70))             # тот же — заменяется
    assert [s["name"] for s in autoclip.load_styles()] == ["Обычный", "Жёлтый"]
    assert autoclip.get_style("Жёлтый")["sub_size"] == 70
    with pytest.raises(autoclip.AutoClipError):
        autoclip.save_style("Обычный", st)
    assert autoclip.get_style("нет такого")["name"] == "Обычный"
    autoclip.delete_style("Жёлтый")
    assert [s["name"] for s in autoclip.load_styles()] == ["Обычный"]


@pytest.mark.skipif(not os.path.isfile(WIN_FONT), reason="нужен шрифт Windows")
def test_add_font(tmp_path, fake_trash):
    src = renamed_font(WIN_FONT, str(tmp_path / "мой.ttf"), "AutoClip Test Face")
    assert autoclip.font_family(src) == "AutoClip Test Face"
    assert autoclip.add_font(src) == "AutoClip Test Face"
    assert os.path.isfile(os.path.join(autoclip.FONTS_DIR, "мой.ttf"))
    assert autoclip.user_fonts() == {"AutoClip Test Face": os.path.join(autoclip.FONTS_DIR, "мой.ttf")}
    bad = tmp_path / "не шрифт.ttf"
    bad.write_bytes(b"0" * 100)
    with pytest.raises(autoclip.AutoClipError):
        autoclip.add_font(str(bad))


def _black_video(tmp_path, dur=6):
    v = tmp_path / "чёрное.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=black:s=1080x1920:r=30:d={dur}",
                    "-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=48000:duration={dur}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(v)],
                   check=True)
    return str(v)


def _render(tmp_path, cfg, words, monkeypatch=None):
    video = _black_video(tmp_path)
    vinfo = autoclip.probe(video)
    segs = [{"s": words[0]["s"], "e": words[-1]["e"], "text": "", "words": words}]
    out = str(tmp_path / "клип.mp4")
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    cfg = dict(cfg, zoom=False, bleep=False, nick=False, subs=True)
    assert autoclip.render_clip(video, {"s": 0.0, "e": 5.0, "zooms": [], "hook": None}, segs, vinfo,
                                out, str(work), cfg) is not None
    return out


@pytest.mark.skipif(not os.path.isfile(WIN_FONT), reason="нужен шрифт Windows")
def test_custom_font_goes_into_render(tmp_path, fake_trash, monkeypatch):
    autoclip.add_font(renamed_font(WIN_FONT, str(tmp_path / "мой.ttf"), "AutoClip Test Face"))
    logs = []
    real = autoclip.run

    def run(cmd, *a, **k):
        if "-filter_complex" in cmd:                     # сам рендер клипа — с подробным логом
            cmd = [("debug" if c == "error" and i and cmd[i - 1] == "-v" else c) for i, c in enumerate(cmd)]
            p = real(cmd, *a, **k)
            logs.append(p.stderr)
            return p
        return real(cmd, *a, **k)
    monkeypatch.setattr(autoclip, "run", run)
    _render(tmp_path, dict(autoclip.CONFIG, sub_font="AutoClip Test Face"), _words("вот это поворот", 1.0))
    assert any("fontselect: (AutoClip Test Face" in s and "-> AutoClipTestFace" in s for s in logs)


def _bright_box(rgb, w, h, mask=None):
    """Где на кадре светлый текст (белый и жёлтый), без обводки."""
    xs, ys = [], []
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            i = (y * w + x) * 3
            if rgb[i] > 200 and rgb[i + 1] > 180 and (mask is None or mask[y * w + x] > 200):
                xs.append(x)
                ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def test_preview_matches_clip(tmp_path):
    from PySide6.QtGui import QImage
    cfg = dict(autoclip.CONFIG, safe_zone=True, sub_y=0.42, sub_x=0.40, sub_size=90,
               sub_color="#FFFFFF", sub_hl_color="#FFE600")
    layer = autoclip.render_sub_layer(cfg, 1080, 1920, str(tmp_path / "слой.png"))
    im = QImage(layer).convertToFormat(QImage.Format_RGBA8888)
    raw = bytes(im.constBits())
    rgb = bytearray(1080 * 1920 * 3)
    alpha = bytearray(1080 * 1920)
    for i in range(1080 * 1920):
        rgb[3 * i:3 * i + 3] = raw[4 * i:4 * i + 3]
        alpha[i] = raw[4 * i + 3]
    a = _bright_box(rgb, 1080, 1920, alpha)
    clip = _render(tmp_path, cfg, _words(" ".join(autoclip.PREVIEW_WORDS), 1.0))
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.55", "-i", clip, "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True)
    b = _bright_box(p.stdout, 1080, 1920)
    assert all(abs(x - y) <= 6 for x, y in zip(a, b)), (a, b)        # совпадают с точностью до пикселей


# ---------- окно ----------

@pytest.fixture
def win(tmp_path, monkeypatch):
    import sys
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    w = A.MainWindow()
    w.show()
    yield A, w
    w.close()


def wait_for(cond, ms=20000):
    from qtwait import pump
    for _ in range(ms // 50):
        if cond():
            return True
        pump(50)
    return cond()


def test_live_preview_drag_and_styles(win, monkeypatch):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    A, w = win
    st = w.settings_page
    st.render_live()
    assert wait_for(lambda: st.live.layer is not None)
    x0, y0, lay = st.live.center()
    k = st.live._k()

    def mouse(kind, x, y):
        ev = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), Qt.LeftButton,
                         Qt.LeftButton if kind != QEvent.MouseButtonRelease else Qt.NoButton, Qt.NoModifier)
        {QEvent.MouseButtonPress: st.live.mousePressEvent, QEvent.MouseMove: st.live.mouseMoveEvent,
         QEvent.MouseButtonRelease: st.live.mouseReleaseEvent}[kind](ev)
    mouse(QEvent.MouseButtonPress, x0 * k, y0 * k)
    mouse(QEvent.MouseMove, x0 * k - 30, y0 * k - 400)                 # далеко вверх — за сейф-зону
    mouse(QEvent.MouseButtonRelease, x0 * k - 30, y0 * k - 400)
    s = A.load_settings()
    assert s["sub_pos"] == A.CUSTOM_POS and st.sub_pos.currentText() == A.CUSTOM_POS
    cfg = A.sub_settings(s)
    top = autoclip.SAFE_ZONE["top"] * 1920 + 0.6 * lay["fs"]
    assert cfg["sub_y"] * 1920 >= top - 1                              # упёрлись в сейф-зону
    assert cfg["sub_x"] < x0 / 1080
    w.cut.apply_config()
    assert autoclip.CONFIG["sub_y"] == cfg["sub_y"] and autoclip.CONFIG["sub_x"] == cfg["sub_x"]
    st.sub_pos.setCurrentText("Снизу")                                 # кнопка «Низ»
    w.cut.apply_config()
    assert autoclip.CONFIG["sub_y"] == autoclip.SUB_POSITIONS["Снизу"] and autoclip.CONFIG["sub_x"] is None

    # стиль: поменять цвет, сохранить как, выбрать «Обычный» и обратно
    st.c_text.set_color("#00FF00")
    st._set_style_key("sub_color", "#00FF00")
    st.size_box.setValue(100)
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Зелёный", True))
    st.save_style_as()
    assert [x["name"] for x in autoclip.load_styles()] == ["Обычный", "Зелёный"]
    assert st.style_box.currentText() == "Зелёный"
    st.apply_style("Обычный")
    assert A.load_settings()["sub_color"] == "#FFFFFF" and st.size_box.value() == 82
    st.apply_style("Зелёный")
    w.cut.apply_config()
    assert autoclip.CONFIG["sub_color"] == "#00FF00" and autoclip.CONFIG["sub_size"] == 100
    assert autoclip.CONFIG["sub_style"] == "Зелёный"


def test_clip_style_override(win, tmp_path, fake_trash):
    import json
    A, w = win
    video = _black_video(tmp_path, dur=40)
    segs = [{"s": t, "e": t + 2.4, "text": "", "words": [
        {"s": t + i * 0.6, "e": t + i * 0.6 + 0.5, "w": x} for i, x in enumerate(["ну", "вот", "смотри"])]}
        for t in range(0, 40, 4)]
    with open(tmp_path / "чёрное.transcript.json", "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False)
    autoclip.CONFIG.update(max_silence_share=1.0)          # синтетика — фразы с паузами, это не тишина
    autoclip.CONFIG.update(llm="none", clips=1, hook=False, clips_mode="count", build_mode="full")
    autoclip.CONFIG["min_len"] = 10.0
    cut = autoclip.process(str(video))
    assert cut
    autoclip.save_style("Крупный", dict(autoclip.BUILTIN_STYLE, sub_size=120, sub_color="#FF00FF"))
    page = w.clips
    page.load(cut)
    assert page.e_style.currentData() == ""                           # как у нарезки
    page.e_style.setCurrentIndex(page.e_style.findData("Крупный"))
    assert "style" in page.pending()
    page.rebuild()
    assert wait_for(lambda: not page.busy, 60000)
    c = autoclip.load_project(cut)["clips"][0]
    assert c["overrides"]["sub_style"] == "Крупный" and c["overrides"]["sub_size"] == 120
    assert autoclip.clip_config(autoclip.load_project(cut), c)["sub_color"] == "#FF00FF"
    assert page.e_style.currentData() == "Крупный" and not page.pending()
    page.e_style.setCurrentIndex(0)                                    # обратно «как у нарезки»
    page.rebuild()
    assert wait_for(lambda: not page.busy, 60000)
    c = autoclip.load_project(cut)["clips"][0]
    assert "sub_style" not in c["overrides"] and "sub_size" not in c["overrides"]
