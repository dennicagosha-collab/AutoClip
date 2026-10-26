"""Патч 5.2: оценки и обучение не зависят от папок с клипами."""
import json
import os

import autoclip
import forecast
import store

FEATS = {k: 0.5 for k, _ in forecast.FEATURES}


def _proj(tmp_path, name, clips, candidates=()):
    out = tmp_path / name
    out.mkdir()
    proj = autoclip.new_project(str(tmp_path / f"{name}.mp4"), {"w": 2, "h": 2, "dur": 600.0, "fps": 30},
                                str(out), str(tmp_path / "t.json"))
    proj["source_fp"] = f"fp-{name}-600"
    for i, (status, extra) in enumerate(clips, 1):
        c = autoclip.make_clip_record({"s": i * 30.0, "e": i * 30.0 + 20, "peak": i * 30.0 + 10, "score": 2,
                                       "zooms": [], "title": f"клип {i}", "reason": ""}, i, f"{i:02d}.mp4")
        c.update(status=status, features=FEATS, **extra)
        proj["clips"].append(c)
    proj["candidates"] = list(candidates)
    autoclip.save_project(proj)                     # сохранение само пишет в хранилище
    autoclip.register_project(proj["_path"])
    return proj


def test_deleting_cut_folder_keeps_learning(tmp_path, fake_trash):
    _proj(tmp_path, "а_clips", [("good", {}), ("rejected", {}), ("new", {}),
                                ("published", {"published": {"tiktok": {"date": "2026-10-25", "views": 900}}})])
    n = len(forecast.collect())
    assert n == 3                                    # «новый» без оценки — не пример
    autoclip.trash(str(tmp_path / "а_clips"))        # Гоша удалил папку нарезки
    assert len(forecast.collect()) == n
    s = {x["id"]: x for x in forecast.collect()}
    assert s["c01"]["like"] == 1.0 and s["c02"]["like"] == 0.0 and s["c04"]["views"] == {"tiktok": 900}


def test_migration_from_old_cuts_once(tmp_path):
    proj = _proj(tmp_path, "б_clips", [("good", {})],
                 candidates=[{"id": "k01", "start": 100, "end": 120, "peak": 110, "deleted": True,
                              "text": "кандидат", "score": 1}])
    os.remove(store.PATH)                            # как будто хранилища ещё нет (до 1.4.0)
    s = forecast.collect()
    assert len(s) == 2 and {x["weight"] for x in s} == {1.0, store.WEAK}
    assert store.load()["migrated"]


def test_taste_from_store_and_log_text(tmp_path):
    _proj(tmp_path, "в_clips", [("good", {}), ("rejected", {})])
    data = store.load()
    for r in data["items"].values():
        r["text"] = "текст " + r["title"]
    store.save(data)
    texts = forecast.taste_examples()
    assert texts == ["текст клип 1"] and forecast.taste_examples.total == 2


def test_removed_without_rating_forgotten(tmp_path, fake_trash):
    proj = _proj(tmp_path, "г_clips", [("good", {})])
    (tmp_path / "г_clips" / "01.mp4").write_bytes(b"x")
    assert len(store.load()["items"]) == 1
    autoclip.remove_clip(proj["_path"], "c01")
    assert store.load()["items"] == {}
