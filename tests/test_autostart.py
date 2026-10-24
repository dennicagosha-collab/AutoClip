"""Патч 3Б.8: запуск вместе с Windows (реестр в тестах — подменённый, см. conftest)."""
import os
import sys

import pytest

import autoclip
import autostart


def test_enable_writes_and_disable_removes():
    assert not autostart.is_enabled()
    cmd = autostart.enable(["C:\\Windows\\pyw.exe", "-3.13"])
    assert autostart.is_enabled() and autostart._reg_get(autostart.NAME) == cmd
    assert cmd.startswith('"C:\\Windows\\pyw.exe" -3.13 ')
    assert f'"{autostart.APP}"' in cmd and cmd.endswith(" --tray")
    autostart.disable()
    assert not autostart.is_enabled()
    autostart.disable()                                      # второй раз — без ошибки


def test_python_like_launcher(monkeypatch):
    monkeypatch.setattr(autostart.shutil, "which", lambda n: f"C:\\Windows\\{n}.exe")

    class P:
        def __init__(self, rc):
            self.returncode = rc
    tried = []

    def run(args, **k):
        tried.append(args[1])
        return P(0 if args[1] == "-3.12" else 1)          # 3.13 нет, 3.12 есть — как в AutoClip.bat
    monkeypatch.setattr(autostart.subprocess, "run", run)
    assert autostart.python_cmd() == ["C:\\Windows\\pyw.exe", "-3.12"]
    assert tried[:2] == ["-3.13", "-3.12"]
    monkeypatch.setattr(autostart.shutil, "which", lambda n: None)   # лаунчера нет — pythonw
    assert autostart.python_cmd()[0].lower().endswith(("pythonw.exe", "python.exe"))


def test_refresh_after_move(monkeypatch):
    autostart._reg_set(autostart.NAME, '"pyw" -3.13 "E:\\Старое\\app.py" --tray')
    monkeypatch.setattr(autostart, "python_cmd", lambda: ["pyw", "-3.13"])
    autostart.refresh()
    assert autostart.APP in autostart._reg_get(autostart.NAME)
    autostart.disable()
    autostart.refresh()                                      # выключен — не включает
    assert not autostart.is_enabled()


def test_startup_shortcuts_found_and_trashed(tmp_path, fake_trash):
    d = tmp_path / "автозагрузка"
    d.mkdir()
    (d / "AutoClip.lnk").write_bytes(b"x")
    (d / "Discord.lnk").write_bytes(b"x")
    found = autostart.startup_shortcuts()
    assert [os.path.basename(x) for x in found] == ["AutoClip.lnk"]
    autostart.remove_shortcuts(found)
    assert not (d / "AutoClip.lnk").exists() and (d / "Discord.lnk").exists()


@pytest.fixture
def A(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    import app
    app.dark_palette(QApplication.instance() or QApplication([]))
    return app


def test_tray_flag_hides_window(A):
    win = A.MainWindow()
    if not win.tray:                                         # в тестах без экрана трея нет — подделка

        class Fake:
            visible = False

            def setVisible(self, v):
                self.visible = v

            def isVisible(self):
                return self.visible

            def __getattr__(self, name):
                return lambda *a, **k: None
        win.tray, win.tray_watch = Fake(), Fake()
    assert A.start_window(win, ["app.py", "--tray"]) is False
    assert not win.isVisible() and win.tray.isVisible()
    win._quitting = True
    win.close()
    win2 = A.MainWindow()
    assert A.start_window(win2, ["app.py"]) is True and win2.isVisible()
    win2.close()


def test_settings_toggle_and_shortcut_question(A, tmp_path, monkeypatch, fake_trash):
    d = tmp_path / "автозагрузка"
    d.mkdir()
    (d / "AutoClip.lnk").write_bytes(b"x")
    monkeypatch.setattr(autostart, "python_cmd", lambda: ["pyw", "-3.13"])
    asked = []
    monkeypatch.setattr(A, "ask_choice", lambda p, text, ch: asked.append(text) or "remove")
    win = A.MainWindow()
    st = win.settings_page
    assert not st.cb_autostart.isChecked()
    st.cb_autostart.setChecked(True)
    assert autostart.is_enabled() and asked and "AutoClip.lnk" in asked[0]
    assert not (d / "AutoClip.lnk").exists()
    st.cb_autostart.setChecked(False)
    assert not autostart.is_enabled()
    win.close()
