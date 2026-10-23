"""Еженедельная подборка: отбор клипов, сборка, порядок, затемнение, раздел в окне."""
import datetime
import json
import os
import subprocess
import sys

import numpy as np
import pytest

import autoclip
from qtwait import pump

COLORS = {"red": (200, 40, 40), "green": (40, 200, 40), "blue": (40, 40, 200)}


def make_clip(path, color="red", dur=2.0, size="270x480"):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"color={color}:s={size}:r=30:d={dur}", "-f", "lavfi", "-i",
                    f"sine=frequency=440:d={dur}", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)


def make_project(tmp_path, clips, name="запись"):
    """clips: [(статус, оценка, дней назад, есть ли файл, цвет)]."""
    out = tmp_path / f"{name}_clips"
    out.mkdir()
    proj = autoclip.new_project(str(tmp_path / f"{name}.mp4"), {"w": 1080, "h": 1920, "dur": 600.0,
                                "fps": 60.0}, str(out), str(tmp_path / "t.json"))
    now = datetime.datetime.now()
    for i, (status, score, ago, has_file, color) in enumerate(clips, 1):
        fn = f"{i:02d}_клип.mp4"
        if has_file:
            make_clip(out / fn, color)
        rec = autoclip.make_clip_record({"s": 10.0 * i, "e": 10.0 * i + 2, "peak": 10.0 * i + 1,
                                         "score": score, "zooms": [], "parts": {},
                                         "title": f"клип {i}", "reason": ""}, i, fn)
        rec["status"] = status
        rec["created"] = (now - datetime.timedelta(days=ago)).isoformat(timespec="seconds")
        proj["clips"].append(rec)
    autoclip.save_project(proj)
    autoclip.register_project(str(out))
    return out


def test_register_project_dedupes(tmp_path):
    out = make_project(tmp_path, [])
    autoclip.register_project(str(out))
    autoclip.register_project(str(out / "project.json"))
    assert autoclip.known_projects() == [str(out / "project.json")]


def test_weekly_candidates_rules(tmp_path):
    make_project(tmp_path, [
        ("good", 2.0, 1, True, "red"),          # да
        ("published", 3.0, 2, True, "green"),   # да
        ("new", 9.0, 1, True, "blue"),          # нет: не одобрен
        ("rejected", 9.0, 1, False, "blue"),    # нет: в корзине
        ("good", 9.0, 10, True, "blue"),        # нет: старый
        ("good", 9.0, 1, False, "blue"),        # нет: файла нет
    ])
    got = autoclip.weekly_candidates(7)
    assert [c["title"] for c in got] == ["клип 2", "клип 1"]        # лучшие первыми
    assert len(autoclip.weekly_candidates(30)) == 3                 # старый — если взять 30 дней


def _probe(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,width,height,r_frame_rate:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def _rgb(path, t, w=16, h=16):
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                        "-vf", f"crop=iw/4:ih/4,scale={w}:{h},format=rgb24", "-f", "rawvideo", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.uint8).reshape(-1, 3).mean(axis=0)


def _closest(rgb):
    return min(COLORS, key=lambda k: np.abs(np.array(COLORS[k]) - rgb).sum())


@pytest.mark.parametrize("fmt,size", [("vertical", (1080, 1920)), ("horizontal", (1920, 1080))])
def test_build_compilation(tmp_path, fmt, size):
    clips = []
    for color in ("red", "green", "blue"):
        p = tmp_path / f"{color}.mp4"
        make_clip(p, color)
        clips.append(str(p))
    out = autoclip.build_compilation(clips, fmt)
    info = _probe(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == size and v["r_frame_rate"] == "60/1"
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert abs(float(info["format"]["duration"]) - 6.0) < 0.2
    # порядок — как задан, затемнение на стыке
    assert [_closest(_rgb(out, t)) for t in (1.0, 3.0, 5.0)] == ["red", "green", "blue"]
    assert _rgb(out, 2.0).max() < 40                   # стык — почти чёрный
    assert _rgb(out, 1.0).max() > 150
    assert os.path.isfile(os.path.splitext(out)[0] + ".json")
    # вторая подборка того же дня не затирает первую
    out2 = autoclip.build_compilation(clips[:1], fmt)
    assert out2 != out and os.path.isfile(out)


def test_reorder_changes_order(tmp_path):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    make_clip(a, "red")
    make_clip(b, "blue")
    out = autoclip.build_compilation([str(b), str(a)], "vertical")
    assert [_closest(_rgb(out, t)) for t in (1.0, 3.0)] == ["blue", "red"]


def test_empty_list_is_clear_error():
    with pytest.raises(autoclip.AutoClipError):
        autoclip.build_compilation([], "vertical")


# ---------- окно ----------

def test_weekly_page(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", lambda m: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    make_project(tmp_path, [("good", 2.0, 1, True, "red"), ("good", 3.0, 1, True, "green"),
                            ("published", 1.0, 1, True, "blue"), ("new", 5.0, 1, True, "red")])
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    win = A.MainWindow()
    win.settings["weekly_dir"] = str(tmp_path / "мои подборки")
    win.show()
    win.go("weekly")
    page = win.weekly
    assert page.list.count() == 3 and "3 из 3" in page.summary.text()
    page.list.item(2).setCheckState(Qt.Unchecked)                    # убрать синий
    page.list.setCurrentRow(1)
    page.move(-1)                                                    # красный — первым
    order = [os.path.basename(p) for p, _ in page.chosen()]
    assert order == ["01_клип.mp4", "02_клип.mp4"]                  # красный, потом зелёный
    assert "2 из 3" in page.summary.text()
    page.set_format("horizontal")
    page.build()
    for _ in range(1200):
        if not page.busy:
            break
        pump(50)
    assert page.last and os.path.isfile(page.last), page.state.text()
    assert page.last.startswith(str(tmp_path / "мои подборки"))
    info = _probe(page.last)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert v["width"] == 1920
    assert [_closest(_rgb(page.last, t)) for t in (1.0, 3.0)] == ["red", "green"]
    win.close()
