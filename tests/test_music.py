"""Музыка в клип из своих файлов: громкость к голосу, края, нужный отрезок трека."""
import os
import subprocess

import numpy as np
import pytest

import autoclip


def _tone(path, freq, dur, vol=0.5):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:sample_rate=48000:duration={dur}", "-af", f"volume={vol}",
                    str(path)], check=True)
    return str(path)


def _video(tmp_path, dur=20):
    """Голос — 300 Гц, ровно и громко."""
    v = tmp_path / "запись.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=black:s=270x480:r=30:d={dur}",
                    "-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=48000:duration={dur}",
                    "-af", "volume=0.5", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", str(v)], check=True)
    return str(v)


def _audio(path):
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "8000",
                        "-f", "s16le", "-"], capture_output=True)
    return np.frombuffer(p.stdout, np.int16).astype(np.float32) / 32768


def _band(x, f, rate=8000):
    """Сила частоты f в сигнале (по спектру)."""
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1 / rate)
    i = np.argmin(np.abs(freqs - f))
    return spec[max(0, i - 3):i + 4].max()


def _render(tmp_path, music, words=(), bleep=False):
    video = _video(tmp_path)
    vinfo = autoclip.probe(video)
    segs = [{"s": 0, "e": 20, "text": "", "words": list(words)}] if words else []
    out = str(tmp_path / "клип.mp4")
    work = tmp_path / "w"
    work.mkdir(exist_ok=True)
    cfg = dict(autoclip.CONFIG, zoom=False, subs=False, nick=False, bleep=bleep, music=music)
    assert autoclip.render_clip(video, {"s": 2.0, "e": 14.0, "zooms": [], "hook": None}, segs, vinfo,
                                out, str(work), cfg) is not None
    return out


def test_music_quieter_than_voice_with_soft_edges(tmp_path):
    track = _tone(tmp_path / "трек.mp3", 1000, 30)
    out = _render(tmp_path, {"file": track, "offset": 0, "volume": -18, "duck": False, "fade": 1.0})
    x = _audio(out)
    mid = x[4 * 8000:8 * 8000]
    voice, music = _band(mid, 300), _band(mid, 1000)
    assert music > 0 and voice > music * 4                      # музыка есть, голос громче
    ratio_db = 20 * np.log10(voice / music)
    assert 12 < ratio_db < 24                                    # около −18 дБ к голосу
    start, end = _band(x[:int(0.25 * 8000)], 1000), _band(x[-int(0.25 * 8000):], 1000)
    assert start < music * 0.5 and end < music * 0.5             # плавное появление и затухание


def test_music_segment_matches_choice(tmp_path):
    # трек: первые 10 с — 600 Гц, дальше — 1500 Гц; выбран кусок с 12-й секунды
    a = _tone(tmp_path / "a.wav", 600, 10)
    b = _tone(tmp_path / "b.wav", 1500, 30)
    track = str(tmp_path / "трек.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", a, "-i", b, "-filter_complex",
                    "[0:a][1:a]concat=n=2:v=0:a=1", track], check=True)
    out = _render(tmp_path, {"file": track, "offset": 12.0, "volume": -10, "duck": False, "fade": 0.5})
    mid = _audio(out)[3 * 8000:9 * 8000]
    assert _band(mid, 1500) > 5 * _band(mid, 600)                # звучит выбранный кусок


def test_duck_under_speech_and_silence_under_bleep(tmp_path):
    track = _tone(tmp_path / "трек.mp3", 1000, 30)
    words = [{"s": 7.0, "e": 7.6, "w": "вот"}, {"s": 7.7, "e": 8.3, "w": "это"},
             {"s": 11.0, "e": 11.6, "w": "блять"}]
    music = {"file": track, "offset": 0, "volume": -18, "duck": True, "fade": 0.5}
    out = _render(tmp_path, music, words, bleep=True)
    x = _audio(out)
    seg = lambda a, b: _band(x[int(a * 8000):int(b * 8000)], 1000)   # noqa: E731
    quiet, talk, mat = seg(1.5, 1.8), seg(5.4, 5.7), seg(9.15, 9.45)   # окна одной длины
    assert talk < quiet * 0.6                                    # под речью музыка тише
    assert mat > quiet * 0.15                                    # под матом — не провал в тишину,
    assert mat < quiet * 0.6 and 0.5 < mat / talk < 2            # а приглушена, как под речью


def test_no_music_by_default_and_missing_file(tmp_path):
    assert autoclip.CONFIG.get("music") is None
    assert autoclip.check_music({"file": str(tmp_path / "нет.mp3")}) is None
    assert autoclip.check_music(None) is None


def test_list_music_and_waveform(tmp_path):
    d = tmp_path / "Музыка"
    (d / "rock").mkdir(parents=True)
    _tone(d / "Летний Вечер.mp3", 440, 3)
    _tone(d / "rock" / "Гром.wav", 220, 2)
    (d / "обложка.jpg").write_bytes(b"x")
    names = [os.path.basename(p) for p in autoclip.list_music(str(d))]
    assert names == ["Гром.wav", "Летний Вечер.mp3"]
    assert [os.path.basename(p) for p in autoclip.list_music(str(d), "ЛЕТ")] == ["Летний Вечер.mp3"]
    peaks, dur = autoclip.waveform(str(d / "Летний Вечер.mp3"), 50)
    assert len(peaks) == 50 and max(peaks) == 1.0 and dur == pytest.approx(3.0, abs=0.1)


def test_weekly_with_one_track(tmp_path, fake_trash):
    clips = []
    for i in (1, 2):
        out = _render(tmp_path, None)
        dst = tmp_path / f"клип{i}.mp4"
        os.replace(out, dst)
        clips.append(str(dst))
    track = _tone(tmp_path / "трек.mp3", 1000, 60)
    res = autoclip.build_compilation(clips, "vertical", str(tmp_path / "подборка.mp4"),
                                     music={"file": track, "volume": -18, "fade": 1.0})
    x = _audio(res)
    mid = x[3 * 8000:6 * 8000]
    assert _band(mid, 1000) > 0 and _band(mid, 300) > _band(mid, 1000)


def test_music_tab(tmp_path, fake_trash, monkeypatch):
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
    video = _video(tmp_path, 40)
    segs = [{"s": t, "e": t + 2.4, "text": "", "words": [
        {"s": t + i * 0.6, "e": t + i * 0.6 + 0.5, "w": x} for i, x in enumerate(["ну", "вот", "смотри"])]}
        for t in range(0, 40, 4)]
    json.dump(segs, open(tmp_path / "запись.transcript.json", "w", encoding="utf-8"), ensure_ascii=False)
    autoclip.CONFIG.update(llm="none", clips=1, hook=False, clips_mode="count", min_len=10.0)
    cut = autoclip.process(video)
    mdir = tmp_path / "Музыка"
    mdir.mkdir()
    track = _tone(mdir / "Тихая.mp3", 1000, 60)
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    w = A.MainWindow()
    try:
        w.settings_page.music_dir.setText(str(mdir))
        page = w.clips
        page.load(cut)
        assert page.music is None and page.m_list.count() == 1          # по умолчанию без музыки
        page.set_track(page.m_list.item(0).data(0x0100))
        assert page.m_wave.dur == pytest.approx(60, abs=0.5) and "music" in page.pending()
        page.m_wave.set_window(page.clip_len(), 20.0)
        page._music_set(offset=20.0)
        page.m_vol.setValue(-12)
        page.listen_music()
        for _ in range(300):
            if page.m_listen.isEnabled():
                break
            pump(50)
        assert "Играет клип с музыкой" in page.m_state.text()
        page.rebuild()
        for _ in range(1200):
            if not page.busy:
                break
            pump(50)
        c = autoclip.load_project(cut)["clips"][0]
        m = c["overrides"]["music"]
        assert m["file"] == track and m["offset"] == 20.0 and m["volume"] == -12.0
        assert page.music == m and not page.pending()                    # пересборка помнит музыку
        page.set_track(None)
        page.rebuild()
        for _ in range(1200):
            if not page.busy:
                break
            pump(50)
        assert "music" not in autoclip.load_project(cut)["clips"][0]["overrides"]
    finally:
        w.close()
