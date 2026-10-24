"""Восстановление после прерванного обновления. Без зависимостей от остальной программы:
app.py зовёт его первым делом — даже если остальные файлы остались наполовину новыми."""
import json
import os
import shutil

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_NAME = "прежняя версия"
JOURNAL_NAME = "обновление.json"   # пока он есть, замена файлов не закончена


def recover(app_dir=APP_DIR):
    """Обновление прервали посередине (выключили свет): вернуть прежнюю версию из
    «прежняя версия» и убрать недописанное. Зовётся при запуске программы до всего остального."""
    journal = os.path.join(app_dir, JOURNAL_NAME)
    if not os.path.exists(journal):
        return False
    try:
        with open(journal, encoding="utf-8") as f:
            j = json.load(f)
    except (OSError, ValueError):
        j = {}
    backup = os.path.join(app_dir, BACKUP_NAME)
    added = set(j.get("added", []))
    for f in j.get("changed", []) + j.get("removed", []):
        old, cur = os.path.join(backup, f), os.path.join(app_dir, f)
        if os.path.isfile(old):                        # прежний файл — на место
            os.makedirs(os.path.dirname(cur), exist_ok=True)
            shutil.copy2(old, cur + ".old")
            os.replace(cur + ".old", cur)              # замена файла — целиком или никак
        elif f in added and os.path.isfile(cur):       # файла не было до обновления — убрать
            os.makedirs(os.path.dirname(os.path.join(backup, f)), exist_ok=True)
            os.replace(cur, os.path.join(backup, f + ".недоставлен"))
        if os.path.exists(cur + ".new"):
            os.makedirs(os.path.dirname(os.path.join(backup, f)), exist_ok=True)
            os.replace(cur + ".new", os.path.join(backup, f + ".new"))
    os.remove(journal)
    return True
