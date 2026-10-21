# -*- coding: utf-8 -*-
"""AutoClip — окно на PySide6. Вся обработка — в autoclip.py, здесь только интерфейс."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["PATH"] = HERE + os.pathsep + os.environ.get("PATH", "")

import autoclip  # noqa: E402

from PySide6.QtCore import QByteArray, QObject, QSize, Qt, QTimer, QUrl, Signal  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPalette, QPixmap  # noqa: E402
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer  # noqa: E402
from PySide6.QtMultimediaWidgets import QVideoWidget  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QSlider, QSpinBox,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

QUALITY = {"Максимальное": 14, "Высокое": 16, "Файлы полегче": 19}
WEBCAM = {"Вебка сверху": 0.30, "Вебка снизу": 0.70, "По центру": 0.50}
LLM_MODES = {"Авто": "auto", "Ollama на компьютере": "ollama", "Claude API": "anthropic",
             "Без модели": "none"}
VIDEO_EXT = (".mp4", ".mkv", ".mov", ".flv", ".ts", ".webm")
VIDEO_FILTER = "Видео (*.mp4 *.mkv *.mov *.flv *.ts *.webm);;Все файлы (*.*)"
LATER = "Появится в следующих версиях"

DEFAULTS = {
    "clips": 10, "subs": True, "zoom": True, "hook": False, "bleep": True,
    "sound": "перелистывание", "marks": False, "nick": False, "cam": "Вебка сверху",
    "quality": "Высокое", "llm": "auto", "ollama_model": autoclip.CONFIG["ollama_model"],
    "nick_text": "Final_KFC_Boss", "hashtags": "", "obs_dir": "", "recent": [],
    "geometry": "", "player_geometry": "",
}

BG, PANEL, PANEL2, FG, MUTED, ACCENT = "#15161a", "#1e2027", "#272a33", "#eceef2", "#8b8f9a", "#ff4f6d"

STYLE = f"""
QWidget {{ font-family: "Segoe UI"; font-size: 10pt; color: {FG}; }}
QMainWindow, #page {{ background: {BG}; }}
#nav {{ background: {PANEL}; border: none; outline: none; padding-top: 12px; }}
#nav::item {{ padding: 12px 18px; border-left: 3px solid transparent; }}
#nav::item:selected {{ background: {PANEL2}; border-left: 3px solid {ACCENT}; color: white; }}
#nav::item:hover:!selected {{ background: #23252d; }}
#title {{ font-size: 16pt; font-weight: 600; }}
#hint {{ color: {MUTED}; font-size: 9pt; }}
#drop {{ background: {PANEL}; border: 2px dashed #3a3d48; border-radius: 10px; }}
#drop[hover="true"] {{ border-color: {ACCENT}; }}
#dropText {{ font-size: 12pt; font-weight: 600; }}
QGroupBox {{ background: {PANEL}; border: none; border-radius: 10px; margin-top: 14px;
            padding: 14px 12px 10px 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; color: {MUTED}; }}
QPushButton {{ background: {PANEL2}; border: none; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ background: #323642; }}
QPushButton:disabled {{ color: #5c606b; }}
#accent {{ background: {ACCENT}; color: white; font-size: 13pt; font-weight: 600;
          padding: 12px; border-radius: 8px; }}
#accent:hover {{ background: #e23e5b; }}
#accent[busy="true"] {{ background: #5a3340; }}
QComboBox, QSpinBox, QLineEdit {{ background: {PANEL2}; border: 1px solid #343845;
                                  border-radius: 5px; padding: 4px 8px; min-height: 20px; }}
QComboBox QAbstractItemView {{ background: {PANEL2}; selection-background-color: {ACCENT}; }}
QPlainTextEdit {{ background: {PANEL}; border: none; border-radius: 8px;
                  font-family: Consolas; font-size: 9pt; padding: 6px; }}
QProgressBar {{ background: {PANEL}; border: none; border-radius: 4px; height: 8px;
                text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
#clipList {{ background: {PANEL}; border: none; border-radius: 8px; outline: none; }}
#clipList::item {{ padding: 8px; border-bottom: 1px solid #2a2d36; }}
#clipList::item:selected {{ background: {PANEL2}; border-left: 3px solid {ACCENT}; }}
QSlider::groove:horizontal {{ height: 4px; background: #343845; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 12px; margin: -5px 0; border-radius: 6px; }}
QSplitter::handle {{ background: {BG}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; }}
QToolTip {{ background: {PANEL2}; color: {FG}; border: 1px solid #343845; }}
"""


# ---------------- служебное ----------------

def load_settings():
    data = dict(DEFAULTS)
    try:
        with open(autoclip.SETTINGS_PATH, encoding="utf-8") as f:
            data.update(json.load(f))
    except Exception:
        pass
    return data


def save_settings(data):
    try:
        with open(autoclip.SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def open_path(path):
    if os.name == "nt":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])


def show_in_folder(path):
    if os.name == "nt":
        subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
    else:
        open_path(os.path.dirname(path))


def fmt_ms(ms):
    s = max(0, int(ms // 1000))
    return f"{s // 60}:{s % 60:02d}"


class Bus(QObject):
    """Сигналы из рабочего потока в окно."""
    log = Signal(str)
    progress = Signal(str, float, str)
    done = Signal(object)
    thumb = Signal(int, str, object)


class Stream:
    """Перехват print и ошибок библиотек в лог (у pythonw нет консоли)."""
    def __init__(self, bus):
        self.bus = bus

    def write(self, s):
        if s.strip():
            self.bus.log.emit(s.rstrip())

    def flush(self):
        pass


def page_title(text, hint=""):
    box = QVBoxLayout()
    t = QLabel(text)
    t.setObjectName("title")
    box.addWidget(t)
    if hint:
        h = QLabel(hint)
        h.setObjectName("hint")
        h.setWordWrap(True)
        box.addWidget(h)
    return box


def hint(text):
    h = QLabel(text)
    h.setObjectName("hint")
    h.setWordWrap(True)
    return h


# ---------------- зона перетаскивания ----------------

class DropZone(QFrame):
    files = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(150)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(18)
        self.pic = QLabel()
        self.pic.setFixedSize(0, 0)
        lay.addWidget(self.pic)
        self.text = QLabel("Перетащи сюда запись стрима\nили нажми, чтобы выбрать")
        self.text.setObjectName("dropText")
        self.text.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.text, 1)

    def set_preview(self, pixmap, text):
        if pixmap:
            self.pic.setFixedSize(pixmap.size())
            self.pic.setPixmap(pixmap)
            self.text.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        else:
            self.pic.setFixedSize(0, 0)
            self.pic.clear()
            self.text.setAlignment(Qt.AlignCenter)
        self.text.setText(text)

    def _hover(self, on):
        self.setProperty("hover", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hover(True)

    def dragLeaveEvent(self, e):
        self._hover(False)

    def dropEvent(self, e):
        self._hover(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        paths = [p for p in paths if os.path.isfile(p)]
        if paths:
            self.files.emit(paths)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            paths, _ = QFileDialog.getOpenFileNames(self, "Запись стрима", "", VIDEO_FILTER)
            if paths:
                self.files.emit(paths)


# ---------------- просмотр видео ----------------

class PlayerPanel(QWidget):
    """Видео с перемоткой. Можно открепить в отдельное окно и вернуть."""
    detach_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(280, 420)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget()
        self.video.setStyleSheet("background: black;")
        self.video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.player.setVideoOutput(self.video)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(44)
        self.btn_play.clicked.connect(self.toggle)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.time = QLabel("0:00 / 0:00")
        self.time.setObjectName("hint")
        self.btn_detach = QPushButton("Открепить")
        self.btn_detach.setToolTip("Показать просмотр в отдельном окне, например на втором мониторе")
        self.btn_detach.clicked.connect(self.detach_clicked)

        ctl = QHBoxLayout()
        ctl.addWidget(self.btn_play)
        ctl.addWidget(self.slider, 1)
        ctl.addWidget(self.time)
        ctl.addWidget(self.btn_detach)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.video, 1)
        lay.addLayout(ctl)

        self.player.positionChanged.connect(self._pos)
        self.player.durationChanged.connect(self._dur)
        self.player.playbackStateChanged.connect(self._state)

    def open(self, path, autoplay=True):
        self.player.setSource(QUrl.fromLocalFile(path))
        if autoplay:
            self.player.play()

    def clear(self):
        self.player.stop()
        self.player.setSource(QUrl())

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _pos(self, ms):
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.time.setText(f"{fmt_ms(ms)} / {fmt_ms(self.player.duration())}")

    def _dur(self, ms):
        self.slider.setRange(0, ms)

    def _state(self, st):
        self.btn_play.setText("❚❚" if st == QMediaPlayer.PlayingState else "▶")


class DetachedWindow(QWidget):
    closed = Signal()

    def __init__(self):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("AutoClip — просмотр")
        self.setStyleSheet(f"background: {BG};")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(8, 8, 8, 8)

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)


# ---------------- раздел «Нарезка» ----------------

class CutPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.s = win.settings
        self.files = []
        self.thumb_n = 0
        self.last_out = None
        self.sfx = QMediaPlayer(self)
        self.sfx_out = QAudioOutput(self)
        self.sfx.setAudioOutput(self.sfx_out)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        lay.addLayout(page_title("Нарезка"))

        self.drop = DropZone()
        self.drop.files.connect(self.set_files)
        lay.addWidget(self.drop)

        # --- галочки для всех клипов ---
        box = QGroupBox("Для всех клипов")
        g = QGridLayout(box)
        g.setHorizontalSpacing(24)
        g.setVerticalSpacing(10)
        self.cb_subs = self._check("Субтитры", "subs")
        self.cb_zoom = self._check("Зум на эмоциях", "zoom")
        self.cb_hook = self._check("Хук в начале", "hook", later=True)
        self.cb_marks = self._check("Метки из OBS", "marks", later=True)
        self.cb_nick = self._check("Ник в углу", "nick", later=True)
        self.cb_bleep = self._check("Мат звуком", "bleep")
        g.addWidget(self.cb_subs, 0, 0)
        g.addWidget(self.cb_zoom, 0, 1)
        g.addWidget(self.cb_hook, 0, 2)
        g.addWidget(self.cb_marks, 1, 0)
        g.addWidget(self.cb_nick, 1, 1)

        snd = QHBoxLayout()
        snd.setSpacing(10)
        snd.addWidget(self.cb_bleep)
        self.sound = QComboBox()
        self.sound.setMinimumWidth(170)
        self.sound.currentTextChanged.connect(lambda t: self._set("sound", t) if t else None)
        snd.addWidget(self.sound)
        b = QPushButton("▶")
        b.setToolTip("Прослушать")
        b.setFixedWidth(40)
        b.clicked.connect(self.play_sound)
        snd.addWidget(b)
        snd.addStretch(1)
        g.addLayout(snd, 2, 0, 1, 3)
        self.cb_bleep.toggled.connect(self.sound.setEnabled)

        form = QHBoxLayout()
        form.setSpacing(10)
        form.addWidget(QLabel("Клипов"))
        self.count = QSpinBox()
        self.count.setRange(1, 50)
        self.count.setValue(int(self.s["clips"]))
        self.count.valueChanged.connect(lambda v: self._set("clips", v))
        form.addWidget(self.count)
        form.addSpacing(16)
        form.addWidget(QLabel("Раскладка"))
        self.cam = self._combo(WEBCAM, "cam")
        form.addWidget(self.cam)
        form.addSpacing(16)
        form.addWidget(QLabel("Качество"))
        self.quality = self._combo(QUALITY, "quality")
        form.addWidget(self.quality)
        form.addStretch(1)
        g.addLayout(form, 3, 0, 1, 3)
        lay.addWidget(box)

        # --- запуск и прогресс ---
        self.btn = QPushButton("✂  Нарезать")
        self.btn.setObjectName("accent")
        self.btn.clicked.connect(self.start_or_stop)
        lay.addWidget(self.btn)

        steps = QHBoxLayout()
        self.step_labels = []
        for st in autoclip.STAGES:
            lb = QLabel("○ " + st)
            lb.setObjectName("hint")
            steps.addWidget(lb)
            self.step_labels.append(lb)
        steps.addStretch(1)
        lay.addLayout(steps)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)

        row = QHBoxLayout()
        self.btn_folder = QPushButton("📂  Открыть папку с клипами")
        self.btn_folder.setEnabled(False)
        self.btn_folder.clicked.connect(lambda: self.last_out and open_path(self.last_out))
        self.btn_clips = QPushButton("К клипам  →")
        self.btn_clips.setEnabled(False)
        self.btn_clips.clicked.connect(lambda: self.win.go("clips"))
        row.addWidget(self.btn_folder)
        row.addWidget(self.btn_clips)
        row.addStretch(1)
        lay.addLayout(row)

        self.refresh_sounds()
        self.sound.setEnabled(self.cb_bleep.isChecked())

    # --- виджеты, которые сами запоминают значение ---
    def _set(self, key, value):
        self.s[key] = value
        save_settings(self.s)

    def _check(self, text, key, later=False):
        cb = QCheckBox(text)
        cb.setChecked(bool(self.s.get(key)))
        cb.toggled.connect(lambda v: self._set(key, v))
        if later:
            cb.setEnabled(False)
            cb.setToolTip(LATER)
        return cb

    def _combo(self, values, key):
        cb = QComboBox()
        cb.addItems(list(values))
        if self.s.get(key) in values:
            cb.setCurrentText(self.s[key])
        cb.currentTextChanged.connect(lambda t: self._set(key, t))
        return cb

    # --- звуки ---
    def refresh_sounds(self):
        names = autoclip.list_sounds()
        want = self.s.get("sound")
        self.sound.blockSignals(True)
        self.sound.clear()
        self.sound.addItems(names)
        self.sound.setCurrentText(want if want in names else names[0])
        self.sound.blockSignals(False)

    def play_sound(self):
        self.refresh_sounds()
        path = autoclip.sound_path(self.sound.currentText())
        if path:
            self.sfx.stop()
            self.sfx.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
            self.sfx.play()

    # --- выбор файла и превью ---
    def set_files(self, paths):
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            return
        if self.win.busy:
            self.write("ℹ️  Дождись конца нарезки или останови её.")
            return
        self.files = paths
        names = "\n".join(os.path.basename(p) for p in paths[:4])
        if len(paths) > 4:
            names += f"\n…и ещё {len(paths) - 4}"
        self.drop.set_preview(None, "🎬 " + names)
        self.thumb_n += 1
        threading.Thread(target=self._make_thumb, args=(paths, self.thumb_n), daemon=True).start()

    def _make_thumb(self, paths, n):
        png = os.path.join(tempfile.gettempdir(), f"autoclip_thumb_{os.getpid()}_{n}.png")
        try:
            info = autoclip.thumbnail(paths[0], png, box=200)
        except Exception:
            return                                   # без превью — останется название
        self.win.bus.thumb.emit(n, png, {"paths": paths, **info})

    def show_thumb(self, n, png, info):
        if n != self.thumb_n:                        # пока делали кадр, выбрали другой файл
            return
        pm = QPixmap(png)
        try:
            os.remove(png)                           # наш временный кадр
        except OSError:
            pass
        paths = info["paths"]
        text = (f"{os.path.basename(paths[0])}\n\n{autoclip.fmt_time(info['dur'])}\n"
                f"{info['w']}×{info['h']}, {info['fps']:g} к/с")
        if info["w"] > info["h"]:
            text += "\nгоризонтальное"
        if len(paths) > 1:
            text += f"\n\n…и ещё {len(paths) - 1}"
        self.drop.set_preview(None if pm.isNull() else pm, text)

    # --- запуск ---
    def apply_config(self):
        c = autoclip.CONFIG
        s = self.s
        c["clips"] = int(s["clips"])
        c["subs"] = bool(s["subs"])
        c["zoom"] = bool(s["zoom"])
        c["bleep"] = bool(s["bleep"])
        c["bleep_sound"] = s["sound"]
        c["zoom_focus_y"] = WEBCAM.get(s["cam"], 0.3)
        c["quality"] = QUALITY.get(s["quality"], 16)
        c["llm"] = s["llm"]
        c["ollama_model"] = s["ollama_model"] or DEFAULTS["ollama_model"]

    def start_or_stop(self):
        if self.win.busy:
            self.win.cancel.set()
            self.btn.setText("Останавливаю…")
            self.btn.setEnabled(False)
            return
        if not self.files:
            self.drop.mousePressEvent(_LeftClick())
            if not self.files:
                return
        self.apply_config()
        self.win.start_cut(list(self.files))
        self.btn.setText("■  Остановить")
        self._busy_style(True)
        self.btn_folder.setEnabled(False)
        self.btn_clips.setEnabled(False)
        self.bar.setValue(0)
        for lb, st in zip(self.step_labels, autoclip.STAGES):
            lb.setText("○ " + st)

    def _busy_style(self, on):
        self.btn.setProperty("busy", on)
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)

    def show_progress(self, stage, pct, msg):
        stages = autoclip.STAGES
        if stage not in stages:
            return
        i = stages.index(stage)
        self.bar.setValue(int((i + pct / 100) / len(stages) * 1000))
        for j, (lb, st) in enumerate(zip(self.step_labels, stages)):
            if j < i or (j == i and pct >= 100):
                lb.setText("✓ " + st)
            elif j == i:
                lb.setText(f"● {st} {pct:.0f}%")

    def finished(self, out):
        self.btn.setText("✂  Нарезать")
        self.btn.setEnabled(True)
        self._busy_style(False)
        if out:
            self.last_out = out
            self.btn_folder.setEnabled(True)
            self.btn_clips.setEnabled(True)
        else:
            self.bar.setValue(0)

    def write(self, msg):
        self.log.appendPlainText(msg)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())


class _LeftClick:
    def button(self):
        return Qt.LeftButton


# ---------------- раздел «Клипы» ----------------

class ClipsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.proj = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        lay.addLayout(page_title("Клипы"))

        top = QHBoxLayout()
        self.projects = QComboBox()
        self.projects.setMinimumWidth(360)
        self.projects.activated.connect(lambda i: self.load(self.projects.itemData(i)))
        top.addWidget(self.projects, 1)
        b = QPushButton("Открыть папку с клипами…")
        b.clicked.connect(self.pick)
        top.addWidget(b)
        lay.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setObjectName("clipList")
        self.list.currentItemChanged.connect(self.select)
        split.addWidget(self.list)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 0, 0, 0)
        self.player_slot = QVBoxLayout()
        self.player = PlayerPanel()
        self.player.detach_clicked.connect(self.win.toggle_detach)
        self.player_slot.addWidget(self.player)
        self.detached_note = QWidget()
        dn = QVBoxLayout(self.detached_note)
        dn.addStretch(1)
        note = hint("Просмотр открыт в отдельном окне.")
        note.setWordWrap(False)
        dn.addWidget(note, 0, Qt.AlignCenter)
        back = QPushButton("Вернуть сюда")
        back.clicked.connect(self.win.toggle_detach)
        dn.addWidget(back, 0, Qt.AlignCenter)
        dn.addStretch(1)
        self.detached_note.hide()
        self.player_slot.addWidget(self.detached_note)
        rl.addLayout(self.player_slot, 1)

        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rl.addWidget(self.info)
        btns = QHBoxLayout()
        self.btn_show = QPushButton("Показать в папке")
        self.btn_show.clicked.connect(self.show_file)
        btns.addWidget(self.btn_show)
        btns.addStretch(1)
        rl.addLayout(btns)
        split.addWidget(right)
        split.setSizes([360, 640])
        lay.addWidget(split, 1)

        self.empty = hint("Здесь будут клипы. Нарежь запись или открой папку с клипами.")
        lay.addWidget(self.empty)
        self.refresh_recent()

    def refresh_recent(self):
        recent = [p for p in self.win.settings.get("recent", []) if os.path.isfile(p)]
        self.win.settings["recent"] = recent
        self.projects.clear()
        for p in recent:
            self.projects.addItem(os.path.basename(os.path.dirname(p)), p)

    def remember(self, pp):
        recent = [p for p in self.win.settings.get("recent", []) if p != pp]
        self.win.settings["recent"] = [pp] + recent[:9]
        save_settings(self.win.settings)
        self.refresh_recent()

    def pick(self):
        d = QFileDialog.getExistingDirectory(self, "Папка с клипами (…_clips)")
        if d:
            self.load(d)

    def load(self, path):
        try:
            proj = autoclip.load_project(path)
        except autoclip.AutoClipError as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            return
        self.proj = proj
        self.remember(proj["_path"])
        self.projects.setCurrentIndex(0)
        self.list.clear()
        for c in sorted(proj["clips"], key=lambda c: c["num"]):
            if c["status"] == "rejected":
                continue
            st = autoclip.STATUSES.get(c["status"], c["status"])
            it = QListWidgetItem(
                f"{c['num']:02d}   ★ {c['score']:.1f}   {c['title']}\n"
                f"      {st} · {autoclip.fmt_time(c['start'])}–{autoclip.fmt_time(c['end'])}"
                f" · {c['end'] - c['start']:.0f} с")
            it.setData(Qt.UserRole, c["id"])
            it.setSizeHint(QSize(0, 52))
            self.list.addItem(it)
        self.empty.setVisible(self.list.count() == 0)
        if self.list.count():
            self.list.setCurrentRow(0)

    def current_clip(self):
        it = self.list.currentItem()
        if not (it and self.proj):
            return None
        return autoclip.find_clip(self.proj, it.data(Qt.UserRole))

    def clip_path(self, c):
        return os.path.join(os.path.dirname(self.proj["_path"]), c["file"])

    def select(self, *_):
        c = self.current_clip()
        if not c:
            self.player.clear()
            self.info.setText("")
            return
        path = self.clip_path(c)
        if os.path.isfile(path):
            self.player.open(path)
        parts = ", ".join(f"{k} {v:+.1f}" for k, v in c.get("score_parts", {}).items()
                          if abs(v) >= 0.05)
        lines = [f"<b>{c['title']}</b>",
                 f"Оценка {c['score']:.1f}" + (f" — {parts}" if parts else ""),
                 f"В записи: {autoclip.fmt_time(c['start'])}–{autoclip.fmt_time(c['end'])}, "
                 f"зумов: {len(c['zooms'])}, запикано: {c['bleeps'] if c['bleeps'] is not None else '-'}"]
        if c.get("reason"):
            lines.append(f"Почему: {c['reason']}")
        self.info.setText("<br>".join(lines))

    def show_file(self):
        c = self.current_clip()
        if c:
            show_in_folder(self.clip_path(c))


# ---------------- раздел «Настройки» ----------------

class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.s = win.settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(6)
        lay.addLayout(page_title("Настройки"))

        # --- языковая модель ---
        box = QGroupBox("Языковая модель")
        f = QFormLayout(box)
        self.llm = QComboBox()
        self.llm.addItems(list(LLM_MODES))
        cur = next((k for k, v in LLM_MODES.items() if v == self.s["llm"]), "Авто")
        self.llm.setCurrentText(cur)
        self.llm.currentTextChanged.connect(lambda t: self._set("llm", LLM_MODES[t]))
        f.addRow("Как искать моменты", self.llm)
        self.ollama = QLineEdit(self.s["ollama_model"])
        self.ollama.textChanged.connect(lambda t: self._set("ollama_model", t.strip()))
        f.addRow("Модель Ollama", self.ollama)
        row = QHBoxLayout()
        b = QPushButton("Проверить")
        b.clicked.connect(self.check_llm)
        row.addWidget(b)
        self.llm_state = hint("")
        row.addWidget(self.llm_state, 1)
        f.addRow("", row)
        f.addRow(hint("Авто: Ollama, если запущена; иначе Claude API, если задан ключ "
                      "ANTHROPIC_API_KEY; иначе только по звуку и речи."))
        lay.addWidget(box)

        # --- звуки ---
        box = QGroupBox("Звуки для мата")
        f = QFormLayout(box)
        b = QPushButton("Открыть папку своих звуков")
        b.clicked.connect(self.open_sounds)
        f.addRow(b)
        f.addRow(hint("Положи туда свой mp3 или wav — он появится в списке на «Нарезке»."))
        lay.addWidget(box)

        # --- экспорт ---
        box = QGroupBox("Экспорт")
        f = QFormLayout(box)
        f.addRow(hint("Качество выбирается на «Нарезке». Пресеты под площадки — " + LATER.lower() + "."))
        lay.addWidget(box)

        # --- на будущее ---
        box = QGroupBox("Канал и OBS")
        f = QFormLayout(box)
        obs = QHBoxLayout()
        self.obs = QLineEdit(self.s["obs_dir"])
        self.obs.setPlaceholderText("Папка, куда OBS пишет записи")
        self.obs.textChanged.connect(lambda t: self._set("obs_dir", t.strip()))
        obs.addWidget(self.obs, 1)
        b = QPushButton("Выбрать…")
        b.clicked.connect(self.pick_obs)
        obs.addWidget(b)
        f.addRow("Папка OBS", obs)
        self.nick = QLineEdit(self.s["nick_text"])
        self.nick.textChanged.connect(lambda t: self._set("nick_text", t.strip()))
        f.addRow("Ник", self.nick)
        self.tags = QLineEdit(self.s["hashtags"])
        self.tags.setPlaceholderText("#стрим #игры")
        self.tags.textChanged.connect(lambda t: self._set("hashtags", t.strip()))
        f.addRow("Хэштеги", self.tags)
        f.addRow(hint("Запоминается уже сейчас. Слежка за папкой, ник в углу и хэштеги — "
                      + LATER.lower() + "."))
        lay.addWidget(box)

        lay.addStretch(1)
        lay.addWidget(hint(f"Настройки хранятся в {autoclip.user_dir()}"))

    def _set(self, key, value):
        self.s[key] = value
        save_settings(self.s)

    def pick_obs(self):
        d = QFileDialog.getExistingDirectory(self, "Папка записей OBS", self.obs.text())
        if d:
            self.obs.setText(os.path.normpath(d))
            self._set("obs_dir", self.obs.text())

    def open_sounds(self):
        autoclip.prepare_sounds()
        open_path(autoclip.SOUNDS_DIR)

    def check_llm(self):
        autoclip.CONFIG["ollama_model"] = self.s["ollama_model"] or DEFAULTS["ollama_model"]
        ollama = "Ollama работает" if autoclip._ollama_alive() else "Ollama не запущена"
        key = "ключ Claude есть" if os.environ.get("ANTHROPIC_API_KEY") else "ключа Claude нет"
        mode = autoclip.pick_llm(self.s["llm"])
        names = {"ollama": "Ollama", "anthropic": "Claude API", "none": "без модели"}
        self.llm_state.setText(f"{ollama}, {key}. Сейчас будет: {names.get(mode, mode)}.")


# ---------------- главное окно ----------------

class MainWindow(QMainWindow):
    PAGES = (("cut", "✂   Нарезка"), ("clips", "🎬   Клипы"), ("weekly", "📅   Подборка"),
             ("settings", "⚙   Настройки"))

    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.busy = False
        self.cancel = threading.Event()
        self.detached = None
        self.bus = Bus()

        self.setWindowTitle("AutoClip")
        self.resize(1200, 860)
        self.setMinimumSize(980, 720)
        if self.settings.get("geometry"):
            self.restoreGeometry(QByteArray.fromHex(self.settings["geometry"].encode()))

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(190)
        f = QFont("Segoe UI", 11)
        for _, text in self.PAGES:
            it = QListWidgetItem(text)
            it.setFont(f)
            self.nav.addItem(it)
        root.addWidget(self.nav)

        self.stack = QStackedWidget()
        self.cut = CutPage(self)
        self.clips = ClipsPage(self)
        weekly = QWidget()
        wl = QVBoxLayout(weekly)
        wl.setContentsMargins(24, 20, 24, 20)
        wl.addLayout(page_title("Подборка", "Ролик из хороших клипов за неделю. " + LATER + "."))
        wl.addStretch(1)
        self.settings_page = SettingsPage(self)
        for w in (self.cut, self.clips, weekly, self.settings_page):
            w.setObjectName("page")
            self.stack.addWidget(w)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.nav.currentRowChanged.connect(self._page)
        self.nav.setCurrentRow(0)

        self.bus.log.connect(self.cut.write)
        self.bus.progress.connect(self.cut.show_progress)
        self.bus.done.connect(self.finished)
        self.bus.thumb.connect(self.cut.show_thumb)
        autoclip.log = lambda m: self.bus.log.emit(str(m))
        sys.stdout = Stream(self.bus)
        sys.stderr = Stream(self.bus)

        try:
            autoclip.need_ffmpeg()
            autoclip.prepare_sounds()
            self.cut.refresh_sounds()
            self.cut.write("Выбери запись и нажми «Нарезать».")
        except autoclip.AutoClipError as e:
            self.cut.write(str(e))
        if self.settings["recent"]:
            QTimer.singleShot(0, lambda: self.clips.load(self.settings["recent"][0]))

    def _page(self, i):
        self.stack.setCurrentIndex(i)
        if self.PAGES[i][0] != "clips" and not self.detached:
            self.clips.player.player.pause()

    def go(self, key):
        self.nav.setCurrentRow([k for k, _ in self.PAGES].index(key))

    # --- нарезка в фоне ---
    def start_cut(self, files):
        self.busy = True
        self.cancel.clear()
        threading.Thread(target=self._worker, args=(files,), daemon=True).start()

    def _worker(self, files):
        out = None
        for i, f in enumerate(files, 1):
            if len(files) > 1:
                self.bus.log.emit(f"\n===== {i}/{len(files)}: {os.path.basename(f)} =====")
            try:
                out = autoclip.process(
                    f, progress=lambda st, pct, msg: self.bus.progress.emit(st, float(pct), msg),
                    cancel=self.cancel) or out
            except autoclip.Cancelled as e:
                self.bus.log.emit(str(e))
                break
            except autoclip.AutoClipError as e:
                self.bus.log.emit(str(e))
            except Exception:
                self.bus.log.emit("❌ Неожиданная ошибка:\n" + traceback.format_exc()[-1500:])
        self.bus.done.emit(out)

    def finished(self, out):
        self.busy = False
        self.cut.finished(out)
        if out:
            self.clips.load(out)
            self.cut.write("Клипы — в разделе «Клипы».")

    # --- открепляемый просмотр ---
    def toggle_detach(self):
        p = self.clips.player
        if self.detached is None:
            self.detached = DetachedWindow()
            self.detached.closed.connect(self._reattach)
            self.detached.lay.addWidget(p)
            p.btn_detach.setText("Вернуть")
            if self.settings.get("player_geometry"):
                self.detached.restoreGeometry(
                    QByteArray.fromHex(self.settings["player_geometry"].encode()))
            else:
                self.detached.resize(560, 960)
            self.clips.detached_note.show()
            self.detached.show()
        else:
            self.detached.close()                    # closeEvent вернёт просмотр

    def _reattach(self):
        w = self.detached
        if w is None:
            return
        self.settings["player_geometry"] = bytes(w.saveGeometry().toHex()).decode()
        save_settings(self.settings)
        self.detached = None
        p = self.clips.player
        self.clips.player_slot.insertWidget(0, p)
        p.btn_detach.setText("Открепить")
        self.clips.detached_note.hide()
        w.deleteLater()

    def closeEvent(self, e):
        if self.busy:
            r = QMessageBox.question(self, "AutoClip", "Нарезка ещё идёт. Остановить и закрыть?")
            if r != QMessageBox.Yes:
                e.ignore()
                return
            self.cancel.set()
        if self.detached:
            self.detached.close()
        self.clips.player.clear()
        self.settings["geometry"] = bytes(self.saveGeometry().toHex()).decode()
        save_settings(self.settings)
        super().closeEvent(e)


def dark_palette(app):
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in ((QPalette.Window, BG), (QPalette.WindowText, FG), (QPalette.Base, PANEL),
                        (QPalette.AlternateBase, PANEL2), (QPalette.Text, FG),
                        (QPalette.Button, PANEL2), (QPalette.ButtonText, FG),
                        (QPalette.Highlight, ACCENT), (QPalette.HighlightedText, "#ffffff"),
                        (QPalette.ToolTipBase, PANEL2), (QPalette.ToolTipText, FG),
                        (QPalette.PlaceholderText, MUTED)):
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#5c606b"))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#5c606b"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#5c606b"))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)


def main():
    autoclip.migrate_user_data()
    app = QApplication(sys.argv)
    dark_palette(app)
    win = MainWindow()
    win.show()
    videos = [a for a in sys.argv[1:] if a.lower().endswith(VIDEO_EXT) and os.path.isfile(a)]
    if videos:
        win.cut.set_files(videos)
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # у pythonw нет консоли — показываем ошибку окном
        msg = traceback.format_exc()[-1500:]
        try:
            QMessageBox.critical(None, "AutoClip", msg)
        except Exception:
            pass
        raise
