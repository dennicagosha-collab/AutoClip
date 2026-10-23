"""Режимы сборки: на полную (несколько клипов сразу), фоновый (тихо), авто; остановка."""
import json
import os
import subprocess
import threading

import pytest

import autoclip


def test_resolve_build_mode():
    r = autoclip.resolve_build_mode
    assert r("full")[0] == "full" and r("background")[0] == "background"
    assert r("auto", procs=["explorer.exe"], fullscreen="")[0] == "full"
    mode, why = r("auto", procs=["Explorer.exe", "OBS64.EXE"], fullscreen="")
    assert mode == "background" and "obs64.exe" in why
    autoclip.CONFIG["game_processes"] = "bg3, Cyberpunk2077.exe"
    assert r("auto", procs=["bg3.exe"], fullscreen="")[0] == "background"
    assert r("auto", procs=["cyberpunk2077.exe"], fullscreen="")[0] == "background"
    assert r("auto", procs=["chrome.exe"], fullscreen="game.exe") == ("background",
                                                                     "на весь экран: game.exe")


def _video(tmp_path, dur=90):
    v = tmp_path / "запись.mp4"
    audio = f"aevalsrc='0.03*sin(2*PI*300*t)*(1+25*between(mod(t,30),10,12))':s=48000:d={dur}"
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
    return v


def test_parallel_build_same_clips(tmp_path, fake_trash):
    autoclip.CONFIG.update(llm="none", clips=3, hook=False, clips_mode="count")
    video = _video(tmp_path)
    autoclip.CONFIG.update(build_mode="background")
    seq = autoclip.load_project(autoclip.process(str(video)))
    autoclip.CONFIG.update(build_mode="full", parallel_clips=3)
    par = autoclip.load_project(autoclip.process(str(video)))
    key = [(c["num"], c["start"], c["end"], c["file"]) for c in seq["clips"]]
    assert key == [(c["num"], c["start"], c["end"], c["file"]) for c in par["clips"]]
    assert [c["num"] for c in par["clips"]] == [1, 2, 3]
    folder = os.path.dirname(par["_path"])
    assert all(os.path.getsize(os.path.join(folder, c["file"])) > 1000 for c in par["clips"])


def test_background_lowers_priority(tmp_path, fake_trash, monkeypatch):
    autoclip.CONFIG.update(llm="none", clips=1, hook=False, clips_mode="count",
                           build_mode="background")
    seen = []
    real = autoclip.render_clip
    monkeypatch.setattr(autoclip, "render_clip",
                        lambda *a, **k: seen.append(autoclip._flags()) or real(*a, **k))
    autoclip.process(str(_video(tmp_path)))
    if os.name == "nt":
        assert seen and all(f & autoclip._LOW_PRIORITY for f in seen)
    assert autoclip._proc_priority == 0                       # после нарезки — как было


def test_cancel_stops_all_parallel_ffmpeg(tmp_path, fake_trash, monkeypatch):
    autoclip.CONFIG.update(llm="none", clips=3, hook=False, clips_mode="count",
                           build_mode="full", parallel_clips=3)
    video = _video(tmp_path)
    cancel = threading.Event()
    procs = []
    real_popen = subprocess.Popen

    def popen(cmd, *a, **k):
        p = real_popen(cmd, *a, **k)
        if cmd and cmd[0] == "ffmpeg" and "-filter_complex" in cmd:
            procs.append(p)
            if len(procs) >= 2:                   # два клипа собираются — жмём «Остановить»
                cancel.set()
        return p
    monkeypatch.setattr(subprocess, "Popen", popen)
    with pytest.raises(autoclip.Cancelled):
        autoclip.process(str(video), cancel=cancel)
    assert len(procs) >= 2
    assert all(p.poll() is not None for p in procs)          # ни один ffmpeg не остался
