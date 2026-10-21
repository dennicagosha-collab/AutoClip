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

from PySide6.QtCore import (  # noqa: E402
    QByteArray, QEventLoop, QObject, QSize, Qt, QTimer, QUrl, Signal,
)
from PySide6.QtGui import (  # noqa: E402
    QColor, QFont, QKeySequence, QPainter, QPalette, QPixmap, QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer  # noqa: E402
from PySide6.QtMultimediaWidgets import QVideoWidget  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QSlider, QSpinBox,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget,
    QAbstractItemView,
)

WEBCAM = {"Вебка сверху": 0.30, "Вебка снизу": 0.70, "По центру": 0.50}
LLM_MODES = {"Авто": "auto", "Ollama на компьютере": "ollama", "Claude API": "anthropic",
             "Без модели": "none"}
VIDEO_EXT = (".mp4", ".mkv", ".mov", ".flv", ".ts", ".webm")
VIDEO_FILTER = "Видео (*.mp4 *.mkv *.mov *.flv *.ts *.webm);;Все файлы (*.*)"
LATER = "Появится в следующих версиях"

DEFAULTS = {
    "clips": 10, "subs": True, "zoom": True, "hook": True, "bleep": True,
    "sound": "перелистывание", "marks": True, "nick": False, "cam": "Вебка сверху",
    "sub_pos": autoclip.sub_position_name(autoclip.CONFIG["sub_y"]), "safe_zone": True,
    "preset": autoclip.CONFIG["preset"], "llm": "auto", "ollama_model": autoclip.CONFIG["ollama_model"],
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
#rebuild {{ background: #3a2a33; color: white; font-weight: 600; padding: 8px 18px; }}
#rebuild:hover {{ background: #4a3340; }}
#filter {{ padding: 5px 12px; border-radius: 12px; }}
#filter:checked {{ background: {ACCENT}; color: white; }}
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
    rebuilt = Signal(str, object)          # id клипа, текст ошибки или None


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

class SubsPreview(QWidget):
    """Схема кадра 9:16: где будут субтитры и какие поля закрывают кнопки соцсетей."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(72, 128)
        self.setToolTip("Где будут субтитры. Красным — зона кнопок и подписей соцсетей.")
        self.sub_y, self.safe = 0.6, True

    def set_state(self, sub_y, safe):
        self.sub_y, self.safe = sub_y, safe
        self.update()

    def paintEvent(self, e):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(0, 0, w, h, QColor("#0d0e11"))
        p.setPen(QColor("#3a3d48"))
        p.drawRect(0, 0, w - 1, h - 1)
        if self.safe:
            z = autoclip.SAFE_ZONE
            red = QColor(255, 79, 109, 70)
            p.fillRect(0, 0, w, int(z["top"] * h), red)
            p.fillRect(0, h - int(z["bottom"] * h), w, int(z["bottom"] * h), red)
            p.fillRect(w - int(z["right"] * w), int(z["top"] * h), int(z["right"] * w),
                       h - int((z["top"] + z["bottom"]) * h), red)
            p.fillRect(0, int(z["top"] * h), int(z["left"] * w),
                       h - int((z["top"] + z["bottom"]) * h), red)
        lay = autoclip.subs_layout(1080, 1920, dict(autoclip.CONFIG, sub_y=self.sub_y,
                                                    safe_zone=self.safe))
        l, _, r, _ = lay["box"]
        bw = (r - l) / 1080 * w * 0.8
        cx, cy = lay["x"] / 1080 * w, lay["y"] / 1920 * h
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(int(cx - bw / 2), int(cy - 4), int(bw), 8, 3, 3)
        p.setBrush(QColor("#ffe600"))
        p.drawRoundedRect(int(cx - bw / 6), int(cy - 4), int(bw / 3), 8, 3, 3)
        p.end()


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

class ClickableVideo(QVideoWidget):
    clicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class PlayerPanel(QWidget):
    """Видео с перемоткой. Можно открепить в отдельное окно и вернуть.
    Клип открывается на паузе с первым кадром; играет по ▶, клику по видео или пробелу."""
    detach_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(280, 420)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = ClickableVideo()
        self.video.setCursor(Qt.PointingHandCursor)
        self.video.setToolTip("Клик или пробел — пуск и пауза")
        self.video.clicked.connect(self.toggle)
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
        self.player.mediaStatusChanged.connect(self._loaded)
        self._first_frame = False
        self._may_play = False         # играть можно только после действия пользователя

    def open(self, path, autoplay=False):
        self._first_frame = not autoplay
        self._may_play = autoplay
        self.audio.setMuted(not autoplay)    # пока показываем первый кадр — без звука
        self.player.setSource(QUrl.fromLocalFile(path))
        if autoplay:
            self.play()

    def play(self):
        self._may_play = True
        self.audio.setMuted(False)
        self.player.play()

    def _loaded(self, status):
        # пауза сразу после загрузки показывает первый кадр без звука
        if status == QMediaPlayer.LoadedMedia and self._first_frame:
            self._first_frame = False
            self.player.pause()
            QTimer.singleShot(400, self._ensure_frame)

    def _ensure_frame(self):
        # бывает, что первый кадр не пришёл — просим его ещё раз
        if not self._may_play and not self.video.videoSink().videoFrame().isValid():
            self.player.setPosition(0)
            self.player.pause()

    def clear(self):
        self.player.stop()
        self.player.setSource(QUrl())

    def release_file(self, ms=300):
        """Закрыть файл и дать проигрывателю его отпустить: иначе Windows не даст
        перенести или заменить клип (проигрыватель закрывает файл не сразу)."""
        self.clear()
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self._may_play = False
            self.player.pause()
        else:
            self.play()

    def _pos(self, ms):
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.time.setText(f"{fmt_ms(ms)} / {fmt_ms(self.player.duration())}")

    def _dur(self, ms):
        self.slider.setRange(0, ms)

    def _state(self, st):
        if st == QMediaPlayer.PlayingState and not self._may_play:
            # проигрыватель Qt иногда сам уходит из паузы в воспроизведение — не даём
            self.player.pause()
            self.player.setPosition(0)
            return
        self.btn_play.setText("❚❚" if st == QMediaPlayer.PlayingState else "▶")


class DetachedWindow(QWidget):
    closed = Signal()

    def __init__(self):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("AutoClip — просмотр")
        self.setStyleSheet(f"background: {BG};")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(8, 8, 8, 8)
        self.space = QShortcut(QKeySequence(Qt.Key_Space), self)

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
        self.cb_hook = self._check("Хук в начале", "hook")
        self.cb_hook.setToolTip("1–2 секунды яркой реакции из этого же клипа в самом начале. "
                                "Ставится, только где есть сильный момент.")
        self.cb_marks = self._check("Метки из OBS", "marks")
        self.cb_marks.setToolTip("Моменты, где ты нажал «Добавить маркер главы» в OBS, "
                                 "идут первыми. Нужна запись в Hybrid MP4.")
        self.cb_nick = self._check("Ник в углу", "nick", later=True)
        self.cb_bleep = self._check("Мат звуком", "bleep")
        g.addWidget(self.cb_subs, 0, 0)
        g.addWidget(self.cb_zoom, 0, 1)
        g.addWidget(self.cb_hook, 0, 2)
        g.addWidget(self.cb_marks, 1, 0)
        g.addWidget(self.cb_nick, 1, 1)

        subs = QHBoxLayout()
        subs.setSpacing(10)
        subs.addWidget(QLabel("Субтитры"))
        self.sub_pos = self._combo(autoclip.SUB_POSITIONS, "sub_pos")
        subs.addWidget(self.sub_pos)
        self.cb_safe = self._check("Сейф-зона соцсетей", "safe_zone")
        self.cb_safe.setToolTip("Субтитры не заходят под кнопки, ник и подпись "
                                "TikTok, Shorts и Reels")
        subs.addSpacing(8)
        subs.addWidget(self.cb_safe)
        subs.addStretch(1)
        g.addLayout(subs, 2, 0, 1, 3)
        self.preview = SubsPreview()
        g.addWidget(self.preview, 0, 3, 5, 1, Qt.AlignRight | Qt.AlignTop)
        for w in (self.sub_pos, self.cb_safe, self.cb_subs):
            (w.currentTextChanged if isinstance(w, QComboBox) else w.toggled).connect(
                self._update_preview)
        self.cb_subs.toggled.connect(self.sub_pos.setEnabled)
        self.cb_subs.toggled.connect(self.cb_safe.setEnabled)
        self.sub_pos.setEnabled(self.cb_subs.isChecked())
        self.cb_safe.setEnabled(self.cb_subs.isChecked())

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
        g.addLayout(snd, 3, 0, 1, 3)
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
        form.addWidget(QLabel("Пресет"))
        self.preset = QComboBox()
        self.preset.setMinimumWidth(170)
        self.preset.setToolTip("Размер, кадры и битрейт клипов. Свой пресет — в «Настройках».")
        self.preset.currentTextChanged.connect(lambda t: self._set("preset", t) if t else None)
        form.addWidget(self.preset)
        form.addStretch(1)
        g.addLayout(form, 4, 0, 1, 3)
        lay.addWidget(box)
        self._update_preview()

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
        self.refresh_presets()
        self.sound.setEnabled(self.cb_bleep.isChecked())

    def _update_preview(self, *_):
        self.preview.set_state(autoclip.SUB_POSITIONS.get(self.sub_pos.currentText(), 0.6),
                               self.cb_safe.isChecked())
        self.preview.setVisible(self.cb_subs.isChecked())

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

    def refresh_presets(self):
        names = [p["name"] for p in autoclip.load_presets()]
        want = self.s.get("preset")
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItems(names)
        self.preset.setCurrentText(want if want in names else names[0])
        self.preset.blockSignals(False)
        self.s["preset"] = self.preset.currentText()

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
            info["marks"] = len(autoclip.read_markers(paths[0]))
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
        text += f"\nметок из OBS: {info.get('marks', 0)}"
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
        c["hook"] = bool(s["hook"])
        c["marks"] = bool(s["marks"])
        c["sub_y"] = autoclip.SUB_POSITIONS.get(s["sub_pos"], autoclip.CONFIG["sub_y"])
        c["safe_zone"] = bool(s["safe_zone"])
        c["bleep_sound"] = s["sound"]
        c["zoom_focus_y"] = WEBCAM.get(s["cam"], 0.3)
        c["preset"] = s["preset"]
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

FILTERS = (("Все", None), ("Новые", {"new"}), ("Хорошие", {"good"}), ("Выложены", {"published"}))
SHIFT = 2.0          # шаг сдвига начала и конца, сек


class ClipsPage(QWidget):
    """Список клипов нарезки и редактор выбранного клипа."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.proj = None
        self.base = {}             # значения выбранного клипа до правок
        self.busy = False          # идёт пересборка
        self._row = -1             # выбранная строка — чтобы вернуть, если передумал уходить

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
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        frow = QHBoxLayout()
        frow.setSpacing(4)
        self.filter_btns = []
        for i, (name, _) in enumerate(FILTERS):
            fb = QPushButton(name)
            fb.setCheckable(True)
            fb.setObjectName("filter")
            fb.clicked.connect(lambda _, i=i: self.set_filter(i))
            frow.addWidget(fb)
            self.filter_btns.append(fb)
        frow.addStretch(1)
        ll.addLayout(frow)
        self.filter = 0
        self.filter_btns[0].setChecked(True)
        self.list = QListWidget()
        self.list.setObjectName("clipList")
        self.list.currentRowChanged.connect(self._row_changed)
        self.list.itemDoubleClicked.connect(lambda _: self.player.play())
        ll.addWidget(self.list, 1)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 0, 0, 0)
        self.player_slot = QVBoxLayout()
        self.player = PlayerPanel()
        sc = QShortcut(QKeySequence(Qt.Key_Space), self)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self.player.toggle)
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

        # --- редактор клипа ---
        self.editor = QGroupBox("Этот клип")
        ed = QVBoxLayout(self.editor)
        ed.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(14)
        self.e_hook = QCheckBox("Хук")
        self.e_zoom = QCheckBox("Зум")
        self.e_bleep = QCheckBox("Мат звуком")
        self.e_subs = QCheckBox("Субтитры")
        self.e_pos = QComboBox()
        self.e_pos.addItems(list(autoclip.SUB_POSITIONS))
        self.e_safe = QCheckBox("Сейф-зона")
        for w in (self.e_hook, self.e_zoom, self.e_bleep, self.e_subs):
            row.addWidget(w)
            w.toggled.connect(self._changed)
        row.addWidget(self.e_pos)
        row.addWidget(self.e_safe)
        self.e_pos.currentTextChanged.connect(self._changed)
        self.e_safe.toggled.connect(self._changed)
        self.e_subs.toggled.connect(self.e_pos.setEnabled)
        self.e_subs.toggled.connect(self.e_safe.setEnabled)
        row.addStretch(1)
        ed.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.e_start = QLineEdit()
        self.e_end = QLineEdit()
        for label, edit in (("Начало", self.e_start), ("Конец", self.e_end)):
            row.addWidget(QLabel(label))
            minus = QPushButton(f"−{SHIFT:g} с")
            plus = QPushButton(f"+{SHIFT:g} с")
            minus.clicked.connect(lambda _, e=edit: self.shift(e, -SHIFT))
            plus.clicked.connect(lambda _, e=edit: self.shift(e, SHIFT))
            edit.setFixedWidth(92)
            edit.setToolTip("Время в записи: 1:18 или 0:01:18.5")
            edit.textChanged.connect(self._changed)
            row.addWidget(minus)
            row.addWidget(edit)
            row.addWidget(plus)
            row.addSpacing(12)
        self.e_len = hint("")
        row.addWidget(self.e_len)
        row.addStretch(1)
        ed.addLayout(row)

        row = QHBoxLayout()
        self.btn_rebuild = QPushButton("🔁  Пересобрать")
        self.btn_rebuild.setObjectName("rebuild")
        self.btn_rebuild.clicked.connect(self.rebuild)
        row.addWidget(self.btn_rebuild)
        self.state = hint("")
        row.addWidget(self.state, 1)
        ed.addLayout(row)

        row = QHBoxLayout()
        self.btn_good = QPushButton("👍  Хороший")
        self.btn_good.clicked.connect(self.toggle_good)
        self.btn_trash = QPushButton("🗑  В корзину")
        self.btn_trash.clicked.connect(self.to_trash)
        self.btn_save = QPushButton("Сохранить как…")
        self.btn_save.clicked.connect(self.save_as)
        self.btn_show = QPushButton("Показать в папке")
        self.btn_show.clicked.connect(self.show_file)
        for w in (self.btn_good, self.btn_trash, self.btn_save, self.btn_show):
            row.addWidget(w)
        row.addStretch(1)
        ed.addLayout(row)
        rl.addWidget(self.editor)
        self.editor.setEnabled(False)

        split.addWidget(right)
        split.setSizes([450, 650])
        lay.addWidget(split, 1)

        self.empty = hint("Здесь будут клипы. Нарежь запись или открой папку с клипами.")
        lay.addWidget(self.empty)
        self.win.bus.rebuilt.connect(self._rebuilt)
        self.refresh_recent()

    # ---------- нарезки ----------
    def refresh_recent(self):
        recent = [p for p in self.win.settings.get("recent", []) if os.path.isfile(p)]
        self.win.settings["recent"] = recent
        self.projects.clear()
        for p in recent:
            label = os.path.basename(os.path.dirname(p))
            try:
                with open(p, encoding="utf-8") as f:
                    run = json.load(f).get("run", {}).get("date", "")
                if run:                              # «2026-10-21T23:15:02» → «21.10 23:15»
                    label += f"  ·  нарезка {run[8:10]}.{run[5:7]} {run[11:16]}"
            except (OSError, ValueError):
                pass
            self.projects.addItem(label, p)

    def remember(self, pp):
        recent = [p for p in self.win.settings.get("recent", []) if p != pp]
        self.win.settings["recent"] = [pp] + recent[:9]
        save_settings(self.win.settings)
        self.refresh_recent()

    def pick(self):
        d = QFileDialog.getExistingDirectory(self, "Папка с клипами (…_clips)")
        if d:
            self.load(d)

    def load(self, path, select_id=None):
        if not self._leave_ok():
            return
        try:
            proj = autoclip.load_project(path)
        except autoclip.AutoClipError as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            return
        self.proj = proj
        self.remember(proj["_path"])
        self.projects.setCurrentIndex(0)
        self.refill(select_id)

    def reload(self, select_id=None):
        """Перечитать project.json после изменений ядра."""
        if self.proj:
            self.proj = autoclip.load_project(self.proj["_path"])
            self.refill(select_id)

    # ---------- список ----------
    def set_filter(self, i):
        for j, b in enumerate(self.filter_btns):
            b.setChecked(j == i)
        if i == self.filter:
            return
        if not self._leave_ok():
            self.filter_btns[i].setChecked(False)
            self.filter_btns[self.filter].setChecked(True)
            return
        self.filter = i
        c = self.current_clip()
        self.refill(c["id"] if c else None)

    def refill(self, select_id=None):
        want = FILTERS[self.filter][1]
        self.list.blockSignals(True)
        self.list.clear()
        clips = [c for c in sorted(self.proj["clips"], key=lambda c: c["num"])
                 if c["status"] != "rejected" and (want is None or c["status"] in want)]
        row = 0
        for i, c in enumerate(clips):
            it = QListWidgetItem(
                f"{c['num']:02d}   ★ {c['score']:.1f}   {'📍 ' if c.get('marks') else ''}"
                f"{c['title']}\n"
                f"      {autoclip.fmt_time(c['start'])}–{autoclip.fmt_time(c['end'])}"
                f" · {c['end'] - c['start']:.0f} с · " + " · ".join(autoclip.clip_tags(c)))
            if c.get("marks"):
                it.setToolTip("Клип по метке из OBS")
            it.setData(Qt.UserRole, c["id"])
            it.setSizeHint(QSize(0, 52))
            self.list.addItem(it)
            if c["id"] == select_id:
                row = i
        self.list.blockSignals(False)
        total = sum(c["status"] != "rejected" for c in self.proj["clips"])
        self.empty.setText("Здесь будут клипы. Нарежь запись или открой папку с клипами."
                           if total == 0 else "В этом фильтре клипов нет.")
        self.empty.setVisible(self.list.count() == 0)
        self._row = -1
        if self.list.count():
            self.list.setCurrentRow(row)
            if self.list.currentRow() == row and self._row != row:
                self._row_changed(row)
        else:
            self.select()

    def current_clip(self):
        it = self.list.currentItem()
        if not (it and self.proj):
            return None
        return autoclip.find_clip(self.proj, it.data(Qt.UserRole))

    def clip_path(self, c):
        return os.path.join(os.path.dirname(self.proj["_path"]), c["file"])

    def _row_changed(self, row):
        if row == self._row:
            return
        if self._row >= 0 and not self._leave_ok():
            self.list.blockSignals(True)
            self.list.setCurrentRow(self._row)
            self.list.blockSignals(False)
            return
        self._row = row
        self.select()

    def _leave_ok(self):
        """Есть непересобранные правки — спросить, бросить ли их."""
        if not self.pending():
            return True
        r = QMessageBox.question(self, "AutoClip",
                                 "Правки этого клипа ещё не пересобраны и пропадут. Продолжить?")
        if r == QMessageBox.Yes:
            self.base = {}
            return True
        return False

    # ---------- выбранный клип ----------
    def select(self, *_):
        c = self.current_clip()
        self.editor.setEnabled(bool(c) and not self.busy)
        if not c:
            self.player.clear()
            self.info.setText("")
            self.base = {}
            return
        path = self.clip_path(c)
        if os.path.isfile(path):
            self.player.open(path)
        else:
            self.player.clear()
        parts = ", ".join(f"{k} {v:+.1f}" for k, v in c.get("score_parts", {}).items()
                          if abs(v) >= 0.05)
        lines = [f"<b>{c['title']}</b>",
                 f"Оценка {c['score']:.1f}" + (f" — {parts}" if parts else ""),
                 f"Зумов: {len(c['zooms'])}, запикано: "
                 f"{c['bleeps'] if c['bleeps'] is not None else '-'}"]
        if c.get("marks"):
            lines.append("📍 Метка из OBS: " + ", ".join(autoclip.fmt_time(t) for t in c["marks"]))
        ht = autoclip.hook_text(c)
        lines.append(ht[:1].upper() + ht[1:])
        if c.get("quiet_start"):
            lines.append("Тихое начало — первые 3 с без звука")
        if c.get("reason"):
            lines.append(f"Почему: {c['reason']}")
        self.info.setText("<br>".join(lines))
        self.fill_editor(c)

    def fill_editor(self, c):
        cfg = autoclip.clip_config(self.proj, c)
        self.base = {"hook": bool((c.get("hook") or {}).get("on")), "zoom": bool(cfg["zoom"]),
                     "bleep": bool(cfg["bleep"]), "subs": bool(cfg["subs"]),
                     "sub_y": autoclip.SUB_POSITIONS[autoclip.sub_position_name(cfg["sub_y"])],
                     "safe_zone": bool(cfg.get("safe_zone")),
                     "start": round(c["start"], 1), "end": round(c["end"], 1)}
        widgets = (self.e_hook, self.e_zoom, self.e_bleep, self.e_subs, self.e_pos, self.e_safe,
                   self.e_start, self.e_end)
        for w in widgets:
            w.blockSignals(True)
        b = self.base
        self.e_hook.setChecked(b["hook"])
        self.e_zoom.setChecked(b["zoom"])
        self.e_bleep.setChecked(b["bleep"])
        self.e_subs.setChecked(b["subs"])
        self.e_pos.setCurrentText(autoclip.sub_position_name(b["sub_y"]))
        self.e_safe.setChecked(b["safe_zone"])
        self.e_pos.setEnabled(b["subs"])
        self.e_safe.setEnabled(b["subs"])
        self.e_start.setText(autoclip.fmt_time_exact(b["start"]))
        self.e_end.setText(autoclip.fmt_time_exact(b["end"]))
        for w in widgets:
            w.blockSignals(False)
        good = c["status"] == "good"
        self.btn_good.setText("↩  Убрать из хороших" if good else "👍  Хороший")
        self._changed()

    def _time(self, edit):
        try:
            return round(autoclip.parse_time(edit.text()), 1)
        except autoclip.AutoClipError:
            return None

    def edited(self):
        """Текущие значения редактора (время — None, если введено с ошибкой)."""
        return {"hook": self.e_hook.isChecked(), "zoom": self.e_zoom.isChecked(),
                "bleep": self.e_bleep.isChecked(), "subs": self.e_subs.isChecked(),
                "sub_y": autoclip.SUB_POSITIONS[self.e_pos.currentText()],
                "safe_zone": self.e_safe.isChecked(),
                "start": self._time(self.e_start), "end": self._time(self.e_end)}

    def pending(self):
        """Что поменяли в редакторе и ещё не пересобрали."""
        if not self.base:
            return {}
        now = self.edited()
        return {k: v for k, v in now.items() if v != self.base.get(k)}

    def _changed(self, *_):
        now = self.edited()
        bad = now["start"] is None or now["end"] is None
        for edit, val in ((self.e_start, now["start"]), (self.e_end, now["end"])):
            edit.setStyleSheet("border: 1px solid #ff4f6d;" if val is None else "")
        if not bad:
            ln = now["end"] - now["start"]
            self.e_len.setText(f"длина {ln:.1f} с" if ln > 0 else "конец раньше начала")
        if self.busy:
            return
        p = self.pending()
        if bad:
            self.state.setText("Время не понял — пиши как 1:18 или 0:01:18.5")
        elif p:
            self.state.setText("Есть правки — нажми «Пересобрать»")
        else:
            self.state.setText("")
        self.btn_rebuild.setEnabled(not bad)

    def shift(self, edit, delta):
        t = self._time(edit)
        if t is None:
            return
        dur = self.proj["source_info"]["dur"]
        edit.setText(autoclip.fmt_time_exact(min(dur, max(0.0, t + delta))))

    # ---------- действия ----------
    def rebuild(self):
        c = self.current_clip()
        if not c or self.busy:
            return
        now, p = self.edited(), self.pending()
        if now["start"] is None or now["end"] is None:
            return
        if now["end"] - now["start"] < 3:
            QMessageBox.warning(self, "AutoClip", "Клип получается короче 3 секунд.")
            return
        overrides = {k: v for k, v in p.items() if k in autoclip.OVERRIDE_KEYS}
        start = now["start"] if "start" in p else None
        end = now["end"] if "end" in p else None
        self.busy = True
        self.editor.setEnabled(False)
        self.state.setText("Пересобираю…")
        self.player.release_file()               # иначе Windows не даст заменить файл
        cid, pp = c["id"], self.proj["_path"]
        bus = self.win.bus

        def work():
            try:
                autoclip.rebuild_clip(pp, cid, start, end, overrides)
                bus.rebuilt.emit(cid, None)
            except autoclip.AutoClipError as e:
                bus.rebuilt.emit(cid, str(e))
            except Exception:
                bus.rebuilt.emit(cid, "❌ " + traceback.format_exc()[-800:])
        threading.Thread(target=work, daemon=True).start()

    def _rebuilt(self, cid, err):
        self.busy = False
        self.base = {}
        self.reload(cid)
        self.state.setText(err or "Готово ✓")
        if err:
            QMessageBox.warning(self, "AutoClip", err)

    def toggle_good(self):
        c = self.current_clip()
        if not c:
            return
        try:
            autoclip.set_status(self.proj["_path"], c["id"], "new" if c["status"] == "good" else "good")
        except autoclip.AutoClipError as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            return
        self.base = {}
        self.reload(c["id"])

    def to_trash(self):
        c = self.current_clip()
        if not c:
            return
        r = QMessageBox.question(self, "AutoClip", f"Убрать клип «{c['title']}» в корзину?\n"
                                 "Файл можно будет вернуть из корзины Windows.")
        if r != QMessageBox.Yes:
            return
        row = self.list.currentRow()
        self.player.release_file()               # иначе Windows не даст перенести файл
        try:
            autoclip.set_status(self.proj["_path"], c["id"], "rejected")
        except Exception as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            self.select()
            return
        self.base = {}
        self.reload()
        if self.list.count():
            self.list.setCurrentRow(min(row, self.list.count() - 1))

    def save_as(self):
        c = self.current_clip()
        if not c:
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Сохранить клип", c["file"], "Видео (*.mp4)")
        if not dest:
            return
        try:
            autoclip.save_clip_as(self.proj["_path"], c["id"], dest)
        except Exception as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            return
        self.state.setText(f"Сохранено: {os.path.basename(dest)}")

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
        box = QGroupBox("Пресеты экспорта")
        v = QVBoxLayout(box)
        self.presets = QListWidget()
        self.presets.setObjectName("clipList")
        self.presets.setSelectionMode(QAbstractItemView.SingleSelection)
        self.presets.setFixedHeight(96)
        v.addWidget(self.presets)
        row = QHBoxLayout()
        self.p_name = QLineEdit()
        self.p_name.setPlaceholderText("Название, например «Shorts 1080p30»")
        row.addWidget(self.p_name, 1)
        self.p_w = self._spin(240, 4320, 1080, 2, "Ширина")
        self.p_h = self._spin(240, 4320, 1920, 2, "Высота")
        self.p_fps = self._spin(24, 120, 60, 1, "Кадров в секунду")
        self.p_kbps = self._spin(1000, 100000, 18000, 500, "Битрейт, Кбит/с")
        for label, w in (("", self.p_w), ("×", self.p_h), ("к/с", self.p_fps),
                         ("Кбит/с", self.p_kbps)):
            if label and label != "×":
                row.addWidget(w)
                row.addWidget(QLabel(label))
            else:
                if label:
                    row.addWidget(QLabel(label))
                row.addWidget(w)
        b = QPushButton("Добавить")
        b.clicked.connect(self.add_preset)
        row.addWidget(b)
        v.addLayout(row)
        row = QHBoxLayout()
        self.btn_del = QPushButton("Удалить выбранный")
        self.btn_del.clicked.connect(self.delete_preset)
        row.addWidget(self.btn_del)
        self.p_state = hint("H.264, постоянный битрейт, MP4, цвет Rec. 709, звук AAC 320 кбит/с.")
        row.addWidget(self.p_state, 1)
        v.addLayout(row)
        self.presets.currentRowChanged.connect(self._preset_selected)
        lay.addWidget(box)
        self.refresh_presets()

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

    def _spin(self, lo, hi, val, step, tip):
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setValue(val)
        sp.setToolTip(tip)
        return sp

    # --- пресеты ---
    def refresh_presets(self, select=None):
        self.all_presets = autoclip.load_presets()
        self.presets.clear()
        for p in self.all_presets:
            extra = " · встроенный" if p.get("builtin") else ""
            self.presets.addItem(f"{p['name']} — {p['w']}×{p['h']}, {p['fps']} к/с, "
                                 f"{p['kbps']} Кбит/с{extra}")
        names = [p["name"] for p in self.all_presets]
        self.presets.setCurrentRow(names.index(select) if select in names else 0)
        self.win.cut.refresh_presets()

    def _preset_selected(self, row):
        ok = 0 <= row < len(self.all_presets) and not self.all_presets[row].get("builtin")
        self.btn_del.setEnabled(ok)

    def add_preset(self):
        new = {"name": self.p_name.text().strip(), "w": self.p_w.value(), "h": self.p_h.value(),
               "fps": self.p_fps.value(), "kbps": self.p_kbps.value()}
        try:
            new = autoclip.check_preset(new)
            if new["name"] in [p["name"] for p in self.all_presets]:
                raise autoclip.AutoClipError("❌ Пресет с таким названием уже есть.")
            autoclip.save_user_presets(self.all_presets + [new])
        except (autoclip.AutoClipError, OSError) as e:
            self.p_state.setText(str(e))
            return
        self.p_name.clear()
        self.p_state.setText(f"Добавлен «{new['name']}». Выбрать его можно на «Нарезке».")
        self.refresh_presets(select=new["name"])

    def delete_preset(self):
        row = self.presets.currentRow()
        if not (0 <= row < len(self.all_presets)) or self.all_presets[row].get("builtin"):
            return
        name = self.all_presets[row]["name"]
        autoclip.save_user_presets([p for i, p in enumerate(self.all_presets) if i != row])
        self.p_state.setText(f"Пресет «{name}» удалён.")
        self.refresh_presets()

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
            self.detached.space.activated.connect(p.toggle)
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
