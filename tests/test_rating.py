"""Патч 5.3: «Выложу / Норм / Не то»; 5.4: «выложен» ставится всегда."""
import os

import autoclip
import forecast


def _proj(tmp_path, clips):
    out = tmp_path / "з_clips"
    out.mkdir()
    proj = autoclip.new_project(str(tmp_path / "з.mp4"), {"w": 2, "h": 2, "dur": 600.0, "fps": 30},
                                str(out), str(tmp_path / "t.json"))
    for i, extra in enumerate(clips, 1):
        c = autoclip.make_clip_record({"s": i * 30.0, "e": i * 30.0 + 20, "peak": i * 30.0 + 10, "score": 2,
                                       "zooms": [], "title": f"к{i}", "reason": ""}, i, f"{i:02d}.mp4")
        c.update(extra)
        (out / c["file"]).write_bytes(b"x")
        proj["clips"].append(c)
    autoclip.save_project(proj)
    return str(out)


def test_old_statuses_converted_and_published_repaired(tmp_path):
    pub = {"tiktok": {"date": "2026-10-25T01:27:45"}, "youtube": {"date": "2026-10-25T01:34:52"}}
    cut = _proj(tmp_path, [{"status": "good"}, {"status": "rejected"}, {"status": "good", "published": pub},
                           {"status": "new"}])
    cs = autoclip.load_project(cut)["clips"]
    assert [(c["status"], c.get("rating")) for c in cs] == [
        ("post", "post"), ("rejected", "bad"), ("published", "post"), ("new", None)]


def test_three_ratings(tmp_path, fake_trash):
    cut = _proj(tmp_path, [{}, {}, {}])
    assert autoclip.set_rating(cut, "c01", "post")["status"] == "post"
    c = autoclip.set_rating(cut, "c02", "ok")
    assert c["status"] == "ok" and os.path.isfile(os.path.join(cut, c["file"]))     # «Норм» — файл остаётся
    c = autoclip.set_rating(cut, "c03", "bad")
    assert c["status"] == "rejected" and not os.path.isfile(os.path.join(cut, c["file"]))
    assert autoclip.set_rating(cut, "c01", None)["status"] == "new"


def test_publish_from_any_status_and_rating_after(tmp_path):
    cut = _proj(tmp_path, [{}, {}])
    autoclip.set_rating(cut, "c01", "ok")
    assert autoclip.mark_published(cut, "c01", "tiktok")["status"] == "published"    # из «Норм» тоже
    c = autoclip.set_rating(cut, "c01", "post")                     # оценка после публикации — статус тот же
    assert c["status"] == "published" and c["rating"] == "post"
    assert autoclip.mark_published(cut, "c01", "tiktok", on=False)["status"] == "post"
    assert autoclip.mark_published(cut, "c02", "youtube")["status"] == "published"


def test_ok_is_half_signal():
    import random
    rnd = random.Random(5)
    samples = []
    for i in range(60):
        f = {k: rnd.uniform(0, 1) for k, _ in forecast.FEATURES}
        f["laugh"] = [0.0, 1.5, 3.0][i % 3]
        samples.append({"features": f, "like": [0.0, 0.5, 1.0][i % 3], "views": {}, "retention": {}})
    info = forecast.train(save=False, samples=samples)
    assert info["like"] is not None and info["n_like"] == 60
    mid = dict(samples[0]["features"], laugh=1.5)
    p = forecast.predict(mid, 2.0, info)
    lo = forecast.predict(dict(mid, laugh=0.0), 2.0, info)
    hi = forecast.predict(dict(mid, laugh=3.0), 2.0, info)
    assert lo["value"] < p["value"] < hi["value"]                   # «Норм» — между
