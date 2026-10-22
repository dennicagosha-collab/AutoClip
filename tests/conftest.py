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
