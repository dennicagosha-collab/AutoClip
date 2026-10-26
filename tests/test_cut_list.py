"""Патч 5.14: список нарезок AutoClip с числом клипов по статусам и путь к папке."""
import json
import os
import sys

import pytest

import autoclip


def _cut(base, name, created, statuses):
    d = base / name / ".autoclip"
    d.mkdir(parents=True)
    clips = [{"id": f"c{i}", "status": st, "file": f"{i}.mp4"} for i, st in enumerate(statuses)]
    (d / "project.json").write_text(json.dumps({"created": created, "source": "D:/Записи/запись.mp4",
                                                "clips": clips, "layout": 2}), encoding="utf-8")
    (d / autoclip.MARKER).write_text("{}", encoding="utf-8")
    return str(d / "project.json")


def test_cut_summaries(tmp_path):
    base = tmp_path / "Клипы"
    autoclip.CONFIG["clips_dir"] = str(base)
    _cut(base, "Клипы 24.10.2026", "2026-10-24T02:00:00", ["new", "good", "rejected"])
    _cut(base, "Клипы 25.10.2026", "2026-10-25T01:00:00", ["post", "ok", "published", "new"])
    xs = autoclip.cut_summaries()
    assert [x["name"] for x in xs] == ["Клипы 25.10.2026", "Клипы 24.10.2026"]        # новые первыми
    assert xs[1]["counts"] == {"new": 1, "post": 1, "rejected": 1}                     # «хороший» = «выложу»
    label = autoclip.cut_label(xs[0])
    assert label.startswith("Клипы 25.10.2026  ·  25.10 01:00  ·  запись")
    assert "новых 1" in label and "выложу 1" in label and "норм 1" in label and "выложено 1" in label


def test_copy_path_button(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    base = tmp_path / "Клипы"
    autoclip.CONFIG["clips_dir"] = str(base)
    pp = _cut(base, "Клипы 26.10.2026", "2026-10-26T01:00:00", ["new"])
    import app
    app.dark_palette(QApplication.instance() or QApplication([]))
    win = app.MainWindow()
    win.cut.apply_config = lambda: None
    page = win.clips
    page.refresh_recent()
    assert page.projects.count() == 1 and page.projects.currentIndex() == -1          # при запуске — пусто
    page.proj = autoclip.load_project(pp)
    page.copy_cut_path()
    assert QApplication.clipboard().text() == str(base / "Клипы 26.10.2026")
    win.close()
