"""Патч 3Б.4: вырезать кусок, сжать паузы, разбить клип."""
import json
import os
import subprocess

import numpy as np
import pytest

import autoclip


def _rms(path, a, b):
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}",
                        "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                       capture_output=True, check=True)
    x = np.frombuffer(p.stdout, dtype=np.int16).astype(float) / 32768
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


def _dur(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(p.stdout)


# ---------- куски и время ----------

def test_keep_pieces_and_timeline():
    assert autoclip.keep_pieces(10, 20, []) == [(10, 20)]
    assert autoclip.keep_pieces(10, 20, [[12, 14], [13, 15], [30, 40]]) == [(10, 12), (15, 20)]
    assert autoclip.keep_pieces(10, 20, [[5, 25]]) == []
    tl = autoclip.clip_timeline(10, 20, [[12, 14]], hook=(16, 17))
    assert tl == [(16, 17, 0.0, 0), (10, 12, 1.0, 1), (14, 20, 3.0, 2)]
    assert autoclip.timeline_len(tl) == pytest.approx(9.0)
    assert autoclip.rec_to_out(15, tl) == pytest.approx(4.0)
    assert autoclip.rec_to_out(13, tl) is None                      # вырезано
    assert autoclip.rec_to_out(16.5, tl, hook=True) == pytest.approx(0.5)
    assert autoclip.out_to_rec(4.0, tl) == pytest.approx(15.0)
    assert autoclip.out_to_rec(0.5, tl) == pytest.approx(16.5)


def test_hook_never_from_cut_piece():
    rec = {"start": 10, "end": 30, "hook": {"auto": True, "start": 15, "end": 16.5},
           "overrides": {"cuts": [[14, 18]]}}
    assert autoclip.hook_span(rec, {"hook": True}) is None
    rec["overrides"]["cuts"] = [[20, 22]]
    assert autoclip.hook_span(rec, {"hook": True}) == (15, 16.5)


# ---------- вырез посередине: длина, субтитры и писки на своих словах ----------

def test_cut_in_middle_render(tmp_path):
    v = tmp_path / "в.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=270x480:r=30:d=12",
                    "-f", "lavfi", "-i", "sine=f=300:d=12", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(v)], check=True)
    segs = [{"s": 2, "e": 8, "text": "", "words": [
        {"s": 2.0, "e": 2.5, "w": "ну"}, {"s": 4.0, "e": 4.5, "w": "прыжки"},
        {"s": 6.0, "e": 6.5, "w": "сука"}, {"s": 7.0, "e": 7.5, "w": "да"}]}]
    vi = autoclip.probe(str(v))
    work = tmp_path / "w"
    work.mkdir()
    cfg = dict(autoclip.CONFIG, zoom=False, subs=True, nick=False, bleep=True, music=None,
               bleep_sound="тишина", censor="full", cuts=[[3.0, 5.5]])
    out = tmp_path / "к.mp4"
    job = {"s": 1.0, "e": 9.0, "zooms": [], "hook": None}
    assert autoclip.render_clip(str(v), job, segs, vi, str(out), str(work), cfg) == 1
    assert abs(_dur(out) - 5.5) < 0.15                              # 8 с минус вырезанные 2,5 с
    assert job["timeline"] == [[1.0, 3.0, 0.0, 1], [5.5, 9.0, 2.0, 2]]
    # «сука» в записи 6,0–6,5 → в клипе 2,5–3,0: там тихо, вокруг — звук
    assert _rms(out, 2.6, 2.9) < 0.005
    assert _rms(out, 3.4, 3.9) > 0.05
    assert _rms(out, 1.0, 1.4) > 0.05
    ass = (work / "subs.ass").read_text(encoding="utf-8")
    assert "прыжки" not in ass                                       # вырезанное слово
    assert "0:00:03.50" in ass                                       # «да» 7,0 → 3,5 в клипе
    assert "0:00:01.00" in ass                                       # «ну» 2,0 → 1,0


# ---------- сжать паузы ----------

def test_pause_cuts_synthetic():
    words = [{"s": 0.0, "e": 1.0, "w": "а"}, {"s": 1.5, "e": 2.0, "w": "б"},      # пауза 0,5 — остаётся
             {"s": 5.0, "e": 5.5, "w": "в"},                                       # пауза 3 — режем
             {"s": 9.0, "e": 9.5, "w": "г"}]                                       # пауза 3,5, но там смех
    cuts = autoclip.pause_cuts(0, 10, words, 1.5, 0.3, voice=[(6.0, 8.0)])
    assert cuts == [[2.3, 4.7]]
    left = autoclip.keep_pieces(0, 10, cuts)
    assert sum(b - a for a, b in left) == pytest.approx(10 - 2.4)
    # без смеха — обе паузы
    assert autoclip.pause_cuts(0, 10, words, 1.5, 0.3) == [[2.3, 4.7], [5.8, 8.7]]
    assert autoclip.pause_cuts(0, 10, words, 4.0, 0.3) == []


def test_merge_cuts():
    assert autoclip.merge_cuts([[5, 6], [1, 2], [1.5, 3]]) == [[1, 3], [5, 6]]


# ---------- разбить ----------

def test_split_point_not_inside_word():
    words = [{"s": 0.5, "e": 4.0, "w": "длинное"}, {"s": 4.6, "e": 6.0, "w": "слово"}]
    t = autoclip.split_point(2.0, 0, 10, words)
    assert 4.0 <= t <= 4.6                                           # в паузе, а не посреди слова
    assert autoclip.split_point(5.0, 0, 10, words) == pytest.approx(4.45)   # ближе к краю паузы
    assert autoclip.split_point(5.0, 0, 10, words[:1]) is None             # пауз нет — не разбить


def _project(tmp_path):
    dur = 40
    v = tmp_path / "запись.mp4"
    audio = f"aevalsrc='0.03*sin(2*PI*300*t)*(1+25*between(mod(t,20),10,12))':s=48000:d={dur}"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=s=270x480:r=30:d={dur}", "-f", "lavfi", "-i", audio,
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                    str(v)], check=True)
    segs = [{"s": t, "e": t + 2.4, "text": "ну вот смотри сюда",
             "words": [{"s": t + i * 0.6, "e": t + i * 0.6 + 0.5, "w": w}
                       for i, w in enumerate(["ну", "вот", "смотри", "сюда"])]}
            for t in range(0, dur, 4)]
    with open(tmp_path / "запись.transcript.json", "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False)
    autoclip.CONFIG.update(llm="none", clips=1, hook=False, max_silence_share=1.0)
    return autoclip.process(str(v))


def test_split_and_cuts_survive_rebuild(tmp_path, fake_trash):
    cut = _project(tmp_path)
    proj = autoclip.load_project(cut)
    c = proj["clips"][0]
    s, e = c["start"], c["end"]
    # вырезка переживает сдвиг границ
    mid = round((s + e) / 2, 1)
    autoclip.rebuild_clip(cut, c["id"], overrides={"cuts": [[mid, mid + 1.0]]})
    c1 = autoclip.find_clip(autoclip.load_project(cut), c["id"])
    assert abs(_dur(os.path.join(cut, c1["file"])) - (e - s - 1.0)) < 0.2
    autoclip.rebuild_clip(cut, c["id"], start=s + 0.5)
    c1 = autoclip.find_clip(autoclip.load_project(cut), c["id"])
    assert c1["overrides"]["cuts"] == [[mid, mid + 1.0]]
    assert abs(_dur(os.path.join(cut, c1["file"])) - (e - s - 1.5)) < 0.2
    # сбросить вырезки
    autoclip.rebuild_clip(cut, c["id"], overrides={"cuts": None})
    c1 = autoclip.find_clip(autoclip.load_project(cut), c["id"])
    assert "cuts" not in c1["overrides"]

    # разбить: два клипа, граница не внутри слова
    words = autoclip.all_words(autoclip.load_segments(autoclip.load_project(cut)))
    first, second = autoclip.split_clip(cut, c["id"], (c1["start"] + c1["end"]) / 2)
    assert first["end"] == pytest.approx(second["start"])
    assert not any(w["s"] + 0.01 < first["end"] < w["e"] - 0.01 for w in words)
    proj = autoclip.load_project(cut)
    assert len(proj["clips"]) == 2 and second["origin"] == "split"
    for x in proj["clips"]:
        assert os.path.isfile(os.path.join(cut, x["file"]))
    with pytest.raises(autoclip.AutoClipError):
        autoclip.split_clip(cut, first["id"], first["start"] + 1.0)   # часть короче 3 с


# ---------- редактор ----------

def test_editor_cut_squeeze_split(tmp_path, fake_trash, monkeypatch):
    import sys
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from qtwait import pump
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", lambda m: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda p, t, text, *a, **k: (_ for _ in ()).throw(AssertionError(text)))
    cut = _project(tmp_path)
    import app as A
    A.dark_palette(QApplication.instance() or QApplication([]))
    win = A.MainWindow()
    win.show()
    page = win.clips
    page.load(cut)
    c = page.current_clip()
    pos = {"t": 0.0}
    monkeypatch.setattr(page.player.player, "position", lambda: int(pos["t"] * 1000))

    def wait():
        for _ in range(1200):
            if not page.busy:
                return
            pump(50)

    # вырезать кусок 2–4 с клипа
    pos["t"] = 2.0
    page.cut_mark(0)
    pos["t"] = 4.0
    page.cut_mark(1)
    assert page.btn_cut.isEnabled()
    page.cut_piece()
    assert page.pending() == {"cuts": [[round(c["start"] + 2, 2), round(c["start"] + 4, 2)]]}
    assert "вырезано 2.0" in page.e_len.text()
    page.rebuild()
    wait()
    c1 = autoclip.find_clip(autoclip.load_project(cut), c["id"])
    assert abs(_dur(os.path.join(cut, c1["file"])) - (c["end"] - c["start"] - 2)) < 0.2
    assert not page.pending()
    # место просмотра после вырезки — по склеенному времени
    pos["t"] = 3.0
    assert page.rec_at_player(c1) == pytest.approx(c["start"] + 5.0, abs=0.05)

    # сжать паузы: предпросмотр и применение (в синтетике паузы по 1,6 с)
    page.pause_len.setValue(1.0)
    assert "короче" in page.pause_info.text() or "нет" in page.pause_info.text()
    # сбросить вырезки
    page.cuts_reset()
    assert page.pending() == {"cuts": []}
    page.fill_editor(page.current_clip())

    # разбить
    pos["t"] = (c1["end"] - c1["start"] - 2) / 2
    page.split_here()
    wait()
    proj = autoclip.load_project(cut)
    assert len(proj["clips"]) == 2
    win.close()
