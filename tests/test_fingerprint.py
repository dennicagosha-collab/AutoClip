"""Патч 5.1: запись узнаётся по содержимому, а не по имени."""
import json
import os
import shutil
import sys

import autoclip


def _file(path, size=9 * 1024 * 1024, seed=1):
    import random
    rnd = random.Random(seed)
    with open(path, "wb") as f:
        f.write(bytes(rnd.getrandbits(8) for _ in range(1024)) * (size // 1024))
    return str(path)


def test_fingerprint_survives_rename(tmp_path):
    a = _file(tmp_path / "2026-10-24 02-08-08.mp4")
    fp = autoclip.fingerprint(a, dur=1898)
    b = str(tmp_path / "123123123.mp4")
    os.rename(a, b)
    assert autoclip.same_recording(autoclip.fingerprint(b, dur=1898), fp)
    other = _file(tmp_path / "другая.mp4", seed=2)
    assert not autoclip.same_recording(autoclip.fingerprint(other, dur=1898), fp)
    assert autoclip.find_recording(fp, [str(tmp_path)]) == b


def test_renamed_recording_finds_cache(tmp_path, monkeypatch):
    v = _file(tmp_path / "старое.mp4")
    fp = autoclip.fingerprint(v, dur=10)
    with open(tmp_path / "старое.transcript.v2.json", "w", encoding="utf-8") as f:
        json.dump({"version": 2, "segments": [], "filled": True, "lang_checked": True, "fp": fp}, f)
    new = str(tmp_path / "новое.mp4")
    os.rename(v, new)
    monkeypatch.setattr(autoclip, "probe", lambda p: {"dur": 10, "w": 2, "h": 2, "fps": 30})
    found, old = autoclip.find_cache(new)
    assert found and found.startswith(autoclip.CACHE_DIR) and old is None      # переехал в кэш-папку
    assert not (tmp_path / "старое.transcript.v2.json").exists()
    segs, path = autoclip.transcribe(new, 10.0, str(tmp_path))
    assert path == found                                    # Whisper не запускался — взят кэш


def test_renamed_recording_found_by_project(tmp_path, monkeypatch):
    v = _file(tmp_path / "старое.mp4")
    out = tmp_path / "старое_clips"
    out.mkdir()
    monkeypatch.setattr(autoclip, "probe", lambda p: {"dur": 10.0, "w": 2, "h": 2, "fps": 30})
    proj = autoclip.new_project(v, {"dur": 10.0, "w": 2, "h": 2, "fps": 30}, str(out), str(tmp_path / "t.json"))
    autoclip.save_project(proj)
    os.rename(v, tmp_path / "новое.mp4")
    assert autoclip.load_project(str(out))["source"] == str(tmp_path / "новое.mp4")
    # старая нарезка без отпечатка — по длительности и кадру
    proj = autoclip.load_project(str(out))
    proj.pop("source_fp")
    proj["source"] = str(tmp_path / "нет.mp4")
    autoclip.save_project(proj)
    assert autoclip.load_project(str(out))["source"] == str(tmp_path / "новое.mp4")


def test_golden_found_by_fingerprint(tmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    import golden_check
    v = _file(tmp_path / "123123123.mp4")
    meta = {"recording": "2026-10-24 02-08-08.mp4", "fingerprint": autoclip.fingerprint(v, dur=5)}
    assert golden_check.find_video(str(tmp_path), meta) == v
