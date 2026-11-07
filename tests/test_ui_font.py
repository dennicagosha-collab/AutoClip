"""0.2.0: свой шрифт окна — из своих шрифтов пользователя (%APPDATA%\AutoClip\шрифты), не из программы."""
import json
import os

import pytest

import autoclip
from fontfile import renamed_font

WIN_FONT = r"C:\Windows\Fonts\comic.ttf"


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.mark.skipif(not os.path.isfile(WIN_FONT), reason="нужен шрифт Windows")
def test_ui_font(tmp_path, fake_trash, qapp):
    import app as A
    assert A.ui_font() is None                                         # по умолчанию — обычный
    autoclip.add_font(renamed_font(WIN_FONT, str(tmp_path / "мой.ttf"), "AutoClip UI Face"))
    with open(autoclip.SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump({"ui_font": "AutoClip UI Face"}, f)
    assert A.ui_font() == "AutoClip UI Face"
    A.dark_palette(qapp)
    assert qapp.font().family() == "AutoClip UI Face" and '"AutoClip UI Face", "Inter"' in qapp.styleSheet()
    with open(autoclip.SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump({"ui_font": "Шрифта нет"}, f)                       # файл шрифта удалили — обычный
    assert A.ui_font() is None
    A.dark_palette(qapp)
