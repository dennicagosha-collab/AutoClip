"""Патч 3.2: «пусто» — нет речи И тихо в игре; режется только мёртвое."""
import numpy as np

import autoclip


def _dead(n, loud_z, burst, voice=(), words=()):
    loud = np.full(n, -30.0, dtype=np.float32)
    punch = loud + np.asarray(burst, dtype=np.float32)
    return autoclip.dead_seconds(loud, punch, np.asarray(loud_z), list(voice), list(words))


def test_fight_without_words_stays():
    # 0–20 с: драка без слов (громко, удары), 20–23 — реплика, пик на 21
    z = [0.5] * 40
    burst = [8.0] * 40
    dead = _dead(40, z, burst, voice=[(20, 23)])
    assert autoclip.trim_dead(0.0, 30.0, 21.0, dead) == (0.0, 30.0)


def test_quiet_running_cut():
    # 0–10 с: беготня — нет речи, тихо, без всплесков; 10–25 — разговор, пик на 15
    z = [-0.5] * 10 + [0.5] * 15 + [-0.5] * 15
    burst = [1.0] * 10 + [8.0] * 15 + [1.0] * 15
    dead = _dead(40, z, burst, voice=[(10, 25)])
    s, e = autoclip.trim_dead(0.0, 40.0, 15.0, dead)
    assert s == 9.0                                   # за 1 с до конца мёртвого куска
    assert e == 25.5                                  # хвост в мёртвое время не тянем


def test_question_answer_not_split():
    # вопрос 2–4 с, пауза 4–6 (тихо, но <6 с), ответ 6–9, пик на 7 — начало не трогаем
    z = [-0.5] * 30
    burst = [0.0] * 30
    words = [{"s": 2.0, "e": 4.0, "w": "дочь"}, {"s": 6.0, "e": 9.0, "w": "да"}]
    dead = _dead(30, z, burst, voice=[(2, 4), (6, 9)], words=words)
    s, _ = autoclip.trim_dead(1.0, 25.0, 7.0, dead)
    assert s == 1.0


def test_talk_after_peak_continues():
    # после пика разговор с паузами по 2 с (не мёртвые ≥3 с) до 24-й секунды
    z = [-0.5] * 40
    burst = [0.0] * 40
    voice = [(10, 12), (14, 16), (18, 20), (22, 24)]
    dead = _dead(40, z, burst, voice=voice)
    _, e = autoclip.trim_dead(0.0, 35.0, 11.0, dead)
    assert e == 24.5


def test_short_clip_not_shrunk_below_min():
    z = [-0.5] * 20
    dead = _dead(20, z, [0.0] * 20, voice=[(8, 10)])
    assert autoclip.trim_dead(0.0, 12.0, 9.0, dead) == (0.0, 12.0)
