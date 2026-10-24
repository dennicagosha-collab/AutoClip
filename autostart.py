# -*- coding: utf-8 -*-
"""Запуск AutoClip вместе с Windows: запись в HKCU\\...\\Run с флагом --tray (окно не
показывается, работают слежка за OBS, Telegram и проверка обновлений).

Путь к Python — как в AutoClip.bat: лаунчер pyw с версией 3.13 / 3.12 / 3.14 / 3.11, иначе
pythonw рядом с тем Python, на котором запущена программа. Обновление меняет файлы на месте,
поэтому запись остаётся рабочей."""

import os
import shutil
import subprocess
import sys

import autoclip

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "AutoClip"
TRAY_FLAG = "--tray"
APP = os.path.join(autoclip.SCRIPT_DIR, "app.py")
VERSIONS = ("3.13", "3.12", "3.14", "3.11")


# ---------- реестр (тонкая прослойка — в тестах подменяется) ----------

def _reg_get(name):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _reg_set(name, value):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def _reg_del(name):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except FileNotFoundError:
        pass


# ---------- команда запуска ----------

def python_cmd():
    """Чем запускать окно без консоли: [pyw, -3.13] или [путь к pythonw.exe]."""
    pyw = shutil.which("pyw")
    py = shutil.which("py")
    if pyw and py:
        for v in VERSIONS:
            try:
                p = subprocess.run([py, f"-{v}", "-c", "import sys"], capture_output=True,
                                   timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if p.returncode == 0:
                    return [pyw, f"-{v}"]
            except (OSError, subprocess.SubprocessError):
                pass
    exe = sys.executable or "pythonw"
    w = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return [w if os.path.isfile(w) else exe]


def command(py=None):
    parts = (py or python_cmd()) + [APP, TRAY_FLAG]
    return " ".join(f'"{p}"' if " " in p or not p.startswith("-") else p for p in parts)


def is_enabled():
    return bool(_reg_get(NAME))


def enable(py=None):
    """Включить автозапуск. Возвращает записанную команду."""
    cmd = command(py)
    _reg_set(NAME, cmd)
    return cmd


def disable():
    _reg_del(NAME)


def refresh():
    """Автозапуск включён — переписать команду (например, программу перенесли в другую папку)."""
    cur = _reg_get(NAME)
    if cur and (APP not in cur or TRAY_FLAG not in cur):
        enable()


# ---------- ярлыки в shell:startup ----------

def startup_dir():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu",
                        "Programs", "Startup")


def startup_shortcuts(folder=None):
    """Ярлыки AutoClip в папке автозагрузки (shell:startup) — с ними будет два запуска."""
    folder = folder or startup_dir()
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return [os.path.join(folder, n) for n in sorted(names)
            if "autoclip" in n.lower() and n.lower().endswith((".lnk", ".bat", ".cmd", ".url"))]


def remove_shortcuts(paths):
    """Ярлыки — в корзину Windows (не насовсем)."""
    for p in paths:
        autoclip.trash(p)
