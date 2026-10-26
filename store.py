# -*- coding: utf-8 -*-
"""Общее хранилище оценок (Патч 5.2): %APPDATA%\\AutoClip\\оценки.json.

По каждому клипу и удалённому кандидату — отпечаток записи (5.1), время, признаки для прогноза,
кусок расшифровки (для «образцов вкуса» модели), оценка Гоши, публикации по площадкам с просмотрами
и досмотрами. Обучение прогноза и образцы для модели берутся **только отсюда**: удалишь запись или
папку с клипами — обучение ничего не теряет.

Хранилище обновляется само при каждом сохранении нарезки (`autoclip.save_project`)."""

import json
import os

import autoclip as A

PATH = os.path.join(A.user_dir(), "оценки.json")
VERSION = 1
TEXT_MAX = 400
TASTE_MAX = 5            # образцов для модели — не больше (иначе запрос слишком длинный)

# оценка Гоши → что это значит для обучения (5.3: «Норм» — между)
RATINGS = {"post": "Выложу", "ok": "Норм", "bad": "Не то"}
OLD_STATUS_RATING = {"good": "post", "published": "post", "rejected": "bad", "post": "post", "ok": "ok"}


class StoreError(Exception):
    """Хранилище не прочиталось — писать в него нельзя, иначе пропадут оценки."""


def load():
    """Хранилище оценок. Нет файла — пустое. Файл занят другим процессом — подождать и прочитать
    снова. Файл испорчен — ошибка (а не «пусто»: запись поверх стёрла бы все оценки)."""
    import time
    for attempt in range(40):
        try:
            with open(PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("items"), dict):
                return data
            raise StoreError("неверный формат")
        except FileNotFoundError:
            return {"version": VERSION, "items": {}, "migrated": False}
        except PermissionError:
            time.sleep(0.025)
        except ValueError as e:
            if attempt >= 4:
                raise StoreError(f"файл испорчен: {e}")
            time.sleep(0.05)                               # дописывается — ещё раз
    raise StoreError("файл занят")


def save(data):
    """Запись через временный файл; прежняя версия — в оценки.json.bak (на всякий случай)."""
    import shutil
    import time
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    if os.path.isfile(PATH):
        try:
            shutil.copyfile(PATH, PATH + ".bak")
        except OSError:
            pass
    for attempt in range(40):
        try:
            os.replace(tmp, PATH)
            return
        except PermissionError:
            time.sleep(0.025)
    os.replace(tmp, PATH)


def project_fp(proj):
    """Отпечаток записи нарезки; без файла и без отпечатка — имя и длительность (для старых)."""
    if proj.get("source_fp"):
        return proj["source_fp"]
    src = proj.get("source") or ""
    if src and os.path.isfile(src):
        try:
            return A.fingerprint(src, (proj.get("source_info") or {}).get("dur"))
        except OSError:
            pass
    dur = (proj.get("source_info") or {}).get("dur", 0)
    return f"name:{os.path.basename(src)}:{int(round(float(dur or 0)))}"


def key(fp, peak, kind="clip"):
    return f"{fp}|{kind}|{float(peak):.1f}"


def rating_of(clip):
    """Оценка клипа: из поля rating (5.3), а у старых — из статуса."""
    if clip.get("rating") in RATINGS:
        return clip["rating"]
    return OLD_STATUS_RATING.get(clip.get("status"))


def _features(proj, c, segs_box):
    if c.get("features"):
        return c["features"]
    try:
        import forecast
        if segs_box[0] is None:
            segs_box[0] = _segments(proj)
        return forecast.clip_features(c, segs_box[0])
    except Exception:
        return None


def _segments(proj):
    try:
        return A.load_segments(proj)
    except Exception:
        return []


def _text(proj, c, segs_box):
    if segs_box[0] is None:
        segs_box[0] = _segments(proj)
    return A.text_between(segs_box[0], c["start"], c["end"]).strip()[:TEXT_MAX]


def _publications(c):
    out = {}
    for plat, pub in (c.get("published") or {}).items():
        if isinstance(pub, dict):
            out[plat] = {k: pub.get(k) for k in ("date", "views", "retention", "views_date") if k in pub}
    return out


def sync_project(proj, data=None, write=True):
    """Переносит в хранилище всё, чему можно учиться, из нарезки. Возвращает число изменённых записей."""
    own = data is None
    data = load() if own else data
    items = data["items"]
    fp = project_fp(proj)
    rec_name = os.path.basename(proj.get("source") or "")
    segs_box = [None]
    changed = 0
    for c in proj.get("clips", []):
        k = key(fp, c.get("peak", c["start"]))
        if c.get("removed"):
            if items.pop(k, None) is not None:            # «удалить без оценки» — не учим
                changed += 1
            continue
        rating = rating_of(c)
        weak = rating is None and c.get("origin") == "candidate" and c.get("status") == "new"
        pubs = _publications(c)
        if rating is None and not weak and not pubs:
            if k in items:                                 # оценку сняли — запись больше не пример
                items.pop(k)
                changed += 1
            continue
        old = items.get(k) or {}
        rec = {"fp": fp, "recording": rec_name, "kind": "clip", "peak": c.get("peak"),
               "project": proj.get("_path"), "id": c.get("id"),
               "start": c["start"], "end": c["end"], "title": c.get("title", ""),
               "rating": rating, "weak": bool(weak), "status": c.get("status"),
               "published": pubs, "score": c.get("score"),
               "features": _features(proj, c, segs_box) or old.get("features"),
               "text": old.get("text") or _text(proj, c, segs_box),
               "date": c.get("status_date") or c.get("created") or old.get("date")}
        if {x: rec[x] for x in rec if x != "text"} != {x: old.get(x) for x in rec if x != "text"} or not old:
            items[k] = dict(old, **rec)
            changed += 1
    for kd in proj.get("candidates") or []:
        k = key(fp, kd.get("peak", kd["start"]), "candidate")
        if not kd.get("deleted"):
            if items.pop(k, None) is not None:
                changed += 1
            continue
        if k in items:
            continue
        c = dict(kd, hook={"on": False}, quiet_start=False)
        items[k] = {"fp": fp, "recording": rec_name, "kind": "candidate", "peak": kd.get("peak"),
                    "project": proj.get("_path"), "id": kd.get("id"),
                    "start": kd["start"], "end": kd["end"], "title": kd.get("title", ""),
                    "rating": "bad", "weak": True, "status": "deleted", "published": {},
                    "score": kd.get("score"), "features": _features(proj, c, segs_box),
                    "text": (kd.get("text") or "")[:TEXT_MAX], "date": kd.get("deleted_date")}
        changed += 1
    if own and changed and write:
        save(data)
    return changed


def forget_clip(proj, clip):
    """Клип удалён без оценки — убрать из хранилища."""
    data = load()
    if data["items"].pop(key(project_fp(proj), clip.get("peak", clip["start"])), None) is not None:
        save(data)


def migrate(project_paths, force=False):
    """Один раз перенести всё из существующих нарезок. Возвращает (нарезок, записей)."""
    data = load()
    if data.get("migrated") and not force:
        return 0, 0
    n = 0
    seen = set()
    for pp in project_paths:
        pp = os.path.abspath(A.project_path(pp))
        if pp in seen or not os.path.isfile(pp):
            continue
        seen.add(pp)
        try:
            proj = A.load_project(pp)
        except Exception:
            continue
        sync_project(proj, data)
        n += 1
    data["migrated"] = True
    save(data)
    return n, len(data["items"])


def find_projects(folders):
    """Все нарезки в папках (на один уровень вглубь, и в скрытой .autoclip — 5.11)."""
    out = []
    for d in folders:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            for pp in (os.path.join(d, n, A.PROJECT_FILE), os.path.join(d, n, ".autoclip", A.PROJECT_FILE)):
                if os.path.isfile(pp):
                    out.append(pp)
    return out


def samples():
    """Примеры для обучения прогноза — из хранилища."""
    out = []
    for k, r in load()["items"].items():
        f = r.get("features")
        if not f:
            continue
        rating = r.get("rating")
        like = {"post": 1.0, "bad": 0.0, "ok": OK_LIKE}.get(rating)
        weight = 1.0
        if r.get("weak"):
            like = 1.0 if like is None else like
            weight = WEAK
        views = {p: v["views"] for p, v in (r.get("published") or {}).items()
                 if isinstance(v.get("views"), (int, float))}
        retention = {p: float(v["retention"]) for p, v in (r.get("published") or {}).items()
                     if isinstance(v.get("retention"), (int, float))}
        if like is None and not views:
            continue
        out.append({"features": f, "like": like, "views": views, "retention": retention,
                    "weight": weight, "key": k, "project": r.get("project"), "id": r.get("id"),
                    "rating": rating})
    return out


WEAK = 0.5        # кандидат: «Собрать» / «Удалить» — слабый сигнал (3.10)
OK_LIKE = 0.5     # «Норм» — между «Выложу» и «Не то» (5.3)


def taste(k=TASTE_MAX):
    """Образцы вкуса для модели: клипы «Выложу» и с лучшими просмотрами — (тексты, всего оценок)."""
    items = load()["items"].values()
    rated = [r for r in items if r.get("rating") in RATINGS]
    good = []
    for r in items:
        views = max([v.get("views") or 0 for v in (r.get("published") or {}).values()] or [0])
        if (r.get("rating") == "post" or views) and r.get("text"):
            good.append((views, r.get("date") or "", r["text"]))
    good.sort(reverse=True)
    return [t[:300] for _, _, t in good[:k]], len(rated)
