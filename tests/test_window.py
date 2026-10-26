"""Окно на отключённом мониторе: открывается на основном и целиком; развёрнутость помнится."""
import sys

import pytest

import autoclip

pytest.importorskip("PySide6")


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    return A


def inside(w):
    from PySide6.QtGui import QGuiApplication
    g = w.geometry()
    return any(sc.availableGeometry().contains(g) for sc in QGuiApplication.screens())


def test_window_from_missing_monitor(app_module):
    A = app_module
    w = A.MainWindow()
    w.setGeometry(-6000, -3000, 1200, 860)              # где-то на мониторе, которого нет
    w.show()
    w.close()                                          # запомнили это место
    w2 = A.MainWindow()
    try:
        w2.show()
        assert inside(w2)                              # на основном мониторе и целиком
    finally:
        w2.close()


def test_too_big_window_shrinks(app_module):
    from PySide6.QtGui import QGuiApplication
    A = app_module
    area = QGuiApplication.primaryScreen().availableGeometry()
    w = A.MainWindow()
    w.setMinimumSize(10, 10)
    w.setGeometry(area.x() + 300, area.y() + 200, area.width() + 900, area.height() + 700)
    assert A.fit_on_screen(w)
    assert inside(w)
    assert not A.fit_on_screen(w)                       # уже на месте — ничего не делаем
    w.close()


def test_maximized_remembered(app_module):
    A = app_module
    w = A.MainWindow()
    w.show()
    w.showMaximized()
    w.close()
    assert A.load_settings()["geometry"]
    w2 = A.MainWindow()
    try:
        w2.show()
        assert w2.isMaximized()
    finally:
        w2.close()


def test_detached_player_from_missing_monitor(app_module):
    A = app_module
    w = A.MainWindow()
    try:
        w.show()
        w.toggle_detach()
        w.detached.setGeometry(-5000, -900, 560, 960)    # второй монитор отключили
        w.toggle_detach()                              # закрыли — место запомнилось
        w.toggle_detach()                              # открыли снова
        assert inside(w.detached)
        w.toggle_detach()
    finally:
        w.close()


def test_stage_strip_shows_current_and_total(monkeypatch):
    """2.3.1: этап и его процент — прямо в полосе («Модель», 50%, этап 3 из 5), общий процент — рядом."""
    import sys
    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    import autoclip
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    import app
    app.dark_palette(QApplication.instance() or QApplication([]))
    win = app.MainWindow()
    cut = win.cut
    assert cut.bar.state == "idle"
    cut.eta = autoclip.Eta()
    cut.show_progress("модель", 50, "")
    bar = cut.bar
    assert (bar.state, bar.name, round(bar.pct), bar.index + 1, bar.count) == ("busy", "Модель", 50, 3, 5)
    assert cut.total.text().startswith("Всего ")
    cut.show_progress("рендер", 10, "")
    assert (bar.name, round(bar.pct)) == ("Рендер", 10)                 # новый этап — снова с нуля
    cut.finished("D:/папка")
    assert bar.state == "done"
    win.close()


def test_animations_only_when_visible(monkeypatch):
    """5.20: анимации — только когда окно видно и игра не на весь экран; тост сам исчезает."""
    import sys
    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    import autoclip
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    import app
    app.dark_palette(QApplication.instance() or QApplication([]))
    monkeypatch.setattr(autoclip, "fullscreen_app", lambda: None)
    app._ANIM["t"] = 0
    win = app.MainWindow()
    assert not app.animations_ok(win)                          # окно скрыто (в трее) — без анимаций
    win.show()
    assert app.animations_ok(win)
    monkeypatch.setattr(autoclip, "fullscreen_app", lambda: "game.exe")
    app._ANIM["t"] = 0
    assert not app.animations_ok(win)                          # игра на весь экран — без анимаций
    app._ANIM["t"] = 0
    monkeypatch.setattr(autoclip, "fullscreen_app", lambda: None)
    win.toast("Привет", ms=50)
    assert win._toast.isVisible() and win._toast.text() == "Привет"
    from qtwait import pump
    pump(200)
    assert not win._toast.isVisible()
    cut = win.cut
    cut.eta = autoclip.Eta()
    cut.show_progress("поиск", 50, "")
    assert cut.scissors.isVisible() and cut.scissors.x() > 0  # ножницы едут по полосе
    cut.finished(None)
    assert not cut.scissors.isVisible()
    win.close()
