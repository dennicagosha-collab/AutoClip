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
Результат: папка "<имя видео>_clips" рядом с видео + отчёт.txt

Настройки — в блоке CONFIG ниже.
"""

import argparse
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

    # --- качество ---
    "quality": 16,            # 14 = почти без потерь (файлы больше), 18 = легче
}
# ======================================================


# ---------------- утилиты ----------------

def log(msg):
    print(msg, flush=True)


def fmt_time(sec):
    sec = max(0, int(sec))
    return f"{sec // 3600:d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def run(cmd, cwd=None, quiet=True):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0 and not quiet:
        log(p.stderr[-3000:])
    return p


def need_ffmpeg():
    # ffmpeg.exe / ffprobe.exe можно просто положить рядом со скриптом
    here = os.path.dirname(os.path.abspath(__file__))
    os.environ["PATH"] = here + os.pathsep + os.environ.get("PATH", "")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            log(f"❌ Не найден {tool}. Установи ffmpeg (install.bat) и перезапусти окно.")
            sys.exit(1)


def probe(video):
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
             "-show_format", video])
    if p.returncode != 0:
        log("❌ ffprobe не смог прочитать видео:\n" + p.stderr)
        sys.exit(1)
    info = json.loads(p.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if not v:
        log("❌ В файле нет видеодорожки.")
        sys.exit(1)
    if not a:
        log("❌ В файле нет звука — без звука искать моменты нечем.")
        sys.exit(1)
    return {
        "w": int(v["width"]), "h": int(v["height"]),
        "dur": float(info["format"]["duration"]),
    }


# ---------------- 1. звук ----------------

def extract_audio(video, wav):
    log("🔊 Достаю звук...")
    p = run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", wav], quiet=False)
    if p.returncode != 0:
        sys.exit(1)


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


def transcribe(wav, cache_path, dur):
    if os.path.exists(cache_path):
        log("📝 Расшифровка уже есть, беру из кэша.")
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    _windows_cuda_dlls()
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log("❌ Не установлен faster-whisper. Запусти install.bat.")
        sys.exit(1)

    name = CONFIG["whisper_model"]
    model = None
    for device, ctype in (("cuda", "float16"), ("cpu", "int8")):
        try:
            log(f"🧠 Загружаю Whisper {name} ({device})... первый раз скачается ~3 ГБ")
            model = WhisperModel(name, device=device, compute_type=ctype)
            if device == "cpu":
                log("⚠️  Видеокарта не подхватилась, считаю на процессоре — будет в разы медленнее.")
            break
        except Exception as e:
            log(f"   не вышло на {device}: {e}")
    if model is None:
        log("❌ Whisper не запустился.")
        sys.exit(1)

    log("📝 Расшифровываю речь (на 3 часа записи — примерно 10–25 минут на видеокарте)...")
    t0 = time.time()
    try:
        segments, _info = model.transcribe(
            wav,
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
            words = [{"s": round(w.start, 2), "e": round(w.end, 2), "w": w.word.strip()}
                     for w in (s.words or []) if w.word.strip()]
            result.append({"s": round(s.start, 2), "e": round(s.end, 2),
                           "text": s.text.strip(), "words": words})
            if s.end - last_print > 120:
                last_print = s.end
                pct = min(100, s.end / dur * 100)
                log(f"   {fmt_time(s.end)} из {fmt_time(dur)} ({pct:.0f}%)")
    except Exception as e:
        log(f"❌ Ошибка расшифровки: {e}")
        log("   Если ошибка про cublas/cudnn — запусти install.bat ещё раз.")
        sys.exit(1)

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


def llm_moments(segments, mode):
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
        log(f"   кусок {i}/{n_chunks}")
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

    score = (1.0 * loud_z
             + 1.5 * np.minimum(laugh, 3)
             + 0.4 * np.minimum(excl, 1)
             + 0.6 * np.minimum(mat, 2)
             + 0.15 * np.minimum(words, 6)
             + 3.0 * llm)
    k = np.ones(5) / 5
    smooth = np.convolve(score, k, mode="same")
    return smooth, loud_z


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


def pick_clips(smooth, loud_z, segments, moments, dur):
    import numpy as np
    order = np.argsort(-smooth)
    clips = []
    for peak in order:
        if len(clips) >= CONFIG["clips"]:
            break
        if smooth[peak] <= 0.5:
            break
        peak = float(peak)
        if any(c["s"] - CONFIG["min_gap"] < peak < c["e"] + CONFIG["min_gap"] for c in clips):
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
        if any(not (e <= c["s"] or s >= c["e"]) for c in clips):
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
                     for w in seg["words"]][:6]
            title = " ".join(first)
        # без мата в названии файла и отчёте
        title = " ".join(_censor(w) for w in title.split())
        clips.append({"s": round(s, 2), "e": round(e, 2), "peak": peak,
                      "score": float(smooth[int(peak)]), "zooms": sorted(zooms),
                      "title": title, "reason": reason})
    return sorted(clips, key=lambda c: -c["score"])


# ---------------- звуки для мата ----------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR = os.path.join(SCRIPT_DIR, "звуки")
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


def _display_word(w):
    w = w.strip()
    w = re.sub(r"^[\"«(]+|[\"»),.;:]+$", "", w)
    w = _censor(w)
    if CONFIG["sub_uppercase"]:
        w = w.upper()
    return _ass_escape(w)


def build_ass(words, w, h, path):
    """words: [{'s','e','w'}] со временем относительно начала клипа."""
    fs = int(CONFIG["sub_size"] * w / 1080)
    outline = max(3, int(fs * 0.09))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{CONFIG["sub_font"]},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},2,5,40,40,0,204

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # группируем слова в короткие фразы
    chunks, cur = [], []
    for i, wd in enumerate(words):
        if cur:
            prev = cur[-1]
            chars = sum(len(x["w"]) + 1 for x in cur) + len(wd["w"])
            if (len(cur) >= CONFIG["sub_max_words"] or chars > CONFIG["sub_max_chars"]
                    or wd["s"] - prev["e"] > 0.45 or re.search(r"[.!?…]$", prev["w"])):
                chunks.append(cur)
                cur = []
        cur.append(wd)
    if cur:
        chunks.append(cur)

    x, y = w // 2, int(h * CONFIG["sub_y"])
    lines = []
    for ci, ch in enumerate(chunks):
        disp = [_display_word(x_["w"]) for x_ in ch]
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

_ENCODER = None


def _encoders():
    q = str(CONFIG["quality"])
    return [
        ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", q,
         "-b:v", "0", "-maxrate", "60M", "-bufsize", "120M", "-spatial-aq", "1",
         "-temporal-aq", "1", "-profile:v", "high"],
        ["-c:v", "libx264", "-preset", "slow", "-crf", q, "-profile:v", "high"],
    ]


def render_clip(video, clip, segments, vinfo, out_path, tmpdir):
    global _ENCODER
    s, e = clip["s"], clip["e"]
    dur = e - s
    # родное разрешение записи — без пережатия в меньшее
    if vinfo["w"] > vinfo["h"]:
        H = vinfo["h"] - vinfo["h"] % 2
        W = int(H * 9 / 16) // 2 * 2
    else:
        W, H = vinfo["w"] - vinfo["w"] % 2, vinfo["h"] - vinfo["h"] % 2

    # слова клипа (время относительно начала клипа)
    words = []
    for seg in segments:
        if seg["e"] < s or seg["s"] > e:
            continue
        for wd in seg["words"]:
            if wd["s"] >= s - 0.05 and wd["e"] <= e + 0.05:
                words.append({"s": round(wd["s"] - s, 3), "e": round(wd["e"] - s, 3), "w": wd["w"]})

    # --- видео ---
    vf = []
    if vinfo["w"] > vinfo["h"]:                       # если вдруг запись горизонтальная
        vf.append(f"crop={W}:{H}")
    vf.append("setsar=1")
    if CONFIG["zoom"] and clip["zooms"]:
        A = CONFIG["zoom_amount"]
        env = "+".join(
            f"clip((t-{z - s - 0.12:.2f})/0.12,0,1)*clip(({z - s + 1.6:.2f}-t)/0.35,0,1)"
            for z in clip["zooms"])
        Z = f"(1+{A}*min(1,{env}))"
        fy = CONFIG["zoom_focus_y"]
        vf.append(f"scale=w='2*trunc({W}*{Z}/2)':h='2*trunc({H}*{Z}/2)':eval=frame:flags=lanczos")
        vf.append(f"crop={W}:{H}:x='(iw-ow)/2':y='(ih-oh)*{fy}'")
    ass_name = None
    if CONFIG["subs"] and words:
        ass_name = f"subs_{os.getpid()}.ass"
        build_ass(words, W, H, os.path.join(tmpdir, ass_name))
        vf.append(f"ass={ass_name}")
    vf.append("format=yuv420p")
    vgraph = "[0:v]" + ",".join(vf) + "[vout]"

    # --- звук и бип ---
    bleeps = []
    if CONFIG["bleep"]:
        pad = CONFIG["bleep_pad"]
        for wd in words:
            if is_profane(wd["w"]):
                a, b = max(0.0, wd["s"] - pad), min(dur, wd["e"] + pad)
                if bleeps and a <= bleeps[-1][1]:
                    bleeps[-1][1] = b
                else:
                    bleeps.append([a, b])
    fmt = "aformat=sample_rates=48000:channel_layouts=stereo"
    snd = sound_path(CONFIG["bleep_sound"]) if bleeps else None
    extra_in = []
    if bleeps:
        E = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in bleeps)
        agraph = f"[0:a]{fmt},volume=0:enable='{E}'[am]"
        if snd:
            sdur = sound_duration(snd)
            extra_in = ["-i", os.path.abspath(snd)]
            n = len(bleeps)
            agraph += f";[1:a]{fmt},volume={CONFIG['bleep_volume']},asplit={n}" + \
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

    graph = vgraph + ";" + agraph
    base = ["ffmpeg", "-y", "-v", "error", "-ss", f"{s:.3f}", "-t", f"{dur:.3f}",
            "-i", os.path.abspath(video)] + extra_in + ["-filter_complex", graph,
            "-map", "[vout]", "-map", "[aout]"]
    tail = ["-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-movflags", "+faststart",
            os.path.abspath(out_path)]

    encs = [_ENCODER] if _ENCODER else _encoders()
    last_err = ""
    for enc in encs:
        p = run(base + enc + tail, cwd=tmpdir)
        if p.returncode == 0:
            _ENCODER = enc
            return len(bleeps)
        last_err = p.stderr
    log("   ❌ ffmpeg:\n" + last_err[-1500:])
    return None


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
    ap.add_argument("video", nargs="?", help="путь к видео")
    ap.add_argument("--clips", type=int, help="сколько клипов")
    ap.add_argument("--llm", choices=["auto", "ollama", "anthropic", "none"])
    ap.add_argument("--model", help="модель Whisper (large-v3 / medium / small)")
    ap.add_argument("--no-subs", action="store_true")
    ap.add_argument("--no-zoom", action="store_true")
    ap.add_argument("--no-bleep", action="store_true")
    ap.add_argument("--sound", help="звук на мат: перелистывание / буп / свист / бип / тишина / свой файл")
    ap.add_argument("--analyze-only", action="store_true", help="только найти моменты, без рендера")
    args = ap.parse_args()

    video = args.video
    if not video:
        video = input("Перетащи сюда видео и нажми Enter: ").strip().strip('"').strip("'")
    if not os.path.isfile(video):
        log(f"❌ Файл не найден: {video}")
        sys.exit(1)
    if args.clips:
        CONFIG["clips"] = args.clips
    if args.llm:
        CONFIG["llm"] = args.llm
    if args.model:
        CONFIG["whisper_model"] = args.model
    if args.no_subs:
        CONFIG["subs"] = False
    if args.no_zoom:
        CONFIG["zoom"] = False
    if args.no_bleep:
        CONFIG["bleep"] = False
    if args.sound:
        CONFIG["bleep_sound"] = args.sound

    process(video, analyze_only=args.analyze_only)


def process(video, analyze_only=False):
    """Вся обработка одного видео. Возвращает папку с клипами (или None)."""
    need_ffmpeg()
    prepare_sounds()
    try:
        import numpy  # noqa: F401
    except ImportError:
        log("❌ Не установлен numpy. Запусти install.bat.")
        sys.exit(1)

    t_start = time.time()
    vinfo = probe(video)
    log(f"🎬 {os.path.basename(video)} — {fmt_time(vinfo['dur'])}, {vinfo['w']}x{vinfo['h']}")
    if vinfo["w"] > vinfo["h"]:
        log("⚠️  Видео горизонтальное — обрежу центр под 9:16.")

    stem = os.path.splitext(os.path.abspath(video))[0]
    out_dir = stem + "_clips"
    os.makedirs(out_dir, exist_ok=True)
    cache = stem + ".transcript.json"

    with tempfile.TemporaryDirectory(prefix="autoclip_") as tmp:
        wav = os.path.join(tmp, "audio.wav")
        extract_audio(video, wav)
        loud = loudness_per_second(wav)
        segments = transcribe(wav, cache, vinfo["dur"])
    n_words = sum(len(s["words"]) for s in segments)
    n_mat = sum(is_profane(w["w"]) for s in segments for w in s["words"])
    log(f"   слов: {n_words}, из них мата: {n_mat}")

    mode = pick_llm(CONFIG["llm"])
    moments = []
    if mode != "none":
        log(f"🤖 Оцениваю моменты через {mode}...")
        moments = llm_moments(segments, mode)
        log(f"   модель предложила {len(moments)} моментов")
    else:
        log("🤖 Без языковой модели — ищу по звуку и речи.")

    smooth, loud_z = score_timeline(loud, segments, moments)
    clips = pick_clips(smooth, loud_z, segments, moments, vinfo["dur"])
    if not clips:
        log("😕 Ярких моментов не нашлось. Попробуй уменьшить min_len или подключить модель.")
        return None
    log(f"✂️  Нашёл {len(clips)} клипов")

    report = [f"Источник: {video}", ""]
    made = []
    with tempfile.TemporaryDirectory(prefix="autoclip_r_") as tmp:
        for i, c in enumerate(clips, 1):
            name = f"{i:02d}_{safe_name(c['title'])}.mp4"
            out = os.path.join(out_dir, name)
            line = (f"{i:02d}. {fmt_time(c['s'])}–{fmt_time(c['e'])} "
                    f"({c['e'] - c['s']:.0f} с), оценка {c['score']:.1f}")
            if analyze_only:
                log("   " + line + f" — {c['title']}")
                bl = "-"
            else:
                log(f"   [{i}/{len(clips)}] {name}")
                bl = render_clip(video, c, segments, vinfo, out, tmp)
                if bl is None:
                    continue
            made.append({"file": name, "title": c["title"], "start": c["s"], "end": c["e"]})
            report += [line, f"    файл: {name}", f"    про что: {c['title']}"]
            if c["reason"]:
                report.append(f"    почему: {c['reason']}")
            report.append(f"    запикано: {bl}, зумов: {len(c['zooms'])}")
            report.append("")

    with open(os.path.join(out_dir, "отчёт.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    with open(os.path.join(out_dir, "clips.json"), "w", encoding="utf-8") as f:
        json.dump(made, f, ensure_ascii=False, indent=1)
    log(f"✅ Готово за {(time.time() - t_start) / 60:.1f} мин → {out_dir}")
    return out_dir


if __name__ == "__main__":
    main()
