"""Горизонтальные клипы (0.1.0 бета): пресет «Горизонтальный 1920×1080» — только для горизонтальных записей,
всё остальное (хук, зум, мат, субтитры, ник, обложки) — то же, только 16:9."""
import json
import os
import subprocess
import sys

import pytest

import autoclip
import update

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_export import _probe  # noqa: E402

VERT, HORIZ = "Вертикальный 1080×1920", "Горизонтальный 1920×1080"


def test_two_builtin_presets():
    names = [p["name"] for p in autoclip.load_presets()][:2]
    assert names == [VERT, HORIZ]
    h = autoclip.get_preset(HORIZ)
    assert (h["w"], h["h"], h["fps"], h["kbps"]) == (1920, 1080, 60, 18000)
    assert autoclip.is_horizontal(HORIZ) and not autoclip.is_horizontal(VERT)


def test_vertical_recording_refuses_horizontal_preset():
    with pytest.raises(autoclip.AutoClipError, match="вертикальная"):
        autoclip.check_orientation({"w": 1080, "h": 1920}, HORIZ)
    autoclip.check_orientation({"w": 2560, "h": 1440}, HORIZ)          # горизонтальная — можно
    autoclip.check_orientation({"w": 2560, "h": 1440}, VERT)           # и вертикальный по-прежнему можно


def test_subtitles_same_size_and_no_safe_zone_on_horizontal():
    cfg = dict(autoclip.CONFIG, safe_zone=True, nick=False)
    v = autoclip.subs_layout(1080, 1920, cfg)
    h = autoclip.subs_layout(1920, 1080, cfg)
    assert v["fs"] == h["fs"]                                          # буквы того же размера, не вдвое крупнее
    assert autoclip.frame_area(1920, 1080, cfg) == (40.0, 40.0, 1880.0, 1040.0)   # кнопок TikTok нет
    nv = autoclip.nick_layout(1080, 1920, dict(cfg, nick_size=40))
    nh = autoclip.nick_layout(1920, 1080, dict(cfg, nick_size=40))
    assert nv["fs"] == nh["fs"]


def test_telegram_light_copy_keeps_orientation():
    assert autoclip.light_plan(30, horizontal=True)[:2] == (1920, 1080)
    assert autoclip.light_plan(30)[:2] == (1080, 1920)
    assert autoclip.light_plan(600, horizontal=True)[:2] == (1280, 720)


def test_version_name():
    assert update.version_name("3.0.0") == "0.1.0 бета"
    assert update.version_name("3.0.1") == "0.1.1 бета"
    assert update.version_name("3.1.0") == "0.2.0 бета"
    assert update.version_name("2.3.6") == "2.3.6"
    assert update.is_newer("3.0.0", "2.3.6")                           # старые копии обновятся сами


def _horizontal_record(tmp_path, w=2560, h=1440):
    video = tmp_path / "гориз.mp4"
    dur = 40
    audio = f"aevalsrc='0.03*sin(2*PI*300*t)*(1+25*between(t,20,22))':s=48000:d={dur}"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r=60:d={dur}",
                    "-f", "lavfi", "-i", audio, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", str(video)], check=True)
    with open(tmp_path / "гориз.transcript.json", "w", encoding="utf-8") as f:
        json.dump([{"s": 19.0, "e": 22.0, "text": "ну блять смотри",
                    "words": [{"s": 19.5, "e": 20.0, "w": "ну"}, {"s": 20.2, "e": 20.6, "w": "блять"},
                              {"s": 20.8, "e": 21.4, "w": "смотри"}]}], f, ensure_ascii=False)
    return video


def test_horizontal_cut_is_1920x1080(tmp_path, fake_trash, monkeypatch):
    """Горизонтальная запись 2560×1440 → клип 1920×1080, 60 к/с, H.264, Rec. 709, обложка тоже 16:9;
    мат запикан, субтитры и ник на месте."""
    video = _horizontal_record(tmp_path)
    monkeypatch.setattr(autoclip, "log", lambda m: None)
    autoclip.CONFIG.update(max_silence_share=1.0, llm="none", clips=1, preset=HORIZ, subs=True, bleep=True,
                           nick=True, nick_text="Ник", zoom="on")
    out_dir = autoclip.process(str(video))
    proj = autoclip.load_project(out_dir)
    assert autoclip.project_horizontal(proj)
    clip = proj["clips"][0]
    v, bitrate = _probe(os.path.join(out_dir, clip["file"]))
    assert (v["width"], v["height"]) == (1920, 1080)
    assert v["r_frame_rate"] == "60/1" and v["codec_name"] == "h264"
    assert (v["color_space"], v["color_primaries"], v["color_transfer"]) == ("bt709",) * 3
    assert 15_000_000 < bitrate < 21_000_000
    assert clip["bleeps"] == 1
    cover = autoclip.cover_path_for(out_dir, clip["file"])
    assert os.path.isfile(cover)
    wh = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                         "-of", "csv=p=0", cover], capture_output=True, text=True).stdout.strip()
    assert wh == "1920,1080"


def test_process_refuses_vertical_record_with_horizontal_preset(tmp_path, fake_trash, monkeypatch):
    video = _horizontal_record(tmp_path, w=540, h=960)
    monkeypatch.setattr(autoclip, "log", lambda m: None)
    autoclip.CONFIG.update(llm="none", clips=1, preset=HORIZ)
    with pytest.raises(autoclip.AutoClipError, match="Вертикальный"):
        autoclip.process(str(video))


def test_window_horizontal_cards_and_cut_guard(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", autoclip.log)
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    win = A.MainWindow()
    win.show()
    cards = win.clips.cards
    cards.set_grid(True)
    cards.set_horizontal(True)
    sz = cards.size_hint()
    cover = cards._cover_rect(A.QRectF(0, 0, sz.width(), sz.height()).toRect())
    assert cover.width() > cover.height()                              # широкая обложка 16:9
    assert abs(cover.width() / cover.height() - 16 / 9) < 0.05
    cards.set_horizontal(False)
    cover = cards._cover_rect(A.QRectF(0, 0, cards.size_hint().width(), cards.size_hint().height()).toRect())
    assert cover.height() > cover.width()
    # вертикальная запись + горизонтальный пресет — нарезка не начинается, понятная подсказка
    cut = win.cut
    cut.preset.setCurrentText(HORIZ)
    assert win.settings_page.live.horizontal and win.settings_page.live.W == 1920
    cut.files = ["x.mp4"]
    cut._thumb_info = {"paths": ["x.mp4"], "w": 1080, "h": 1920, "fps": 60, "dur": 100, "marks": 0}
    started = []
    monkeypatch.setattr(win, "start_cut", lambda files: started.append(files))
    cut.start_or_stop()
    assert started == [] and "вертикальная" in cut.log.toPlainText()
    cut.preset.setCurrentText(VERT)
    cut.start_or_stop()
    assert started == [["x.mp4"]]
    win.close()
