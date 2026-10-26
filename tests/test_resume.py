"""P3: прерванная нарезка доделывается с места обрыва; атомарная запись."""
import json
import os
import sys

import pytest

import autoclip


def test_resume_after_interrupt(tmp_path, fake_trash, monkeypatch):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import test_editor
    autoclip.CONFIG.update(llm="none", clips=3, hook="off")
    v = str(test_editor._video(tmp_path))
    real = autoclip.render_planned
    calls = []

    def flaky(proj, video, vinfo, segs, reaction, num, c, total, cancel=None, on_frac=None):
        calls.append(num)
        if len(calls) == 2:
            raise autoclip.Cancelled()                     # «выключили свет» на втором клипе
        return real(proj, video, vinfo, segs, reaction, num, c, total, cancel, on_frac)
    monkeypatch.setattr(autoclip, "render_planned", flaky)
    with pytest.raises(autoclip.Cancelled):
        autoclip.process(v)
    unfinished = autoclip.unfinished_cuts()
    assert len(unfinished) == 1
    pp, left = unfinished[0]
    proj = autoclip.load_project(pp)
    assert len(proj["clips"]) == 1 and left == len(proj["planned"]) - 1
    monkeypatch.setattr(autoclip, "render_planned", real)
    out = autoclip.resume_cut(pp)
    proj = autoclip.load_project(out)
    assert len(proj["clips"]) == len(proj.get("planned") or []) or proj["run"]["complete"] is True
    assert proj["run"]["complete"] is True and not autoclip.unfinished_cuts()
    for c in proj["clips"]:
        assert os.path.isfile(os.path.join(out, c["file"]))


def test_write_atomic_keeps_old_on_failure(tmp_path, monkeypatch):
    p = tmp_path / "x.json"
    autoclip.write_json(str(p), {"a": 1})
    real = os.replace

    def boom(a, b):
        raise OSError("диск отвалился")
    monkeypatch.setattr(autoclip.os, "replace", boom)
    with pytest.raises(OSError):
        autoclip.write_json(str(p), {"a": 2})
    monkeypatch.setattr(autoclip.os, "replace", real)
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}             # старый целиком, не обрывок
