#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AutoClip — нарезка длинной вертикальной записи стрима на короткие клипы
для TikTok / Shorts / Reels.

Что делает:
  1. Расшифровывает речь локально (Whisper на видеокарте), с таймкодом каждого слова.
  2. Ищет моменты: пики громкости (крик, смех), смех в речи, восклицания, мат,
     плюс (по желанию) оценка расшифровки языковой моделью.
  3. Режет клипы 15–60 сек по границам фраз.
  4. Запикивает мат (бип 1 кГц) и прячет его в субтитрах (Б***).
  5. Вшивает субтитры в стиле TikTok (2–3 слова, текущее слово жёлтое).
  6. Делает резкий зум-ин на эмоциональных пиках.

Запуск:  python autoclip.py запись.mp4
         python autoclip.py запись.mp4 --clips 15 --llm none
         python autoclip.py запись_clips --rebuild 3 --start 1:02:10 --no-zoom
Результат: папка "<имя видео>_clips" рядом с видео: клипы, project.json, отчёт.txt

Из другого кода: process(video, progress=..., cancel=...) и rebuild_clip(...).
Ошибки приходят как AutoClipError (текст уже понятный), остановка — Cancelled.

Настройки — в блоке CONFIG ниже.
"""

import argparse
import datetime
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave

# ======================= CONFIG =======================
CONFIG = {
    # --- клипы ---
    "clips": 10,              # сколько клипов сделать (режим «Число»)
    "build_mode": "auto",     # auto / full (несколько клипов сразу) / background (тихо, по одному)
    "parallel_clips": 3,      # сколько клипов собирать одновременно «на полную»
    "game_processes": "",     # свои игры через запятую: при них «Авто» собирает в фоне
    "clips_mode": "count",    # count — ровно «clips»; auto — все выше порога, не больше потолка
    "auto_min_score": 2.5,    # порог «Авто» с языковой моделью: на 25-мин записи 11 клипов
    "auto_min_score_plain": 1.7,   # он же без модели (оценки ниже): на той же записи 9 клипов
    "auto_max": 30,           # потолок «Авто»
    "max_candidates": 20,     # сколько моментов сверх отобранных показать кандидатами
    "min_len": 15.0,          # мин. длина клипа, сек
    "max_len": 55.0,          # макс. длина клипа, сек
    "pre": 14.0,              # сколько секунд взять ДО пика
    "post": 7.0,              # сколько секунд взять ПОСЛЕ пика
    "min_gap": 8.0,           # мин. зазор между клипами, сек
    # границы клипа — по речи, а не по ответу модели (её границы — только подсказка)
    "tail_after": 8.0,        # конец — не дальше стольких секунд после пика…
    "tail_max": 15.0,         # …если договаривает без пауз — до конца фразы, но не дальше этого
    "talk_gap": 1.5,          # пауза короче этой — речь ещё продолжается
    "lead_before": 1.5,       # начало — не раньше стольких секунд до первой речи (кроме громкой реакции)
    "max_silence": 6.0,       # пауза без речи длиннее — клип обрезается по неё со стороны без пика
    "soft_silence": 3.0,      # пауза длиннее — тоже обрезается со стороны без пика, если клип не короче min_tight
    "min_tight": 8.0,         # после обрезки клип не короче этого, иначе — в кандидаты
    "max_silence_share": 0.45,  # тишины (паузы >1 с) в клипе больше этой доли — в кандидаты

    # --- Whisper ---
    "whisper_model": "large-v3",   # large-v3 / medium / small
    "retranscribe": False,    # расшифровать заново, даже если кэш есть
    "subs_team": False,       # субтитры и для тиммейтов (дорожка Discord)
    "language": "ru",

    # --- языковая модель для оценки моментов ---
    # auto = Ollama, если запущена; иначе Claude API, если задан ANTHROPIC_API_KEY; иначе без неё
    "llm": "auto",                  # auto / ollama / anthropic / none
    "ollama_model": "qwen3:14b",
    "ollama_url": "http://localhost:11434",
    "anthropic_model": "claude-haiku-5-5",

    # --- субтитры ---
    "subs": True,
    "sub_font": "Arial Black",
    "sub_size": 82,
    "sub_y": 0.60,            # высота субтитров: 0 = верх кадра, 1 = низ (см. SUB_POSITIONS)
    "safe_zone": True,        # не заходить под кнопки и подписи TikTok / Shorts / Reels

    # --- ник в углу (тестовая функция, по умолчанию выключена) ---
    "nick": False,
    "nick_text": "Final_KFC_Boss",
    "nick_corner": "Сверху слева",  # см. NICK_CORNERS
    "nick_size": 40,                # размер шрифта при ширине кадра 1080
    "nick_opacity": 70,             # непрозрачность, %
    "sub_max_words": 3,
    "sub_mode": "words",      # words — по 2–3 слова; single — по одному слову
    "sub_color": "#FFFFFF",   # текст
    "sub_hl_color": "#FFE600",  # текущее слово
    "sub_outline_color": "#000000",
    "sub_outline": 7,         # толщина обводки при ширине кадра 1080
    "sub_x": None,            # центр строки по ширине (доля кадра); None — середина области
    "sub_style": "Обычный",   # сохранённый стиль
    "sub_max_chars": 18,
    "sub_uppercase": True,

    # --- зум ---
    "zoom": "auto",           # зум: auto — только на яркой реакции, on — на громких местах, off
    "zoom_amount": 0.18,      # +18% при зуме
    "zoom_focus_y": 0.35,     # куда зумить по вертикали: 0 = верх (вебка), 0.5 = центр, 1 = низ
    "max_zooms": 3,           # макс. зумов на клип

    # --- мат ---
    "bleep": True,
    "bleep_soft": True,       # запикивать ещё и «сука», «хер», «мудак», «пидор» и т.п.
    # звук поверх мата: перелистывание / буп / свист / тишина / бип —
    # или имя своего файла из папки «звуки» (mp3, wav, ogg...)
    "bleep_sound": "перелистывание",
    "censor": "partial",      # мат: partial — скрыть часть слова (е*ать), full — целиком (б****)
    "bleep_volume": 1.0,      # 1.0 = как есть, 0.5 = тише, 1.5 = громче (если речь не измерить)
    "bleep_rel_db": 0.0,      # громкость звука на мат относительно речи рядом, дБ (0 — на уровне голоса)
    "bleep_pad": 0.06,        # запас вокруг слова, сек

    # --- описание к клипу: хэштеги (всего не больше 5) ---
    "hashtags": "",                                  # всегда добавлять
    "platform_tags": {"tiktok": "", "youtube": "#shorts", "instagram": "#reels"},

    # --- метки из OBS (горячая клавиша «Добавить маркер главы», запись в Hybrid MP4) ---
    "marks": True,
    "mark_window": 30.0,      # метку ставят после момента: ищем момент за 30 с до неё
    "mark_bonus": 3.0,        # прибавка к оценке клипа с меткой

    # --- хук: 1–2 с яркой реакции из этого же клипа в самом начале ---
    "hook": "auto",               # хук: auto — когда есть яркий момент, on — всегда, если есть место, off
    "hook_min_reaction": 1.0,     # реакция для хука — не слабее этого
    "hook_percentile": 97,        # и сильнее, чем 97% секунд этой записи

    # --- экспорт ---
    "preset": "TikTok 1080p60",   # имя пресета из load_presets()
    "clip_length": "normal",      # длина клипов: short / normal / long (LENGTHS)
}
# ======================================================

# «Длина клипов» одной настройкой: сколько брать до и после момента и в каких пределах.
# normal — как в 1.1; long — больше контекста; short — плотнее.
LENGTHS = {
    "short": {"pre": 10.0, "post": 5.0, "min_len": 12.0, "max_len": 40.0},
    "normal": {"pre": 14.0, "post": 7.0, "min_len": 15.0, "max_len": 55.0},
    "long": {"pre": 18.0, "post": 10.0, "min_len": 20.0, "max_len": 60.0},
}


def apply_length(cfg=None):
    """Подставляет в настройки значения границ для выбранной «Длины клипов»."""
    cfg = CONFIG if cfg is None else cfg
    cfg.update(LENGTHS.get(cfg.get("clip_length"), LENGTHS["normal"]))
    return cfg


# ---------------- утилиты ----------------

def log(msg):
    print(msg, flush=True)


def fmt_time(sec):
    sec = max(0, int(sec))
    return f"{sec // 3600:d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def fmt_time_exact(sec):
    """Время с десятыми: 0:01:18.4 — для точного ввода границ клипа."""
    sec = max(0.0, round(float(sec), 1))
    whole = int(sec)
    return f"{whole // 3600:d}:{whole % 3600 // 60:02d}:{whole % 60:02d}.{int(round((sec - whole) * 10)) % 10}"


class AutoClipError(Exception):
    """Ошибка, которую можно показать пользователю как есть."""


class Cancelled(AutoClipError):
    def __init__(self, msg="⛔ Остановлено."):
        super().__init__(msg)


def _is_cancelled(cancel):
    """cancel — threading.Event или функция, которая возвращает True, когда пора остановиться."""
    if cancel is None:
        return False
    if hasattr(cancel, "is_set"):
        return cancel.is_set()
    return bool(cancel())


def check_cancel(cancel):
    if _is_cancelled(cancel):
        raise Cancelled()


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # без мигающих консолей под pythonw
_LOW_PRIORITY = 0x00004000    # BELOW_NORMAL_PRIORITY_CLASS
_proc_priority = 0            # в фоновой сборке ffmpeg запускается с пониженным приоритетом


def _flags():
    return _NO_WINDOW | (_proc_priority if os.name == "nt" else 0)


def run(cmd, cwd=None, quiet=True, cancel=None, binary=False, on_time=None):
    """on_time(секунд готово) — ход работы ffmpeg (через -progress), для полосы прогресса."""
    if on_time is not None:
        return _run_progress(cmd, cwd, quiet, cancel, on_time)
    text = {} if binary else {"encoding": "utf-8", "errors": "replace"}
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            creationflags=_flags(), **text)
    while True:
        try:
            out, err = proc.communicate(timeout=0.3)
            break
        except subprocess.TimeoutExpired:
            if _is_cancelled(cancel):
                proc.kill()
                proc.communicate()
                raise Cancelled()
    p = subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    if p.returncode != 0 and not quiet and not binary:
        log(p.stderr[-3000:])
    return p


def _run_progress(cmd, cwd, quiet, cancel, on_time):
    import threading
    cmd = [cmd[0], "-progress", "pipe:1", "-nostats"] + list(cmd[1:])
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                            creationflags=_flags())
    err = []
    t = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
    t.start()
    for line in proc.stdout:
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                on_time(int(line.split("=", 1)[1]) / 1e6)
            except (ValueError, Exception):
                pass
        if _is_cancelled(cancel):
            proc.kill()
            proc.wait()
            raise Cancelled()
    proc.wait()
    t.join(5)
    p = subprocess.CompletedProcess(cmd, proc.returncode, "", "".join(err))
    if p.returncode != 0 and not quiet:
        log(p.stderr[-3000:])
    return p


class Eta:
    """Сколько осталось — по уже прошедшему времени, сглаженно, без скачков."""

    def __init__(self, now=None):
        self.t0 = now if now is not None else time.time()
        self.left = None

    def update(self, frac, now=None):
        """frac — доля сделанного 0..1. Возвращает секунды до конца или None (рано судить)."""
        now = now if now is not None else time.time()
        spent = now - self.t0
        if frac <= 0.02 or spent < 2:
            return None
        raw = spent * (1 - frac) / frac
        if self.left is None:
            self.left = raw
        else:
            # плавно: новая оценка весит 15%, а прошедшее время честно вычитается
            self.left = 0.85 * max(0.0, self.left - (now - self._last)) + 0.15 * raw
        self._last = now
        return max(0.0, self.left)

    _last = 0.0


def fmt_left(sec):
    """«осталось около 2 мин» / «меньше минуты»."""
    if sec is None:
        return ""
    if sec < 45:
        return "осталось меньше минуты"
    m = int(round(sec / 60))
    return f"осталось около {m} мин" if m < 90 else f"осталось около {m / 60:.1f} ч".replace(".", ",")


# ---------------- режимы сборки ----------------

BUILD_MODES = {"auto": "Авто", "full": "На полную", "background": "Фоновый"}
# стриминг и запись: при них «Авто» собирает в фоне
BUSY_PROCESSES = ("obs64.exe", "obs32.exe", "obs.exe", "streamlabs obs.exe")


def running_processes():
    """Имена запущенных программ (нижним регистром). Без psutil — через tasklist."""
    if os.name != "nt":
        return set()
    try:
        p = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                           encoding="cp866", errors="replace", timeout=10, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.split('","')[0].strip('"').lower() for line in p.stdout.splitlines() if line}


def fullscreen_app():
    """Имя программы, которая сейчас на весь экран (игра), или None."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return None
        cls = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, cls, 256)
        if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return None                       # рабочий стол и панель задач — не игра
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return None
        r = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi)):
            return None
        m = mi.rcMonitor
        if (r.left, r.top, r.right, r.bottom) != (m.left, m.top, m.right, m.bottom):
            return None
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
        name = "программа на весь экран"
        if h:
            buf = ctypes.create_unicode_buffer(520)
            size = wintypes.DWORD(520)
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = os.path.basename(buf.value)
            k.CloseHandle(h)
        return name
    except Exception:
        return None


def resolve_build_mode(mode=None, procs=None, fullscreen=None):
    """("full" | "background", почему). «Авто»: OBS или игра запущены — фоновый, иначе на полную."""
    mode = mode or CONFIG.get("build_mode", "auto")
    if mode in ("full", "background"):
        return mode, "выбрано в настройках"
    procs = running_processes() if procs is None else {p.lower() for p in procs}
    games = [g.strip().lower() for g in str(CONFIG.get("game_processes", "")).split(",") if g.strip()]
    games = [g if g.endswith(".exe") else g + ".exe" for g in games]
    for name in BUSY_PROCESSES:
        if name in procs:
            return "background", f"запущен {name}"
    for name in games:
        if name in procs:
            return "background", f"запущена игра {name}"
    fs = fullscreen_app() if fullscreen is None else fullscreen
    if fs:
        return "background", f"на весь экран: {fs}"
    return "full", "OBS и игры не запущены"


def _set_self_priority(low):
    """Понизить (или вернуть) приоритет самой программы — Whisper считает в ней."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), _LOW_PRIORITY if low else 0x00000020)
    except Exception:
        pass


def need_ffmpeg():
    # ffmpeg.exe / ffprobe.exe можно просто положить рядом со скриптом
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in os.environ.get("PATH", "").split(os.pathsep):      # один раз, а не при каждом вызове
        os.environ["PATH"] = here + os.pathsep + os.environ.get("PATH", "")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise AutoClipError(f"❌ Не найден {tool}. Установи ffmpeg (install.bat) и перезапусти окно.")


def probe(video):
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
             "-show_format", video])
    if p.returncode != 0:
        raise AutoClipError("❌ ffprobe не смог прочитать видео:\n" + p.stderr)
    info = json.loads(p.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if not v:
        raise AutoClipError("❌ В файле нет видеодорожки.")
    if not a:
        raise AutoClipError("❌ В файле нет звука — без звука искать моменты нечем.")
    try:
        num, den = v.get("avg_frame_rate", "0/1").split("/")
        fps = round(float(num) / float(den), 3)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return {
        "w": int(v["width"]), "h": int(v["height"]),
        "dur": float(info["format"]["duration"]), "fps": fps,
    }


def thumbnail(video, out_png, box=240):
    """Кадр из записи для превью, вписанный в квадрат box×box (около 10% от начала, не дальше 5 минут).
    Возвращает сведения о видео из probe()."""
    vinfo = probe(video)
    at = min(vinfo["dur"] * 0.1, 300.0)
    p = run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", video, "-frames:v", "1",
             "-vf", f"scale={box}:{box}:force_original_aspect_ratio=decrease:flags=lanczos",
             out_png])
    if p.returncode != 0 or not os.path.isfile(out_png):
        raise AutoClipError("❌ Не получилось взять кадр из видео.")
    return vinfo


def _boxes(f, start, end):
    """Боксы mp4 между start и end: [(тип, начало данных, конец)] — читаем только заголовки."""
    import struct
    out, pos = [], start
    while pos + 8 <= end:
        f.seek(pos)
        size, kind = struct.unpack(">I4s", f.read(8))
        head = 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            head = 16
        elif size == 0:
            size = end - pos
        if size < head:
            break
        out.append((kind.decode("latin-1"), pos + head, pos + size))
        pos += size
    return out


def mp4_chapters(path):
    """Главы mp4 без ffprobe: дорожка глав (handler «text», как пишет OBS Hybrid MP4) или
    бокс chpl. Из большого файла читаются только боксы moov. [(сек, название)]."""
    import struct
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            moov = next(((a, b) for k, a, b in _boxes(f, 0, size) if k == "moov"), None)
            if not moov:
                return []
            f.seek(moov[0])
            data = f.read(moov[1] - moov[0])
    except OSError:
        return []

    def boxes(buf, a, b):
        out, pos = [], a
        while pos + 8 <= b:
            sz, kind = struct.unpack(">I4s", buf[pos:pos + 8])
            head = 8
            if sz == 1:
                sz = struct.unpack(">Q", buf[pos + 8:pos + 16])[0]
                head = 16
            if sz < head or pos + sz > b:
                break
            out.append((kind.decode("latin-1"), pos + head, pos + sz))
            pos += sz
        return out

    def find(buf, a, b, path_):
        for k, x, y in boxes(buf, a, b):
            if k == path_[0]:
                return (x, y) if len(path_) == 1 else find(buf, x, y, path_[1:])
        return None

    out = []
    for k, a, b in boxes(data, 0, len(data)):
        if k == "udta":                                  # Nero chpl
            ch = find(data, a, b, ["chpl"])
            if ch:
                try:
                    x = ch[0] + 4 + (1 if data[ch[0]] == 1 else 0)   # версия, флаги, запас в v1
                    n, x = data[x], x + 1
                    for _ in range(n):
                        t = struct.unpack(">Q", data[x:x + 8])[0] / 1e7
                        ln = data[x + 8]
                        out.append((t, data[x + 9:x + 9 + ln].decode("utf-8", "replace")))
                        x += 9 + ln
                except (IndexError, struct.error):
                    pass
        if k != "trak":
            continue
        hd = find(data, a, b, ["mdia", "hdlr"])
        if not hd or data[hd[0] + 8:hd[0] + 12] != b"text":
            continue
        md = find(data, a, b, ["mdia", "mdhd"])
        st = find(data, a, b, ["mdia", "minf", "stbl"])
        if not (md and st):
            continue
        ver = data[md[0]]
        scale = struct.unpack(">I", data[md[0] + (20 if ver == 1 else 12):][:4])[0] or 1000
        tab = {kk: (x, y) for kk, x, y in boxes(data, st[0], st[1])}
        if not all(t in tab for t in ("stts", "stsz", "stsc")) or not ("stco" in tab or "co64" in tab):
            continue
        x = tab["stts"][0]
        times, t = [], 0
        for i in range(struct.unpack(">I", data[x + 4:x + 8])[0]):
            cnt, delta = struct.unpack(">II", data[x + 8 + 8 * i:x + 16 + 8 * i])
            for _ in range(cnt):
                times.append(t)
                t += delta
        x = tab["stsz"][0]
        fixed, n = struct.unpack(">II", data[x + 4:x + 12])
        sizes = [fixed] * n if fixed else list(struct.unpack(f">{n}I", data[x + 12:x + 12 + 4 * n]))
        if "stco" in tab:
            x = tab["stco"][0]
            m = struct.unpack(">I", data[x + 4:x + 8])[0]
            chunks = list(struct.unpack(f">{m}I", data[x + 8:x + 8 + 4 * m]))
        else:
            x = tab["co64"][0]
            m = struct.unpack(">I", data[x + 4:x + 8])[0]
            chunks = list(struct.unpack(f">{m}Q", data[x + 8:x + 8 + 8 * m]))
        x = tab["stsc"][0]
        runs = [struct.unpack(">III", data[x + 8 + 12 * i:x + 20 + 12 * i])
                for i in range(struct.unpack(">I", data[x + 4:x + 8])[0])]
        offsets, si = [], 0
        for ci, off in enumerate(chunks, 1):
            per = next((r[1] for r in reversed(runs) if r[0] <= ci), 1)
            for _ in range(per):
                if si >= len(sizes):
                    break
                offsets.append(off)
                off += sizes[si]
                si += 1
        try:
            with open(path, "rb") as f:
                for i, off in enumerate(offsets[:len(times)]):
                    f.seek(off)
                    raw = f.read(min(sizes[i], 1024))
                    ln = struct.unpack(">H", raw[:2])[0] if len(raw) >= 2 else 0
                    out.append((times[i] / scale, raw[2:2 + ln].decode("utf-8", "replace")))
        except OSError:
            continue
    return sorted(out)


def read_markers(video):
    """Метки, которые стример поставил в OBS горячей клавишей «Добавить маркер главы».
    OBS (Hybrid MP4) пишет их главами: читаем через ffprobe, а если он ничего не дал —
    сами из mp4 (дорожка глав / chpl). [{"t": сек, "name": ...}].
    Глава в самом начале записи — не метка, а начало файла."""
    chapters, how = [], "ffprobe"
    p = run(["ffprobe", "-v", "error", "-show_chapters", "-print_format", "json", video])
    if p.returncode == 0:
        try:
            for ch in json.loads(p.stdout).get("chapters", []):
                try:
                    chapters.append((float(ch["start_time"]), str(ch.get("tags", {}).get("title", ""))))
                except (KeyError, TypeError, ValueError):
                    continue
        except ValueError:
            pass
    else:
        log(f"   ⚠️  ffprobe не прочитал главы: {p.stderr.strip()[-200:]}")
    if not [t for t, _ in chapters if t >= 1.0]:
        own = mp4_chapters(video)
        if own:
            chapters, how = own, "разбор mp4"
    out = [{"t": round(t, 2), "name": name} for t, name in chapters if t >= 1.0]
    read_markers.how = how
    return sorted(out, key=lambda m: m["t"])


# ---------------- 1. звук ----------------

def extract_audio(video, wav, cancel=None):
    log("🔊 Достаю звук...")
    p = run(["ffmpeg", "-y", "-v", "error", "-i", video, "-map", "0:a:0", "-vn", "-ac", "1",
             "-ar", "16000", "-c:a", "pcm_s16le", wav], quiet=False, cancel=cancel)
    if p.returncode != 0:
        raise AutoClipError("❌ Не получилось достать звук из видео.")


def loudness_per_second(wav):
    """Громкость (dB) каждой секунды. Читаем кусками, чтобы не съесть память на 3-часовом файле."""
    import numpy as np
    out = []
    with wave.open(wav, "rb") as wf:
        sr = wf.getframerate()
        while True:
            frames = wf.readframes(sr)
            if not frames:
                break
            x = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
            out.append(20 * math.log10(rms + 1e-6))
    return np.array(out, dtype=np.float32)


# ---------------- 2. расшифровка ----------------

def _windows_cuda_dlls():
    """На Windows библиотеки CUDA из pip (nvidia-cublas, nvidia-cudnn) лежат не в PATH — добавляем."""
    if os.name != "nt":
        return
    import site
    roots = []
    try:
        roots += site.getsitepackages()
    except Exception:
        pass
    try:
        roots.append(site.getusersitepackages())
    except Exception:
        pass
    for r in roots:
        for d in glob.glob(os.path.join(r, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(d)
            except Exception:
                pass
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def _read_wav(wav):
    """WAV 16 кГц моно → float32 для Whisper (3 часа ≈ 0,7 ГБ памяти)."""
    import numpy as np
    with wave.open(wav, "rb") as wf:
        x = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    return x.astype(np.float32) / 32768.0


# Whisper на тишине и музыке иногда выдумывает титры из обучающих видео
_HALLUCINATIONS = re.compile(
    r"(?:субтитры|титры)\s+(?:делал|сделал|создавал|подготовил|подогнал|сделаны)\b.*"
    r"|.*dimatorzok.*|редактор субтитров.*|корректор.*|продолжение следует"
    r"|подписывайтесь на канал.*", re.I)


def unnatural(w):
    """Слово неестественной длины: так долго не произносят (Whisper растянул шум)."""
    letters = len(re.sub(r"[^\w]", "", w["w"]))
    return (w["e"] - w["s"]) > max(2.0, 0.3 * letters + 1.2)


def _voiced_share(words, regions):
    """Какая доля длины слов приходится на голос по Silero."""
    total = sum(w["e"] - w["s"] for w in words) or 1.0
    voiced = sum(max(0.0, min(w["e"], b) - max(w["s"], a)) for w in words for a, b in regions
                 if a < w["e"] and b > w["s"])
    return voiced / total


def drop_hallucinations(segments, regions=None):
    """Убирает то, что Whisper выдумал, а не услышал: известные фразы-«титры», слова
    неестественной длины и (если известно, где голос) куски, где голоса нет вовсе.
    Кусок, от которого почти ничего не осталось, уходит целиком."""
    import bisect
    starts = [a for a, _ in regions or []]
    out = []
    for seg in segments:
        text = re.sub(r"[^\w\s]", "", seg["text"].lower().replace("ё", "е")).strip()
        if text and _HALLUCINATIONS.fullmatch(text):
            continue
        words = seg.get("words", [])
        if regions and words:                             # голос не нашёлся вовсе — не судим
            j = max(0, bisect.bisect_right(starts, seg["s"]) - 1)
            if not any(a < seg["e"] and b > seg["s"] for a, b in regions[j:j + 50] if a < seg["e"]):
                continue                                  # голоса нет — Whisper выдумал
        if seg["s"] < START_SILENT and words and (
                (len(words) < 3 and all(w["e"] - w["s"] > 1.0 for w in words))
                or (regions and _voiced_share(words, regions) < 0.5)):
            continue                                      # «слова» в начале записи без голоса — шум
        good = [w for w in words if not unnatural(w)]
        if words and len(good) < len(words):
            if len(good) < 2 or len(good) < len(words) / 2:
                continue                                  # почти всё растянуто — кусок целиком
            seg = dict(seg, words=good, text=" ".join(w["w"] for w in good))
        out.append(seg)
    return out


ASR_VERSION = 2               # 2 — ровная громкость, мягкий VAD, без подсказки, время по звуку
# фильтр перед Whisper: выровнять громкость и сжать динамику — тихая речь не теряется
ASR_FILTER = "dynaudnorm=f=150:g=15:p=0.9:m=20,acompressor=threshold=0.05:ratio=4:attack=5:release=100"
# VAD: общий звук (голос + игра) и чистая дорожка микрофона / Discord (подобрано на записи 24.10)
VAD_MIX = {"threshold": 0.25, "min_silence_duration_ms": 800, "speech_pad_ms": 600}
VAD_VOICE = {"threshold": 0.2, "min_silence_duration_ms": 800, "speech_pad_ms": 600}


def audio_tracks(video):
    """Сколько звуковых дорожек в записи (OBS: 1 — общий звук, 2 — микрофон, 3 — Discord)."""
    p = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
             "-of", "csv=p=0", video])
    return len([x for x in p.stdout.split() if x.strip()]) if p.returncode == 0 else 1


def asr_audio(video, track, out, cancel=None):
    """Звук одной дорожки для Whisper: 16 кГц моно, ровная громкость."""
    p = run(["ffmpeg", "-y", "-v", "error", "-i", video, "-map", f"0:a:{track}", "-vn",
             "-af", ASR_FILTER, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out], cancel=cancel)
    if p.returncode != 0:
        raise AutoClipError(f"❌ Не получилось достать звук дорожки {track + 1}.")
    return out


def speech_regions(audio):
    """Где на самом деле звучит речь (Silero VAD, шаг ~30 мс): [(начало, конец)] в секундах."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except ImportError:
        return []
    opts = VadOptions(threshold=0.5, min_silence_duration_ms=150, speech_pad_ms=30)
    return [(r["start"] / 16000, r["end"] / 16000) for r in get_speech_timestamps(audio, opts)]


def refine_words(words, regions, max_shift=0.8):
    """Whisper ставит время слов раньше звука. Подвигаем границы к тому, где речь слышна:
    начало — к началу речи, если она начинается позже, но до конца слова; конец последнего
    слова перед паузой — к концу речи (не дальше следующего слова)."""
    import bisect
    if not regions:
        return words
    starts = [a for a, _ in regions]
    ws = sorted(words, key=lambda w: w["s"])
    out = []
    for i, w in enumerate(ws):
        s0, e0 = w["s"], w["e"]
        nxt = ws[i + 1]["s"] if i + 1 < len(ws) else math.inf
        j = max(0, bisect.bisect_right(starts, s0) - 1)
        reg = [r for r in regions[j:j + 4] if r[1] > s0 - 0.05 and r[0] < e0 + 0.6]
        s1, e1 = s0, e0
        if reg:
            a, b = reg[0]
            if s0 < a < e0 - 0.05 and a - s0 <= max_shift:      # звук начался позже
                s1 = round(a, 2)
            last = reg[-1]
            if nxt - e0 > 0.25 and last[0] < e0 + 0.3 and last[1] > e0:   # конец фразы
                e1 = round(min(last[1], nxt - 0.05, e0 + max_shift), 2)
        if e1 - s1 < 0.08:
            s1, e1 = s0, e0
        out.append(dict(w, s=s1, e=e1))
    return out


def _load_whisper():
    _windows_cuda_dlls()
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise AutoClipError("❌ Не установлен faster-whisper. Запусти install.bat.")
    global WHISPER_DEVICE
    name = CONFIG["whisper_model"]
    for device, ctype in (("cuda", "float16"), ("cpu", "int8")):
        try:
            log(f"🧠 Загружаю Whisper {name} ({device})... первый раз скачается ~3 ГБ")
            model = WhisperModel(name, device=device, compute_type=ctype)
            WHISPER_DEVICE = f"{device} {ctype}"
            if device == "cpu":
                log("⚠️  Видеокарта не подхватилась, считаю на процессоре — будет в разы медленнее.")
            return model
        except Exception as e:
            log(f"   не вышло на {device}: {e}")
    raise AutoClipError("❌ Whisper не запустился.")


def _asr(model, audio, vad, dur, spk, progress=None, cancel=None, part=(0, 1)):
    """Одна дорожка → сегменты со словами (у слова spk — кто сказал)."""
    # без initial_prompt: на записи 24.10 подсказка «ругательства полностью» убирала слова
    segments, _info = model.transcribe(audio, language=CONFIG["language"], word_timestamps=True,
                                       vad_filter=True, vad_parameters=vad, beam_size=5,
                                       condition_on_previous_text=False)
    out, last_print = [], 0
    k, n = part
    for sg in segments:
        check_cancel(cancel)
        words = [{"s": round(w.start, 2), "e": round(w.end, 2), "w": w.word.strip(), "spk": spk}
                 for w in (sg.words or []) if w.word.strip()]
        out.append({"s": round(sg.start, 2), "e": round(sg.end, 2), "text": sg.text.strip(),
                    "words": words, "spk": spk})
        pct = (k + min(1.0, sg.end / dur)) / n * 100
        if progress:
            progress("расшифровка", pct, f"{fmt_time(sg.end)} из {fmt_time(dur)}")
        if sg.end - last_print > 120:
            last_print = sg.end
            log(f"   {fmt_time(sg.end)} из {fmt_time(dur)} ({pct:.0f}%)")
    return out


def _refine_segments(segments, audio):
    """Уточнить время слов по звуку — по всем словам сразу, чтобы слово не заехало на
    первое слово следующего куска Whisper."""
    regions = speech_regions(audio)
    flat = [(k, j, w) for k, sg in enumerate(segments) for j, w in enumerate(sg["words"])]
    order = sorted(range(len(flat)), key=lambda n: flat[n][2]["s"])
    refined = refine_words([dict(flat[n][2], _n=n) for n in order], regions)
    for w in refined:
        k, j, _ = flat[w.pop("_n")]
        segments[k]["words"][j] = w
    segments = [sg for sg in segments if sg["words"] or not sg.get("text")]
    for sg in segments:
        if sg["words"]:
            sg["s"], sg["e"] = min(w["s"] for w in sg["words"]), max(w["e"] for w in sg["words"])
    return drop_hallucinations(segments, regions)     # уже по уточнённому времени


def cache_paths(video):
    stem = os.path.splitext(os.path.abspath(video))[0]
    return stem + ".transcript.v2.json", stem + ".transcript.json"


def read_transcript(path):
    """Расшифровка из файла: новый формат {"version", "segments"} или старый — список."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["segments"] if isinstance(data, dict) else data


def _save_transcript(path, segments, how):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": ASR_VERSION, "how": how, "segments": segments}, f, ensure_ascii=False)


def transcribe(video, dur, tmp, progress=None, cancel=None, fresh=False):
    """Расшифровка записи → (сегменты, путь кэша). Кэш новой версии — «.transcript.v2.json».
    Старая расшифровка («.transcript.json», её используют прежние нарезки) не меняется: слова
    из неё берутся, но время уточняется по звуку. fresh — расшифровать заново.
    Дорожки 2 и 3 (микрофон и Discord) — отдельно; у слова spk: me / team."""
    new_cache, old_cache = cache_paths(video)
    if not fresh and os.path.exists(new_cache):
        log("📝 Расшифровка уже есть, беру из кэша.")
        return read_transcript(new_cache), new_cache
    tracks = audio_tracks(video)
    plan = [(1, "me", VAD_VOICE), (2, "team", VAD_VOICE)] if tracks >= 3 else [(0, "me", VAD_MIX)]
    if tracks >= 3:
        log("🎙  В записи 3 дорожки: расшифровываю микрофон и Discord отдельно")
    audios = {}
    for track, spk, _ in plan:
        audios[spk] = _read_wav(asr_audio(video, track, os.path.join(tmp, f"asr_{spk}.wav"), cancel))
    if not fresh and os.path.exists(old_cache) and tracks < 3:
        log("📝 Расшифровка уже есть, беру из кэша и уточняю время слов по звуку.")
        segments = _refine_segments(read_transcript(old_cache), audios["me"])
        _save_transcript(new_cache, segments, "старая расшифровка, время по звуку")
        return segments, new_cache
    model = _load_whisper()
    log("📝 Расшифровываю речь (на 3 часа записи — примерно 10–25 минут на видеокарте)...")
    t0 = time.time()
    segments = []
    try:
        for k, (track, spk, vad) in enumerate(plan):
            got = _asr(model, audios[spk], vad, dur, spk, progress, cancel, (k, len(plan)))
            segments += _refine_segments(got, audios[spk])
    except AutoClipError:
        raise
    except Exception as e:
        raise AutoClipError(f"❌ Ошибка расшифровки: {e}\n"
                            "   Если ошибка про cublas/cudnn — запусти install.bat ещё раз.")
    segments.sort(key=lambda sg: sg["s"])
    log(f"   готово за {(time.time() - t0) / 60:.1f} мин")
    _save_transcript(new_cache, segments, "whisper")
    return segments, new_cache


def speaker_segments(segments, spk="me"):
    """Только речь одного говорящего (старые расшифровки — всё «me»)."""
    out = []
    for sg in segments:
        ws = [w for w in sg["words"] if w.get("spk", "me") == spk]
        if ws:
            out.append(dict(sg, words=ws))
    return out


# ---------------- 3. мат ----------------

_PFX = (r"(?:за|на|по|от|отъ|оть|у|вы|при|до|объ|вз|въ|разъ|изъ|съ|сь|подъ|пере|про|"
        r"недо|долбо|долба|ни)?")
_HARD = [
    re.compile(r"ху[йеяи]"),                     # хуй, хуе, хуя, хуи + производные
    re.compile(r"^" + _PFX + r"хую"),            # «хую», «нахую» (но не «тихую», «плохую»)
    re.compile(r"пизд"),
    re.compile(r"^" + _PFX + r"еб"),             # ебать, заебал, долбоеб, съебал (но не «себе»)
    re.compile(r"^(?:вы|рас|раз)?бля"),          # бля, блять, выблядок (но не «оскорблять»)
]
_HARD_EXCEPT = re.compile(r"страху|психу|^хуа|хунт")
_SOFT = [
    re.compile(r"^сук(?:а|и|у|ой|ам|ами|ах|ин|ина|ины|ину)?$"),
    re.compile(r"^сучк"),
    re.compile(r"^(?:на|по)?хер(?!сон)"),
    re.compile(r"^муд[аио]"),
    re.compile(r"^пид[оа]?р"),
    re.compile(r"залуп"),
    re.compile(r"^г[ао]ндон"),
    re.compile(r"шлюх"),
    re.compile(r"^манд(?:а|у|ой|е|ы|ец|ой)$"),
]


def clean_word(w):
    return re.sub(r"[^\w*]", "", w.lower().replace("ё", "е"))


def is_profane(word):
    w = clean_word(word)
    if not w:
        return False
    if "*" in w:                     # Whisper иногда сам пишет «б***ь»
        return True
    if not _HARD_EXCEPT.search(w) and any(p.search(w) for p in _HARD):
        return True
    if CONFIG["bleep_soft"] and any(p.search(w) for p in _SOFT):
        return True
    return False


_LAUGH = re.compile(r"^(?:а?ха){2,}|^(?:ах){2,}|^х[еи]х|^пхах|^лол$|^ору$|^ржу|^кек$|^ахах")


def is_laugh(word):
    return bool(_LAUGH.search(clean_word(word)))


# ---------------- 4. языковая модель (по желанию) ----------------

LLM_PROMPT = """Ты — монтажёр коротких вертикальных видео (TikTok, YouTube Shorts, Reels) для русскоязычного игрового стримера.
Ниже кусок расшифровки стрима, в квадратных скобках — секунда от начала записи.

Найди фрагменты, которые зайдут как отдельный короткий ролик:
- смешное, абсурдное, неожиданное, сильная эмоция (крик, ярость, восторг, паника, смех);
- удачная фраза или шутка, конфликт, эпичный момент в игре, который видно по реакции;
- фрагмент должен быть понятен без контекста и цеплять с первых 2 секунд.
Длина каждого 15–60 секунд. Не бери скучные куски, объяснения настроек, паузы.
Если хорошего ничего нет — верни пустой список.

Ответь ТОЛЬКО JSON без пояснений:
{"moments": [{"start": 123.0, "end": 151.0, "score": 8, "title": "короткое название 3-6 слов", "reason": "почему зайдёт"}]}
score — от 1 до 10, насколько это вирусно.

Расшифровка:
"""


def _http_json(url, payload, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _ollama_alive():
    try:
        with urllib.request.urlopen(CONFIG["ollama_url"] + "/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def ollama_models():
    """Какие модели скачаны в Ollama ([] — Ollama не запущена или моделей нет)."""
    try:
        with urllib.request.urlopen(CONFIG["ollama_url"] + "/api/tags", timeout=2) as r:
            return [m["name"] for m in json.loads(r.read().decode("utf-8")).get("models", [])]
    except Exception:
        return []


def resolve_ollama_model(models=None):
    """Модель из настроек, если она скачана; иначе — подходящая скачанная (та же семья,
    потом qwen3:14b, потом любая). None — скачанных моделей нет."""
    models = ollama_models() if models is None else models
    if not models:
        return None
    want = CONFIG["ollama_model"].strip()
    names = {m.lower(): m for m in models}
    for cand in (want, want + ":latest"):
        if cand.lower() in names:
            return names[cand.lower()]
    family = want.split(":")[0].lower()
    return (next((m for m in models if m.lower().split(":")[0] == family), None)
            or names.get("qwen3:14b") or models[0])


def pick_llm(mode):
    """Какую модель звать: ollama / anthropic / none. Для Ollama заодно проверяет, что
    модель из настроек скачана, а если нет — берёт скачанную и говорит об этом."""
    if mode in ("auto", "ollama"):
        if _ollama_alive():
            model = resolve_ollama_model()
            if model:
                if model != CONFIG["ollama_model"]:
                    log(f"   ⚠️  модели {CONFIG['ollama_model']} нет в Ollama — беру {model}")
                    CONFIG["ollama_model"] = model
                return "ollama"
            log("   ⚠️  в Ollama нет ни одной модели — скачай: ollama pull qwen3:14b")
        elif mode == "ollama":
            log("   ⚠️  Ollama не запущена — ищу без модели")
        if mode == "auto" and os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        return "none"
    return mode


_warned = set()


def warn_once(msg):
    """Одно и то же предупреждение — один раз за нарезку, а не на каждый клип."""
    if msg not in _warned:
        _warned.add(msg)
        log(msg)


def _parse_moments(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for it in data.get("moments", []) if isinstance(data, dict) else []:
        try:
            s, e = float(it["start"]), float(it["end"])
            if e > s:
                out.append({"s": s, "e": e, "score": float(it.get("score", 5)),
                            "title": str(it.get("title", ""))[:60],
                            "reason": str(it.get("reason", ""))[:200]})
        except (KeyError, TypeError, ValueError):
            continue
    return out


_THINKING_MODELS = ("qwen3", "deepseek-r1", "magistral", "gpt-oss")
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)


def _ask_llm(prompt, mode, max_tokens=2000):
    """Текст ответа языковой модели (ollama / anthropic). Ошибки сети — исключением."""
    if mode == "ollama":
        model = CONFIG["ollama_model"]
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json", "stream": False,
            "options": {"temperature": 0.3, "num_ctx": 16384},
        }
        if model.lower().startswith(_THINKING_MODELS):
            payload["think"] = False             # Qwen3 и др. иначе сначала «думают вслух»
        r = _http_json(CONFIG["ollama_url"] + "/api/chat", payload, {}, timeout=600)
        # если модель всё же подумала вслух — рассуждения не нужны, нужен только ответ
        return _THINK_BLOCK.sub("", r.get("message", {}).get("content", "")).strip()
    r = _http_json("https://api.anthropic.com/v1/messages", {
        "model": CONFIG["anthropic_model"],
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }, {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01"}, timeout=180)
    return "".join(b.get("text", "") for b in r.get("content", []))


def taste_block(examples):
    """Примеры клипов, которые нравятся Гоше или зашли зрителям, — для запроса к модели."""
    if not examples:
        return ""
    return ("Примеры клипов, которые нравятся стримеру или хорошо зашли зрителям "
            "(ищи похожее по духу):\n" + "\n".join(f"- «{t}»" for t in examples) + "\n\n")


def llm_moments(segments, mode, progress=None, cancel=None, examples=()):
    if mode == "none" or not segments:
        return []
    taste = taste_block(examples)
    chunk_len, overlap = 600.0, 30.0
    end_all = segments[-1]["e"]
    moments, start = [], 0.0
    n_chunks = max(1, math.ceil(end_all / (chunk_len - overlap)))
    i = 0
    while start < end_all:
        i += 1
        lines = [f"[{s['s']:.0f}] {s['text']}" for s in segments
                 if s["e"] > start and s["s"] < start + chunk_len and s["text"]]
        start += chunk_len - overlap
        if len(lines) < 3:
            continue
        check_cancel(cancel)
        log(f"   кусок {i}/{n_chunks}")
        if progress:
            progress("модель", (i - 1) / n_chunks * 100, f"кусок {i} из {n_chunks}")
        prompt = LLM_PROMPT.replace("Расшифровка:\n", taste + "Расшифровка:\n") + "\n".join(lines)
        try:
            moments += _parse_moments(_ask_llm(prompt, mode))
        except urllib.error.HTTPError as e:
            warn_once(f"   ⚠️  модель ответила ошибкой {e.code}: {e.read()[:300]!r}")
        except Exception as e:
            log(f"   ⚠️  модель недоступна ({e}), продолжаю без неё")
            return moments
    return moments


# ---------------- 5. поиск моментов ----------------

def score_timeline(loud, segments, moments):
    import numpy as np
    n = len(loud)
    # громкость относительно фона последних/следующих 2 минут
    win = 121
    pad = np.pad(loud, (win // 2, win // 2), mode="edge")
    from numpy.lib.stride_tricks import sliding_window_view
    base = np.median(sliding_window_view(pad, win), axis=1)[:n]
    diff = loud - base
    mad = float(np.median(np.abs(diff - np.median(diff)))) + 1e-3
    loud_z = np.clip(diff / (1.4826 * mad), -2, 5)
    loud_z[loud < -50] = -2                     # тишина

    words = np.zeros(n)
    laugh = np.zeros(n)
    mat = np.zeros(n)
    excl = np.zeros(n)
    for seg in segments:
        if "!" in seg["text"]:
            a, b = int(seg["s"]), min(n, int(seg["e"]) + 1)
            excl[a:b] += 1
        for w in seg["words"]:
            i = int(w["s"])
            if 0 <= i < n:
                words[i] += 1
                if is_laugh(w["w"]):
                    laugh[i] += 1
                if is_profane(w["w"]):
                    mat[i] += 1

    llm = np.zeros(n)
    for m in moments:
        a, b = max(0, int(m["s"])), min(n, int(m["e"]) + 1)
        llm[a:b] = np.maximum(llm[a:b], m["score"] / 10.0)

    k = np.ones(5) / 5
    # разбор оценки: вклад каждого признака (сглаженный); их сумма = итоговая оценка
    parts = {
        "громкость": 1.0 * loud_z,
        "смех": 1.5 * np.minimum(laugh, 3),
        "восклицания": 0.4 * np.minimum(excl, 1),
        "мат": 0.6 * np.minimum(mat, 2),
        "речь": 0.15 * np.minimum(words, 6),
        "модель": 3.0 * llm,
    }
    parts = {name: np.convolve(arr, k, mode="same") for name, arr in parts.items()}
    smooth = sum(parts.values())
    return smooth, loud_z, parts


# ---------------- хук ----------------

HOOK_MIN, HOOK_MAX = 1.0, 2.0     # длина хука, сек
PAD_BEFORE, PAD_AFTER = 0.15, 0.4  # запас до первого и после последнего слова (клип и хук)


def pad_before(w, prev):
    """Где начать перед словом w: за PAD_BEFORE до него, в короткой паузе — посередине."""
    gap = (w["s"] - prev["e"]) if prev else math.inf
    return max(0.0, w["s"] - (PAD_BEFORE if gap >= 2 * PAD_BEFORE else max(0.0, gap) / 2))


def pad_after(w, nxt):
    """Где закончить после слова w: через PAD_AFTER, в короткой паузе — посередине."""
    gap = (nxt["s"] - w["e"]) if nxt else math.inf
    return w["e"] + (PAD_AFTER if gap >= 2 * PAD_AFTER else max(0.0, gap) / 2)
HOOK_SKIP_START = 3.0             # пик в первые 3 с — клип и так начинается с действия


def reaction_curve(parts):
    """Реакция стримера по секундам: смех, мат, восклицания и громкость, но громкость
    без речи рядом (просто звук игры) весит втрое меньше."""
    import numpy as np
    voice = parts["речь"] > 0.05
    return (parts["смех"] + parts["восклицания"] + parts["мат"]
            + parts["громкость"] * np.where(voice, 1.0, 0.3))


def _hook_window(i, s, e, words):
    """1–2 с вокруг секунды i, строго внутри клипа [s, e]. Начало — в паузе перед фразой,
    конец — в паузе после слова, с запасом: хук не режет слово (время слов у Whisper
    внутри фразы неточное, поэтому середину фразы не берём)."""
    ws = sorted((w for w in words if w["s"] >= s and w["e"] <= e), key=lambda w: w["s"])
    target = max(s, i - 0.5)
    starts = []
    for k, w in enumerate(ws):
        prev = ws[k - 1] if k else None
        if prev is None or w["s"] - prev["e"] >= PAUSE:
            starts.append((max(s, pad_before(w, prev)), k))
    best = None
    for hs, k in sorted(starts, key=lambda x: (abs(x[0] - target), x[0] > i)):
        ends = []
        for j in range(k, len(ws)):
            nxt = ws[j + 1] if j + 1 < len(ws) else None
            if nxt is not None and nxt["s"] - ws[j]["e"] < 0.08:
                continue                              # между словами нет зазора — тут не резать
            he = min(e, pad_after(ws[j], nxt))
            if he - hs > HOOK_MAX:
                break
            if he - hs >= HOOK_MIN * 0.8:
                ends.append(he)
        if ends:
            best = (hs, min(ends, key=lambda x: abs(x - hs - 1.6)))
            break
    if best is None and ws:
        # реакция без слов (смех, крик): пауза между словами вокруг секунды i, хук — в ней
        edges = [s] + [x for w in ws for x in (w["s"], w["e"])] + [e]
        gaps = [(edges[k] + (0.05 if k else 0.0), edges[k + 1] - (0.05 if k + 2 < len(edges) else 0.0))
                for k in range(0, len(edges) - 1, 2)]
        for ga, gb in gaps:
            if ga <= i <= gb and gb - ga >= HOOK_MIN:
                hs = max(ga, min(i - 0.5, gb - 1.6))
                return round(hs, 2), round(min(gb, hs + 1.6), 2)
        return None, None                             # без разреза слова хук не поставить
    if best is None:                                  # слов нет — просто 1,6 с вокруг пика
        hs = max(s, i - 0.5)
        he = min(e, hs + 1.6)
        if he - hs < HOOK_MIN:
            he = min(e, hs + HOOK_MIN)
            hs = max(s, he - HOOK_MIN)
        best = (hs, he)
    return round(best[0], 2), round(best[1], 2)


def _what_reaction(i, parts):
    if not parts:
        return "яркая реакция"
    what = [name for key, name in (("смех", "смех"), ("мат", "мат"), ("восклицания", "крик"))
            if parts[key][i] > 0.1]
    if parts["громкость"][i] > 1.5 and parts["речь"][i] > 0.05 and "крик" not in what:
        what.append("громкий голос")
    return " и ".join(what) or "яркая реакция"


TRI = ("auto", "on", "off")


def tri(v, old_true="auto"):
    """Хук и зум: «auto» / «on» / «off». Старое True — old_true (в общих настройках это было
    «как решит программа», у клипа — «включить»), False — «off», None — None (как у нарезки)."""
    if v is None:
        return None
    if v is True:
        return old_true
    if v is False:
        return "off"
    return v if v in TRI else "auto"


def auto_zooms(s, e, reaction, parts=None, threshold=None, limit=3):
    """Зум в «Авто»: только на яркой реакции голосом (смех, крик, громкий голос — не звук игры),
    не больше limit на клип, не ближе 5 с друг к другу. [{t, why}] во времени записи."""
    import numpy as np
    reaction = np.asarray(reaction, dtype=float)
    if not len(reaction):
        return []
    thr = hook_threshold(reaction) if threshold is None else threshold
    lo, hi = int(math.ceil(s + 1.0)), min(len(reaction), int(math.floor(e - 2.0)) + 1)
    cand = []
    for i in range(lo, hi):
        if reaction[i] < 0.8 * thr:
            continue
        if parts:
            voice = (parts["смех"][i] > 0.3 or parts["восклицания"][i] > 0.3 or
                     (parts["громкость"][i] > 1.5 and parts["речь"][i] > 0.05))
            if not voice:
                continue                         # громко, но не голос — звук игры, без зума
        cand.append(i)
    out = []
    for i in sorted(cand, key=lambda i: -reaction[i]):
        if len(out) >= limit:
            break
        if all(abs(i - z["t"]) >= 5 for z in out):
            out.append({"t": float(i), "why": _what_reaction(i, parts)})
    return sorted(out, key=lambda z: z["t"])


def clip_zooms(rec, cfg, s=None, e=None):
    """Точки зума для рендера и почему: (точки, текст). Личная настройка клипа важнее общей."""
    s = rec.get("start", rec.get("s")) if s is None else s
    e = rec.get("end", rec.get("e")) if e is None else e
    mode = tri((rec.get("overrides") or {}).get("zoom"), "on") or tri(cfg.get("zoom"))
    if mode == "off":
        return [], "без зума — выключен"
    if mode == "on" or "zoom_auto" not in rec:              # нарезки до 1.3.0 — как раньше
        pts = [z for z in rec.get("zooms", []) if s <= z <= e]
        return pts, ("зум: " + ", ".join(_mmss(z - s) for z in pts)) if pts else "без зума — нет громких мест"
    pts = [z for z in rec["zoom_auto"] if s <= z["t"] <= e]
    if not pts:
        return [], "без зума — нет яркой реакции"
    return [z["t"] for z in pts], "зум: " + ", ".join(f"{z['why']} на {_mmss(z['t'] - s)}" for z in pts)


def _mmss(t):
    t = int(max(0.0, t))
    return f"{t // 60}:{t % 60:02d}"


def hook_threshold(reaction, cfg=None):
    """Порог яркой реакции для этой записи: у тихих и громких записей он разный."""
    import numpy as np
    cfg = cfg or CONFIG
    return max(cfg["hook_min_reaction"],
               float(np.percentile(np.asarray(reaction, dtype=float), cfg["hook_percentile"])))


def _voice_hook_window(i, s, e, voice):
    """Хук по паузам в голосе (Silero): Whisper часто ставит слова встык, а настоящая пауза
    между ними есть. Края — в середине тишины, слово не режется. (начало, конец) или (None, None)."""
    regs = sorted((a, b) for a, b in voice if b > s and a < e)
    if not regs:
        return None, None
    cuts = []
    for (a1, b1), (a2, b2) in zip(regs, regs[1:]):
        if a2 - b1 >= 0.12:
            cuts.append(round((b1 + a2) / 2, 2))
    if regs[0][0] - s >= 0.12:
        cuts.insert(0, round(max(s, regs[0][0] - 0.1), 2))
    if e - regs[-1][1] >= 0.12:
        cuts.append(round(min(e, regs[-1][1] + 0.1), 2))
    best = None
    for hs in cuts:
        for he in cuts:
            ln = he - hs
            if not (HOOK_MIN * 0.8 <= ln <= HOOK_MAX) or not (s <= hs and he <= e):
                continue
            cover = hs - 0.3 <= i <= he                        # яркая секунда внутри хука
            key = (not cover, abs((hs + he) / 2 - (i + 0.5)), abs(ln - 1.6))
            if best is None or key < best[0]:
                best = (key, hs, he)
    if best is None or best[0][1] > 3.0:
        return None, None
    return best[1], best[2]


def decide_hook(s, e, reaction, segments, parts=None, threshold=None, cfg=None, voice=None):
    """Решение про хук для клипа [s, e]. Хук всегда берётся из этого же клипа.
    Возвращает {"on", "auto", "start", "end", "why"}: auto — совет ставить хук,
    start/end — лучший момент (есть, даже если совет «не ставить»), on заполняет рендер."""
    import numpy as np
    cfg = cfg or CONFIG
    rec = {"on": False, "auto": False, "start": None, "end": None, "why": ""}
    reaction = np.asarray(reaction, dtype=float)
    a, b = int(math.ceil(s)), min(len(reaction), int(math.floor(e)))
    lo, hi = int(math.ceil(s + HOOK_SKIP_START)), b - 1
    if hi <= lo:
        rec["why"] = "клип слишком короткий для хука"
        return rec
    i = lo + int(np.argmax(reaction[lo:hi]))
    peak = float(reaction[i])
    start_level = float(reaction[a:min(b, a + 2)].max())
    words = [w for seg in segments if seg["e"] > s and seg["s"] < e for w in seg["words"]]
    if threshold is None:
        threshold = hook_threshold(reaction, cfg)
    rec["start"], rec["end"] = _hook_window(i, s, e, words)
    if rec["start"] is None:
        # у самого яркого места слова идут сплошняком — пробуем другие яркие секунды клипа
        # (короткая фраза целиком или реакция без слов), слово по-прежнему не режем
        for j in sorted(range(lo, hi), key=lambda j: -reaction[j]):
            if j == i or reaction[j] < max(threshold, 0.7 * peak):
                continue
            hs, he = _hook_window(j, s, e, words)
            if hs is not None:
                i, rec["start"], rec["end"] = j, hs, he
                peak = float(reaction[j])
                break
    if rec["start"] is None and voice:
        rec["start"], rec["end"] = _voice_hook_window(i, s, e, voice)   # настоящие паузы в голосе
    if rec["start"] is None:
        rec["why"] = "нет места для хука без разреза слова"
    elif peak < threshold:
        rec["why"] = "нет яркой реакции в клипе"
    elif start_level >= 0.7 * peak:
        rec["why"] = "клип и так начинается с сильного момента"
    else:
        rec["auto"] = True
        rec["why"] = f"{_what_reaction(i, parts)} на {int(i - s)}-й секунде клипа"
    return rec


HOOK_PROMPT = """Ты монтажёр коротких вертикальных видео. Есть клип из стрима и кусок из его середины, который хотим показать в самом начале как тизер на 1–2 секунды, а потом клип с начала.
Раскроет ли этот тизер развязку шутки или главный сюрприз, так что досматривать станет неинтересно?
Ответь ТОЛЬКО JSON: {"spoils": true или false, "reason": "коротко почему"}

Клип:
<<CLIP>>

Тизер:
<<HOOK>>
"""


def llm_hook_spoils(clip_text, hook_text, mode):
    """(True/False, почему) — раскроет ли тизер развязку; (None, "") — модель не ответила."""
    if mode == "none" or not hook_text.strip():
        return None, ""
    prompt = HOOK_PROMPT.replace("<<CLIP>>", clip_text).replace("<<HOOK>>", hook_text)
    try:
        text = _ask_llm(prompt, mode, max_tokens=300)
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {}
        if isinstance(data.get("spoils"), bool):
            return data["spoils"], str(data.get("reason", ""))[:200]
    except Exception as e:
        warn_once(f"   ⚠️  модель не ответила про хук ({e})")
    return None, ""


def text_between(segments, s, e):
    return " ".join(w["w"] for seg in segments if seg["e"] > s and seg["s"] < e
                    for w in seg["words"] if s - 0.05 <= w["s"] and w["e"] <= e + 0.05)


def hook_window_at(segments, s, e, t):
    """«Выбрать другой момент»: хук 1–2 с вокруг места t клипа [s, e], без разреза слов."""
    words = [w for seg in segments if seg["e"] > s and seg["s"] < e for w in seg["words"]]
    return _hook_window(min(max(t, s), e) + 0.5, s, e, words)


MIN_PIECE = 0.2        # кусок клипа короче этого между вырезками не оставляем


def keep_pieces(s, e, cuts):
    """Что остаётся от клипа [s, e] после вырезок cuts ([начало, конец] во времени записи):
    [(начало, конец)] во времени записи, по порядку."""
    out, t = [], float(s)
    for a, b in sorted((float(a), float(b)) for a, b in cuts or ()):
        a, b = max(a, s), min(b, e)
        if b <= a:
            continue
        if a - t >= MIN_PIECE:
            out.append((t, a))
        t = max(t, b)
    if e - t >= MIN_PIECE:
        out.append((t, float(e)))
    return [(round(a, 3), round(b, 3)) for a, b in out]


def clip_timeline(s, e, cuts=None, hook=None):
    """Куски готового клипа: [(начало в записи, конец в записи, начало в клипе, часть)].
    Часть 0 — хук, дальше 1, 2, … — куски клипа между вырезками."""
    tl, o = [], 0.0
    if hook:
        tl.append((float(hook[0]), float(hook[1]), 0.0, 0))
        o = float(hook[1]) - float(hook[0])
    for i, (a, b) in enumerate(keep_pieces(s, e, cuts), 1):
        tl.append((a, b, round(o, 3), i))
        o += b - a
    return tl


def timeline_len(tl):
    return sum(b - a for a, b, _, _ in tl)


def rec_to_out(t, tl, hook=False):
    """Место t записи → время в готовом клипе (None — вырезано). hook=True — искать в хуке."""
    for a, b, o, part in tl:
        if (part == 0) == hook and a - 1e-6 <= t <= b + 1e-6:
            return o + (t - a)
    return None


def out_to_rec(t, tl):
    """Время t в готовом клипе → место в записи."""
    for a, b, o, _ in tl:
        if t < o + (b - a) + 1e-6:
            return a + max(0.0, t - o)
    a, b, o, _ = tl[-1]
    return b


def rendered_timeline(clip):
    """Куски готового файла клипа (как он собран сейчас) — для перевода времени просмотра в запись."""
    if clip.get("timeline"):
        return [tuple(x) for x in clip["timeline"]]
    h = clip.get("hook") or {}
    hook = (h["start"], h["end"]) if h.get("on") and h.get("start") is not None else None
    return clip_timeline(clip["start"], clip["end"], None, hook)


def clip_cuts(rec, cfg=None):
    return [list(map(float, x)) for x in ((cfg or {}).get("cuts") or
                                          (rec.get("overrides") or {}).get("cuts") or [])]


def in_cuts(a, b, cuts):
    return any(x < b and y > a for x, y in cuts)


def hook_span(rec, cfg):
    """(начало, конец) хука для рендера или None. Личная настройка клипа важнее общей
    галочки; хук вне клипа не ставится никогда (правило 5)."""
    h = rec.get("hook") or {}
    mode = tri(rec.get("overrides", {}).get("hook"), "on") or tri(cfg.get("hook"))
    want = mode == "on" or (mode == "auto" and bool(h.get("auto")))
    hs, he = h.get("start"), h.get("end")
    if want and hs is not None and rec["start"] <= hs < he <= rec["end"] and \
            not in_cuts(hs, he, clip_cuts(rec, cfg)):         # хук — только из оставшихся кусков
        return hs, he
    return None


PAUSE = 0.3            # пауза между словами, в которой можно резать клип, сек
_SENTENCE_END = re.compile(r"[.!?…]$")


def all_words(segments):
    return sorted((w for seg in segments for w in seg["words"]), key=lambda w: w["s"])


def _stretch(w):
    """Насколько слово длиннее, чем нужно на его буквы. В сплошной речи Whisper ставит
    слова встык и прячет паузу внутрь слова — «команд» у него длится 3 секунды."""
    letters = len(re.sub(r"[^\w]", "", w["w"]))
    return (w["e"] - w["s"]) - (0.08 * letters + 0.15)


# после этих слов фраза явно продолжается — заканчивать на них клип нельзя
_CONTINUES = set("""и а но или что чтобы это эта этот эти на в во с со к ко по за из у о об от до
для при без не ни ну как если когда потому типа короче то же бы ли чё че там тут где который
которая которые его её ее их мой моя твой твоя же ведь даже уже ещё еще очень""".split())


# эти слова приклеены к предыдущему («стоит ли», «кто же») — резать перед ними нельзя
_ATTACHED = {"ли", "же", "ж", "бы", "б", "то", "таки"}


def _cut_score(pause, last_word, next_word, dist, preferred_side):
    """Чем выше, тем лучше место для разреза: длинная пауза, конец предложения,
    не на союзе или предлоге, ближе к задуманной границе."""
    sc = min(pause, 1.0)                 # пауза дольше секунды — уже чистая пауза
    if last_word is not None:
        if _SENTENCE_END.search(last_word["w"]):
            sc += 1.0
        if clean_word(last_word["w"]) in _CONTINUES:
            sc -= 1.5
    if next_word is not None and clean_word(next_word["w"]).lstrip("-") in _ATTACHED:
        sc -= 1.5
    return sc - 0.1 * abs(dist) + (0.15 if preferred_side else 0.0)


def _end_points(words):
    """Где можно закончить клип: после слова, за которым пауза (в том числе спрятанная
    внутрь растянутого слова) или конец предложения. [(время, пауза, последнее слово)]."""
    pts = []
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["s"] - w["e"]) if nxt else math.inf
        # пауза, спрятанная в растянутом слове, — менее надёжна, чем настоящая
        pause = gap if gap >= PAUSE else max(gap, 0.6 * _stretch(w))
        if pause >= PAUSE or _SENTENCE_END.search(w["w"]):
            # после конца слова с запасом, чтобы не съесть последний звук, но не на следующем слове
            pts.append((pad_after(w, nxt), pause, w, nxt))
    return pts


def _start_points(words):
    """Где можно начать клип: перед словом, до которого пауза или конец предложения.
    [(время, пауза, слово перед разрезом)]."""
    pts = []
    for i, w in enumerate(words):
        prev = words[i - 1] if i else None
        gap = (w["s"] - prev["e"]) if prev else math.inf
        pause = gap if (not prev or gap >= PAUSE) else max(gap, 0.6 * _stretch(prev))
        if pause >= PAUSE or (prev and _SENTENCE_END.search(prev["w"])):
            pts.append((pad_before(w, prev), pause, prev, w))
    return pts


def _not_inside_word(t, words, lo, hi):
    """Если t попало внутрь слова — сдвиг к краю слова в пределах [lo, hi]."""
    w = next((w for w in words if w["s"] < t < w["e"]), None)
    if not w:
        return t
    for edge in sorted((w["s"], w["e"]), key=lambda x: abs(x - t)):
        if lo <= edge <= hi:
            return edge
    return t


def snap_end(t, words, lo, hi, after=10.0, before=6.0):
    """Конец клипа около t, в пределах [lo, hi]: в паузе после законченной фразы, не на
    полуслове и не на «и/а/но». Лучше чуть позже t (дать договорить), чем раньше."""
    pts = [x for x in _end_points(words) if lo <= x[0] <= hi and t - before <= x[0] <= t + after]
    if pts:
        return max(pts, key=lambda x: _cut_score(x[1], x[2], x[3], x[0] - t, x[0] >= t))[0]
    # пауз нет — режем там, где промежуток между словами самый большой
    near = [(w["e"], (words[i + 1]["s"] - w["e"]) if i + 1 < len(words) else math.inf)
            for i, w in enumerate(words) if lo <= w["e"] <= hi and -before <= w["e"] - t <= after]
    if near:
        return max(near, key=lambda x: x[1])[0]
    return _not_inside_word(t, words, lo, hi)


def snap_start(t, words, lo, hi, before=6.0, after=5.0):
    """Начало клипа около t, в пределах [lo, hi]: в паузе перед новой фразой, не на
    полуслове и не сразу после «и/а/но». Лучше чуть раньше t (захватить начало фразы)."""
    pts = [x for x in _start_points(words) if lo <= x[0] <= hi and t - before <= x[0] <= t + after]
    if pts:
        return max(pts, key=lambda x: _cut_score(x[1], x[2], x[3], x[0] - t, x[0] <= t))[0]
    near = [(w["s"], (w["s"] - words[i - 1]["e"]) if i else math.inf)
            for i, w in enumerate(words) if lo <= w["s"] <= hi and -before <= w["s"] - t <= after]
    if near:
        return max(near, key=lambda x: x[1])[0]
    return _not_inside_word(t, words, lo, hi)


def mark_peaks(smooth, marks, window=None):
    """Для каждой метки — самая яркая секунда за window секунд до неё (метку ставят после
    смешного момента) и пара секунд после. [(секунда пика, метка)]."""
    import numpy as np
    window = CONFIG["mark_window"] if window is None else window
    n = len(smooth)
    out = []
    for m in marks:
        a, b = max(0, int(m["t"] - window)), min(n, int(m["t"]) + 3)
        if b > a:
            out.append((a + int(np.argmax(smooth[a:b])), m))
    return out


def split_clips(found, cfg=None):
    """Отобранные клипы и кандидаты. Метки из OBS — всегда в клипах.
    «Число»: первые clips по оценке. «Авто»: все с оценкой не ниже порога, не больше потолка."""
    cfg = cfg or CONFIG
    found = sorted(found, key=lambda c: -c["score"])
    marked = [c for c in found if c.get("marks") and not c.get("short")]
    rest = [c for c in found if not c.get("marks") and not c.get("short")]
    shorts = [c for c in found if c.get("short")]
    if cfg.get("clips_mode") == "auto":
        room = max(0, int(cfg["auto_max"]) - len(marked))
        good = [c for c in rest if c["score"] >= float(cfg["auto_min_score"])][:room]
    else:
        good = rest[:max(0, int(cfg["clips"]) - len(marked))]
    ids = {id(c) for c in good}
    clips = sorted(marked + good, key=lambda c: -c["score"])
    cands = ([c for c in rest if id(c) not in ids] + shorts)[:int(cfg.get("max_candidates", 20))]
    return clips, cands


def candidate_record(c, num, segments):
    """Кандидат: момент без собранного видео — можно собрать потом кнопкой."""
    return {"id": f"k{num:02d}", "start": c["s"], "end": c["e"], "peak": c["peak"],
            "score": round(c["score"], 2), "score_parts": c.get("parts", {}),
            "title": c["title"], "reason": c.get("reason", ""), "zooms": c["zooms"],
            "marks": c.get("marks", []),
            "text": " ".join(censor_word(w) for w in text_between(segments, c["s"], c["e"]).split())[:160],
            "created": now_iso()}


def set_candidate_deleted(path, ref, deleted=True):
    """«Удалить кандидата» (и «Вернуть»): кандидат не пропадает, а уходит в «Удалённые»."""
    proj = load_project(path)
    k = next((k for k in proj.get("candidates") or [] if k["id"] == ref), None)
    if not k:
        raise AutoClipError(f"❌ Нет кандидата «{ref}».")
    k["deleted"] = bool(deleted)
    if deleted:
        k["deleted_date"] = now_iso()
    save_project(proj)
    return k


def build_candidate(path, ref, progress=None, cancel=None):
    """«Собрать»: кандидат становится обычным клипом."""
    proj = load_project(path)
    cand = next((k for k in proj.get("candidates", []) if k["id"] == ref), None)
    if not cand:
        raise AutoClipError(f"❌ Нет кандидата «{ref}».")
    c = {"s": cand["start"], "e": cand["end"], "peak": cand["peak"], "score": cand["score"],
         "zooms": cand["zooms"], "parts": cand.get("score_parts", {}), "title": cand["title"],
         "reason": cand.get("reason", ""), "marks": cand.get("marks", [])}
    rec = add_clip(path, c, "candidate", progress, cancel)
    proj = load_project(path)
    proj["candidates"] = [k for k in proj.get("candidates", []) if k["id"] != ref]
    save_project(proj)
    return rec


def silence_share(s, e, words):
    """Доля клипа в паузах без речи длиннее 1 с."""
    ws = [w for w in words if w["e"] > s and w["s"] < e]
    if not ws or e <= s:
        return 1.0
    edges = [s] + [x for w in ws for x in (w["s"], w["e"])] + [e]
    gaps = [edges[i + 1] - edges[i] for i in range(0, len(edges) - 1, 2)]
    return sum(g for g in gaps if g > 1.0) / (e - s)


def guard_edges(s, e, words, voice=None, max_end=None):
    """Края клипа не режут слово (у Whisper слова бывают растянуты) и голос, который Silero
    слышит, а Whisper не записал словами: конец — за голос, начало — перед ним."""
    allw = sorted(words, key=lambda w: w["s"])
    nxt_of = {id(w): (allw[i + 1] if i + 1 < len(allw) else None) for i, w in enumerate(allw)}
    prv_of = {id(w): (allw[i - 1] if i else None) for i, w in enumerate(allw)}
    for a, b in voice or ():
        if a + 0.05 < e < b - 0.05 and (max_end is None or b <= max_end):
            nxt = next((w for w in allw if w["s"] >= e), None)
            e = min(b + 0.25, nxt["s"] - 0.05) if nxt and nxt["s"] > b else b + 0.25
        if a + 0.05 < s < b - 0.05 and a >= s - 5:
            s = max(0.0, a - PAD_BEFORE)
    w = next((w for w in allw if w["s"] + 0.01 < e < w["e"] - 0.01), None)
    if w is not None:
        e = pad_after(w, nxt_of.get(id(w)))
    w = next((w for w in allw if w["s"] + 0.01 < s < w["e"] - 0.01), None)
    if w is not None:
        s = pad_before(w, prv_of.get(id(w)))
    return round(s, 2), round(e, 2)


def tighten_clip(peak, s, e, words, parts=None, cfg=None, voice=None):
    """Границы клипа по речи (поверх того, что предложила модель и shape_clip):
    конец — до tail_after после пика (или до конца непрерывной фразы, не дальше tail_max);
    начало — не раньше lead_before до первой речи (кроме громкой реакции до неё); пауза без
    речи длиннее max_silence — обрезаем по неё со стороны без пика. Слова не режем."""
    cfg = cfg or CONFIG
    ws = sorted((w for w in words if w["e"] > s and w["s"] < e), key=lambda w: w["s"])
    if not ws:
        return s, min(e, peak + cfg["tail_after"])
    allw = sorted(words, key=lambda w: w["s"])
    nxt_of = {id(w): (allw[i + 1] if i + 1 < len(allw) else None) for i, w in enumerate(allw)}
    prv_of = {id(w): (allw[i - 1] if i else None) for i, w in enumerate(allw)}
    # пауза без речи длиннее max_silence — отрезаем ту сторону, где нет пика
    for a, b in zip(ws, ws[1:]):
        if b["s"] - a["e"] > cfg["max_silence"]:
            if b["s"] <= peak:
                s = max(s, pad_before(b, a))
            elif a["e"] >= peak:
                e = min(e, pad_after(a, b))
                break
    ws = [w for w in ws if w["s"] >= s - 0.01 and w["e"] <= e + 0.01] or ws
    # конец: до tail_after после пика; договаривает без пауз — до конца фразы, но не дальше tail_max
    limit = peak + cfg["tail_after"]
    if e > limit:
        before = [w for w in ws if w["s"] < limit]
        if before:
            last = before[-1]
            k = ws.index(last)
            while k + 1 < len(ws) and ws[k + 1]["s"] - ws[k]["e"] <= cfg["talk_gap"] \
                    and ws[k + 1]["e"] <= peak + cfg["tail_max"]:
                k += 1
            e = min(e, pad_after(ws[k], nxt_of.get(id(ws[k]))))
        else:
            e = min(e, limit)
    # начало: не раньше lead_before до первой речи, кроме громкой реакции до неё
    first = next((w for w in ws if w["e"] > s), None)
    if first is not None and first["s"] - s > cfg["lead_before"]:
        start = first["s"] - cfg["lead_before"]
        loud = None
        if parts:
            react = [i for i in range(int(math.ceil(s)), int(first["s"]))
                     if parts.get("смех") is not None and i < len(parts["смех"])
                     and (parts["смех"][i] > 0.3 or parts["восклицания"][i] > 0.3)]
            loud = react[0] if react else None
        start = min(start, loud - 0.3) if loud is not None else start
        s = max(s, start, prv_of.get(id(first))["e"] if prv_of.get(id(first)) else 0.0)
    # паузы покороче (soft_silence) со стороны без пика — тоже долой, если клип не станет
    # короче min_tight: тишина в клипе зрителю не нужна
    ws = [w for w in ws if w["e"] > s and w["s"] < e]
    for a, b in zip(ws, ws[1:]):
        if b["s"] - a["e"] > cfg["soft_silence"] and b["s"] <= peak:
            ns = pad_before(b, a)
            if e - ns >= cfg["min_tight"]:
                s = max(s, ns)
    for a, b in reversed(list(zip(ws, ws[1:]))):
        if b["s"] - a["e"] > cfg["soft_silence"] and a["e"] >= peak:
            ne = pad_after(a, b)
            if ne - s >= cfg["min_tight"]:
                e = min(e, ne)
    # край попал внутрь голоса (Silero слышит речь, которую Whisper не записал словами) —
    # конец сдвигаем за голос, начало — перед ним
    for a, b in voice or ():
        if a + 0.05 < e < b - 0.05 and b <= peak + cfg["tail_max"]:
            nxt = next((w for w in allw if w["s"] >= e), None)
            e = min(b + 0.25, nxt["s"] - 0.05) if nxt and nxt["s"] > b else b + 0.25
        if a + 0.05 < s < b - 0.05 and a >= s - cfg["lead_before"] - 3:
            s = max(0.0, a - PAD_BEFORE)
    # край попал внутрь слова (у Whisper слова бывают растянуты) — слово не режем никогда
    w = next((w for w in allw if w["s"] + 0.01 < e < w["e"] - 0.01), None)
    if w is not None:
        e = pad_after(w, nxt_of.get(id(w)))
    w = next((w for w in allw if w["s"] + 0.01 < s < w["e"] - 0.01), None)
    if w is not None:
        s = pad_before(w, prv_of.get(id(w)))
    return round(s, 2), round(e, 2)


def shape_clip(peak, s, e, words, dur):
    """Длина 15–55 с вокруг пика и границы в паузах между фразами (не на полуслове)."""
    min_len, max_len = CONFIG["min_len"], CONFIG["max_len"]
    s, e = max(0.0, s), min(dur, e)
    if e - s > max_len:                    # слишком длинно — центрируем на пике
        s = max(0.0, min(peak - max_len * 0.65, e - max_len))
        e = s + max_len
    if e - s < min_len:
        extra = min_len - (e - s)
        s = max(0.0, s - extra * 0.6)
        e = min(dur, s + min_len)
    # границы — в паузах между фразами: не начинать с середины и дать договорить
    s = snap_start(s, words, lo=max(0.0, e - max_len), hi=max(0.0, min(peak - 1, e - min_len)))
    e = snap_end(e, words, lo=min(dur, max(peak + 1, s + min_len * 0.8)),
                 hi=min(dur, s + max_len))
    return s, e


def zoom_points(s, e, peak, loud_z):
    """Точки зума: самые громкие пики внутри клипа."""
    zooms = []
    a, b = int(s), min(len(loud_z), int(e))
    cand = sorted(range(a, b), key=lambda i: -loud_z[i])
    for i in cand:
        if len(zooms) >= CONFIG["max_zooms"] or loud_z[i] < 2.0:
            break
        if i - s < 1.0 or e - i < 2.0:
            continue
        if all(abs(i - z) >= 5 for z in zooms):
            zooms.append(float(i))
    if not zooms and s + 1 < peak < e - 2:
        zooms = [peak]
    return zooms


def moment_title(title, segments, s, e, peak):
    """Название: от модели или первые слова клипа; мат скрыт."""
    if not title:
        first = [w["w"] for seg in segments if seg["e"] > s and seg["s"] < e
                 for w in seg["words"] if s <= w["s"] < e][:6]
        title = " ".join(first) or f"момент {fmt_time(peak)}"
    # без мата в названии файла и отчёте
    return " ".join(censor_word(w) for w in title.split())


def _stems(text):
    """Основы значимых слов (первые 4 буквы слов длиннее 3 букв) — для сравнения текста."""
    return {norm_text(w)[:4] for w in re.findall(r"\w+", str(text)) if len(w) > 3}


def title_fits(title, clip_text):
    """Название — про этот клип: хоть одно значимое слово названия звучит в клипе."""
    t = _stems(title)
    return not t or bool(t & _stems(clip_text))


START_SILENT = 30.0   # клип без единого слова в первые столько секунд записи не берём


def pick_clips(smooth, loud_z, segments, moments, dur, parts=None, taken=(), marks=(),
               limit=None, voice=None):
    """taken — интервалы (начало, конец) уже существующих клипов: рядом с ними не берём.
    marks — метки из OBS: их моменты идут первыми, сверх обычного числа клипов, если надо.
    limit — сколько моментов искать (по умолчанию CONFIG["clips"])."""
    import numpy as np
    order = np.argsort(-smooth)
    clips = []
    busy = [{"s": a, "e": b} for a, b in taken]
    words = all_words(segments)
    min_len = CONFIG["min_len"]
    marked = mark_peaks(smooth, marks) if marks else []
    limit = max(CONFIG["clips"] if limit is None else limit, len(marked))
    candidates = marked + [(int(p), None) for p in order]
    for peak, mark in candidates:
        if len(clips) >= limit:
            break
        if mark is None and smooth[peak] <= 0.5:
            break
        peak = float(peak)
        if mark is not None:
            # вторая метка про тот же момент — просто добавляем её к клипу
            host = next((c for c in clips if c["s"] <= peak <= c["e"]), None)
            if host:
                host["marks"].append(mark["t"])
                continue
        if any(c["s"] - CONFIG["min_gap"] < peak < c["e"] + CONFIG["min_gap"]
               for c in clips + busy):
            continue

        m = next((m for m in moments if m["s"] - 3 <= peak <= m["e"] + 3), None)
        if m:
            s, e = m["s"], m["e"]
            title, reason = m["title"], m["reason"]
        else:
            s, e = peak - CONFIG["pre"], peak + CONFIG["post"]
            title, reason = "", ""
        s, e = shape_clip(peak, s, e, words, dur)
        if e - s < min_len * 0.8:
            continue
        # границы — как в 1.1 (окно вокруг пика, края в паузах между фразами); обрезка по
        # первой/последней речи и мягким паузам из 3.1 убрана: она срезала драку, смерть, вопрос
        s, e = guard_edges(s, e, words, voice, max_end=min(dur, s + CONFIG["max_len"] + 2))
        short = False
        if any(not (e <= c["s"] or s >= c["e"]) for c in clips + busy):
            continue
        if mark is None and s < START_SILENT and not any(
                s <= w["s"] < e for w in words):
            continue                     # без речи в первых секундах — шум начала записи, не момент

        zooms = zoom_points(s, e, peak, loud_z)
        if title and not title_fits(title, text_between(segments, s, e)):
            title = ""                   # модель назвала по соседнему куску — берём слова клипа
        title = moment_title(title, segments, s, e, peak)
        pk = int(peak)
        clip_parts = {k: round(float(v[pk]), 2) for k, v in (parts or {}).items()}
        score = float(smooth[pk])
        if mark is not None:                   # метка из OBS — большой приоритет
            clip_parts["метка"] = CONFIG["mark_bonus"]
            score += CONFIG["mark_bonus"]
        clips.append({"s": round(s, 2), "e": round(e, 2), "peak": peak,
                      "score": score, "zooms": sorted(zooms), "parts": clip_parts,
                      "title": title, "reason": reason, "short": short,
                      "marks": [mark["t"]] if mark is not None else []})
    return sorted(clips, key=lambda c: -c["score"])


# ---------------- звуки для мата ----------------

def user_dir():
    """%APPDATA%\\AutoClip — настройки, свои звуки, история; обновление программы их не трогает."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "AutoClip")
    os.makedirs(d, exist_ok=True)
    return d


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR = os.path.join(user_dir(), "звуки")
SOUND_EXT = (".wav", ".mp3", ".ogg", ".m4a", ".flac", ".aac")

# встроенные звуки генерируются через ffmpeg, без чужих файлов
BUILTIN_SOUNDS = {
    "перелистывание": (
        "anoisesrc=color=white:sample_rate=48000:duration=0.32:amplitude=0.9,"
        "highpass=f=1800,lowpass=f=7500,"
        "tremolo=f=35:d=0.55,"
        "afade=t=in:d=0.03,afade=t=out:st=0.09:d=0.23,volume=1.6"),
    "буп": (
        "aevalsrc='0.55*sin(2*PI*(520*t-650*t*t))*exp(-7*t)':s=48000:d=0.30,"
        "afade=t=in:d=0.005"),
    "свист": (
        "aevalsrc='0.35*sin(2*PI*(900*t+2600*t*t))*(1-t/0.35)':s=48000:d=0.35,"
        "afade=t=in:d=0.01,afade=t=out:st=0.25:d=0.1"),
    "бип": "sine=frequency=1000:sample_rate=48000:duration=0.5,volume=2.8",
}


def prepare_sounds():
    """Создаёт папку «звуки» со встроенными звуками (один раз)."""
    migrate_user_data()
    os.makedirs(SOUNDS_DIR, exist_ok=True)
    for name, spec in BUILTIN_SOUNDS.items():
        path = os.path.join(SOUNDS_DIR, name + ".wav")
        if not os.path.exists(path):
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", spec,
                 "-ac", "2", "-ar", "48000", path])


def list_sounds():
    names = list(BUILTIN_SOUNDS) + ["тишина"]
    if os.path.isdir(SOUNDS_DIR):
        for f in sorted(os.listdir(SOUNDS_DIR)):
            stem, ext = os.path.splitext(f)
            if ext.lower() in SOUND_EXT and stem not in BUILTIN_SOUNDS:
                names.append(f)
    return names


RANDOM_SOUND = "Случайный"     # на каждый мат — свой звук из выбранных (bleep_pool)


def sound_pool(cfg):
    """Звуки для «Случайного»: выбранные галочками, а если не выбрано ничего — все, кроме тишины."""
    have = [n for n in list_sounds() if n != "тишина"]
    pool = [n for n in (cfg.get("bleep_pool") or []) if n in have]
    return pool or have


def bleep_sequence(cfg, n, seed):
    """Какой звук на каком мате: n имён, один и тот же не два раза подряд (если звуков больше
    одного). seed фиксирован у клипа — пересборка даёт те же звуки."""
    import random
    if cfg.get("bleep_sound") != RANDOM_SOUND:
        return [cfg["bleep_sound"]] * n
    pool = sound_pool(cfg)
    rnd = random.Random(int(seed))
    out = []
    for _ in range(n):
        choices = [x for x in pool if not out or x != out[-1]] or pool
        out.append(rnd.choice(choices))
    return out


def sound_path(name):
    if name == "тишина":
        return None
    if name == RANDOM_SOUND:                       # прослушать «Случайный» — любой из выбранных
        import random
        return sound_path(random.choice(sound_pool(CONFIG)))
    if os.path.isfile(name):
        return name
    for cand in (os.path.join(SOUNDS_DIR, name), os.path.join(SOUNDS_DIR, name + ".wav")):
        if os.path.isfile(cand):
            return cand
    log(f"⚠️  Звук «{name}» не найден, ставлю «перелистывание».")
    prepare_sounds()
    return os.path.join(SOUNDS_DIR, "перелистывание.wav")


def sound_duration(path):
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path])
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.5


# ---------------- 6. субтитры ----------------

def _ass_time(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000:d}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _ass_escape(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")")


def _censor(w):
    if not is_profane(w):
        return w
    letters = re.sub(r"[^\w]", "", w)
    return (letters[:1] or "*") + "*" * max(2, len(letters) - 1)


# частичная цензура: какие буквы корня скрыть (группа x), остальное слово угадывается
_MASKS = [
    re.compile(r"^дол(?P<x>б[ао])е"),                 # долбоёб → дол**ёб
    re.compile(r"ху(?P<x>[йеяи])"),                   # хуйня → ху*ня, нахуй → наху*
    re.compile(r"^" + _PFX + r"ху(?P<x>ю)"),          # нахую → наху*
    re.compile(r"пи(?P<x>з)д"),                       # пиздец → пи*дец
    re.compile(r"^" + _PFX + r"е(?P<x>б)"),           # ебать → е*ать, заебал → зае*ал
    re.compile(r"^(?:вы|рас|раз)?(?P<x>б)ля"),        # блять → *лять, выблядок → вы*лядок
    re.compile(r"^с(?P<x>у)[кч]"),                    # сука → с*ка, сучка → с*чка
    re.compile(r"^(?:на|по)?х(?P<x>е)р"),             # хер → х*р
    re.compile(r"^м(?P<x>у)д"),                       # мудак → м*дак
    re.compile(r"^п(?P<x>и)д"),                       # пидор → п*дор
    re.compile(r"зал(?P<x>у)п"),                      # залупа → зал*па
    re.compile(r"^г(?P<x>[ао])ндон"),                 # гондон → г*ндон
    re.compile(r"шл(?P<x>ю)х"),                       # шлюха → шл*ха
    re.compile(r"^м(?P<x>а)нд"),                      # манда → м*нда
]


def mask_span(word):
    """Какие буквы мата скрыть при частичной цензуре: (начало, конец, всего букв) по буквам
    слова, или None — если это не мат или корень не нашёлся."""
    if not is_profane(word):
        return None
    letters = re.sub(r"[^\w*]", "", word)
    low = letters.lower().replace("ё", "е")
    for rx in _MASKS:
        m = rx.search(low)
        if m:
            return m.start("x"), m.end("x"), len(letters)
    return None


def censor_word(w, mode=None):
    """Мат в тексте: частично («е*ать», «*лять») или полностью («б****»). Остальное — как есть."""
    mode = mode or CONFIG.get("censor", "partial")
    if not is_profane(w) or "*" in w:
        return w
    span = mask_span(w) if mode == "partial" else None
    if span is None:
        return _censor(w)
    a, b, _ = span
    letters = [ch for ch in w if re.match(r"[\w*]", ch)]
    idx = [i for i, ch in enumerate(w) if re.match(r"[\w*]", ch)]
    out = list(w)
    for k in range(a, b):
        out[idx[k]] = "*"
    return "".join(out) if letters else w


def _display_word(w, cfg=None):
    cfg = cfg or CONFIG
    w = w.strip()
    w = re.sub(r"^[\"«(]+|[\"»),.;:]+$", "", w)
    w = censor_word(w, cfg.get("censor", "partial"))
    if cfg["sub_uppercase"]:
        w = w.upper()
    return _ass_escape(w)


# где субтитры: доля высоты кадра для центра строки
SUB_POSITIONS = {"Сверху": 0.18, "Выше середины": 0.38, "Середина": 0.50,
                 "Ниже середины": 0.60, "Снизу": 0.85}
# поля кадра, которые закрывают кнопки, ник и подпись площадок — общий осторожный вариант
# для TikTok, YouTube Shorts и Instagram Reels (доли кадра 1080×1920)
SAFE_ZONE = {"top": 0.15, "bottom": 0.30, "left": 0.06, "right": 0.18}
CHAR_W = 0.62                 # ширина заглавной буквы Arial Black в долях размера шрифта (с запасом)


def sub_position_name(y):
    """Ближайшее название позиции для доли высоты."""
    return min(SUB_POSITIONS, key=lambda k: abs(SUB_POSITIONS[k] - y))


NICK_CORNERS = {"Сверху слева": "tl", "Сверху справа": "tr", "Снизу слева": "bl",
                "Снизу справа": "br"}
NICK_ALIGN = {"tl": 7, "tr": 9, "bl": 1, "br": 3}     # выравнивание ASS: точка — угол строки


def frame_area(w, h, cfg):
    """Где можно рисовать текст: внутри сейф-зоны соцсетей или с отступом от краёв."""
    if cfg.get("safe_zone"):
        return (SAFE_ZONE["left"] * w, SAFE_ZONE["top"] * h,
                w - SAFE_ZONE["right"] * w, h - SAFE_ZONE["bottom"] * h)
    return 40.0, 40.0, w - 40.0, h - 40.0


def nick_layout(w, h, cfg=None):
    """Ник в углу: точка привязки, выравнивание, размер и занятая полоса по высоте."""
    cfg = cfg or CONFIG
    left, top, right, bottom = frame_area(w, h, cfg)
    corner = NICK_CORNERS.get(cfg.get("nick_corner"), "tl")
    fs = int(cfg.get("nick_size", 40) * w / 1080)
    pad = 0.015 * w                                  # небольшой отступ от края области
    x = left + pad if corner[1] == "l" else right - pad
    y = top + pad if corner[0] == "t" else bottom - pad
    tall = 1.35 * fs                                 # строка с обводкой и тенью
    y0, y1 = (y, y + tall) if corner[0] == "t" else (y - tall, y)
    return {"x": int(x), "y": int(y), "an": NICK_ALIGN[corner], "fs": fs, "corner": corner,
            "y0": y0, "y1": y1}


def build_nick_ass(w, h, path, cfg, dur):
    """Ник отдельным слоем — виден, даже если субтитры выключены."""
    nk = nick_layout(w, h, cfg)
    alpha = max(0, min(255, int(round(255 * (1 - cfg.get("nick_opacity", 70) / 100)))))
    a = f"{alpha:02X}"
    text = _ass_escape(str(cfg.get("nick_text", "")).strip())
    outline = max(2, int(nk["fs"] * 0.08))
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Nick,Arial,{nk['fs']},&H{a}FFFFFF,&H{a}FFFFFF,&H{a}000000,&H{a}000000,-1,0,0,0,100,100,1,0,1,{outline},1,{nk['an']},0,0,0,204

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 1,{_ass_time(0)},{_ass_time(dur + 1)},Nick,,0,0,0,,{{\\an{nk['an']}\\pos({nk['x']},{nk['y']})}}{text}
""")


def subs_layout(w, h, cfg=None):
    """Куда и каким размером ставить субтитры: центр (x, y), размер шрифта, сколько букв
    влезает в строку и границы области. С сейф-зоной — внутри неё."""
    cfg = cfg or CONFIG
    fs = int(cfg["sub_size"] * w / 1080)
    left, top, right, bottom = frame_area(w, h, cfg)
    half = 0.6 * fs                                  # половина строки с обводкой и тенью
    y = min(max(h * cfg["sub_y"], top + half), bottom - half)
    if cfg.get("nick") and str(cfg.get("nick_text", "")).strip():
        # ник не должен перекрывать субтитры — отодвигаем строку от него
        nk, gap = nick_layout(w, h, cfg), 0.25 * fs
        if y - half < nk["y1"] + gap and y + half > nk["y0"] - gap:
            y = nk["y1"] + gap + half if nk["corner"][0] == "t" else nk["y0"] - gap - half
            y = min(max(y, top + half), bottom - half)
    # по ширине — куда перетащили (в пределах области); строка не шире, чем влезает вокруг центра
    x = (left + right) / 2
    if cfg.get("sub_x") is not None and right - left > 4 * fs:
        x = min(max(w * float(cfg["sub_x"]), left + 2 * fs), right - 2 * fs)
    room = 2 * min(x - left, right - x)
    max_chars = max(4, min(cfg["sub_max_chars"], int(room / (CHAR_W * fs))))
    return {"x": int(x), "y": int(y), "fs": fs, "max_chars": max_chars,
            "box": (left, top, right, bottom), "room": room}


def ass_color(rgb, alpha=0):
    """«#RRGGBB» → «&HAABBGGRR» для ASS."""
    v = str(rgb or "#FFFFFF").lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", v):
        v = "FFFFFF"
    return f"&H{alpha:02X}{v[4:6]}{v[2:4]}{v[0:2]}".upper()


def build_ass(words, w, h, path, cfg=None):
    """words: [{'s','e','w'}] со временем относительно начала клипа."""
    cfg = cfg or CONFIG
    lay = subs_layout(w, h, cfg)
    fs = lay["fs"]
    outline = max(1, int(round(float(cfg.get("sub_outline", 7)) * w / 1080)))
    text_c, out_c = ass_color(cfg.get("sub_color")), ass_color(cfg.get("sub_outline_color", "#000000"))
    hl = ass_color(cfg.get("sub_hl_color", "#FFE600"))[4:]        # без прозрачности: &HBBGGRR
    base = text_c[4:]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{cfg["sub_font"]},{fs},{text_c},{text_c},{out_c},&H80000000,-1,0,0,0,100,100,0,0,1,{outline},2,5,40,40,0,204

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # группируем слова в короткие фразы
    chunks, cur = [], []
    for i, wd in enumerate(words):
        if cur:
            prev = cur[-1]
            chars = sum(len(x["w"]) + 1 for x in cur) + len(wd["w"])
            max_words = 1 if cfg.get("sub_mode") == "single" else cfg["sub_max_words"]
            if (len(cur) >= max_words or chars > lay["max_chars"]
                    or wd["s"] - prev["e"] > 0.45 or re.search(r"[.!?…]$", prev["w"])
                    or wd.get("part") != prev.get("part")):
                chunks.append(cur)
                cur = []
        cur.append(wd)
    if cur:
        chunks.append(cur)

    x, y = lay["x"], lay["y"]
    room = lay["room"]
    lines = []
    for ci, ch in enumerate(chunks):
        disp = [_display_word(x_["w"], cfg) for x_ in ch]
        if not any(disp):
            continue
        next_start = chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else ch[-1]["e"] + 0.3
        chunk_end = min(ch[-1]["e"] + 0.25, next_start, ch[-1].get("until", math.inf))
        for wi, wd in enumerate(ch):
            st = wd["s"]
            en = ch[wi + 1]["s"] if wi + 1 < len(ch) else chunk_end
            if en <= st:
                continue
            parts = []
            for j, d in enumerate(disp):
                parts.append("{\\c&H%s&}" % hl + d + "{\\c&H%s&}" % base if j == wi else d)
            # одно длинное слово шире области — уменьшаем строку, а не вылезаем за край
            width = CHAR_W * fs * len(" ".join(disp))
            k = min(100, int(100 * room / width)) if width else 100
            if wi == 0:
                pop = "{\\fscx%d\\fscy%d\\t(0,90,\\fscx%d\\fscy%d)}" % (
                    k * 85 // 100, k * 85 // 100, k, k)
            else:
                pop = "{\\fscx%d\\fscy%d}" % (k, k) if k < 100 else ""
            text = "{\\an5\\pos(%d,%d)}" % (x, y) + pop + " ".join(parts)
            lines.append(f"Dialogue: 0,{_ass_time(st)},{_ass_time(en)},Main,,0,0,0,,{text}")

    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(header + "\n".join(lines) + "\n")


# ---------------- свои шрифты и стили субтитров ----------------

FONTS_DIR = os.path.join(user_dir(), "шрифты")
FONT_EXT = (".ttf", ".otf")


def font_family(path):
    """Название семейства из файла шрифта (таблица name), чтобы назвать его в ASS."""
    import struct
    try:
        with open(path, "rb") as f:
            data = f.read()
        num = struct.unpack(">H", data[4:6])[0]
        name_off = None
        for i in range(num):
            tag, _, off, _ = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
            if tag == b"name":
                name_off = off
        if name_off is None:
            return None
        _, count, str_off = struct.unpack(">HHH", data[name_off:name_off + 6])
        found = {}
        for i in range(count):
            pid, eid, lang, nid, ln, off = struct.unpack(
                ">HHHHHH", data[name_off + 6 + 12 * i: name_off + 18 + 12 * i])
            if nid not in (1, 16):
                continue
            raw = data[name_off + str_off + off: name_off + str_off + off + ln]
            text = raw.decode("utf-16-be", "replace") if pid in (0, 3) else raw.decode("latin-1")
            # лучше: типографское семейство (16), английское (0x409), Windows
            rank = (nid == 16, pid == 3 and lang == 0x409, pid == 3)
            if text.strip() and (nid not in found or rank > found[nid][0]):
                found[nid] = (rank, text.strip())
        best = found.get(1) or found.get(16)
        return best[1] if best else None
    except (OSError, struct.error, IndexError):
        return None


def add_font(path):
    """«Свой файл шрифта…»: копия в %APPDATA%\\AutoClip\\шрифты. Возвращает название семейства."""
    if not path.lower().endswith(FONT_EXT):
        raise AutoClipError("❌ Нужен файл шрифта .ttf или .otf.")
    fam = font_family(path)
    if not fam:
        raise AutoClipError("❌ Не получилось прочитать шрифт — файл повреждён или не шрифт.")
    os.makedirs(FONTS_DIR, exist_ok=True)
    dest = os.path.join(FONTS_DIR, os.path.basename(path))
    if os.path.abspath(dest) != os.path.abspath(path):
        if os.path.exists(dest):
            trash(dest)
        shutil.copy2(path, dest)
    return fam


def user_fonts():
    """Свои шрифты: {семейство: файл}."""
    out = {}
    if os.path.isdir(FONTS_DIR):
        for f in sorted(os.listdir(FONTS_DIR)):
            if f.lower().endswith(FONT_EXT):
                fam = font_family(os.path.join(FONTS_DIR, f))
                if fam:
                    out.setdefault(fam, os.path.join(FONTS_DIR, f))
    return out


def ass_filter(ass_name, tmpdir):
    """Фильтр ass для ffmpeg; свои шрифты кладём рядом (fontsdir=fonts), чтобы не возиться
    с двоеточием диска в пути."""
    fonts = user_fonts()
    if not fonts:
        return f"ass={ass_name}"
    fd = os.path.join(tmpdir, "fonts")
    os.makedirs(fd, exist_ok=True)
    for path in fonts.values():
        dest = os.path.join(fd, os.path.basename(path))
        if not os.path.exists(dest):
            shutil.copy2(path, dest)
    return f"ass={ass_name}:fontsdir=fonts"


# стиль = шрифт, режим, размер, цвета, обводка (положение — отдельно)
STYLE_KEYS = ("sub_font", "sub_mode", "sub_size", "sub_color", "sub_hl_color",
              "sub_outline_color", "sub_outline")
STYLES_PATH = os.path.join(user_dir(), "стили.json")
BUILTIN_STYLE = {"name": "Обычный", "sub_font": "Arial Black", "sub_mode": "words",
                 "sub_size": 82, "sub_color": "#FFFFFF", "sub_hl_color": "#FFE600",
                 "sub_outline_color": "#000000", "sub_outline": 7}


def load_styles():
    """Сохранённые стили: встроенный «Обычный» + свои из %APPDATA%\\AutoClip\\стили.json."""
    try:
        with open(STYLES_PATH, encoding="utf-8") as f:
            own = [x for x in json.load(f) if isinstance(x, dict) and x.get("name")]
    except (OSError, ValueError):
        own = []
    out = [dict(BUILTIN_STYLE, builtin=True)]
    for st in own:
        if st["name"] != BUILTIN_STYLE["name"]:
            out.append({k: st.get(k, BUILTIN_STYLE.get(k)) for k in ("name",) + STYLE_KEYS})
    return out


def get_style(name):
    return next((st for st in load_styles() if st["name"] == name), load_styles()[0])


def save_style(name, values):
    """Сохранить (или заменить) свой стиль."""
    name = str(name).strip()
    if not name:
        raise AutoClipError("❌ Дай стилю название.")
    if name == BUILTIN_STYLE["name"]:
        raise AutoClipError("❌ «Обычный» — встроенный стиль, назови свой иначе.")
    own = [st for st in load_styles() if not st.get("builtin") and st["name"] != name]
    own.append(dict({k: values.get(k, BUILTIN_STYLE[k]) for k in STYLE_KEYS}, name=name))
    tmp = STYLES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(own, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STYLES_PATH)


def delete_style(name):
    own = [st for st in load_styles() if not st.get("builtin") and st["name"] != name]
    with open(STYLES_PATH, "w", encoding="utf-8") as f:
        json.dump(own, f, ensure_ascii=False, indent=1)


PREVIEW_WORDS = ["вот", "это", "поворот"]


def render_sub_layer(cfg, w, h, out_png, words=None):
    """Субтитры одной строки на прозрачном фоне — точно так же, как в клипе (тот же libass,
    тот же ASS). Для живого предпросмотра в «Настройках»."""
    need_ffmpeg()
    words = words or PREVIEW_WORDS
    ws = [{"s": 0.1 + i * 0.4, "e": 0.45 + i * 0.4, "w": wd} for i, wd in enumerate(words)]
    cfg = dict(cfg, sub_mode="words", sub_max_words=max(3, len(ws)))
    import numpy as np
    with tempfile.TemporaryDirectory(prefix="autoclip_p_", ignore_cleanup_errors=True) as tmp:
        build_ass(ws, w, h, os.path.join(tmp, "p.ass"), cfg)
        # ass не трогает прозрачность — рисуем на чёрном и на белом и из разницы
        # получаем, где строка и насколько она прозрачна
        layers = []
        for bg in ("black", "white"):
            p = run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                     f"color=c={bg}:s={w}x{h}:d=1:r=10", "-vf",
                     ass_filter("p.ass", tmp) + ",format=rgb24", "-ss", "0.5",
                     "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                    cwd=tmp, binary=True)
            if p.returncode != 0 or len(p.stdout) != w * h * 3:
                raise AutoClipError("❌ Предпросмотр не получился: " +
                                    p.stderr.decode("utf-8", "replace")[-300:])
            layers.append(np.frombuffer(p.stdout, np.uint8).reshape(h, w, 3).astype(np.float32))
    black, white = layers
    alpha = np.clip(1.0 - (white - black).mean(axis=2) / 255.0, 0, 1)
    rgb = np.where(alpha[..., None] > 0.003, black / np.maximum(alpha[..., None], 0.003), 0)
    rgba = np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype(np.uint8)
    _write_png(out_png, rgba)
    return out_png


def _write_png(path, rgba):
    """PNG без сторонних библиотек (zlib есть в Python)."""
    import struct
    import zlib
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 3)) + chunk(b"IEND", b""))


# ---------------- 7. рендер ----------------

_ENCODER = None            # какой кодек сработал: h264_nvenc или libx264
WHISPER_DEVICE = "кэш"     # на чём шла расшифровка: cuda / cpu / кэш

# пресеты экспорта: встроенные + свои из %APPDATA%\AutoClip\пресеты.json
BUILTIN_PRESETS = [
    {"name": "TikTok 1080p60", "w": 1080, "h": 1920, "fps": 60, "kbps": 18000},
]
PRESETS_PATH = os.path.join(user_dir(), "пресеты.json")
# цвет Rec. 709 во всех трёх полях + обычный (не полный) диапазон
COLOR_FLAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
               "-color_range", "tv"]


def check_preset(p):
    """Проверяет и приводит пресет к виду {name, w, h, fps, kbps}."""
    try:
        name = str(p["name"]).strip()
        w, h, fps, kbps = int(p["w"]), int(p["h"]), int(p["fps"]), int(p["kbps"])
    except (KeyError, TypeError, ValueError):
        raise AutoClipError("❌ В пресете должны быть название, ширина, высота, кадры и битрейт.")
    if not name:
        raise AutoClipError("❌ У пресета нет названия.")
    if not (240 <= w <= 4320 and 240 <= h <= 4320) or w % 2 or h % 2:
        raise AutoClipError("❌ Ширина и высота — чётные, от 240 до 4320.")
    if not 24 <= fps <= 120:
        raise AutoClipError("❌ Кадров в секунду — от 24 до 120.")
    if not 1000 <= kbps <= 100000:
        raise AutoClipError("❌ Битрейт — от 1000 до 100000 Кбит/с.")
    return {"name": name, "w": w, "h": h, "fps": fps, "kbps": kbps}


def load_presets():
    """Встроенные пресеты, затем свои. У встроенных builtin=True."""
    out = [dict(p, builtin=True) for p in BUILTIN_PRESETS]
    try:
        with open(PRESETS_PATH, encoding="utf-8") as f:
            user = json.load(f)
    except (OSError, ValueError):
        user = []
    names = {p["name"] for p in out}
    for p in user if isinstance(user, list) else []:
        try:
            p = check_preset(p)
        except AutoClipError:
            continue
        if p["name"] not in names:
            names.add(p["name"])
            out.append(p)
    return out


def save_user_presets(presets):
    """Сохраняет свои пресеты (встроенные пропускаются)."""
    user = [check_preset(p) for p in presets if not p.get("builtin")
            and p["name"] not in {b["name"] for b in BUILTIN_PRESETS}]
    tmp = PRESETS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(user, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PRESETS_PATH)


def get_preset(value):
    """Имя пресета или сам пресет → пресет. Неизвестное имя → первый встроенный."""
    if isinstance(value, dict):
        return check_preset(value)
    for p in load_presets():
        if p["name"] == value:
            return check_preset(p)
    return check_preset(BUILTIN_PRESETS[0])


def _encoders(preset):
    b, buf = f"{preset['kbps']}k", f"{preset['kbps'] * 2}k"
    gop = str(preset["fps"] * 2)              # опорный кадр раз в 2 секунды
    return {
        "h264_nvenc": ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "cbr",
                       "-b:v", b, "-minrate", b, "-maxrate", b, "-bufsize", buf, "-g", gop,
                       "-spatial-aq", "1", "-profile:v", "high"],
        "libx264": ["-c:v", "libx264", "-preset", "slow", "-b:v", b, "-minrate", b,
                    "-maxrate", b, "-bufsize", buf, "-g", gop, "-profile:v", "high"],
    }


def frame_filters(vinfo, preset):
    """Обрезка по центру под пропорции пресета, масштаб (lanczos) и частота кадров."""
    sw, sh = vinfo["w"] - vinfo["w"] % 2, vinfo["h"] - vinfo["h"] % 2
    W, H = preset["w"], preset["h"]
    vf = []
    cw, ch = sw, sh
    if sw * H > sh * W:                       # шире, чем нужно (например, горизонтальная запись)
        cw = int(sh * W / H) // 2 * 2
    elif sh * W > sw * H:                     # выше, чем нужно
        ch = int(sw * H / W) // 2 * 2
    if (cw, ch) != (sw, sh) or (sw, sh) != (vinfo["w"], vinfo["h"]):
        vf.append(f"crop={cw}:{ch}")
    if (cw, ch) != (W, H):
        vf.append(f"scale={W}:{H}:flags=lanczos")
    vf.append("setsar=1")
    if abs(vinfo.get("fps", 0) - preset["fps"]) > 0.01:
        vf.append(f"fps={preset['fps']}")
    return vf


# ---------------- музыка (свои треки) ----------------
# Музыка — только из своих файлов. Скачивания с площадок и стримингов нет и не будет.

MUSIC_EXT = (".mp3", ".wav", ".ogg", ".flac", ".m4a")
MUSIC_DEFAULT = {"volume": -18.0, "duck": True, "fade": 1.0}   # громкость — дБ к голосу
DUCK_DB = 8.0                 # под речью музыка уходит ещё на столько дБ
_loudness_cache = {}


def list_music(folder, query=""):
    """Треки из папки «Музыка» (и подпапок), с поиском по имени без учёта регистра."""
    out = []
    if folder and os.path.isdir(folder):
        q = norm_text(query).strip()
        for root, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(MUSIC_EXT) and (not q or q in norm_text(f)):
                    out.append(os.path.join(root, f))
    return sorted(out, key=lambda x: norm_text(os.path.basename(x)))


def loudness(path, start=0.0, dur=None):
    """Средняя громкость (LUFS, EBU R128) файла или его куска. Тишина — None."""
    key = (os.path.abspath(path), round(start, 2), dur and round(dur, 2),
           os.path.getmtime(path) if os.path.exists(path) else 0)
    if key in _loudness_cache:
        return _loudness_cache[key]
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}"]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", path, "-vn", "-af", "ebur128=framelog=quiet", "-f", "null", "-"]
    p = run(cmd)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
    val = float(m[-1]) if m else None
    if val is not None and val < -69:            # почти тишина — громкость не посчитать
        val = None
    _loudness_cache[key] = val
    return val


def waveform(path, bins=600):
    """Волна трека: [0..1] по bins кусочкам и длина в секундах."""
    import numpy as np
    p = run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "4000",
             "-f", "s16le", "-"], binary=True)
    x = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if not len(x):
        raise AutoClipError(f"❌ Не получилось прочитать трек: {os.path.basename(path)}")
    dur = len(x) / 4000.0
    chunks = np.array_split(np.abs(x), bins)
    peaks = np.array([c.max() if len(c) else 0.0 for c in chunks])
    top = peaks.max() or 1.0
    return [round(float(v / top), 3) for v in peaks], dur


def speech_spans(words, gap=0.5):
    """Где говорят: слова, слитые в куски (пауза меньше gap — один кусок)."""
    spans = []
    for w in sorted(words, key=lambda w: w["s"]):
        if spans and w["s"] - spans[-1][1] < gap:
            spans[-1][1] = max(spans[-1][1], w["e"])
        else:
            spans.append([w["s"], w["e"]])
    return [tuple(x) for x in spans]


def music_chain(m_in, total, mcfg, gain_db, speech=()):
    """Фильтры для музыки: громкость, приглушение под речью (и под матом — так же, без провала
    в тишину), плавные края. Возвращает строку фильтра, которая из m_in делает [mus]."""
    fade = max(0.0, min(float(mcfg.get("fade", 1.0)), total / 3))
    base = 10 ** (gain_db / 20)
    expr = f"{base:.5f}"
    if mcfg.get("duck", True) and speech:
        k = 1 - 10 ** (-DUCK_DB / 20)
        env = "+".join(f"clip((t-{a - 0.25:.2f})/0.2,0,1)*clip(({b + 0.4:.2f}-t)/0.3,0,1)"
                       for a, b in speech)
        expr += f"*(1-{k:.3f}*min(1,{env}))"
    chain = (f"{m_in}aformat=sample_rates=48000:channel_layouts=stereo,"
             f"atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume='{expr}':eval=frame")
    if fade > 0:
        chain += f",afade=t=in:d={fade:.2f},afade=t=out:st={max(0.0, total - fade):.3f}:d={fade:.2f}"
    return chain + "[mus]"


def music_gain(mcfg, voice_lufs):
    """Усиление музыки (дБ), чтобы она была на mcfg["volume"] дБ тише голоса."""
    ml = loudness(mcfg["file"], float(mcfg.get("offset", 0)), mcfg.get("_len"))
    rel = float(mcfg.get("volume", MUSIC_DEFAULT["volume"]))
    if ml is None or voice_lufs is None:
        return rel                                   # не измерить — просто громкость ползунка
    return (voice_lufs + rel) - ml


def check_music(mcfg):
    if not mcfg:
        return None
    f = mcfg.get("file")
    if not f or not os.path.isfile(f):
        log(f"⚠️  Трек не найден, клип без музыки: {f}")
        return None
    if not f.lower().endswith(MUSIC_EXT):
        log(f"⚠️  Этот файл не похож на трек, клип без музыки: {os.path.basename(f)}")
        return None
    return dict(MUSIC_DEFAULT, **mcfg)


def bleep_gains(src, tl, bleeps, snd, cfg):
    """snd — путь к звуку или список путей (свой на каждое место)."""
    if isinstance(snd, list):
        cache = {}
        out = []
        for i, b in enumerate(bleeps):
            if snd[i] not in cache:
                cache[snd[i]] = loudness(snd[i])
            out.append(_bleep_gain(src, tl, b, cache[snd[i]], cfg))
        return out
    sl = loudness(snd)
    return [_bleep_gain(src, tl, b, sl, cfg) for b in bleeps]


def _bleep_gain(src, tl, bleep, sl, cfg):
    """Усиление звука на мат (дБ) для каждого места: под громкость речи рядом (окно ±1,5 с
    в записи, LUFS) плюс поправка bleep_rel_db. Не измерить — фиксированная bleep_volume."""
    fixed = 20 * math.log10(max(0.01, float(cfg.get("bleep_volume", 1.0))))
    a, b, _ = bleep
    t = out_to_rec(a, tl)                                   # где это место в записи
    voice = loudness(src, max(0.0, t - 1.5), (b - a) + 3.0)
    return fixed if (sl is None or voice is None) else voice + float(cfg.get("bleep_rel_db", 0.0)) - sl


def clip_words(segments, s, e):
    """Слова клипа со временем относительно его начала."""
    words = []
    for seg in segments:
        if seg["e"] < s or seg["s"] > e:
            continue
        for wd in seg["words"]:
            if wd["s"] >= s - 0.05 and wd["e"] <= e + 0.05:
                words.append({"s": round(wd["s"] - s, 3), "e": round(wd["e"] - s, 3), "w": wd["w"],
                              "spk": wd.get("spk", "me")})
    return words


def is_mat_word(w):
    """Мат по фильтру или по ручной пометке у клипа («это мат» / «не мат»)."""
    if w.get("nomat"):
        return False
    return bool(w.get("mat")) or is_profane(w["w"])


def apply_word_edits(words, cfg):
    """Правки текста клипа: words_edit — {время слова в записи: новый текст} (пусто — убрать
    из субтитров), mat_words — времена слов, которые фильтр пропустил, а это мат."""
    edits = {round(float(k), 2): v for k, v in (cfg.get("words_edit") or {}).items()}
    mats = [float(t) for t in cfg.get("mat_words") or []]
    out = []
    for w in words:
        src = w.get("src")
        if src is not None and w["w"]:
            key = next((k for k in edits if abs(k - src) < 0.06), None)
            if key is not None:
                w = dict(w, w=str(edits[key]).strip())
                if not w["w"]:
                    continue
            if any(abs(t - src) < 0.06 for t in mats):
                w = dict(w, mat=True)
        out.append(w)
    return out


def mark_manual_bleeps(words, cfg, s, e=None, hook=None, hd=0.0):
    """Ручные правки писка у клипа (время — в записи, чтобы пережить сдвиг границ):
    bleep_remove — начала слов, где писк снять; bleep_add — [начало, конец] куска, где запикать
    (слова, которого нет в расшифровке)."""
    remove = [float(t) for t in cfg.get("bleep_remove") or []]
    out = [dict(w, nomat=True) if any(abs(w.get("src", -99) - t) < 0.06 for t in remove) else w
           for w in words]
    tl = s if isinstance(s, list) else clip_timeline(s, e, None, hook)    # s — готовые куски
    for a, b in cfg.get("bleep_add") or []:
        a, b = float(a), float(b)
        parts = [(max(a, ra) - ra + o, min(b, rb) - ra + o, part)
                 for ra, rb, o, part in tl if a < rb and b > ra]
        for x, y, part in parts:
            if y - x > 0.02:
                out.append({"s": round(x, 3), "e": round(y, 3), "w": "", "mat": True, "part": part,
                            "src": a})
    return sorted(out, key=lambda w: w["s"])


PARTIAL_MIN = 0.25          # слово короче — закрываем целиком (граница внутри слова ненадёжна)
PARTIAL_PAD = 0.04          # запас вокруг скрытой части


def bleep_spans(words, total, pad, partial=False):
    """Где закрыть мат: [(начало, конец, до_куда_можно_звук)] во времени клипа.
    Запас pad вокруг слова не залезает на соседние слова без мата, а звук поверх мата
    должен закончиться до начала следующего такого слова."""
    ws = sorted(words, key=lambda w: w["s"])
    spans = []
    for i, wd in enumerate(ws):
        if not is_mat_word(wd):
            continue
        prev_e = max((w["e"] for w in ws[:i] if not is_mat_word(w)), default=0.0)
        nxt = next((w["s"] for w in ws[i + 1:] if not is_mat_word(w)), total)
        a = max(0.0, wd["s"] - pad, min(prev_e, wd["s"]))
        b = min(total, wd["e"] + pad, max(nxt, wd["e"]))
        until = min(total, max(nxt, b))
        span = mask_span(wd["w"]) if partial and wd["w"] else None
        d = wd["e"] - wd["s"]
        if span and d >= PARTIAL_MIN:
            x, y, n = span                       # закрыть только скрытые буквы, остальное слышно
            a = max(0.0, wd["s"] + d * x / n - PARTIAL_PAD)
            b = min(total, wd["s"] + d * y / n + PARTIAL_PAD)
            until = b
        if spans and a <= spans[-1][1]:
            spans[-1][1:] = [b, until]
        else:
            spans.append([a, b, until])
    return [tuple(x) for x in spans]


def render_clip(video, clip, segments, vinfo, out_path, tmpdir, cfg=None, cancel=None,
                on_frac=None):
    """clip: {'s', 'e', 'zooms', 'hook': (начало, конец) или None} во времени записи.
    Хук — кусок этого же клипа, ставится в самое начало, затем клип с начала.
    Возвращает число запиканных мест или None. Клип собирается во временной папке
    и только потом встаёт на место out_path."""
    global _ENCODER
    cfg = cfg or CONFIG
    preset = get_preset(cfg["preset"])
    s, e = clip["s"], clip["e"]
    dur = e - s
    W, H = preset["w"], preset["h"]
    hook = clip.get("hook")
    if hook and not (s <= hook[0] < hook[1] <= e):
        raise AutoClipError("❌ Хук вне клипа — так нельзя.")
    cuts = clip_cuts(clip, cfg)
    if hook and in_cuts(hook[0], hook[1], cuts):
        raise AutoClipError("❌ Хук из вырезанного куска — так нельзя.")
    tl = clip_timeline(s, e, cuts, hook)
    if not any(part for _, _, _, part in tl):
        raise AutoClipError("❌ Вырезано всё — от клипа ничего не осталось.")
    hd = (hook[1] - hook[0]) if hook else 0.0      # длина хука = сдвиг клипа в готовом видео
    total = timeline_len(tl)
    clip["timeline"] = [list(x) for x in tl]

    # слова и зумы во времени готового видео
    words = []
    for ra, rb, o, part in tl:
        last = part == tl[-1][3]
        for w in clip_words(segments, ra, rb):
            if len(tl) > 1 and not (0 <= (w["s"] + w["e"]) / 2 < rb - ra):
                continue                            # слово на стыке — в том куске, где его середина
            w = dict(w, s=round(w["s"] + o, 3), e=round(min(w["e"], rb - ra + 0.05) + o, 3),
                     part=part, src=ra + w["s"])
            if not last:
                w["until"] = round(o + rb - ra, 3)  # субтитры куска исчезают ровно на склейке
            words.append(w)
    words = mark_manual_bleeps(words, cfg, tl)
    words = apply_word_edits(words, cfg)
    zooms = []
    pts, _ = clip_zooms(dict(clip, start=s, end=e, overrides={}), cfg)
    for z in pts:
        t = rec_to_out(z, tl)
        if t is not None and hd + 1.0 <= t <= total - 2.0:
            zooms.append(t)
    if hook:
        zooms = [0.12] + zooms                      # хук — сразу крупно

    # --- склейка хука и кусков клипа ---
    pre = ",".join(frame_filters(vinfo, preset))
    fmt = "aformat=sample_rates=48000:channel_layouts=stereo"
    src = os.path.abspath(video)
    if len(tl) > 1:
        inputs, graph, cat = [], "", ""
        fade = 0.03                                 # без щелчка на склейке
        for i, (ra, rb, o, part) in enumerate(tl):
            ln = rb - ra
            inputs += ["-ss", f"{ra:.3f}", "-t", f"{ln:.3f}", "-i", src]
            af = [fmt]
            if i < len(tl) - 1:
                af.append(f"afade=t=out:st={max(0.0, ln - fade):.3f}:d={fade}")
            if i:
                af.append(f"afade=t=in:d={fade}")
            graph += (f"[{i}:v]{pre},setpts=PTS-STARTPTS[v{i}];"
                      f"[{i}:a]{','.join(af)},asetpts=PTS-STARTPTS[a{i}];")
            cat += f"[v{i}][a{i}]"
        graph += f"{cat}concat=n={len(tl)}:v=1:a=1[vc][ac];"
        vin, ain, snd_in = "[vc]", "[ac]", len(tl)
        vf = []
    else:
        inputs = ["-ss", f"{s:.3f}", "-t", f"{dur:.3f}", "-i", src]
        graph = ""
        vin, ain, snd_in = "[0:v]", "[0:a]", 1
        vf = [pre]

    # --- видео ---
    if zooms and cfg.get("zoom") not in (False, "off"):
        A = cfg["zoom_amount"]
        env = "+".join(
            f"clip((t-{z - 0.12:.2f})/0.12,0,1)*clip(({z + 1.6:.2f}-t)/0.35,0,1)"
            for z in zooms)
        Z = f"(1+{A}*min(1,{env}))"
        fy = cfg["zoom_focus_y"]
        vf.append(f"scale=w='2*trunc({W}*{Z}/2)':h='2*trunc({H}*{Z}/2)':eval=frame:flags=lanczos")
        vf.append(f"crop={W}:{H}:x='(iw-ow)/2':y='(ih-oh)*{fy}'")
    sub_words = [w for w in words if w["w"] and (w.get("spk", "me") == "me" or cfg.get("subs_team"))]
    if cfg["subs"] and sub_words:
        ass_name = "subs.ass"
        build_ass(sub_words, W, H, os.path.join(tmpdir, ass_name), cfg)
        vf.append(ass_filter(ass_name, tmpdir))
    if cfg.get("nick") and str(cfg.get("nick_text", "")).strip():
        build_nick_ass(W, H, os.path.join(tmpdir, "nick.ass"), cfg, total)
        vf.append("ass=nick.ass")
    # перевод в Rec. 709 и метки цвета в самих кадрах (ffmpeg 9 берёт их оттуда, а не из флагов)
    vf.append("scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
              "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv")
    graph += vin + ",".join(vf) + "[vout]"

    # --- звук и бип ---
    bleeps = bleep_spans(words, total, cfg["bleep_pad"], cfg.get("censor") == "partial") if cfg["bleep"] else []
    # звуки «Случайного» фиксированы у клипа: от его пика (не меняется при сдвиге границ)
    seed = cfg.get("bleep_seed") if cfg.get("bleep_seed") is not None else int(clip.get("peak", s) * 1000)
    names = bleep_sequence(cfg, len(bleeps), seed)
    clip["bleep_seq"] = names if cfg.get("bleep_sound") == RANDOM_SOUND else None
    paths = [sound_path(x) for x in names]
    extra_in, n_snd = [], 0
    if bleeps:
        E = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b, _ in bleeps)
        agraph = f"{ain}{fmt},volume=0:enable='{E}'[am]"
        used = [i for i, x in enumerate(paths) if x]          # «тишина» — только заглушить
        if used:
            files = sorted({paths[i] for i in used})
            for k, f in enumerate(files):
                mine = [i for i in used if paths[i] == f]
                extra_in += ["-i", os.path.abspath(f)]
                agraph += (f";[{snd_in + k}:a]{fmt},asplit={len(mine)}" +
                           "".join(f"[s{i}]" for i in mine))
            n_snd = len(files)
            sdurs = {f: sound_duration(f) for f in files}
            gains = bleep_gains(src, tl, bleeps, paths, cfg)
            for i, (a, b, until) in enumerate(bleeps):
                if i not in used:
                    continue
                sdur = sdurs[paths[i]]
                # звук не дольше, чем до следующего слова без мата
                L = max(0.05, min(sdur, until - a))
                fd = min(0.06, L / 3)
                ms = int(a * 1000)
                agraph += (f";[s{i}]atrim=0:{L:.3f},volume={gains[i]:.2f}dB,"
                           f"afade=t=out:st={L - fd:.3f}:d={fd:.3f},adelay={ms}:all=1[d{i}]")
            agraph += ";[am]" + "".join(f"[d{i}]" for i in used) + \
                      f"amix=inputs={len(used) + 1}:duration=first:normalize=0[aout]"
        else:
            agraph = agraph.replace("[am]", "[aout]")
    else:
        agraph = f"{ain}{fmt}[aout]"

    # --- музыка ---
    music = check_music(cfg.get("music"))
    if music:
        mi = snd_in + n_snd
        extra_in += ["-ss", f"{float(music.get('offset', 0)):.3f}", "-t", f"{total:.3f}",
                     "-i", os.path.abspath(music["file"])]
        voice = loudness(src, s, dur)
        gain = music_gain(dict(music, _len=total), voice)
        agraph = agraph.replace("[aout]", "[voice]")
        # мат — тоже речь: под ним музыка приглушена, как под словами
        agraph += ";" + music_chain(f"[{mi}:a]", total, music, gain, speech_spans(words))
        agraph += ";[voice][mus]amix=inputs=2:duration=first:normalize=0[aout]"

    tmp_out = os.path.join(tmpdir, "render.mp4")
    graph += ";" + agraph
    base = ["ffmpeg", "-y", "-v", "error"] + inputs + extra_in + [
        "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]"]
    tail = COLOR_FLAGS + ["-fps_mode", "cfr", "-r", str(preset["fps"]),
                          "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
                          "-movflags", "+faststart", tmp_out]

    encs = _encoders(preset)
    names = [_ENCODER] if _ENCODER else list(encs)
    last_err = ""
    track = (lambda t: on_frac(min(1.0, t / total))) if on_frac else None
    for name in names:
        p = run(base + encs[name] + tail, cwd=tmpdir, cancel=cancel, on_time=track)
        if p.returncode == 0:
            _ENCODER = name
            replace_file(tmp_out, out_path)
            return len(bleeps)
        last_err = p.stderr
    log("   ❌ ffmpeg:\n" + last_err[-1500:])
    return None


# ---------------- обложка ----------------

COVER_WINDOW = 1.0     # кадр для обложки ищем ±1 с вокруг самой яркой реакции
COVER_FPS = 4          # сколько кадров в секунду смотреть


def _face_detector():
    """Детектор лиц OpenCV, если он установлен (иначе обложка выбирается по резкости)."""
    try:
        import cv2
    except ImportError:
        return None
    path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    det = cv2.CascadeClassifier(path) if os.path.isfile(path) else None
    return None if det is None or det.empty() else det


def cover_moment(clip, reaction):
    """Секунда записи с самой яркой реакцией внутри клипа — вокруг неё ищем обложку."""
    import numpy as np
    s, e = clip["start"], clip["end"]
    n = 0 if reaction is None else len(reaction)
    a, b = int(math.ceil(s + 0.5)), min(n, int(e - 0.5))
    if b <= a:
        return (s + e) / 2
    return a + int(np.argmax(np.asarray(reaction[a:b], dtype=float))) + 0.5


def webcam_zone(cfg, h):
    """Строки кадра, где вебка: сверху, снизу или весь кадр (по «Раскладке»)."""
    fy = cfg.get("zoom_focus_y", 0.3)
    if fy < 0.45:
        return 0, h // 2
    if fy > 0.55:
        return h // 2, h
    return 0, h


def score_cover_frame(gray, det=None, zone=None):
    """Насколько кадр хорош для обложки: лицо в зоне вебки, резкость, не тёмный.
    Возвращает (оценка, есть ли лицо)."""
    import numpy as np
    f = gray.astype(np.int16)
    sharp = float(np.var(np.diff(f, axis=1))) + float(np.var(np.diff(f, axis=0)))
    score = math.log1p(sharp)
    if gray.mean() < 25:                          # почти чёрный кадр — плохая обложка
        score -= 3.0
    face = False
    if det is not None:
        a, b = zone or (0, gray.shape[0])
        found = det.detectMultiScale(gray[a:b], scaleFactor=1.1, minNeighbors=5, minSize=(20, 20))
        if len(found):
            face = True
            biggest = max(fw * fh for (_, _, fw, fh) in found)
            score += 10.0 + 50.0 * biggest / gray.size
    return score, face


def pick_cover_time(video, vinfo, t, cfg, cancel=None):
    """Из кадров t±1 с выбирает лучший для обложки. Возвращает (время, есть ли лицо)."""
    import numpy as np
    preset = get_preset(cfg["preset"])
    w = 270
    h = int(round(w * preset["h"] / preset["w"] / 2)) * 2
    t0 = max(0.0, t - COVER_WINDOW)
    vf = ",".join(frame_filters(vinfo, preset) + [f"fps={COVER_FPS}", f"scale={w}:{h}", "format=gray"])
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{2 * COVER_WINDOW:.3f}",
                        "-i", video, "-vf", vf, "-f", "rawvideo", "-"],
                       capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=_flags())
    check_cancel(cancel)
    raw = np.frombuffer(p.stdout, np.uint8)
    n = len(raw) // (w * h)
    if p.returncode != 0 or n == 0:
        return t, False
    frames = raw[:n * w * h].reshape(n, h, w)
    det = _face_detector()
    zone = webcam_zone(cfg, h)
    scored = [score_cover_frame(fr, det, zone) for fr in frames]
    best = max(range(n), key=lambda i: scored[i][0])
    return t0 + best / COVER_FPS, scored[best][1]


def make_cover(video, vinfo, clip, reaction, cover_path, cfg=None, cancel=None):
    """Обложка клипа <клип>.jpg: кадр с самой яркой реакцией (с лицом, если найдётся),
    в размере клипа, без субтитров и зума. Кадр всегда из самого клипа.
    Возвращает {"file", "t", "face"} или None — обложка не должна ломать нарезку."""
    cfg = cfg or CONFIG
    try:
        t, face = pick_cover_time(video, vinfo, cover_moment(clip, reaction), cfg, cancel)
        t = min(max(t, clip["start"]), clip["end"] - 0.05)
        preset = get_preset(cfg["preset"])
        vf = ",".join(frame_filters(vinfo, preset) + ["format=yuvj420p"])
        tmp = cover_path + ".tmp.jpg"
        p = run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
                 "-vf", vf, "-q:v", "2", tmp], cancel=cancel)
        if p.returncode != 0 or not os.path.isfile(tmp):
            return None
        replace_file(tmp, cover_path)
        return {"file": os.path.basename(cover_path), "t": round(t, 2), "face": bool(face)}
    except Cancelled:
        raise
    except Exception as e:
        log(f"   ⚠️  обложка не получилась: {e}")
        return None


def cover_path_for(folder, clip_file):
    return os.path.join(folder, os.path.splitext(clip_file)[0] + ".jpg")


# ---------------- 8. файлы и папка пользователя ----------------

SETTINGS_PATH = os.path.join(user_dir(), "настройки.json")


def migrate_user_data():
    """Переносит настройки и свои звуки из папки программы (версия 1) в %APPDATA%\\AutoClip."""
    old = os.path.join(SCRIPT_DIR, "настройки.json")
    if os.path.isfile(old) and not os.path.exists(SETTINGS_PATH):
        shutil.move(old, SETTINGS_PATH)
    old_sounds = os.path.join(SCRIPT_DIR, "звуки")
    if os.path.isdir(old_sounds) and os.path.abspath(old_sounds) != os.path.abspath(SOUNDS_DIR):
        os.makedirs(SOUNDS_DIR, exist_ok=True)
        for f in os.listdir(old_sounds):
            src, dst = os.path.join(old_sounds, f), os.path.join(SOUNDS_DIR, f)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.move(src, dst)
        try:
            os.rmdir(old_sounds)        # только если папка опустела
        except OSError:
            pass


def _send_to_trash(path):
    try:
        from send2trash import send2trash
    except ImportError:
        raise AutoClipError("❌ Не установлен send2trash. Запусти install.bat.")
    send2trash(os.path.abspath(path))


def trash(path, wait=3.0):
    """Удаление только в корзину Windows — насовсем программа ничего не удаляет.
    Если файл ещё занят (например, проигрыватель не успел его отпустить), пробуем снова."""
    deadline = time.time() + wait
    while True:
        if not os.path.exists(path):
            return
        try:
            _send_to_trash(path)
            return
        except OSError:
            if time.time() >= deadline:
                raise AutoClipError(f"❌ Файл занят другой программой: {os.path.basename(path)}\n"
                                    "   Закрой его там и попробуй ещё раз.")
            time.sleep(0.2)


def replace_file(src, dst):
    """Ставит новый файл на место старого; старый уходит в корзину."""
    if os.path.exists(dst):
        trash(dst)
    shutil.move(src, dst)


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def parse_time(t):
    """'95.5', '1:35', '1:02:10' → секунды."""
    if isinstance(t, (int, float)):
        return float(t)
    parts = str(t).strip().replace(",", ".").split(":")
    try:
        sec = 0.0
        for x in parts:
            sec = sec * 60 + float(x)
        return sec
    except ValueError:
        raise AutoClipError(f"❌ Не понял время «{t}». Пиши секундами или как 1:02:10.")


# ---------------- 9. проект записи (project.json) ----------------

PROJECT_FILE = "project.json"
PROJECT_VERSION = 1
STATUSES = {"new": "новый", "good": "хороший", "published": "выложен", "rejected": "отклонён"}
# что можно переопределить у отдельного клипа
OVERRIDE_KEYS = ("subs", "zoom", "bleep", "bleep_sound", "hook", "sub_y", "safe_zone", "nick",
                 "sub_x", "sub_style", "music", "bleep_add", "bleep_remove", "hook_at",
                 "words_edit", "mat_words", "title", "censor", "cuts", "bleep_seed",
                 "bleep_pool") + STYLE_KEYS
# настройки, которые запоминаются в проекте и нужны для пересборки
RENDER_KEYS = ("subs", "subs_team", "sub_font", "sub_size", "sub_y", "safe_zone", "sub_max_words", "sub_max_chars",
               "sub_mode", "sub_color", "sub_hl_color", "sub_outline_color", "sub_outline",
               "sub_x", "sub_style",
               "sub_uppercase", "zoom", "zoom_amount", "zoom_focus_y", "bleep", "bleep_soft",
               "bleep_sound", "bleep_pool", "bleep_volume", "bleep_rel_db", "bleep_pad", "censor", "preset", "hook",
               "nick", "nick_text", "nick_corner", "nick_size", "nick_opacity",
               "hashtags", "platform_tags")


def clip_dirs(video):
    """Папки нарезок записи по порядку: «<запись>_clips», «<запись>_clips_2», …"""
    base = os.path.splitext(os.path.abspath(video))[0] + "_clips"
    found = []
    if os.path.isdir(base):
        found.append((1, base))
    folder = os.path.dirname(base)
    name = os.path.basename(base)
    try:
        entries = os.listdir(folder)
    except OSError:
        entries = []
    for d in entries:
        m = re.fullmatch(re.escape(name) + r"_(\d+)", d)
        if m and os.path.isdir(os.path.join(folder, d)):
            found.append((int(m.group(1)), os.path.join(folder, d)))
    return [d for _, d in sorted(found)]


def new_clip_dir(video):
    """Папка для новой нарезки: каждая нарезка — в свою папку, старые не трогаются."""
    base = os.path.splitext(os.path.abspath(video))[0] + "_clips"
    dirs = clip_dirs(video)
    if not dirs:
        return base
    n = max(int(d.rsplit("_", 1)[1]) if d != base else 1 for d in dirs) + 1
    return f"{base}_{n}"


def project_path(path):
    """Запись (её последняя нарезка), папка нарезки или сам project.json → project.json."""
    path = os.path.abspath(path)
    if os.path.isdir(path):
        return os.path.join(path, PROJECT_FILE)
    if path.lower().endswith(".json"):
        return path
    dirs = clip_dirs(path)
    last = dirs[-1] if dirs else os.path.splitext(path)[0] + "_clips"
    return os.path.join(last, PROJECT_FILE)


def load_project(path):
    pp = project_path(path)
    if not os.path.isfile(pp):
        raise AutoClipError(f"❌ Нет проекта: {pp}\n   Сначала нарежь запись.")
    with open(pp, encoding="utf-8") as f:
        proj = json.load(f)
    proj["_path"] = pp
    return proj


def save_project(proj):
    """Пишет project.json через временный файл, чтобы при сбое не остался обрывок."""
    pp = proj["_path"]
    data = {k: v for k, v in proj.items() if not k.startswith("_")}
    tmp = pp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, pp)


def new_project(video, vinfo, out_dir, transcript):
    return {"_path": os.path.join(out_dir, PROJECT_FILE), "version": PROJECT_VERSION,
            "source": os.path.abspath(video), "source_info": vinfo,
            "transcript": os.path.abspath(transcript), "created": now_iso(),
            "settings": {}, "run": {}, "clips": []}


def find_clip(proj, ref):
    """Клип по id («c03»), номеру («3») или имени файла."""
    ref = str(ref).strip()
    for c in proj["clips"]:
        if ref in (c["id"], c["file"]) or (ref.isdigit() and int(ref) == c["num"]):
            return c
    raise AutoClipError(f"❌ В проекте нет клипа «{ref}».")


def clip_config(proj, clip):
    """Настройки рендера клипа: общие → сохранённые в проекте → личные клипа."""
    cfg = dict(CONFIG)
    cfg.update(proj.get("settings", {}))
    if proj.get("settings") and "censor" not in proj["settings"]:
        cfg["censor"] = "full"                      # нарезки до 1.3.0 — пересборка как была
    cfg.update({k: v for k, v in clip.get("overrides", {}).items() if k in OVERRIDE_KEYS})
    for k in ("hook", "zoom"):                  # у клипа старое True — «включить»
        cfg[k] = tri(clip.get("overrides", {}).get(k), "on") or tri(cfg.get(k))
    return cfg


def make_clip_record(c, num, file):
    return {
        "id": f"c{num:02d}", "num": num, "file": file,
        "start": c["s"], "end": c["e"], "peak": c["peak"],
        "score": round(c["score"], 2), "score_parts": c.get("parts", {}),
        "title": c["title"], "reason": c["reason"],
        "zooms": c["zooms"],
        **({"zoom_auto": c["zoom_auto"]} if "zoom_auto" in c else {}),
        "marks": c.get("marks", []),           # метки из OBS, по которым найден клип
        "meta": c.get("meta"),                 # название и хэштеги от языковой модели
        "desc_custom": None,                   # своё описание по площадкам, если поправил
        "hook": c.get("hook") or {"on": False, "auto": False, "start": None, "end": None,
                                  "why": "нет данных для хука"},
        "status": "new", "overrides": {}, "bleeps": None,
        "created": now_iso(), "rendered": None,
        "published": {},       # площадка → {"date", "url", "views": [...]}
        "origin": "auto",      # откуда клип: auto, search (поиск), candidate (кандидат)
    }


QUIET_DB = -35.0              # тише этого — «без звука»


def quiet_start(path, seconds=3.0):
    """True, если в первые seconds секунд готового клипа нет звука («тихое начало»)."""
    import numpy as np
    p = subprocess.run(["ffmpeg", "-v", "error", "-t", f"{seconds:.2f}", "-i", path, "-vn",
                        "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                       capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=_flags())
    x = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if p.returncode != 0 or not len(x):
        return None
    win = 8000                                   # по полсекунды
    levels = [20 * math.log10(float(np.sqrt(np.mean(x[i:i + win] ** 2))) + 1e-6)
              for i in range(0, len(x), win) if len(x[i:i + win])]
    return max(levels) < QUIET_DB


def clip_tags(c):
    """Короткие пометки клипа для списка: статус, хук, тихое начало, метка."""
    tags = [STATUSES.get(c["status"], c["status"]),
            "хук" if (c.get("hook") or {}).get("on") else "без хука"]
    if c.get("quiet_start"):
        tags.append("тихое начало")
    if c.get("marks"):
        tags.append("метка")
    if c.get("origin") == "search":
        tags.append("из поиска")
    return tags


def set_status(path, ref, status):
    """Новый статус клипа. «Отклонён» — файл клипа уходит в корзину Windows."""
    if status not in STATUSES:
        raise AutoClipError(f"❌ Нет такого статуса: {status}")
    proj = load_project(path)
    clip = find_clip(proj, ref)
    if clip["status"] == "rejected":
        raise AutoClipError("❌ Клип уже в корзине.")
    if status == "rejected":
        folder = os.path.dirname(proj["_path"])
        trash(os.path.join(folder, clip["file"]))
        trash(cover_path_for(folder, clip["file"]))
    clip["status"] = status
    clip["status_date"] = now_iso()
    save_project(proj)
    write_report(proj)
    return clip


def remove_clip(path, ref):
    """«Удалить (без оценки)»: клип убирается из программы, файл и обложка — в корзину Windows.
    На обучение не влияет (дубли, технический брак)."""
    proj = load_project(path)
    clip = find_clip(proj, ref)
    folder = os.path.dirname(proj["_path"])
    trash(os.path.join(folder, clip["file"]))
    trash(cover_path_for(folder, clip["file"]))
    proj["clips"] = [c for c in proj["clips"] if c["id"] != clip["id"]]
    save_project(proj)
    write_report(proj)
    return clip


TG_LIMIT_MB = 50          # Telegram Bot API: файл от бота — не больше 50 МБ


TG_TARGET_MB = 48         # облегчённая копия — с запасом до лимита
FULL_HD_MIN_K = 5000      # ниже — сначала 30 к/с, потом меньше разрешение (не ниже 720×1280)


def light_plan(dur, limit_mb=TG_LIMIT_MB):
    """Как сжать клип в limit_mb: (ширина, высота, кадры/с, видео кбит/с). Сначала держим
    1080×1920 и 60 к/с; битрейта мало — 30 к/с; совсем мало — 720×1280."""
    target = min(TG_TARGET_MB, limit_mb * 0.96)
    video_k = max(200, int(target * 8 * 1024 / max(dur, 1.0)) - 128)
    if video_k >= FULL_HD_MIN_K:
        return 1080, 1920, 60, video_k
    if video_k >= FULL_HD_MIN_K / 2:
        return 1080, 1920, 30, video_k              # вдвое меньше кадров — то же качество кадра
    return 720, 1280, 30, video_k


def light_copy(src, dst, limit_mb=TG_LIMIT_MB, on_frac=None, cancel=None):
    """Облегчённая копия клипа для Telegram: 1080×1920, H.264 в два прохода (preset slow)
    под ~48 МБ, звук AAC 128 кбит/с. Не влезает — 30 к/с, потом 720×1280."""
    dur = _probe_dur(src)
    w, h, fps, video_k = light_plan(dur, limit_mb)
    work = os.path.dirname(os.path.abspath(dst))
    log_base = os.path.join(work, "x264pass")
    vf = f"scale={w}:{h}:flags=lanczos,fps={fps}"
    common = ["-vf", vf, "-c:v", "libx264", "-preset", "slow", "-b:v", f"{video_k}k",
              "-maxrate", f"{int(video_k * 1.3)}k", "-bufsize", f"{video_k * 2}k", "-passlogfile", log_base]
    p1 = run(["ffmpeg", "-y", "-v", "error", "-i", src] + common + ["-pass", "1", "-an", "-f", "null", os.devnull],
             cancel=cancel, on_time=(lambda t: on_frac(min(1.0, t / dur) / 2)) if on_frac else None)
    p = p1 if p1.returncode != 0 else run(
        ["ffmpeg", "-y", "-v", "error", "-i", src] + common +
        ["-pass", "2", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst],
        cancel=cancel, on_time=(lambda t: on_frac(0.5 + min(1.0, t / dur) / 2)) if on_frac else None)
    if p.returncode != 0 or not os.path.isfile(dst):
        raise AutoClipError("❌ Не получилось сделать облегчённую копию:\n" + p.stderr[-400:])
    if os.path.getsize(dst) > limit_mb * 1024 * 1024:
        raise AutoClipError(f"❌ Даже облегчённая копия больше {limit_mb} МБ — клип слишком длинный.")
    return dst


def save_clip_as(path, ref, dest):
    """Копия готового клипа в другое место. Файл с тем же именем там уходит в корзину."""
    proj = load_project(path)
    clip = find_clip(proj, ref)
    src = os.path.join(os.path.dirname(proj["_path"]), clip["file"])
    if not os.path.isfile(src):
        raise AutoClipError("❌ Файла клипа нет.")
    if os.path.abspath(dest) == os.path.abspath(src):
        return dest
    if os.path.exists(dest):
        trash(dest)
    shutil.copy2(src, dest)
    return dest


def add_forecast(clip, segments):
    """Признаки клипа и прогноз 0–10 (правила + модель, если обучена)."""
    try:
        import forecast
        clip["features"] = forecast.clip_features(clip, segments)
        clip["forecast"] = forecast.predict(clip["features"], clip.get("score", 0),
                                            forecast.load_model())
    except Exception as e:                       # прогноз не должен ломать нарезку
        log(f"   ⚠️  прогноз не посчитался: {e}")


def write_report(proj):
    out_dir = os.path.dirname(proj["_path"])
    vi = proj["source_info"]
    rep = [f"Источник: {proj['source']}", ""]
    clips = sorted((c for c in proj["clips"] if c["status"] != "rejected"),
                   key=lambda c: -c["score"])
    for c in clips:
        rep.append(f"{c['num']:02d}. {fmt_time(c['start'])}–{fmt_time(c['end'])} "
                   f"({c['end'] - c['start']:.0f} с), оценка {c['score']:.1f}, "
                   f"{STATUSES.get(c['status'], c['status'])}")
        rep += [f"    файл: {c['file']}", f"    про что: {c['title']}"]
        if c.get("marks"):
            rep.append("    📍 метка из OBS: " + ", ".join(fmt_time(t) for t in c["marks"]))
        if c["reason"]:
            rep.append(f"    почему: {c['reason']}")
        parts = ", ".join(f"{k} {v:+.1f}" for k, v in c["score_parts"].items() if abs(v) >= 0.05)
        if parts:
            rep.append(f"    из чего оценка: {parts}")
        rep.append(f"    запикано: {c['bleeps'] if c['bleeps'] is not None else '-'}; "
                   + clip_zooms(c, clip_config(proj, c))[1])
        rep.append("    " + hook_text(c))
        if c.get("forecast") and c.get("features"):
            import forecast
            rep.append(f"    прогноз: {c['forecast']['value']:.1f} из 10 — {c['forecast']['note']}")
            for ok, text in forecast.retention_notes(c, c["features"]):
                rep.append("      " + {True: "+", False: "−", None: "·"}[ok] + " " + text)
        rep.append("    хэштеги (TikTok): " +
                   (" ".join(compose_tags("tiktok", proj.get("settings") or CONFIG,
                                          (c.get("meta") or {}).get("tags", []))) or "—"))
        if c.get("quiet_start"):
            rep.append("    тихое начало — первые 3 с без звука")
        if c.get("cover"):
            cv = c["cover"]
            rep.append(f"    обложка: {cv['file']} (кадр {fmt_time(cv['t'])}"
                       f"{', лицо' if cv.get('face') else ''})")
        if c["overrides"]:
            rep.append("    свои настройки: " +
                       ", ".join(f"{k}={v}" for k, v in c["overrides"].items()))
        rep.append("")
    cands = proj.get("candidates") or []
    if cands:
        rep.append(f"Кандидаты (без видео, собрать — в «Клипах»): {len(cands)}")
        rep += [f"    {fmt_time(k['start'])}–{fmt_time(k['end'])}, оценка {k['score']:.1f} — {k['title']}"
                for k in cands]
        rep.append("")
    run_info = proj.get("run", {})
    rep += [f"Запись: {fmt_time(vi['dur'])}, {vi['w']}x{vi['h']}, {vi.get('fps', 0):g} к/с"]
    pr = get_preset(proj.get("settings", {}).get("preset", CONFIG["preset"]))
    rep.append(f"Пресет: {pr['name']} — {pr['w']}x{pr['h']}, {pr['fps']} к/с, "
               f"{pr['kbps']} Кбит/с, H.264")
    if run_info:
        rep.append(f"Время работы: {run_info.get('minutes', 0):.1f} мин")
        rep += [f"    {n}: {sec:.0f} с" for n, sec in run_info.get("timings", [])]
        if run_info.get("encoder"):
            rep.append(f"    кодек: {run_info['encoder']}")
    with open(os.path.join(out_dir, "отчёт.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep))


# ---------------- хэштеги и описание ----------------

PLATFORMS = {"tiktok": "TikTok", "youtube": "YouTube", "instagram": "Instagram"}
MAX_TAGS = 5
_TAG_CHARS = re.compile(r"[^\w]", re.U)


def parse_tags(text):
    """«стрим, #игры  shorts» → ['#стрим', '#игры', '#shorts'] — без повторов и мусора."""
    out, seen = [], set()
    for raw in re.split(r"[\s,;]+", str(text or "")):
        word = _TAG_CHARS.sub("", raw.lstrip("#"))
        if word and word.lower() not in seen:
            seen.add(word.lower())
            out.append("#" + word)
    return out


def compose_tags(platform, cfg=None, content=()):
    """Хэштеги для площадки: добавка площадки (#shorts), постоянные, потом по содержанию.
    Не больше MAX_TAGS, без повторов."""
    cfg = cfg or CONFIG
    tags = (parse_tags(cfg.get("platform_tags", {}).get(platform, "")) +
            parse_tags(cfg.get("hashtags", "")) + parse_tags(" ".join(content or [])))
    out, seen = [], set()
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:MAX_TAGS]


def clip_title(clip):
    """Название клипа для описания: от модели, если есть, иначе своё (без мата)."""
    meta = clip.get("meta") or {}
    mode = (clip.get("overrides") or {}).get("censor")
    title = (meta.get("title") or clip.get("title") or "").strip()
    return " ".join(censor_word(w, mode) for w in title.split())


def auto_description(clip, platform, cfg=None):
    """Описание, которое программа предлагает сама: название и хэштеги."""
    tags = compose_tags(platform, cfg, (clip.get("meta") or {}).get("tags", []))
    return (clip_title(clip) + ("\n\n" + " ".join(tags) if tags else "")).strip()


def clip_description(clip, platform, cfg=None):
    """Текст под клип для площадки: свой текст Гоши для этой площадки, если он его
    поправил, иначе — автоматический."""
    custom = (clip.get("desc_custom") or {}).get(platform)
    return custom.strip() if custom else auto_description(clip, platform, cfg)


def set_description(path, ref, platform, text):
    """Свой текст описания клипа для площадки. None или пусто — вернуть автоматический."""
    if platform not in PLATFORMS:
        raise AutoClipError(f"❌ Нет такой площадки: {platform}")
    proj = load_project(path)
    clip = find_clip(proj, ref)
    custom = dict(clip.get("desc_custom") or {})
    text = (text or "").strip()
    if text:
        custom[platform] = text
    else:
        custom.pop(platform, None)
    clip["desc_custom"] = custom or None
    save_project(proj)
    return clip


META_PROMPT = """Ты монтируешь короткие ролики для TikTok русскоязычного игрового стримера.
Ниже — что он говорит в клипе (расшифровка речи, бывают ошибки распознавания).
Придумай:
- title — название, как у роликов, которые залетают: до 50 символов, живо и разговорно,
  с интригой или шуткой. Можно взять короткий кусок его фразы, но не копируй расшифровку
  целиком. Не пиши «стример», «пользователь», «игрок». Без мата, кавычек и эмодзи.
- tags — 2 или 3 хэштега, которые люди реально ищут: название игры (если узнаёшь по речи —
  персонажи, заклинания, места), персонаж, мем, жанр. Слитно, без подчёркиваний.
  Не бери пустые и общие: #игры #стрим #стример #игрок #ситуация #интрига #эмоции #fyp.
Ответь ТОЛЬКО JSON: {"title": "...", "tags": ["#...", "#..."]}

Что он говорит:
<<CLIP>>
"""

# хэштеги, которые модель любит вставлять, а толку от них нет
_EMPTY_TAGS = {
    "мем", "мемы", "игрок", "игры", "игра", "стрим", "стример", "стримы", "ситуация",
    "интрига", "эмоции", "эмоция", "fyp", "foryou", "рекомендации", "ругательства", "мат",
    "шок", "клик", "видео", "тренд", "игровойстример", "игровой_стример", "смешно", "юмор",
}


def useful_tag(tag):
    """Хэштег годится: не пустой-общий и без мата."""
    word = tag.lstrip("#")
    return bool(word) and word.lower() not in _EMPTY_TAGS and not is_profane(word)


def llm_clip_meta(clip_text, mode):
    """Название и 2–3 хэштега по содержанию от языковой модели или None."""
    if mode == "none" or not clip_text.strip():
        return None
    try:
        text = _ask_llm(META_PROMPT.replace("<<CLIP>>", clip_text), mode, max_tokens=300)
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception as e:
        warn_once(f"   ⚠️  модель не ответила про название ({e})")
        return None
    title = " ".join(censor_word(w) for w in str(data.get("title", "")).replace('"', "").split())[:60]
    tags = [t for t in parse_tags(" ".join(map(str, data.get("tags", []) or [])))
            if useful_tag(t)][:3]
    if not title and not tags:
        return None
    return {"title": title, "tags": tags}


def hook_text(c):
    """Одна строка про хук для отчёта и окна."""
    h = c.get("hook") or {}
    if h.get("on"):
        return (f"хук: {fmt_time(h['start'])} в записи, {h['end'] - h['start']:.1f} с "
                f"(с {h['start'] - c['start']:.0f}-й секунды клипа) — {h['why']}")
    forced = tri(c.get("overrides", {}).get("hook"), "on")
    if forced == "off":
        return "без хука — выключен для этого клипа"
    if h.get("auto"):
        return f"без хука — выключен галочкой (был бы: {h['why']})"
    return f"без хука — {h.get('why') or 'нет данных'}"


def norm_text(text):
    """Для поиска: без регистра, ё = е."""
    return str(text).lower().replace("ё", "е")


def search_transcript(segments, query, limit=300):
    """Места в расшифровке, где встречается query (часть слова тоже: «смеш» → «смешно»).
    Возвращает [{t, s, e, text, hl: (начало, конец) подсветки в text}] по времени."""
    q = " ".join(norm_text(query).split())
    if len(q) < 2:
        return []
    hits = []
    for seg in segments:
        words = [w for w in seg.get("words", []) if str(w.get("w", "")).strip()]
        if not words:
            continue
        text, starts, shown, sh = "", [], "", []          # shown — с мат скрытым, как в субтитрах
        for w in words:
            if text:
                text += " "
                shown += " "
            starts.append(len(text))
            text += str(w["w"]).strip()
            a = len(shown)
            shown += censor_word(str(w["w"]).strip())
            sh.append((a, len(shown)))
        low = norm_text(text)
        pos = low.find(q)
        while pos >= 0:
            i = max(k for k, st in enumerate(starts) if st <= pos)   # слово, где началось
            j = max(k for k, st in enumerate(starts) if st < pos + len(q))
            hits.append({"t": float(words[i]["s"]), "s": float(seg["s"]), "e": float(seg["e"]),
                         "text": text, "hl": (pos, pos + len(q)),
                         "shown": shown, "hl_shown": (sh[i][0], sh[j][1])})
            if len(hits) >= limit:
                return hits
            pos = low.find(q, pos + len(q))
    return sorted(hits, key=lambda h: h["t"])


def next_clip_num(proj):
    return max((c.get("num", 0) for c in proj["clips"]), default=0) + 1


def add_clip(path, c, origin, progress=None, cancel=None):
    """Собрать новый клип по моменту c ({s, e, peak, score, zooms, parts, title, …})
    и добавить в project.json. origin — откуда клип («search», «candidate»)."""
    need_ffmpeg()
    prepare_sounds()
    proj = load_project(path)
    src = proj["source"]
    if not os.path.isfile(src):
        raise AutoClipError(f"❌ Не найдена исходная запись: {src}")
    segments = load_segments(proj)
    out_dir = os.path.dirname(proj["_path"])
    if not c.get("hook"):
        c["hook"] = decide_hook(c["s"], c["e"], proj.get("reaction") or [], segments, voice=clip_voice(src, c["s"], c["e"]),
                                threshold=proj.get("hook_threshold"),
                                cfg=dict(CONFIG, **proj.get("settings", {})))
    num = next_clip_num(proj)
    name = f"{num:02d}_{safe_name(c['title'])}.mp4"
    rec = make_clip_record(c, num, name)
    rec["origin"] = origin
    rec["overrides"].update({k: v for k, v in (c.get("overrides") or {}).items() if k in OVERRIDE_KEYS})
    cfg = clip_config(proj, rec)
    span = hook_span(rec, cfg)
    rec["hook"]["on"] = span is not None
    log(f"➕ Новый клип {name} ({fmt_time(c['s'])}–{fmt_time(c['e'])})")
    if progress:
        progress("рендер", 0, name)
    job = dict(c, hook=span)
    with tempfile.TemporaryDirectory(prefix="autoclip_r_") as tmp:
        rec["bleeps"] = render_clip(src, job, segments, proj["source_info"],
                                    os.path.join(out_dir, name), tmp, cfg, cancel)
    rec["timeline"] = job.get("timeline")
    rec["bleep_seq"] = job.get("bleep_seq")
    if rec["bleeps"] is None:
        raise AutoClipError("❌ ffmpeg не смог собрать клип.")
    rec["rendered"] = now_iso()
    rec["quiet_start"] = quiet_start(os.path.join(out_dir, name))
    rec["cover"] = make_cover(src, proj["source_info"], rec, proj.get("reaction") or [],
                              cover_path_for(out_dir, name), cfg, cancel)
    add_forecast(rec, segments)
    proj = load_project(path)                    # за время рендера проект могли поменять
    proj["clips"].append(rec)
    save_project(proj)
    write_report(proj)
    register_project(proj["_path"])
    if progress:
        progress("рендер", 100, name)
    return rec


def moment_at(proj, t, segments):
    """Момент вокруг места t в записи — по тем же правилам, что и автоматический:
    до места — pre секунд, после — post, длина 15–55 с, границы по фразам."""
    dur = proj["source_info"]["dur"]
    t = max(0.0, min(float(t), dur))
    words = all_words(segments)
    s, e = shape_clip(t, t - CONFIG["pre"], t + CONFIG["post"], words, dur)
    s, e = guard_edges(s, e, words)
    loud_z = proj.get("loud_z") or []
    reaction = proj.get("reaction") or []
    inside = [i for i in range(int(s), min(len(reaction), int(e)))]
    peak = max(inside, key=lambda i: reaction[i], default=t) if inside else t
    score = float(reaction[int(peak)]) if inside else 0.0
    return {"s": round(s, 2), "e": round(e, 2), "peak": float(peak), "score": score,
            "zooms": zoom_points(s, e, peak, loud_z) if loud_z else [],
            "zoom_auto": auto_zooms(s, e, reaction, None, proj.get("hook_threshold")),
            "parts": {}, "title": moment_title("", segments, s, e, peak), "reason": "",
            "marks": []}


def clip_from_search(path, t, progress=None, cancel=None):
    """«Клип отсюда»: клип вокруг найденного в расшифровке места."""
    proj = load_project(path)
    c = moment_at(proj, t, load_segments(proj))
    c["reason"] = f"из поиска по расшифровке, место {fmt_time(t)}"
    return add_clip(path, c, "search", progress, cancel)


def music_preview(path, ref, mcfg, out_path):
    """Готовый клип + выбранная музыка с текущей громкостью — быстро, без пережатия видео."""
    proj = load_project(path)
    clip = find_clip(proj, ref)
    src = os.path.join(os.path.dirname(proj["_path"]), clip["file"])
    music = check_music(mcfg)
    if not (music and os.path.isfile(src)):
        raise AutoClipError("❌ Нет клипа или трека для прослушивания.")
    total = _probe_dur(src)
    hd = 0.0
    if (clip.get("hook") or {}).get("on") and clip["hook"].get("start") is not None:
        hd = clip["hook"]["end"] - clip["hook"]["start"]
    try:
        segs = load_segments(proj)
        words = [dict(w, s=w["s"] + hd, e=w["e"] + hd)
                 for w in clip_words(segs, clip["start"], clip["end"])]
    except AutoClipError:
        words = []
    gain = music_gain(dict(music, _len=total), loudness(src))
    graph = (music_chain("[1:a]", total, music, gain, speech_spans(words)) +
             ";[0:a]aformat=sample_rates=48000:channel_layouts=stereo[voice];"
             "[voice][mus]amix=inputs=2:duration=first:normalize=0[aout]")
    p = run(["ffmpeg", "-y", "-v", "error", "-i", src, "-ss", f"{float(music.get('offset', 0)):.3f}",
             "-t", f"{total:.3f}", "-i", music["file"], "-filter_complex", graph,
             "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", out_path])
    if p.returncode != 0:
        raise AutoClipError("❌ Не получилось смешать музыку:\n" + p.stderr[-500:])
    return out_path


def load_segments(proj):
    path = proj.get("transcript", "")
    if not os.path.isfile(path):
        raise AutoClipError(f"❌ Нет расшифровки: {path}\n   Нарежь запись заново.")
    return drop_hallucinations(read_transcript(path))


PAUSE_MIN = 1.5        # «Сжать паузы»: паузы без речи длиннее этого…
PAUSE_KEEP = 0.3       # …вырезаются, тишины с каждой стороны остаётся столько


def pause_cuts(s, e, words, min_pause=PAUSE_MIN, keep=PAUSE_KEEP, voice=None, cuts=None):
    """Вырезки для «Сжать паузы»: паузы между словами внутри клипа длиннее min_pause,
    по keep тишины с каждой стороны. Голос без слов (смех, крик по voice) паузой не считается."""
    ws = sorted((w for w in words if w["e"] > s and w["s"] < e), key=lambda w: w["s"])
    marks = [(w["s"], w["e"]) for w in ws] + [(a, b) for a, b in voice or () if b > s and a < e]
    marks.sort()
    out = []
    end = None
    for a, b in marks:
        if end is not None and a - end > min_pause:
            x, y = end + keep, a - keep
            if y - x > 0.05 and not in_cuts(x, y, cuts or []):
                out.append([round(x, 2), round(y, 2)])
        end = b if end is None else max(end, b)
    return out


def merge_cuts(cuts):
    out = []
    for a, b in sorted([float(a), float(b)] for a, b in cuts):
        if out and a <= out[-1][1] + 0.01:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([round(a, 2), round(b, 2)])
    return out


def clip_voice(src, s, e):
    """Где в куске записи слышен голос (Silero): [(начало, конец)] во времени записи."""
    try:
        with tempfile.TemporaryDirectory(prefix="autoclip_v_") as tmp:
            w = os.path.join(tmp, "v.wav")
            p = run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s:.2f}", "-t", f"{e - s:.2f}", "-i", src,
                     "-map", "0:a:0", "-af", ASR_FILTER, "-ac", "1", "-ar", "16000", w])
            if p.returncode != 0:
                return []
            return [(a + s, b + s) for a, b in speech_regions(_read_wav(w))]
    except Exception:
        return []


def suggest_pause_cuts(path, ref, min_pause=PAUSE_MIN, keep=PAUSE_KEEP, start=None, end=None,
                       cuts=None, voice=None, segments=None):
    """«Сжать паузы» для клипа: (вырезки, на сколько секунд станет короче). Прежние вырезки
    (cuts, по умолчанию — у клипа) остаются, новые добавляются к ним."""
    proj = load_project(path)
    clip = find_clip(proj, ref)
    s = clip["start"] if start is None else float(start)
    e = clip["end"] if end is None else float(end)
    old = clip_cuts(clip) if cuts is None else [list(map(float, x)) for x in cuts]
    words = all_words(segments if segments is not None else load_segments(proj))
    if voice is None:
        voice = clip_voice(proj["source"], s, e) if os.path.isfile(proj["source"]) else []
    new = pause_cuts(s, e, words, min_pause, keep, voice, old)
    before = sum(b - a for a, b in keep_pieces(s, e, old))
    after = sum(b - a for a, b in keep_pieces(s, e, merge_cuts(old + new)))
    return merge_cuts(old + new), round(before - after, 1)


def split_point(t, s, e, words):
    """Где разбить клип у места t: в паузе между словами (слово не режем), по возможности
    поближе к t. None — подходящей паузы нет."""
    ws = sorted((w for w in words if w["e"] > s and w["s"] < e), key=lambda w: w["s"])
    gaps = [(max(s, a["e"]), min(e, b["s"])) for a, b in zip(ws, ws[1:]) if b["s"] - a["e"] >= 0.08]
    if not ws:
        return round(t, 2)
    best = None
    for a, b in gaps:
        if b - a < 0.05:
            continue
        x = min(max(t, a + min(0.15, (b - a) / 2)), b - min(0.15, (b - a) / 2))
        if best is None or abs(x - t) < abs(best - t):
            best = x
    return None if best is None else round(best, 2)


def split_clip(path, ref, t, progress=None, cancel=None):
    """«Разбить здесь»: клип делится на два у места t записи (граница — в паузе). Первый —
    этот же клип до границы, второй — новый клип со своими настройками (копия этих).
    Возвращает (первый, второй)."""
    proj = load_project(path)
    clip = find_clip(proj, ref)
    words = all_words(load_segments(proj))
    at = split_point(float(t), clip["start"], clip["end"], words)
    if at is None or at - clip["start"] < 3 or clip["end"] - at < 3:
        raise AutoClipError("❌ Здесь не разбить: каждая часть должна быть не короче 3 секунд "
                            "и граница — в паузе между словами.")
    cuts = clip_cuts(clip)
    ov = {k: v for k, v in (clip.get("overrides") or {}).items() if k not in ("title", "hook_at", "cuts")}
    second_cuts = [c for c in cuts if c[1] > at]
    if second_cuts:
        ov["cuts"] = [[max(a, at), b] for a, b in second_cuts]
    c2 = {"s": at, "e": clip["end"], "peak": min(max(clip["peak"], at), clip["end"]),
          "score": clip["score"], "parts": clip.get("score_parts", {}),
          "title": clip["title"], "reason": "вторая часть клипа " + str(clip["num"]),
          "zooms": [z for z in clip.get("zooms", []) if z > at], "overrides": ov}
    first_ov = {"cuts": [[a, min(b, at)] for a, b in cuts if a < at] or None} if cuts else None
    first = rebuild_clip(path, ref, None, at, first_ov, progress, cancel)
    second = add_clip(path, c2, "split", progress, cancel)
    return first, second


def rebuild_clip(path, ref, start=None, end=None, overrides=None, progress=None, cancel=None):
    """Пересобирает один клип по записи в project.json, без повторной расшифровки.
    start/end — новое начало/конец в секундах записи; overrides — личные настройки клипа
    (значение None убирает переопределение). Возвращает обновлённую запись клипа."""
    need_ffmpeg()
    proj = load_project(path)
    clip = find_clip(proj, ref)
    if clip["status"] == "rejected":
        raise AutoClipError("❌ Клип отклонён, его файл в корзине.")
    src = proj["source"]
    if not os.path.isfile(src):
        raise AutoClipError(f"❌ Не найдена исходная запись: {src}")
    dur = proj["source_info"]["dur"]
    s = clip["start"] if start is None else parse_time(start)
    e = clip["end"] if end is None else parse_time(end)
    s, e = max(0.0, s), min(dur, e)
    if e - s < 3:
        raise AutoClipError("❌ Клип получается короче 3 секунд.")
    for k, v in (overrides or {}).items():
        if k not in OVERRIDE_KEYS:
            raise AutoClipError(f"❌ Настройку «{k}» нельзя менять у отдельного клипа.")
        if v is None:
            clip["overrides"].pop(k, None)
        else:
            clip["overrides"][k] = v

    segments = load_segments(proj)
    cfg = clip_config(proj, clip)
    cuts = clip_cuts(clip, cfg)
    if timeline_len(clip_timeline(s, e, cuts)) < 3:
        raise AutoClipError("❌ После вырезок клип короче 3 секунд.")
    h0 = clip.get("hook") or {}
    if (s, e) != (clip["start"], clip["end"]) or h0.get("start") is None or \
            "cuts" in (overrides or {}) or in_cuts(h0["start"], h0["end"], cuts):
        # границы или вырезки поменялись — момент для хука ищем заново в оставшихся кусках
        if proj.get("reaction"):
            react = list(proj["reaction"])
            for a, b in cuts:                          # вырезанное хуком не станет (правило 5)
                for i in range(max(0, int(a)), min(len(react), int(math.ceil(b)))):
                    react[i] = 0.0
            clip["hook"] = decide_hook(s, e, react, segments,
                                       threshold=proj.get("hook_threshold"), cfg=cfg,
                                       voice=clip_voice(src, s, e))
            if clip["hook"].get("start") is not None and \
                    in_cuts(clip["hook"]["start"], clip["hook"]["end"], cuts):
                clip["hook"].update(auto=False, why="момент хука вырезан")
        elif clip.get("hook", {}).get("start") is not None and \
                not (s <= clip["hook"]["start"] and clip["hook"]["end"] <= e):
            clip["hook"].update(auto=False, why="момент хука оказался вне клипа")
    at = clip.get("overrides", {}).get("hook_at")
    if at and s <= float(at[0]) < float(at[1]) <= e and \
            not in_cuts(float(at[0]), float(at[1]), cuts):     # хук выбран вручную — внутри клипа
        clip["hook"] = dict(clip.get("hook") or {}, start=round(float(at[0]), 2),
                            end=round(float(at[1]), 2), auto=True, why="выбран вручную")
    span = hook_span(dict(clip, start=s, end=e), cfg)
    folder = os.path.dirname(proj["_path"])
    old_file = clip["file"]
    title = str(clip.get("overrides", {}).get("title") or "").strip()
    if title and title != clip["title"]:
        clip["file"] = f"{clip['num']:02d}_{safe_name(title)}.mp4"      # новое название — новое имя
    out = os.path.join(folder, clip["file"])
    log(f"🔁 Пересобираю {clip['file']} ({fmt_time(s)}–{fmt_time(e)})")
    if progress:
        progress("рендер", 0, clip["file"])
    t0 = time.time()
    job = {"s": s, "e": e, "zooms": clip["zooms"], "hook": span, "peak": clip.get("peak", s),
           **({"zoom_auto": clip["zoom_auto"]} if "zoom_auto" in clip else {})}
    with tempfile.TemporaryDirectory(prefix="autoclip_r_") as tmp:
        bl = render_clip(src, job, segments,
                         proj["source_info"], out, tmp, cfg, cancel,
                         on_frac=(lambda f: progress("рендер", f * 95, clip["file"])) if progress else None)
    if bl is None:
        raise AutoClipError("❌ ffmpeg не смог собрать клип.")
    clip.update(start=round(s, 2), end=round(e, 2), bleeps=bl, rendered=now_iso(),
                quiet_start=quiet_start(out), timeline=job.get("timeline"), bleep_seq=job.get("bleep_seq"))
    if clip["file"] != old_file:                       # переименовали: прежний файл и обложку — в корзину
        try:
            trash(os.path.join(folder, old_file))
        except AutoClipError:
            trash(out)                                 # прежний занят — новый убираем, клип цел
            raise AutoClipError(f"❌ Файл {old_file} занят другой программой — закрой его там и "
                                "пересобери ещё раз. Клип не тронут.")
        trash(cover_path_for(folder, old_file))
    if title:
        clip["title"] = title
        if clip.get("meta"):
            clip["meta"]["title"] = title
    clip["cover"] = make_cover(src, proj["source_info"], clip, proj.get("reaction") or [],
                               cover_path_for(os.path.dirname(proj["_path"]), clip["file"]),
                               cfg, cancel)
    clip["hook"]["on"] = span is not None
    add_forecast(clip, segments)
    log("   " + hook_text(clip))
    save_project(proj)
    write_report(proj)
    if progress:
        progress("рендер", 100, clip["file"])
    log(f"✅ Готово за {time.time() - t0:.1f} с")
    return clip


# ---------------- 10. все нарезки и еженедельная подборка ----------------

PROJECTS_INDEX = os.path.join(user_dir(), "нарезки.json")
WEEKLY_DIR = os.path.join(os.path.expanduser("~"), "Videos", "AutoClip подборки")
WEEKLY_FORMATS = {
    "vertical": {"name": "Вертикальная", "w": 1080, "h": 1920, "fps": 60, "kbps": 18000},
    "horizontal": {"name": "Горизонтальная", "w": 1920, "h": 1080, "fps": 60, "kbps": 12000},
}
FADE = 0.15          # затемнение на стыке: 0,15 с в чёрный + 0,15 с из чёрного


def known_projects():
    try:
        with open(PROJECTS_INDEX, encoding="utf-8") as f:
            data = json.load(f)
        return [p for p in data if isinstance(p, str)]
    except (OSError, ValueError):
        return []


def register_project(path):
    """Запоминает нарезку в общем списке — по нему подборка ищет клипы всех записей."""
    pp = os.path.abspath(project_path(path))
    items = [p for p in known_projects() if os.path.abspath(p) != pp]
    items.append(pp)
    tmp = PROJECTS_INDEX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PROJECTS_INDEX)


def _clip_date(c):
    """Когда клип в последний раз «стал интересен»: нарезан, одобрен или выложен."""
    dates = [c.get("created"), c.get("status_date")]
    dates += [p.get("date") for p in (c.get("published") or {}).values() if isinstance(p, dict)]
    return max((d for d in dates if d), default="")


def weekly_candidates(days=7, now=None):
    """Клипы «хороший» и «выложен» за последние days дней из всех нарезок,
    по убыванию оценки: [{"project", "id", "path", "title", "score", "dur", "date", "status"}]."""
    now = now or datetime.datetime.now()
    since = (now - datetime.timedelta(days=days)).isoformat(timespec="seconds")
    out = []
    for pp in known_projects():
        try:
            proj = load_project(pp)
        except (AutoClipError, OSError, ValueError):
            continue
        folder = os.path.dirname(proj["_path"])
        for c in proj["clips"]:
            path = os.path.join(folder, c["file"])
            date = _clip_date(c)
            if c["status"] in ("good", "published") and date >= since and os.path.isfile(path):
                h = c.get("hook") or {}
                hook = (h["end"] - h["start"]) if h.get("on") and h.get("start") is not None else 0
                out.append({"project": proj["_path"], "id": c["id"], "path": path,
                            "title": c["title"], "score": c["score"], "status": c["status"],
                            "dur": round(c["end"] - c["start"] + hook, 2), "date": date,
                            "source": os.path.basename(proj.get("source", ""))})
    return sorted(out, key=lambda x: -x["score"])


def _segment_filter(fmt, dur):
    """Кадр подборки из одного клипа + затемнение в начале и в конце."""
    W, H, fps = fmt["w"], fmt["h"], fmt["fps"]
    fade = (f"fade=t=in:d={FADE},fade=t=out:st={max(0.0, dur - FADE):.3f}:d={FADE}")
    if W > H:
        # горизонтально: клип по центру, по бокам — он же, размытый и притушенный
        v = (f"[0:v]fps={fps},split=2[bg][fg];"
             f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
             f"boxblur=30:3,eq=brightness=-0.12[bgb];"
             f"[fg]scale=-2:{H}:flags=lanczos[fgs];"
             f"[bgb][fgs]overlay=(W-w)/2:0,setsar=1,{fade},")
    else:
        v = (f"[0:v]fps={fps},scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,"
             f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,{fade},")
    v += ("scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
          "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv[v]")
    a = (f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,"
         f"afade=t=in:d={FADE},afade=t=out:st={max(0.0, dur - FADE):.3f}:d={FADE}[a]")
    return v + ";" + a


def _probe_dur(path):
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path])
    try:
        return float(p.stdout.strip())
    except ValueError:
        raise AutoClipError(f"❌ Не читается клип: {os.path.basename(path)}")


def build_compilation(paths, fmt="vertical", out_path=None, progress=None, cancel=None,
                      music=None):
    """Склеивает готовые клипы (в заданном порядке) в одну подборку с затемнением на стыках.
    fmt — "vertical" (1080×1920) или "horizontal" (1920×1080). music — один трек на всю
    подборку ({file, offset, volume, duck, fade}) или None. Возвращает путь к файлу."""
    global _ENCODER
    need_ffmpeg()
    if not paths:
        raise AutoClipError("❌ Нет клипов для подборки.")
    spec = WEEKLY_FORMATS[fmt]
    if out_path is None:
        os.makedirs(WEEKLY_DIR, exist_ok=True)
        stamp = datetime.date.today().isoformat()
        base = os.path.join(WEEKLY_DIR, f"подборка_{stamp}_{spec['name'].lower()}")
        out_path, n = base + ".mp4", 2
        while os.path.exists(out_path):              # старые подборки не перезаписываем
            out_path, n = f"{base}_{n}.mp4", n + 1
    log(f"🎞  Подборка: {len(paths)} клипов, {spec['name'].lower()} {spec['w']}×{spec['h']}")
    t0 = time.time()
    encs = _encoders(spec)
    with tempfile.TemporaryDirectory(prefix="autoclip_w_") as tmp:
        parts = []
        for i, src in enumerate(paths, 1):
            check_cancel(cancel)
            if progress:
                progress("подборка", (i - 1) / len(paths) * 100, os.path.basename(src))
            dur = _probe_dur(src)
            part = os.path.join(tmp, f"{i:03d}.mp4")
            base = ["ffmpeg", "-y", "-v", "error", "-i", os.path.abspath(src),
                    "-filter_complex", _segment_filter(spec, dur), "-map", "[v]", "-map", "[a]"]
            tail = COLOR_FLAGS + ["-fps_mode", "cfr", "-r", str(spec["fps"]), "-c:a", "aac",
                                  "-b:a", "320k", "-ar", "48000", part]
            names = [_ENCODER] if _ENCODER else list(encs)
            err = ""
            part_frac = ((lambda t, i=i, dur=dur: progress("подборка", (i - 1 + min(1, t / dur)) / len(paths) * 90,
                                                           os.path.basename(src)))
                         if progress else None)
            for name in names:
                p = run(base + encs[name] + tail, cancel=cancel, on_time=part_frac)
                if p.returncode == 0:
                    _ENCODER = name
                    break
                err = p.stderr
            else:
                raise AutoClipError("❌ ffmpeg не смог подготовить клип для подборки:\n" + err[-800:])
            parts.append(part)
        # все куски одного формата — склеиваем без пережатия
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w", encoding="utf-8") as f:
            for part in parts:
                f.write("file '" + part.replace("\\", "/").replace("'", "'\\''") + "'\n")
        tmp_out = os.path.join(tmp, "out.mp4")
        p = run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
                 "-c", "copy", "-movflags", "+faststart", tmp_out], cancel=cancel)
        if p.returncode != 0:
            raise AutoClipError("❌ Не получилось склеить подборку:\n" + p.stderr[-800:])
        music = check_music(music)
        if music:
            check_cancel(cancel)
            if progress:
                progress("подборка", 95, "музыка")
            total = _probe_dur(tmp_out)
            gain = music_gain(dict(music, _len=total), loudness(tmp_out))
            # слов у подборки под рукой нет — приглушаем под любым звуком клипов (sidechain)
            duck = ";[mus][sc]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=400[md]" \
                if music.get("duck", True) else ";[mus]anull[md]"
            graph = (music_chain("[1:a]", total, dict(music, duck=False), gain) +
                     ";[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[voice][sc]" +
                     duck + ";[voice][md]amix=inputs=2:duration=first:normalize=0[aout]")
            mixed = os.path.join(tmp, "music.mp4")
            p = run(["ffmpeg", "-y", "-v", "error", "-i", tmp_out,
                     "-ss", f"{float(music.get('offset', 0)):.3f}", "-t", f"{total:.3f}",
                     "-i", music["file"], "-filter_complex", graph, "-map", "0:v", "-map", "[aout]",
                     "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
                     "-movflags", "+faststart", mixed], cancel=cancel)
            if p.returncode != 0:
                raise AutoClipError("❌ Не получилось наложить музыку на подборку:\n" + p.stderr[-800:])
            tmp_out = mixed
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        replace_file(tmp_out, out_path)
    with open(os.path.splitext(out_path)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump({"created": now_iso(), "format": fmt, "clips": list(paths)}, f,
                  ensure_ascii=False, indent=1)
    if progress:
        progress("подборка", 100, os.path.basename(out_path))
    log(f"✅ Подборка готова за {time.time() - t0:.0f} с → {out_path}")
    return out_path


# ---------------- 11. публикация ----------------
# Программа только открывает страницу загрузки и кладёт описание в буфер.
# Кнопки на сайтах нажимает сам Гоша — никаких автокликов (правило 4).

UPLOAD_URLS = {
    "tiktok": "https://www.tiktok.com/tiktokstudio/upload",
    "youtube": "https://www.youtube.com/upload",
    # у Instagram в браузере нет прямой страницы публикации — «Создать» (+) в меню слева
    "instagram": "https://www.instagram.com/",
}
EDGE_PATHS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")


def find_edge():
    """Путь к Edge или None."""
    found = shutil.which("msedge")
    if found:
        return found
    for p in EDGE_PATHS:
        if os.path.isfile(p):
            return p
    if os.name == "nt":
        try:
            import winreg
            key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root, key) as k:
                        p = winreg.QueryValue(k, None)
                        if p and os.path.isfile(p):
                            return p
                except OSError:
                    continue
        except ImportError:
            pass
    return None


def browser_profile_dir():
    """Отдельный профиль Edge для AutoClip: войти в соцсети нужно один раз."""
    d = os.path.join(user_dir(), "браузер")
    os.makedirs(d, exist_ok=True)
    return d


def side_by_side(rect, n):
    """Делит прямоугольник экрана (x, y, w, h) на n окон рядом слева направо."""
    x, y, w, h = rect
    step = w // n
    return [(x + i * step, y, step, h) for i in range(n)]


def open_upload(platform, rect=None):
    """Открывает страницу загрузки площадки отдельным окном Edge в режиме приложения
    (rect — где поставить окно: x, y, ширина, высота). Нет Edge — браузер по умолчанию.
    Возвращает "edge" или "browser"."""
    if platform not in UPLOAD_URLS:
        raise AutoClipError(f"❌ Нет такой площадки: {platform}")
    url = UPLOAD_URLS[platform]
    edge = find_edge()
    if edge:
        cmd = [edge, f"--app={url}", f"--user-data-dir={browser_profile_dir()}",
               "--no-first-run", "--no-default-browser-check"]
        if rect:
            x, y, w, h = (int(v) for v in rect)
            cmd += [f"--window-position={x},{y}", f"--window-size={w},{h}"]
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | _NO_WINDOW
        subprocess.Popen(cmd, creationflags=flags, close_fds=True)
        return "edge"
    import webbrowser
    webbrowser.open(url)
    return "browser"


def mark_published(path, ref, platform, on=True, url=""):
    """Отметка «выложен на площадке» (дата и, по желанию, ссылка на пост).
    Первая отметка делает статус «выложен»; если снять все — снова «хороший»."""
    if platform not in PLATFORMS:
        raise AutoClipError(f"❌ Нет такой площадки: {platform}")
    proj = load_project(path)
    clip = find_clip(proj, ref)
    if clip["status"] == "rejected":
        raise AutoClipError("❌ Клип в корзине.")
    pub = dict(clip.get("published") or {})
    if on:
        old = pub.get(platform) or {}
        pub[platform] = {**old, "date": old.get("date") or now_iso(),
                         "url": (url or old.get("url") or "").strip()}
    else:
        pub.pop(platform, None)
    clip["published"] = pub
    if pub and clip["status"] != "published":
        clip["status"], clip["status_date"] = "published", now_iso()
    elif not pub and clip["status"] == "published":
        clip["status"], clip["status_date"] = "good", now_iso()
    save_project(proj)
    write_report(proj)
    return clip


# ---------------- 12. слежка за папкой OBS ----------------

VIDEO_EXT = (".mp4", ".mkv", ".mov", ".flv", ".ts", ".webm")
RECORDINGS_LOG = os.path.join(user_dir(), "записи.json")
STABLE_SECONDS = 10.0        # запись дописана, если размер не меняется столько секунд


def _read_ini(path):
    """Простое чтение ini OBS: {секция: {ключ: значение}} (configparser спотыкается на BOM)."""
    data, sec = {}, None
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    sec = data.setdefault(line[1:-1], {})
                elif "=" in line and sec is not None:
                    k, v = line.split("=", 1)
                    sec[k.strip()] = v.strip()
    except OSError:
        pass
    return data


def find_obs_record_dir():
    """Папка, куда OBS пишет записи (из настроек текущего профиля OBS) или None."""
    base = os.path.join(os.environ.get("APPDATA", ""), "obs-studio")
    user = _read_ini(os.path.join(base, "user.ini")) or _read_ini(os.path.join(base, "global.ini"))
    prof = user.get("Basic", {}).get("ProfileDir")
    if not prof:
        return None
    ini = _read_ini(os.path.join(base, "basic", "profiles", prof, "basic.ini"))
    mode = ini.get("Output", {}).get("Mode", "Simple")
    path = (ini.get("AdvOut", {}).get("RecFilePath") if mode == "Advanced"
            else ini.get("SimpleOutput", {}).get("FilePath"))
    if path:
        path = os.path.normpath(path.replace("\\\\", "\\"))
        return path if os.path.isdir(path) else None
    return None


def load_recordings_log():
    try:
        with open(RECORDINGS_LOG, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_recording_state(path, state):
    """Что решили про запись: offered / cut / declined / short — второй раз не спрашиваем."""
    data = load_recordings_log()
    data[os.path.normcase(os.path.abspath(path))] = {"state": state, "date": now_iso()}
    tmp = RECORDINGS_LOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, RECORDINGS_LOG)


def recording_state(path):
    return (load_recordings_log().get(os.path.normcase(os.path.abspath(path))) or {}).get("state")


def new_recordings(folder, since):
    """Видео в папке OBS, появившиеся после since (время, сек) и ещё не разобранные."""
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    decided = load_recordings_log()
    for n in names:
        p = os.path.join(folder, n)
        if not n.lower().endswith(VIDEO_EXT) or not os.path.isfile(p):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        if st.st_mtime >= since and \
                os.path.normcase(os.path.abspath(p)) not in decided:
            out.append(p)
    return sorted(out)


class GrowthTracker:
    """Следит, дописал ли OBS файл: размер не меняется STABLE_SECONDS секунд."""

    def __init__(self, stable=STABLE_SECONDS):
        self.stable = stable
        self.seen = {}               # путь → (размер, когда размер последний раз менялся)

    def update(self, path, now=None):
        """Отметить текущий размер. True — файл перестал расти и уже читается."""
        now = time.time() if now is None else now
        try:
            size = os.path.getsize(path)
        except OSError:
            self.seen.pop(path, None)
            return False
        last = self.seen.get(path)
        if last is None or last[0] != size:
            self.seen[path] = (size, now)
            return False
        return size > 0 and now - last[1] >= self.stable

    def forget(self, path):
        self.seen.pop(path, None)


def recording_info(path):
    """Длительность и число меток — для вопроса «Нарезать?». None — файл ещё не читается."""
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
             "default=nw=1:nk=1", path])
    try:
        dur = float(p.stdout.strip())
    except ValueError:
        return None
    return {"dur": dur, "marks": len(read_markers(path))}


# ---------------- main ----------------

def safe_name(s):
    s = s.replace("*", "＊")              # звёздочку Windows в имени не пускает — маска мата «е＊ать»
    s = re.sub(r"[\\/:*?\"<>|\n\r\t]+", "", s).strip()
    s = re.sub(r"\s+", "_", s)
    return s[:50] or "clip"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Нарезка стрима на клипы для TikTok/Shorts/Reels")
    ap.add_argument("video", nargs="?",
                    help="путь к видео (для --rebuild можно папку _clips или project.json)")
    ap.add_argument("--clips", type=int, help="сколько клипов")
    ap.add_argument("--llm", choices=["auto", "ollama", "anthropic", "none"])
    ap.add_argument("--build", choices=list(BUILD_MODES), help="сборка: auto, full, background")
    ap.add_argument("--retranscribe", action="store_true", help="расшифровать заново, без кэша")
    ap.add_argument("--model", help="модель Whisper (large-v3 / medium / small)")
    ap.add_argument("--subs", action=argparse.BooleanOptionalAction, default=None)
    ap.add_argument("--zoom", action=argparse.BooleanOptionalAction, default=None)
    ap.add_argument("--bleep", action=argparse.BooleanOptionalAction, default=None)
    ap.add_argument("--sub-pos", choices=list(SUB_POSITIONS), help="где субтитры")
    ap.add_argument("--safe-zone", action=argparse.BooleanOptionalAction, default=None,
                    help="не заходить субтитрами под кнопки соцсетей")
    ap.add_argument("--nick", action=argparse.BooleanOptionalAction, default=None,
                    help="ник в углу; с --rebuild — только для этого клипа")
    ap.add_argument("--hook", action=argparse.BooleanOptionalAction, default=None,
                    help="хук в начале; с --rebuild — только для этого клипа")
    ap.add_argument("--sound", help="звук на мат: перелистывание / буп / свист / бип / тишина / свой файл")
    ap.add_argument("--analyze-only", action="store_true", help="только найти моменты, без рендера")
    ap.add_argument("--rebuild", metavar="КЛИП",
                    help="пересобрать один клип (номер или id) без повторной расшифровки")
    ap.add_argument("--start", help="для --rebuild: новое начало в записи (сек или 1:02:10)")
    ap.add_argument("--end", help="для --rebuild: новый конец в записи")
    args = ap.parse_args()

    video = args.video
    if not video:
        video = input("Перетащи сюда видео и нажми Enter: ").strip().strip('"').strip("'")
    if not os.path.exists(video):
        log(f"❌ Файл не найден: {video}")
        sys.exit(1)
    migrate_user_data()
    flags = {"subs": args.subs, "zoom": args.zoom, "bleep": args.bleep,
             "bleep_sound": args.sound, "hook": args.hook, "safe_zone": args.safe_zone, "nick": args.nick,
             "sub_y": SUB_POSITIONS[args.sub_pos] if args.sub_pos else None}
    try:
        if args.rebuild:
            # флаги становятся личными настройками этого клипа
            rebuild_clip(video, args.rebuild, args.start, args.end,
                         {k: v for k, v in flags.items() if v is not None})
            return
        if args.clips:
            CONFIG["clips"] = args.clips
        if args.llm:
            CONFIG["llm"] = args.llm
        if args.build:
            CONFIG["build_mode"] = args.build
        if args.retranscribe:
            CONFIG["retranscribe"] = True
        if args.model:
            CONFIG["whisper_model"] = args.model
        CONFIG.update({k: v for k, v in flags.items() if v is not None})
        process(video, analyze_only=args.analyze_only)
    except AutoClipError as e:
        log(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        log("⛔ Остановлено.")
        sys.exit(1)


STAGES = ("звук", "расшифровка", "модель", "поиск", "рендер")


def process(video, analyze_only=False, progress=None, cancel=None):
    """Вся обработка одного видео (см. _process) в выбранном режиме сборки:
    «на полную» — несколько клипов сразу, «фоновый» — по одному, с пониженным приоритетом."""
    global _proc_priority
    mode, why = resolve_build_mode()
    workers = max(1, int(CONFIG.get("parallel_clips", 3))) if mode == "full" else 1
    log(f"⚙️  Сборка: {BUILD_MODES[mode].lower()} — {why}"
        + (f", клипов сразу: {workers}" if mode == "full" else ", по одному, тихо"))
    if mode == "background":
        _proc_priority = _LOW_PRIORITY
        _set_self_priority(True)
    try:
        return _process(video, analyze_only, progress, cancel, workers)
    finally:
        if mode == "background":
            _proc_priority = 0
            _set_self_priority(False)


def _process(video, analyze_only=False, progress=None, cancel=None, workers=1):
    """Вся обработка одного видео. Возвращает папку с клипами (или None).
    progress(этап, процент 0–100 внутри этапа, сообщение) — этапы из STAGES;
    cancel — threading.Event или функция; при остановке — исключение Cancelled.
    Каждая нарезка идёт в новую папку («_clips», «_clips_2», …); прошлые нарезки
    не трогаются."""
    def prog(stage, pct, msg=""):
        if progress:
            progress(stage, pct, msg)

    need_ffmpeg()
    prepare_sounds()
    _warned.clear()
    if CONFIG.get("clip_length", "normal") != "normal":
        apply_length()                      # «обычно» — значения CONFIG как есть
    try:
        import numpy  # noqa: F401
    except ImportError:
        raise AutoClipError("❌ Не установлен numpy. Запусти install.bat.")

    t_start = time.time()
    vinfo = probe(video)
    log(f"🎬 {os.path.basename(video)} — {fmt_time(vinfo['dur'])}, {vinfo['w']}x{vinfo['h']}")
    preset = get_preset(CONFIG["preset"])
    if vinfo["w"] * preset["h"] != vinfo["h"] * preset["w"]:
        log(f"⚠️  Пропорции записи не как у клипа — возьму середину кадра "
            f"и приведу к {preset['w']}x{preset['h']}.")
    elif (vinfo["w"], vinfo["h"]) != (preset["w"], preset["h"]):
        log(f"ℹ️  Клипы будут {preset['w']}x{preset['h']}.")
    if abs(vinfo["fps"] - preset["fps"]) > 0.01:
        log(f"⚠️  В записи {vinfo['fps']:g} кадров/с, клипы будут {preset['fps']}. Плавнее от "
            f"этого не станет — лучше сразу писать в OBS {preset['fps']} кадров/с.")

    out_dir = new_clip_dir(video)                # каждая нарезка — в свою папку

    timings = []

    def mark(name, t0):
        timings.append((name, round(time.time() - t0, 1)))
        return time.time()

    with tempfile.TemporaryDirectory(prefix="autoclip_") as tmp:
        wav = os.path.join(tmp, "audio.wav")
        t = time.time()
        prog("звук", 0, "достаю звук")
        extract_audio(video, wav, cancel)
        loud = loudness_per_second(wav)
        voice = speech_regions(_read_wav(wav))      # где слышен голос — края клипов не режут его
        prog("звук", 100)
        t = mark("звук и громкость", t)
        prog("расшифровка", 0)
        segments, cache = transcribe(video, vinfo["dur"], tmp, progress, cancel,
                                     fresh=CONFIG.get("retranscribe", False))
        segments = drop_hallucinations(segments)
        prog("расшифровка", 100)
        t = mark(f"расшифровка ({WHISPER_DEVICE})", t)
    marks = read_markers(video) if CONFIG["marks"] else []
    if CONFIG["marks"]:
        log(f"📍 Меток из OBS: {len(marks)}" + (f" ({getattr(read_markers, 'how', '')}) — эти моменты "
                                                  "пойдут первыми" if marks else ""))
    n_words = sum(len(s["words"]) for s in segments)
    n_mat = sum(is_profane(w["w"]) for s in segments for w in s["words"])
    log(f"   слов: {n_words}, из них мата: {n_mat}")

    check_cancel(cancel)
    mode = pick_llm(CONFIG["llm"])
    moments = []
    prog("модель", 0)
    if mode != "none":
        log(f"🤖 Оцениваю моменты через {mode}...")
        try:
            import forecast
            examples = forecast.taste_examples()
        except Exception:
            examples = []
        if examples:
            log(f"   примеры твоего вкуса: {len(examples)}")
        moments = llm_moments(segments, mode, progress, cancel, examples)
        log(f"   модель предложила {len(moments)} моментов")
    else:
        log("🤖 Без языковой модели — ищу по звуку и речи.")
    prog("модель", 100)
    t = mark("языковая модель", t)

    prog("поиск", 0)
    proj = new_project(video, vinfo, out_dir, cache)
    proj["marks"] = marks

    # речь и восклицания — по голосу Гоши (если есть его дорожка), громкость — по общему звуку
    smooth, loud_z, parts = score_timeline(loud, speaker_segments(segments, "me"), moments)
    proj["loud_z"] = [round(float(x), 2) for x in loud_z]   # для «Клип отсюда»: точки зума
    want = CONFIG["auto_max"] if CONFIG.get("clips_mode") == "auto" else CONFIG["clips"]
    found = pick_clips(smooth, loud_z, segments, moments, vinfo["dur"], parts, marks=marks, voice=voice,
                       limit=int(want) + int(CONFIG.get("max_candidates", 20)))
    thr = CONFIG["auto_min_score"] if mode != "none" else CONFIG.get("auto_min_score_plain", 1.7)
    clips, cands = split_clips(found, dict(CONFIG, auto_min_score=thr))
    proj["candidates"] = [candidate_record(c, i, segments) for i, c in enumerate(cands, 1)]
    if CONFIG.get("clips_mode") == "auto":
        log(f"   режим «Авто»: оценка от {thr:g}, не больше {CONFIG['auto_max']}")
    if not clips and cands:
        log("   выше порога моментов нет — все найденные в кандидатах")
    if not clips and not cands:
        prog("поиск", 100)
        log("😕 Ярких моментов не нашлось. Попробуй уменьшить min_len или подключить модель.")
        return None
    log(f"✂️  Нашёл {len(clips)} клипов" + (f", ещё {len(cands)} — кандидаты" if cands else ""))

    reaction = reaction_curve(parts)
    thr = hook_threshold(reaction)
    proj["reaction"] = [round(float(x), 2) for x in reaction]   # для пересборки со сдвигом
    proj["hook_threshold"] = round(thr, 2)
    for i, c in enumerate(clips, 1):
        check_cancel(cancel)
        c["hook"] = decide_hook(c["s"], c["e"], reaction, segments, parts, thr, voice=voice)
        c["zoom_auto"] = auto_zooms(c["s"], c["e"], reaction, parts, thr)
        h = c["hook"]
        if h["auto"] and mode != "none" and tri(CONFIG["hook"]) != "off":
            prog("поиск", i / len(clips) * 100, "проверяю хуки моделью")
            spoils, why = llm_hook_spoils(text_between(segments, c["s"], c["e"]),
                                          text_between(segments, h["start"], h["end"]), mode)
            if spoils:
                h.update(auto=False, why="модель: тизер раскроет развязку" +
                         (f" — {why}" if why else ""))
        if mode != "none":
            prog("поиск", i / len(clips) * 100, "название и хэштеги")
            text = text_between(segments, c["s"], c["e"])
            c["meta"] = llm_clip_meta(text, mode) if text.strip() else None
            if c["meta"] and c["meta"]["title"] and not title_fits(c["meta"]["title"], text):
                c["meta"]["title"] = moment_title("", segments, c["s"], c["e"], c["peak"])
            if c["meta"] and c["meta"]["title"]:
                c["title"] = c["meta"]["title"]          # и имя файла станет понятным
    prog("поиск", 100)
    t = mark("поиск моментов", t)

    if analyze_only:
        process.last = {"clips": clips, "candidates": cands, "segments": segments}
        for i, c in enumerate(clips, 1):
            log(f"   {i:02d}. {fmt_time(c['s'])}–{fmt_time(c['e'])} ({c['e'] - c['s']:.0f} с), "
                f"оценка {c['score']:.1f} — {c['title']}")
            log("       " + hook_text({"start": c["s"], "hook": dict(
                c["hook"], on=c["hook"]["auto"] and tri(CONFIG["hook"]) != "off")}))
        return out_dir

    os.makedirs(out_dir, exist_ok=True)
    log(f"📁 Клипы будут в папке {os.path.basename(out_dir)}")
    proj["settings"] = {k: CONFIG[k] for k in RENDER_KEYS if k in CONFIG}
    proj["settings"]["preset"] = preset          # сам пресет: пересборка не зависит от списка
    proj["run"] = {"date": now_iso(), "timings": timings}
    save_project(proj)
    register_project(proj["_path"])

    import threading
    lock = threading.Lock()
    done = [0]
    fracs = {}

    def frac_of(num, name):
        def f(x):
            with lock:
                fracs[num] = x
                prog("рендер", sum(fracs.values()) / len(clips) * 100, name)
        return f

    def build(num, c):
        """Один клип: рендер, тихое начало, обложка, прогноз. Своя временная папка —
        клипы можно собирать одновременно."""
        check_cancel(cancel)
        name = f"{num:02d}_{safe_name(c['title'])}.mp4"
        log(f"   [{num}/{len(clips)}] {name}")
        rec = make_clip_record(c, num, name)
        cfg = clip_config(proj, rec)
        span = hook_span(rec, cfg)
        rec["hook"]["on"] = span is not None
        job = dict(c, hook=span)
        with tempfile.TemporaryDirectory(prefix="autoclip_r_") as tmp:
            rec["bleeps"] = render_clip(video, job, segments, vinfo,
                                        os.path.join(out_dir, name), tmp, cfg, cancel,
                                        on_frac=frac_of(num, name))
        rec["bleep_seq"] = job.get("bleep_seq")
        if rec["bleeps"] is None:
            return None
        rec["rendered"] = now_iso()
        rec["quiet_start"] = quiet_start(os.path.join(out_dir, name))
        rec["cover"] = make_cover(video, vinfo, rec, reaction,
                                  cover_path_for(out_dir, name), cfg, cancel)
        add_forecast(rec, segments)
        with lock:
            proj["clips"].append(rec)
            proj["clips"].sort(key=lambda r: r["num"])
            save_project(proj)                   # после каждого клипа: остановка ничего не теряет
            done[0] += 1
            fracs[num] = 1.0
            prog("рендер", sum(fracs.values()) / len(clips) * 100, name)
        return rec

    prog("рендер", 0)
    if workers <= 1:
        for num, c in enumerate(clips, 1):
            build(num, c)
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(build, num, c) for num, c in enumerate(clips, 1)]
            try:
                for f in futures:
                    f.result()                   # ошибка или остановка — сразу наверх
            except BaseException:
                for f in futures:
                    f.cancel()                   # ещё не начатые — не начинать
                raise                            # начатые сами остановятся по cancel
    prog("рендер", 100)

    mark("рендер клипов", t)
    proj["run"].update(timings=timings, minutes=round((time.time() - t_start) / 60, 2),
                       whisper=WHISPER_DEVICE, encoder=_ENCODER)
    save_project(proj)
    write_report(proj)
    log(f"✅ Готово за {(time.time() - t_start) / 60:.1f} мин → {out_dir}")
    return out_dir


if __name__ == "__main__":
    main()
