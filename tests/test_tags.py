"""Хэштеги и описание: разбор, порядок и лимит, своё описание по площадкам, модель, окно."""
import json
import os
import subprocess
import sys

import pytest

import autoclip


def test_parse_tags():
    assert autoclip.parse_tags("стрим, #игры  shorts #Игры ##ok! ; bg3") == \
        ["#стрим", "#игры", "#shorts", "#ok", "#bg3"]
    assert autoclip.parse_tags("") == []


def test_compose_order_limit_and_dedupe():
    cfg = {"hashtags": "#стрим #игры #Shorts", "platform_tags": {"youtube": "#shorts", "tiktok": ""}}
    yt = autoclip.compose_tags("youtube", cfg, ["#смешно", "#фейл", "#bg3"])
    assert yt == ["#shorts", "#стрим", "#игры", "#смешно", "#фейл"]     # 5, без второго #Shorts
    tt = autoclip.compose_tags("tiktok", cfg, ["#смешно"])
    assert tt == ["#стрим", "#игры", "#Shorts", "#смешно"]               # у TikTok добавки нет


def _project(tmp_path):
    out = tmp_path / "запись_clips"
    out.mkdir()
    proj = autoclip.new_project(str(tmp_path / "запись.mp4"), {"w": 1080, "h": 1920, "dur": 60.0,
                                "fps": 60.0}, str(out), str(tmp_path / "t.json"))
    rec = autoclip.make_clip_record({"s": 1.0, "e": 20.0, "peak": 5.0, "score": 2.0, "zooms": [],
                                     "parts": {}, "title": "мяч надо кинуть", "reason": "",
                                     "meta": {"title": "Мяч улетел в космос",
                                              "tags": ["#bg3", "#фейл"]}}, 1, "01_клип.mp4")
    proj["clips"].append(rec)
    autoclip.save_project(proj)
    return str(out), rec["id"]


def test_description_per_platform(tmp_path):
    path, cid = _project(tmp_path)
    cfg = {"hashtags": "#стрим", "platform_tags": {"youtube": "#shorts", "tiktok": "", "instagram": "#reels"}}
    c = autoclip.find_clip(autoclip.load_project(path), cid)
    yt = autoclip.clip_description(c, "youtube", cfg)
    assert yt == "Мяч улетел в космос\n\n#shorts #стрим #bg3 #фейл"
    # своя правка для YouTube не трогает TikTok
    autoclip.set_description(path, cid, "youtube", "Мой текст #shorts")
    c = autoclip.find_clip(autoclip.load_project(path), cid)
    assert autoclip.clip_description(c, "youtube", cfg) == "Мой текст #shorts"
    assert autoclip.clip_description(c, "tiktok", cfg) == "Мяч улетел в космос\n\n#стрим #bg3 #фейл"
    autoclip.set_description(path, cid, "youtube", None)                  # вернуть как было
    c = autoclip.find_clip(autoclip.load_project(path), cid)
    assert autoclip.clip_description(c, "youtube", cfg) == yt
    with pytest.raises(autoclip.AutoClipError):
        autoclip.set_description(path, cid, "вконтакте", "x")


def test_llm_meta(monkeypatch):
    monkeypatch.setattr(autoclip, "_ask_llm", lambda *a, **k:
                        '{"title": "Как же он б**** промахнулся блять", "tags": ["бг3", "#фейл", "#ор", "#лишний"]}')
    meta = autoclip.llm_clip_meta("какой-то текст", "ollama")
    assert "блять" not in meta["title"].lower() and meta["title"]
    assert meta["tags"] == ["#бг3", "#фейл", "#ор"]                        # не больше 3
    monkeypatch.setattr(autoclip, "_ask_llm", lambda *a, **k: "не JSON")
    assert autoclip.llm_clip_meta("текст", "ollama") is None
    assert autoclip.llm_clip_meta("текст", "none") is None


def test_process_uses_llm_title_and_tags(tmp_path, monkeypatch, fake_trash):
    v = tmp_path / "запись.mp4"
    audio = "aevalsrc='0.03*sin(2*PI*300*t)*(1+25*between(t,20,22))':s=48000:d=40"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=270x480:r=30:d=40",
                    "-f", "lavfi", "-i", audio, "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(v)], check=True)
    with open(tmp_path / "запись.transcript.json", "w", encoding="utf-8") as f:
        json.dump([{"s": 19.0, "e": 22.0, "text": "ну вот смотри", "words": [
            {"s": 19.5, "e": 20.0, "w": "ну"}, {"s": 20.2, "e": 20.6, "w": "вот"},
            {"s": 20.8, "e": 21.4, "w": "смотри"}]}], f, ensure_ascii=False)

    def fake_llm(prompt, mode, max_tokens=2000):
        if "tags" in prompt and "title" in prompt and "расшифровка короткого клипа" in prompt:
            return '{"title": "Смотри сюда", "tags": ["#bg3", "#ор"]}'
        if "spoils" in prompt:
            return '{"spoils": false, "reason": ""}'
        return '{"moments": []}'
    monkeypatch.setattr(autoclip, "pick_llm", lambda m: "ollama")
    monkeypatch.setattr(autoclip, "_ask_llm", fake_llm)
    autoclip.CONFIG.update(clips=1, hashtags="#стрим")
    out = autoclip.process(str(v))
    c = autoclip.load_project(out)["clips"][0]
    assert c["meta"] == {"title": "Смотри сюда", "tags": ["#bg3", "#ор"]}
    assert c["title"] == "Смотри сюда" and "Смотри_сюда" in c["file"]
    report = open(os.path.join(out, "отчёт.txt"), encoding="utf-8").read()
    assert "хэштеги (TikTok): #стрим #bg3 #ор" in report


# ---------- окно ----------

def test_description_tab(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    path, cid = _project(tmp_path)
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    win = A.MainWindow()
    st, page = win.settings_page, win.clips
    st.tags.setText("#стрим")
    st.ptags["youtube"].setText("#shorts")
    page.load(path)
    page.show_tab(1)
    page.set_desc_platform("youtube")
    assert page.desc.toPlainText() == "Мяч улетел в космос\n\n#shorts #стрим #bg3 #фейл"
    assert "4 из 5" in page.desc_tags.text() and not page.btn_desc_reset.isEnabled()

    page.desc.setPlainText("Свой текст #shorts")                 # правка → сохраняется сама
    page.save_desc()
    c = autoclip.find_clip(autoclip.load_project(path), cid)
    assert c["desc_custom"] == {"youtube": "Свой текст #shorts"}
    assert page.btn_desc_reset.isEnabled()
    page.copy_desc()
    assert QApplication.clipboard().text() == "Свой текст #shorts"

    page.set_desc_platform("tiktok")                             # TikTok — своё, автоматическое
    assert page.desc.toPlainText().startswith("Мяч улетел в космос")
    page.set_desc_platform("youtube")
    page.reset_desc()
    assert page.desc.toPlainText().startswith("Мяч улетел в космос")
    assert autoclip.find_clip(autoclip.load_project(path), cid)["desc_custom"] is None
    win.close()

    saved = json.load(open(autoclip.SETTINGS_PATH, encoding="utf-8"))
    assert saved["hashtags"] == "#стрим" and saved["platform_tags"]["youtube"] == "#shorts"
