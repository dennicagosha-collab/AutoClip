"""Патч 5.7: реплики игры (английская речь героев) — не в субтитры и не в название."""
import numpy as np

import autoclip


def _seg(s, e, text):
    ws = text.split()
    step = (e - s) / len(ws)
    return {"s": s, "e": e, "text": text,
            "words": [{"s": s + i * step, "e": s + (i + 1) * step, "w": w} for i, w in enumerate(ws)]}


class FakeModel:
    """Язык по времени: кусок с 10-й секунды — английский (герой игры), остальное — русский."""
    def detect_language(self, audio):
        return getattr(self, "next", ("ru", 0.9, [("ru", 0.9)]))


def test_mark_foreign_by_language():
    segs = [_seg(1.0, 3.0, "короче смотри сюда"), _seg(10.0, 12.0, "Белый Волкер в атаке"),
            _seg(20.0, 22.0, "ну хилинг ульта gg")]
    audio = np.zeros(16000 * 30, dtype=np.float32)

    class M:
        def detect_language(self, part):
            return {0: ("ru", 0.9, [("ru", 0.9)]), 1: ("en", 0.91, [("en", 0.91), ("ru", 0.01)]),
                    2: ("en", 0.4, [("en", 0.4), ("ru", 0.3)])}[M.i.__next__()]
    M.i = iter(range(3))
    assert autoclip.mark_foreign(M(), audio, segs) == 1
    assert [s.get("lang") for s in segs] == [None, "en", None]       # свои словечки — по куску, остались
    kept = autoclip.drop_hallucinations(segs)
    assert [s["text"] for s in kept] == ["короче смотри сюда", "ну хилинг ульта gg"]


def test_known_game_lines_dropped():
    segs = [_seg(1.0, 2.5, "Fear is on cooldown."), _seg(5.0, 6.0, "да fear is on cooldown был")]
    assert [s["text"] for s in autoclip.drop_hallucinations(segs)] == ["да fear is on cooldown был"]


def test_multitrack_does_not_check_language(monkeypatch):
    called = []
    monkeypatch.setattr(autoclip, "mark_foreign", lambda *a, **k: called.append(1) or 0)
    monkeypatch.setattr(autoclip, "speech_regions", lambda a: [])
    plan = [(1, "me", {}), (2, "team", {})]
    autoclip._fill_all([], plan, {"me": np.zeros(10), "team": np.zeros(10)}, model=object())
    assert not called
    autoclip._fill_all([], [(0, "me", {})], {"me": np.zeros(10)}, model=object())
    assert called
