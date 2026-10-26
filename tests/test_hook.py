"""Хук: решение, правило 5 (только из этого же клипа), склейка, пересборка."""
import json
import os
import random
import subprocess

import numpy as np
import pytest

import autoclip


def words_every(step, n, start=0.0):
    return [{"s": start + i * step, "e": start + i * step + step * 0.8, "w": "слово"}
            for i in range(n)]


@pytest.mark.parametrize("seed", range(300))
def test_hook_always_inside_clip(seed):
    rnd = random.Random(seed)
    n = 400
    reaction = np.array([rnd.uniform(-1, 4) for _ in range(n)])
    segs = [{"s": 0, "e": n, "text": "", "words": words_every(rnd.uniform(0.2, 1.5), 300)}]
    s = round(rnd.uniform(0, 300), 2)
    e = round(min(n, s + rnd.uniform(3, 60)), 2)
    h = autoclip.decide_hook(s, e, reaction, segs, threshold=1.0)
    if h["start"] is not None:
        assert s <= h["start"] < h["end"] <= e
        import story
        assert story.HOOK_MIN - 0.5 <= h["end"] - h["start"] <= story.HOOK_MAX + 0.5


def _phrase(start, text, step=0.4):
    ws = text.split()
    return [{"s": round(start + k * step, 2), "e": round(start + k * step + step - 0.05, 2), "w": w}
            for k, w in enumerate(ws)]


def test_culmination_in_middle_gets_hook():
    """Хук — кульминация: целая фраза у самого яркого места речи (5.9)."""
    r = np.zeros(100)
    r[40] = 3.0
    words = _phrase(30.0, "ну вот идём.") + _phrase(39.6, "яйцо нажал вместо хила,") + _phrase(46.0, "ладно.")
    h = autoclip.decide_hook(25.0, 50.0, r, [{"s": 30, "e": 47, "words": words}], peak=40)
    assert h["auto"] and h["start"] <= 39.6 and h["end"] >= 41.15 and 1.4 <= h["end"] - h["start"] <= 3.1
    assert "кульминация" in h["why"]


def test_no_speech_no_hook():
    r = np.full(100, 3.0)                       # громко, но никто не говорит — звук игры
    h = autoclip.decide_hook(25.0, 50.0, r, [], peak=40)
    assert not h["auto"] and "нет явной кульминации" in h["why"]


def test_clip_starting_with_culmination_gets_no_hook():
    r = np.zeros(100)
    r[27] = 3.0
    words = _phrase(25.2, "ну ты видел вообще?") + _phrase(35.0, "ладно пошли")
    h = autoclip.decide_hook(25.0, 50.0, r, [{"s": 25, "e": 36, "words": words}], peak=27)
    assert not h["auto"] and ("начинается" in h["why"] or "нет явной" in h["why"])


def test_voice_matters_more_than_game_noise():
    n = 60
    parts = {k: np.zeros(n) for k in ("громкость", "смех", "восклицания", "мат", "речь", "модель")}
    parts["громкость"][10] = 3.0                    # громко, но никто не говорит — игра
    parts["громкость"][30] = 2.0
    parts["речь"][30] = 0.3                         # громко и говорит — голос
    r = autoclip.reaction_curve(parts)
    assert r[30] > r[10]


def test_hook_window_snaps_to_words():
    words = [{"s": 39.3, "e": 39.9, "w": "ну"}, {"s": 40.6, "e": 41.2, "w": "ааа"}]
    hs, he = autoclip._hook_window(40, 25.0, 50.0, words)
    assert hs == pytest.approx(39.3 - autoclip.PAD_BEFORE)           # с запасом до первого слова
    assert 39.9 < he < 40.6 and he - hs <= autoclip.HOOK_MAX          # конец — в паузе, слово целое


def test_hook_never_cuts_words_and_keeps_padding():
    import random
    rnd = random.Random(5)
    for _ in range(300):
        t, words = 10.0, []
        while t < 40:
            d = rnd.uniform(0.15, 0.7)
            words.append({"s": round(t, 2), "e": round(t + d, 2), "w": "слово"})
            t += d + rnd.choice([0.05, 0.1, 0.2, 0.4, 0.9])
        i = rnd.randint(15, 35)
        hs, he = autoclip._hook_window(i, 10.0, 40.0, words)
        assert 10.0 <= hs < he <= 40.0 and he - hs <= autoclip.HOOK_MAX + 1e-6
        for w in words:
            assert not (w["s"] < hs < w["e"]) and not (w["s"] < he < w["e"])   # не режет слово


def _rec(start=10.0, end=30.0, auto=True, hs=20.0, he=21.5, override=None):
    rec = {"start": start, "end": end, "overrides": {},
           "hook": {"auto": auto, "start": hs, "end": he, "why": ""}}
    if override is not None:
        rec["overrides"]["hook"] = override
    return rec


def test_hook_span_rules():
    on, off = {"hook": True}, {"hook": False}
    assert autoclip.hook_span(_rec(), on) == (20.0, 21.5)
    assert autoclip.hook_span(_rec(), off) is None                       # общая галочка
    assert autoclip.hook_span(_rec(override=False), on) is None          # выключен у клипа
    assert autoclip.hook_span(_rec(auto=False, override=True), off) == (20.0, 21.5)
    assert autoclip.hook_span(_rec(auto=False), on) is None              # совет «не ставить»
    # правило 5: кусок вне клипа не ставится ни при каких настройках
    assert autoclip.hook_span(_rec(hs=5.0, he=6.5, override=True), on) is None
    assert autoclip.hook_span(_rec(hs=29.0, he=30.5, override=True), on) is None


def test_render_refuses_hook_outside_clip(tmp_path):
    with pytest.raises(autoclip.AutoClipError):
        autoclip.render_clip("x.mp4", {"s": 10, "e": 30, "zooms": [], "hook": (5, 6.5)}, [],
                             {"w": 1080, "h": 1920, "fps": 60}, str(tmp_path / "o.mp4"),
                             str(tmp_path))


def test_llm_spoiler_turns_hook_off(monkeypatch):
    monkeypatch.setattr(autoclip, "_ask_llm",
                        lambda *a, **k: '{"spoils": true, "reason": "видно развязку"}')
    assert autoclip.llm_hook_spoils("клип", "тизер", "ollama") == (True, "видно развязку")
    monkeypatch.setattr(autoclip, "_ask_llm", lambda *a, **k: "мусор")
    assert autoclip.llm_hook_spoils("клип", "тизер", "ollama") == (None, "")


# ---------- настоящий рендер ----------

def _make(tmp_path, dur=60):
    video = tmp_path / "запись.mp4"
    # громкий крик на 24–25 с, речь вокруг; testsrc2 — каждый кадр разный
    audio = f"aevalsrc='0.03*sin(2*PI*300*t)*(1+30*between(t,24,25.5))':s=48000:d={dur}"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=s=1080x1920:r=60:d={dur}", "-f", "lavfi", "-i", audio,
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                    str(video)], check=True)
    segs = [{"s": t, "e": t + 2.4, "text": "ну вот смотри сюда",
             "words": [{"s": t + i * 0.6, "e": t + i * 0.6 + 0.5, "w": w}
                       for i, w in enumerate(["ну", "вот", "смотри", "сюда"])]}
            for t in range(0, dur, 3)]
    with open(tmp_path / "запись.transcript.json", "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False)
    return video


def _frame(path, t, w=54, h=96):
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
                        "-frames:v", "1", "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo",
                        "-"], capture_output=True, check=True)
    return np.frombuffer(p.stdout, dtype=np.uint8).astype(float)


def _dur(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(p.stdout)


def test_hook_rendered_from_same_clip(tmp_path, fake_trash):
    video = _make(tmp_path)
    autoclip.CONFIG.update(llm="none", clips=1, subs=False, zoom=False, hook=True)
    out_dir = autoclip.process(str(video))
    proj = autoclip.load_project(out_dir)
    c = proj["clips"][0]
    h = c["hook"]
    assert h["on"], h
    assert c["start"] <= h["start"] < h["end"] <= c["end"]
    clip_file = os.path.join(out_dir, c["file"])
    hd = h["end"] - h["start"]
    assert abs(_dur(clip_file) - (hd + c["end"] - c["start"])) < 0.15

    # первые кадры — из момента хука, после склейки — начало клипа
    def diff(a, b):
        return float(np.abs(a - b).mean())
    first = _frame(clip_file, 0.1)
    assert diff(first, _frame(video, h["start"] + 0.1)) < 6
    assert diff(first, _frame(video, c["start"] + 0.1)) > diff(first, _frame(video, h["start"] + 0.1))
    after = _frame(clip_file, hd + 0.3)
    assert diff(after, _frame(video, c["start"] + 0.3)) < 6

    # хук выключен у клипа — длина как у самого клипа
    rec = autoclip.rebuild_clip(out_dir, c["id"], overrides={"hook": False})
    assert not rec["hook"]["on"]
    assert abs(_dur(clip_file) - (c["end"] - c["start"])) < 0.15

    # сдвиг начала: момент хука ищется внутри новых границ
    rec = autoclip.rebuild_clip(out_dir, c["id"], start=c["start"] + 4,
                                overrides={"hook": True})
    assert rec["hook"]["on"]
    assert rec["start"] <= rec["hook"]["start"] < rec["hook"]["end"] <= rec["end"]
    report = open(os.path.join(out_dir, "отчёт.txt"), encoding="utf-8").read()
    assert "хук:" in report


def test_hook_subtitles_end_at_cut(tmp_path):
    hd = 1.5
    words = [{"s": 0.2, "e": 0.6, "w": "куда", "part": 0, "until": hd},
             {"s": 0.7, "e": 1.4, "w": "его", "part": 0, "until": hd},
             {"s": hd + 1.5, "e": hd + 1.9, "w": "ну", "part": 1}]
    path = tmp_path / "s.ass"
    autoclip.build_ass(words, 1080, 1920, str(path))
    ends = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("Dialogue:") and ("КУДА" in line or "ЕГО" in line):
            h, m, sec = line.split(",")[2].split(":")
            ends.append(int(h) * 3600 + int(m) * 60 + float(sec))
    assert ends and max(ends) <= hd + 0.01


def test_manual_hook_in_editor(tmp_path, fake_trash, monkeypatch):
    import sys
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from qtwait import pump
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    video = _make(tmp_path)
    autoclip.CONFIG.update(llm="none", clips=1, subs=False, zoom=False, hook=True)
    cut = autoclip.process(str(video))
    import app as A
    qapp = QApplication.instance() or QApplication([])  # noqa: F841
    w = A.MainWindow()

    def wait():
        for _ in range(1200):
            if not w.clips.busy:
                return
            pump(50)
    try:
        page = w.clips
        page.load(cut)
        c = page.current_clip()
        assert page.hook_at and not page.pending()                       # автоматический — не правка
        hs, he = page.hook_at
        page.hook_shift(0, -0.25)
        page.hook_shift(1, 0.25)
        assert page.hook_at == [round(hs - 0.25, 2), round(he + 0.25, 2)] and "hook_at" in page.pending()
        page.rebuild()
        wait()
        c2 = autoclip.find_clip(autoclip.load_project(cut), c["id"])
        assert [c2["hook"]["start"], c2["hook"]["end"]] == page.hook_at and c2["hook"]["on"]
        assert c2["start"] <= c2["hook"]["start"] < c2["hook"]["end"] <= c2["end"]
        assert not page.pending()                                        # пересборка помнит
        for _ in range(40):
            page.hook_shift(0, -0.25)                                    # за начало клипа не уйти
        assert page.hook_at[0] >= c2["start"]
        page.player.player.setPosition(int((c2["end"] - c2["start"] - 4) * 1000))
        page.hook_here()
        assert c2["start"] <= page.hook_at[0] < page.hook_at[1] <= c2["end"]
    finally:
        monkeypatch.setattr(A, "ask_choice", lambda *a: "discard")     # правки не нужны — закрыть
        w.close()
