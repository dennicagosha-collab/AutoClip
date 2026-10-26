"""Патч 5.15: выбор нескольких клипов (Ctrl/Shift) и действия сразу для всех."""
import os
import sys

import pytest

import autoclip

pytest.importorskip("PySide6")


def test_multi_select_actions(tmp_path, fake_trash, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import test_editor
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", lambda m: None)
    autoclip.CONFIG.update(llm="none", clips=3, hook="off")
    cut = autoclip.process(str(test_editor._video(tmp_path)))
    import app as A
    A.dark_palette(QApplication.instance() or QApplication([]))
    win = A.MainWindow()
    page = win.clips
    page.load(cut)
    n = page.list.count()
    assert n >= 2
    page.list.item(0).setSelected(True)
    page.list.item(1).setSelected(True)
    clips = page.selected_clips()
    assert len(clips) == 2
    menu = page.build_menu()
    names = [a.text() for a in menu.actions() if a.text()]
    assert "Выложу (2)" in names and "Не то — в корзину (2)" in names and "Пересобрать (2)" in names
    page.bulk_rate(clips, "ok")
    proj = autoclip.load_project(cut)
    assert sorted(c["status"] for c in proj["clips"] if c["id"] in {x["id"] for x in clips}) == ["ok", "ok"]
    page.bulk_published(clips, "youtube")
    proj = autoclip.load_project(cut)
    assert sum(c["status"] == "published" for c in proj["clips"]) == 2
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    page.bulk_rate([c for c in proj["clips"] if c["status"] == "published"], "bad")
    assert sum(c["status"] == "rejected" for c in autoclip.load_project(cut)["clips"]) == 2
    win.close()
