# -*- coding: utf-8 -*-
"""Прогноз: разбор клипа по правилам удержания, просмотры, обучение на оценках Гоши
и реальных просмотрах. Это оценка, а не обещание просмотров.

Признаки клипа считаются из project.json и расшифровки. Модели простые и объяснимые
(логистическая и линейная регрессия), веса хранятся в %APPDATA%\\AutoClip\\модель.json."""

import datetime
import json
import math
import os

import autoclip as A

# признак → как его называть человеку
FEATURES = (
    ("loud", "громкость у пика"), ("laugh", "смех"), ("mat", "мат"), ("excl", "крик"),
    ("speech", "речь у пика"), ("llm", "оценка языковой модели"), ("mark", "метка из OBS"),
    ("hook", "хук"), ("length", "длина"), ("quiet", "тихое начало"),
    ("pauses", "самая длинная пауза"), ("peak_pos", "пик ближе к концу"),
    ("density", "слов в секунду"),
)
MIN_SAMPLES = 30                       # столько примеров нужно, чтобы учиться
MIN_RETENTION = 20                     # досмотры Гоша вводит не всегда — им хватит и меньше
HISTORY_PATH = os.path.join(A.user_dir(), "история.json")
MODEL_PATH = os.path.join(A.user_dir(), "модель.json")


# ---------------- признаки и разбор ----------------

def clip_features(clip, segments):
    """Числа, по которым видно, чем клип хорош или плох. segments — расшифровка записи."""
    parts = clip.get("score_parts") or {}
    s, e = clip["start"], clip["end"]
    cuts = A.clip_cuts(clip)
    pieces = A.keep_pieces(s, e, cuts) or [(s, e)]
    dur = max(0.1, sum(b - a for a, b in pieces))          # без вырезанного
    words = sorted((w for seg in segments for w in seg["words"]
                    if any(a <= w["s"] < b for a, b in pieces)), key=lambda w: w["s"])
    gap, gap_at, prev = 0.0, 0.0, s
    for w in words + [{"s": e, "e": e}]:
        g = w["s"] - prev - sum(max(0.0, min(y, w["s"]) - max(x, prev)) for x, y in cuts)
        if g > gap:
            gap, gap_at = g, prev - s
        prev = max(prev, w["e"])
    h = clip.get("hook") or {}
    hook_len = (h["end"] - h["start"]) if h.get("on") and h.get("start") is not None else 0.0
    peak = clip.get("peak", (s + e) / 2)
    return {
        "loud": float(parts.get("громкость", 0)), "laugh": float(parts.get("смех", 0)),
        "mat": float(parts.get("мат", 0)), "excl": float(parts.get("восклицания", 0)),
        "speech": float(parts.get("речь", 0)), "llm": float(parts.get("модель", 0)),
        "mark": 1.0 if clip.get("marks") else 0.0, "hook": 1.0 if h.get("on") else 0.0,
        "length": round(dur + hook_len, 2), "quiet": 1.0 if clip.get("quiet_start") else 0.0,
        "pauses": round(gap, 2), "pause_at": round(gap_at, 1),
        "peak_pos": round(min(1.0, max(0.0, (peak - s) / dur)), 3),
        "density": round(len(words) / dur, 3),
    }


def retention_notes(clip, f):
    """Разбор по правилам удержания: [(хорошо: True / плохо: False / так себе: None, фраза)]."""
    notes = []
    h = clip.get("hook") or {}
    if h.get("on"):
        notes.append((True, "крючок в первые секунды — хук из яркого момента"))
    elif f["peak_pos"] <= 0.1:
        notes.append((True, "клип сразу начинается с яркого момента"))
    else:
        notes.append((False, "нет крючка в первые 1–2 с"))
    if f["quiet"]:
        notes.append((False, "тихое начало — первые 3 с без звука"))
    n = f["length"]
    if n < 15:
        notes.append((None, f"короткий — {n:.0f} с"))
    elif n <= 35:
        notes.append((True, f"хорошая длина — {n:.0f} с"))
    elif n <= 55:
        notes.append((None, f"длинноват — {n:.0f} с, до конца досматривают реже"))
    else:
        notes.append((False, f"слишком длинный — {n:.0f} с"))
    if f["pauses"] >= 3:
        notes.append((False, f"пауза {f['pauses']:.0f} с без речи "
                             f"на {f['pause_at']:.0f}-й секунде"))
    if f["peak_pos"] <= 0.4:
        notes.append((True, "эмоция в первой половине — держит внимание"))
    elif f["peak_pos"] >= 0.7:
        notes.append((False, "самое яркое — ближе к концу, до него могут не досмотреть"))
    else:
        notes.append((None, "самое яркое — в середине"))
    if f["density"] < 0.8:
        notes.append((False, f"мало речи — {f['density']:.1f} слова в секунду"))
    elif f["density"] >= 1.5:
        notes.append((True, f"живая речь — {f['density']:.1f} слова в секунду"))
    return notes


def vector(f):
    return [float(f.get(k, 0.0)) for k, _ in FEATURES]


# ---------------- просмотры: вопрос через N дней ----------------

def _parse(iso):
    try:
        return datetime.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def due_questions(days=3, now=None):
    """Клипы, которые выложены days+ дней назад и про просмотры которых ещё не спрашивали.
    [{"project", "id", "platform", "title", "days_ago"}] — по каждой площадке отдельно."""
    now = now or datetime.datetime.now()
    out = []
    for pp in A.known_projects():
        try:
            proj = A.load_project(pp)
        except (A.AutoClipError, OSError, ValueError):
            continue
        for c in proj["clips"]:
            for plat, pub in (c.get("published") or {}).items():
                if not isinstance(pub, dict) or "views" in pub or pub.get("views_skipped"):
                    continue
                date, later = _parse(pub.get("date")), _parse(pub.get("remind_after"))
                if not date or (later and later > now):
                    continue
                ago = (now - date).days
                if ago >= days:
                    out.append({"project": proj["_path"], "id": c["id"], "platform": plat,
                                "title": A.clip_title(c), "days_ago": ago})
    return sorted(out, key=lambda q: -q["days_ago"])


def _update_pub(project, cid, platform, fn):
    proj = A.load_project(project)
    clip = A.find_clip(proj, cid)
    pub = (clip.get("published") or {}).get(platform)
    if pub is None:
        raise A.AutoClipError("❌ Клип не отмечен выложенным на этой площадке.")
    fn(pub)
    A.save_project(proj)
    return proj, clip


def record_views(project, cid, platform, views, retention=None):
    """Ответ «сколько просмотров»: у клипа в project.json и в общей истории."""
    views = int(views)
    if views < 0:
        raise A.AutoClipError("❌ Просмотров не может быть меньше нуля.")
    if retention is not None:
        retention = float(retention)
        if not 0 <= retention <= 100:
            raise A.AutoClipError("❌ Процент досмотров — от 0 до 100.")

    def put(pub):
        pub.update(views=views, retention=retention, views_date=A.now_iso())
        pub.pop("remind_after", None)
    proj, clip = _update_pub(project, cid, platform, put)
    hist = load_history()
    hist.append({"date": A.now_iso(), "project": proj["_path"], "id": cid,
                 "title": A.clip_title(clip), "platform": platform,
                 "published": clip["published"][platform].get("date"),
                 "views": views, "retention": retention,
                 "features": clip.get("features"), "score": clip.get("score")})
    _write_json(HISTORY_PATH, hist)
    return clip


def snooze_views(project, cid, platform, now=None):
    """«Напомнить завтра»."""
    later = (now or datetime.datetime.now()) + datetime.timedelta(days=1)
    _update_pub(project, cid, platform,
                lambda pub: pub.update(remind_after=later.isoformat(timespec="seconds")))


def skip_views(project, cid, platform):
    """«Пропустить» — больше не спрашивать про эту площадку."""
    _update_pub(project, cid, platform, lambda pub: pub.update(views_skipped=True))


def load_history():
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ---------------- обучение ----------------

# кандидат: «Собрать» / «Удалить» — сигнал вкуса слабее, чем «Хороший» / «В корзину»:
# собирают и чтобы просто посмотреть, удаляют и просто лишнее
WEAK = 0.5


def migrate_store(extra_dirs=()):
    """Один раз перенести оценки из всех нарезок в общее хранилище (5.2)."""
    import store
    projects = list(A.known_projects())
    dirs = set(extra_dirs or ())
    try:                                                   # и папка записей OBS из настроек
        with open(A.SETTINGS_PATH, encoding="utf-8") as f:
            obs = json.load(f).get("obs_dir")
        if obs:
            dirs.add(obs)
    except (OSError, ValueError, AttributeError):
        pass
    for pp in projects:
        d = os.path.dirname(os.path.abspath(pp))
        dirs.add(os.path.dirname(d))                       # папка, где лежат нарезки
        dirs.add(os.path.dirname(os.path.dirname(d)))      # …и на уровень выше (.autoclip, 5.11)
    projects += store.find_projects(sorted(d for d in dirs if d))
    return store.migrate(projects)


def collect():
    """Примеры для обучения — только из общего хранилища оценок (5.2): удалённые записи и папки
    клипов ничего не стирают. Нарезки до 1.4.0 переносятся туда один раз."""
    import store
    migrate_store()
    return store.samples()


def _standardize(rows):
    n = len(rows)
    mean = [sum(r[i] for r in rows) / n for i in range(len(rows[0]))]
    std = [math.sqrt(sum((r[i] - mean[i]) ** 2 for r in rows) / n) or 1.0
           for i in range(len(rows[0]))]
    return mean, std, [[(r[i] - mean[i]) / std[i] for i in range(len(r))] for r in rows]


def _per_platform(samples, key, fn):
    """Нормировка внутри площадки: TikTok и YouTube в разных масштабах. Возвращает
    (строки признаков, цель — среднее z по площадкам клипа, {площадка: [среднее, разброс]})."""
    by_plat = {}
    for s in samples:
        for p, v in (s.get(key) or {}).items():
            by_plat.setdefault(p, []).append(fn(v))
    stats = {}
    for p, vals in by_plat.items():
        mean_p = sum(vals) / len(vals)
        std_p = math.sqrt(sum((x - mean_p) ** 2 for x in vals) / len(vals)) if len(vals) >= 3 else 0.0
        stats[p] = (mean_p, std_p or 1.0)
    rows, y = [], []
    for s in samples:
        if s.get(key):
            zs = [(fn(v) - stats[p][0]) / stats[p][1] for p, v in s[key].items()]
            rows.append(vector(s["features"]))
            y.append(sum(zs) / len(zs))
    return rows, y, stats


def train(save=True, samples=None):
    """Учит две простые модели: «нравится ли Гоше» (логистическая регрессия по «Хороший» /
    «В корзину») и «сколько наберёт» (линейная регрессия по log просмотров, нормированных
    по площадке). Каждая — только если примеров не меньше MIN_SAMPLES."""
    from sklearn.linear_model import LogisticRegression, Ridge
    samples = collect() if samples is None else samples
    info = {"date": A.now_iso(), "features": [k for k, _ in FEATURES],
            "n_like": sum(s["like"] is not None for s in samples),
            "n_views": sum(bool(s["views"]) for s in samples),
            "n_retention": sum(bool(s.get("retention")) for s in samples),
            "like": None, "views": None, "retention": None}

    rated = [s for s in samples if s["like"] is not None]
    if len(rated) >= MIN_SAMPLES and len({s["like"] for s in rated}) == 2:
        mean, std, X = _standardize([vector(s["features"]) for s in rated])
        m = LogisticRegression(C=1.0, max_iter=1000).fit(
            X, [s["like"] for s in rated], sample_weight=[s.get("weight", 1.0) for s in rated])
        info["like"] = {"coef": [round(float(c), 4) for c in m.coef_[0]],
                        "intercept": round(float(m.intercept_[0]), 4), "mean": mean, "std": std}

    # просмотры (log10) и досмотры (%) — нормировка внутри площадки; досмотры — второй сигнал,
    # когда Гоша их указал, со своим порогом
    for key, fn, need in (("views", lambda v: math.log10(v + 1), MIN_SAMPLES),
                          ("retention", float, MIN_RETENTION)):
        rows, y, stats = _per_platform(samples, key, fn)
        if len(rows) >= need:
            mean, std, X = _standardize(rows)
            m = Ridge(alpha=1.0).fit(X, y)
            info[key] = {"coef": [round(float(c), 4) for c in m.coef_],
                         "intercept": round(float(m.intercept_), 4), "mean": mean, "std": std,
                         "platforms": {p: [round(a, 4), round(b, 4)] for p, (a, b) in stats.items()}}
    if save:
        _write_json(MODEL_PATH, info)
    return info


def load_model():
    try:
        with open(MODEL_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def _apply(part, f):
    x = vector(f)
    return part["intercept"] + sum(c * (v - m) / s for c, v, m, s in
                                   zip(part["coef"], x, part["mean"], part["std"]))


def model_share(model):
    """Сколько веса у модели в итоговой оценке: растёт с числом примеров, но не больше 70%."""
    if not model or not (model.get("like") or model.get("views") or model.get("retention")):
        return 0.0
    n = (model.get("n_like", 0) if model.get("like") else 0) + \
        2 * (model.get("n_views", 0) if model.get("views") else 0) + \
        (model.get("n_retention", 0) if model.get("retention") else 0)
    return round(min(0.7, n / 200), 2)


def predict(f, score, model=None):
    """Итоговая оценка 0–10: смесь правил (эвристика) и модели, если она обучена.
    {"value", "heur", "model", "share", "note"}."""
    heur = _sigmoid(float(score) - 2.0)              # оценка по правилам: 2 — средний клип
    parts = []
    if model and model.get("views"):
        parts.append((0.6, _sigmoid(_apply(model["views"], f))))
    if model and model.get("retention"):
        parts.append((0.3, _sigmoid(_apply(model["retention"], f))))
    if model and model.get("like"):
        parts.append((0.4, _sigmoid(_apply(model["like"], f))))
    learned = sum(w * v for w, v in parts) / sum(w for w, _ in parts) if parts else None
    share = model_share(model) if learned is not None else 0.0
    value = (1 - share) * heur + share * (learned or 0.0)
    if learned is None:
        n_like = (model or {}).get("n_like", 0)
        n_views = (model or {}).get("n_views", 0)
        note = (f"пока по правилам — данных мало (оценок {n_like} из {MIN_SAMPLES}, "
                f"клипов с просмотрами {n_views} из {MIN_SAMPLES}, "
                f"с досмотрами {(model or {}).get('n_retention', 0)} из {MIN_RETENTION})")
    else:
        note = f"правила + модель ({int(share * 100)}% от модели)"
    return {"value": round(10 * value, 1), "heur": round(heur, 3),
            "model": None if learned is None else round(learned, 3), "share": share, "note": note}


def explain(model, top=5):
    """Что помогает и что мешает, по весам модели: {"like": [(название, вес)], "views": […]}."""
    names = dict(FEATURES)
    out = {}
    for key in ("like", "views", "retention"):
        part = (model or {}).get(key)
        if part:
            pairs = sorted(zip(model["features"], part["coef"]), key=lambda x: -abs(x[1]))
            out[key] = [(names.get(k, k), round(c, 2)) for k, c in pairs[:top] if abs(c) >= 0.01]
    return out


# ---------------- вкус для языковой модели ----------------

def taste_examples(k=5):
    """Образцы вкуса для модели — из хранилища: клипы «Выложу» и с лучшими просмотрами.
    Возвращает тексты (не больше k); taste_examples.total — сколько всего твоих оценок."""
    import store
    migrate_store()
    texts, total = store.taste(k)
    taste_examples.total = total
    return texts
