"""Лог программы в файл и «Отчёт об ошибке».

Лог: %APPDATA%\\AutoClip\\logs, по файлу на запуск, хранятся последние 10.
Отчёт: zip на рабочий стол — логи, версии, настройки без секретов, отчёт и project.json
последней нарезки. Записи и клипы в отчёт не кладутся.

Из консоли:  python diag.py   — собрать отчёт
"""
import datetime
import glob
import json
import os
import platform
import re
import subprocess
import sys
import zipfile

import autoclip

LOG_DIR = os.path.join(autoclip.user_dir(), "logs")
KEEP_LOGS = 10
SECRET_KEY = re.compile(r"token|key|secret|pass|chat_?id|auth|cookie", re.I)
# похожее на токен бота («123456:AA…»), ключи API, длинные случайные строки
SECRET_VALUE = re.compile(r"\d{6,}:[\w-]{30,}|sk-[\w-]{20,}|gh[opsu]_\w{20,}|[A-Za-z0-9_\-]{40,}")
PACKAGES = ("faster-whisper", "ctranslate2", "av", "numpy", "PySide6", "send2trash",
            "opencv-python-headless", "scikit-learn", "nvidia-cublas-cu12", "nvidia-cudnn-cu12")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FileLog:
    """Лог одного запуска. write() можно звать из любого потока."""

    def __init__(self, log_dir=None, keep=KEEP_LOGS):
        import threading
        self.dir = log_dir or LOG_DIR
        os.makedirs(self.dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.path = os.path.join(self.dir, f"{stamp}.log")
        n = 2
        while os.path.exists(self.path):
            self.path = os.path.join(self.dir, f"{stamp}_{n}.log")
            n += 1
        self._lock = threading.Lock()
        self._f = open(self.path, "a", encoding="utf-8")
        self.write(f"AutoClip {version()} · Python {sys.version.split()[0]} · {platform.platform()}")
        prune_logs(self.dir, keep)

    def write(self, text):
        text = str(text).rstrip()
        if not text:
            return
        t = datetime.datetime.now().strftime("%H:%M:%S")
        with self._lock:
            try:
                for line in text.splitlines():
                    self._f.write(f"{t}  {line}\n")
                self._f.flush()
            except (OSError, ValueError):
                pass

    def close(self):
        with self._lock:
            try:
                self._f.close()
            except OSError:
                pass


def prune_logs(log_dir=None, keep=KEEP_LOGS):
    """Оставить последние keep логов. Старые — в корзину (насовсем программа не удаляет)."""
    files = sorted(glob.glob(os.path.join(log_dir or LOG_DIR, "*.log")), key=os.path.getmtime)
    for f in files[:-keep] if keep else files:
        try:
            autoclip.trash(f, wait=0)
        except (autoclip.AutoClipError, OSError):
            pass


def version():
    try:
        import update
        return f"{update.version_name()} ({update.VERSION})"
    except Exception:
        return "?"


def clean(data):
    """Настройки без секретов: ключи с token/key/chat_id и значения, похожие на токены."""
    if isinstance(data, dict):
        return {k: ("<скрыто>" if SECRET_KEY.search(str(k)) and v not in ("", None, False)
                    else clean(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [clean(v) for v in data]
    if isinstance(data, str):
        return SECRET_VALUE.sub("<скрыто>", data)
    return data


def _cmd(args, timeout=10):
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=_NO_WINDOW)
        return (p.stdout or p.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return "нет"


def system_info():
    from importlib import metadata
    lines = [f"AutoClip {version()}", f"Python {sys.version}", f"Система: {platform.platform()}",
             f"Процессор: {platform.processor() or '?'}", ""]
    lines.append("ffmpeg: " + (_cmd(["ffmpeg", "-hide_banner", "-version"]).splitlines() or ["нет"])[0])
    gpu = _cmd(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"])
    lines.append(f"Видеокарта (имя, драйвер, память): {gpu}")
    lines += ["", "Пакеты:"]
    for name in PACKAGES:
        try:
            lines.append(f"  {name} {metadata.version(name)}")
        except metadata.PackageNotFoundError:
            lines.append(f"  {name} — нет")
    return "\n".join(lines) + "\n"


def desktop_dir():
    """Рабочий стол (в том числе перенесённый в OneDrive)."""
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
                return buf.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


USER_FILES = ("настройки.json", "пресеты.json", "нарезки.json", "записи.json", "модель.json")


def make_report(dest_dir=None, log_dir=None):
    """Собрать отчёт об ошибке в zip. Возвращает путь к архиву."""
    dest_dir = dest_dir or desktop_dir()
    os.makedirs(dest_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    path = os.path.join(dest_dir, f"AutoClip отчёт об ошибке {stamp}.zip")
    n = 2
    while os.path.exists(path):
        path = os.path.join(dest_dir, f"AutoClip отчёт об ошибке {stamp} ({n}).zip")
        n += 1
    log_dir = log_dir or LOG_DIR
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("система.txt", system_info())
        for f in sorted(glob.glob(os.path.join(log_dir, "*.log")))[-KEEP_LOGS:]:
            with open(f, encoding="utf-8", errors="replace") as fh:
                z.writestr(f"логи/{os.path.basename(f)}", SECRET_VALUE.sub("<скрыто>", fh.read()))
        for name in USER_FILES:
            data = _read_json(os.path.join(autoclip.user_dir(), name))
            if data is not None:
                z.writestr(f"настройки/{name}", json.dumps(clean(data), ensure_ascii=False, indent=1))
        projects = autoclip.known_projects()
        last = next((p for p in reversed(projects) if os.path.isfile(p)), None)
        if last:
            data = _read_json(last)
            if data is not None:
                z.writestr("последняя нарезка/project.json",
                           json.dumps(clean(data), ensure_ascii=False, indent=1))
            rep = os.path.join(os.path.dirname(last), "отчёт.txt")
            if os.path.isfile(rep):
                z.write(rep, "последняя нарезка/отчёт.txt")
    return path


if __name__ == "__main__":
    print(make_report())
