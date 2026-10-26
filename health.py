# -*- coding: utf-8 -*-
"""Надёжность (Патч 5, P3): ресурсы компьютера перед нарезкой и во время неё, сторож для зависших
процессов, освобождение видеопамяти, экран «Состояние системы».

У Гоши под тяжёлой нагрузкой видеодрайвер изредка перезапускается (nvlddmkm 153) — поэтому
Whisper и модель Ollama не держат видеопамять одновременно с кодированием клипов: после своего
этапа они её отдают."""

import ctypes
import json
import os
import shutil
import subprocess
import time

import autoclip as A

RAM_MIN_MB = 2500            # свободной памяти меньше — подождать
VRAM_WHISPER_MB = 3500       # Whisper large-v3 на видеокарте (float16) — примерно столько
GPU_HOT_C = 85               # видеокарта горячее — подождать, пусть остынет
DISK_MIN_GB = 3.0            # места на диске нарезки меньше — не начинать
WAIT_MAX_S = 180             # ждать ресурсы не дольше


def _flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def gpu():
    """Видеокарта NVIDIA: {"used", "total", "free", "temp", "util"} (МБ, °C, %) или None."""
    try:
        p = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10,
                           creationflags=_flags())
        used, total, temp, util = [float(x) for x in p.stdout.strip().splitlines()[0].split(",")]
        return {"used": used, "total": total, "free": total - used, "temp": temp, "util": util}
    except Exception:
        return None


def gpu_name():
    """Название видеокарты NVIDIA («NVIDIA GeForce RTX 5080») или None — карты нет или нет драйвера."""
    try:
        p = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True,
                           text=True, timeout=10, creationflags=_flags())
        name = p.stdout.strip().splitlines()[0].strip()
        return name or None
    except Exception:
        return None


def ram():
    """Память: {"free", "total"} в МБ или None."""
    if os.name != "nt":
        return None

    class MEM(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MEM()
    m.dwLength = ctypes.sizeof(MEM)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None
    return {"free": m.ullAvailPhys / 2 ** 20, "total": m.ullTotalPhys / 2 ** 20}


def disk_free_gb(path):
    try:
        d = path
        while d and not os.path.exists(d):
            d = os.path.dirname(d)
        return shutil.disk_usage(d or ".").free / 2 ** 30
    except OSError:
        return None


def problems(out_dir=None, need_whisper=True, g=None, r=None):
    """Что мешает нарезать прямо сейчас: [(насколько: "wait" | "stop", текст)]."""
    out = []
    g = gpu() if g is None else g
    r = ram() if r is None else r
    if r and r["free"] < RAM_MIN_MB:
        out.append(("wait", f"мало свободной памяти: {r['free'] / 1024:.1f} ГБ"))
    if g:
        if g["temp"] >= GPU_HOT_C:
            out.append(("wait", f"видеокарта горячая: {g['temp']:.0f} °C"))
        if need_whisper and g["free"] < VRAM_WHISPER_MB:
            out.append(("wait", f"мало видеопамяти: свободно {g['free'] / 1024:.1f} ГБ"))
    if out_dir:
        free = disk_free_gb(out_dir)
        if free is not None and free < DISK_MIN_GB:
            out.append(("stop", f"мало места на диске: {free:.1f} ГБ"))
    return out


def wait_resources(out_dir=None, need_whisper=True, cancel=None, log=None, max_s=WAIT_MAX_S, sleep=10.0):
    """Перед тяжёлым этапом: мало памяти / горячо — подождать (до max_s). Возвращает оставшиеся
    проблемы (пусто — можно). Места на диске нет — AutoClipError сразу."""
    t0 = time.time()
    told = False
    while True:
        ps = problems(out_dir, need_whisper)
        stops = [t for kind, t in ps if kind == "stop"]
        if stops:
            raise A.AutoClipError("❌ " + "; ".join(stops) + ". Освободи место и нарежь снова.")
        if not ps or time.time() - t0 >= max_s:
            return [t for _, t in ps]
        if log and not told:
            log("   ⏳ жду ресурсы: " + "; ".join(t for _, t in ps))
            told = True
        A.check_cancel(cancel)
        time.sleep(sleep)


def free_ollama(model=None):
    """Выгрузить модель Ollama из видеопамяти сразу после её этапа (keep_alive: 0)."""
    model = model or A.CONFIG.get("ollama_model")
    if not model:
        return False
    try:
        A._http_json(A.CONFIG["ollama_url"] + "/api/generate", {"model": model, "keep_alive": 0}, {}, timeout=15)
        return True
    except Exception:
        return False


def free_whisper(model):
    """Отдать видеопамять Whisper: модель удаляется, сборщик мусора — сразу."""
    import gc
    try:
        m = getattr(model, "model", None)
        if m is not None and hasattr(m, "unload_model"):
            m.unload_model()
    except Exception:
        pass
    del model
    gc.collect()


# ---------- экран «Состояние системы» ----------

def _ffmpeg_version():
    try:
        p = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10, creationflags=_flags())
        return p.stdout.splitlines()[0].replace("ffmpeg version ", "").split(" Copyright")[0]
    except Exception:
        return None


def _nvenc_ok():
    try:
        p = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
                            "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, text=True, timeout=30,
                           creationflags=_flags())
        return p.returncode == 0
    except Exception:
        return False


def _cuda_devices():
    try:
        A._windows_cuda_dlls()
        import ctranslate2
        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


def status():
    """Всё о системе для экрана «Состояние системы»: [(что, ок ли: True/False/None, текст)]."""
    out = []
    v = _ffmpeg_version()
    out.append(("ffmpeg", bool(v), v or "не найден — запусти install.bat"))
    out.append(("Видеокодек NVENC", _nvenc_ok() if v else False,
                "работает" if v and _nvenc_ok() else "нет — клипы будут кодироваться процессором (медленнее)"))
    n = _cuda_devices()
    out.append(("Whisper на видеокарте (CUDA)", n > 0, f"видеокарт: {n}" if n else "нет — расшифровка на процессоре"))
    g = gpu()
    out.append(("Видеокарта", None if g is None else g["temp"] < GPU_HOT_C,
                "nvidia-smi не отвечает" if g is None else
                f"память {g['used'] / 1024:.1f} из {g['total'] / 1024:.1f} ГБ, {g['temp']:.0f} °C, загрузка {g['util']:.0f}%"))
    r = ram()
    if r:
        out.append(("Память", r["free"] >= RAM_MIN_MB, f"свободно {r['free'] / 1024:.1f} из {r['total'] / 1024:.1f} ГБ"))
    alive = A._ollama_alive()
    models = A.ollama_models() if alive else []
    out.append(("Ollama", bool(alive and models),
                ("модели: " + ", ".join(models[:4])) if models else ("запущена, моделей нет" if alive else "не запущена")))
    try:
        import telegram_bot
        tg = telegram_bot.is_connected()
    except Exception:
        tg = False
    out.append(("Telegram", tg, "подключён" if tg else "не подключён (необязательно)"))
    for name, path in (("Место: папка для клипов", A.CONFIG.get("clips_dir") or ""),
                       ("Место: папка программы", A.SCRIPT_DIR)):
        if path:
            free = disk_free_gb(path)
            out.append((name, None if free is None else free >= DISK_MIN_GB,
                        "—" if free is None else f"свободно {free:.0f} ГБ ({path})"))
    last = last_recording()
    if last:
        try:
            t = A.audio_tracks(last)
            out.append(("Дорожки в последней записи", t >= 3,
                        f"{os.path.basename(last)}: {t} — " + ("микрофон и Discord отдельно" if t >= 3 else
                                                              "только общий звук (в OBS можно включить дорожки 2 и 3)")))
        except Exception:
            pass
    return out


def last_recording():
    """Последняя запись, о которой знает программа (по списку записей OBS)."""
    try:
        with open(A.RECORDINGS_LOG, encoding="utf-8") as f:
            data = json.load(f)
        paths = [p for p in (data.keys() if isinstance(data, dict) else []) if os.path.isfile(p)]
        return max(paths, key=os.path.getmtime) if paths else None
    except (OSError, ValueError):
        return None
