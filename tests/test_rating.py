"""Патч 5.3: «Выложу / Норм / Не то»; 5.4: «выложен» ставится всегда."""
import os

import autoclip
import forecast


def _proj(tmp_path, clips):
    out = tmp_path / "з_clips"
    out.mkdir()
    proj = autoclip.new_project(str(tmp_path / "з.mp4"), {"w": 2, "h": 2, "dur": 600.0, "fps": 30},
                                str(out), str(tmp_path / "t.json"))
    for i, extra in enumerate(clips, 1):
        c = autoclip.make_clip_record({"s": i * 30.0, "e": i * 30.0 + 20, "peak": i * 30.0 + 10, "score": 2,
                                       "zooms": [], "title": f"к{i}", "reason": ""}, i, f"{i:02d}.mp4")
        c.update(extra)
        (out / c["file"]).write_bytes(b"x")
        proj["clips"].append(c)
    autoclip.save_project(proj)
    return str(out)


def test_old_statuses_converted_and_published_repaired(tmp_path):
    pub = {"tiktok": {"date": "2026-10-25T01:27:45"}, "youtube": {"date": "2026-10-25T01:34:52"}}
    cut = _proj(tmp_path, [{"status": "good"}, {"status": "rejected"}, {"status": "good", "published": pub},
                           {"status": "new"}])
    cs = autoclip.load_project(cut)["clips"]
    assert [(c["status"], c.get("rating")) for c in cs] == [
        ("post", "post"), ("rejected", "bad"), ("published", "post"), ("new", None)]


def test_three_ratings(tmp_path, fake_trash):
    cut = _proj(tmp_path, [{}, {}, {}])
    assert autoclip.set_rating(cut, "c01", "post")["status"] == "post"
    c = autoclip.set_rating(cut, "c02", "ok")
    assert c["status"] == "ok" and os.path.isfile(os.path.join(cut, c["file"]))     # «Норм» — файл остаётся
    c = autoclip.set_rating(cut, "c03", "bad")
    assert c["status"] == "rejected" and not os.path.isfile(os.path.join(cut, c["file"]))
    assert autoclip.set_rating(cut, "c01", None)["status"] == "new"


def test_publish_from_any_status_and_rating_after(tmp_path):
    cut = _proj(tmp_path, [{}, {}])
    autoclip.set_rating(cut, "c01", "ok")
    assert autoclip.mark_published(cut, "c01", "tiktok")["status"] == "published"    # из «Норм» тоже
    c = autoclip.set_rating(cut, "c01", "post")                     # оценка после публикации — статус тот же
    assert c["status"] == "published" and c["rating"] == "post"
    assert autoclip.mark_published(cut, "c01", "tiktok", on=False)["status"] == "post"
    assert autoclip.mark_published(cut, "c02", "youtube")["status"] == "published"


def test_ok_is_half_signal():
    import random
    rnd = random.Random(5)
    samples = []
    for i in range(60):
        f = {k: rnd.uniform(0, 1) for k, _ in forecast.FEATURES}
        f["laugh"] = [0.0, 1.5, 3.0][i % 3]
        samples.append({"features": f, "like": [0.0, 0.5, 1.0][i % 3], "views": {}, "retention": {}})
    info = forecast.train(save=False, samples=samples)
    assert info["like"] is not None and info["n_like"] == 60
    mid = dict(samples[0]["features"], laugh=1.5)
    p = forecast.predict(mid, 2.0, info)
    lo = forecast.predict(dict(mid, laugh=0.0), 2.0, info)
    hi = forecast.predict(dict(mid, laugh=3.0), 2.0, info)
    assert lo["value"] < p["value"] < hi["value"]                   # «Норм» — между


def test_move_waits_while_file_is_briefly_busy(tmp_path):
    """Оценка переносит клип в папку оценки; проигрыватель отпускает файл не сразу — перенос
    повторяется, а не падает «файл занят другим процессом»."""
    import threading
    src, dst = tmp_path / "клип.mp4", tmp_path / "Выложу" / "клип.mp4"
    src.write_bytes(b"x" * 1000)
    dst.parent.mkdir()
    f = open(src, "rb")                                       # «плеер» держит файл открытым
    threading.Timer(0.5, f.close).start()                     # и отпускает через полсекунды
    autoclip._replace_retry(str(src), str(dst))
    assert dst.is_file() and not src.exists()
    g = open(dst, "rb")                                       # держит насовсем — честная ошибка
    try:
        try:
            autoclip._replace_retry(str(dst), str(src), seconds=0.3)
            moved = True
        except PermissionError:
            moved = False
        assert not moved
    finally:
        g.close()


def test_rate_frees_player_and_explains_busy_file(tmp_path, monkeypatch):
    """«Выложу»: перед переносом плеер и превью отпускают файл; если файл всё равно занят —
    понятное сообщение, программа не падает."""
    import sys
    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    import app as A
    A.dark_palette(QApplication.instance() or QApplication([]))
    cut = _proj(tmp_path, [{}])
    win = A.MainWindow()
    page = win.clips
    page.load(cut)
    page.list.setCurrentRow(0)
    freed = []
    monkeypatch.setattr(page.player, "release_file", lambda ms=300: freed.append("плеер"))
    monkeypatch.setattr(page.cards, "stop_preview", lambda: freed.append("превью"))
    page.rate("post")
    assert freed[:2] == ["превью", "плеер"]                  # до переноса файла
    assert autoclip.load_project(cut)["clips"][0]["status"] == "post"
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))

    def busy(*a, **k):
        raise PermissionError(32, "файл занят")
    monkeypatch.setattr(autoclip, "set_rating", busy)
    page.rate("ok")
    assert warned and "открыт в другой программе" in warned[0]
    win.close()


def _layout2_cut(tmp_path):
    """Нарезка нового вида: клип лежит в «Новые», файл — настоящее видео (его откроет плеер)."""
    import subprocess
    root = tmp_path / "Клипы 27.10.2026"
    (root / ".autoclip").mkdir(parents=True)
    (root / "Новые").mkdir()
    vid = root / "Новые" / "01_клип.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=180x320:r=30:d=3",
                    "-f", "lavfi", "-i", "sine=f=300:d=3", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(vid)], check=True)
    proj = autoclip.new_project(str(tmp_path / "запись.mp4"), {"w": 180, "h": 320, "dur": 600.0, "fps": 30},
                                str(root), str(tmp_path / "t.json"), layout=2)
    c = autoclip.make_clip_record({"s": 30.0, "e": 33.0, "peak": 31.0, "score": 5, "zooms": [], "title": "клип",
                                   "reason": ""}, 1, "Новые/01_клип.mp4")
    proj["clips"].append(c)
    autoclip.save_project(proj)
    return proj["_path"]


def test_any_move_releases_file_open_in_player(tmp_path, monkeypatch):
    """«Выложу», потом «Выложил на TikTok» — клип каждый раз переезжает в папку, хотя открыт в плеере
    (раньше: «файл занят другим процессом»)."""
    import sys
    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from qtwait import pump
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    import app as A
    A.dark_palette(QApplication.instance() or QApplication([]))
    pp = _layout2_cut(tmp_path)
    win = A.MainWindow()
    win.show()
    page = win.clips
    page.load(pp)
    page.list.setCurrentRow(0)
    pump(800)                                                  # плеер открыл файл
    root = autoclip.cut_root(autoclip.load_project(pp))
    autoclip.set_rating(pp, "c01", "post")                     # как из меню правой кнопкой — мимо rate()
    c = autoclip.load_project(pp)["clips"][0]
    assert c["file"].startswith("Выложу/") and os.path.isfile(os.path.join(root, c["file"]))
    page.reload(c["id"])
    page.list.setCurrentRow(0)
    pump(800)
    page.toggle_published("tiktok")                            # «Выложил на TikTok»
    c = autoclip.load_project(pp)["clips"][0]
    assert c["status"] == "published" and c["file"].startswith("Выложенные/")
    assert os.path.isfile(os.path.join(root, c["file"]))
    win.close()
