import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autoclip  # noqa: E402


@pytest.fixture(autouse=True)
def clean_config(monkeypatch):
    """Каждый тест видит исходный CONFIG."""
    monkeypatch.setattr(autoclip, "CONFIG", dict(autoclip.CONFIG))


@pytest.fixture
def fake_trash(tmp_path, monkeypatch):
    """Вместо корзины Windows — папка внутри теста."""
    bin_dir = tmp_path / "корзина"
    bin_dir.mkdir()

    def trash(path):
        if os.path.exists(path):
            n = len(os.listdir(bin_dir))
            os.replace(path, bin_dir / f"{n}_{os.path.basename(path)}")

    monkeypatch.setattr(autoclip, "trash", trash)
    return bin_dir
