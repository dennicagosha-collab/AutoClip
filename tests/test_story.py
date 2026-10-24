"""ПАТЧ_4, 4.2: начало и конец истории момента (синтетика)."""
import numpy as np

import story


def W(*items):
    return [{"s": s, "e": e, "w": w} for s, e, w in items]


def _env(n=80, hot=()):
    z = np.full(n, -0.5)
    burst = np.zeros(n)
    for a, b in hot:
        z[a:b] = 1.0
        burst[a:b] = 10.0
    return z, burst


def test_fight_before_reaction_is_kept():
    z, burst = _env(hot=[(20, 30)])                      # драка 20–30 с без слов
    words = W((31.0, 31.5, "свободен"), (31.6, 32.2, "мальчик"))
    s, e, why = story.story_bounds(32.0, words, [], z, burst, None, 80.0)
    assert s <= 20.0 and "событие в игре" in why


def test_quiet_running_before_phrase_not_taken():
    z, burst = _env()                                    # до фразы — тихо, ничего не происходит
    words = W((40.0, 40.6, "короче"), (40.7, 41.5, "медсестру"), (41.6, 43.0, "отходит"),
              (45.0, 47.0, "хороший"), (47.2, 48.5, "контур"), (54.0, 55.0, "другое"))
    s, e, why = story.story_bounds(42.0, words, [], z, burst, None, 80.0)
    assert 39.4 <= s <= 40.0 and "«короче»" in why
    assert 48.5 <= e <= 49.0 and "договорил" in why     # после «контур» пауза 5,5 с — конец


def test_question_before_answer_included():
    z, burst = _env()
    words = W((30.0, 32.0, "дочь"), (32.1, 33.0, "родилась"), (36.5, 37.0, "сегодня"), (37.1, 38.0, "ебём"))
    s, _, _ = story.story_bounds(37.5, words, [], z, burst, None, 80.0)
    assert s <= 30.0


def test_talk_after_peak_continues_until_long_pause():
    z, burst = _env()
    words = W((20.0, 21.0, "а"), (23.0, 24.0, "б"), (26.5, 27.5, "в"), (32.0, 33.0, "г"))
    _, e, _ = story.story_bounds(20.5, words, [], z, burst, None, 80.0)
    assert 27.5 <= e <= 28.0                             # пауза 4,5 с — дальше не тянем


def test_lost_phrase_by_voice_is_included():
    z, burst = _env()
    words = W((40.0, 40.6, "мы"), (40.7, 42.0, "живём"))
    voice = [(36.5, 38.0), (40.0, 42.0)]                 # вопрос слышен, но слов нет
    s, _, _ = story.story_bounds(41.0, words, voice, z, burst, None, 80.0)
    assert s <= 36.5


def test_mark_takes_story_before_it():
    z, burst = _env()
    words = W((50.0, 51.0, "ха"))
    s, _, why = story.story_bounds(50.5, words, [], z, burst, None, 80.0, mark=51.0)
    assert s <= 31.0 and "метка" in why


def test_game_only_moment():
    z, burst = _env(hot=[(30, 36)])
    s, e, why = story.story_bounds(33.0, [], [], z, burst, None, 80.0)
    assert 28.5 <= s <= 30.0 and 36.0 <= e <= 38.5 and "событие" in why


def test_no_speech_no_event_gives_none():
    z, burst = _env()
    assert story.story_bounds(33.0, [], [], z, burst, None, 80.0) is None
