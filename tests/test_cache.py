"""Патч 5.13: кэш расшифровки — в %APPDATA%\AutoClip\кэш, не в папке записей."""
import json
import os
import time

import autoclip


def _rec(tmp_path, name="запись.mp4"):
    d = tmp_path / "Записи"
    d.mkdir(exist_ok=True)
    v = d / name
    v.write_bytes(os.urandom(4096))
    return v


def test_legacy_cache_moved_and_old_project_follows(tmp_path):
    v = _rec(tmp_path)
    v1 = v.with_suffix("").as_posix() + ".transcript.json"
    with open(v1, "w", encoding="utf-8") as f:
        json.dump([{"s": 1, "e": 2, "text": "ну", "words": [{"s": 1, "e": 1.5, "w": "ну"}]}], f)
    n = autoclip.move_legacy_caches([str(v.parent)])
    assert n == 1 and not os.path.exists(v1)
    assert [x for x in os.listdir(v.parent)] == ["запись.mp4"]          # в папке записей — только видео
    proj = {"_path": str(tmp_path / "x" / "project.json"), "transcript": v1}
    segs = autoclip.load_segments(proj)
    assert segs and proj["transcript"].startswith(autoclip.CACHE_DIR)  # прежняя нарезка нашла кэш


def test_unused_cache_cleaned():
    os.makedirs(autoclip.CACHE_DIR, exist_ok=True)
    old = os.path.join(autoclip.CACHE_DIR, "a.transcript.v2.json")
    new = os.path.join(autoclip.CACHE_DIR, "b.transcript.v2.json")
    for p in (old, new):
        with open(p, "w") as f:
            f.write("{}")
    t = time.time()
    os.utime(old, (t - 31 * 86400, t - 31 * 86400))
    assert autoclip.clean_cache(30, now=t) == 1
    assert not os.path.exists(old) and os.path.exists(new)
