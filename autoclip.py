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
    "clips": 10,              # сколько клипов сделать
    "min_len": 15.0,          # мин. длина клипа, сек
    "max_len": 55.0,          # макс. длина клипа, сек
    "pre": 14.0,              # сколько секунд взять ДО пика
    "post": 7.0,              # сколько секунд взять ПОСЛЕ пика
    "min_gap": 8.0,           # мин. зазор между клипами, сек

    # --- Whisper ---
    "whisper_model": "large-v3",   # large-v3 / medium / small
    "language": "ru",

    # --- языковая модель для оценки моментов ---
    # auto = Ollama, если запущена; иначе Claude API, если задан ANTHROPIC_API_KEY; иначе без неё
    "llm": "auto",                  # auto / ollama / anthropic / none
    "ollama_model": "qwen2.5:14b",
    "ollama_url": "http://localhost:11434",
    "anthropic_model": "claude-haiku-5-5",

    # --- субтитры ---
    "subs": True,
    "sub_font": "Arial Black",
    "sub_size": 82,
    "sub_y": 0.50,            # высота субтитров: 0 = верх кадра, 1 = низ (0.5 — стык вебки и игры)
    "sub_max_words": 3,
    "sub_max_chars": 18,
    "sub_uppercase": True,

    # --- зум ---
    "zoom": True,
    "zoom_amount": 0.18,      # +18% при зуме
    "zoom_focus_y": 0.35,     # куда зумить по вертикали: 0 = верх (вебка), 0.5 = центр, 1 = низ
    "max_zooms": 3,           # макс. зумов на клип

    # --- мат ---
    "bleep": True,
    "bleep_soft": True,       # запикивать ещё и «сука», «хер», «мудак», «пидор» и т.п.
    # звук поверх мата: перелистывание / буп / свист / тишина / бип —
    # или имя своего файла из папки «звуки» (mp3, wav, ogg...)
    "bleep_sound": "перелистывание",
    "bleep_volume": 1.0,      # 1.0 = как есть, 0.5 = тише, 1.5 = громче
    "bleep_pad": 0.06,        # запас вокруг слова, сек

    # --- экспорт ---
    "preset": "TikTok 1080p60",   # имя пресета из load_presets()
}
# ======================================================


# ---------------- утилиты ----------------

def log(msg):
    print(msg, flush=True)


def fmt_time(sec):
    sec = max(0, int(sec))
    return f"{sec // 3600:d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


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


def run(cmd, cwd=None, quiet=True, cancel=None):
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
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
    if p.returncode != 0 and not quiet:
        log(p.stderr[-3000:])
    return p


def need_ffmpeg():
    # ffmpeg.exe / ffprobe.exe можно просто положить рядом со скриптом
    here = os.path.dirname(os.path.abspath(__file__))
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


# ---------------- 1. звук ----------------

def extract_audio(video, wav, cancel=None):
    log("🔊 Достаю звук...")
    p = run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", wav], quiet=False, cancel=cancel)
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


def drop_hallucinations(segments):
    """Убирает фразы, которые Whisper выдумал, а не услышал."""
    out = []
    for seg in segments:
        text = re.sub(r"[^\w\s]", "", seg["text"].lower().replace("ё", "е")).strip()
        if text and _HALLUCINATIONS.fullmatch(text):
            continue
        out.append(seg)
    return out


def transcribe(wav, cache_path, dur, progress=None, cancel=None):
    if os.path.exists(cache_path):
        log("📝 Расшифровка уже есть, беру из кэша.")
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    _windows_cuda_dlls()
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise AutoClipError("❌ Не установлен faster-whisper. Запусти install.bat.")

    global WHISPER_DEVICE
    name = CONFIG["whisper_model"]
    model = None
    for device, ctype in (("cuda", "float16"), ("cpu", "int8")):
        try:
            log(f"🧠 Загружаю Whisper {name} ({device})... первый раз скачается ~3 ГБ")
            model = WhisperModel(name, device=device, compute_type=ctype)
            WHISPER_DEVICE = f"{device} {ctype}"
            if device == "cpu":
                log("⚠️  Видеокарта не подхватилась, считаю на процессоре — будет в разы медленнее.")
            break
        except Exception as e:
            log(f"   не вышло на {device}: {e}")
    if model is None:
        raise AutoClipError("❌ Whisper не запустился.")

    log("📝 Расшифровываю речь (на 3 часа записи — примерно 10–25 минут на видеокарте)...")
    t0 = time.time()
    try:
        # звук отдаём массивом: так faster-whisper не зависит от версии PyAV
        segments, _info = model.transcribe(
            _read_wav(wav),
            language=CONFIG["language"],
            word_timestamps=True,
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=False,
            initial_prompt="Запись игрового стрима. Разговорная речь, сленг, ругательства "
                           "записываются полностью, как произносятся, без звёздочек.",
        )
        result = []
        last_print = 0
        for s in segments:
            check_cancel(cancel)
            words = [{"s": round(w.start, 2), "e": round(w.end, 2), "w": w.word.strip()}
                     for w in (s.words or []) if w.word.strip()]
            result.append({"s": round(s.start, 2), "e": round(s.end, 2),
                           "text": s.text.strip(), "words": words})
            pct = min(100, s.end / dur * 100)
            if progress:
                progress("расшифровка", pct, f"{fmt_time(s.end)} из {fmt_time(dur)}")
            if s.end - last_print > 120:
                last_print = s.end
                log(f"   {fmt_time(s.end)} из {fmt_time(dur)} ({pct:.0f}%)")
    except AutoClipError:
        raise
    except Exception as e:
        raise AutoClipError(f"❌ Ошибка расшифровки: {e}\n"
                            "   Если ошибка про cublas/cudnn — запусти install.bat ещё раз.")

    log(f"   готово за {(time.time() - t0) / 60:.1f} мин")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    return result


# ---------------- 3. мат ----------------

_PFX = (r"(?:за|на|по|от|отъ|оть|у|вы|при|до|объ|вз|въ|разъ|изъ|съ|сь|подъ|пере|про|"
        r"недо|долбо|ни)?")
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


def pick_llm(mode):
    if mode == "auto":
        if _ollama_alive():
            return "ollama"
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        return "none"
    return mode


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


def llm_moments(segments, mode, progress=None, cancel=None):
    if mode == "none" or not segments:
        return []
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
        prompt = LLM_PROMPT + "\n".join(lines)
        try:
            if mode == "ollama":
                r = _http_json(CONFIG["ollama_url"] + "/api/chat", {
                    "model": CONFIG["ollama_model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "format": "json", "stream": False,
                    "options": {"temperature": 0.3, "num_ctx": 16384},
                }, {}, timeout=600)
                text = r.get("message", {}).get("content", "")
            else:
                r = _http_json("https://api.anthropic.com/v1/messages", {
                    "model": CONFIG["anthropic_model"],
                    "max_tokens": 2000,
                    "messages": [{"role": "user", "content": prompt}],
                }, {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                    "anthropic-version": "2023-06-01"}, timeout=180)
                text = "".join(b.get("text", "") for b in r.get("content", []))
            moments += _parse_moments(text)
        except urllib.error.HTTPError as e:
            log(f"   ⚠️  модель ответила ошибкой {e.code}: {e.read()[:300]!r}")
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


def _snap_start(t, segments):
    for s in segments:
        if s["s"] <= t < s["e"]:
            return s["s"] if t - s["s"] <= 4 else t
    return t


def _snap_end(t, segments):
    for s in segments:
        if s["s"] < t <= s["e"]:
            return s["e"] if s["e"] - t <= 5 else t
    return t


def pick_clips(smooth, loud_z, segments, moments, dur, parts=None, taken=()):
    """taken — интервалы (начало, конец) уже существующих клипов: рядом с ними не берём."""
    import numpy as np
    order = np.argsort(-smooth)
    clips = []
    busy = [{"s": a, "e": b} for a, b in taken]
    for peak in order:
        if len(clips) >= CONFIG["clips"]:
            break
        if smooth[peak] <= 0.5:
            break
        peak = float(peak)
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
        s = max(0.0, _snap_start(max(0.0, s), segments))
        e = min(dur, _snap_end(min(dur, e), segments))
        if e - s > CONFIG["max_len"]:          # слишком длинно — центрируем на пике
            s = max(0.0, min(peak - CONFIG["max_len"] * 0.65, e - CONFIG["max_len"]))
            e = s + CONFIG["max_len"]
        if e - s < CONFIG["min_len"]:
            extra = CONFIG["min_len"] - (e - s)
            s = max(0.0, s - extra * 0.6)
            e = min(dur, s + CONFIG["min_len"])
        if e - s < CONFIG["min_len"] * 0.8:
            continue
        if any(not (e <= c["s"] or s >= c["e"]) for c in clips + busy):
            continue

        # точки зума: самые громкие пики внутри клипа
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

        if not title:
            first = [w["w"] for seg in segments if seg["e"] > s and seg["s"] < e
                     for w in seg["words"] if s <= w["s"] < e][:6]
            title = " ".join(first) or f"момент {fmt_time(peak)}"
        # без мата в названии файла и отчёте
        title = " ".join(_censor(w) for w in title.split())
        pk = int(peak)
        clips.append({"s": round(s, 2), "e": round(e, 2), "peak": peak,
                      "score": float(smooth[pk]), "zooms": sorted(zooms),
                      "parts": {k: round(float(v[pk]), 2) for k, v in (parts or {}).items()},
                      "title": title, "reason": reason})
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


def sound_path(name):
    if name == "тишина":
        return None
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


def _display_word(w, cfg=None):
    cfg = cfg or CONFIG
    w = w.strip()
    w = re.sub(r"^[\"«(]+|[\"»),.;:]+$", "", w)
    w = _censor(w)
    if cfg["sub_uppercase"]:
        w = w.upper()
    return _ass_escape(w)


def build_ass(words, w, h, path, cfg=None):
    """words: [{'s','e','w'}] со временем относительно начала клипа."""
    cfg = cfg or CONFIG
    fs = int(cfg["sub_size"] * w / 1080)
    outline = max(3, int(fs * 0.09))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{cfg["sub_font"]},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},2,5,40,40,0,204

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # группируем слова в короткие фразы
    chunks, cur = [], []
    for i, wd in enumerate(words):
        if cur:
            prev = cur[-1]
            chars = sum(len(x["w"]) + 1 for x in cur) + len(wd["w"])
            if (len(cur) >= cfg["sub_max_words"] or chars > cfg["sub_max_chars"]
                    or wd["s"] - prev["e"] > 0.45 or re.search(r"[.!?…]$", prev["w"])):
                chunks.append(cur)
                cur = []
        cur.append(wd)
    if cur:
        chunks.append(cur)

    x, y = w // 2, int(h * cfg["sub_y"])
    lines = []
    for ci, ch in enumerate(chunks):
        disp = [_display_word(x_["w"], cfg) for x_ in ch]
        if not any(disp):
            continue
        next_start = chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else ch[-1]["e"] + 0.3
        chunk_end = min(ch[-1]["e"] + 0.25, next_start)
        for wi, wd in enumerate(ch):
            st = wd["s"]
            en = ch[wi + 1]["s"] if wi + 1 < len(ch) else chunk_end
            if en <= st:
                continue
            parts = []
            for j, d in enumerate(disp):
                parts.append("{\\c&H00E6FF&}" + d + "{\\c&HFFFFFF&}" if j == wi else d)
            pop = "{\\fscx85\\fscy85\\t(0,90,\\fscx100\\fscy100)}" if wi == 0 else ""
            text = "{\\an5\\pos(%d,%d)}" % (x, y) + pop + " ".join(parts)
            lines.append(f"Dialogue: 0,{_ass_time(st)},{_ass_time(en)},Main,,0,0,0,,{text}")

    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(header + "\n".join(lines) + "\n")


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


def clip_words(segments, s, e):
    """Слова клипа со временем относительно его начала."""
    words = []
    for seg in segments:
        if seg["e"] < s or seg["s"] > e:
            continue
        for wd in seg["words"]:
            if wd["s"] >= s - 0.05 and wd["e"] <= e + 0.05:
                words.append({"s": round(wd["s"] - s, 3), "e": round(wd["e"] - s, 3), "w": wd["w"]})
    return words


def render_clip(video, clip, segments, vinfo, out_path, tmpdir, cfg=None, cancel=None):
    """clip: {'s', 'e', 'zooms'} во времени записи. Возвращает число запиканных мест или None.
    Клип сначала собирается во временной папке и только потом встаёт на место out_path."""
    global _ENCODER
    cfg = cfg or CONFIG
    preset = get_preset(cfg["preset"])
    s, e = clip["s"], clip["e"]
    dur = e - s
    W, H = preset["w"], preset["h"]

    words = clip_words(segments, s, e)
    zooms = [z for z in clip["zooms"] if s + 1.0 <= z <= e - 2.0]

    # --- видео ---
    vf = frame_filters(vinfo, preset)
    if cfg["zoom"] and zooms:
        A = cfg["zoom_amount"]
        env = "+".join(
            f"clip((t-{z - s - 0.12:.2f})/0.12,0,1)*clip(({z - s + 1.6:.2f}-t)/0.35,0,1)"
            for z in zooms)
        Z = f"(1+{A}*min(1,{env}))"
        fy = cfg["zoom_focus_y"]
        vf.append(f"scale=w='2*trunc({W}*{Z}/2)':h='2*trunc({H}*{Z}/2)':eval=frame:flags=lanczos")
        vf.append(f"crop={W}:{H}:x='(iw-ow)/2':y='(ih-oh)*{fy}'")
    if cfg["subs"] and words:
        ass_name = "subs.ass"
        build_ass(words, W, H, os.path.join(tmpdir, ass_name), cfg)
        vf.append(f"ass={ass_name}")
    # перевод в Rec. 709 и метки цвета в самих кадрах (ffmpeg 9 берёт их оттуда, а не из флагов)
    vf.append("scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
              "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv")
    vgraph = "[0:v]" + ",".join(vf) + "[vout]"

    # --- звук и бип ---
    bleeps = []
    if cfg["bleep"]:
        pad = cfg["bleep_pad"]
        for wd in words:
            if is_profane(wd["w"]):
                a, b = max(0.0, wd["s"] - pad), min(dur, wd["e"] + pad)
                if bleeps and a <= bleeps[-1][1]:
                    bleeps[-1][1] = b
                else:
                    bleeps.append([a, b])
    fmt = "aformat=sample_rates=48000:channel_layouts=stereo"
    snd = sound_path(cfg["bleep_sound"]) if bleeps else None
    extra_in = []
    if bleeps:
        E = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in bleeps)
        agraph = f"[0:a]{fmt},volume=0:enable='{E}'[am]"
        if snd:
            sdur = sound_duration(snd)
            extra_in = ["-i", os.path.abspath(snd)]
            n = len(bleeps)
            agraph += f";[1:a]{fmt},volume={cfg['bleep_volume']},asplit={n}" + \
                      "".join(f"[s{i}]" for i in range(n))
            for i, (a, b) in enumerate(bleeps):
                L = max(0.12, min(sdur, (b - a) + 0.35))
                ms = int(a * 1000)
                agraph += (f";[s{i}]atrim=0:{L:.3f},afade=t=out:st={max(0, L - 0.06):.3f}:d=0.06,"
                           f"adelay={ms}:all=1[d{i}]")
            agraph += ";[am]" + "".join(f"[d{i}]" for i in range(n)) + \
                      f"amix=inputs={n + 1}:duration=first:normalize=0[aout]"
        else:
            agraph = agraph.replace("[am]", "[aout]")
    else:
        agraph = f"[0:a]{fmt}[aout]"

    tmp_out = os.path.join(tmpdir, "render.mp4")
    graph = vgraph + ";" + agraph
    base = ["ffmpeg", "-y", "-v", "error", "-ss", f"{s:.3f}", "-t", f"{dur:.3f}",
            "-i", os.path.abspath(video)] + extra_in + ["-filter_complex", graph,
            "-map", "[vout]", "-map", "[aout]"]
    tail = COLOR_FLAGS + ["-fps_mode", "cfr", "-r", str(preset["fps"]),
                          "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
                          "-movflags", "+faststart", tmp_out]

    encs = _encoders(preset)
    names = [_ENCODER] if _ENCODER else list(encs)
    last_err = ""
    for name in names:
        p = run(base + encs[name] + tail, cwd=tmpdir, cancel=cancel)
        if p.returncode == 0:
            _ENCODER = name
            replace_file(tmp_out, out_path)
            return len(bleeps)
        last_err = p.stderr
    log("   ❌ ffmpeg:\n" + last_err[-1500:])
    return None


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


def trash(path):
    """Удаление только в корзину Windows — насовсем программа ничего не удаляет."""
    if not os.path.exists(path):
        return
    try:
        from send2trash import send2trash
    except ImportError:
        raise AutoClipError("❌ Не установлен send2trash. Запусти install.bat.")
    send2trash(os.path.abspath(path))


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
OVERRIDE_KEYS = ("subs", "zoom", "bleep", "bleep_sound", "hook")
# настройки, которые запоминаются в проекте и нужны для пересборки
RENDER_KEYS = ("subs", "sub_font", "sub_size", "sub_y", "sub_max_words", "sub_max_chars",
               "sub_uppercase", "zoom", "zoom_amount", "zoom_focus_y", "bleep", "bleep_soft",
               "bleep_sound", "bleep_volume", "bleep_pad", "preset", "hook")


def project_path(path):
    """Запись, папка «_clips» или сам project.json → путь к project.json."""
    path = os.path.abspath(path)
    if os.path.isdir(path):
        return os.path.join(path, PROJECT_FILE)
    if path.lower().endswith(".json"):
        return path
    return os.path.splitext(path)[0] + "_clips" + os.sep + PROJECT_FILE


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
    cfg.update({k: v for k, v in clip.get("overrides", {}).items() if k in OVERRIDE_KEYS})
    return cfg


def make_clip_record(c, num, file):
    return {
        "id": f"c{num:02d}", "num": num, "file": file,
        "start": c["s"], "end": c["e"], "peak": c["peak"],
        "score": round(c["score"], 2), "score_parts": c.get("parts", {}),
        "title": c["title"], "reason": c["reason"],
        "zooms": c["zooms"],
        "hook": {"on": False, "start": None, "end": None, "why": "хук ещё не сделан (этап 4)"},
        "status": "new", "overrides": {}, "bleeps": None,
        "created": now_iso(), "rendered": None,
        "published": {},       # площадка → {"date", "url", "views": [...]}
    }


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
        if c["reason"]:
            rep.append(f"    почему: {c['reason']}")
        parts = ", ".join(f"{k} {v:+.1f}" for k, v in c["score_parts"].items() if abs(v) >= 0.05)
        if parts:
            rep.append(f"    из чего оценка: {parts}")
        rep.append(f"    запикано: {c['bleeps'] if c['bleeps'] is not None else '-'}, "
                   f"зумов: {len(c['zooms'])}")
        if c["overrides"]:
            rep.append("    свои настройки: " +
                       ", ".join(f"{k}={v}" for k, v in c["overrides"].items()))
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


def load_segments(proj):
    path = proj.get("transcript", "")
    if not os.path.isfile(path):
        raise AutoClipError(f"❌ Нет расшифровки: {path}\n   Нарежь запись заново.")
    with open(path, encoding="utf-8") as f:
        return drop_hallucinations(json.load(f))


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
    out = os.path.join(os.path.dirname(proj["_path"]), clip["file"])
    log(f"🔁 Пересобираю {clip['file']} ({fmt_time(s)}–{fmt_time(e)})")
    if progress:
        progress("рендер", 0, clip["file"])
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="autoclip_r_") as tmp:
        bl = render_clip(src, {"s": s, "e": e, "zooms": clip["zooms"]}, segments,
                         proj["source_info"], out, tmp, cfg, cancel)
    if bl is None:
        raise AutoClipError("❌ ffmpeg не смог собрать клип.")
    clip.update(start=round(s, 2), end=round(e, 2), bleeps=bl, rendered=now_iso())
    save_project(proj)
    write_report(proj)
    if progress:
        progress("рендер", 100, clip["file"])
    log(f"✅ Готово за {time.time() - t0:.1f} с")
    return clip


# ---------------- main ----------------

def safe_name(s):
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
    ap.add_argument("--model", help="модель Whisper (large-v3 / medium / small)")
    ap.add_argument("--subs", action=argparse.BooleanOptionalAction, default=None)
    ap.add_argument("--zoom", action=argparse.BooleanOptionalAction, default=None)
    ap.add_argument("--bleep", action=argparse.BooleanOptionalAction, default=None)
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
             "bleep_sound": args.sound}
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
    """Вся обработка одного видео. Возвращает папку с клипами (или None).
    progress(этап, процент 0–100 внутри этапа, сообщение) — этапы из STAGES;
    cancel — threading.Event или функция; при остановке — исключение Cancelled.
    Уже нарезанные клипы со статусом «хороший»/«выложен»/«отклонён» сохраняются,
    новые моменты рядом с ними не берутся; старые «новые» клипы уходят в корзину."""
    def prog(stage, pct, msg=""):
        if progress:
            progress(stage, pct, msg)

    need_ffmpeg()
    prepare_sounds()
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

    stem = os.path.splitext(os.path.abspath(video))[0]
    out_dir = stem + "_clips"
    cache = stem + ".transcript.json"

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
        prog("звук", 100)
        t = mark("звук и громкость", t)
        prog("расшифровка", 0)
        segments = drop_hallucinations(transcribe(wav, cache, vinfo["dur"], progress, cancel))
        prog("расшифровка", 100)
        t = mark(f"расшифровка ({WHISPER_DEVICE})", t)
    n_words = sum(len(s["words"]) for s in segments)
    n_mat = sum(is_profane(w["w"]) for s in segments for w in s["words"])
    log(f"   слов: {n_words}, из них мата: {n_mat}")

    check_cancel(cancel)
    mode = pick_llm(CONFIG["llm"])
    moments = []
    prog("модель", 0)
    if mode != "none":
        log(f"🤖 Оцениваю моменты через {mode}...")
        moments = llm_moments(segments, mode, progress, cancel)
        log(f"   модель предложила {len(moments)} моментов")
    else:
        log("🤖 Без языковой модели — ищу по звуку и речи.")
    prog("модель", 100)
    t = mark("языковая модель", t)

    prog("поиск", 0)
    proj = new_project(video, vinfo, out_dir, cache)
    if os.path.isfile(os.path.join(out_dir, PROJECT_FILE)):
        old = load_project(out_dir)
        proj["clips"] = old["clips"]
        proj["created"] = old.get("created", proj["created"])
    kept = [c for c in proj["clips"] if c["status"] != "new"]
    stale = [c for c in proj["clips"] if c["status"] == "new"]
    if kept:
        log(f"   оставляю {len(kept)} уже разобранных клипов")

    smooth, loud_z, parts = score_timeline(loud, segments, moments)
    clips = pick_clips(smooth, loud_z, segments, moments, vinfo["dur"], parts,
                       taken=[(c["start"], c["end"]) for c in kept])
    prog("поиск", 100)
    if not clips:
        log("😕 Ярких моментов не нашлось. Попробуй уменьшить min_len или подключить модель.")
        return None
    log(f"✂️  Нашёл {len(clips)} клипов")
    t = mark("поиск моментов", t)

    if analyze_only:
        for i, c in enumerate(clips, 1):
            log(f"   {i:02d}. {fmt_time(c['s'])}–{fmt_time(c['e'])} ({c['e'] - c['s']:.0f} с), "
                f"оценка {c['score']:.1f} — {c['title']}")
        return out_dir

    os.makedirs(out_dir, exist_ok=True)
    for c in stale:                              # прошлая нарезка, которую ещё не смотрели
        trash(os.path.join(out_dir, c["file"]))
    proj["clips"] = kept
    proj["settings"] = {k: CONFIG[k] for k in RENDER_KEYS if k in CONFIG}
    proj["settings"]["preset"] = preset          # сам пресет: пересборка не зависит от списка
    proj["run"] = {"date": now_iso(), "timings": timings}
    save_project(proj)

    num = max((c["num"] for c in kept), default=0)
    with tempfile.TemporaryDirectory(prefix="autoclip_r_") as tmp:
        for i, c in enumerate(clips, 1):
            check_cancel(cancel)
            num += 1
            name = f"{num:02d}_{safe_name(c['title'])}.mp4"
            log(f"   [{i}/{len(clips)}] {name}")
            prog("рендер", (i - 1) / len(clips) * 100, name)
            rec = make_clip_record(c, num, name)
            rec["bleeps"] = render_clip(video, c, segments, vinfo, os.path.join(out_dir, name),
                                        tmp, clip_config(proj, rec), cancel)
            if rec["bleeps"] is None:
                num -= 1
                continue
            rec["rendered"] = now_iso()
            proj["clips"].append(rec)
            save_project(proj)                   # после каждого клипа: остановка ничего не теряет
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
