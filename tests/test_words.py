import pytest

import autoclip

MAT = ["хуй", "Хуйня", "нахуй", "нахую", "хуево", "пизда", "пиздец", "распиздяй", "ебать",
       "заебал", "долбоеб", "съебал", "ебаный", "бля", "Блять!", "блядь", "выблядок",
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
