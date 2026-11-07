"""0.1.9: мат глушится только на голосе того, кто сматерился (микрофон или Discord), игра и второй
человек остаются слышны; звук на мат не длиннее закрытого места; время мата сужается по голосу."""
import subprocess

import numpy as np
import pytest

import autoclip

GAME, ME, TEAM = 300, 1000, 2500          # «игра», «мой голос», «друг» — разные частоты


def _tone(path, a, b, t0, t1):
    """Сила частоты f (Гц) в звуке клипа на отрезке [t0, t1]."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", str(path),
                        "-map", f"0:a:{a}", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                       capture_output=True, check=True)
    x = np.frombuffer(p.stdout, dtype=np.float32)
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    fr = np.fft.rfftfreq(len(x), 1 / 16000)
    return float(spec[np.abs(fr - b) < 30].max() / len(x))


@pytest.fixture
def obs_video(tmp_path):
    """Как запись OBS: дорожка 1 — всё вместе, 2 — мой микрофон, 3 — Discord.
    Мой голос звучит 1–3 с, друг — 1–5 с, игра — всё время."""
    v = tmp_path / "obs.mp4"
    me = f"sine=frequency={ME}:sample_rate=48000:duration=6,volume=enable='between(t,1,3)':volume=1,volume=enable='not(between(t,1,3))':volume=0"
    team = f"sine=frequency={TEAM}:sample_rate=48000:duration=6,volume=enable='not(between(t,1,5))':volume=0"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=270x480:r=30:d=6",
                    "-f", "lavfi", "-i", f"sine=frequency={GAME}:sample_rate=48000:duration=6",
                    "-f", "lavfi", "-i", me, "-f", "lavfi", "-i", team,
                    "-filter_complex",
                    "[1:a]volume=0.2,asplit=1[g];[2:a]volume=0.2,asplit=2[m1][m2];[3:a]volume=0.2,asplit=2[t1][t2];"
                    "[g][m1][t1]amix=inputs=3:normalize=0,aformat=channel_layouts=stereo[mix];"
                    "[m2]aformat=channel_layouts=stereo[mic];[t2]aformat=channel_layouts=stereo[dis]",
                    "-map", "0:v", "-map", "[mix]", "-map", "[mic]", "-map", "[dis]",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "320k", "-t", "6", str(v)],
                   check=True)
    return v


def _render(tmp_path, video, segs, name="клип.mp4"):
    cfg = dict(autoclip.CONFIG, subs=False, zoom=False, bleep=True, bleep_sound="тишина",
               preset="Вертикальный 1080×1920", censor="full")
    out = tmp_path / name
    clip = {"s": 0.0, "e": 6.0, "zooms": []}
    n = autoclip.render_clip(str(video), clip, segs, {"w": 270, "h": 480, "fps": 30.0, "dur": 6.0},
                             str(out), str(tmp_path), cfg)
    return out, n, clip


def _seg(spk, words):
    return {"s": words[0][0], "e": words[-1][1], "spk": spk, "text": " ".join(w for _, _, w in words),
            "words": [{"s": a, "e": b, "w": w, "spk": spk} for a, b, w in words]}


def test_mat_from_mic_mutes_only_mic(tmp_path, obs_video, fake_trash):
    segs = [_seg("me", [(1.0, 1.4, "ну"), (1.6, 2.2, "блять"), (2.4, 2.9, "вот")])]
    out, n, clip = _render(tmp_path, obs_video, segs)
    assert n == 1 and clip["bleep_voice"] == 1
    assert _tone(out, 0, ME, 1.75, 2.05) < 0.02 * _tone(out, 0, ME, 1.0, 1.3)    # мой мат убран
    assert _tone(out, 0, GAME, 1.75, 2.05) > 0.7 * _tone(out, 0, GAME, 3.5, 3.8)  # игра осталась
    assert _tone(out, 0, TEAM, 1.75, 2.05) > 0.7 * _tone(out, 0, TEAM, 3.5, 3.8)  # друг — тоже
    assert _tone(out, 0, ME, 2.45, 2.85) > 0.7 * _tone(out, 0, ME, 1.0, 1.3)     # «вот» слышно


def test_mat_from_discord_mutes_only_discord(tmp_path, obs_video, fake_trash):
    segs = [_seg("team", [(3.4, 4.0, "сука"), (4.2, 4.8, "ладно")])]
    out, n, _ = _render(tmp_path, obs_video, segs)
    assert n == 1
    assert _tone(out, 0, TEAM, 3.55, 3.85) < 0.02 * _tone(out, 0, TEAM, 4.3, 4.7)
    assert _tone(out, 0, GAME, 3.55, 3.85) > 0.7 * _tone(out, 0, GAME, 0.2, 0.8)


def test_wrong_speaker_mutes_everything(tmp_path, obs_video, fake_trash):
    """Whisper записал мат на меня, а в микрофоне тишина (звучало в игре) — глушим всё, как раньше."""
    segs = [_seg("me", [(4.0, 4.6, "блять")])]
    out, n, clip = _render(tmp_path, obs_video, segs)
    assert n == 1 and clip["bleep_voice"] == 0
    assert _tone(out, 0, GAME, 4.15, 4.45) < 0.02 * _tone(out, 0, GAME, 0.2, 0.8)


def test_one_track_recording_mutes_everything(tmp_path, fake_trash):
    v = tmp_path / "один.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=270x480:r=30:d=6",
                    "-f", "lavfi", "-i", f"sine=frequency={GAME}:sample_rate=48000:duration=6",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-t", "6", str(v)], check=True)
    out, n, clip = _render(tmp_path, v, [_seg("me", [(2.0, 2.6, "блять")])])
    assert n == 1 and clip["bleep_voice"] == 0
    assert _tone(out, 0, GAME, 2.15, 2.45) < 0.02 * _tone(out, 0, GAME, 0.2, 0.8)


def test_tighten_to_voice(obs_video):
    """Whisper дал мату 0,2–2,0 с, а голос в микрофоне — с 1,0: время сужается, не расширяется."""
    w = {"s": 0.2, "e": 2.0, "w": "блять", "spk": "me", "src": 0.2}
    autoclip.tighten_mat(str(obs_video), [w], {"me": 1, "team": 2})
    assert 0.9 <= w["s"] <= 1.05 and w["e"] == 2.0 and abs(w["src"] - w["s"]) < 1e-6
    hand = {"s": 0.2, "e": 2.0, "w": "", "mat": True, "src": 0.2}             # добавлен руками — не трогаем
    autoclip.tighten_mat(str(obs_video), [hand], {"me": 1})
    assert (hand["s"], hand["e"]) == (0.2, 2.0)


def test_bleep_len_and_span_tracks():
    assert autoclip.bleep_len(1.0, 1.4, 3.0, 2.0) == pytest.approx(1.4 - 1.0 + autoclip.BLEEP_TAIL)
    assert autoclip.bleep_len(1.0, 1.4, 1.45, 2.0) == pytest.approx(0.45)
    words = [{"s": 1.0, "e": 1.4, "w": "блять", "spk": "me"}, {"s": 3.0, "e": 3.4, "w": "сука", "spk": "team"},
             {"s": 5.0, "e": 5.4, "w": "", "mat": True, "added": True, "spk": "me"}]
    spans = [(0.95, 1.45, 2.0), (2.95, 3.45, 4.0), (4.95, 5.45, 6.0)]
    assert autoclip.span_tracks(words, spans, {"me": 1, "team": 2}) == [[1], [2], []]
    assert autoclip.span_tracks(words, spans, {"me": 1}) == [[1], [], []]
