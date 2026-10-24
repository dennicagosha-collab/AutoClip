import pytest

import autoclip

MAT = ["хуй", "Хуйня", "нахуй", "нахую", "хуево", "пизда", "пиздец", "распиздяй", "ебать",
       "заебал", "долбоеб", "долбаёб", "съебал", "ебаный", "бля", "Блять!", "блядь", "выблядок",
       "охуел", "б***ь", "сука", "суки", "нахер", "хер", "мудак", "пидор", "залупа",
       "гондон", "шлюха"]

NOT_MAT = ["тихую", "плохую", "себе", "небо", "оскорблять", "страхуй", "мандарин", "мудрый",
           "психую", "хобби", "херсон", "сукно", "команда", "требовать", "ребята", "хлеб",
           "колебать", "погибать", "употреблять", "истреблять", "хунта", "психуй"]


@pytest.mark.parametrize("w", MAT)
def test_mat_caught(w):
    assert autoclip.is_profane(w)


@pytest.mark.parametrize("w", NOT_MAT)
def test_normal_words_untouched(w):
    assert not autoclip.is_profane(w)


def test_soft_mat_can_be_switched_off(monkeypatch):
    monkeypatch.setitem(autoclip.CONFIG, "bleep_soft", False)
    assert not autoclip.is_profane("сука")
    assert autoclip.is_profane("блять")


def test_censor_keeps_first_letter():
    assert autoclip._censor("пиздец") == "п*****"
    assert autoclip._censor("небо") == "небо"


@pytest.mark.parametrize("w", ["ахахах", "хахаха", "Ахаха!", "хехе", "лол", "ору", "ржу"])
def test_laugh(w):
    assert autoclip.is_laugh(w)


@pytest.mark.parametrize("w", ["хата", "ага", "ах", "хорошо", "орут"])
def test_not_laugh(w):
    assert not autoclip.is_laugh(w)


def test_parse_time():
    assert autoclip.parse_time("95.5") == 95.5
    assert autoclip.parse_time("1:35") == 95
    assert autoclip.parse_time("1:02:10") == 3730
    with pytest.raises(autoclip.AutoClipError):
        autoclip.parse_time("вчера")


@pytest.mark.parametrize("text", ["Субтитры делал DimaTorzok", "Субтитры сделал DimaTorzok.",
                                  "Продолжение следует...", "Редактор субтитров А.Синецкая"])
def test_whisper_hallucinations_dropped(text):
    seg = {"s": 0, "e": 1, "text": text, "words": []}
    assert autoclip.drop_hallucinations([seg]) == []


@pytest.mark.parametrize("text", ["субтитры включи", "продолжение следует завтра на стриме",
                                  "ну вот смотри"])
def test_normal_speech_kept(text):
    seg = {"s": 0, "e": 1, "text": text, "words": []}
    assert autoclip.drop_hallucinations([seg]) == [seg]



PARTIAL = {"хуй": "ху*", "Хуйня": "Ху*ня", "нахуй": "наху*", "нахую": "наху*", "хуево": "ху*во",
           "пизда": "пи*да", "пиздец": "пи*дец", "распиздяй": "распи*дяй", "ебать": "е*ать",
           "заебал": "зае*ал", "долбоеб": "дол**еб", "долбаёб": "дол**ёб", "съебал": "съе*ал",
           "ебаный": "е*аный", "бля": "*ля", "Блять!": "*лять!", "блядь": "*лядь",
           "выблядок": "вы*лядок", "охуел": "оху*л", "б***ь": "б***ь", "сука": "с*ка", "суки": "с*ки",
           "нахер": "нах*р", "хер": "х*р", "мудак": "м*дак", "пидор": "п*дор", "залупа": "зал*па",
           "гондон": "г*ндон", "шлюха": "шл*ха"}


def test_partial_mask_covers_all_forms():
    assert set(PARTIAL) == set(MAT)                                   # все формы из теста фильтра
    for w, want in PARTIAL.items():
        assert autoclip.censor_word(w, "partial") == want, w
        if "*" not in w:                                               # Whisper уже скрыл — оставляем
            assert autoclip.censor_word(w, "full") == autoclip._censor(w)


@pytest.mark.parametrize("w", NOT_MAT)
def test_partial_mask_leaves_normal_words(w):
    assert autoclip.censor_word(w, "partial") == w and autoclip.mask_span(w) is None


def test_partial_bleep_covers_only_hidden_letters():
    words = [{"s": 1.0, "e": 1.6, "w": "ебать"}, {"s": 2.0, "e": 2.6, "w": "да"},
             {"s": 3.0, "e": 3.15, "w": "бля"}]
    full = autoclip.bleep_spans(words, 5.0, 0.12)
    part = autoclip.bleep_spans(words, 5.0, 0.12, partial=True)
    (a, b, u), (c, d, _) = part
    # «е*ать»: скрыта «б» — 1/5…2/5 слова (1,12…1,24 с) ± 40 мс, «е» и «ать» слышно
    assert abs(a - (1.0 + 0.6 * 1 / 5 - 0.04)) < 1e-6 and abs(b - (1.0 + 0.6 * 2 / 5 + 0.04)) < 1e-6
    assert u == b and b - a < full[0][1] - full[0][0]
    assert (c, d) == (full[1][0], full[1][1])                         # короткое слово — целиком
