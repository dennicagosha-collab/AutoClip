# -*- coding: utf-8 -*-
"""Судья клипов: языковая модель оценивает каждое найденное место как отдельный ролик для
TikTok / Shorts / Reels — по правилам коротких видео, а не по громкости и мату.

Звук, смех и мат только находят места-кандидаты (score_timeline). Дальше модель читает текст
каждого места (с репликой перед ним) и ставит четыре оценки 1–10:
  начало — цепляет ли первые 2 секунды; развязка — есть ли панчлайн или неожиданный итог;
  понятность — ясно ли без контекста стрима и игры; эмоция — смех, ярость, шок, а не болтовня.
Итог — взвешенная сумма (0–10), одна фраза «почему» и фраза для хука (дословно из этого же
клипа, правило 5; пусто — хук не нужен). Примеры вкуса — клипы, которые Гоша взял и выкинул."""

import json
import re

import autoclip as A

WEIGHTS = {"hook": 0.30, "payoff": 0.35, "standalone": 0.15, "emotion": 0.20}
NAMES = {"hook": "начало", "payoff": "развязка", "standalone": "понятность", "emotion": "эмоция"}
BATCH = 4                    # мест в одном запросе (Ollama — контекст 8 тыс. токенов)
CONTEXT_BEFORE = 12.0        # столько секунд перед клипом — модели для понимания, не в оценку
TEXT_MAX = 1400              # символов текста клипа в запросе
HOOK_MAX_LEN = 7.0           # хук — вся реакция кульминации, но не длиннее этого, сек (0.2.0)
HOOK_GAP = 0.6               # реакция идёт, пока паузы между словами короче этого

PROMPT = """Ты — редактор коротких вертикальных видео (TikTok, YouTube Shorts, Reels) для русскоязычного игрового стримера.
Ниже фрагменты его стрима. Оцени каждый как ОТДЕЛЬНОЕ короткое видео для зрителя, который стрим не смотрел и в игру не играл.

Оценки 1–10:
- hook: первые 2 секунды заставляют остаться (резкая фраза, крик, интрига). Вялое начало, «короче», «так» — 1–3.
- payoff: есть развязка — панчлайн, смешной или неожиданный итог, яркая реакция на событие. Нет итога — 1–3.
- standalone: понятно без контекста игры и стрима. Термины игры, тактика, покупки — 1–3.
- emotion: сильная эмоция — смех, ярость, шок, восторг. Спокойная болтовня — 1–3.
Мат сам по себе НЕ делает фрагмент смешным и не повышает оценки. Обычные игровые переговоры (куда идти, что купить, кто где) — низкие оценки.
Ставь честно: большинство фрагментов стрима — средние или слабые, 8–10 — только то, что реально зайдёт.

hook_quote — кульминация фрагмента: дословная цитата 2–8 слов (как в тексте), с которой начинается самая яркая реакция или фраза. Её покажем в самом начале ролика как хук, потом ролик с начала. Пустая строка, если явной кульминации нет или фрагмент и так с неё начинается.
why — одно короткое предложение по-русски: почему такие оценки (что цепляет или чего не хватает).
title — название ролика 3–6 слов, без мата.

{taste}Фрагменты (в квадратных скобках — секунда от начала фрагмента; «Я» — стример, «Друг» — тиммейт в Discord):
{clips}

Ответь ТОЛЬКО JSON:
{{"clips": [{{"id": 1, "hook": 5, "payoff": 5, "standalone": 5, "emotion": 5, "hook_quote": "", "why": "", "title": ""}}]}}"""

SCHEMA = {
    "type": "object",
    "properties": {"clips": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "hook": {"type": "integer"}, "payoff": {"type": "integer"},
                       "standalone": {"type": "integer"}, "emotion": {"type": "integer"},
                       "hook_quote": {"type": "string"}, "why": {"type": "string"}, "title": {"type": "string"}},
        "required": ["id", "hook", "payoff", "standalone", "emotion", "hook_quote", "why", "title"],
        "additionalProperties": False}}},
    "required": ["clips"],
    "additionalProperties": False,
}


def taste_block(good, bad):
    """Примеры вкуса: что Гоша взял («Выложу») и что выкинул («Не то»)."""
    out = ""
    if good:
        out += "Такие фрагменты стример ВЗЯЛ (ориентир для высоких оценок):\n" + \
               "\n".join(f"- «{t[:220]}»" for t in good) + "\n\n"
    if bad:
        out += "Такие фрагменты стример ВЫКИНУЛ (ориентир для низких оценок):\n" + \
               "\n".join(f"- «{t[:220]}»" for t in bad) + "\n\n"
    return out


def clip_text(segments, s, e):
    """Текст места для модели: реплика перед ним (контекст) и сам клип по фразам, с секундами."""
    before = A.text_between(segments, max(0.0, s - CONTEXT_BEFORE), s).strip()
    lines = []
    for sg in sorted(segments, key=lambda x: x["s"]):
        ws = [w for w in sg["words"] if s - 0.05 <= w["s"] and w["e"] <= e + 0.05]
        if not ws or sg.get("lang"):
            continue
        who = "Друг" if sg.get("spk", ws[0].get("spk", "me")) == "team" else "Я"
        lines.append(f"[{ws[0]['s'] - s:.0f}] {who}: " + " ".join(w["w"] for w in ws))
    text = "\n".join(lines)[:TEXT_MAX]
    return (f"(перед этим: …{before[-200:]})\n" if before else "") + (text or "(без слов — только звук)")


def score_of(r):
    return round(sum(WEIGHTS[k] * max(1, min(10, int(r.get(k, 1)))) for k in WEIGHTS), 1)


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    items = data.get("clips", []) if isinstance(data, dict) else []
    return [x for x in items if isinstance(x, dict) and "id" in x]


def _ask_claude(prompt, schema=None):
    """Судья через Claude API: ответ строго по схеме (structured outputs), отказ — пустой ответ."""
    body = {"model": A.CONFIG["anthropic_judge_model"], "max_tokens": 16000,
            "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": schema or SCHEMA}},
            "fallbacks": "default",
            "messages": [{"role": "user", "content": prompt}]}
    headers = {"x-api-key": A.anthropic_key(), "anthropic-version": "2023-06-01",
               "anthropic-beta": "server-side-fallback-2026-07-01"}
    r = A._http_json("https://api.anthropic.com/v1/messages", body, headers, timeout=300)
    if r.get("stop_reason") == "refusal":
        return ""
    return "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")


def ask(prompt, mode, cancel=None, schema=None):
    if mode == "anthropic":
        return _ask_claude(prompt, schema)
    return A._ask_llm(prompt, mode, cancel=cancel)


def judge_clips(found, segments, mode, examples=((), ()), progress=None, cancel=None):
    """Оценить места моделью. Каждому оценённому: c["judge"] = {оценки, value, why, hook_quote},
    c["score"] = value (0–10). Не оценённые (ниже judge_max по звуку, модель не ответила) —
    c["judge"] нет, оценка прежняя. → сколько оценено."""
    if mode == "none" or not found:
        return 0
    good, bad = examples
    taste = taste_block(good, bad)
    order = sorted(found, key=lambda c: -c["score"])[:int(A.CONFIG.get("judge_max", 40))]
    done = 0
    for k in range(0, len(order), BATCH):
        A.check_cancel(cancel)
        part = order[k:k + BATCH]
        if progress:
            progress(k / len(order), f"модель оценивает места {k + 1}–{k + len(part)} из {len(order)}")
        clips = "\n\n".join(f"#{i} ({c['e'] - c['s']:.0f} с)\n{clip_text(segments, c['s'], c['e'])}"
                            for i, c in enumerate(part, 1))
        prompt = PROMPT.format(taste=taste, clips=clips)
        try:
            items = _parse(ask(prompt, mode, cancel))
        except A.Cancelled:
            raise
        except Exception as e:
            A.warn_once(f"   ⚠️  модель-судья не ответила ({e}) — эти места по звуку")
            continue
        for it in items:
            try:
                c = part[int(it["id"]) - 1]
            except (ValueError, IndexError, TypeError):
                continue
            r = {key: max(1, min(10, int(it.get(key, 1)))) for key in WEIGHTS}
            r["value"] = score_of(r)
            r["why"] = str(it.get("why", "")).strip()[:200]
            r["hook_quote"] = str(it.get("hook_quote", "")).strip()[:80]
            r["title"] = " ".join(A.censor_word(w) for w in str(it.get("title", "")).split())[:60]   # без мата в имени
            r["model"] = mode
            c["judge"] = r
            c["sound_score"] = round(float(c["score"]), 2)
            c["score"] = r["value"]
            if r["why"]:
                c["reason"] = r["why"]
            done += 1
    if progress:
        progress(1.0, "модель оценила места")
    return done


def judge_line(j):
    """«начало 7 · развязка 8 · понятность 5 · эмоция 9» — для карточки клипа."""
    return " · ".join(f"{NAMES[k]} {j[k]}" for k in WEIGHTS if k in j)


def _norm(w):
    return A.clean_word(w).replace("*", "")


def hook_from_quote(quote, s, e, segments):
    """Хук по цитате судьи: те же слова в этом клипе (правило 5) → (начало, конец) или None.
    Слова ищутся подряд, не меньше 60% совпадений; хук не длиннее HOOK_MAX_LEN, края — в паузах."""
    q = [_norm(x) for x in quote.split() if _norm(x)]
    if not q:
        return None
    words = [w for w in A.all_words(segments) if s - 0.05 <= w["s"] and w["e"] <= e + 0.05]
    best = None
    for i in range(len(words)):
        win = words[i:i + len(q)]
        if len(win) < max(1, len(q) - 1):
            break
        hit = sum(1 for a, b in zip(q, (_norm(w["w"]) for w in win)) if a and b and (a == b or a[:4] == b[:4]))
        if hit / len(q) >= 0.6 and (best is None or hit > best[0]):
            best = (hit, i, win)
    if best is None:
        return None
    _, i, win = best
    j = i + len(win)                        # реакция продолжается — хук до паузы, а не 1–3 с
    while j < len(words) and words[j]["s"] - words[j - 1]["e"] < HOOK_GAP and             words[j].get("spk") == win[-1].get("spk") and words[j]["e"] - win[0]["s"] <= HOOK_MAX_LEN:
        win = win + [words[j]]
        j += 1
    while len(win) > 1 and win[-1]["e"] - win[0]["s"] > HOOK_MAX_LEN:
        win = win[:-1]
    prev = words[i - 1] if i else None
    nxt_i = i + len(win)
    nxt = words[nxt_i] if nxt_i < len(words) else None
    a = max(s, A.pad_before(win[0], prev))
    b = min(e, A.pad_after(win[-1], nxt))
    if b - a < 0.5:
        return None
    return round(a, 2), round(b, 2)


def decide_hook(c, segments):
    """Хук по решению судьи. None — судьи не было (решает старое правило)."""
    j = c.get("judge")
    if not j:
        return None
    rec = {"on": False, "auto": False, "start": None, "end": None, "why": "", "text": ""}
    q = j.get("hook_quote", "")
    if not q:
        rec["why"] = "модель: хук не нужен — нет фразы, которая цепляет и не раскрывает развязку"
        return rec
    span = hook_from_quote(q, c["s"], c["e"], segments)
    if span is None:
        rec["why"] = f"модель предложила «{q}», но этих слов нет в клипе — без хука"
        return rec
    if span[0] - c["s"] < A.HOOK_SKIP_START:
        rec["why"] = f"клип и так начинается с «{q}»"
        return rec
    rec.update(auto=True, start=span[0], end=span[1],
               why=f"модель: кульминация «{q}»",
               text=A.text_between(segments, span[0], span[1]))
    return rec
