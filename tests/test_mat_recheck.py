"""Второй проход по мату: на длинной записи Whisper пропускает «блядь» (запись 06.11 — в клипе
«Тест объяснил…» все пять), на коротком куске слышит. Куски клипов слушаются ещё раз."""
import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

import autoclip


def _seg(words, spk="me"):
    ws = [dict(w, spk=spk) for w in words]
    return {"s": ws[0]["s"], "e": ws[-1]["e"], "text": " ".join(w["w"] for w in ws), "words": ws, "spk": spk}


# как в записи 06.11: «запылили пиздец ибо» вместо «Блядь, запэрили! Пиздец! Ебан…»
OLD = [_seg([{"s": 39.46, "e": 40.13, "w": "запылили"}, {"s": 40.13, "e": 41.41, "w": "пиздец"},
             {"s": 41.41, "e": 42.19, "w": "ибо"}]),
       _seg([{"s": 40.0, "e": 40.5, "w": "даже"}], spk="team")]
FRESH = [_seg([{"s": 39.02, "e": 39.40, "w": "Блядь,"}, {"s": 39.45, "e": 40.06, "w": "запэрили!"},
               {"s": 40.98, "e": 41.50, "w": "Пиздец!"}, {"s": 41.88, "e": 42.30, "w": "Ебан..."}])]


def test_merge_takes_fresh_words_when_mat_was_missed():
    out, n = autoclip.mat_merge(OLD, FRESH, "me", 30.0, 50.0)
    me = [w["w"] for sg in out for w in sg["words"] if sg["spk"] == "me"]
    assert n == 2                                            # «Блядь» и «Ебан»; «пиздец» уже был
    assert me == ["Блядь,", "запэрили!", "Пиздец!", "Ебан..."]
    assert [w["w"] for sg in out for w in sg["words"] if sg["spk"] == "team"] == ["даже"]   # друг не тронут
    words = autoclip.all_words(out)
    assert sum(autoclip.is_profane(w["w"]) for w in words) == 3


def test_merge_keeps_old_when_nothing_missed():
    fresh = [_seg([{"s": 40.1, "e": 41.4, "w": "пиздец"}])]
    out, n = autoclip.mat_merge(OLD, fresh, "me", 30.0, 50.0)
    assert n == 0 and out is OLD


def test_merge_only_inside_piece():
    fresh = [_seg([{"s": 39.02, "e": 39.40, "w": "блядь"}, {"s": 55.0, "e": 55.4, "w": "сука"}])]
    out, n = autoclip.mat_merge(OLD, fresh, "me", 30.0, 50.0)
    assert n == 1 and "сука" not in [w["w"] for w in autoclip.all_words(out)]


def test_uncovered_parts():
    assert autoclip._uncovered([(10, 50)], []) == [[10.0, 50.0]]
    assert autoclip._uncovered([(10, 50)], [[0, 30]]) == [[30.0, 50.0]]
    assert autoclip._uncovered([(10, 50)], [[0, 20], [30, 60]]) == [[20.0, 30.0]]
    assert autoclip._uncovered([(10, 50)], [[0, 60]]) == []


class FakeModel:
    """Whisper на коротком куске: слышит «блядь» на 42-й секунде записи."""
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **kw):
        self.calls.append(len(audio) / 16000)
        lo = 42.0 - self.lo
        w = [NS(word=" Ну,", start=lo - 0.4, end=lo - 0.1), NS(word=" блядь,", start=lo, end=lo + 0.4)]
        return iter([NS(words=w, text="Ну, блядь,")]), None


@pytest.fixture
def setup(tmp_path, monkeypatch):
    video = tmp_path / "з.mp4"
    video.write_bytes(b"x")
    cache = tmp_path / "t.json"
    segs = [_seg([{"s": 41.6, "e": 41.9, "w": "ну"}])]
    cache.write_text(json.dumps({"version": 2, "segments": segs, "filled": True, "lang_checked": True}),
                     encoding="utf-8")
    model = FakeModel()
    monkeypatch.setattr(autoclip, "MAT_RECHECK", True)
    monkeypatch.setattr(autoclip, "probe", lambda v: {"dur": 600.0})
    monkeypatch.setattr(autoclip, "audio_tracks", lambda v: 1)
    monkeypatch.setattr(autoclip, "_load_whisper", lambda: model)
    import health
    monkeypatch.setattr(health, "free_whisper", lambda m: None)
    monkeypatch.setattr(autoclip, "speech_regions", lambda a: [])

    def cut(v, track, lo, hi, cancel=None):
        model.lo = lo
        return np.zeros(int((hi - lo) * 16000), dtype=np.float32)
    monkeypatch.setattr(autoclip, "_slice_audio", cut)
    return str(video), str(cache), segs, model


def test_recheck_finds_mat_and_remembers(setup):
    video, cache, segs, model = setup
    out = autoclip.mat_recheck(video, segs, cache, [(35.0, 60.0)])
    assert any(autoclip.is_profane(w["w"]) for w in autoclip.all_words(out))
    data = json.load(open(cache, encoding="utf-8"))
    assert data["mat_checked"] == [[27.0, 68.0]]             # клип ± MAT_PAD
    assert any(autoclip.is_profane(w["w"]) for w in autoclip.all_words(data["segments"]))
    assert data["filled"] and data["lang_checked"]           # остальное в кэше не потерялось
    assert all(c <= autoclip.MAT_PIECE + 2 * autoclip.MAT_OVERLAP for c in model.calls)
    n = len(model.calls)
    autoclip.mat_recheck(video, out, cache, [(40.0, 55.0)])  # уже проверено — второй раз не слушает
    assert len(model.calls) == n


def test_recheck_off_in_settings(setup, monkeypatch):
    video, cache, segs, model = setup
    proj = {"source": video, "transcript": cache}
    out = autoclip.recheck_clip_mat(proj, segs, 35.0, 60.0, {"bleep": False})
    assert out is segs and not model.calls


def test_recheck_without_whisper_keeps_clip(setup, monkeypatch):
    video, cache, segs, model = setup

    def fail():
        raise autoclip.AutoClipError("❌ Whisper не запустился.")
    monkeypatch.setattr(autoclip, "_load_whisper", fail)
    assert autoclip.mat_recheck(video, segs, cache, [(35.0, 60.0)]) is segs
