# -*- coding: utf-8 -*-
"""Резервная копия всех данных пользователя (%APPDATA%\\AutoClip) в один zip — для
переустановки Windows — и восстановление из неё.

В копии: настройки, пресеты, свои звуки и шрифты, стили субтитров, список нарезок, история
просмотров, модель прогноза, Telegram (вместе с токеном бота), ответы по записям OBS, профиль
браузера публикации (без кэшей). Логи не входят.

Формат копии версионный (manifest.json, FORMAT): когда токен начнёт шифроваться средствами
Windows (Патч 4), копия будет хранить его так, чтобы он восстанавливался и на новой Windows —
поле "secrets" говорит, как он лежит ("plain" — как в telegram.json)."""

import datetime
import json
import os
import shutil
import tempfile
import zipfile

import autoclip

FORMAT = 1
MANIFEST = "manifest.json"
SKIP_TOP = {"logs"}                                   # не берём в копию
SKIP_DIRS = {"cache", "code cache", "gpucache", "grshadercache", "shadercache", "cachestorage",
             "crashpad", "dawncache", "dawngraphitecache", "dawnwebgpucache"}   # кэши браузера
REMIND_DAYS = 30


def data_dir():
    return autoclip.user_dir()


def _items(root):
    """Что из папки данных идёт в копию: [(путь, имя в архиве)] — только файлы."""
    out = []
    for name in sorted(os.listdir(root)):
        if name in SKIP_TOP or name.endswith((".tmp", ".lock")):
            continue
        full = os.path.join(root, name)
        if os.path.isfile(full):
            out.append((full, name))
        elif os.path.isdir(full):
            for d, dirs, files in os.walk(full):
                dirs[:] = [x for x in dirs if x.lower() not in SKIP_DIRS]
                for f in files:
                    p = os.path.join(d, f)
                    out.append((p, os.path.relpath(p, root).replace(os.sep, "/")))
    return out


def save_backup(dest):
    """Сохраняет копию в dest (.zip). Возвращает {"files", "skipped", "path"}: skipped — файлы,
    которые заняты другой программой (например, открытым браузером) и не попали в копию."""
    import update
    root = data_dir()
    tmp = dest + ".tmp"
    files, skipped = [], []
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for full, arc in _items(root):
            try:
                if arc == "telegram.json":
                    # в копии токен — открытым (secrets "plain"): шифр DPAPI на новой Windows не прочитать
                    import secret
                    with open(full, encoding="utf-8") as f:
                        plain = json.load(f)
                    if isinstance(plain, dict) and plain.get("token"):
                        plain["token"] = secret.unprotect(plain["token"]) or ""
                    z.writestr("data/" + arc, json.dumps(plain, ensure_ascii=False, indent=1))
                else:
                    z.write(full, "data/" + arc)
                files.append(arc)
            except OSError:
                skipped.append(arc)
        z.writestr(MANIFEST, json.dumps({
            "format": FORMAT, "app": "AutoClip", "version": update.VERSION,
            "date": autoclip.now_iso(), "secrets": "plain", "files": files,
        }, ensure_ascii=False, indent=1))
    os.replace(tmp, dest)
    mark_saved()
    return {"files": len(files), "skipped": skipped, "path": dest}


def read_manifest(path):
    try:
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read(MANIFEST).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        raise autoclip.AutoClipError("❌ Это не копия AutoClip или файл повреждён.")
    if m.get("app") != "AutoClip":
        raise autoclip.AutoClipError("❌ Это не копия AutoClip.")
    if int(m.get("format", 0)) > FORMAT:
        raise autoclip.AutoClipError("❌ Копия сделана более новой версией AutoClip — сначала обнови программу.")
    return m


def restore_backup(path):
    """Восстанавливает копию: то, что сейчас в папке данных и есть в копии, — в корзину Windows,
    потом файлы из копии. Нарезки, папок которых больше нет, из списка убираются.
    Возвращает {"files", "missing"}: missing — сколько нарезок пропущено."""
    m = read_manifest(path)
    root = data_dir()
    with tempfile.TemporaryDirectory(prefix="autoclip_restore_") as tmp:
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                name = info.filename
                if not name.startswith("data/") or name.endswith("/"):
                    continue
                target = os.path.normpath(os.path.join(tmp, name[5:]))
                if not target.startswith(os.path.normpath(tmp) + os.sep):
                    continue                              # пути вида ../ — мимо
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        tops = sorted(os.listdir(tmp))
        for top in tops:                                  # текущее — в корзину, не насовсем
            cur = os.path.join(root, top)
            if os.path.exists(cur):
                autoclip.trash(cur)
        for top in tops:
            shutil.move(os.path.join(tmp, top), os.path.join(root, top))
    missing = _drop_missing_projects(os.path.join(root, os.path.basename(autoclip.PROJECTS_INDEX)))
    try:                                               # токен из копии — снова зашифровать на этой Windows
        import telegram_bot
        st = telegram_bot.load_state()
        if st.get("token"):
            telegram_bot.save_state(st)
    except Exception:
        pass
    return {"files": len(m.get("files", [])), "missing": missing}


def _drop_missing_projects(index):
    try:
        with open(index, encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, ValueError):
        return 0
    keep = [p for p in items if isinstance(p, str) and os.path.isfile(p)]
    if len(keep) != len(items):
        autoclip.write_json(index, keep)
    return len(items) - len(keep)


# ---------- напоминание раз в месяц ----------

def _stamp():
    return os.path.join(data_dir(), "копия.json")


def mark_saved(when=None):
    autoclip.write_json(_stamp(), {"saved": (when or datetime.datetime.now()).isoformat(timespec="seconds")})


def last_saved():
    try:
        with open(_stamp(), encoding="utf-8") as f:
            return datetime.datetime.fromisoformat(json.load(f)["saved"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def need_reminder(settings, now=None, first_run=None):
    """Пора ли тихо напомнить «Давно не сохранял копию настроек»: копии не было месяц (или
    никогда — тогда через месяц после первого напоминания-отсчёта), напоминание не выключено и
    не показывалось последние 30 дней."""
    if not settings.get("backup_remind", True):
        return False
    now = now or datetime.datetime.now()
    last = last_saved()
    told = settings.get("backup_told")
    try:
        told = datetime.datetime.fromisoformat(told) if told else None
    except ValueError:
        told = None
    base = last or first_run
    if base is None:
        return False
    if now - base < datetime.timedelta(days=REMIND_DAYS):
        return False
    return told is None or now - told >= datetime.timedelta(days=REMIND_DAYS)
