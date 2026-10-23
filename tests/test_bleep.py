"""Звук на мат не должен заезжать на соседние слова без мата."""
import subprocess

import numpy as np
import pytest

import autoclip


def _rms(path, a, b):
    """Громкость звука готового клипа на отрезке [a, b] секунд."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}",
                        "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                       capture_output=True, check=True)
    x = np.frombuffer(p.stdout, dtype=np.int16).astype(float) / 32768
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


@pytest.fixture
def silent_video(tmp_path):
    v = tmp_path / "тихо.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=s=270x480:r=30:d=6", "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=stereo", "-t", "6", "-c:v", "libx264",
                    "-preset", "ultrafast", "-c:a", "aac", str(v)], check=True)
    return v


@pytest.fixture
def long_sound(tmp_path):
    # свой звук пользователя длиннее слова — как «бумага.mp3»
    s = tmp_path / "длинный.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=1000:sample_rate=48000:duration=1.5", "-ac", "2", str(s)],
                   check=True)
    return s


def test_bleep_sound_stops_before_next_clean_word(tmp_path, silent_video, long_sound,
                                                  fake_trash):
    segs = [{"s": 1.0, "e": 2.4, "text": "блять ну вот", "words": [
        {"s": 1.0, "e": 1.4, "w": "блять"},
        {"s": 1.5, "e": 1.9, "w": "ну"},
        {"s": 2.0, "e": 2.4, "w": "вот"}]}]
    cfg = dict(autoclip.CONFIG, subs=False, zoom=False, bleep=True,
               bleep_sound=str(long_sound), preset="TikTok 1080p60")
    out = tmp_path / "клип.mp4"
    bl = autoclip.render_clip(str(silent_video), {"s": 0.0, "e": 5.0, "zooms": []}, segs,
                              {"w": 270, "h": 480, "fps": 30.0, "dur": 6.0}, str(out),
                              str(tmp_path), cfg)
    assert bl == 1
    assert _rms(out, 1.05, 1.35) > 0.05           # на мате звук есть
    assert _rms(out, 1.52, 1.9) < 0.005           # на «ну» его уже нет
    assert _rms(out, 2.0, 2.4) < 0.005


def test_bleep_spans_respect_neighbours():
    words = [{"s": 0.5, "e": 0.98, "w": "ну"},
             {"s": 1.0, "e": 1.4, "w": "сука"},
             {"s": 1.42, "e": 1.8, "w": "вот"},
             {"s": 3.0, "e": 3.3, "w": "блять"}]
    spans = autoclip.bleep_spans(words, total=5.0, pad=0.06)
    assert len(spans) == 2
    (a1, b1, until1), (a2, b2, until2) = spans
    assert a1 >= 0.98 and b1 <= 1.42 and until1 <= 1.42   # не трогает «ну» и «вот»
    assert a2 == pytest.approx(2.94) and b2 == pytest.approx(3.36)
    assert until2 == 5.0                                  # дальше слов нет — до конца клипа


@pytest.mark.parametrize("voice_vol", [0.05, 0.5])
def test_bleep_matches_voice_loudness(tmp_path, voice_vol):
    """Звук на мат — на уровне речи рядом (±2 дБ), и для тихого голоса, и для громкого."""
    autoclip.prepare_sounds()
    v = tmp_path / f"голос{voice_vol}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=270x480:r=30:d=12",
                    "-f", "lavfi", "-i", "anoisesrc=color=pink:sample_rate=48000:duration=12",
                    "-af", f"bandpass=f=900:width_type=o:w=2,volume={voice_vol}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(v)], check=True)
    words = [{"s": 2.0 + i, "e": 2.8 + i, "w": w} for i, w in enumerate(["ну", "вот", "блять", "так", "да"])]
    segs = [{"s": 2.0, "e": 7.0, "text": "", "words": words}]
    out = str(tmp_path / "клип.mp4")
    cfg = dict(autoclip.CONFIG, zoom=False, subs=False, nick=False, bleep=True, bleep_sound="бип",
               bleep_pad=0.0, music=None)
    work = tmp_path / "w"
    work.mkdir()
    assert autoclip.render_clip(str(v), {"s": 0.0, "e": 10.0, "zooms": [], "hook": None}, segs,
                                autoclip.probe(str(v)), out, str(work), cfg) == 1
    speech = autoclip.loudness(out, 2.0, 1.8)
    beep = autoclip.loudness(out, 4.05, 0.7)
    assert speech is not None and beep is not None
    assert abs(beep - speech) <= 2.0, (beep, speech)


def test_manual_bleep_add_and_remove(tmp_path):
    """«Запикать здесь» — слово, которого нет в расшифровке; «Убрать писк» — ошибочный."""
    v = tmp_path / "в.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=270x480:r=30:d=12",
                    "-f", "lavfi", "-i", "sine=f=300:d=12", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(v)], check=True)
    segs = [{"s": 2, "e": 8, "text": "", "words": [
        {"s": 2.0, "e": 2.5, "w": "ну"}, {"s": 4.0, "e": 4.5, "w": "сука"}, {"s": 6.0, "e": 6.5, "w": "да"}]}]
    vi = autoclip.probe(str(v))
    clip = {"s": 1.0, "e": 9.0, "zooms": [], "hook": None}

    def render(**over):
        work = tmp_path / f"w{len(over)}{sorted(over)}"
        work.mkdir()
        cfg = dict(autoclip.CONFIG, zoom=False, subs=False, nick=False, bleep=True, music=None, **over)
        return autoclip.render_clip(str(v), clip, segs, vi, str(tmp_path / "к.mp4"), str(work), cfg)
    assert render() == 1                                              # «сука» — по фильтру
    assert render(bleep_remove=[4.0]) == 0                            # сняли ошибочный писк
    assert render(bleep_add=[[7.0, 7.4]]) == 2                        # добавили пропущенный
    assert render(bleep_add=[[7.0, 7.4]], bleep_remove=[4.0]) == 1
    words = autoclip.mark_manual_bleeps(
        [dict(w, src=w["s"] + 1) for w in autoclip.clip_words(segs, 1.0, 9.0)],
        {"bleep_add": [[7.0, 7.4]]}, 1.0, 9.0, None, 0.0)
    added = [w for w in words if w.get("mat") and not w["w"]]
    assert [(w["s"], w["e"]) for w in added] == [(6.0, 6.4)]          # в клипе — от его начала


def test_manual_bleep_in_editor(tmp_path, fake_trash, monkeypatch):
    import json
    import sys
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from qtwait import pump
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    v = tmp_path / "запись.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=270x480:r=30:d=40",
                    "-f", "lavfi", "-i", "sine=f=300:d=40", "-af", "volume='1+20*between(mod(t,20),10,12)':eval=frame",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(v)], check=True)
    segs = [{"s": t, "e": t + 2.4, "text": "", "words": [
        {"s": t + i * 0.6, "e": t + i * 0.6 + 0.5, "w": x} for i, x in enumerate(["ну", "сука", "смотри"])]}
        for t in range(0, 40, 4)]
    json.dump(segs, open(tmp_path / "запись.transcript.json", "w", encoding="utf-8"), ensure_ascii=False)
    autoclip.CONFIG.update(llm="none", clips=1, hook=False, clips_mode="count", min_len=10.0)
    cut = autoclip.process(str(v))
    import app as A
    qapp = QApplication.instance() or QApplication([])  # noqa: F841
    w = A.MainWindow()
    try:
        page = w.clips
        page.load(cut)
        c = page.current_clip()
        n = page.e_bleeps.count()
        assert n >= 1 and "по фильтру" in page.e_bleeps.itemText(0)
        page.e_bleeps.setCurrentIndex(0)
        page.bleep_toggle()                                          # убрать писк
        assert "писк снят" in page.e_bleeps.itemText(0) and "bleep_remove" in page.pending()
        page.player.player.setPosition(3000)
        page.bleep_here()
        assert page.b_add and "вручную" in page.e_bleeps.itemText(page.e_bleeps.count() - 1)
        page.rebuild()
        for _ in range(1200):
            if not page.busy:
                break
            pump(50)
        got = autoclip.find_clip(autoclip.load_project(cut), c["id"])["overrides"]
        assert len(got["bleep_remove"]) == 1 and len(got["bleep_add"]) == 1
        assert not page.pending()                                    # пересборка помнит
    finally:
        w.close()
