"""Патч 5.8: «Добавить слово здесь» — слово, которого Whisper не услышал."""
import subprocess
import sys

import numpy as np
import pytest

import autoclip


def _rms(path, a, b):
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(path),
                        "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True, check=True)
    x = np.frombuffer(p.stdout, dtype=np.int16).astype(float) / 32768
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


def test_word_span_by_voice():
    assert autoclip.word_span_at("", 10.2, voice=[(9.9, 10.6), (12.0, 13.0)]) == (9.9, 10.6)
    assert autoclip.word_span_at("", 11.5, voice=[(9.9, 10.6)]) == (11.5, 12.0)    # голоса рядом нет
    a, b = autoclip.word_span_at("", 10.0, voice=[(5.0, 20.0)])
    assert 9.3 <= a <= 10.0 and b - a <= 1.6                                       # не длиннее 1,5 с


def test_added_mat_word_masked_and_bleeped(tmp_path):
    v = tmp_path / "в.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=270x480:r=30:d=8",
                    "-f", "lavfi", "-i", "sine=f=300:d=8", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(v)], check=True)
    segs = [{"s": 1, "e": 2, "text": "ну", "words": [{"s": 1.0, "e": 1.4, "w": "ну"}]}]
    work = tmp_path / "w"
    work.mkdir()
    cfg = dict(autoclip.CONFIG, zoom="off", subs=True, nick=False, bleep=True, music=None,
               bleep_sound="тишина", censor="partial", words_add=[[4.0, 4.6, "блять"]])
    out = tmp_path / "к.mp4"
    job = {"s": 0.0, "e": 7.0, "zooms": [], "hook": None}
    assert autoclip.render_clip(str(v), job, segs, autoclip.probe(str(v)), str(out), str(work), cfg) == 1
    ass = (work / "subs.ass").read_text(encoding="utf-8")
    assert "*ЛЯТЬ" in ass and "БЛЯТЬ" not in ass                     # маска, как у обычного мата
    # частичная цензура: звук закрывает «б» в начале слова, дальше слышно
    assert _rms(out, 4.02, 4.1) < 0.005 and _rms(out, 4.3, 4.5) > 0.05 and _rms(out, 2.0, 3.0) > 0.05


def test_editor_add_word(tmp_path, fake_trash, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QInputDialog
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    import test_cuts
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", lambda m: None)
    cut = test_cuts._project(tmp_path)
    import app as A
    A.dark_palette(QApplication.instance() or QApplication([]))
    win = A.MainWindow()
    page = win.clips
    page.load(cut)
    c = page.current_clip()
    monkeypatch.setattr(page.player.player, "position", lambda: 3000)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("сука", True))
    monkeypatch.setattr(autoclip, "word_span_at", lambda src, t: (round(t, 2), round(t + 0.5, 2)))
    n = page.t_words.rowCount()
    page.add_word_here()
    assert page.t_words.rowCount() == n + 1 and page.t_words.item(n, 2).text() == "мат"
    assert list(page.pending()) == ["words_add"]
    page.rebuild()
    from qtwait import pump
    for _ in range(1200):
        if not page.busy:
            break
        pump(50)
    c1 = autoclip.find_clip(autoclip.load_project(cut), c["id"])
    assert c1["overrides"]["words_add"][0][2] == "сука" and c1["bleeps"] >= 1      # пережило пересборку
    win.close()
