"""Расшифровка: время слов по звуку, три дорожки OBS (микрофон и Discord отдельно), кэш."""
import json
import os
import subprocess

import pytest

import autoclip


def test_refine_moves_early_words_to_real_sound():
    words = [{"s": 1.0, "e": 1.5, "w": "я"}, {"s": 1.55, "e": 2.0, "w": "нажал"},
             {"s": 5.0, "e": 5.4, "w": "хороший"}]
    regions = [(1.35, 2.4), (5.3, 6.1)]              # речь звучит позже, чем думает Whisper
    got = autoclip.refine_words(words, regions)
    assert got[0]["s"] == 1.35                        # начало — к началу речи
    assert got[1]["s"] == 1.55                        # внутри речи — как было
    assert got[1]["e"] == 2.4                         # перед паузой — до конца речи
    assert got[2]["s"] == 5.3 and got[2]["e"] == 6.1
    assert autoclip.refine_words(words, []) == words  # нет данных о речи — не трогаем


def test_refine_never_overlaps_next_word():
    words = [{"s": 1.0, "e": 1.4, "w": "раз"}, {"s": 1.8, "e": 2.2, "w": "два"}]
    got = autoclip.refine_words(words, [(1.0, 3.0)])
    assert got[0]["e"] <= got[1]["s"] - 0.05 + 1e-9
    assert got[1]["e"] == 2.2 + 0.8 or got[1]["e"] == 3.0


def _three_tracks(tmp_path, dur=8):
    v = tmp_path / "три.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=black:s=270x480:r=30:d={dur}",
                    "-f", "lavfi", "-i", f"sine=f=300:d={dur}", "-f", "lavfi", "-i", f"sine=f=500:d={dur}",
                    "-f", "lavfi", "-i", f"sine=f=700:d={dur}", "-map", "0:v", "-map", "1:a", "-map", "2:a",
                    "-map", "3:a", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                    str(v)], check=True)
    return str(v)


def test_three_tracks_transcribed_separately(tmp_path, monkeypatch):
    video = _three_tracks(tmp_path)
    assert autoclip.audio_tracks(video) == 3
    seen = []

    def fake_asr(model, audio, vad, dur, spk, progress=None, cancel=None, part=(0, 1)):
        seen.append((spk, len(audio), vad["threshold"]))
        t = 1.0 if spk == "me" else 3.0
        word = "привет" if spk == "me" else "блять"
        return [{"s": t, "e": t + 0.5, "text": word, "spk": spk,
                 "words": [{"s": t, "e": t + 0.5, "w": word, "spk": spk}]}]
    monkeypatch.setattr(autoclip, "_load_whisper", lambda: None)
    monkeypatch.setattr(autoclip, "_asr", fake_asr)
    monkeypatch.setattr(autoclip, "speech_regions", lambda audio: [])
    segs, cache = autoclip.transcribe(video, 8.0, str(tmp_path))
    assert [x[0] for x in seen] == ["me", "team"]                      # дорожки 2 и 3 по очереди
    assert all(n == 8 * 16000 for _, n, _ in seen)
    assert [(sg["spk"], sg["words"][0]["w"]) for sg in segs] == [("me", "привет"), ("team", "блять")]
    data = json.load(open(cache, encoding="utf-8"))
    assert data["version"] == autoclip.ASR_VERSION and cache.endswith(".transcript.v2.json")
    assert [sg["text"] for sg in autoclip.speaker_segments(segs, "me")] == ["привет"]
    seen.clear()
    assert autoclip.transcribe(video, 8.0, str(tmp_path))[0] == segs and not seen   # из кэша


def test_old_cache_kept_and_refined(tmp_path, monkeypatch):
    video = _three_tracks(tmp_path)
    monkeypatch.setattr(autoclip, "audio_tracks", lambda v: 1)
    old = os.path.splitext(video)[0] + ".transcript.json"
    words = [{"s": 1.0, "e": 1.5, "w": "ну"}]
    json.dump([{"s": 1.0, "e": 1.5, "text": "ну", "words": words}], open(old, "w", encoding="utf-8"))
    before = open(old, encoding="utf-8").read()
    monkeypatch.setattr(autoclip, "speech_regions", lambda audio: [(1.3, 1.9)])
    monkeypatch.setattr(autoclip, "_load_whisper", lambda: (_ for _ in ()).throw(AssertionError("заново")))
    segs, cache = autoclip.transcribe(video, 8.0, str(tmp_path))
    assert segs[0]["words"][0]["s"] == 1.3                             # время уточнено по звуку
    assert open(old, encoding="utf-8").read() == before                # старый файл не тронут
    assert cache != old


def test_team_words_bleeped_but_not_subtitled(tmp_path):
    v = tmp_path / "в.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=270x480:r=30:d=8",
                    "-f", "lavfi", "-i", "sine=f=300:d=8", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(v)], check=True)
    segs = [{"s": 1, "e": 5, "text": "", "words": [
        {"s": 1.0, "e": 1.5, "w": "привет", "spk": "me"},
        {"s": 3.0, "e": 3.6, "w": "блять", "spk": "team"}]}]
    work = tmp_path / "w"
    work.mkdir()
    cfg = dict(autoclip.CONFIG, zoom=False, nick=False, subs=True, bleep=True, music=None)
    n = autoclip.render_clip(str(v), {"s": 0.0, "e": 6.0, "zooms": [], "hook": None}, segs,
                             autoclip.probe(str(v)), str(tmp_path / "к.mp4"), str(work), cfg)
    assert n == 1                                                      # мат тиммейта запикан
    ass = open(work / "subs.ass", encoding="utf-8-sig").read()
    events = ass.split("[Events]")[1].upper()
    assert "ПРИВЕТ" in events and "БЛЯ" not in events and "Б**" not in events   # тиммейта в субтитрах нет


# ---------- галлюцинации (3.7) ----------

def seg(s, e, *words):
    return {"s": s, "e": e, "text": " ".join(w for w, _, _ in words),
            "words": [{"s": a, "e": b, "w": w} for w, a, b in words]}


def test_hallucinations_dropped_whole():
    segs = [seg(3.75, 30.3, ("Субтитры", 3.75, 5.15), ("делал", 6.94, 8.34), ("DimaTorzok", 21.36, 30.3)),
            seg(81.6, 119.1, ("я", 81.6, 82.3), ("в", 87.7, 96.0), ("кахал", 100.7, 107.5)),
            seg(140.0, 142.0, ("есть", 140.0, 140.3), ("минусов", 140.3, 140.9), ("на", 141.0, 141.2)),
            seg(200.0, 204.0, ("ну", 200.0, 200.3), ("вот", 200.4, 200.8), ("ааа", 201.0, 204.0),
                ("да", 203.0, 203.3))]
    got = autoclip.drop_hallucinations(segs)
    assert [g["s"] for g in got] == [140.0, 200.0]                    # «титры» и растянутый кусок — прочь
    assert [w["w"] for w in got[1]["words"]] == ["ну", "вот", "да"]   # одно растянутое слово — только оно
    voice = [(140.0, 142.0)]                                          # голос есть только тут
    assert [g["s"] for g in autoclip.drop_hallucinations(segs, voice)] == [140.0]


def test_no_silent_clip_at_record_start():
    import numpy as np
    n = 200
    smooth = np.zeros(n)
    smooth[5] = 9.0                                                   # громко в начале — заставка игры
    smooth[120] = 3.0
    segs = [seg(110, 125, ("ну", 112.0, 112.4), ("смотри", 113.0, 113.5), ("сюда", 118.0, 118.4))]
    clips = autoclip.pick_clips(smooth, np.zeros(n), segs, [], 200.0)
    assert clips and all(c["s"] > 30 for c in clips)                  # шум первых секунд не взят
