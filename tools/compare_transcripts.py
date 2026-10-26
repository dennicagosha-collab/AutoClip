# -*- coding: utf-8 -*-
"""Сравнение двух расшифровок одной записи (ПАТЧ_4, 4.4): где одна нашла фразу, а в другой на этом месте
пусто. По умолчанию — старая (<запись>.transcript.json, v1) против новой (.transcript.v2.json).

    py -3.13 tools\\compare_transcripts.py "D:\\Записи\\запись.mp4" [--list]"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import autoclip  # noqa: E402


def phrases(segments):
    return [(sg["s"], sg["e"], [w for w in sg.get("words", []) if str(w["w"]).strip()])
            for sg in segments if sg.get("words")]


def missing(a, b, pad=0.3):
    """Фразы из a, на месте которых в b нет ни одного слова: [(начало, конец, текст)]."""
    bw = sorted((w["s"], w["e"]) for sg in b for w in sg.get("words", []))
    out = []
    import bisect
    starts = [x for x, _ in bw]
    for s, e, ws in phrases(a):
        j = max(0, bisect.bisect_left(starts, s - 30))
        if not any(x < e + pad and y > s - pad for x, y in bw[j:j + 400] if x < e + 30):
            out.append((s, e, " ".join(str(w["w"]).strip() for w in ws)))
    return out


def compare(a, b):
    lost, new = missing(a, b), missing(b, a)
    return {"lost": lost, "new": new, "lost_words": sum(len(t.split()) for _, _, t in lost),
            "new_words": sum(len(t.split()) for _, _, t in new),
            "words_a": sum(len(ws) for _, _, ws in phrases(a)), "words_b": sum(len(ws) for _, _, ws in phrases(b))}


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--a", default=None, help="первая расшифровка (по умолчанию v1)")
    ap.add_argument("--b", default=None, help="вторая расшифровка (по умолчанию v2)")
    ap.add_argument("--list", action="store_true")
    x = ap.parse_args(argv)
    v2, v1 = autoclip.find_cache(x.video)
    a = autoclip.read_transcript(x.a or v1)
    b = autoclip.read_transcript(x.b or v2)
    r = compare(a, b)
    print(f"слов: A {r['words_a']}, B {r['words_b']}")
    print(f"фраз из A, которых нет в B: {len(r['lost'])} ({r['lost_words']} слов)")
    print(f"фраз из B, которых нет в A: {len(r['new'])} ({r['new_words']} слов)")
    if x.list:
        for name, rows in (("нет в B", r["lost"]), ("нет в A", r["new"])):
            print(f"\n{name}:")
            for s, e, t in rows:
                print(f"  {autoclip.fmt_time(s)} {s:7.1f}–{e:7.1f}  {t[:90]}")


if __name__ == "__main__":
    main()
