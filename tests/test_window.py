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
    """5.19: полоса «Звук → Расшифровка → Модель → Поиск → Рендер», текущий этап, общий процент."""
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
    assert [lb.text() for lb in cut.step_labels] == ["Звук", "Расшифровка", "Модель", "Поиск", "Рендер"]
    cut.eta = autoclip.Eta()
    cut.show_progress("модель", 50, "")
    texts = [lb.text() for lb in cut.step_labels]
    assert texts[0] == "✓ Звук" and texts[1] == "✓ Расшифровка" and texts[2] == "Модель  50%"
    assert cut.step_labels[2].property("state") == "active" and cut.total.text().startswith("Всего ")
    win.close()
