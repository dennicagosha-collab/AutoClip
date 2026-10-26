# -*- coding: utf-8 -*-
"""Умное начало и конец клипа (ПАТЧ_4, 4.2): где начинается **история** момента и где она досказана.

Начало — самое раннее из:
  - реакция: речь (слова или голос по Silero) перед пиком, без пауз длиннее 2 с;
  - голос без слов прямо перед ней (Whisper потерял фразу — например, вопрос);
  - событие в игре, из которого вырос момент: громкие секунды со всплесками (драка, смерть),
    которые кончаются не дальше 2 с до реакции;
  - одна реплика/вопрос не дальше 6 с перед этим (на что отвечают);
  - метка из OBS: её ставят после момента — история начинается до 20 с до неё.
Конец — реакция + договорил: речь после пика с паузами ≤3,5 с, но не дальше STORY_CAP после пика.
Края — в паузах, слово не режется (3.4), начало не попадает в мёртвый кусок. Не вышло — границы 1.3.2.

Языковую модель для границ пробовали (Ollama qwen3:14b) — на эталоне она давала 0 из 6, поэтому
границы считаются правилами, а модель остаётся для поиска моментов и названий (см. ОТЧЁТ_ПАТЧ_4)."""

import math
import re

import autoclip as A

TALK_GAP_BACK = 2.0      # речь перед пиком — одна реакция, пока паузы не длиннее
TALK_GAP_FWD = 3.5       # после пика — договаривает, пока паузы не длиннее
REACT_MAX = 12.0         # речь-реакция до пика — не длиннее (дальше — уже другой разговор)
VOICE_BEFORE = 4.0       # голос без слов перед реакцией не дальше — тоже реакция (потерянная фраза)
EVENT_Z, EVENT_BURST = 0.5, 6.0   # громкая секунда игры: громче фона и со всплеском
EVENT_MIN = 3            # событие — от 3 громких секунд (с пропусками до EVENT_GAP)
EVENT_GAP = 4            # затишье внутри события (драка с паузами)
EVENT_NEAR = 2.0         # событие кончается не дальше этого до реакции
CUE_BEFORE = 5.0         # реплика, на которую отвечают, — не дальше этого до начала
MARK_BACK = 20.0         # метку ставят после момента: история — до 20 с до неё
LEAD = 0.4               # запас после последнего слова
START_LEAD = 0.7         # запас перед первым словом (вдох, начало звука)
STORY_CAP = {"short": 10.0, "normal": 15.0, "long": 20.0}
MIN_LEN, MAX_LEN = 8.0, 55.0


def burst_of(loud, punch):
    """Насколько самый громкий 0,1-с кусок секунды громче фона двух минут вокруг (дБ)."""
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view
    loud = np.asarray(loud, dtype=float)
    n = len(loud)
    base = np.median(sliding_window_view(np.pad(loud, (60, 60), mode="edge"), 121), axis=1)[:n]
    p = np.asarray(punch, dtype=float)[:n]
    out = np.zeros(n)
    out[:len(p)] = p - base[:len(p)]
    return out


def talk_spans(words, voice):
    """Где говорят: слова и голос по Silero — [(начало, конец, есть ли слова)] по времени."""
    out = [(w["s"], w["e"], True) for w in words] + [(a, b, False) for a, b in voice or ()]
    return sorted(out)


def _fmt(t):
    t = int(t)
    return f"{t // 60}:{t % 60:02d}"


def reaction_start(peak, talk):
    """Начало речи-реакции у пика: идём назад от пика, пока паузы ≤ TALK_GAP_BACK.
    (начало, первое слово или None) или (None, None) — речи у пика нет."""
    before = [x for x in talk if x[0] <= peak + 1.0]
    if not before:
        return None, None
    # ближайшая к пику речь
    cur = max(before, key=lambda x: x[1])
    if peak - cur[1] > TALK_GAP_BACK + 1.0:
        return None, None
    start = cur[0]
    for a, b, _ in sorted(before, key=lambda x: -x[1]):
        if b >= start - TALK_GAP_BACK and a < start:
            start = a
    if start < peak - REACT_MAX:
        # говорит без пауз дольше REACT_MAX — реакция с первой фразы не раньше этого
        starts = [a for k, (a, b, _) in enumerate(talk)
                  if a >= peak - REACT_MAX and (k == 0 or a - max(x[1] for x in talk[:k]) >= A.PAUSE)]
        start = min(starts) if starts else peak - REACT_MAX
    return start, None


def event_start(r, loud_z, burst, words):
    """Начало события в игре, которое кончается не дальше EVENT_NEAR до реакции r. None — нет."""
    n = len(loud_z)
    hot = [i < n and loud_z[i] >= EVENT_Z and burst[i] >= EVENT_BURST for i in range(n)]
    i = int(r) - 1
    end = None
    while i >= 0 and i >= int(r) - EVENT_NEAR - 1:       # последняя громкая секунда у реакции
        if hot[i]:
            end = i
            break
        i -= 1
    if end is None:
        return None
    start, gap, k, count = end, 0, end, 0
    while k >= 0 and k > r - 40:
        if hot[k]:
            start, gap = k, 0
            count += 1
        else:
            gap += 1
            if gap > EVENT_GAP:
                break
        k -= 1
    return float(start) if count >= EVENT_MIN else None


def cue_before(t, words):
    """Реплика/вопрос, которая кончается не дальше CUE_BEFORE до t: её начало или None."""
    ws = sorted((w for w in words if w["e"] <= t + 0.05), key=lambda w: w["s"])
    if not ws or t - ws[-1]["e"] > CUE_BEFORE:
        return None
    k = len(ws) - 1
    while k > 0 and ws[k]["s"] - ws[k - 1]["e"] < A.PAUSE * 2:
        k -= 1                                            # к началу этой фразы
    return ws[k]["s"]


def game_bounds(peak, talk, loud_z, burst, dur, mark=None, length="normal"):
    """Момент без речи у пика — событие в игре: от его начала до конца (+ договорил после)."""
    n = len(loud_z)
    hot = [loud_z[i] >= EVENT_Z and burst[i] >= EVENT_BURST for i in range(n)]
    k = int(peak)
    if not (0 <= k < n) or not any(hot[max(0, k - 2):min(n, k + 3)]):
        return None
    a = b = k
    i = k - 1
    while i >= 0 and i > peak - 40 and k - i <= 60:      # назад: затишья не длиннее EVENT_GAP
        if hot[i]:
            a = i
        elif a - i > EVENT_GAP:
            break
        i -= 1
    i = k + 1
    while i < n and i < peak + 20:
        if hot[i]:
            b = i
        elif i - b > EVENT_GAP:
            break
        i += 1
    start, end = max(0.0, a - 1.0), min(dur, b + 2.0)
    if mark is not None and mark - MARK_BACK < start:
        start = max(0.0, mark - MARK_BACK)
    cap = peak + STORY_CAP.get(length, STORY_CAP["normal"])
    for x, y, _ in talk:                                  # договорил после события
        if end < x <= end + TALK_GAP_FWD and x < cap:
            end = min(cap, y + LEAD)
    if not (MIN_LEN <= end - start <= MAX_LEN):
        return None
    return start, end, f"начало: событие в игре {_fmt(a)}; конец: событие кончилось"


def story_bounds(peak, words, voice, loud_z, burst, dead, dur, mark=None, length="normal"):
    """(начало, конец, почему) истории момента или None — правила не нашли."""
    talk = talk_spans(words, voice)
    r, _ = reaction_start(peak, talk)
    why_s = None
    if r is None:
        return game_bounds(peak, talk, loud_z, burst, dur, mark, length)
    # голос без слов чуть раньше — фраза, которую Whisper потерял или сдвинул (например, «короче»)
    lost = [a for a, b, has_words in talk if not has_words and r - VOICE_BEFORE <= b <= r and a < r and
            not any(w["s"] < b and w["e"] > a for w in words)]
    if lost:
        r = min(lost)
    first_word = next((w for w in sorted(words, key=lambda w: w["s"]) if w["s"] >= r - 0.05), None)
    start = r
    why_s = (f"фраза «{str(first_word['w']).strip(' ,.!?')}»" if first_word and first_word["s"] - r < 0.5
             else "голос перед фразой")
    ev = event_start(r, loud_z, burst, words)
    if ev is not None and ev < start:
        start, why_s = ev, f"событие в игре {_fmt(ev)}"
    cue = cue_before(start, words)
    if cue is not None and cue < start:
        start, why_s = cue, why_s + ", с репликой перед ним"
    if mark is not None and mark - MARK_BACK < start:
        start, why_s = max(0.0, mark - MARK_BACK), f"метка OBS {_fmt(mark)}, история до неё"
    start = max(0.0, peak - 40.0, start - START_LEAD)
    # не начинать с мёртвого куска
    if dead is not None and len(dead):
        i = int(start)
        j = i
        while j < len(dead) and dead[j] and j < peak:
            j += 1
        if j - i >= 3:
            start = j - 1.0
    # конец: договорил
    cap = peak + STORY_CAP.get(length, STORY_CAP["normal"])
    end = peak
    for a, b, _ in talk:
        if a > cap:
            break
        if b <= end:
            continue
        if a - end <= TALK_GAP_FWD or a <= peak:
            end = max(end, min(b, cap) if a < cap else end)
    end = max(end, peak + 2.0)
    end = min(dur, end + LEAD)
    why_e = "договорил" if end < cap else f"{STORY_CAP.get(length, 15):.0f} с после пика"
    if end - start < MIN_LEN:                             # совсем короткая история — до 8 с
        end = min(dur, start + MIN_LEN)
    s, e = A.guard_edges(start, end, words, voice, max_end=max(cap, start + MIN_LEN) + 2)
    if not (MIN_LEN - 0.5 <= e - s <= MAX_LEN) or not (s <= peak <= e):
        return None
    return s, e, f"начало: {why_s}; конец: {why_e}"


def refine(clips, words, voice, loud_z, burst, dead, dur, length="normal"):
    """Начало и конец истории для найденных моментов. Меняет s/e, пишет причину в c["bounds_why"];
    где правила не нашли историю или она налезает на соседний момент — оставляет границы 1.3.2."""
    done = 0
    refine.last = []
    for c in clips:
        mark = min(c["marks"]) if c.get("marks") else None
        got = story_bounds(c["peak"], words, voice, loud_z, burst, dead, dur, mark, length)
        refine.last.append({"peak": c["peak"], "was": (c["s"], c["e"]), "got": got})
        if not got:
            continue
        s, e, why = got
        if any(o is not c and not (e <= o["s"] or s >= o["e"]) for o in clips):
            continue
        c["s"], c["e"], c["bounds_why"] = s, e, why
        done += 1
    return done


# ---------------- хук = кульминация истории (5.9) ----------------

HOOK_MIN, HOOK_MAX = 1.5, 3.0     # длина хука
HOOK_NEAR = 6.0                   # кульминация — не дальше этого от пика момента
HOOK_SKIP = 3.0                   # в первых секундах клипа хук не нужен — клип и так с неё начинается
_CLAUSE_END = re.compile(r"[,.!?…;:]$")
_SENT_END = re.compile(r"[.!?…]$")


def clauses(words):
    """Слова → куски фраз до запятой/точки или паузы: [(начало, конец, слова, конец_предложения)]."""
    out, cur = [], []
    ws = sorted(words, key=lambda w: w["s"])
    for k, w in enumerate(ws):
        cur.append(w)
        nxt = ws[k + 1] if k + 1 < len(ws) else None
        text = str(w["w"]).strip()
        gap = (nxt["s"] - w["e"]) if nxt else 9.0
        if _CLAUSE_END.search(text) or gap >= 0.35:
            out.append((cur[0]["s"], cur[-1]["e"], cur, bool(_SENT_END.search(text)) or gap >= 0.6))
            cur = []
    if cur:
        out.append((cur[0]["s"], cur[-1]["e"], cur, True))
    return out


def culmination_hook(s, e, peak, words, voice, reaction, at=None):
    """Хук — кульминация истории: целая ключевая фраза или реакция (1,5–3 с) у самого яркого места
    речи рядом с пиком. Никаких вздохов, обрывков и звука игры без реакции: не нашлась — None.
    → (начало, конец, что) во времени записи; слово не режется."""
    ws = sorted((w for w in words if w["s"] >= s - 0.01 and w["e"] <= e + 0.01 and str(w["w"]).strip()),
                key=lambda w: w["s"])
    if not ws:
        return None
    if reaction is None or not len(reaction):
        reaction = [1.0] * (int(e) + 2)
    n = len(reaction)
    talk = [False] * n
    for w in ws:
        for i in range(max(0, int(w["s"])), min(n, int(math.ceil(w["e"])))):
            talk[i] = True
    for a, b in voice or ():
        for i in range(max(0, int(a)), min(n, int(math.ceil(b)))):
            talk[i] = True
    if at is not None:                                   # «Хук отсюда»: у этого места
        lo, hi = int(at) - 1, int(at) + 1
    else:
        lo, hi = int(math.ceil(max(s + HOOK_SKIP, peak - HOOK_NEAR))), int(min(e - 0.5, peak + HOOK_NEAR))
    secs = [i for i in range(max(0, lo), min(n, hi + 1)) if talk[i]]
    if not secs:
        return None
    worded = set()
    for w in ws:
        worded.update(range(max(0, int(w["s"])), min(n, int(math.ceil(w["e"])))))
    # самое яркое место речи; голос без слов (смех, крик) — реакция, ему чуть больше веса
    c = (min(secs, key=lambda i: abs(i + 0.5 - at)) if at is not None else
         max(secs, key=lambda i: reaction[i] + (0.3 if i not in worded else 0.0)))
    cl = clauses(ws)
    best = None
    for i in range(len(cl)):
        for j in range(i, len(cl)):
            a, b = cl[i][0], cl[j][1]
            if j > i and cl[j][0] - cl[j - 1][1] > 0.8:
                break                                       # между кусками долгая пауза — не одна фраза
            if b - a > HOOK_MAX + 0.01:
                break
            ext = b
            if b - a < HOOK_MIN:
                # коротко — добавить смех/крик сразу после (голос без слов)
                nxt_w = next((w["s"] for w in ws if w["s"] >= b - 0.01 and w["e"] > b + 0.05), math.inf)
                for va, vb in sorted(voice or ()):
                    if va <= ext + 0.4 and vb > ext:            # голос тянется дальше слов — смех, крик
                        ext = min(vb, a + HOOK_MAX, nxt_w - 0.05)
                if ext - a < HOOK_MIN:
                    continue
            if not (a <= c + 1 and ext >= c):
                continue                                    # должна быть кульминация
            speech = sum(w["e"] - w["s"] for k in range(i, j + 1) for w in cl[k][2])
            nwords = sum(len(cl[k][2]) for k in range(i, j + 1))
            if speech < 0.5 or nwords < 2:
                continue                                    # вздох, кашель, обрывок — нет
            seconds = range(max(0, int(a)), min(n, int(math.ceil(ext))))
            score = sum(reaction[k] for k in seconds) / max(1, len(seconds))
            score += 0.5 * (i == 0 or cl[i - 1][3])         # начинается с начала предложения
            score += 0.5 * cl[j][3]                          # и кончается его концом
            score -= 0.1 * abs((a + ext) / 2 - (c + 0.5))
            if best is None or score > best[0]:
                best = (score, a, ext, i, j)
    if not best:
        return None
    _, a, b, i, j = best
    prev = cl[i - 1][2][-1] if i else None
    nxt = next((w for w in ws if w["s"] >= b - 0.01 and w not in cl[j][2]), None)
    hs = max(s, A.pad_before(cl[i][2][0], prev))
    he = min(e, A.pad_after(cl[j][2][-1], nxt) if b <= cl[j][1] + 0.01 else b + 0.1)
    text = " ".join(str(w["w"]).strip() for k in range(i, j + 1) for w in cl[k][2])
    return round(hs, 2), round(he, 2), text
