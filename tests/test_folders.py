"""Патч 5.11: папки «Клипы ДД.ММ.ГГГГ», подпапки статусов, служебное — в скрытой .autoclip."""
import datetime
import json
import os
import subprocess

import autoclip


def _video(tmp_path, dur=100):
    v = tmp_path / "записи" / "запись.mp4"
    v.parent.mkdir()
    audio = f"aevalsrc='0.03*sin(2*PI*300*t)*(1+25*between(mod(t,20),10,12))':s=48000:d={dur}"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=270x480:r=30:d={dur}",
                    "-f", "lavfi", "-i", audio, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", str(v)], check=True)
    segs = [{"s": t, "e": t + 2.4, "text": "ну вот смотри сюда",
             "words": [{"s": t + i * 0.6, "e": t + i * 0.6 + 0.5, "w": w}
                       for i, w in enumerate(["ну", "вот", "смотри", "сюда"])]} for t in range(0, dur, 4)]
    with open(v.parent / "запись.transcript.json", "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False)
    return str(v)


def test_new_layout(tmp_path, fake_trash):
    clips = tmp_path / "Клипы"
    clips.mkdir()
    autoclip.CONFIG.update(llm="none", clips=2, hook="off", clips_dir=str(clips))
    v = _video(tmp_path)
    out = autoclip.process(v)
    today = datetime.date.today().strftime("%d.%m.%Y")
    assert os.path.basename(out) == f"Клипы {today}"
    assert os.path.isfile(os.path.join(out, ".autoclip", "project.json"))
    assert os.path.isfile(os.path.join(out, ".autoclip", autoclip.MARKER))
    assert os.path.isfile(os.path.join(out, ".autoclip", "отчёт.txt"))
    proj = autoclip.load_project(out)
    c = proj["clips"][0]
    assert c["file"].startswith("Новые/") and os.path.isfile(os.path.join(out, c["file"]))
    # вторая нарезка за день — «… 2»
    assert os.path.basename(autoclip.new_cut_dir(str(clips))) == f"Клипы {today} 2"

    # смена статуса переносит файл и обложку
    c = autoclip.set_rating(out, c["id"], "post")
    assert c["file"].startswith("Выложу/") and os.path.isfile(os.path.join(out, c["file"]))
    assert not os.listdir(os.path.join(out, "Новые")) or all(not n.startswith(c["file"][7:9]) for n in os.listdir(os.path.join(out, "Новые")))
    c = autoclip.mark_published(out, c["id"], "tiktok")
    assert c["file"].startswith("Выложенные/") and os.path.isfile(os.path.join(out, c["file"]))
    c = autoclip.set_rating(out, proj["clips"][1]["id"], "ok")
    assert c["file"].startswith("Норм/")

    # папку переименовали — нарезка находится по маркеру
    new = os.path.join(str(clips), "Мои лучшие")
    os.rename(out, new)
    pp = autoclip.find_cut_by_id(proj["cut_id"], [str(clips)])
    assert pp and os.path.dirname(os.path.dirname(pp)) == new
    assert autoclip.load_project(new)["cut_id"] == proj["cut_id"]


def test_old_layout_still_works(tmp_path):
    autoclip.CONFIG.update(llm="none", clips=1, hook="off", clips_dir="")
    out = autoclip.process(_video(tmp_path))
    assert out.endswith("запись_clips") and os.path.isfile(os.path.join(out, "project.json"))
    c = autoclip.load_project(out)["clips"][0]
    assert "/" not in c["file"]
    c = autoclip.set_rating(out, c["id"], "post")
    assert "/" not in c["file"] and os.path.isfile(os.path.join(out, c["file"]))
