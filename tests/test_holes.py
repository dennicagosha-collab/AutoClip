"""ПАТЧ_4, 4.4: дослушать места, где голос есть, а Whisper слов не дал."""
import json
import os
from types import SimpleNamespace as NS

import numpy as np

import autoclip


def _seg(words):
    return {"s": words[0]["s"], "e": words[-1]["e"], "text": " ".join(w["w"] for w in words), "words": words}


def test_voice_holes_finds_uncovered_voice():
    segs = [_seg([{"s": 19.3, "e": 19.7, "w": "мы"}, {"s": 20.0, "e": 21.0, "w": "живём"}])]
    regions = [(16.6, 21.2), (30.0, 30.5), (40.0, 42.0)]
    holes = autoclip.voice_holes(segs, regions)
    assert holes[0][0] == 16.6 and 18.9 <= holes[0][1] <= 19.2       # вопрос перед «мы живём»
    assert (40.0, 42.0) in holes and all(b - a >= autoclip.HOLE_MIN for a, b in holes)


class FakeModel:
    """Whisper на куске: отдаёт вопрос (и слово, которое уже есть, — его брать нельзя)."""
    def transcribe(self, audio, **kw):
        w = [NS(word=" Инфернус,", start=1.1, end=1.6), NS(word=" дочь", start=1.7, end=2.2),
             NS(word=" родилась?", start=2.3, end=3.0), NS(word=" мы", start=4.2, end=4.6)]
        return iter([NS(words=w)]), None


def test_fill_holes_adds_lost_question():
    segs = [_seg([{"s": 19.3, "e": 19.7, "w": "мы"}, {"s": 20.0, "e": 21.0, "w": "живём"}])]
    regions = [(16.6, 21.2)]
    audio = np.zeros(16000 * 30, dtype=np.float32)
    out, n = autoclip.fill_holes(FakeModel(), audio, segs, "me", regions)
    got = [w["w"] for sg in out for w in sg["words"]]
    assert n == 3 and got[:3] == ["Инфернус,", "дочь", "родилась?"]
    assert got.count("мы") == 1                                         # не задвоили
    assert out[0].get("refilled")


def test_old_cache_filled_once(tmp_path, monkeypatch):
    video = tmp_path / "з.mp4"
    video.write_bytes(b"")
    new, _ = autoclip.cache_paths(str(video))
    os.makedirs(os.path.dirname(new), exist_ok=True)
    with open(new, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "segments": [_seg([{"s": 1.0, "e": 1.5, "w": "а"}])]}, f)
    calls = []
    monkeypatch.setattr(autoclip, "audio_tracks", lambda v: 1)
    monkeypatch.setattr(autoclip, "asr_audio", lambda *a, **k: "x.wav")
    monkeypatch.setattr(autoclip, "_read_wav", lambda p: np.zeros(16000, dtype=np.float32))
    monkeypatch.setattr(autoclip, "_fill_all", lambda segs, *a, **k: calls.append(1) or segs)
    autoclip.transcribe(str(video), 10.0, str(tmp_path))
    assert calls and autoclip._cache_filled(new)
    autoclip.transcribe(str(video), 10.0, str(tmp_path))
    assert len(calls) == 1                                              # второй раз — просто из кэша
