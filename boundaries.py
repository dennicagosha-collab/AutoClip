# -*- coding: utf-8 -*-
"""Учиться на правках границ Гоши (ПАТЧ_4, 4.3).

Когда Гоша двигает начало/конец клипа или вырезает кусок, запоминаем «Гоша поставил так» —
время в записи, границы программы, текст рядом — в %APPDATA%\\AutoClip\\границы.json. Эти примеры:
  (а) пополняют эталон для его записей (tools/golden_check.py берёт их тоже);
  (б) после ≥10 примеров дают поправку по умолчанию — средний (медианный) сдвиг начала и конца,
      с объяснением в карточке клипа. Никакого чёрного ящика: только сдвиг на N секунд."""

import json
import os
import statistics

import autoclip as A

PATH = os.path.join(A.user_dir(), "границы.json")
MIN_EDITS = 10          # поправка — только после стольких правок
MIN_SHIFT = 0.5         # сдвиг меньше — не считается поправкой
MAX_SHIFT = 8.0         # и не больше этого (защита от одной странной правки)


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items):
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)


def record_edit(proj, clip, new_start, new_end, cuts=None, segments=None):
    """Запомнить правку границ клипа. Границы программы — те, что она поставила при нарезке."""
    prog_s = clip.get("auto_start", clip["start"])
    prog_e = clip.get("auto_end", clip["end"])
    text = ""
    if segments:
        text = A.text_between(segments, max(0.0, new_start - 8), new_end + 8)[:400]
    item = {"date": A.now_iso(), "recording": os.path.basename(proj.get("source", "")),
            "project": proj.get("_path", ""), "clip": clip.get("id"), "peak": clip.get("peak"),
            "program": [round(prog_s, 2), round(prog_e, 2)],
            "gosha": [round(float(new_start), 2), round(float(new_end), 2)],
            "cuts": [list(map(float, c)) for c in (cuts or [])], "text": text,
            "bounds_why": clip.get("bounds_why", "")}
    items = [x for x in load() if not (x.get("project") == item["project"] and x.get("clip") == item["clip"])]
    items.append(item)                                   # у клипа — только последняя правка
    try:
        _save(items)
    except OSError:
        pass
    return item


def golden_from_edits(recording, tol=1.5):
    """Правки Гоши для записи — в виде эталонных моментов для golden_check."""
    out = []
    for x in load():
        if x.get("recording") != recording:
            continue
        s, e = x["gosha"]
        anchor = x.get("peak") if x.get("peak") is not None and s <= x["peak"] <= e else (s + e) / 2
        out.append({"name": f"правка Гоши {A.fmt_time(s)}", "anchor": anchor,
                    "start": [s - tol, s + tol], "end": [e - tol, e + tol], "must": [s + tol, e - tol],
                    "why": "Гоша поставил так"})
    return out


def default_shift(items=None):
    """Поправка по правкам Гоши: (сдвиг начала, сдвиг конца, сколько правок). Сдвиги — None, пока
    правок меньше MIN_EDITS или сдвиг незаметный."""
    items = load() if items is None else items
    ds = [x["gosha"][0] - x["program"][0] for x in items if x.get("program") and x.get("gosha")]
    de = [x["gosha"][1] - x["program"][1] for x in items if x.get("program") and x.get("gosha")]
    if len(ds) < MIN_EDITS:
        return None, None, len(ds)

    def pick(v):
        m = statistics.median(v)
        return round(max(-MAX_SHIFT, min(MAX_SHIFT, m)), 1) if abs(m) >= MIN_SHIFT else None
    return pick(ds), pick(de), len(ds)


def apply_shift(s, e, peak, words, voice, shift):
    """Сдвинуть границы по поправке; край — не в слове, пик остаётся в клипе. (s, e, пояснение)."""
    ss, se, n = shift
    note = []
    if ss is not None:
        s = min(peak - 1.0, max(0.0, s + ss))
        note.append(f"начало {'позже' if ss > 0 else 'раньше'} на {abs(ss):.1f} с")
    if se is not None:
        e = max(peak + 1.0, e + se)
        note.append(f"конец {'позже' if se > 0 else 'раньше'} на {abs(se):.1f} с")
    if not note:
        return s, e, ""
    s, e = A.guard_edges(s, e, words, voice)
    return s, e, f"{', '.join(note)} — по твоим правкам ({n})"
