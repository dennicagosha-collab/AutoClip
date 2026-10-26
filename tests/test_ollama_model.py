"""Патч 5.6: модели из настроек нет — взятая модель запоминается, предупреждение один раз."""
import json

import autoclip


def test_replaced_model_remembered(monkeypatch):
    with open(autoclip.SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump({"ollama_model": "qwen2.5:14b", "sound": "буп"}, f)
    monkeypatch.setitem(autoclip.CONFIG, "ollama_model", "qwen2.5:14b")
    monkeypatch.setattr(autoclip, "_ollama_alive", lambda: True)
    monkeypatch.setattr(autoclip, "ollama_models", lambda: ["qwen3:14b"])
    logs = []
    monkeypatch.setattr(autoclip, "log", logs.append)
    assert autoclip.pick_llm("auto") == "ollama"
    assert autoclip.CONFIG["ollama_model"] == "qwen3:14b"
    with open(autoclip.SETTINGS_PATH, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved == {"ollama_model": "qwen3:14b", "sound": "буп"}
    assert sum("нет в Ollama" in m for m in logs) == 1
    autoclip.pick_llm("auto")                                     # второй раз — тихо
    assert sum("нет в Ollama" in m for m in logs) == 1
