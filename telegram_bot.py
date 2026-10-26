"""Telegram-бот AutoClip: уведомления и ответы из телефона.

Свой сервер не нужен: программа сама спрашивает Telegram (getUpdates, long polling), пока
она запущена (хотя бы в трее). Токен бота и chat_id хранятся только в
%APPDATA%\\AutoClip\\telegram.json — не в коде и не в настройках, которые попадают в отчёты.
Команды принимаются только из запомненного chat_id.
"""
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import autoclip
from autoclip import AutoClipError

STATE_PATH = os.path.join(autoclip.user_dir(), "telegram.json")
API = "https://api.telegram.org/bot{token}/{method}"
TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
STALE = "Уже неактуально"
HELP_VIEWS = "Не понял. Напиши число просмотров, например 12500 или «12500 43» — с процентом досмотров."


# ---------------- ответы про просмотры ----------------

def parse_views(text):
    """«12500» → (12500, None); «12 500» → (12500, None); «12500 43» → (12500, 43.0);
    «12 500 43,5%» → (12500, 43.5). Не число — None."""
    t = str(text).strip().lower().replace(" ", " ")
    t = re.sub(r"(просмотр\w*|досмотр\w*|views?)", " ", t)
    parts = [p for p in re.split(r"[\s/;]+", t.replace("%", " ")) if p]
    if not parts or not all(re.fullmatch(r"\d+([.,]\d+)?", p) for p in parts):
        return None

    def grouped(ps):
        """«12 500 000» — число с пробелами по тысячам."""
        if len(ps) == 1:
            return int(ps[0]) if ps[0].isdigit() else None
        if re.fullmatch(r"\d{1,3}", ps[0]) and all(re.fullmatch(r"\d{3}", p) for p in ps[1:]):
            return int("".join(ps))
        return None

    if grouped(parts) is not None:
        return grouped(parts), None
    *head, last = parts
    views = grouped(head) if head else None
    ret = float(last.replace(",", "."))
    if views is None or not 0 <= ret <= 100:
        return None
    return views, ret


# ---------------- обращение к Telegram ----------------

class TelegramError(AutoClipError):
    pass


class _Upload:
    """Тело запроса, которое сообщает, сколько уже ушло (ход отправки клипа)."""

    def __init__(self, data, on_progress):
        self.data, self.pos, self.on_progress = data, 0, on_progress

    def read(self, n=-1):
        n = len(self.data) - self.pos if n is None or n < 0 else min(n, 256 * 1024)
        chunk = self.data[self.pos:self.pos + n]
        self.pos += len(chunk)
        if chunk and self.on_progress:
            self.on_progress(self.pos, len(self.data))
        return chunk


def http_api(token, method, params=None, files=None, timeout=35, on_progress=None):
    """Один запрос к Bot API. files — {поле: путь} для отправки картинки или видео;
    on_progress(отправлено, всего) — ход отправки."""
    url = API.format(token=token, method=method)
    data, headers = None, {}
    if files:
        boundary = uuid.uuid4().hex
        body = b""
        for k, v in (params or {}).items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                     f"{v}\r\n").encode("utf-8")
        for k, path in files.items():
            with open(path, "rb") as f:
                raw = f.read()
            mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; "
                     f"filename=\"file{os.path.splitext(path)[1]}\"\r\nContent-Type: {mime}\r\n\r\n"
                     ).encode("utf-8") + raw + b"\r\n"
        data = body + f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        if on_progress:
            headers["Content-Length"] = str(len(data))
            data = _Upload(data, on_progress)
    elif params:
        data = urllib.parse.urlencode({k: (json.dumps(v, ensure_ascii=False)
                                          if isinstance(v, (dict, list)) else v)
                                      for k, v in params.items()}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            desc = json.load(e).get("description", "")
        except Exception:
            desc = ""
        if e.code in (401, 404):
            raise TelegramError("❌ Telegram не принял токен — проверь, что скопировал его целиком.")
        raise TelegramError(f"❌ Telegram ответил ошибкой {e.code} {desc}".strip())
    except (urllib.error.URLError, OSError, ValueError):
        raise TelegramError("❌ Нет связи с Telegram.")
    if not out.get("ok"):
        raise TelegramError(f"❌ Telegram: {out.get('description', 'ошибка')}")
    return out.get("result")


OFFLINE_WARN_S = 60          # сколько секунд без связи, прежде чем написать «нет связи»


# ---------------- состояние ----------------

def load_state():
    """Состояние бота. Пока другой поток заменяет файл, Windows не даёт его открыть —
    подождать и прочитать снова, а не считать «не подключён» (из-за этого терялись сообщения)."""
    import time
    for attempt in range(40):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                st = json.load(f)
            if not isinstance(st, dict):
                return {}
            if st.get("token"):                         # токен на диске — зашифрован (DPAPI, P3)
                import secret
                st["token"] = secret.unprotect(st["token"]) or ""
            return st
        except FileNotFoundError:
            return {}
        except PermissionError:
            time.sleep(0.025)
        except (OSError, ValueError):
            if attempt >= 3:
                return {}
            time.sleep(0.025)                          # файл дописывается — ещё раз
    return {}


def save_state(st):
    import secret
    disk = dict(st)
    if disk.get("token"):
        disk["token"] = secret.protect(disk["token"])  # на диске — только зашифрованный (DPAPI, P3)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(disk, f, ensure_ascii=False, indent=1)
    for attempt in range(20):                  # файл может читать поток связи — Windows не даст заменить
        try:
            os.replace(tmp, STATE_PATH)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)


def is_connected():
    st = load_state()
    return bool(st.get("token") and st.get("chat_id"))


def disconnect():
    save_state({})


class Bot:
    """Бот AutoClip. api(method, params, files) — запрос к Telegram (в тестах — подмена)."""

    def __init__(self, api=None, log=None):
        self.st = load_state()
        self._api = api
        self.log = log or autoclip.log
        self._offline_logged = False
        self._offline_since = None      # с какого времени нет связи (короткий сбой — не пугаем)
        self._clock = time.time

    # --- запросы ---
    def call(self, method, params=None, files=None, timeout=35, on_progress=None):
        token = self.st.get("token")
        if not token:
            raise TelegramError("❌ Telegram не подключён.")
        if self._api:
            return self._api(method, params or {}, files)
        if on_progress:
            return http_api(token, method, params, files, timeout, on_progress=on_progress)
        return http_api(token, method, params, files, timeout)

    def _send_video(self, path, params, say):
        """Видео в Telegram с ходом отправки; в лог — сколько ушло и с какой скоростью (видно, где долго)."""
        size = os.path.getsize(path)
        t0 = self._clock()
        last = [0.0]

        def progress(done, total):
            now = self._clock()
            if now - last[0] < 0.25 and done < total:
                return
            last[0] = now
            dt = max(0.1, now - t0)
            say(f"Отправляю… {done * 100 // max(1, total)}% · {done * 8 / dt / 1e6:.0f} Мбит/с")
        self.call("sendVideo", params, files={"video": path}, timeout=600, on_progress=progress)
        dt = max(0.1, self._clock() - t0)
        autoclip.log(f"✅ Telegram: клип ушёл — {size / 2**20:.0f} МБ за {dt:.0f} с ({size * 8 / dt / 1e6:.0f} Мбит/с)")

    def save(self):
        save_state(self.st)

    @property
    def connected(self):
        return bool(self.st.get("token") and self.st.get("chat_id"))

    # --- подключение ---
    def set_token(self, token):
        token = token.strip()
        if not TOKEN_RE.match(token):
            raise TelegramError("❌ Это не похоже на токен бота. Он выглядит так: 123456789:AAH…")
        self.st = {"token": token}
        me = self.call("getMe")
        self.st["bot"] = me.get("username", "")
        # старые сообщения боту — не наши: начинаем с последнего
        ups = self.call("getUpdates", {"timeout": 0, "offset": -1})
        if ups:
            self.st["offset"] = ups[-1]["update_id"] + 1
        self.save()
        return self.st["bot"]

    def wait_start(self, seconds=60, stop=None):
        """Ждём /start от Гоши — запоминаем его chat_id. Возвращает chat_id или None."""
        end = time.time() + seconds
        while time.time() < end and not (stop and stop()):
            ups = self.call("getUpdates", {"timeout": 10, "offset": self.st.get("offset", 0)})
            for u in ups or []:
                self.st["offset"] = u["update_id"] + 1
                msg = u.get("message") or {}
                if str(msg.get("text", "")).strip().startswith("/start"):
                    self.st["chat_id"] = msg["chat"]["id"]
                    self.save()
                    self.send("Готово, AutoClip подключён. Сюда будут приходить уведомления.")
                    return self.st["chat_id"]
            self.save()
        return None

    # --- отправка ---
    def send(self, text, buttons=None):
        params = {"chat_id": self.st["chat_id"], "text": text}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d}
                                                           for t, d in buttons]]}
        return self.call("sendMessage", params)

    def send_photo(self, path, caption):
        return self.call("sendPhoto", {"chat_id": self.st["chat_id"], "caption": caption},
                         files={"photo": path})

    def send_clip(self, path, caption, limit_mb=None, on_state=None):
        """Видео клипа с названием и описанием. Больше лимита Telegram — облегчённая копия
        во временной папке (после отправки удаляется), подпись об этом. Возвращает, была ли копия."""
        import tempfile
        limit = limit_mb or autoclip.TG_LIMIT_MB
        say = on_state or (lambda t: None)
        caption = caption[:1000]                         # подпись в Telegram — до 1024 знаков
        if os.path.getsize(path) <= limit * 1024 * 1024:
            say("Отправляю…")
            self._send_video(path, {"chat_id": self.st["chat_id"], "caption": caption,
                                    "supports_streaming": "true"}, say)
            return False
        with tempfile.TemporaryDirectory(prefix="autoclip_tg_") as tmp:
            small = os.path.join(tmp, "клип.mp4")
            autoclip.light_copy(path, small, limit, on_frac=lambda f: say(f"Делаю облегчённую копию… {f:.0%}"))
            say("Отправляю облегчённую копию…")
            note = "облегчённая версия, полный файл — на ПК"
            self._send_video(small, {"chat_id": self.st["chat_id"], "caption": f"{caption[:950]}\n\n({note})",
                                     "supports_streaming": "true"}, say)
        return True

    def test(self):
        self.send("Проверка связи: AutoClip на месте.")

    # --- уведомления ---
    def notify_cut(self, proj_path):
        """Нарезка готова: сколько клипов, лучший и его обложка."""
        proj = autoclip.load_project(proj_path)
        clips = [c for c in proj["clips"] if c["status"] != "rejected"]
        name = os.path.basename(proj.get("source", ""))
        if not clips:
            return self.send(f"Нарезка «{name}» готова, но клипов нет.")
        best = max(clips, key=lambda c: c.get("score", 0))
        n = len(clips)
        cands = len(proj.get("candidates") or [])
        text = (f"Нарезка готова: «{name}»\nКлипов: {n}"
                + (f", ещё кандидатов: {cands}" if cands else "")
                + f"\nЛучший: «{autoclip.clip_title(best)}», оценка {best.get('score', 0):.1f}")
        cover = (best.get("cover") or {}).get("file")
        path = autoclip.cover_path_for(autoclip.cut_root(proj), best["file"]) if cover else ""
        if cover and os.path.isfile(path):
            return self.send_photo(path, text)
        return self.send(text)

    def notify_recording(self, path, info):
        """Новая запись в папке OBS — «Нарезать» / «Не надо» прямо в Telegram."""
        key = uuid.uuid4().hex[:10]
        self.st.setdefault("pending", {})[key] = {"kind": "rec", "path": path}
        self.save()
        marks = info.get("marks", 0)
        self.send(f"Новая запись: {os.path.basename(path)}, {autoclip.fmt_time(info.get('dur', 0))}, "
                  f"меток: {marks}. Нарезать?",
                  [("Нарезать", f"cut:{key}"), ("Не надо", f"no:{key}")])

    def notify_update(self, rel, current):
        """Вышла новая версия — «Обновить» / «Позже» / «Пропустить версию»."""
        v = rel["version"]
        self.st.setdefault("pending", {})[f"u{v}"] = {"kind": "update", "version": v}
        self.save()
        notes = (rel.get("notes") or "").strip()
        self.send(f"Вышла новая версия AutoClip {v} (сейчас {current})."
                  + (f"\n\n{notes[:800]}" if notes else "")
                  + "\n\nОбновлю, только когда скажешь, и не во время нарезки.",
                  [("Обновить", f"upd:{v}"), ("Позже", f"later_upd:{v}"), ("Пропустить версию", f"skip_upd:{v}")])

    def drop_recording(self, path):
        """На запись ответили в программе — кнопки в Telegram больше не нужны."""
        pend = self.st.get("pending", {})
        for k in [k for k, v in pend.items() if v.get("kind") == "rec" and v.get("path") == path]:
            pend.pop(k)
        self.save()

    # --- вопрос про просмотры, по одному ---
    def ask_views(self, days=3):
        """Задать следующий вопрос, если сейчас ни о чём не спрашиваем. True — спросили."""
        import forecast
        if self.st.get("asking"):
            return False
        for q in forecast.due_questions(days):
            key = uuid.uuid4().hex[:10]
            name = autoclip.PLATFORMS.get(q["platform"], q["platform"])
            d = q["days_ago"]
            self.st["asking"] = dict(q, key=key)
            self.save()
            self.send(f"Клип «{q['title']}» выложен в {name} {d} {_days(d)} назад. "
                      "Сколько просмотров?\nМожно вторым числом процент досмотров: «12500 43».",
                      [("Напомнить завтра", f"later:{key}"), ("Пропустить", f"skip:{key}")])
            return True
        return False

    # --- входящие ---
    def poll(self, timeout=25):
        """Забрать новые сообщения и нажатия. Возвращает действия для программы:
        [("cut", путь), ("no", путь), ("views", вопрос), …]. Нет связи — [] (в лог один раз)."""
        try:
            ups = self.call("getUpdates", {"timeout": timeout, "offset": self.st.get("offset", 0),
                                           "allowed_updates": ["message", "callback_query"]},
                            timeout=timeout + 10)
            if self._offline_logged:
                self.log("✅ Telegram снова на связи.")
            self._offline_logged = False
            self._offline_since = None
        except TelegramError as e:
            # один оборвавшийся запрос — обычное дело; предупреждаем, только если связи нет дольше минуты
            now = self._clock()
            if self._offline_since is None:
                self._offline_since = now
            if not self._offline_logged and now - self._offline_since >= OFFLINE_WARN_S:
                self.log(f"⚠️  Telegram: {e} Работаю без него.")
                self._offline_logged = True
            return []
        actions = []
        for u in ups or []:
            self.st["offset"] = u["update_id"] + 1
            try:
                actions += self.handle(u)
            except TelegramError as e:
                self.log(f"⚠️  Telegram: {e}")
        self.save()
        return actions

    def handle(self, u):
        if "callback_query" in u:
            cq = u["callback_query"]
            chat = ((cq.get("message") or {}).get("chat") or {}).get("id")
            if chat != self.st.get("chat_id"):
                return []                                # чужой — молча мимо
            return self._button(cq)
        msg = u.get("message") or {}
        if (msg.get("chat") or {}).get("id") != self.st.get("chat_id"):
            return []
        text = str(msg.get("text", "")).strip()
        if text.startswith("/"):
            if text.startswith("/start"):
                self.send("AutoClip на связи.")
            return []
        return self._answer(text)

    def _button(self, cq):
        kind, _, key = str(cq.get("data", "")).partition(":")
        out, reply = [], STALE
        pend = self.st.setdefault("pending", {})
        ask = self.st.get("asking") or {}
        if kind in ("upd", "later_upd", "skip_upd") and f"u{key}" in pend:
            if kind != "later_upd":
                pend.pop(f"u{key}")
            out.append({"upd": ("update", key), "skip_upd": ("skip_update", key)}.get(kind, ("later", key)))
            reply = {"upd": "Ставлю обновление", "later_upd": "Ок, позже",
                     "skip_upd": "Эту версию пропускаю"}[kind]
            out = [a for a in out if a[0] != "later"]
        elif kind in ("cut", "no") and key in pend:
            item = pend.pop(key)
            out.append((kind, item["path"]))
            reply = "Нарезаю" if kind == "cut" else "Ок, не режу"
        elif kind in ("later", "skip") and ask.get("key") == key:
            import forecast
            args = (ask["project"], ask["id"], ask["platform"])
            try:
                (forecast.snooze_views if kind == "later" else forecast.skip_views)(*args)
            except AutoClipError:
                pass
            self.st["asking"] = None
            reply = "Напомню завтра" if kind == "later" else "Пропускаю"
            out.append(("views", None))
        self.call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": reply})
        if out and out[-1][0] == "views":
            self.ask_views(self.st.get("days", 3))       # следующий вопрос — сразу
        return out

    def _answer(self, text):
        ask = self.st.get("asking")
        if not ask:
            return []
        got = parse_views(text)
        if not got:
            self.send(HELP_VIEWS)
            return []
        import forecast
        views, ret = got
        try:
            forecast.record_views(ask["project"], ask["id"], ask["platform"], views, ret)
        except AutoClipError as e:
            self.send(str(e).replace("❌ ", ""))
            self.st["asking"] = None
            return []
        self.st["asking"] = None
        self.send(f"Записал: {views:,} просмотров".replace(",", " ")
                  + (f", досмотров {ret:g}%" if ret is not None else "") + ".")
        self.ask_views(self.st.get("days", 3))
        return [("views", ask)]


def _days(n):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    return "дня" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "дней"
