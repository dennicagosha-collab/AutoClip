"""Telegram-бот: разбор ответов, чужой chat_id, старые ответы и кнопки (Telegram подменён)."""
import datetime
import json
import os

import pytest

import autoclip
import forecast
import telegram_bot as tg

ME, STRANGER = 111, 999
TOKEN = "123456789:AAH5abcdefghijklmnopqrstuvwxyz012345"


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "STATE_PATH", str(tmp_path / "telegram.json"))


@pytest.mark.parametrize("text, want", [
    ("12500", (12500, None)), ("12 500", (12500, None)), ("12500 43", (12500, 43.0)),
    ("12 500 43,5%", (12500, 43.5)), ("1 200 000", (1200000, None)), ("0", (0, None)),
    ("12043", (12043, None)), ("12500 просмотров 43%", (12500, 43.0)), ("12\u00a0500", (12500, None)),
    ("мусор", None), ("", None), ("12500 143", None), ("-5", None), ("12.5к", None),
    ("сто", None), ("12500 43 7", None),
])
def test_parse_views(text, want):
    assert tg.parse_views(text) == want


class FakeTelegram:
    """Подмена Bot API: копит отправленное, отдаёт заранее заданные обновления."""

    def __init__(self):
        self.sent = []
        self.updates = []
        self.answers = []

    def __call__(self, method, params, files=None):
        if method == "getMe":
            return {"username": "autoclip_test_bot"}
        if method == "getUpdates":
            off = params.get("offset", 0)
            if off == -1:
                return self.updates[-1:]
            return [u for u in self.updates if u["update_id"] >= off]
        if method == "answerCallbackQuery":
            self.answers.append(params["text"])
            return True
        self.sent.append((method, params, files))
        return {"message_id": len(self.sent)}

    def msg(self, chat, text):
        n = len(self.updates) + 1
        self.updates.append({"update_id": n, "message": {"chat": {"id": chat}, "text": text}})

    def press(self, chat, data):
        n = len(self.updates) + 1
        self.updates.append({"update_id": n, "callback_query": {
            "id": f"cb{n}", "data": data, "message": {"chat": {"id": chat}}}})

    def texts(self):
        return [p.get("text") or p.get("caption") for _, p, _ in self.sent]


def connected_bot(api):
    bot = tg.Bot(api=api, log=lambda m: None)
    bot.set_token(TOKEN)
    api.msg(ME, "/start")
    assert bot.wait_start(seconds=1) == ME
    return bot


def test_connect_remembers_chat_and_ignores_old_messages(tmp_path):
    api = FakeTelegram()
    api.msg(STRANGER, "старое сообщение до подключения")
    bot = tg.Bot(api=api, log=lambda m: None)
    with pytest.raises(tg.TelegramError):
        bot.set_token("не токен")
    assert bot.set_token(TOKEN) == "autoclip_test_bot"
    api.msg(ME, "/start")
    assert bot.wait_start(seconds=1) == ME
    st = tg.load_state()                                              # на диске токен зашифрован (P3)
    assert st["chat_id"] == ME and st["token"] == TOKEN
    assert tg.is_connected() and "подключён" in api.texts()[-1]


def ago(days):
    return (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat(timespec="seconds")


def _project(tmp_path):
    out = tmp_path / "запись_clips"
    out.mkdir()
    proj = autoclip.new_project(str(tmp_path / "запись.mp4"), {"w": 1080, "h": 1920, "dur": 600.0,
                                "fps": 60.0}, str(out), str(tmp_path / "запись.transcript.json"))
    for i in (1, 2):
        rec = autoclip.make_clip_record({"s": 10.0 * i, "e": 10.0 * i + 20, "peak": 10.0 * i + 2,
                                         "score": 2.0 + i, "zooms": [], "parts": {},
                                         "title": f"клип {i}", "reason": ""}, i, f"{i:02d}.mp4")
        rec.update(status="published", published={"tiktok": {"date": ago(4)}})
        proj["clips"].append(rec)
    autoclip.save_project(proj)
    autoclip.register_project(str(out))
    return str(out)


def test_views_one_at_a_time_and_strangers_ignored(tmp_path):
    path = _project(tmp_path)
    api = FakeTelegram()
    bot = connected_bot(api)
    assert bot.ask_views(3)
    assert "Сколько просмотров" in api.texts()[-1] and "TikTok" in api.texts()[-1]
    assert not bot.ask_views(3)                                     # пока не ответил — второго нет
    first = bot.st["asking"]["id"]
    api.msg(STRANGER, "999999")                                     # чужой — мимо
    api.msg(ME, "что-то не то")
    acts = bot.poll(0)
    assert acts == [] and tg.HELP_VIEWS in api.texts()
    assert "views" not in autoclip.find_clip(autoclip.load_project(path), first)["published"]["tiktok"]
    api.msg(ME, "12 500 43")
    acts = bot.poll(0)
    c = autoclip.find_clip(autoclip.load_project(path), first)
    assert c["published"]["tiktok"]["views"] == 12500 and c["published"]["tiktok"]["retention"] == 43.0
    assert acts[0][0] == "views"
    assert bot.st["asking"]["id"] != first                          # сразу следующий вопрос
    key = bot.st["asking"]["key"]
    api.press(STRANGER, f"skip:{key}")                              # чужая кнопка — мимо
    bot.poll(0)
    assert bot.st["asking"]["key"] == key
    api.press(ME, f"later:{key}")
    bot.poll(0)
    assert bot.st["asking"] is None and api.answers[-1] == "Напомню завтра"
    assert forecast.due_questions(3) == []                          # один выложен, второй — завтра


def test_old_answers_picked_up_and_stale_buttons(tmp_path, monkeypatch):
    path = _project(tmp_path)
    api = FakeTelegram()
    bot = connected_bot(api)
    bot.ask_views(3)
    old_key = bot.st["asking"]["key"]
    asked = bot.st["asking"]["id"]
    # программа закрылась; пока ПК был выключен, Гоша ответил и понажимал кнопки
    api.msg(ME, "8000")
    api.press(ME, f"skip:{old_key}")                                # уже ответил — кнопка устарела
    api.press(ME, "cut:нет-такого")
    bot2 = tg.Bot(api=api, log=lambda m: None)                      # новый запуск программы
    bot2.poll(0)
    c = autoclip.find_clip(autoclip.load_project(path), asked)
    assert c["published"]["tiktok"]["views"] == 8000
    assert api.answers.count(tg.STALE) == 2
    assert bot2.poll(0) == []                                       # второй раз то же не берём


def test_recording_buttons(tmp_path):
    api = FakeTelegram()
    bot = connected_bot(api)
    bot.notify_recording(r"D:\Записи\стрим.mp4", {"dur": 3600, "marks": 2})
    text = api.texts()[-1]
    assert "стрим.mp4" in text and "1:00:00" in text and "меток: 2" in text
    buttons = api.sent[-1][1]["reply_markup"]["inline_keyboard"][0]
    assert [b["text"] for b in buttons] == ["Нарезать", "Не надо"]
    api.press(ME, buttons[0]["callback_data"])
    assert bot.poll(0) == [("cut", r"D:\Записи\стрим.mp4")]
    api.press(ME, buttons[1]["callback_data"])                      # второй раз — неактуально
    assert bot.poll(0) == [] and api.answers[-1] == tg.STALE
    bot.notify_recording(r"D:\Записи\второй.mp4", {"dur": 600, "marks": 0})
    no = api.sent[-1][1]["reply_markup"]["inline_keyboard"][0][1]["callback_data"]
    bot.drop_recording(r"D:\Записи\второй.mp4")                     # ответили в программе
    api.press(ME, no)
    assert bot.poll(0) == [] and api.answers[-1] == tg.STALE


def test_cut_notice_with_cover(tmp_path):
    path = _project(tmp_path)
    proj = autoclip.load_project(path)
    cover = tmp_path / "запись_clips" / "02.jpg"
    cover.write_bytes(b"\xff\xd8 jpeg")
    proj["clips"][1]["cover"] = {"file": "02.jpg", "t": 12.0}
    autoclip.save_project(proj)
    api = FakeTelegram()
    bot = connected_bot(api)
    bot.notify_cut(path)
    method, params, files = api.sent[-1]
    assert method == "sendPhoto" and files["photo"].endswith("02.jpg")
    assert "Клипов: 2" in params["caption"] and "клип 2" in params["caption"]


def test_offline_logged_once(tmp_path):
    logs = []

    def down(method, params, files=None):
        raise tg.TelegramError("❌ Нет связи с Telegram.")
    bot = tg.Bot(api=down, log=logs.append)
    bot.st = {"token": TOKEN, "chat_id": ME}
    now = [1000.0]
    bot._clock = lambda: now[0]
    assert bot.poll(0) == [] and bot.poll(0) == []
    assert logs == []                                   # короткий сбой — молчим
    now[0] += tg.OFFLINE_WARN_S
    assert bot.poll(0) == [] and bot.poll(0) == []
    assert len(logs) == 1 and "Работаю без него" in logs[0]
    bot._api = lambda method, params, files=None: []      # связь вернулась
    bot.poll(0)
    assert len(logs) == 2 and "снова на связи" in logs[1]


# ---------- окно ----------

def test_window_uses_telegram(tmp_path, monkeypatch):
    import sys
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from qtwait import pump
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    api = FakeTelegram()
    monkeypatch.setattr(tg, "http_api", lambda token, method, params=None, files=None, timeout=35:
                        api(method, params or {}, files))
    tg.save_state({"token": TOKEN, "chat_id": ME, "bot": "autoclip_test_bot", "offset": 0})
    path = _project(tmp_path)
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    w = A.MainWindow()
    cuts = []
    monkeypatch.setattr(w, "cut_recording", lambda p: cuts.append(p))

    def wait(cond, ms=15000):
        for _ in range(ms // 50):
            if cond():
                return True
            pump(50)
        return cond()
    try:
        assert "Подключён: @autoclip_test_bot" in w.settings_page.tg_status.text()
        w.ask_views()
        assert getattr(w, "_views_dialog", None) is None             # окна нет — вопрос в Telegram
        assert wait(lambda: any("Сколько просмотров" in (t or "") for t in api.texts()))
        api.msg(ME, "777")
        assert wait(lambda: any("Записал: 777" in (t or "") for t in api.texts()))
        rec = r"D:\Записи\новая.mp4"
        w.offer(rec, {"dur": 1800, "marks": 1})
        assert wait(lambda: any("Новая запись: новая.mp4" in (t or "") for t in api.texts()))
        data = next(p for m, p, f in api.sent if "reply_markup" in p and "новая.mp4" in p["text"])
        api.press(ME, data["reply_markup"]["inline_keyboard"][0][0]["callback_data"])
        assert wait(lambda: cuts == [rec])
        assert not any(p == rec for p, _ in w._pending)               # в окне больше не спрашиваем
        assert autoclip.recording_state(rec) == "cut"
        w.finished(path)
        assert wait(lambda: any("Нарезка готова" in (t or "") for t in api.texts()))
    finally:
        w.close()


def test_update_buttons(tmp_path):
    api = FakeTelegram()
    bot = connected_bot(api)
    bot.notify_update({"version": "1.2.0", "notes": "- новое"}, "1.1.0")
    text = api.texts()[-1]
    assert "1.2.0" in text and "1.1.0" in text and "- новое" in text
    btn = [b["callback_data"] for b in api.sent[-1][1]["reply_markup"]["inline_keyboard"][0]]
    api.press(ME, btn[1])                                            # «Позже» — кнопки ещё живы
    assert bot.poll(0) == [] and api.answers[-1] == "Ок, позже"
    api.press(ME, btn[0])
    assert bot.poll(0) == [("update", "1.2.0")]
    api.press(ME, btn[2])                                            # уже ответил — неактуально
    assert bot.poll(0) == [] and api.answers[-1] == tg.STALE


def test_send_clip_small_and_light_copy(tmp_path):
    import subprocess
    api = FakeTelegram()
    bot = connected_bot(api)
    sizes = []
    real = api.__call__

    def spy(method, params, files=None):
        if method == "sendVideo":
            sizes.append(os.path.getsize(files["video"]))
        return real(method, params, files)
    bot._api = spy
    clip = tmp_path / "клип.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=6",
                    "-f", "lavfi", "-i", "sine=f=300:d=6", "-c:v", "libx264", "-preset", "ultrafast",
                    "-b:v", "8M", "-c:a", "aac", "-shortest", str(clip)], check=True)
    assert os.path.getsize(clip) > 2 * 1024 * 1024
    assert bot.send_clip(str(clip), "Название\n\n#стрим", limit_mb=50) is False     # влезает — как есть
    assert sizes[-1] == os.path.getsize(clip)
    states = []
    assert bot.send_clip(str(clip), "Название", limit_mb=1, on_state=states.append) is True
    assert sizes[-1] <= 1024 * 1024                                           # копия в лимите
    assert "облегчённая версия" in api.sent[-1][1]["caption"]
    assert any("облегчённую копию" in s for s in states)
    assert TOKEN not in " ".join(str(x) for x in api.sent)                    # токен не в сообщениях



def test_light_plan_keeps_full_hd():
    assert autoclip.light_plan(55) == (1080, 1920, 60, autoclip.light_plan(55)[3])     # 55 с — 1080p60
    assert autoclip.light_plan(55)[3] >= 6500                                           # ≥6,5 Мбит/с
    w, h, fps, k = autoclip.light_plan(100)
    assert (w, h, fps) == (1080, 1920, 30) and k < autoclip.FULL_HD_MIN_K                # сначала 30 к/с
    assert autoclip.light_plan(400)[:3] == (720, 1280, 30)                               # потом 720p
