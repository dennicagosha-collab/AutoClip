"""P3: ресурсы перед нарезкой, сторож ffmpeg, видеопамять."""
import subprocess
import sys

import pytest

import autoclip
import health


def test_problems_wait_and_stop(tmp_path, monkeypatch):
    g = {"used": 14000, "total": 16000, "free": 2000, "temp": 88, "util": 99}
    r = {"free": 1500, "total": 64000}
    ps = health.problems(None, True, g, r)
    kinds = [k for k, _ in ps]
    texts = " ".join(t for _, t in ps)
    assert kinds == ["wait", "wait", "wait"] and "памяти" in texts and "горячая" in texts and "видеопамяти" in texts
    assert health.problems(None, False, dict(g, temp=50), dict(r, free=9000)) == []   # без Whisper видеопамять не нужна
    monkeypatch.setattr(health, "disk_free_gb", lambda p: 1.0)
    assert ("stop", "мало места на диске: 1.0 ГБ") in health.problems(str(tmp_path), False, None, None) or \
        any(k == "stop" for k, _ in health.problems(str(tmp_path), False, {"free": 9e9, "temp": 1, "used": 0,
                                                                           "total": 1, "util": 0}, {"free": 9e9}))


def test_wait_resources_waits_then_gives_up(monkeypatch):
    import importlib
    real = importlib.reload(health)                     # без заглушки из conftest
    calls = []
    monkeypatch.setattr(real, "problems", lambda *a, **k: calls.append(1) or [("wait", "горячо")])
    monkeypatch.setattr(real.time, "sleep", lambda s: None)
    t = [0.0]
    monkeypatch.setattr(real.time, "time", lambda: t.__setitem__(0, t[0] + 50) or t[0])
    left = real.wait_resources(max_s=120, sleep=0)
    assert left == ["горячо"] and len(calls) >= 2
    monkeypatch.setattr(real, "problems", lambda *a, **k: [("stop", "мало места")])
    with pytest.raises(autoclip.AutoClipError):
        real.wait_resources()


def test_ffmpeg_watchdog_kills_and_retries(monkeypatch):
    monkeypatch.setattr(autoclip, "WATCHDOG_S", 1)
    logs = []
    monkeypatch.setattr(autoclip, "log", logs.append)
    # «ffmpeg», который ничего не пишет и висит: python sleep
    cmd = [sys.executable, "-c", "import time,sys; time.sleep(30)"]
    real = autoclip._run_progress

    def fake(cmd_, cwd, quiet, cancel, on_time):
        return real(cmd, cwd, quiet, cancel, on_time)
    monkeypatch.setattr(autoclip, "_run_progress", lambda c, cwd, q, can, on: _plain(cmd, on))
    p = autoclip.run(["ffmpeg"], on_time=lambda t: None)
    assert p.stalled and sum("завис" in m for m in logs) == 2                   # убил, повторил, сдался


def _plain(cmd, on_time):
    """Как _run_progress, но без «-progress» (для подставной команды)."""
    import threading
    import time
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    last, stalled = [time.time()], []

    def watch():
        while proc.poll() is None:
            if time.time() - last[0] > autoclip.WATCHDOG_S:
                stalled.append(True)
                proc.kill()
                return
            time.sleep(0.1)
    threading.Thread(target=watch, daemon=True).start()
    for _ in proc.stdout:
        last[0] = time.time()
    proc.wait()
    p = subprocess.CompletedProcess(cmd, proc.returncode, "", "")
    p.stalled = bool(stalled)
    return p


def test_status_rows(monkeypatch):
    import health as h
    monkeypatch.setattr(h, "_ffmpeg_version", lambda: "9.0")
    monkeypatch.setattr(h, "_nvenc_ok", lambda: True)
    monkeypatch.setattr(h, "_cuda_devices", lambda: 1)
    monkeypatch.setattr(h, "gpu", lambda: {"used": 2000, "total": 16000, "free": 14000, "temp": 50, "util": 5})
    monkeypatch.setattr(autoclip, "_ollama_alive", lambda: True)
    monkeypatch.setattr(autoclip, "ollama_models", lambda: ["qwen3:14b"])
    rows = {name: (ok, text) for name, ok, text in h.status()}
    assert rows["ffmpeg"][0] and rows["Видеокодек NVENC"][0] and rows["Whisper на видеокарте (CUDA)"][0]
    assert rows["Ollama"] == (True, "модели: qwen3:14b") and "Telegram" in rows


def test_friendly_errors_and_hook(monkeypatch):
    pytest.importorskip("PySide6")
    import app
    assert "памяти" in app.friendly_error(MemoryError, MemoryError())
    assert "занят" in app.friendly_error(PermissionError, PermissionError("x.mp4"))
    e = OSError(28, "no space")
    e.winerror = 112
    assert "место" in app.friendly_error(OSError, e)
    assert app.friendly_error(autoclip.AutoClipError, autoclip.AutoClipError("❌ Не найдена запись")) == \
        "Не найдена запись"
