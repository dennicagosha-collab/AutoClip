# -*- coding: utf-8 -*-
"""Тип «Нарезка» (0.2.0): сюжетный ролик вместо клипа.

Яркий момент (кульминацию) уже нашли звук, речь и модель-судья. Модель читает расшифровку
нескольких минут вокруг него и собирает историю: какие куски привели к кульминации (завязка,
просьбы, обещания, повторяющиеся события) и сама кульминация. Всё лишнее между кусками
вырезается, склейки встык, длина — какая нужна сюжету. В начало — хук из кульминации.

Ролик — обычный клип нарезки: [s, e] от первого куска до последнего, вырезки в
overrides["cuts"]. Поэтому его можно править в редакторе, пересобирать, оценивать и выкладывать
как любой клип. Все куски — из этой же записи, хук — из оставленных кусков ролика (правило 5)."""

import re

import autoclip as A

LOOKBACK = 240.0       # столько секунд до момента модель читает в поисках завязки
AFTER = 20.0           # и столько после — договорить реакцию
LINE_GAP = 0.7         # пауза длиннее — новая строка расшифровки
LINE_WORDS = 14        # строка не длиннее стольких слов
TEXT_MAX = 7000        # символов расшифровки в запросе (Ollama — контекст 8 тыс. токенов)
MERGE_GAP = 2.0        # вырезать дырку короче этого нет смысла — куски сливаются
MAX_LEN = 180.0        # ролик не длиннее, сек (три минуты — предел TikTok/Reels без вопросов)
MAX_ANCHORS = 12       # сколько лучших моментов пробовать (каждый — один запрос к модели)
PAD_IN, PAD_OUT = 0.4, 0.6   # запас перед строкой и после неё
HOOK_MIN = 1.5         # хук не короче, сек

PROMPT = """Ты монтажёр коротких вертикальных видео (TikTok, YouTube Shorts, Reels) для русскоязычного игрового стримера.
Ниже расшифровка куска его стрима. Строки со ★ — яркий момент (кульминация), его уже нашли.

Собери из этого куска сюжетный ролик, как у блогеров: зритель, который стрим не видел, должен понять, что происходит и к чему всё шло, и досмотреть до кульминации. Только нужные куски, всё скучное между ними вырежем, склейки встык.
- pieces — строки, из которых складывается история: что привело к кульминации (завязка, обещание, просьба, ставка, спор, повторяющееся событие) и сами строки со ★. Можно цепочку событий (просили — случилось — снова — финал), можно одну завязку и момент — как лучше выходит.
- Не бери переговоры по игре, которые не двигают историю. Длина — какая нужна сюжету, без воды.
- Если с кульминацией тут ничего не связано и истории нет — story: false.
- hook — строки кульминации (самая яркая реакция), их покажем в самом начале ролика, потом история по порядку.
- Оценки готового ролика 1–10, честно (большинство историй — средние, 8–10 — только то, что реально зайдёт):
  hook — цепляет ли начало (хук из кульминации); payoff — есть ли развязка, смешной или неожиданный итог;
  standalone — понятно ли без стрима и игры; emotion — сильная эмоция (смех, ярость, шок), а не болтовня.
- title — название 3–6 слов без мата. why — одно короткое предложение: в чём история.
Мат сам по себе не делает историю смешной.

{taste}Строки (L-номер, [минуты:секунды от начала куска], кто говорит: «Я» — стример, «Друг» — тиммейт в Discord):
{lines}

Ответь ТОЛЬКО JSON:
{{"story": true, "pieces": [{{"from": 3, "to": 5}}, {{"from": 12, "to": 14}}], "hook": {{"from": 13, "to": 13}}, "hook_score": 5, "payoff": 5, "standalone": 5, "emotion": 5, "title": "", "why": ""}}"""

_RANGE = {"type": "object", "properties": {"from": {"type": "integer"}, "to": {"type": "integer"}},
          "required": ["from", "to"], "additionalProperties": False}
SCHEMA = {
    "type": "object",
    "properties": {"story": {"type": "boolean"}, "pieces": {"type": "array", "items": _RANGE},
                   "hook": _RANGE, "hook_score": {"type": "integer"}, "payoff": {"type": "integer"},
                   "standalone": {"type": "integer"}, "emotion": {"type": "integer"},
                   "title": {"type": "string"}, "why": {"type": "string"}},
    "required": ["story", "pieces", "hook", "hook_score", "payoff", "standalone", "emotion", "title", "why"],
    "additionalProperties": False,
}


def lines_of(segments, lo, hi):
    """Слова куска [lo, hi] → строки: [{"s", "e", "spk", "text", "words"}] по порядку.
    Новая строка — другой человек, пауза или длинная фраза."""
    ws = [w for w in A.all_words(segments) if lo <= w["s"] and w["e"] <= hi]
    out, cur = [], []
    for k, w in enumerate(ws):
        if cur and (w.get("spk") != cur[-1].get("spk") or w["s"] - cur[-1]["e"] >= LINE_GAP
                    or len(cur) >= LINE_WORDS):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return [{"s": c[0]["s"], "e": c[-1]["e"], "spk": c[0].get("spk", "me"),
             "text": " ".join(str(w["w"]).strip() for w in c), "words": c} for c in out]


def lines_text(lines, lo, star):
    """Строки для запроса: «L3 [1:05] Я: текст», ★ — строки кульминации."""
    rows = []
    for i, ln in enumerate(lines, 1):
        t = int(ln["s"] - lo)
        who = "Друг" if ln["spk"] == "team" else "Я"
        mark = " ★" if star[0] < ln["e"] and ln["s"] < star[1] else ""
        rows.append(f"L{i}{mark} [{t // 60}:{t % 60:02d}] {who}: {ln['text']}")
    text = "\n".join(rows)
    while len(text) > TEXT_MAX and rows:                # длинно — отрезаем самое раннее
        rows.pop(0)
        text = "\n".join(rows)
    return text


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        import json
        data = json.loads(m.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _range(r, n):
    try:
        a, b = int(r["from"]), int(r["to"])
    except (KeyError, TypeError, ValueError):
        return None
    a, b = max(1, min(a, b)), min(n, max(a, b))
    return (a - 1, b - 1) if a <= b else None


def piece_times(lines, i, j):
    """Строки i..j → (начало, конец) в записи, с запасом, не залезая на соседние строки."""
    prev_e = lines[i - 1]["e"] if i > 0 else lines[i]["s"] - PAD_IN
    nxt_s = lines[j + 1]["s"] if j + 1 < len(lines) else lines[j]["e"] + PAD_OUT
    a = max(lines[i]["s"] - PAD_IN, (prev_e + lines[i]["s"]) / 2)
    b = min(lines[j]["e"] + PAD_OUT, (lines[j]["e"] + nxt_s) / 2)
    return max(0.0, a), b


def merge(pieces, gap=MERGE_GAP):
    out = []
    for a, b in sorted(pieces):
        if out and a - out[-1][1] < gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def fit(pieces, anchor, limit=MAX_LEN):
    """Ролик длиннее limit — убираем самые ранние куски завязки (кульминацию — никогда)."""
    pieces = list(pieces)
    while sum(b - a for a, b in pieces) > limit and len(pieces) > 1:
        k = next((i for i, (a, b) in enumerate(pieces) if not (a < anchor[1] and b > anchor[0])), None)
        if k is None:
            break
        pieces.pop(k)
    return pieces


def cuts_of(pieces):
    """Куски → вырезки между ними (во времени записи), как overrides["cuts"] у клипа."""
    return [[round(pieces[k][1], 2), round(pieces[k + 1][0], 2)] for k in range(len(pieces) - 1)]


def hook_of(lines, rng, pieces, s):
    """Хук — строки кульминации: от первой до паузы, не длиннее judge.HOOK_MAX_LEN, только из
    оставленных кусков. → запись хука как у клипа."""
    import judge
    rec = {"on": False, "auto": False, "start": None, "end": None, "why": "", "text": ""}
    if not rng:
        rec["why"] = "модель не выбрала кульминацию для хука"
        return rec
    i, j = rng
    a = lines[i]["s"]
    b = lines[j]["e"]
    words = [w for ln in lines[i:j + 1] for w in ln["words"]]
    while len(words) > 1 and words[-1]["e"] - a > judge.HOOK_MAX_LEN:
        words.pop()
    b = min(words[-1]["e"] + 0.25, a + judge.HOOK_MAX_LEN)
    a = max(s, a - 0.2)
    if b - a < HOOK_MIN:                                  # «бля, мид» — 0,8 с: мало, берём реакцию дальше
        end = next((y for x, y in pieces if x <= a < y), b)
        b = min(end, a + HOOK_MIN)
    inside = any(x <= a and b <= y for x, y in pieces)
    if not inside:
        rec["why"] = "кульминация не в кусках ролика — без хука"
        return rec
    if a - s < A.HOOK_SKIP_START:
        rec["why"] = "ролик и так начинается с кульминации"
        return rec
    text = " ".join(str(w["w"]) for w in words)
    shown = " ".join(A.censor_word(w) for w in text.split())
    rec.update(auto=True, start=round(a, 2), end=round(b, 2), text=text,
               why=f"кульминация «{shown[:60]}»")
    return rec


def build_story(anchor, segments, mode, dur, taste="", cancel=None, taken=()):
    """Один сюжетный ролик вокруг момента anchor ({"s", "e", "peak", ...}). → словарь ролика
    (как найденный клип, с overrides["cuts"]) или None — истории нет или модель молчит."""
    import judge
    lo = max(0.0, anchor["s"] - LOOKBACK)
    hi = min(dur, anchor["e"] + AFTER)
    lines = lines_of(segments, lo, hi)
    if len(lines) < 3:
        return None
    prompt = PROMPT.format(taste=taste, lines=lines_text(lines, lo, (anchor["s"], anchor["e"])))
    try:
        data = _parse(judge.ask(prompt, mode, cancel, SCHEMA))
    except A.Cancelled:
        raise
    except Exception as e:
        A.warn_once(f"   ⚠️  модель не собрала сюжет ({e})")
        return None
    if not data or not data.get("story"):
        return None
    n = len(lines)
    rngs = [r for r in (_range(x, n) for x in data.get("pieces") or [] if isinstance(x, dict)) if r]
    pieces = [piece_times(lines, i, j) for i, j in rngs]
    pieces = [(a, b) for a, b in pieces                    # уже в другом ролике — не повторяем
              if not any(a < y and b > x for x, y in taken)]
    pieces.append((anchor["s"], anchor["e"]))             # кульминация — всегда в ролике
    pieces = fit(merge(pieces), (anchor["s"], anchor["e"]))
    if len(pieces) < 2:
        return None                                       # один кусок — это обычный клип, не сюжет
    s, e = pieces[0][0], pieces[-1][1]
    hook = hook_of(lines, _range(data.get("hook") or {}, n) if isinstance(data.get("hook"), dict) else None,
                   pieces, s)
    marks = {}
    for key, name in (("hook", "hook_score"), ("payoff", "payoff"), ("standalone", "standalone"),
                      ("emotion", "emotion")):
        try:
            marks[key] = max(1, min(10, int(data.get(name, data.get("score", 1)))))
        except (TypeError, ValueError):
            marks[key] = 1
    score = judge.score_of(marks)                         # как у судьи клипов: начало, развязка, …
    title = " ".join(A.censor_word(w) for w in str(data.get("title", "")).replace('"', "").split())[:60] \
        or anchor.get("title", "")                         # мат в названии — как в клипах, со звёздочками
    why = str(data.get("why", "")).strip()[:200]
    keep = sum(b - a for a, b in pieces)
    story = dict(anchor)
    story.update(
        s=round(s, 2), e=round(e, 2), auto_start=round(s, 2), auto_end=round(e, 2),
        score=float(score), title=title, reason=why or anchor.get("reason", ""),
        hook=hook, kind="story",
        overrides={"cuts": cuts_of(pieces)},
        story={"pieces": [[round(a, 2), round(b, 2)] for a, b in pieces], "why": why,
               "anchor": [anchor["s"], anchor["e"]], "length": round(keep, 1)},
        judge=dict(marks, value=float(score), why=why, title=title, hook_quote="", model=mode),
        zooms=[z for z in anchor.get("zooms", []) if any(a <= z <= b for a, b in pieces)],
    )
    story.pop("bounds_why", None)
    return story


def build_stories(found, segments, mode, dur, threshold, examples=((), ()), progress=None, cancel=None):
    """Сюжетные ролики из лучших моментов. → (ролики выше порога, моменты в кандидаты).
    Момент, который уже вошёл в чужой ролик, второй раз не берётся."""
    import judge
    taste = judge.taste_block(*examples) if examples else ""
    anchors = sorted(found, key=lambda c: -c["score"])[:MAX_ANCHORS]
    stories, used = [], []
    for k, c in enumerate(anchors):
        A.check_cancel(cancel)
        if any(a <= c["peak"] <= b for st in stories for a, b in st["story"]["pieces"]):
            used.append(c)
            continue
        if progress:
            progress(k / len(anchors), f"модель собирает сюжет {k + 1} из {len(anchors)}")
        taken = [tuple(p) for x in stories for p in x["story"]["pieces"]]
        st = build_story(c, segments, mode, dur, taste, cancel, taken)
        if st:
            A.log(f"   сюжет {A.fmt_time(st['s'])}–{A.fmt_time(st['e'])}: {len(st['story']['pieces'])} куска, "
                  f"{st['story']['length']:.0f} с, оценка {st['score']:.0f} — {st['title']}")
            if st["score"] >= threshold:
                stories.append(st)
                used.append(c)
    if progress:
        progress(1.0, "сюжеты собраны")
    stories.sort(key=lambda x: -x["score"])
    rest = [c for c in found if not any(c is u for u in used)]
    return stories, rest
