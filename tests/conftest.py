import os
import sys

import pytest

# окна при тестах рисуются в памяти и не появляются на экране
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autoclip  # noqa: E402


@pytest.fixture(autouse=True)
def clean_config(monkeypatch, tmp_path):
    """Каждый тест видит исходный CONFIG, свой список нарезок и свою папку подборок."""
    monkeypatch.setattr(autoclip, "CONFIG", dict(autoclip.CONFIG))
    monkeypatch.setattr(autoclip, "PROJECTS_INDEX", str(tmp_path / "нарезки.json"))
    monkeypatch.setattr(autoclip, "WEEKLY_DIR", str(tmp_path / "подборки"))
    monkeypatch.setattr(autoclip, "RECORDINGS_LOG", str(tmp_path / "записи.json"))
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))   # не настоящие
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    import forecast
    monkeypatch.setattr(forecast, "HISTORY_PATH", str(tmp_path / "история.json"))
    monkeypatch.setattr(forecast, "MODEL_PATH", str(tmp_path / "модель.json"))
    import update
    monkeypatch.setattr(update, "REPO", "")          # тесты не ходят на GitHub
    import diag
    monkeypatch.setattr(diag, "LOG_DIR", str(tmp_path / "logs"))   # и не пишут в настоящие логи
    monkeypatch.setattr(autoclip, "FONTS_DIR", str(tmp_path / "шрифты"))
    monkeypatch.setattr(autoclip, "STYLES_PATH", str(tmp_path / "стили.json"))
    import telegram_bot
    monkeypatch.setattr(telegram_bot, "STATE_PATH", str(tmp_path / "telegram.json"))   # не настоящий бот
    import autostart                                   # и не трогают настоящий реестр Windows
    reg = {}
    monkeypatch.setattr(autostart, "_reg_get", reg.get)
    monkeypatch.setattr(autostart, "_reg_set", reg.__setitem__)
    monkeypatch.setattr(autostart, "_reg_del", lambda n: reg.pop(n, None))
    monkeypatch.setattr(autostart, "startup_dir", lambda: str(tmp_path / "автозагрузка"))
    import backup                                      # копия — из временной папки, не из %APPDATA%
    (tmp_path / "данные").mkdir(exist_ok=True)
    monkeypatch.setattr(backup, "data_dir", lambda: str(tmp_path / "данные"))


@pytest.fixture
def fake_trash(tmp_path, monkeypatch):
    """Вместо корзины Windows — папка внутри теста."""
    bin_dir = tmp_path / "корзина"
    bin_dir.mkdir()

    def send(path):
        # как корзина Windows: занятый файл не переносится (PermissionError)
        n = len(os.listdir(bin_dir))
        os.replace(path, bin_dir / f"{n}_{os.path.basename(path)}")

    monkeypatch.setattr(autoclip, "_send_to_trash", send)
    return bin_dir


@pytest.fixture(autouse=True)
def no_modal_questions(monkeypatch):
    """Окно-вопрос, на которое тест не ответил, сразу роняет тест — а не ждёт вечно."""
    try:
        from PySide6.QtWidgets import QMessageBox
    except ImportError:
        return

    def fail(self, *a, **k):
        raise AssertionError(f"неожиданный вопрос в окне: {self.text()}")
    monkeypatch.setattr(QMessageBox, "exec", fail)


@pytest.fixture(autouse=True)
def stop_telegram_threads():
    """Поток связи с Telegram от окна прошлого теста не должен читать данные следующего."""
    yield
    app = sys.modules.get("app")
    for link in getattr(getattr(app, "TelegramLink", None), "alive", []):
        link.stop.set()
    if app is not None:
        app.TelegramLink.alive.clear()


def pytest_addoption(parser):
    parser.addoption("--golden", action="store_true", default=False,
                     help="проверка границ на эталонной записи (медленно)")


def pytest_configure(config):
    config.addinivalue_line("markers", "golden: проверка границ на эталонной записи")
