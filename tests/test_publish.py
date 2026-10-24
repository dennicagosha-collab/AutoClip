"""Публикация: окна загрузки (Edge подменён), отметка «выложен», перетаскивание клипа."""
import os
import sys

import pytest

import autoclip


@pytest.fixture
def popen(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(autoclip, "find_edge", lambda: r"C:\Edge\msedge.exe")
    monkeypatch.setattr(autoclip, "browser_profile_dir", lambda: str(tmp_path / "браузер"))
    monkeypatch.setattr(autoclip.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd))
    return calls


def test_open_upload_in_edge_app_window(popen, tmp_path):
    assert autoclip.open_upload("tiktok") == "edge"
    cmd = popen[0]
    assert cmd[0].endswith("msedge.exe")
    assert "--app=https://www.tiktok.com/tiktokstudio/upload" in cmd
    assert f"--user-data-dir={tmp_path / 'браузер'}" in cmd and "--no-first-run" in cmd
    autoclip.open_upload("youtube", (1146, 0, 1146, 1440))
    assert "--window-position=1146,0" in popen[1] and "--window-size=1146,1440" in popen[1]


def test_no_edge_uses_default_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(autoclip, "find_edge", lambda: None)
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", opened.append)
    assert autoclip.open_upload("instagram") == "browser"
    assert opened == ["https://www.instagram.com/"]
    with pytest.raises(autoclip.AutoClipError):
        autoclip.open_upload("вконтакте")


def test_side_by_side():
    assert autoclip.side_by_side((0, 0, 3440, 1440), 3) == [
        (0, 0, 1146, 1440), (1146, 0, 1146, 1440), (2292, 0, 1146, 1440)]


def _project(tmp_path, status="good"):
    out = tmp_path / "запись_clips"
    out.mkdir()
    (out / "01_клип.mp4").write_bytes(b"x")
    proj = autoclip.new_project(str(tmp_path / "запись.mp4"), {"w": 1080, "h": 1920, "dur": 60.0,
                                "fps": 60.0}, str(out), str(tmp_path / "t.json"))
    rec = autoclip.make_clip_record({"s": 1.0, "e": 20.0, "peak": 5.0, "score": 2.0, "zooms": [],
                                     "parts": {}, "title": "мяч надо кинуть", "reason": ""},
                                    1, "01_клип.mp4")
    rec["status"] = status
    proj["clips"].append(rec)
    autoclip.save_project(proj)
    return str(out), rec["id"]


def test_mark_published(tmp_path):
    path, cid = _project(tmp_path)
    c = autoclip.mark_published(path, cid, "tiktok", True, "https://tiktok.com/@x/video/1")
    assert c["status"] == "published"
    assert c["published"]["tiktok"]["url"].endswith("/video/1") and c["published"]["tiktok"]["date"]
    c = autoclip.mark_published(path, cid, "youtube", True)
    assert set(c["published"]) == {"tiktok", "youtube"}
    autoclip.mark_published(path, cid, "tiktok", False)
    c = autoclip.mark_published(path, cid, "youtube", False)
    assert c["published"] == {} and c["status"] == "good"           # сняли всё — снова «хороший»
    with pytest.raises(autoclip.AutoClipError):
        autoclip.mark_published(path, cid, "вконтакте")


def test_rejected_cannot_be_published(tmp_path):
    path, cid = _project(tmp_path, status="rejected")
    with pytest.raises(autoclip.AutoClipError):
        autoclip.mark_published(path, cid, "tiktok")


# ---------- окно ----------

def test_publish_tab_and_drag(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    opened = []
    monkeypatch.setattr(autoclip, "open_upload", lambda p, rect=None: opened.append((p, rect)) or "edge")
    path, cid = _project(tmp_path)
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    win = A.MainWindow()
    win.settings["platform_tags"] = {"tiktok": "", "youtube": "#shorts", "instagram": "#reels"}
    page = win.clips
    page.load(path)
    page.show_tab(3)

    # перетаскивание: в «посылке» — сам файл клипа
    md = page.list.mimeData([page.list.item(0)])
    assert [u.toLocalFile() for u in md.urls()] == [os.path.join(path, "01_клип.mp4").replace("\\", "/")]

    page.publish("youtube")
    assert opened == [("youtube", None)]
    assert QApplication.clipboard().text().endswith("#shorts")
    assert "YouTube" in page.pub_state.text()

    opened.clear()
    page.publish_all()
    assert [p for p, _ in opened] == ["instagram", "youtube", "tiktok"]
    rects = {p: r for p, r in opened}
    assert rects["tiktok"][0] < rects["youtube"][0] < rects["instagram"][0]   # слева направо
    assert "#shorts" not in QApplication.clipboard().text()                   # в буфере — TikTok

    state, link, mark = page.pub_rows["tiktok"]
    assert state.text() == "не выложен" and not link.isEnabled()
    page.toggle_published("tiktok")
    state, link, mark = page.pub_rows["tiktok"]
    assert state.text().startswith("выложен") and link.isEnabled() and mark.text() == "Снять отметку"
    link.setText("https://tiktok.com/@x/video/2")
    page.save_link("tiktok")
    c = autoclip.find_clip(autoclip.load_project(path), cid)
    assert c["status"] == "published" and c["published"]["tiktok"]["url"].endswith("/2")
    page.set_filter(3)                                                        # «Выложены»
    assert page.list.count() == 1
    win.close()
