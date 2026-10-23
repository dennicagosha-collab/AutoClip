"""Автообновление: версия, релиз на GitHub, замена файлов программы без потери данных."""
import io
import json
import os
import subprocess
import sys
import urllib.error
import zipfile

import pytest

import autoclip
import update


def test_versions():
    assert update.parse_version("v1.2.3") == (1, 2, 3)
    assert update.parse_version("1.4") == (1, 4, 0)
    assert update.parse_version("abc") is None
    assert update.is_newer("1.0.1", "1.0.0") and update.is_newer("v2", "1.9.9")
    assert not update.is_newer("1.0.0", "1.0.0") and not update.is_newer("0.9", "1.0.0")
    assert not update.is_newer("мусор", "1.0.0")


class FakeResp(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_latest_release(monkeypatch):
    rel = {"tag_name": "v1.2.0", "body": "Что нового: всё",
           "assets": [{"name": "AutoClip-v1.2.0.zip", "size": 123,
                       "browser_download_url": "https://example/a.zip"}],
           "zipball_url": "https://example/zipball"}
    asked = []
    monkeypatch.setattr(update, "_get", lambda url, t: asked.append(url) or
                        FakeResp(json.dumps(rel).encode()))
    r = update.latest("gosha/AutoClip")
    assert asked == ["https://api.github.com/repos/gosha/AutoClip/releases/latest"]
    assert r == {"version": "1.2.0", "notes": "Что нового: всё", "url": "https://example/a.zip",
                 "size": 123}
    monkeypatch.setattr(update, "VERSION", "1.0.0")
    assert update.check("gosha/AutoClip")["version"] == "1.2.0"
    assert update.check("gosha/AutoClip", skip="1.2.0") is None          # «Пропустить эту версию»
    monkeypatch.setattr(update, "VERSION", "1.2.0")
    assert update.check("gosha/AutoClip") is None
    assert update.latest("") is None                                   # репозиторий не задан

    def fail(code):
        def get(url, t):
            if code:
                raise urllib.error.HTTPError(url, code, "x", {}, None)
            raise urllib.error.URLError("нет сети")
        return get
    monkeypatch.setattr(update, "_get", fail(404))
    assert update.latest("gosha/AutoClip") is None                     # релизов ещё нет
    for code in (500, None):
        monkeypatch.setattr(update, "_get", fail(code))
        with pytest.raises(autoclip.AutoClipError):
            update.latest("gosha/AutoClip")


def make_zip(path, files, top="AutoClip-v1.1.0/"):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(top + name, text)
    return str(path)


def write(d, files):
    for name, text in files.items():
        p = os.path.join(d, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)


def read(p):
    return open(p, encoding="utf-8").read()


OLD = {"app.py": "старое окно", "autoclip.py": "старое ядро", "update.py": "u",
       "install.bat": "pip", "старый.py": "убрали в новой версии"}


def test_install_replaces_only_program_files(tmp_path, fake_trash):
    app = tmp_path / "AutoClip"
    app.mkdir()
    write(app, OLD)
    user = {"запись.mp4": "видео", "запись_clips/01.mp4": "клип", "AutoClip.lnk": "ярлык",
            "звуки/мой.wav": "звук"}
    write(app, user)
    (app / update.MANIFEST_NAME).write_text(json.dumps(list(OLD)), encoding="utf-8")
    z = make_zip(tmp_path / "new.zip", {"app.py": "новое окно", "autoclip.py": "старое ядро",
                                        "update.py": "u", "install.bat": "pip",
                                        "icon/autoclip.ico": "иконка"})
    res = update.install(z, str(app))
    assert res == {"changed": 2, "removed": 1, "need_install": False}
    assert read(app / "app.py") == "новое окно" and read(app / "icon/autoclip.ico") == "иконка"
    assert not (app / "старый.py").exists()
    backup = app / update.BACKUP_NAME
    assert read(backup / "app.py") == "старое окно"                  # прежняя версия не пропала
    assert read(backup / "старый.py") == "убрали в новой версии"
    assert not (backup / "autoclip.py").exists()                     # не менялся — не копируем
    for name, text in user.items():
        assert read(app / name) == text                              # файлы Гоши не тронуты
    assert sorted(json.loads(read(app / update.MANIFEST_NAME))) == [
        "app.py", "autoclip.py", "icon/autoclip.ico", "install.bat", "update.py"]

    z2 = make_zip(tmp_path / "newer.zip", {"app.py": "ещё новее", "autoclip.py": "старое ядро",
                                           "update.py": "u", "install.bat": "pip + новое",
                                           "icon/autoclip.ico": "иконка"})
    res = update.install(z2, str(app))
    assert res["need_install"] is True and res["removed"] == 0
    assert os.listdir(fake_trash) == [f"0_{update.BACKUP_NAME}"]     # позапрошлая — в корзину
    assert read(backup / "app.py") == "новое окно"


def test_bad_archives_change_nothing(tmp_path):
    app = tmp_path / "AutoClip"
    app.mkdir()
    write(app, OLD)
    bad = [make_zip(tmp_path / "evil.zip", {"../../evil.py": "x", "app.py": "x"}, top=""),
           make_zip(tmp_path / "other.zip", {"readme.txt": "не AutoClip"})]
    (tmp_path / "broken.zip").write_bytes(b"not a zip")
    bad.append(str(tmp_path / "broken.zip"))
    for z in bad:
        with pytest.raises(autoclip.AutoClipError):
            update.install(z, str(app))
    for name, text in OLD.items():
        assert read(app / name) == text
    assert not (app / update.BACKUP_NAME).exists() and not (tmp_path / "evil.py").exists()


def git(cwd, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_git_checkout_updates_by_tag(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q")
    write(origin, OLD)
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", "1.0.0")
    git(tmp_path, "clone", "-q", str(origin), "app")
    app = tmp_path / "app"
    write(origin, {"app.py": "новое окно", "install.bat": "pip + новое"})
    git(origin, "commit", "-qam", "1.1.0")
    git(origin, "tag", "v1.1.0")
    assert update.is_git_checkout(str(app))
    res = update.update_git("1.1.0", str(app))
    assert res == {"changed": 2, "removed": 0, "need_install": True}
    assert read(app / "app.py") == "новое окно"

    write(origin, {"app.py": "1.2"})
    git(origin, "commit", "-qam", "1.2.0")
    git(origin, "tag", "v1.2.0")
    write(app, {"autoclip.py": "мои правки"})                       # несохранённые изменения
    with pytest.raises(autoclip.AutoClipError, match="несохранённые"):
        update.update_git("1.2.0", str(app))
    assert read(app / "app.py") == "новое окно"


# ---------- окно ----------

@pytest.fixture
def win(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    w = A.MainWindow()
    yield A, w
    w.close()


def test_update_dialog_and_settings(win):
    A, w = win
    assert w.windowTitle() == f"AutoClip {update.VERSION}"
    assert "не подключён" in w.settings_page.update_state.text()
    w.update_found(None, True)
    assert "последняя версия" in w.settings_page.update_state.text()
    w.update_found({"error": "❌ нет сети"}, True)
    assert w.settings_page.update_state.text() == "❌ нет сети"
    w.update_found({"version": "9.0.0", "notes": "Что нового", "url": "u", "size": 1}, False)
    dlg = w._update_dialog
    assert isinstance(dlg, A.UpdateDialog)
    dlg._done("skip")
    assert w._update_dialog is None
    assert A.load_settings()["skip_version"] == "9.0.0"
    w.update_found({"version": "9.0.1", "notes": "", "url": "u", "size": 1}, False)
    w.update_installed(None, "❌ не скачалось")
    assert "не скачалось" in w._update_dialog.state.text()


# ---------- «Что нового» ----------

NEWS = """# Что нового

## 1.2.0
- Третья версия
  с переносом строки

## 1.0.0 — 23.10.2026
- Первая

## 1.1.0
- Вторая
"""


def test_changelog_parse_and_news_since(tmp_path, monkeypatch):
    entries = update.parse_changelog(NEWS)
    assert [e["version"] for e in entries] == ["1.2.0", "1.1.0", "1.0.0"]     # новые сверху
    assert entries[0]["items"] == ["Третья версия с переносом строки"]
    assert entries[2]["date"] == "23.10.2026"
    monkeypatch.setattr(update, "VERSION", "1.1.0")
    assert [e["version"] for e in update.news_since("1.0.0", entries)] == ["1.1.0"]
    assert update.news_since("1.1.0", entries) == []
    f = tmp_path / "ЧТО_НОВОГО.md"
    f.write_text(NEWS, encoding="utf-8")
    monkeypatch.setattr(update, "CHANGELOG", str(f))
    assert update.release_notes() == "- Вторая"
    assert update.release_notes("9.9.9") == ""


def test_real_changelog_has_current_version():
    entries = update.changelog()
    assert entries and entries[0]["version"] == update.VERSION or \
        any(e["version"] == update.VERSION for e in entries)
    assert all(e["items"] for e in entries)
    assert 5 <= len(next(e for e in entries if e["version"] == "1.0.0")["items"]) <= 8


def test_news_shown_once_after_update(win, monkeypatch):
    A, w = win
    assert w.version_btn.text() == f"версия {update.VERSION}"
    w.show_news()
    assert "Версия 1.0.0" in w._news.body.text()
    w._news.accept()
    assert w._news is None

    monkeypatch.setattr(update, "VERSION", "1.1.0")
    monkeypatch.setattr(update, "changelog", lambda path=None: update.parse_changelog(NEWS))
    w.show()
    w.settings["seen_version"] = ""
    w.news_after_update()                      # первый запуск — без окна, только запомнили
    assert w._news is None and w.settings["seen_version"] == "1.1.0"
    w.settings["seen_version"] = "1.0.0"
    w.news_after_update()                      # обновились с 1.0.0
    assert w._news is not None
    text = w._news.body.text()
    assert "Версия 1.1.0" in text and "1.0.0" not in text and "1.2.0" not in text
    w._news.accept()
    w.news_after_update()                      # второй раз не показываем
    assert w._news is None
    assert A.load_settings()["seen_version"] == "1.1.0"
