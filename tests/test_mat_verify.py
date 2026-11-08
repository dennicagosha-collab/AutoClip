"""0.2.1: края мата по голосу, склейка соседних мест, проверка готового клипа на слышный мат."""
import numpy as np

import autoclip
from test_bleep_voice import GAME, ME, _render, _seg, _tone, obs_video  # noqa: F401


def test_merged_spans_keep_the_longer_end():
    """Место, услышанное проверкой (длинное), и мат внутри него — вместе не короче длинного."""
    words = [{"s": 1.0, "e": 2.0, "w": "", "mat": True, "heard": True},
             {"s": 1.2, "e": 1.5, "w": "блять"}]
    spans = autoclip.bleep_spans(words, 5.0, 0.0)
    assert len(spans) == 1 and spans[0][0] == 1.0 and spans[0][1] >= 2.0


def test_widen_to_where_voice_stops(obs_video):
    """Whisper дал мату 1,5–2,9 с, а голос в микрофоне звучит до 3,0 — конец уходит к 3,0."""
    w = {"s": 1.5, "e": 2.9, "w": "блять", "spk": "me", "src": 1.5}
    autoclip.widen_mat(str(obs_video), [w], {"me": 1, "team": 2})
    assert w["s"] == 1.5                                 # голос и раньше — границы не видно, не трогаем
    assert 2.98 <= w["e"] <= 3.06
    hand = {"s": 1.5, "e": 2.9, "w": "", "mat": True, "src": 1.5, "added": True, "spk": "me"}
    autoclip.widen_mat(str(obs_video), [hand], {"me": 1})
    assert (hand["s"], hand["e"]) == (1.5, 2.9)          # отмечено руками — не трогаем


def _main_freq(x):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / 16000)[int(np.argmax(spec))])


def _fake_whisper(monkeypatch, heard, who=ME):
    """Whisper проверки: мат в heard слышит только на дорожке того, кто правда матерился
    (частота who; None — нигде)."""
    calls = {"n": 0}

    def words(model, audio):
        calls["n"] += 1
        if who is None or abs(_main_freq(audio) - who) > 50:
            return []
        return [dict(s=heard[0], e=heard[1], w="блять")]
    monkeypatch.setattr(autoclip, "MAT_VERIFY", True)
    monkeypatch.setattr(autoclip, "_verify_whisper", lambda: object())
    monkeypatch.setattr(autoclip, "_verify_words", words)
    return calls


def test_verify_closes_missed_mat(tmp_path, obs_video, monkeypatch, fake_trash):
    """Расшифровка мат пропустила — проверка готового клипа слышит мой голос и закрывает его."""
    _fake_whisper(monkeypatch, (2.0, 2.4))
    segs = [_seg("me", [(1.0, 1.4, "ну"), (2.5, 2.9, "вот")])]
    out, n, clip = _render(tmp_path, obs_video, segs)
    assert n == 1 and clip["mat_heard"] and clip["mat_heard"][0][2] == "me"
    a, b, _ = clip["mat_heard"][0]
    assert 1.9 <= a <= 2.05 and 2.35 <= b <= 2.5
    assert _tone(out, 0, ME, 2.1, 2.3) < 0.02 * _tone(out, 0, ME, 1.0, 1.3)       # мат убран
    assert _tone(out, 0, GAME, 2.1, 2.3) > 0.7 * _tone(out, 0, GAME, 3.5, 3.8)    # игра осталась
    assert _tone(out, 0, ME, 2.6, 2.85) > 0.7 * _tone(out, 0, ME, 1.0, 1.3)       # «вот» слышно


def test_verify_ignores_what_clean_track_does_not_confirm(tmp_path, obs_video, monkeypatch, fake_trash):
    """Whisper «послышался» мат (смех, шум), а на чистой дорожке его нет — клип не трогаем."""
    _fake_whisper(monkeypatch, (2.0, 2.4), who=None)
    out, n, clip = _render(tmp_path, obs_video, [_seg("me", [(1.0, 1.4, "ну")])])
    assert n == 0 and not clip.get("mat_heard")
    assert _tone(out, 0, ME, 2.1, 2.3) > 0.7 * _tone(out, 0, ME, 1.0, 1.3)


def test_verify_skips_already_closed(tmp_path, obs_video, monkeypatch, fake_trash):
    """Мат уже закрыт (голос убран), а Whisper всё равно «слышит» его по смыслу — не пересобираем."""
    _fake_whisper(monkeypatch, (1.6, 2.2))
    segs = [_seg("me", [(1.0, 1.4, "ну"), (1.6, 2.2, "блять"), (2.4, 2.9, "вот")])]
    out, n, clip = _render(tmp_path, obs_video, segs)
    assert n == 1 and not clip.get("mat_heard")


def test_heard_mat_from_game_mutes_all(tmp_path, obs_video, monkeypatch, fake_trash):
    """Мат в звуке игры (друзья в голосовом чате игры, не в Discord) — глушится всё в этом месте."""
    _fake_whisper(monkeypatch, (5.2, 5.6), GAME)             # после 5 с — только игра
    out, n, clip = _render(tmp_path, obs_video, [_seg("me", [(1.0, 1.4, "ну")])])
    assert clip["mat_heard"] and clip["mat_heard"][0][2] is None
    assert _tone(out, 0, GAME, 5.3, 5.5) < 0.02 * _tone(out, 0, GAME, 3.5, 3.8)


def test_add_heard_mats_maps_to_hook_and_body():
    tl = [(10.0, 11.0, 0.0, 0), (8.0, 14.0, 1.0, 1)]       # хук 10–11, потом клип 8–14
    w = autoclip.add_heard_mats([], [[10.2, 10.5, "me"]], tl)
    assert [(x["s"], x["e"]) for x in w] == [(0.2, 0.5), (3.2, 3.5)]
    assert all(x["heard"] and x["spk"] == "me" for x in w)


class _W:
    def __init__(self, s, e, w):
        self.start, self.end, self.word = s, e, w


class _Seg:
    def __init__(self, words):
        self.words = words


def test_verify_words_takes_time_from_middle_of_piece(monkeypatch):
    """У края куска Whisper ошибается во времени: из двух кусков берётся тот, где слово дальше
    от края. Два разных мата рядом не склеиваются в один."""
    monkeypatch.setattr(autoclip, "VERIFY_PIECE", 10.0)
    monkeypatch.setattr(autoclip, "VERIFY_OVERLAP", 5.0)
    said = {0: [(8.9, 9.3, "блять")],                        # кусок 0–10: у края, время сбито
            5: [(9.2, 9.6, "блять"), (10.2, 10.6, "сука")],  # кусок 5–15: в середине
            10: [(10.2, 10.6, "сука")]}
    seen = []

    class M:
        def transcribe(self, audio, **kw):
            i = [0, 5, 10][len(seen)]
            seen.append(i)
            return [_Seg([_W(a - i, b - i, w) for a, b, w in said[i]])], None
    got = autoclip._verify_words(M(), np.zeros(16000 * 20, dtype=np.float32))
    assert [(round(w["s"], 2), w["w"]) for w in got] == [(9.2, "блять"), (10.2, "сука")]


def test_out_lag_finds_shift(monkeypatch):
    """Звук готового клипа сдвинут на 3,5 мс — сдвиг находится, и голос узнаётся."""
    rng = np.random.default_rng(1)
    src = rng.standard_normal(16000 * 10).astype(np.float32)
    monkeypatch.setattr(autoclip, "_pcm", lambda path, track, start, dur, **k:
                        src[int(round(start * 16000)):int(round((start + dur) * 16000))])
    out = src[56:]                                           # клип на 56 отсчётов «раньше»
    assert abs(autoclip._out_lag(out, "x", 0.0, 10.0, 0.0) - 56 / 16000) < 1e-4
