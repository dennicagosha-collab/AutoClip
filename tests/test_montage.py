"""0.2.0, тип «Нарезка»: модель собирает сюжетный ролик из кусков, которые привели к кульминации.
Куски — только из этой записи, кульминация всегда в ролике, хук — из оставленных кусков."""
import json

import autoclip
import montage


def _seg(spk, words):
    ws = [{"s": a, "e": b, "w": w, "spk": spk} for a, b, w in words]
    return {"s": ws[0]["s"], "e": ws[-1]["e"], "spk": spk, "text": " ".join(w["w"] for w in ws), "words": ws}


SEGS = [_seg("me", [(100.0, 100.4, "пойду"), (100.5, 100.9, "один"), (101.0, 101.4, "на"), (101.5, 102.0, "босса")]),
        _seg("team", [(110.0, 110.5, "куда"), (110.6, 111.0, "купить"), (111.1, 111.6, "броню")]),     # вода
        _seg("me", [(150.0, 150.4, "у"), (150.5, 150.8, "меня"), (150.9, 151.3, "двести"), (151.4, 151.8, "хп")]),
        _seg("team", [(170.0, 170.5, "иди"), (170.6, 171.0, "налево")]),
        _seg("me", [(200.0, 200.5, "ДА"), (200.6, 201.0, "НУ"), (201.1, 201.8, "НАХРЕН"), (201.9, 202.6, "умер"),
                    (202.8, 203.4, "опять")])]
ANCHOR = {"s": 196.0, "e": 206.0, "peak": 201.0, "score": 8.0, "title": "Умер", "reason": "", "zooms": [201.0, 120.0],
          "parts": {}}


def _ask(answer):
    def ask(prompt, mode, cancel=None, schema=None):
        ask.prompt = prompt
        return json.dumps(answer)
    return ask


def test_lines_split_by_speaker_and_pause():
    lines = montage.lines_of(SEGS, 0, 300)
    assert [ln["text"] for ln in lines][:2] == ["пойду один на босса", "куда купить броню"]
    assert lines[1]["spk"] == "team"
    text = montage.lines_text(lines, 0, (196, 206))
    assert "L1 [1:40] Я: пойду один на босса" in text and "L5 ★" in text and "Друг: куда" in text


def test_build_story(monkeypatch):
    import judge
    monkeypatch.setattr(judge, "ask", _ask({"story": True, "pieces": [{"from": 1, "to": 1}, {"from": 3, "to": 3}],
                                            "hook": {"from": 5, "to": 5}, "hook_score": 8, "payoff": 8,
                                            "standalone": 8, "emotion": 8,
                                            "title": "Один на босса", "why": "обещал и умер"}))
    st = montage.build_story(ANCHOR, SEGS, "ollama", 400)
    pieces = st["story"]["pieces"]
    assert len(pieces) == 3 and pieces[0][0] < 100.0 and pieces[1][0] < 150.0 < pieces[1][1]
    assert pieces[-1] == [196.0, 206.0]                                   # кульминация — всегда в ролике
    assert st["s"] == pieces[0][0] and st["e"] == 206.0 and st["kind"] == "story"
    cuts = st["overrides"]["cuts"]
    assert len(cuts) == 2 and autoclip.keep_pieces(st["s"], st["e"], cuts) == [tuple(p) for p in pieces]
    assert not any(a < 111.0 and b > 110.0 for a, b in pieces)          # «куда купить броню» вырезано
    h = st["hook"]
    assert h["auto"] and 196.0 <= h["start"] < h["end"] <= 206.0 and h["end"] - h["start"] > 3.0   # вся реакция
    assert autoclip.hook_span(autoclip.make_clip_record(st, 1, "x.mp4"), {"hook": "auto"}) == (h["start"], h["end"])
    assert st["score"] == 8.0 and st["title"] == "Один на босса"
    assert st["zooms"] == [201.0]                                         # зум из вырезанного куска — нет


def test_no_story(monkeypatch):
    import judge
    monkeypatch.setattr(judge, "ask", _ask({"story": False, "pieces": [], "hook": {"from": 1, "to": 1},
                                            "score": 3, "title": "", "why": ""}))
    assert montage.build_story(ANCHOR, SEGS, "ollama", 400) is None
    monkeypatch.setattr(judge, "ask", _ask({"story": True, "pieces": [{"from": 5, "to": 5}],
                                            "hook": {"from": 5, "to": 5}, "score": 9, "title": "т", "why": ""}))
    assert montage.build_story(ANCHOR, SEGS, "ollama", 400) is None      # один кусок — это клип, не сюжет


def test_bad_line_numbers_are_safe(monkeypatch):
    import judge
    monkeypatch.setattr(judge, "ask", _ask({"story": True, "pieces": [{"from": 99, "to": -4}, {"from": "x", "to": 2}],
                                            "hook": {"from": 0, "to": 0}, "score": 7, "title": "т", "why": ""}))
    st = montage.build_story(ANCHOR, SEGS, "ollama", 400)
    assert st is None or all(0 <= a < b <= 400 for a, b in st["story"]["pieces"])


def test_fit_drops_earliest_setup_not_climax():
    pieces = [(0.0, 100.0), (150.0, 250.0), (300.0, 310.0)]
    got = montage.fit(pieces, (300.0, 310.0), limit=150.0)
    assert got == [(150.0, 250.0), (300.0, 310.0)]


def test_build_stories_threshold_and_reuse(monkeypatch):
    import judge
    monkeypatch.setattr(judge, "ask", _ask({"story": True, "pieces": [{"from": 1, "to": 1}],
                                            "hook": {"from": 5, "to": 5}, "score": 7, "title": "т", "why": "в"}))
    inner = dict(ANCHOR, s=99.0, e=103.0, peak=101.0, score=6.0)         # уже внутри сюжета — второй раз не берём
    weak = dict(ANCHOR, s=700.0, e=710.0, peak=705.0, score=5.5)
    found = [ANCHOR, inner, weak]
    stories, rest = montage.build_stories(found, SEGS, "ollama", 800, 5.0)
    assert len(stories) == 1 and stories[0]["kind"] == "story"
    assert inner not in rest and weak in rest                              # у weak нет слов — в кандидаты


def test_clip_tag_story():
    rec = autoclip.make_clip_record(dict(ANCHOR, kind="story", overrides={"cuts": [[103.0, 149.0]]},
                                         story={"pieces": []}, hook=None), 1, "x.mp4")
    assert "сюжет" in autoclip.clip_tags(rec) and rec["overrides"]["cuts"] == [[103.0, 149.0]]


def test_second_story_does_not_repeat_pieces(monkeypatch):
    import judge
    monkeypatch.setattr(judge, "ask", _ask({"story": True, "pieces": [{"from": 1, "to": 1}],
                                            "hook": {"from": 1, "to": 1}, "score": 7, "title": "т", "why": ""}))
    taken = [(99.0, 103.0)]
    assert montage.build_story(ANCHOR, SEGS, "ollama", 400, taken=taken) is None   # единственный кусок уже занят


def test_title_censored_and_hook_not_too_short(monkeypatch):
    import judge
    monkeypatch.setattr(judge, "ask", _ask({"story": True, "pieces": [{"from": 1, "to": 1}],
                                            "hook": {"from": 5, "to": 5}, "hook_score": 7, "payoff": 7,
                                            "standalone": 7, "emotion": 7, "title": "Пиздец у босса", "why": ""}))
    segs = SEGS[:4] + [_seg("me", [(200.0, 200.4, "бля"), (200.5, 200.8, "мид")])]
    st = montage.build_story(ANCHOR, segs, "ollama", 400)
    assert "Пиздец" not in st["title"] and "босса" in st["title"]
    assert st["hook"]["end"] - st["hook"]["start"] >= montage.HOOK_MIN - 0.01
