"""Редизайн 2.3.0: шрифт и значки из папки программы, карточки клипов, «список / сетка», без символов-квадратиков."""
import os
import re
import sys

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton  # noqa: E402

import autoclip  # noqa: E402
import theme  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def A(tmp_path, monkeypatch):
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    import app
    qapp = QApplication.instance() or QApplication([])
    app.dark_palette(qapp)
    return app


def test_font_and_licenses_in_program(A):
    assert theme.FAMILY == "Inter"
    assert os.path.isfile(os.path.join(HERE, "fonts", "LICENSE-Inter.txt"))
    assert os.path.isfile(os.path.join(HERE, "icon", "lucide", "LICENSE"))


def test_every_icon_used_in_code_exists():
    src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    names = set(re.findall(r'(?:set_icon\([^,]+,|theme\.icon\(|theme\.pixmap\(|icon_label\()\s*"([a-z0-9-]+)"', src))
    names |= set(re.findall(r'"([a-z0-9-]+)"', src[src.index("CARD_ICONS = {"):src.index("def icon_label")]))
    import app as _app  # noqa: F401
    names |= {p[2] for p in _app.MainWindow.PAGES}
    missing = sorted(n for n in names if not theme.has_icon(n))
    assert not missing, missing


def test_icon_draws_something(A):
    pm = theme.pixmap("scissors", "#ff4f6d", 24)
    img = pm.toImage()
    assert any(img.pixelColor(x, y).alpha() > 0 for x in range(0, img.width(), 2) for y in range(0, img.height(), 2))
    assert theme.pixmap("нет-такого", "#fff", 24).toImage().pixelColor(5, 5).alpha() == 0   # не квадратик


def test_no_unicode_symbol_buttons(A):
    win = A.MainWindow()
    bad = "✂▶■❚👍🎞↑↓→▸▾▴✈"
    for b in win.findChildren(QPushButton) + win.findChildren(QToolButton):
        assert not any(ch in b.text() for ch in bad), b.text()
    win.close()


def test_view_toggle_remembered(A):
    win = A.MainWindow()
    page = win.clips
    page.set_view("list")
    assert not page.cards.grid and A.load_settings()["clips_view"] == "list"
    page.set_view("grid")
    assert page.cards.grid and A.load_settings()["clips_view"] == "grid"
    assert page.view_btns["grid"].isChecked() and not page.view_btns["list"].isChecked()
    win.close()


def test_cards_have_data_and_status(A, tmp_path):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import test_cuts
    autoclip.log = lambda m: None
    folder = test_cuts._project(tmp_path)
    win = A.MainWindow()
    win.clips.load(folder)
    d = win.clips.list.item(0).data(A.CARD)
    assert d["kind"] == "clip" and d["status"] == "new" and d["title"]
    assert A.STATUS_NAMES[d["status"]] == "Новый"
    cards = win.clips.cards
    if d.get("cover"):
        cards.cover(d["cover"])
        cards.load_all_now()
        assert cards.cover(d["cover"])                   # обложка загружена — не скелет
    cards.set_grid(True)
    w, h = cards.size_hint().width(), cards.size_hint().height()
    assert h > w                                         # вертикальная карточка
    win.close()


def test_glow_and_dash_respect_animations(A, monkeypatch):
    win = A.MainWindow()
    win.show()
    monkeypatch.setattr(A, "animations_ok", lambda w=None: False)    # трей / игра — без анимаций
    d0 = win.cut.drop._dash
    win.cut.drop._tick()
    assert win.cut.drop._dash == d0
    win.cut.btn._glow._to(1.0)                           # без анимации — сразу
    assert win.cut.btn._glow.eff.blurRadius() > 26
    win.close()


def test_dash_timer_only_while_visible(A):
    """Рамка «бежит», только пока её видно: у закрытого окна таймер стоит (не грузит ПК)."""
    win = A.MainWindow()
    drop = win.cut.drop
    assert not drop._dash_timer.isActive()
    win.show()
    from qtwait import pump
    pump(50)
    assert drop._dash_timer.isActive()
    win.close()
    pump(50)
    assert not drop._dash_timer.isActive()


def test_feed_shows_only_important(A):
    """«Что происходит»: важные строки со значками, служебные (с отступом, трассировки) — только в «Весь лог»."""
    assert A.feed_item("✅ Готово за 3.1 мин → D:\Клипы")[0] == "circle-check"
    assert A.feed_item("⚠️  Telegram: ❌ Нет связи с Telegram. Работаю без него.")[2].startswith("Telegram")
    assert A.feed_item("   [3/10] 03_клип.mp4") is None
    assert A.feed_item("Выбери запись и нажми «Нарезать».") is None
    assert A.feed_item("❌ Неожиданная ошибка:\nTraceback ...")[2] == "Неожиданная ошибка:"
    win = A.MainWindow()
    cut = win.cut
    assert cut.feed.isVisibleTo(win) and not cut.log.isVisibleTo(win)     # лента на виду, лог — по кнопке
    cut.write("🔊 Достаю звук...")
    cut.write("   служебная строка")
    assert len(cut.feed.items) == 1 and "служебная" in cut.log.toPlainText()
    cut.btn_log.setChecked(True)
    assert cut.log.isVisibleTo(win)
    win.close()


def test_hover_preview_paints_frames(A):
    """Превью при наведении — кадры рисуются на карточке, без второго окна видео."""
    from PySide6.QtGui import QImage, QColor
    win = A.MainWindow()
    cards = win.clips.cards
    win.clips.list.addItem("x")
    cards.preview_row = 0

    class Frame:
        def toImage(self):
            img = QImage(108, 192, QImage.Format_RGB32)
            img.fill(QColor("red"))
            return img
    cards._frame(Frame())
    assert cards.preview_pm is not None and cards.preview_pm.height() == cards.GRID_COVER * 2
    cards.stop_preview()
    assert cards.preview_row == -1 and cards.preview_pm is None
    from PySide6.QtMultimediaWidgets import QVideoWidget
    assert not win.clips.list.viewport().findChildren(QVideoWidget)
    win.close()


def test_telegram_send_shows_center_notice(A):
    """Отправка в Telegram — крупно по центру: «Отправляю…» → «Отправлено», ошибка — красным."""
    win = A.MainWindow()
    win.resize(1200, 800)
    win.show()
    page = win.clips
    page._send_state("Telegram: готовлю…")
    n = win._notice
    assert n.isVisible() and n.kind == "busy" and n.title == "Отправляю в Telegram" and n.sub == "готовлю…"
    centre = win.mapToGlobal(win.rect().center())
    assert abs(n.geometry().center().x() - centre.x()) < 4 and abs(n.geometry().center().y() - centre.y()) < 4
    assert n.isWindow()                                                   # своё окошко — видео его не закроет
    page._send_state("Отправлено в Telegram ✓")
    assert n.kind == "ok" and n.title == "Отправлено в Telegram"
    page._send_state("Не отправилось: файл слишком большой")
    assert n.kind == "error" and "слишком большой" in n.sub
    win.close()


def test_new_own_sound_appears_without_restart(A, tmp_path, monkeypatch):
    """Положил звук в «Свои звуки» — он сразу в списке, когда раскрываешь выбор (без перезапуска)."""
    names = ["перелистывание", "бип"]
    monkeypatch.setattr(autoclip, "list_sounds", lambda: list(names))
    win = A.MainWindow()
    combo = win.settings_page.sound
    win.settings_page.refresh_sounds()
    assert combo.findText("мой.mp3") < 0
    names.append("мой.mp3")                                  # Гоша положил файл в папку
    combo.showPopup()
    combo.hidePopup()
    assert combo.findText("мой.mp3") >= 0
    assert "мой.mp3" in win.settings_page.pool_checks        # и в «Случайном» тоже
    win.close()


def test_player_volume_only_for_preview(A, tmp_path, monkeypatch):
    """Громкость просмотра: ползунок у плеера, запоминается, на сборку клипов не влияет."""
    win = A.MainWindow()
    pl = win.clips.player
    pl.vol.setValue(30)
    assert A.load_settings()["player_volume"] == 30
    assert 0 < pl.audio.volume() < 0.3                       # «на слух»: 30% ползунка — заметно тише
    pl._toggle_mute()
    assert pl.vol.value() == 0 and pl.audio.volume() == 0
    pl._toggle_mute()
    assert pl.vol.value() == 30
    assert "player_volume" not in autoclip.RENDER_KEYS        # в настройки сборки клипа не попадает
    win.close()
    win2 = A.MainWindow()
    assert win2.clips.player.vol.value() == 30                # запомнилось
    win2.close()
