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
        if prompt.startswith(autoclip.META_PROMPT.split("<<CLIP>>")[0]):
            return '{"title": "Смотри сюда", "tags": ["#bg3", "#ор"]}'
        if "spoils" in prompt:
            return '{"spoils": false, "reason": ""}'
        return '{"moments": []}'
    monkeypatch.setattr(autoclip, "pick_llm", lambda m: "ollama")
    monkeypatch.setattr(autoclip, "_ask_llm", fake_llm)
    autoclip.CONFIG.update(clips=1, hashtags="#стрим", max_silence_share=1.0)   # синтетика с паузами
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
    page.show_tab(2)
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


def test_ollama_request_for_thinking_model(monkeypatch):
    """Qwen3 просим не думать вслух, а если подумала — рассуждения выкидываем."""
    sent = {}

    def fake_http(url, payload, headers, timeout):
        sent.update(payload)
        return {"message": {"content": '<think>хм, а что если</think>{"title": "Ок", "tags": []}'}}
    monkeypatch.setattr(autoclip, "_http_json", fake_http)
    monkeypatch.setitem(autoclip.CONFIG, "ollama_model", "qwen3:14b")
    assert autoclip._ask_llm("x", "ollama") == '{"title": "Ок", "tags": []}'
    assert sent["think"] is False and sent["format"] == "json"
    monkeypatch.setitem(autoclip.CONFIG, "ollama_model", "qwen2.5:14b")
    sent.clear()
    autoclip._ask_llm("x", "ollama")
    assert "think" not in sent                       # старым моделям параметр не шлём


def test_llm_meta_drops_empty_and_profane_tags(monkeypatch):
    monkeypatch.setattr(autoclip, "_ask_llm", lambda *a, **k:
                        '{"title": "Чародей без ячеек", "tags": ["#мем", "#хуя", "#чародей", "#игрок", "#bg3"]}')
    assert autoclip.llm_clip_meta("текст", "ollama")["tags"] == ["#чародей", "#bg3"]


@pytest.mark.parametrize("want,models,expect", [
    ("qwen3:14b", ["qwen3:14b"], "qwen3:14b"),
    ("qwen2.5:14b", ["qwen3:14b"], "qwen3:14b"),            # старое имя — берём скачанную
    ("qwen3", ["qwen3:latest", "llama3:8b"], "qwen3:latest"),
    ("qwen3:8b", ["llama3:8b", "qwen3:14b"], "qwen3:14b"),  # та же семья
    ("mistral", ["llama3:8b"], "llama3:8b"),                # хоть какая-то
    ("qwen3:14b", [], None),
])
def test_resolve_ollama_model(monkeypatch, want, models, expect):
    monkeypatch.setitem(autoclip.CONFIG, "ollama_model", want)
    assert autoclip.resolve_ollama_model(models) == expect


def test_pick_llm_switches_to_downloaded_model(monkeypatch):
    logs = []
    monkeypatch.setattr(autoclip, "log", logs.append)
    monkeypatch.setattr(autoclip, "_ollama_alive", lambda: True)
    monkeypatch.setattr(autoclip, "ollama_models", lambda: ["qwen3:14b"])
    monkeypatch.setitem(autoclip.CONFIG, "ollama_model", "qwen2.5:14b")
    assert autoclip.pick_llm("auto") == "ollama"
    assert autoclip.CONFIG["ollama_model"] == "qwen3:14b"
    assert any("нет в Ollama" in m for m in logs)
    monkeypatch.setattr(autoclip, "ollama_models", lambda: [])
    assert autoclip.pick_llm("auto") in ("none", "anthropic")      # моделей нет — без неё


def test_llm_failure_warned_once_per_cut(tmp_path, monkeypatch, fake_trash):
    import urllib.error
    v = tmp_path / "запись.mp4"
    audio = "aevalsrc='0.03*sin(2*PI*300*t)*(1+25*between(mod(t,20),10,12))':s=48000:d=100"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=270x480:r=30:d=100",
                    "-f", "lavfi", "-i", audio, "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(v)], check=True)
    segs = [{"s": t, "e": t + 2.4, "text": "ну вот смотри сюда",
             "words": [{"s": t + i * 0.6, "e": t + i * 0.6 + 0.5, "w": w}
                       for i, w in enumerate(["ну", "вот", "смотри", "сюда"])]} for t in range(0, 100, 4)]
    with open(tmp_path / "запись.transcript.json", "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False)

    def broken(*a, **k):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    logs = []
    monkeypatch.setattr(autoclip, "log", logs.append)
    monkeypatch.setattr(autoclip, "pick_llm", lambda m: "ollama")
    monkeypatch.setattr(autoclip, "_ask_llm", broken)
    autoclip.CONFIG.update(clips=3)
    out = autoclip.process(str(v))
    assert len(autoclip.load_project(out)["clips"]) >= 2
    assert sum("про название" in m for m in logs) == 1               # одна строка, а не на каждый клип


def test_title_only_from_this_clip():
    """Клип 7 записи 24.10: в клипе одно слово «просто», а модель назвала «Бессмертная вайпер умерла»."""
    assert not autoclip.title_fits("Бессмертная вайпер умерла", "просто")
    assert autoclip.title_fits("Вайпер бессмертная, но умерла", "просто вайпер бессмертная она умерла")
    import numpy as np
    n = 120
    smooth = np.zeros(n)
    smooth[60] = 4.0
    segs = [{"s": 50, "e": 70, "text": "просто", "words": [{"s": 58.0, "e": 58.4, "w": "просто"}]}]
    moments = [{"s": 40, "e": 80, "score": 9, "title": "Бессмертная вайпер умерла", "reason": ""}]
    clips = autoclip.pick_clips(smooth, np.zeros(n), segs, moments, 120.0)
    assert clips and clips[0]["title"] == "просто"                    # название — из слов клипа


class _FakeStream:
    """Ответ Ollama кусочками (stream=True)."""

    def __init__(self, pieces, on_close=None):
        import json as _j
        self.lines = [(_j.dumps({"message": {"content": p}, "done": False}) + "\n").encode() for p in pieces]
        self.lines.append(b'{"message": {"content": ""}, "done": true}\n')
        self.closed = False

    def __iter__(self):
        return iter(self.lines)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_stream_moves_progress_and_stops(monkeypatch):
    """Полоса «Модель» движется по мере ответа; «Остановить» обрывает запрос к Ollama."""
    import threading
    import urllib.request
    pieces = ['{"moments": [', '{"start": 1, "end": 5, "score": 8, "title": "т", "reason": "р"}', ']}']
    fake = _FakeStream(pieces)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: fake)
    monkeypatch.setattr(autoclip, "_check_ollama_vram", lambda model: None)
    monkeypatch.setattr(autoclip, "_warn_gpu_busy", lambda: None)
    segs = [{"s": float(i), "e": i + 1.0, "text": f"фраза {i}", "words": []} for i in range(10)]
    pts = []
    m = autoclip.llm_moments(segs, "ollama", progress=lambda st, pct, msg: pts.append(pct))
    assert len(m) == 1 and len(pts) >= 3 and pts == sorted(pts) and max(pts) < 100
    cancel = threading.Event()
    cancel.set()
    fake2 = _FakeStream(pieces)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: fake2)
    with pytest.raises(autoclip.Cancelled):
        autoclip._ask_llm("x", "ollama", cancel=cancel)
    assert fake2.closed                                   # запрос оборван — Ollama не дожёвывает


def test_ollama_silent_too_long_goes_on_without_model(monkeypatch):
    """Модель молчит дольше трёх минут — нарезка не висит, ищет без неё."""
    import urllib.request

    def silent(req, timeout=None):
        raise TimeoutError("timed out")
    monkeypatch.setattr(urllib.request, "urlopen", silent)
    monkeypatch.setattr(autoclip, "_warn_gpu_busy", lambda: None)
    logs = []
    monkeypatch.setattr(autoclip, "log", logs.append)
    segs = [{"s": float(i), "e": i + 1.0, "text": f"фраза {i}", "words": []} for i in range(10)]
    assert autoclip.llm_moments(segs, "ollama", progress=lambda *a: None) == []
    assert any("не отвечает" in x for x in logs)


class _FakeStream:
    """Ответ Ollama кусочками (stream=True)."""

    def __init__(self, pieces):
        import json as _j
        self.lines = [(_j.dumps({"message": {"content": p}, "done": False}) + "\n").encode() for p in pieces]
        self.lines.append(b'{"message": {"content": ""}, "done": true}\n')
        self.closed = False

    def __iter__(self):
        return iter(self.lines)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_stream_moves_progress_and_stops(monkeypatch):
    """Полоса «Модель» движется по мере ответа; «Остановить» обрывает запрос к Ollama."""
    import threading
    import urllib.request
    pieces = ['{"moments": [', '{"start": 1, "end": 5, "score": 8, "title": "т", "reason": "р"}', ']}']
    fake = _FakeStream(pieces)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: fake)
    monkeypatch.setattr(autoclip, "_check_ollama_vram", lambda model: None)
    monkeypatch.setattr(autoclip, "_warn_gpu_busy", lambda: None)
    segs = [{"s": float(i), "e": i + 1.0, "text": f"фраза {i}", "words": []} for i in range(10)]
    pts = []
    m = autoclip.llm_moments(segs, "ollama", progress=lambda st, pct, msg: pts.append(pct))
    assert len(m) == 1 and len(pts) >= 3 and pts == sorted(pts) and max(pts) < 100
    cancel = threading.Event()
    cancel.set()
    fake2 = _FakeStream(pieces)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: fake2)
    with pytest.raises(autoclip.Cancelled):
        autoclip._ask_llm("x", "ollama", cancel=cancel)
    assert fake2.closed                                   # запрос оборван — Ollama не дожёвывает


def test_ollama_silent_too_long_goes_on_without_model(monkeypatch):
    """Модель молчит дольше трёх минут — нарезка не висит, ищет без неё."""
    import urllib.request

    def silent(req, timeout=None):
        raise TimeoutError("timed out")
    monkeypatch.setattr(urllib.request, "urlopen", silent)
    monkeypatch.setattr(autoclip, "_warn_gpu_busy", lambda: None)
    logs = []
    monkeypatch.setattr(autoclip, "log", logs.append)
    segs = [{"s": float(i), "e": i + 1.0, "text": f"фраза {i}", "words": []} for i in range(10)]
    assert autoclip.llm_moments(segs, "ollama", progress=lambda *a: None) == []
    assert any("не отвечает" in x for x in logs)
