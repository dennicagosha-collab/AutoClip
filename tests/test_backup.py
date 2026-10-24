"""Патч 3Б.9: где лежат данные пользователя, резервная копия и восстановление."""
import datetime
import json
import os
import subprocess
import sys
import zipfile

import pytest

import autoclip
import backup

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_all_user_data_in_appdata():
    """Всё пользовательское — в %APPDATA%\\AutoClip, ничего — в папке программы (её меняет обновление)."""
    code = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import autoclip, forecast, telegram_bot, diag
print(json.dumps({
    "user": autoclip.user_dir(), "app": autoclip.SCRIPT_DIR,
    "paths": [autoclip.SETTINGS_PATH, autoclip.PRESETS_PATH, autoclip.SOUNDS_DIR, autoclip.FONTS_DIR,
              autoclip.STYLES_PATH, autoclip.PROJECTS_INDEX, autoclip.RECORDINGS_LOG,
              forecast.HISTORY_PATH, forecast.MODEL_PATH, telegram_bot.STATE_PATH,
              autoclip.browser_profile_dir(), diag.LOG_DIR]}))
"""
    env = dict(os.environ, APPDATA=os.path.join(os.environ.get("TEMP", HERE), "autoclip_appdata_test"))
    p = subprocess.run([sys.executable, "-c", code, HERE], capture_output=True, text=True, env=env,
                       encoding="utf-8")
    data = json.loads(p.stdout.strip().splitlines()[-1])
    user = os.path.normcase(os.path.abspath(data["user"]))
    assert user.endswith(os.path.normcase(os.path.join("autoclip_appdata_test", "AutoClip")))
    for path in data["paths"]:
        full = os.path.normcase(os.path.abspath(path))
        assert full.startswith(user + os.sep), path
        assert not full.startswith(os.path.normcase(data["app"]) + os.sep), path


def _fill(root):
    os.makedirs(os.path.join(root, "звуки"), exist_ok=True)
    os.makedirs(os.path.join(root, "браузер", "Default", "Cache"), exist_ok=True)
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    files = {"настройки.json": {"sound": "буп", "music_dir": r"D:\Музыка"},
             "telegram.json": {"token": "123:abc", "chat_id": 42},
             "история.json": [{"views": 100}], "модель.json": {"n_like": 3},
             "записи.json": {"a.mp4": "no"}, "пресеты.json": [], "стили.json": []}
    for name, data in files.items():
        with open(os.path.join(root, name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    open(os.path.join(root, "звуки", "мой.wav"), "wb").write(b"RIFF")
    open(os.path.join(root, "браузер", "Default", "Cookies"), "wb").write(b"c")
    open(os.path.join(root, "браузер", "Default", "Cache", "big"), "wb").write(b"x" * 1000)
    open(os.path.join(root, "logs", "a.log"), "w").write("log")


def test_save_and_restore_roundtrip(tmp_path, fake_trash):
    root = backup.data_dir()
    _fill(root)
    proj = tmp_path / "з_clips" / "project.json"
    proj.parent.mkdir()
    proj.write_text("{}", encoding="utf-8")
    with open(os.path.join(root, "нарезки.json"), "w", encoding="utf-8") as f:
        json.dump([str(proj), str(tmp_path / "нет" / "project.json")], f)
    z = str(tmp_path / "копия.zip")
    res = backup.save_backup(z)
    names = zipfile.ZipFile(z).namelist()
    assert "data/telegram.json" in names and "data/звуки/мой.wav" in names
    assert "data/браузер/Default/Cookies" in names
    assert not any("Cache" in n or n.startswith("data/logs") for n in names)   # без кэша и логов
    m = backup.read_manifest(z)
    assert m["format"] == backup.FORMAT and m["secrets"] == "plain" and res["files"] == len(m["files"])
    assert backup.last_saved() is not None

    # всё поменялось / пропало — восстанавливаем
    with open(os.path.join(root, "настройки.json"), "w", encoding="utf-8") as f:
        json.dump({"sound": "другой"}, f)
    os.remove(os.path.join(root, "telegram.json"))
    out = backup.restore_backup(z)
    with open(os.path.join(root, "настройки.json"), encoding="utf-8") as f:
        assert json.load(f)["sound"] == "буп"
    with open(os.path.join(root, "telegram.json"), encoding="utf-8") as f:
        assert json.load(f)["token"] == "123:abc"                    # Telegram — без повторного ввода
    assert os.path.isfile(os.path.join(root, "звуки", "мой.wav"))
    with open(os.path.join(root, "нарезки.json"), encoding="utf-8") as f:
        assert json.load(f) == [str(proj)]                           # нарезки, которых нет, — мимо
    assert out["missing"] == 1
    trashed = os.listdir(tmp_path / "корзина")
    assert any("настройки" in n for n in trashed)                     # прежнее — в корзину, не насовсем


def test_restore_refuses_bad_files(tmp_path):
    bad = tmp_path / "не_копия.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("a.txt", "x")
    with pytest.raises(autoclip.AutoClipError):
        backup.read_manifest(str(bad))
    newer = tmp_path / "новая.zip"
    with zipfile.ZipFile(newer, "w") as z:
        z.writestr("manifest.json", json.dumps({"app": "AutoClip", "format": backup.FORMAT + 1}))
    with pytest.raises(autoclip.AutoClipError, match="новой версией"):
        backup.read_manifest(str(newer))
    evil = tmp_path / "злая.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("manifest.json", json.dumps({"app": "AutoClip", "format": 1}))
        z.writestr("data/../../вне.txt", "x")
    backup.restore_backup(str(evil))
    assert not (tmp_path / "вне.txt").exists()


def test_monthly_reminder(monkeypatch):
    now = datetime.datetime(2026, 12, 1)
    start = now - datetime.timedelta(days=40)
    assert backup.need_reminder({}, now, first_run=start)                     # месяц без копии
    assert not backup.need_reminder({}, now, first_run=now - datetime.timedelta(days=5))
    assert not backup.need_reminder({"backup_remind": False}, now, first_run=start)   # выключено
    told = (now - datetime.timedelta(days=3)).isoformat()
    assert not backup.need_reminder({"backup_told": told}, now, first_run=start)      # уже напомнил
    backup.mark_saved(now - datetime.timedelta(days=2))
    assert not backup.need_reminder({}, now, first_run=start)                 # копия свежая


def test_window_backup_buttons(tmp_path, monkeypatch, fake_trash):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    import app
    app.dark_palette(QApplication.instance() or QApplication([]))
    _fill(backup.data_dir())
    win = app.MainWindow()
    st = win.settings_page
    z = str(tmp_path / "к.zip")
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda p, t, text, *a: told.append(text))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (z, ""))
    st.save_backup()
    assert os.path.isfile(z) and "токен" in told[-1] and "Последняя копия" in st.backup_state.text()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (z, ""))
    monkeypatch.setattr(app, "ask_choice", lambda p, text, ch: "yes")
    st.restore_backup()
    assert "восстановлена" in told[-1]
    win.close()
