"""Патч 3Б.7: процент досмотров — второй сигнал обучения."""
import random

import autoclip
import forecast


def _mixed(n, with_ret, seed=3):
    """Просмотры — от хука; досмотры (у части клипов) — от плотности речи. Две площадки
    в разных масштабах: на YouTube досматривают в среднем меньше."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        f = {k: rnd.uniform(0, 1) for k, _ in forecast.FEATURES}
        f.update(hook=float(rnd.random() < 0.5), density=rnd.uniform(0.5, 3.0))
        plat = "tiktok" if i % 2 else "youtube"
        views = {plat: int(10 ** (3 + 1.2 * f["hook"] + rnd.gauss(0, 0.2)))}
        ret = {}
        if i < with_ret:
            base = 40 if plat == "tiktok" else 20
            ret = {plat: max(0.0, min(100.0, base + 12 * f["density"] + rnd.gauss(0, 2)))}
        out.append({"features": f, "like": None, "views": views, "retention": ret})
    return out


def test_retention_needs_own_minimum():
    info = forecast.train(save=False, samples=_mixed(40, with_ret=forecast.MIN_RETENTION - 1))
    assert info["views"] is not None and info["retention"] is None
    assert info["n_retention"] == forecast.MIN_RETENTION - 1
    p = forecast.predict(_mixed(1, 0)[0]["features"], 2.0, info)
    assert p["model"] is not None                            # просмотры учатся и без досмотров


def test_retention_learns_alongside_views():
    info = forecast.train(save=False, samples=_mixed(40, with_ret=25))
    assert info["n_retention"] == 25 and info["retention"] is not None
    w = dict(zip(info["features"], info["retention"]["coef"]))
    assert w["density"] == max(w.values())                   # досмотры — от плотности речи
    v = dict(zip(info["features"], info["views"]["coef"]))
    assert v["hook"] == max(v.values())                      # просмотры — по-прежнему от хука
    assert set(info["retention"]["platforms"]) == {"tiktok", "youtube"}
    assert forecast.explain(info)["retention"][0][0] == "слов в секунду"
    dense = dict(_mixed(1, 0)[0]["features"], density=3.0)
    sparse = dict(dense, density=0.5)
    assert forecast.predict(dense, 2.0, info)["value"] > forecast.predict(sparse, 2.0, info)["value"]


def test_old_samples_without_retention_key():
    old = [{k: v for k, v in s.items() if k != "retention"} for s in _mixed(35, 0)]
    info = forecast.train(save=False, samples=old)
    assert info["views"] is not None and info["retention"] is None and info["n_retention"] == 0


def test_retention_only_model_counts_in_share():
    assert forecast.model_share({"retention": {"coef": [1]}, "n_retention": 20}) > 0
    assert forecast.model_share({"n_retention": 20}) == 0


def test_collect_reads_retention(tmp_path):
    out = tmp_path / "з_clips"
    out.mkdir()
    proj = autoclip.new_project(str(tmp_path / "з.mp4"), {"w": 270, "h": 480, "dur": 60.0, "fps": 30.0},
                                str(out), str(tmp_path / "t.json"))
    feats = {k: 0.5 for k, _ in forecast.FEATURES}
    a = autoclip.make_clip_record({"s": 1, "e": 20, "peak": 5, "score": 2, "zooms": [], "title": "а",
                                   "reason": ""}, 1, "01.mp4")
    a.update(features=feats, published={"tiktok": {"date": "2026-10-01T10:00:00", "views": 500,
                                                   "retention": 35.5},
                                        "youtube": {"date": "2026-10-01T10:00:00", "views": 90}})
    b = autoclip.make_clip_record({"s": 21, "e": 40, "peak": 25, "score": 2, "zooms": [], "title": "б",
                                   "reason": ""}, 2, "02.mp4")
    b.update(features=feats, published={"tiktok": {"date": "2026-10-01T10:00:00", "views": 70,
                                                   "retention": None}})
    proj["clips"] = [a, b]
    autoclip.save_project(proj)
    autoclip.register_project(proj["_path"])
    got = {s["id"]: s for s in forecast.collect()}
    assert got["c01"]["retention"] == {"tiktok": 35.5}
    assert got["c02"]["retention"] == {}
