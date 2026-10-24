"""Редактор клипа: статусы, тихое начало, сдвиг границ, пересборка, корзина, «Сохранить как»."""
import json
import os
import subprocess
import sys

import pytest

import autoclip
from qtwait import pump


def _video(tmp_path, dur=60, quiet_until=0):
    v = tmp_path / "запись.mp4"
    # громкие всплески на 10–12, 30–32, 50–52 с; до quiet_until — полная тишина
    audio = (f"aevalsrc='0.03*sin(2*PI*300*t)*(1+25*between(mod(t,20),10,12))"
             f"*gte(t,{quiet_until})':s=48000:d={dur}")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=s=270x480:r=30:d={dur}", "-f", "lavfi", "-i", audio,
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                    str(v)], check=True)
    segs = [{"s": t, "e": t + 2.4, "text": "ну вот смотри сюда",
             "words": [{"s": t + i * 0.6, "e": t + i * 0.6 + 0.5, "w": w}
                       for i, w in enumerate(["ну", "вот", "смотри", "сюда"])]}
            for t in range(0, dur, 4)]
    with open(tmp_path / "запись.transcript.json", "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False)
    return v


@pytest.fixture
def cut(tmp_path, fake_trash):
    autoclip.CONFIG.update(llm="none", clips=3, hook=False)
    return autoclip.process(str(_video(tmp_path)))


# ---------- ядро ----------

def test_time_exact_roundtrip():
    for t in (0, 78.4, 3730.9, 59.95):
        assert abs(autoclip.parse_time(autoclip.fmt_time_exact(t)) - round(t, 1)) < 0.051


def test_status_good_and_back(cut):
    c = autoclip.load_project(cut)["clips"][0]
    assert autoclip.set_status(cut, c["id"], "good")["status"] == "good"
    assert autoclip.set_status(cut, c["id"], "new")["status"] == "new"
    with pytest.raises(autoclip.AutoClipError):
        autoclip.set_status(cut, c["id"], "крутой")


def test_rejected_goes_to_trash(cut, fake_trash):
    c = autoclip.load_project(cut)["clips"][0]
    autoclip.set_status(cut, c["id"], "rejected")
    assert not os.path.exists(os.path.join(cut, c["file"]))
    assert len([f for f in os.listdir(fake_trash) if f.endswith(".mp4")]) == 1   # не удалён, а в корзине
    with pytest.raises(autoclip.AutoClipError):
        autoclip.set_status(cut, c["id"], "good")
    assert "rejected" == autoclip.find_clip(autoclip.load_project(cut), c["id"])["status"]


def test_save_as_copies_and_trashes_old(cut, tmp_path, fake_trash):
    c = autoclip.load_project(cut)["clips"][0]
    dest = tmp_path / "копия.mp4"
    dest.write_bytes(b"old")
    autoclip.save_clip_as(cut, c["id"], str(dest))
    assert dest.stat().st_size == os.path.getsize(os.path.join(cut, c["file"]))
    assert os.path.isfile(os.path.join(cut, c["file"]))     # оригинал на месте
    assert len(os.listdir(fake_trash)) == 1                 # старая «копия» — в корзине


def test_quiet_start(tmp_path):
    loud, quiet = tmp_path / "loud.mp4", tmp_path / "quiet.mp4"
    for path, expr in ((loud, "0.3*sin(2*PI*300*t)"), (quiet, "0.3*sin(2*PI*300*t)*gte(t,4)")):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"aevalsrc='{expr}':s=48000:d=6", "-c:a", "aac", str(path)], check=True)
    assert autoclip.quiet_start(str(loud)) is False
    assert autoclip.quiet_start(str(quiet)) is True


def test_clip_tags():
    c = {"status": "good", "hook": {"on": True}, "quiet_start": True, "marks": [10.0]}
    assert autoclip.clip_tags(c) == ["хороший", "хук", "тихое начало", "метка"]


# ---------- окно ----------

pytest.importorskip("PySide6")


@pytest.fixture
def win(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(autoclip, "SETTINGS_PATH", str(tmp_path / "настройки.json"))
    monkeypatch.setattr(autoclip, "PRESETS_PATH", str(tmp_path / "пресеты.json"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(autoclip, "log", lambda m: None)
    import app as A
    qapp = QApplication.instance() or QApplication([])
    A.dark_palette(qapp)
    from PySide6.QtWidgets import QMessageBox

    def fail(parent, title, text, *a, **k):    # всплывающая ошибка — сразу провал теста
        raise AssertionError(text)
    monkeypatch.setattr(QMessageBox, "warning", fail)
    w = A.MainWindow()
    w.show()
    yield w
    w.close()


def wait_for(cond, ms=60000):
    for _ in range(ms // 50):
        if cond():
            return True
        pump(50)
    return cond()


def _dur(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(p.stdout)


def test_editor_shift_and_rebuild(win, cut, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    page = win.clips
    page.load(cut)
    c = page.current_clip()
    assert page.editor.isEnabled() and not page.pending()

    # +2 с к началу и выключить зум у этого клипа
    page.shift(page.e_start, 2.0)
    page.e_zoom.setCurrentIndex(page.e_zoom.findData("off"))
    assert set(page.pending()) == {"start", "zoom"}
    assert "Пересобрать" in page.state.text()
    page.rebuild()
    assert wait_for(lambda: not page.busy)
    assert page.state.text().startswith("Готово"), page.state.text()
    new = autoclip.find_clip(autoclip.load_project(cut), c["id"])
    assert new["start"] == pytest.approx(round(c["start"], 1) + 2.0, abs=0.06)
    assert new["overrides"]["zoom"] == "off"
    assert abs(_dur(os.path.join(cut, new["file"])) - (new["end"] - new["start"])) < 0.2
    assert not page.pending()                                # после пересборки правок нет
    assert page.current_clip()["id"] == c["id"]              # выбран тот же клип

    # неверное время — пересборка недоступна
    page.e_end.setText("вчера")
    assert not page.btn_rebuild.isEnabled()
    page.fill_editor(page.current_clip())

    # «Хороший» и фильтры
    page.toggle_good()
    assert autoclip.find_clip(autoclip.load_project(cut), c["id"])["status"] == "good"
    page.set_filter(2)                                       # «Хорошие»
    assert page.list.count() == 1
    page.set_filter(1)                                       # «Новые»
    total = len(autoclip.load_project(cut)["clips"])
    assert page.list.count() == total - 1
    page.set_filter(0)

    # «Сохранить как…»
    dest = os.path.join(os.path.dirname(cut), "мой_клип.mp4")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (dest, ""))
    page.save_as()
    assert os.path.isfile(dest)

    # «В корзину»
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    n = page.list.count()
    gone = page.current_clip()
    page.to_trash()
    assert page.list.count() == n - 1
    assert autoclip.find_clip(autoclip.load_project(cut), gone["id"])["status"] == "rejected"
    assert not os.path.exists(os.path.join(cut, gone["file"]))


def answer(monkeypatch, key, asked=None):
    import app as A
    monkeypatch.setattr(A, "ask_choice", lambda parent, text, choices:
                        (asked.append(text) if asked is not None else None) or key)


def test_unsaved_edits_ask_before_leaving(win, cut, monkeypatch):
    page = win.clips
    page.load(cut)
    first = page.current_clip()["id"]
    second = page.list.item(1).data(0x0100)
    page.shift(page.e_end, 2.0)
    answer(monkeypatch, "cancel")
    page.list.setCurrentRow(1)
    assert page.current_clip()["id"] == first and page.pending()   # остались на месте
    answer(monkeypatch, "discard")
    page.list.setCurrentRow(1)
    assert page.current_clip()["id"] == second and not page.pending()

    # «Применить» — клип пересобирается, потом выбирается тот, куда шли
    page.list.setCurrentRow(0)
    old_end = page.current_clip()["end"]
    page.shift(page.e_end, 2.0)
    answer(monkeypatch, "apply")
    page.list.setCurrentRow(1)
    assert wait_for(lambda: not page.busy)
    assert page.current_clip()["id"] == second
    c = autoclip.find_clip(autoclip.load_project(cut), first)
    assert c["end"] == pytest.approx(round(old_end, 1) + 2.0, abs=0.06)


def test_close_asks_about_edits(win, cut, monkeypatch):
    page = win.clips
    page.load(cut)
    first, old_start = page.current_clip()["id"], page.current_clip()["start"]
    page.shift(page.e_start, 2.0)
    asked = []
    answer(monkeypatch, "cancel", asked)
    win.close()
    assert win.isVisible() and asked == ["Есть неприменённые правки."]
    answer(monkeypatch, "apply")
    win.close()
    assert win.isVisible() and page.busy                     # сначала пересборка
    assert wait_for(lambda: not win.isVisible())             # потом окно закрылось само
    c = autoclip.find_clip(autoclip.load_project(cut), first)
    assert c["start"] == pytest.approx(round(old_start, 1) + 2.0, abs=0.06)   # правка применилась
    win.show()
    page.load(cut)
    page.shift(page.e_start, 2.0)
    answer(monkeypatch, "discard")
    win.close()
    assert not win.isVisible()


def test_close_while_cutting_and_plain_close(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    answer(monkeypatch, "apply")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    win.busy = True
    win.close()
    assert win.isVisible() and not win.cancel.is_set()       # нарезка идёт — не закрыли
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    win.close()
    assert not win.isVisible() and win.cancel.is_set()       # остановили и закрыли
    win.busy = False

    win.show()
    import app as A
    monkeypatch.setattr(A, "ask_choice", lambda *a: (_ for _ in ()).throw(AssertionError(a[1])))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: (_ for _ in ()).throw(AssertionError(a[2])))
    win.close()                                              # ничего не идёт — без вопросов
    assert not win.isVisible()


def test_tray_exit_asks_when_watching(win, monkeypatch):
    win.settings["watch"] = True
    asked = []
    answer(monkeypatch, "cancel", asked)
    win.quit_from_tray()
    assert win.isVisible() and asked == ["Слежка за папкой OBS остановится. Выйти?"]
    assert not win._quitting
    answer(monkeypatch, "quit")
    win.quit_from_tray()
    assert not win.isVisible()
    win.settings["watch"] = False


@pytest.mark.skipif(os.name != "nt", reason="блокировка файлов — особенность Windows")
def test_trash_waits_for_locked_file(tmp_path, fake_trash):
    import threading
    f = tmp_path / "клип.mp4"
    f.write_bytes(b"x" * 100)
    h = open(f, "rb")                                    # как проигрыватель, который держит файл
    threading.Timer(0.6, h.close).start()
    autoclip.trash(str(f))                               # дождался и перенёс
    assert not f.exists() and len(os.listdir(fake_trash)) == 1

    g = tmp_path / "занят.mp4"
    g.write_bytes(b"x")
    with open(g, "rb"):
        with pytest.raises(autoclip.AutoClipError):
            autoclip.trash(str(g), wait=0.5)             # так и не отпустили — понятная ошибка
    assert g.exists()                                    # и файл не пропал


# ---------- 3.11, 3.13 ----------

def test_three_rebuilds_keep_one_file(cut, fake_trash):
    c = autoclip.load_project(cut)["clips"][0]
    for _ in range(3):
        autoclip.rebuild_clip(cut, c["id"])
    mp4 = [f for f in os.listdir(cut) if f.endswith(".mp4")]
    assert mp4.count(c["file"]) == 1 and len([f for f in mp4 if f.startswith(c["file"][:3])]) == 1
    old = [f for f in os.listdir(fake_trash) if f.endswith(c["file"])]
    assert len(old) == 3                                             # прежние версии — в корзине


def test_title_edit_renames_file(cut, fake_trash):
    c = autoclip.load_project(cut)["clips"][0]
    new = autoclip.rebuild_clip(cut, c["id"], overrides={"title": "Мой новый заголовок"})
    assert new["title"] == "Мой новый заголовок" and new["file"].startswith(f"{c['num']:02d}_Мой_новый")
    files = os.listdir(cut)
    assert new["file"] in files and c["file"] not in files            # один файл на клип
    assert any(f.endswith(c["file"]) for f in os.listdir(fake_trash))
    again = autoclip.rebuild_clip(cut, c["id"])                       # название помнится
    assert again["file"] == new["file"] and again["title"] == "Мой новый заголовок"


def test_word_edits_and_mat_flags(tmp_path):
    words = [{"s": 0.5, "e": 0.9, "w": "на", "src": 10.5}, {"s": 1.0, "e": 1.4, "w": "бывает", "src": 11.0},
             {"s": 2.0, "e": 2.4, "w": "ёпта", "src": 12.0}, {"s": 3.0, "e": 3.4, "w": "э", "src": 13.0}]
    cfg = {"words_edit": {"10.5": "ну", "13.0": ""}, "mat_words": [12.0]}
    got = autoclip.apply_word_edits(words, cfg)
    assert [w["w"] for w in got] == ["ну", "бывает", "ёпта"]           # «на» → «ну», «э» убрано
    assert got[2].get("mat") and autoclip.is_mat_word(got[2])          # «это мат»


def test_text_tab_edits_survive_rebuild(win, cut, monkeypatch):
    import app as A
    from qtwait import pump
    page = win.clips
    page.load(cut)
    c = page.current_clip()
    assert page.t_words.rowCount() > 0 and page.t_title.text() == c["title"] and not page.pending()
    page.t_words.item(0, 1).setText("исправил")                       # ошибка распознавания
    page.t_words.item(1, 2).setCheckState(A.Qt.Checked)               # «это мат»
    page.t_title.setText("Новое имя")
    page.t_title.textEdited.emit("Новое имя")
    assert {"words_edit", "mat_words", "title"} <= set(page.pending())
    page.rebuild()
    for _ in range(1200):
        if not page.busy:
            break
        pump(50)
    c2 = autoclip.find_clip(autoclip.load_project(cut), c["id"])
    assert c2["title"] == "Новое имя" and "Новое_имя" in c2["file"]
    assert list(c2["overrides"]["words_edit"].values()) == ["исправил"] and len(c2["overrides"]["mat_words"]) == 1
    assert page.t_words.item(0, 1).text() == "исправил" and not page.pending()
    assert c2["bleeps"] >= 1                                           # «это мат» — запикано


def test_remove_without_rating_not_learned(cut, fake_trash):
    import forecast
    proj = autoclip.load_project(cut)
    a, b = proj["clips"][0], proj["clips"][1]
    autoclip.set_status(cut, a["id"], "good")
    autoclip.set_status(cut, b["id"], "good")
    autoclip.remove_clip(cut, b["id"])                                 # дубль — убрать без оценки
    left = autoclip.load_project(cut)["clips"]
    assert b["id"] not in [c["id"] for c in left]
    assert not os.path.exists(os.path.join(cut, b["file"]))
    assert any(f.endswith(b["file"]) for f in os.listdir(fake_trash))  # в корзине, не насовсем
    ids = [s["id"] for s in forecast.collect()]
    assert a["id"] in ids and b["id"] not in ids                       # на обучение не влияет


def test_context_menu(win, cut, monkeypatch):
    import app as A
    from PySide6.QtWidgets import QMessageBox
    page = win.clips
    page.load(cut)
    c = page.current_clip()
    shown = []
    monkeypatch.setattr(A, "show_in_folder", lambda p: shown.append(p))
    menu = page.build_menu()
    acts = {a.text(): a for a in menu.actions() if a.text()}
    assert {"Показать в папке", "Открыть в плеере", "Отправить в Telegram", "Переименовать", "Пересобрать",
            "Хороший", "В корзину (не нравится)", "Удалить (без оценки)"} <= set(acts)
    assert not acts["Отправить в Telegram"].isEnabled()                # бот не подключён
    acts["Показать в папке"].trigger()
    assert shown == [os.path.join(cut, c["file"])]                     # именно этот файл
    acts["Переименовать"].trigger()
    assert page.ed_stack.currentIndex() == 1
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    n = page.list.count()
    acts["Удалить (без оценки)"].trigger()
    assert page.list.count() == n - 1
