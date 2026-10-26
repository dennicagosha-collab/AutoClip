"""Патч 5.12: перенос старых нарезок в «Клипы ДД.ММ.ГГГГ» с подпапками статусов."""
import json
import os

import autoclip
import store


def _old_cut(root, name, created, clips):
    d = root / name
    d.mkdir(parents=True)
    proj = {"version": 2, "source": str(root / "запись.mp4"), "source_info": {"dur": 100.0, "w": 2, "h": 2},
            "created": created, "settings": {}, "clips": []}
    for i, st in enumerate(clips, 1):
        f = f"{i:02d}_клип.mp4"
        (d / f).write_bytes(b"v")
        (d / f"{i:02d}_клип.jpg").write_bytes(b"c")
        proj["clips"].append({"id": f"c{i:02d}", "num": i, "file": f, "status": st, "start": i * 10.0,
                              "end": i * 10.0 + 5, "peak": i * 10.0 + 2, "overrides": {}, "title": "т",
                              "cover": {"file": f"{i:02d}_клип.jpg", "t": 1}})
    (d / "project.json").write_text(json.dumps(proj, ensure_ascii=False), encoding="utf-8")
    (d / "отчёт.txt").write_text("отчёт", encoding="utf-8")
    (d / "мой файл.txt").write_text("не трогать", encoding="utf-8")
    autoclip.register_project(str(d / "project.json"))
    return d


def test_move_old_cuts(tmp_path):
    rec = tmp_path / "Записи"
    base = tmp_path / "Клипы"
    a = _old_cut(rec, "запись_clips", "2026-10-24T02:41:00", ["good", "rejected", "new"])
    b = _old_cut(rec, "запись_clips_2", "2026-10-24T05:48:00", ["new"])
    c = _old_cut(rec, "клипы 25.10", "2026-10-25T00:43:00", ["post"])
    plan = autoclip.plan_old_cuts([str(rec)], str(base))
    assert [(os.path.basename(o), os.path.basename(n)) for o, n, _ in plan] == [
        ("запись_clips", "Клипы 24.10.2026"), ("запись_clips_2", "Клипы 24.10.2026 2"),
        ("клипы 25.10", "Клипы 25.10.2026")]
    done, skipped = autoclip.move_old_cuts([str(rec)], str(base))
    assert len(done) == 3 and not skipped and not a.exists()
    new = base / "Клипы 24.10.2026"
    assert (new / ".autoclip" / "project.json").is_file() and (new / ".autoclip" / "отчёт.txt").is_file()
    assert (new / "Выложу" / "01_клип.mp4").is_file() and (new / "Выложу" / "01_клип.jpg").is_file()
    assert (new / "Новые" / "03_клип.mp4").is_file()
    assert (new / "мой файл.txt").is_file()                          # чужое не трогаем
    proj = autoclip.load_project(str(new))
    assert proj["layout"] == 2 and proj["clips"][0]["file"] == "Выложу/01_клип.mp4"
    assert autoclip.known_projects() and all(".autoclip" in p for p in autoclip.known_projects())
    assert all(".autoclip" in (r.get("project") or "") for r in store.load()["items"].values())


def test_busy_folder_skipped(tmp_path, monkeypatch):
    rec = tmp_path / "Записи"
    _old_cut(rec, "запись_clips", "2026-10-24T02:41:00", ["new"])
    real = os.rename

    def busy(a, b):
        raise PermissionError(32, "занято")
    monkeypatch.setattr(autoclip.os, "rename", busy)
    done, skipped = autoclip.move_old_cuts([str(rec)], str(tmp_path / "Клипы"))
    assert not done and len(skipped) == 1 and (rec / "запись_clips" / "project.json").is_file()
