"""Поиск по расшифровке и «Клип отсюда»."""
import json
import os
import subprocess
import sys

import pytest

import autoclip

SEGS = [
    {"s": 0.0, "e": 3.0, "text": "", "words": [
        {"s": 0.0, "e": 0.5, "w": "Ну"}, {"s": 0.6, "e": 1.2, "w": "это"},
        {"s": 1.3, "e": 2.0, "w": "СМЕШНО"}]},
    {"s": 5.0, "e": 8.0, "text": "", "words": [
        {"s": 5.0, "e": 5.5, "w": "Ёлка"}, {"s": 5.6, "e": 6.4, "w": "смешная,"},
        {"s": 6.5, "e": 7.0, "w": "ещё"}, {"s": 7.1, "e": 7.8, "w": "ёлка"}]},
]


def test_search_case_yo_and_part_of_word():
    hits = autoclip.search_transcript(SEGS, "смеш")
    assert [h["t"] for h in hits] == [1.3, 5.6]                     # часть слова, регистр не важен
    assert hits[0]["text"][slice(*hits[0]["hl"])] == "СМЕШ"
    assert [h["t"] for h in autoclip.search_transcript(SEGS, "ЕЛКА")] == [5.0, 7.1]   # ё = е
    assert [h["t"] for h in autoclip.search_transcript(SEGS, "елка")] == [5.0, 7.1]
    assert [h["t"] for h in autoclip.search_transcript(SEGS, "Ещё")] == [6.5]
    assert [h["t"] for h in autoclip.search_transcript(SEGS, "это  смешно")] == [0.6]  # фраза
    assert autoclip.search_transcript(SEGS, "к") == []              # одна буква — не ищем
    assert autoclip.search_transcript(SEGS, "банан") == []


def _words(dur, step=0.6, gap_every=7, gap=1.2):
    """Речь подряд с паузами — как у Whisper."""
    out, t, i = [], 0.0, 0
    while t < dur - 1:
        out.append({"s": round(t, 2), "e": round(t + 0.45, 2), "w": f"слово{i}"})
        t += step + (gap if i % gap_every == gap_every - 1 else 0)
        i += 1
    return [{"s": w["s"], "e": w["e"], "text": "", "words": [w]} for w in out]


@pytest.mark.parametrize("t", [3.0, 40.0, 117.0, 199.0])
def test_moment_at_bounds(t):
    segs = _words(200)
    proj = {"source_info": {"dur": 200.0}, "reaction": [0.0] * 200, "loud_z": [0.0] * 200}
    c = autoclip.moment_at(proj, t, segs)
    ln = c["e"] - c["s"]
    assert autoclip.CONFIG["min_len"] * 0.8 <= ln <= autoclip.CONFIG["max_len"] + 0.01
    assert c["s"] <= t <= c["e"]                                    # найденное место в клипе
    words = [w for s in segs for w in s["words"]]
    for b in (c["s"], c["e"]):                                      # не на полуслове
        assert not any(w["s"] + 0.05 < b < w["e"] - 0.05 for w in words)


def _video(tmp_path, dur=60):
    v = tmp_path / "запись.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=s=270x480:r=30:d={dur}", "-f", "lavfi", "-i",
                    f"aevalsrc='0.03*sin(2*PI*300*t)*(1+25*between(mod(t,20),10,12))':s=48000:d={dur}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                    str(v)], check=True)
    words = ["ну", "вот", "смотри", "сюда"]
    segs = [{"s": t, "e": t + 2.4, "text": " ".join(words),
             "words": [{"s": t + i * 0.6, "e": t + i * 0.6 + 0.5, "w": w} for i, w in enumerate(words)]}
            for t in range(0, dur, 4)]
    segs[11]["words"][2]["w"] = "Ёжик"                              # 44.0 + 1.2 = 45.2 с
    with open(tmp_path / "запись.transcript.json", "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False)
    return v


@pytest.fixture
def cut(tmp_path, fake_trash):
    autoclip.CONFIG.update(llm="none", clips=1, hook=False)
    return autoclip.process(str(_video(tmp_path)))


def test_clip_from_search(cut):
    proj = autoclip.load_project(cut)
    assert len(proj["loud_z"]) == 60                                 # зум для «Клип отсюда»
    n = len(proj["clips"])
    hit = autoclip.search_transcript(autoclip.load_segments(proj), "ежик")[0]
    assert hit["t"] == pytest.approx(45.2)
    rec = autoclip.clip_from_search(cut, hit["t"])
    proj = autoclip.load_project(cut)
    assert len(proj["clips"]) == n + 1 and proj["clips"][-1]["id"] == rec["id"]
    assert rec["origin"] == "search" and "из поиска" in autoclip.clip_tags(rec)
    assert rec["num"] == n + 1 and os.path.isfile(os.path.join(cut, rec["file"]))
    assert rec["start"] <= hit["t"] <= rec["end"]
    assert 15 * 0.8 <= rec["end"] - rec["start"] <= 55
    assert rec["hook"]["start"] is None or rec["start"] <= rec["hook"]["start"] < rec["hook"]["end"] <= rec["end"]


# ---------- окно ----------

@pytest.fixture
def win(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", lambda m: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    w = A.MainWindow()
    w.show()
    yield w
    w.close()


def wait_for(cond, ms=60000):
    from PySide6.QtTest import QTest
    for _ in range(ms // 50):
        if cond():
            return True
        QTest.qWait(50)
    return cond()


def test_search_page(win, cut):
    page = win.clips
    page.load(cut)
    page.search.setText("ЕЖ")
    page.run_search()
    assert page.left_stack.currentIndex() == 1 and len(page.hits) == 1
    assert "Нашлось: 1" in page.found_count.text()
    page.found.setCurrentRow(0)
    assert page.btn_here.isEnabled() and "0:45" in page.info.text()
    ok = wait_for(lambda: abs(page.player.player.position() - 44200) < 600, 15000)
    assert ok, (page.player.player.position(), page.player.player.duration(), page.player.player.source())   # запись на месте
    page.clip_here()
    assert wait_for(lambda: not page.busy)
    assert page.left_stack.currentIndex() == 0 and page.search.text() == ""
    c = page.current_clip()
    assert c["origin"] == "search" and c["start"] <= 45.2 <= c["end"]
    page.search.setText("нет такого")
    page.run_search()
    assert "Ничего" in page.found_count.text()
    page.search.setText("")
    page.run_search()
    assert page.left_stack.currentIndex() == 0 and page.editor.isEnabled()


def test_search_hides_mat_in_results():
    segs = [{"s": 0, "e": 3, "text": "", "words": [{"s": 0, "e": 0.5, "w": "ну"},
                                                     {"s": 0.6, "e": 1.0, "w": "блядь"},
                                                     {"s": 1.1, "e": 1.5, "w": "смешно"}]}]
    h = autoclip.search_transcript(segs, "смеш")[0]
    assert "блядь" not in h["shown"] and h["shown"][slice(*h["hl_shown"])] == "смешно"
    h = autoclip.search_transcript(segs, "бляд")[0]
    assert h["shown"][slice(*h["hl_shown"])] == autoclip._censor("блядь")
