"""Пресет экспорта: размер, 60 кадров/с, H.264, постоянный битрейт, цвет Rec. 709."""
import json
import os
import subprocess

import pytest

import autoclip


@pytest.fixture
def presets_file(tmp_path, monkeypatch):
    path = tmp_path / "пресеты.json"
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(path))
    return path


def test_default_preset_is_tiktok():
    p = autoclip.get_preset(autoclip.CONFIG["preset"])
    assert p == {"name": "TikTok 1080p60", "w": 1080, "h": 1920, "fps": 60, "kbps": 18000}


def test_user_presets_saved_and_loaded(presets_file):
    mine = {"name": "Мой 720p30", "w": 720, "h": 1280, "fps": 30, "kbps": 8000}
    autoclip.save_user_presets(autoclip.load_presets() + [mine])
    names = [p["name"] for p in autoclip.load_presets()]
    assert names == ["TikTok 1080p60", "Мой 720p30"]
    # встроенный в файл не пишется
    assert json.loads(presets_file.read_text(encoding="utf-8")) == [mine]
    assert autoclip.get_preset("Мой 720p30")["fps"] == 30


def test_unknown_preset_falls_back_to_default(presets_file):
    assert autoclip.get_preset("нет такого")["name"] == "TikTok 1080p60"


@pytest.mark.parametrize("bad", [
    {"name": "", "w": 1080, "h": 1920, "fps": 60, "kbps": 18000},
    {"name": "x", "w": 1081, "h": 1920, "fps": 60, "kbps": 18000},
    {"name": "x", "w": 1080, "h": 1920, "fps": 500, "kbps": 18000},
    {"name": "x", "w": 1080, "h": 1920, "fps": 60, "kbps": 10},
    {"name": "x", "w": "много", "h": 1920, "fps": 60, "kbps": 18000},
])
def test_bad_presets_rejected(bad):
    with pytest.raises(autoclip.AutoClipError):
        autoclip.check_preset(bad)


def test_frame_filters():
    tiktok = autoclip.get_preset("TikTok 1080p60")
    same = autoclip.frame_filters({"w": 1080, "h": 1920, "fps": 60.0}, tiktok)
    assert same == ["setsar=1"]
    wide = autoclip.frame_filters({"w": 2560, "h": 1440, "fps": 60.0}, tiktok)
    assert wide == ["crop=810:1440", "scale=1080:1920:flags=lanczos", "setsar=1"]
    slow = autoclip.frame_filters({"w": 720, "h": 1280, "fps": 30.0}, tiktok)
    assert slow == ["scale=1080:1920:flags=lanczos", "setsar=1", "fps=60"]


def _probe(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate,codec_name,color_space,color_primaries,"
                        "color_transfer,color_range:format=bit_rate", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    data = json.loads(p.stdout)
    return data["streams"][0], int(data["format"]["bit_rate"])


def test_horizontal_30fps_record_becomes_tiktok_clip(tmp_path, fake_trash, monkeypatch):
    video = tmp_path / "гориз.mp4"
    dur = 40
    audio = f"aevalsrc='0.03*sin(2*PI*300*t)*(1+25*between(t,20,22))':s=48000:d={dur}"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=s=1280x720:r=30:d={dur}", "-f", "lavfi", "-i", audio,
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                    str(video)], check=True)
    with open(tmp_path / "гориз.transcript.json", "w", encoding="utf-8") as f:
        json.dump([{"s": 19.0, "e": 22.0, "text": "ну вот смотри",
                    "words": [{"s": 19.5, "e": 20.0, "w": "ну"}, {"s": 20.2, "e": 20.6, "w": "вот"},
                              {"s": 20.8, "e": 21.4, "w": "смотри"}]}], f, ensure_ascii=False)
    logs = []
    monkeypatch.setattr(autoclip, "log", logs.append)
    autoclip.CONFIG.update(llm="none", clips=1)

    out_dir = autoclip.process(str(video))
    proj = autoclip.load_project(out_dir)
    assert proj["settings"]["preset"]["name"] == "TikTok 1080p60"
    v, bitrate = _probe(os.path.join(out_dir, proj["clips"][0]["file"]))
    assert (v["width"], v["height"]) == (1080, 1920)
    assert v["r_frame_rate"] == "60/1"
    assert v["codec_name"] == "h264"
    assert (v["color_space"], v["color_primaries"], v["color_transfer"]) == ("bt709",) * 3
    assert v["color_range"] == "tv"
    assert 15_000_000 < bitrate < 21_000_000
    # про 30 кадров/с предупреждаем ровно один раз
    assert sum("кадров/с" in m for m in logs) == 1
