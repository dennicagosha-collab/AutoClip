# -*- coding: utf-8 -*-
"""Проверка границ клипов на эталоне (ПАТЧ_4, 4.1).

    py -3.13 tools\\golden_check.py                      — запись из эталона, модель как в настройках, 1 прогон
    py -3.13 tools\\golden_check.py --runs 2 --llm none  — 2 прогона, без модели

Ищет моменты на записи (без сборки видео), для каждого эталонного момента берёт клип или кандидата,
в котором лежит его опорная секунда, и печатает «эталон / получилось / ок». Плюс по всей нарезке:
средняя длина, мёртвое время, разрезанные слова — чтобы видеть, не стало ли хуже на остальных клипах.
Эталон — tests/golden/<запись>.json и правки Гоши из %APPDATA%\\AutoClip\\границы.json (4.3)."""

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import autoclip  # noqa: E402

GOLDEN_DIR = os.path.join(HERE, "tests", "golden")
RECORDINGS = r"D:\Записи"


def load_golden(path, with_meta=False):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    moments = list(data["moments"])
    try:
        import boundaries                                  # правки Гоши — тоже эталон
        moments += boundaries.golden_from_edits(data["recording"], data.get("fingerprint"))
    except Exception:
        pass
    if with_meta:
        return data["recording"], moments, data
    return data["recording"], moments


def find_video(folder, data):
    """Запись эталона: по имени, если отпечаток совпал, иначе — по отпечатку среди записей (5.1)."""
    fp = data.get("fingerprint")
    path = os.path.join(folder, data["recording"])
    if os.path.isfile(path) and (not fp or autoclip.same_recording(autoclip.fingerprint(path), fp)):
        return path
    return autoclip.find_recording(fp, [folder]) if fp else None


def _in(v, rng):
    lo, hi = rng
    return (lo is None or v >= lo - 1e-6) and (hi is None or v <= hi + 1e-6)


def judge(m, clips, cands):
    """Клип/кандидат эталонного момента и вердикт: (клип или None, вид, [провалы])."""
    t = m["anchor"]
    pool = [(c, "клип") for c in clips] + [(c, "кандидат") for c in cands]
    hit = next(((c, k) for c, k in pool if c["s"] <= t <= c["e"]), None)
    if hit is None:
        return None, "", ["момент не найден"]
    c, kind = hit
    bad = []
    if not _in(c["s"], m["start"]):
        bad.append("начало")
    if not _in(c["e"], m["end"]):
        bad.append("конец")
    a, b = m.get("must") or (None, None)
    if a is not None and not (c["s"] <= a + 0.3 and c["e"] >= b - 0.3):
        bad.append("нет нужного куска")
    return c, kind, bad


def summary(clips, words, dead):
    """Длина, мёртвое время, разрезанные слова по всем клипам нарезки."""
    if not clips:
        return {"n": 0}
    lens, dead_share, cut = [], [], 0
    for c in clips:
        s, e = c["s"], c["e"]
        lens.append(e - s)
        if dead is not None and len(dead):
            secs = range(int(s), min(len(dead), int(e)))
            dead_share.append(sum(bool(dead[i]) for i in secs) / max(1, len(secs)))
        for t in (s, e):
            if any(w["s"] + 0.01 < t < w["e"] - 0.01 for w in words):
                cut += 1
    return {"n": len(clips), "len": sum(lens) / len(lens), "min": min(lens), "max": max(lens),
            "dead": (sum(dead_share) / len(dead_share)) if dead_share else None, "cut_words": cut}


def run_once(video, moments, llm=None):
    autoclip.log = lambda m: None
    if llm:
        autoclip.CONFIG["llm"] = llm
    autoclip.process(video, analyze_only=True)
    last = autoclip.process.last
    rows = [(m, *judge(m, last["clips"], last["candidates"])) for m in moments]
    words = autoclip.all_words(last["segments"])
    return rows, summary(last["clips"], words, last.get("dead"))


def fmt(v):
    return "—" if v is None else f"{v:.1f}"


def rng(r):
    lo, hi = r
    return f"{fmt(lo) if lo is not None else '…'}–{fmt(hi) if hi is not None else '…'}"


def print_run(rows, summ, out=print):
    out("| момент | эталон начало | эталон конец | получилось | вид | итог |")
    out("|---|---|---|---|---|---|")
    ok = 0
    for m, c, kind, bad in rows:
        got = f"{c['s']:.1f}–{c['e']:.1f} ({c['e'] - c['s']:.0f} с)" if c else "—"
        ok += not bad
        out(f"| {m['name']} | {rng(m['start'])} | {rng(m['end'])} | {got} | {kind} | "
            f"{'ок' if not bad else 'НЕТ: ' + ', '.join(bad)} |")
    out(f"\nИтог: **{ok} из {len(rows)}**.")
    if summ.get("n"):
        out(f"Вся нарезка: клипов {summ['n']}, длина в среднем {summ['len']:.1f} с (от {summ['min']:.0f} до "
            f"{summ['max']:.0f}), мёртвого времени {(summ['dead'] or 0) * 100:.0f}%, разрезанных слов "
            f"{summ['cut_words']}.")
    return ok


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Проверка границ клипов на эталоне")
    ap.add_argument("golden", nargs="?", default=None, help="файл эталона (по умолчанию все в tests/golden)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--llm", default=None, help="auto / ollama / none")
    ap.add_argument("--dir", default=RECORDINGS, help="папка записей")
    a = ap.parse_args(argv)
    autoclip.SETTINGS_PATH = os.devnull                      # настройки Гоши не трогаем
    files = [a.golden] if a.golden else sorted(glob.glob(os.path.join(GOLDEN_DIR, "*.json")))
    total = good = 0
    for path in files:
        rec, moments, meta = load_golden(path, with_meta=True)
        video = find_video(a.dir, meta)
        if not video:
            print(f"Нет записи {rec} (по отпечатку тоже) — пропускаю")
            continue
        for r in range(a.runs):
            print(f"\n### {rec}, прогон {r + 1}\n")
            rows, summ = run_once(video, moments, a.llm)
            good += print_run(rows, summ)
            total += len(rows)
    print(f"\nВсего: {good} из {total}")
    return 0 if good == total else 1


if __name__ == "__main__":
    sys.exit(main())
