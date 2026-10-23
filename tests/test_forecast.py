"""Прогноз: разбор по правилам удержания, вопрос про просмотры, обучение, вкус для модели."""
import datetime
import json
import random
import sys

import pytest

import autoclip
import forecast


def words(*items, start=0.0):
    out, t = [], start
    for w, d, gap in items:
        out.append({"s": round(t, 2), "e": round(t + d, 2), "w": w})
        t += d + gap
    return out


CLIP = {"start": 10.0, "end": 30.0, "peak": 13.0, "score": 2.5, "status": "new",
        "score_parts": {"громкость": 1.5, "смех": 0.6, "мат": 0.3, "восклицания": 0.0,
                        "речь": 0.4, "модель": 0.0},
        "hook": {"on": False}, "quiet_start": True, "marks": []}


def test_features_and_notes():
    ws = words(("ну", 0.5, 0.1), ("смотри", 0.5, 0.1), ("сюда", 0.5, 6.0), ("ахаха", 0.6, 0.1),
               start=10.0)
    segs = [{"s": 10, "e": 30, "text": "", "words": ws}]
    f = forecast.clip_features(CLIP, segs)
    assert f["length"] == 20.0 and f["laugh"] == 0.6 and f["quiet"] == 1.0
    assert f["pauses"] == pytest.approx(11.7, abs=0.05)    # самая длинная тишина — в конце клипа
    assert f["peak_pos"] == pytest.approx(0.15)
    assert f["density"] == pytest.approx(4 / 20)
    notes = dict((t.split(" — ")[0], ok) for ok, t in forecast.retention_notes(CLIP, f))
    assert notes["нет крючка в первые 1–2 с"] is False
    assert notes["тихое начало"] is False
    assert notes["хорошая длина"] is True
    assert notes["мало речи"] is False
    assert any(t.startswith("пауза") for t in notes)


def _project(tmp_path, clips, name="запись", transcript=None):
    out = tmp_path / f"{name}_clips"
    out.mkdir()
    tr = tmp_path / f"{name}.transcript.json"
    tr.write_text(json.dumps(transcript or [], ensure_ascii=False), encoding="utf-8")
    proj = autoclip.new_project(str(tmp_path / f"{name}.mp4"), {"w": 1080, "h": 1920, "dur": 600.0,
                                "fps": 60.0}, str(out), str(tr))
    for i, extra in enumerate(clips, 1):
        rec = autoclip.make_clip_record({"s": 10.0 * i, "e": 10.0 * i + 8, "peak": 10.0 * i + 2,
                                         "score": 2.0, "zooms": [], "parts": {},
                                         "title": f"клип {i}", "reason": ""}, i, f"{i:02d}.mp4")
        rec.update(extra)
        proj["clips"].append(rec)
    autoclip.save_project(proj)
    autoclip.register_project(str(out))
    return str(out)


def ago(days):
    return (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat(timespec="seconds")


def test_views_questions(tmp_path):
    path = _project(tmp_path, [
        {"status": "published", "published": {"tiktok": {"date": ago(4)}, "youtube": {"date": ago(1)},
                                              "instagram": {"date": ago(5), "views": 100}}},
    ])
    qs = forecast.due_questions(3)
    assert [(q["platform"], q["days_ago"]) for q in qs] == [("tiktok", 4)]   # по площадке отдельно
    forecast.snooze_views(path, "c01", "tiktok")
    assert forecast.due_questions(3) == []                                    # завтра спросим
    tomorrow = datetime.datetime.now() + datetime.timedelta(days=1, minutes=1)
    assert len(forecast.due_questions(3, now=tomorrow)) == 1
    assert len(forecast.due_questions(1, now=tomorrow)) == 2                  # и YouTube подошёл
    c = forecast.record_views(path, "c01", "tiktok", 12345, 41.5)
    assert c["published"]["tiktok"]["views"] == 12345 and c["published"]["tiktok"]["retention"] == 41.5
    assert forecast.load_history()[-1]["views"] == 12345
    forecast.skip_views(path, "c01", "youtube")
    assert forecast.due_questions(1, now=tomorrow) == []
    with pytest.raises(autoclip.AutoClipError):
        forecast.record_views(path, "c01", "tiktok", -5)


def _synthetic(n, seed=1):
    """Смех нравится Гоше, хук набирает просмотры."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        laugh, hook = rnd.uniform(0, 3), float(rnd.random() < 0.5)
        f = {k: rnd.uniform(0, 1) for k, _ in forecast.FEATURES}
        f.update(laugh=laugh, hook=hook)
        like = int(laugh + rnd.gauss(0, 0.4) > 1.5)
        views = int(10 ** (3 + 1.2 * hook + rnd.gauss(0, 0.2)))
        out.append({"features": f, "like": like, "views": {"tiktok": views}})
    return out


def test_training_learns_and_explains(tmp_path):
    few = forecast.train(samples=_synthetic(10))
    assert few["like"] is None and few["views"] is None
    p = forecast.predict(_synthetic(1)[0]["features"], 2.0, few)
    assert p["share"] == 0 and "данных мало" in p["note"]

    info = forecast.train(samples=_synthetic(60))
    weights = dict(zip(info["features"], info["like"]["coef"]))
    assert weights["laugh"] == max(weights.values())                      # главное для «нравится»
    vweights = dict(zip(info["features"], info["views"]["coef"]))
    assert vweights["hook"] == max(vweights.values())                     # главное для просмотров
    assert forecast.load_model()["n_like"] == 60
    good = dict(_synthetic(1)[0]["features"], laugh=3.0, hook=1.0)
    bad = dict(good, laugh=0.0, hook=0.0)
    pg, pb = forecast.predict(good, 2.0, info), forecast.predict(bad, 2.0, info)
    assert pg["value"] > pb["value"] and 0 < pg["share"] <= 0.7 and "модель" in pg["note"]
    ex = forecast.explain(info)
    assert ex["like"][0][0] == "смех" and ex["views"][0][0] == "хук"


def test_share_grows_with_data():
    a = forecast.model_share({"like": {"coef": [1]}, "n_like": 30, "n_views": 0})
    b = forecast.model_share({"like": {"coef": [1]}, "views": {"coef": [1]}, "n_like": 60, "n_views": 40})
    assert 0 < a < b <= 0.7


def test_taste_examples_go_into_llm_prompt(tmp_path, monkeypatch):
    tr = [{"s": 10.0, "e": 15.0, "text": "", "words": [{"s": 10.5, "e": 11.0, "w": "ахаха"},
                                                        {"s": 11.2, "e": 11.8, "w": "умер"}]}]
    _project(tmp_path, [{"status": "good"}, {"status": "rejected"}], transcript=tr)
    ex = forecast.taste_examples()
    assert ex == ["ахаха умер"]
    sent = []
    monkeypatch.setattr(autoclip, "_ask_llm", lambda prompt, mode, **k: sent.append(prompt) or "{}")
    segs = [{"s": t, "e": t + 2, "text": f"фраза {t}", "words": []} for t in range(0, 30, 3)]
    autoclip.llm_moments(segs, "ollama", examples=ex)
    assert "«ахаха умер»" in sent[0] and sent[0].index("ахаха") < sent[0].index("Расшифровка:")


# ---------- окно ----------

@pytest.fixture
def win(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    w = A.MainWindow()
    yield A, w
    w.close()


def test_views_dialog(win, tmp_path):
    A, w = win
    path = _project(tmp_path, [
        {"status": "published", "published": {"tiktok": {"date": ago(4)}, "youtube": {"date": ago(5)}}}])
    qs = forecast.due_questions(3)
    dlg = A.ViewsDialog(w, qs)
    assert len(dlg.rows) == 2
    yt = next(r for r in dlg.rows if r[0]["platform"] == "youtube")
    yt[1].setText("5000")
    yt[2].setText("37,5")
    dlg.action = "save"
    assert dlg.apply() == 1
    c = autoclip.find_clip(autoclip.load_project(path), "c01")
    assert c["published"]["youtube"]["views"] == 5000 and c["published"]["youtube"]["retention"] == 37.5
    assert "remind_after" in c["published"]["tiktok"]            # пустую строку — завтра
    assert forecast.due_questions(3) == []


def test_forecast_in_clip_info_and_settings(win, tmp_path):
    A, w = win
    tr = [{"s": 10.0, "e": 18.0, "text": "", "words": [{"s": 10.5, "e": 11.0, "w": "ну"}]}]
    path = _project(tmp_path, [{"status": "good"}], transcript=tr)
    w.clips.load(path)
    text = w.clips.info.text()
    assert "Прогноз:" in text and "из 10" in text and "данных мало" in text
    w.settings_page.show_model(forecast.train())
    assert "Оценок" in w.settings_page.model_state.text()
    w.settings_page.show_model(forecast.train(samples=_synthetic(60)))
    assert "смех" in w.settings_page.model_state.text()


def test_training_uses_all_cuts(tmp_path):
    """Оценки «Хороший» / «В корзину» из всех прошлых нарезок, а не только из последней."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _project(a, [{"status": "good"}, {"status": "rejected"}], name="первая")
    _project(b, [{"status": "good"}], name="вторая")
    got = forecast.collect()
    assert len(got) == 3 and len({s["project"] for s in got}) == 2
    assert sorted(s["like"] for s in got) == [0, 1, 1]
