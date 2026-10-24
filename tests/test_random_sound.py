"""Патч 3Б.6: «Случайный» звук на мат."""
import subprocess
import sys

import pytest

import autoclip


def test_sequence_no_repeat_and_fixed(monkeypatch):
    monkeypatch.setattr(autoclip, "list_sounds", lambda: ["а.wav", "б.wav", "в.wav", "тишина"])
    cfg = {"bleep_sound": autoclip.RANDOM_SOUND, "bleep_pool": []}
    seq = autoclip.bleep_sequence(cfg, 30, 7)
    assert all(x != y for x, y in zip(seq, seq[1:]))             # не два раза подряд
    assert set(seq) <= {"а.wav", "б.wav", "в.wav"}                # тишина в «Случайный» не идёт
    assert autoclip.bleep_sequence(cfg, 30, 7) == seq             # тот же клип — те же звуки
    assert autoclip.bleep_sequence(cfg, 30, 8) != seq             # «Перемешать» — другие
    cfg["bleep_pool"] = ["б.wav"]
    assert autoclip.bleep_sequence(cfg, 4, 7) == ["б.wav"] * 4    # один звук — повторяется
    assert autoclip.bleep_sequence({"bleep_sound": "буп"}, 3, 1) == ["буп"] * 3


def test_random_render_uses_two_sounds(tmp_path, monkeypatch):
    snd = tmp_path / "звуки"
    snd.mkdir()
    for name, f in (("высокий.wav", 2000), ("низкий.wav", 500)):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"sine=frequency={f}:sample_rate=48000:duration=0.6", "-ac", "2",
                        str(snd / name)], check=True)
    monkeypatch.setattr(autoclip, "SOUNDS_DIR", str(snd))
    v = tmp_path / "в.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=270x480:r=30:d=8",
                    "-f", "lavfi", "-i", "sine=f=300:d=8", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(v)], check=True)
    segs = [{"s": 1, "e": 6, "text": "", "words": [
        {"s": 1.0, "e": 1.5, "w": "сука"}, {"s": 3.0, "e": 3.5, "w": "блять"}, {"s": 5.0, "e": 5.5, "w": "сука"}]}]
    cfg = dict(autoclip.CONFIG, zoom="off", subs=False, nick=False, bleep=True, music=None, censor="full",
               bleep_sound=autoclip.RANDOM_SOUND, bleep_pool=["высокий.wav", "низкий.wav"])
    job = {"s": 0.0, "e": 7.0, "zooms": [], "hook": None, "peak": 3.0}
    work = tmp_path / "w"
    work.mkdir()
    out = tmp_path / "к.mp4"
    assert autoclip.render_clip(str(v), job, segs, autoclip.probe(str(v)), str(out), str(work), cfg) == 3
    seq = job["bleep_seq"]
    assert len(seq) == 3 and seq[0] != seq[1] and seq[1] != seq[2]
    job2 = dict(job)
    autoclip.render_clip(str(v), job2, segs, autoclip.probe(str(v)), str(out), str(work), cfg)
    assert job2["bleep_seq"] == seq                               # пересборка — те же звуки


def test_settings_pool_and_editor_shuffle(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    import app
    app.dark_palette(QApplication.instance() or QApplication([]))
    win = app.MainWindow()
    st = win.settings_page
    st.sound.setCurrentText(autoclip.RANDOM_SOUND)
    assert win.settings["sound"] == autoclip.RANDOM_SOUND
    assert not st.pool_row.isHidden()
    first = next(iter(st.pool_checks))
    st.pool_checks[first].setChecked(True)
    assert win.settings["bleep_pool"] == [first]
    win.cut.apply_config()
    assert autoclip.CONFIG["bleep_pool"] == [first]
    page = win.clips
    page.base = {"bleep_seed": None}
    page.bleep_seed = None
    page.shuffle_sounds()
    assert page.bleep_seed is not None
    assert page.pending() == {"bleep_seed": page.bleep_seed} or "bleep_seed" in page.pending()
    page.base = {}
    win.close()
