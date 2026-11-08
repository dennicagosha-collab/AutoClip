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
    """Whisper проверки: в готовом клипе «слышит» мат в heard; на чистой дорожке — только если
    это дорожка того, кто правда матерился (частота who; None — нигде)."""
    calls = {"n": 0}

    def words(model, audio):
        calls["n"] += 1
        if len(audio) > 16000 * 4:                       # весь клип
            return [dict(s=heard[0], e=heard[1], w="блять")]
        if who is None or abs(_main_freq(audio) - who) > 50:
            return []
        return [dict(s=autoclip.CONFIRM_PAD, e=autoclip.CONFIRM_PAD + heard[1] - heard[0], w="блять")]
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
