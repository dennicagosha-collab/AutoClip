"""Лог в файл и «Отчёт об ошибке»."""
import json
import os
import zipfile

import autoclip
from qtwait import pump
import diag


def test_file_log_keeps_last_ten(tmp_path, fake_trash):
    d = tmp_path / "logs"
    d.mkdir()
    for i in range(12):
        f = d / f"2026-01-{i + 1:02d}_10-00-00.log"
        f.write_text("старый", encoding="utf-8")
        os.utime(f, (1000 + i, 1000 + i))
    log = diag.FileLog(str(d))
    log.write("строка один\nстрока два")
    log.close()
    files = sorted(os.listdir(d))
    assert len(files) == 10 and os.path.basename(log.path) in files
    assert "2026-01-01_10-00-00.log" not in files                    # самые старые — в корзину
    assert len(os.listdir(fake_trash)) == 3
    text = open(log.path, encoding="utf-8").read()
    assert "AutoClip" in text and "строка один" in text and "строка два" in text


def test_clean_hides_secrets():
    data = {"telegram_token": "123456789:AAH5abcdefghijklmnopqrstuvwxyz012345",
            "chat_id": 987654, "nick_text": "Final_KFC_Boss", "hashtags": "#стрим",
            "nested": {"api_key": "x"}, "note": "ключ sk-ant-abcdefghijklmnopqrstuvwxyz",
            "empty_token": "", "watch": True}
    c = diag.clean(data)
    assert c["telegram_token"] == "<скрыто>" and c["chat_id"] == "<скрыто>"
    assert c["nested"]["api_key"] == "<скрыто>" and "sk-ant" not in c["note"]
    assert c["nick_text"] == "Final_KFC_Boss" and c["hashtags"] == "#стрим" and c["watch"] is True
    assert c["empty_token"] == ""


def test_report_zip(tmp_path, monkeypatch):
    user = tmp_path / "AutoClip"
    user.mkdir()
    monkeypatch.setattr(autoclip, "user_dir", lambda: str(user))
    (user / "настройки.json").write_text(json.dumps(
        {"telegram_token": "123456789:AAH5abcdefghijklmnopqrstuvwxyz012345", "clips": 10}),
        encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "2026-10-23_10-00-00.log").write_text("10:00:00  ✅ Готово", encoding="utf-8")
    # нарезка: project.json, отчёт, клип и запись рядом
    cut = tmp_path / "запись_clips"
    cut.mkdir()
    (cut / "project.json").write_text(json.dumps({"clips": [], "source": "D:/запись.mp4"}),
                                      encoding="utf-8")
    (cut / "отчёт.txt").write_text("отчёт", encoding="utf-8")
    (cut / "01_клип.mp4").write_bytes(b"video")
    autoclip.register_project(str(cut / "project.json"))
    path = diag.make_report(str(tmp_path / "стол"), str(logs))
    assert os.path.isfile(path) and path.endswith(".zip")
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert "система.txt" in names and "логи/2026-10-23_10-00-00.log" in names
        assert "последняя нарезка/project.json" in names and "последняя нарезка/отчёт.txt" in names
        assert not any(n.endswith((".mp4", ".mkv", ".wav")) for n in names)   # без видео
        s = json.loads(z.read("настройки/настройки.json"))
        assert s["telegram_token"] == "<скрыто>" and s["clips"] == 10
        info = z.read("система.txt").decode("utf-8")
        assert "AutoClip" in info and "ffmpeg" in info and "faster-whisper" in info
    assert diag.make_report(str(tmp_path / "стол"), str(logs)) != path     # второй — рядом


def test_report_button(tmp_path, monkeypatch):
    import sys
    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    made = []
    zip_path = str(tmp_path / "стол" / "отчёт.zip")
    monkeypatch.setattr(diag, "make_report", lambda: made.append(1) or zip_path)
    shown = []
    monkeypatch.setattr(A, "ask_choice", lambda *a: "show")
    monkeypatch.setattr(A, "show_in_folder", lambda p: shown.append(p))
    w = A.MainWindow()
    try:
        w.make_report()
        for _ in range(100):
            if shown:
                break
            pump(50)
        assert made and shown and shown[0].endswith("отчёт.zip")
        assert "Готово" in w.settings_page.report_state.text() and w.settings_page.report_btn.isEnabled()
    finally:
        w.close()
