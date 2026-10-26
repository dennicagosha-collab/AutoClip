"""Патч 5.17: таймлайн редактора — ручки, хук, писки, выделение, отмена."""
import os
import sys

import pytest

import autoclip

pytest.importorskip("PySide6")


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_timeline_drag_handles_and_select(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from timeline import Timeline
    tl = Timeline()
    tl.resize(600, 96)
    tl.set_clip(20.0, 40.0, 100.0)                     # видно 10–50 с
    got = {}
    tl.bounds_changed.connect(lambda s, e: got.__setitem__("b", (s, e)))
    tl.selection_changed.connect(lambda a, b: got.__setitem__("sel", (a, b)))
    tl.seek.connect(lambda t: got.__setitem__("seek", t))
    x = int(tl.x_of(20.0))
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, 60))
    QTest.mouseMove(tl, QPoint(int(tl.x_of(15.0)), 60))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl.x_of(15.0)), 60))
    assert got["b"][0] == pytest.approx(15.0, abs=0.2) and got["b"][1] == 40.0   # начало раньше — запас записи
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl.x_of(25.0)), 60))
    QTest.mouseMove(tl, QPoint(int(tl.x_of(30.0)), 60))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl.x_of(30.0)), 60))
    a, b = got["sel"]
    assert a == pytest.approx(25.0, abs=0.2) and b == pytest.approx(30.0, abs=0.2)
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl.x_of(33.0)), 60))
    assert got["seek"] == pytest.approx(33.0, abs=0.2)


def test_timeline_hook_stays_inside_clip(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from timeline import Timeline
    tl = Timeline()
    tl.resize(600, 96)
    tl.set_clip(20.0, 40.0, 100.0)
    tl.set_layers(hook=(30.0, 32.0))
    got = []
    tl.hook_changed.connect(lambda a, b: got.append((a, b)))
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl.x_of(31.0)), 8))
    QTest.mouseMove(tl, QPoint(int(tl.x_of(49.0)), 8))                      # тянем за конец клипа
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl.x_of(49.0)), 8))
    a, b = got[-1]
    assert b <= 40.0 + 1e-6 and b - a == pytest.approx(2.0, abs=0.01)          # правило 5: внутри клипа


def test_wheel_zoom(qapp):
    from timeline import Timeline
    tl = Timeline()
    tl.resize(600, 96)
    tl.set_clip(20.0, 40.0, 100.0)
    span = tl.view[1] - tl.view[0]

    class Ev:
        def position(self):
            from PySide6.QtCore import QPointF
            return QPointF(300, 50)

        def angleDelta(self):
            from PySide6.QtCore import QPoint
            return QPoint(0, 120)
    tl.wheelEvent(Ev())
    assert tl.view[1] - tl.view[0] < span


def test_editor_timeline_edits_and_undo(tmp_path, fake_trash, monkeypatch, qapp):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import test_cuts
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", lambda m: None)
    cut = test_cuts._project(tmp_path)
    import app as A
    A.dark_palette(qapp)
    win = A.MainWindow()
    page = win.clips
    page.load(cut)
    c = page.current_clip()
    page._tl_bounds(c["start"] - 2.0, c["end"])                              # потянул ручку начала
    assert page.pending()["start"] == pytest.approx(round(c["start"] - 2.0, 1), abs=0.11)
    page._tl_selection(c["start"] + 2.0, c["start"] + 4.0)
    page._key_cut()                                                        # X
    assert page.pending()["cuts"]
    page.undo()                                                            # Ctrl+Z — вырезки нет
    assert "cuts" not in page.pending()
    page.undo()                                                            # и начало прежнее
    assert not page.pending()
    page.base = {}
    win.close()


def test_dead_pieces_stored_and_estimated(tmp_path, qapp):
    import numpy as np
    from timeline import Timeline, estimate_dead
    x = np.concatenate([np.full(8000 * 5, 0.3), np.full(8000 * 4, 0.01), np.full(8000 * 5, 0.3)]).astype(np.float32)
    x[::2] *= -1
    assert estimate_dead(x, 100.0, []) == [[105.0, 109.0]]                     # тихие 4 с без речи
    assert estimate_dead(x, 100.0, [(106.0, 106.5)]) == []                     # там говорят — не мёртвое
    tl = Timeline()
    tl.set_layers(dead=[[1.0, 5.0]])
    assert tl.dead == [[1.0, 5.0]]
