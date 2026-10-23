# -*- coding: utf-8 -*-
"""AutoClip — окно на PySide6. Вся обработка — в autoclip.py, здесь только интерфейс."""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["PATH"] = HERE + os.pathsep + os.environ.get("PATH", "")

import autoclip  # noqa: E402
import forecast  # noqa: E402
import update  # noqa: E402
import diag  # noqa: E402

from PySide6.QtCore import (  # noqa: E402
    QByteArray, QEventLoop, QObject, QPointF, QRectF, QSize, Qt, QTimer, QUrl,
    QVariantAnimation, Signal,
)
from PySide6.QtGui import (  # noqa: E402
    QColor, QFont, QIcon, QKeySequence, QPainter, QPalette, QPen, QPixmap, QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer  # noqa: E402
from PySide6.QtMultimediaWidgets import QVideoWidget  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton, QAbstractItemView, QApplication, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QDialog, QMenu, QSystemTrayIcon, QSizePolicy, QSlider, QSpinBox,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

WEBCAM = {"Вебка сверху": 0.30, "Вебка снизу": 0.70, "По центру": 0.50}
LLM_MODES = {"Авто": "auto", "Ollama на компьютере": "ollama", "Claude API": "anthropic",
             "Без модели": "none"}
VIDEO_EXT = (".mp4", ".mkv", ".mov", ".flv", ".ts", ".webm")
VIDEO_FILTER = "Видео (*.mp4 *.mkv *.mov *.flv *.ts *.webm);;Все файлы (*.*)"
LATER = "Появится в следующих версиях"
NICK_SIZES = {"Маленький": 32, "Средний": 40, "Крупный": 52}

DEFAULTS = {
    "clips": 10, "clips_mode": "count", "auto_min_score": autoclip.CONFIG["auto_min_score"],
    "auto_min_score_plain": autoclip.CONFIG["auto_min_score_plain"],
    "auto_max": autoclip.CONFIG["auto_max"], "build_mode": "auto", "game_processes": "",
    "subs": True, "zoom": True, "hook": True, "bleep": True,
    "sound": "перелистывание", "marks": True, "nick": False, "cam": "Вебка сверху",
    "sub_pos": autoclip.sub_position_name(autoclip.CONFIG["sub_y"]), "safe_zone": True,
    "nick_corner": autoclip.CONFIG["nick_corner"], "nick_size": "Средний",
    "nick_opacity": autoclip.CONFIG["nick_opacity"],
    "preset": autoclip.CONFIG["preset"], "llm": "auto", "ollama_model": autoclip.CONFIG["ollama_model"],
    "nick_text": "Final_KFC_Boss", "hashtags": "", "obs_dir": "", "recent": [],
    "platform_tags": dict(autoclip.CONFIG["platform_tags"]),
    "watch": False, "min_minutes": 5, "watch_since": 0.0, "tray_hint_shown": False,
    "views_days": 3, "check_updates": True, "skip_version": "", "seen_version": "",
    "geometry": "", "player_geometry": "",
    "weekly_days": 7, "weekly_format": "vertical", "weekly_dir": autoclip.WEEKLY_DIR,
}

BG, SURFACE, SURFACE2, BORDER = "#111216", "#18191f", "#20222a", "#2a2c35"
FG, MUTED, ACCENT = "#eceef2", "#8b8f9a", "#ff4f6d"
PANEL, PANEL2 = SURFACE, SURFACE2          # старые имена — для схемы субтитров и окна просмотра

STYLE = f"""
QWidget {{ font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 10pt; color: {FG}; }}
QMainWindow, #page, #scrollBody {{ background: {BG}; }}
QScrollArea {{ background: {BG}; border: none; }}
#side {{ background: #0c0d10; border-right: 1px solid {BORDER}; }}
#brand {{ font-size: 14pt; font-weight: 700; color: white; padding: 22px 22px 14px 24px; }}
#brandDot {{ color: {ACCENT}; }}
#version {{ color: {MUTED}; font-size: 8pt; text-align: left; padding: 0 0 12px 25px;
            border: none; background: transparent; }}
#version:hover {{ color: {FG}; }}
#nav {{ background: transparent; border: none; outline: none; padding: 0 10px; }}
#nav::item {{ padding: 10px 14px; border-radius: 8px; margin: 2px 0; color: {MUTED}; }}
#nav::item:selected {{ background: {SURFACE2}; color: white; }}
#nav::item:hover:!selected {{ background: #16171c; color: {FG}; }}
#title {{ font-size: 19pt; font-weight: 600; color: white; }}
#subtitle {{ color: {MUTED}; }}
#hint {{ color: {MUTED}; font-size: 9pt; }}
#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#cardTitle {{ font-size: 11pt; font-weight: 600; color: white; }}
#rowLabel {{ color: {FG}; }}
#rowHint {{ color: {MUTED}; font-size: 9pt; }}
#sep {{ background: {BORDER}; }}
#fieldLabel {{ color: {MUTED}; font-size: 9pt; }}
#drop {{ background: {SURFACE}; border: 2px dashed #2f323c; border-radius: 14px; }}
#drop[hover="true"] {{ border-color: {ACCENT}; background: #1c1a20; }}
#dropText {{ font-size: 13pt; font-weight: 600; color: white; }}
#dropHint {{ color: {MUTED}; }}
QPushButton {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 8px;
              padding: 0 14px; min-height: 32px; }}
QPushButton:hover {{ background: #272a33; border-color: #363946; }}
QPushButton:pressed {{ background: #1b1d23; }}
QPushButton:disabled {{ color: #5c606b; background: #17181d; border-color: #22242b; }}
#accent {{ background: {ACCENT}; border: none; color: white; font-size: 12pt; font-weight: 600;
          min-height: 46px; border-radius: 10px; padding: 0 28px; }}
#accent:hover {{ background: #ff6680; }}
#accent[busy="true"] {{ background: #3b2430; color: #ffb3c0; }}
#primary {{ background: {ACCENT}; border: none; color: white; font-weight: 600; padding: 0 18px; }}
#primary:hover {{ background: #ff6680; }}
#primary:disabled {{ background: #3b2430; color: #a07080; }}
#ghost {{ background: transparent; border: none; color: {MUTED}; padding: 0 8px; }}
#ghost:hover {{ color: {FG}; background: {SURFACE2}; }}
#danger:hover {{ color: #ff8094; border-color: #5a2a35; background: #2a1a20; }}
#square {{ padding: 0; min-width: 32px; max-width: 32px; font-size: 12pt; }}
#filter {{ background: transparent; border: 1px solid {BORDER}; border-radius: 14px;
          padding: 0 11px; min-height: 28px; color: {MUTED}; }}
#filter:hover {{ color: {FG}; }}
#filter:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
#stepValue {{ font-size: 12pt; font-weight: 600; min-width: 34px; }}
QComboBox, QLineEdit, QSpinBox {{ background: {SURFACE2}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 0 10px; min-height: 32px; }}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{ border-color: #3a3d48; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox:disabled, QLineEdit:disabled {{ color: #5c606b; background: #17181d; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url(@ARROW@); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{ background: {SURFACE2}; border: 1px solid {BORDER};
    padding: 4px; outline: none; selection-background-color: #30333d; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QPlainTextEdit {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
    font-family: "Cascadia Mono", Consolas; font-size: 9pt; padding: 10px; color: #b9bcc6; }}
#desc {{ font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 10pt; color: {FG};
         background: {SURFACE2}; padding: 8px; }}
QProgressBar {{ background: {SURFACE2}; border: none; border-radius: 3px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
#step {{ color: {MUTED}; font-size: 9pt; padding: 3px 10px; border-radius: 10px;
        background: {SURFACE}; border: 1px solid {BORDER}; }}
#step[state="active"] {{ color: white; border-color: {ACCENT}; }}
#step[state="done"] {{ color: #9fe3b4; border-color: #2c4a37; background: #17221b; }}
#clipList {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
    outline: none; padding: 6px; }}
#clipList::item {{ padding: 8px 10px; border-radius: 8px; margin: 1px 0; }}
#clipList::item:selected {{ background: #2a2d37; color: white; }}
#clipList::item:hover:!selected {{ background: #1e2027; }}
QSlider::groove:horizontal {{ height: 4px; background: #343845; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 12px; margin: -5px 0; border-radius: 6px; }}
QSplitter::handle {{ background: {BG}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2d3039; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a3e4a; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{ background: {SURFACE2}; color: {FG}; border: 1px solid {BORDER}; padding: 4px; }}
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
    added = Signal(object, object)         # новый клип (id) или None, текст ошибки или None
    weekly_progress = Signal(float, str)
    weekly_done = Signal(str, object)      # путь к подборке, текст ошибки или None
    trained = Signal(object)               # итог обучения прогноза
    update_found = Signal(object, bool)    # релиз или None, проверка вручную?
    update_progress = Signal(float)
    update_done = Signal(object, object)   # итог установки, текст ошибки или None
    report_done = Signal(object, object)   # путь к отчёту об ошибке, текст ошибки или None


class Stream:
    """Перехват print и ошибок библиотек в лог (у pythonw нет консоли)."""
    def __init__(self, bus):
        self.bus = bus

    def write(self, s):
        if s.strip():
            self.bus.log.emit(s.rstrip())

    def flush(self):
        pass


def page_title(text, sub=""):
    box = QVBoxLayout()
    box.setSpacing(2)
    t = QLabel(text)
    t.setObjectName("title")
    box.addWidget(t)
    if sub:
        h = QLabel(sub)
        h.setObjectName("subtitle")
        h.setWordWrap(True)
        box.addWidget(h)
    box.addSpacing(6)
    return box


def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


NOTE_MARK = {True: ("+", "#7dd99a"), False: ("−", "#ff7a90"), None: ("·", MUTED)}


def ask_choice(parent, text, choices):
    """Вопрос с кнопками [(ключ, надпись), …]; первая — главная, последняя — «Отмена».
    Возвращает ключ нажатой кнопки (крестик — ключ последней)."""
    box = QMessageBox(parent)
    box.setWindowTitle("AutoClip")
    box.setText(text)
    buttons = {}
    for i, (key, label) in enumerate(choices):
        role = (QMessageBox.AcceptRole if i == 0 else
                QMessageBox.RejectRole if i == len(choices) - 1 else QMessageBox.DestructiveRole)
        buttons[box.addButton(label, role)] = key
    first = next(iter(buttons))
    box.setDefaultButton(first)
    box.setEscapeButton(list(buttons)[-1])
    box.exec()
    return buttons.get(box.clickedButton(), choices[-1][0])


EDITS_CHOICES = (("apply", "Применить"), ("discard", "Не применять"), ("cancel", "Отмена"))


def hint(text):
    h = QLabel(text)
    h.setObjectName("hint")
    h.setWordWrap(True)
    return h


def card(title=None, sub=None):
    """Карточка: (рамка, раскладка содержимого)."""
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(4)
    if title:
        t = QLabel(title)
        t.setObjectName("cardTitle")
        lay.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setObjectName("rowHint")
        s.setWordWrap(True)
        lay.addWidget(s)
    if title or sub:
        lay.addSpacing(6)
    return frame, lay


def separator():
    line = QFrame()
    line.setObjectName("sep")
    line.setFixedHeight(1)
    return line


def option_row(text, widget, sub=None):
    """Строка настройки: подпись (и пояснение) слева, переключатель или поле справа."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 7, 0, 7)
    h.setSpacing(16)
    col = QVBoxLayout()
    col.setSpacing(1)
    lbl = QLabel(text)
    lbl.setObjectName("rowLabel")
    col.addWidget(lbl)
    if sub:
        s = QLabel(sub)
        s.setObjectName("rowHint")
        s.setWordWrap(True)
        col.addWidget(s)
        col.addStretch(1)              # у высоких строк подпись с пояснением остаётся сверху
    h.addLayout(col, 1)
    if isinstance(widget, QWidget):
        h.addWidget(widget, 0, Qt.AlignVCenter)
    else:
        h.addLayout(widget)
    return w


def labeled(text, widget):
    """Маленькая подпись над полем."""
    box = QVBoxLayout()
    box.setSpacing(4)
    lbl = QLabel(text)
    lbl.setObjectName("fieldLabel")
    box.addWidget(lbl)
    if isinstance(widget, QWidget):
        box.addWidget(widget)
    else:
        box.addLayout(widget)
    return box


class Toggle(QAbstractButton):
    """Переключатель вместо галочки."""

    W, H = 40, 22

    def __init__(self, checked=False, tip=""):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.W, self.H)
        if tip:
            self.setToolTip(tip)
        self._t = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(120)
        self._anim.valueChanged.connect(self._step)
        self.toggled.connect(self._go)

    def sizeHint(self):
        return QSize(self.W, self.H)

    def _go(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _step(self, v):
        self._t = float(v)
        self.update()

    def paintEvent(self, e):
        if self._anim.state() != QVariantAnimation.Running:
            self._t = 1.0 if self.isChecked() else 0.0      # значение поставили без сигнала
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        off, on = QColor("#3a3d48"), QColor(ACCENT)
        t = self._t
        track = QColor(int(off.red() + (on.red() - off.red()) * t),
                       int(off.green() + (on.green() - off.green()) * t),
                       int(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            track.setAlpha(80)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(0, 0, self.W, self.H, self.H / 2, self.H / 2)
        p.setBrush(QColor("#ffffff") if self.isEnabled() else QColor("#8a8c93"))
        d = self.H - 6
        p.drawEllipse(QRectF(3 + t * (self.W - d - 6), 3, d, d))
        p.end()


class Stepper(QWidget):
    """Число с кнопками − и + (вместо поля со стрелками)."""
    valueChanged = Signal(int)

    def __init__(self, lo, hi, value):
        super().__init__()
        self.lo, self.hi = lo, hi
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.minus = QPushButton("−")
        self.plus = QPushButton("+")
        for b in (self.minus, self.plus):
            b.setObjectName("square")
            b.setAutoRepeat(True)
        self.label = QLabel()
        self.label.setObjectName("stepValue")
        self.label.setAlignment(Qt.AlignCenter)
        h.addWidget(self.minus)
        h.addWidget(self.label)
        h.addWidget(self.plus)
        self.minus.clicked.connect(lambda: self.setValue(self._v - 1))
        self.plus.clicked.connect(lambda: self.setValue(self._v + 1))
        self._v = None
        self.setValue(value)

    def value(self):
        return self._v

    def setValue(self, v):
        v = max(self.lo, min(self.hi, int(v)))
        if v == self._v:
            return
        self._v = v
        self.label.setText(str(v))
        self.minus.setEnabled(v > self.lo)
        self.plus.setEnabled(v < self.hi)
        self.valueChanged.emit(v)


class SoundButton(QPushButton):
    """▶ — прослушать звук на мат."""

    def __init__(self, combo):
        super().__init__("▶")
        self.setObjectName("square")
        self.setToolTip("Прослушать")
        self.combo = combo
        self.player = QMediaPlayer(self)
        self.out = QAudioOutput(self)
        self.player.setAudioOutput(self.out)
        self.clicked.connect(self.play)

    def play(self):
        path = autoclip.sound_path(self.combo.currentText())
        if path:
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
            self.player.play()


def fill_sounds(combo, want):
    names = autoclip.list_sounds()
    combo.blockSignals(True)
    combo.clear()
    combo.addItems(names)
    combo.setCurrentText(want if want in names else names[0])
    combo.blockSignals(False)


ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")


def glyph_icon(code, size=18):
    """Значок из шрифта значков Windows: обычный — серый, выбранный — белый."""
    from PySide6.QtGui import QFontDatabase, QIcon
    family = next((f for f in ICON_FONTS if f in QFontDatabase.families()), None)
    icon = QIcon()
    if not family:
        return icon
    for color, mode in ((MUTED, QIcon.Normal), ("#ffffff", QIcon.Selected)):
        pm = QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.TextAntialiasing)
        f = QFont(family)
        f.setPixelSize(size - 2)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, code)
        p.end()
        icon.addPixmap(pm, mode)
    return icon


def arrow_icon():
    """Стрелка для выпадающих списков (рисуется один раз во временную папку)."""
    path = os.path.join(tempfile.gettempdir(), "autoclip_arrow.png")
    pm = QPixmap(20, 20)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(MUTED), 2.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QPointF(5, 8), QPointF(10, 13), QPointF(15, 8)])
    p.end()
    pm.save(path)
    return path.replace("\\", "/")


class SubsPreview(QWidget):
    """Схема кадра 9:16: где будут субтитры и какие поля закрывают кнопки соцсетей."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(72, 128)
        self.setToolTip("Где будут субтитры. Красным — зона кнопок и подписей соцсетей.")
        self.sub_y, self.safe, self.subs, self.nick = 0.6, True, True, {}

    def set_state(self, sub_y, safe, subs=True, nick=None):
        """nick — настройки ника ({"nick": True, "nick_corner": …}) или пусто."""
        self.sub_y, self.safe, self.subs, self.nick = sub_y, safe, subs, nick or {}
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
        cfg = dict(autoclip.CONFIG, sub_y=self.sub_y, safe_zone=self.safe, nick=False)
        cfg.update(self.nick)
        p.setPen(Qt.NoPen)
        if self.subs:
            lay = autoclip.subs_layout(1080, 1920, cfg)
            l, _, r, _ = lay["box"]
            bw = (r - l) / 1080 * w * 0.8
            cx, cy = lay["x"] / 1080 * w, lay["y"] / 1920 * h
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(int(cx - bw / 2), int(cy - 4), int(bw), 8, 3, 3)
            p.setBrush(QColor("#ffe600"))
            p.drawRoundedRect(int(cx - bw / 6), int(cy - 4), int(bw / 3), 8, 3, 3)
        if cfg.get("nick") and str(cfg.get("nick_text", "")).strip():
            nk = autoclip.nick_layout(1080, 1920, cfg)
            nw = min(w * 0.6, len(cfg["nick_text"]) * nk["fs"] * 0.55 / 1080 * w)
            nh = max(4, (nk["y1"] - nk["y0"]) / 1920 * h * 0.7)
            x = nk["x"] / 1080 * w - (nw if nk["corner"][1] == "r" else 0)
            y = nk["y0"] / 1920 * h
            p.setBrush(QColor(255, 255, 255, int(255 * cfg.get("nick_opacity", 70) / 100)))
            p.drawRoundedRect(QRectF(x, y, nw, nh), 2, 2)
        p.end()


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
        self.setMinimumSize(240, 240)      # на невысоком экране видео ужимается, а не наезжает
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
        self._seek = 0                 # куда перемотать после открытия, мс
        self._pending_seek = None
        self.player.seekableChanged.connect(self._seekable)
        self.player.durationChanged.connect(lambda _: self._seekable(self.player.isSeekable()))

    def open(self, path, autoplay=False, at_ms=0):
        self._first_frame = not autoplay
        self._may_play = autoplay
        self._seek = int(at_ms)
        self._pending_seek = int(at_ms) or None
        self.audio.setMuted(not autoplay)    # пока показываем первый кадр — без звука
        self.player.setSource(QUrl.fromLocalFile(path))
        if autoplay:
            self.play()

    def show_at(self, path, ms):
        """Перемотать на место (открыть файл, если открыт другой), на паузе."""
        if self.player.source() == QUrl.fromLocalFile(path) and \
                self.player.mediaStatus() not in (QMediaPlayer.NoMedia, QMediaPlayer.InvalidMedia,
                                                  QMediaPlayer.LoadingMedia):
            self._may_play = False
            self.player.pause()
            self.player.setPosition(int(ms))
        else:
            self.open(path, at_ms=ms)

    def play(self):
        self._may_play = True
        self.audio.setMuted(False)
        self.player.play()

    def _loaded(self, status):
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            self._seekable(self.player.isSeekable())
        # пауза сразу после загрузки показывает первый кадр без звука
        if status == QMediaPlayer.LoadedMedia and self._first_frame:
            self._first_frame = False
            self.player.pause()
            QTimer.singleShot(400, self._ensure_frame)

    def _seekable(self, ok):
        # перемотка до готовности файла теряется — делаем её, как только можно
        # (сначала приходит «загружено» ещё про прежний файл — ждём длину нового;
        # перемотку во время загрузки проигрыватель может сбросить — повторяем, пока не встанет)
        if ok and self._pending_seek is not None and self.player.duration() > self._pending_seek:
            self.player.setPosition(self._pending_seek)

    def _ensure_frame(self):
        # бывает, что первый кадр не пришёл — просим его ещё раз
        if not self._may_play and not self.video.videoSink().videoFrame().isValid():
            self.player.setPosition(self._seek)
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
        if self._pending_seek is not None and abs(ms - self._pending_seek) < 1000:
            self._pending_seek = None                # встали куда надо
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


class DropZone(QFrame):
    files = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(190)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(22)
        self.pic = QLabel()
        self.pic.setFixedSize(0, 0)
        lay.addWidget(self.pic)
        col = QVBoxLayout()
        col.setSpacing(6)
        col.addStretch(1)
        self.text = QLabel("Перетащи сюда запись стрима")
        self.text.setObjectName("dropText")
        self.sub = QLabel("или нажми, чтобы выбрать файл")
        self.sub.setObjectName("dropHint")
        col.addWidget(self.text)
        col.addWidget(self.sub)
        col.addStretch(1)
        lay.addLayout(col, 1)
        self._center(True)

    def _center(self, on):
        al = Qt.AlignCenter if on else (Qt.AlignLeft | Qt.AlignVCenter)
        self.text.setAlignment(al)
        self.sub.setAlignment(al)

    def set_preview(self, pixmap, text, sub=""):
        if pixmap:
            self.pic.setFixedSize(pixmap.size())
            self.pic.setPixmap(pixmap)
        else:
            self.pic.setFixedSize(0, 0)
            self.pic.clear()
        self._center(not pixmap)
        self.text.setText(text)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))

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


# ---------------- раздел «Нарезка» ----------------

class CutPage(QWidget):
    """Главное: выбрать запись, сколько клипов, пресет — и «Нарезать».
    Как резать (субтитры, хук, мат…) — в «Настройках», у отдельного клипа — в «Клипах»."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.s = win.settings
        self.files = []
        self.thumb_n = 0
        self.last_out = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(14)
        lay.addLayout(page_title("Нарезка", "Перетащи запись — программа найдёт яркие моменты "
                                            "и нарежет клипы."))

        self.drop = DropZone()
        self.drop.files.connect(self.set_files)
        lay.addWidget(self.drop)

        row = QHBoxLayout()
        row.setSpacing(18)
        self.count = Stepper(1, 50, int(self.s["clips"]))
        self.count.valueChanged.connect(lambda v: self._set("clips", v))
        cnt = QHBoxLayout()
        cnt.setSpacing(6)
        cnt.addWidget(self.count)
        self.mode_btns = {}
        for key, name, tip in (("count", "Число", "Ровно столько клипов"),
                               ("auto", "Авто", "Все яркие моменты — выше порога из «Настроек»")):
            b = QPushButton(name)
            b.setObjectName("filter")
            b.setCheckable(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _, k=key: self.set_mode(k))
            cnt.addWidget(b)
            self.mode_btns[key] = b
        row.addLayout(labeled("Клипов", cnt))
        self.preset = QComboBox()
        self.preset.setMinimumWidth(200)
        self.preset.setToolTip("Размер, кадры и битрейт клипов. Свой пресет — в «Настройках».")
        self.preset.currentTextChanged.connect(lambda t: self._set("preset", t) if t else None)
        row.addLayout(labeled("Пресет", self.preset))
        row.addStretch(1)
        self.btn = QPushButton("✂   Нарезать")
        self.btn.setObjectName("accent")
        self.btn.setMinimumWidth(240)
        self.btn.clicked.connect(self.start_or_stop)
        row.addWidget(self.btn, 0, Qt.AlignBottom)
        lay.addLayout(row)

        steps = QHBoxLayout()
        steps.setSpacing(6)
        self.step_labels = []
        for st in autoclip.STAGES:
            lb = QLabel(st)
            lb.setObjectName("step")
            steps.addWidget(lb)
            self.step_labels.append(lb)
        steps.addStretch(1)
        lay.addLayout(steps)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)

        row = QHBoxLayout()
        self.btn_folder = QPushButton("Открыть папку с клипами")
        self.btn_folder.setEnabled(False)
        self.btn_folder.clicked.connect(lambda: self.last_out and open_path(self.last_out))
        self.btn_clips = QPushButton("К клипам  →")
        self.btn_clips.setEnabled(False)
        self.btn_clips.clicked.connect(lambda: self.win.go("clips"))
        row.addWidget(self.btn_folder)
        row.addWidget(self.btn_clips)
        row.addStretch(1)
        lay.addLayout(row)

        self.refresh_presets()
        self.set_mode(self.s.get("clips_mode", "count"))

    def _set(self, key, value):
        self.s[key] = value
        save_settings(self.s)

    def set_mode(self, key):
        key = "auto" if key == "auto" else "count"
        for k, b in self.mode_btns.items():
            b.setChecked(k == key)
        self.count.setEnabled(key == "count")
        if self.s.get("clips_mode") != key:
            self._set("clips_mode", key)

    def refresh_presets(self):
        names = [p["name"] for p in autoclip.load_presets()]
        want = self.s.get("preset")
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItems(names)
        self.preset.setCurrentText(want if want in names else names[0])
        self.preset.blockSignals(False)
        self.s["preset"] = self.preset.currentText()

    # --- выбор файла и превью ---
    def set_files(self, paths):
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            return
        if self.win.busy:
            self.write("ℹ️  Дождись конца нарезки или останови её.")
            return
        self.files = paths
        more = f"…и ещё {len(paths) - 1}" if len(paths) > 1 else ""
        self.drop.set_preview(None, "🎬  " + os.path.basename(paths[0]), more)
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
        sub = [f"{autoclip.fmt_time(info['dur'])}  ·  {info['w']}×{info['h']}  ·  "
               f"{info['fps']:g} к/с",
               f"меток из OBS: {info.get('marks', 0)}"]
        if info["w"] > info["h"]:
            sub.append("горизонтальное — возьму середину кадра")
        if len(paths) > 1:
            sub.append(f"…и ещё {len(paths) - 1}")
        self.drop.set_preview(None if pm.isNull() else pm, os.path.basename(paths[0]),
                              "\n".join(sub))

    # --- запуск ---
    def apply_config(self):
        c = autoclip.CONFIG
        s = self.s
        c["clips"] = int(s["clips"])
        c["clips_mode"] = "auto" if s.get("clips_mode") == "auto" else "count"
        c["build_mode"] = s.get("build_mode") if s.get("build_mode") in autoclip.BUILD_MODES else "auto"
        c["game_processes"] = s.get("game_processes", "")
        c["auto_min_score"] = float(s.get("auto_min_score", DEFAULTS["auto_min_score"]))
        c["auto_min_score_plain"] = float(s.get("auto_min_score_plain",
                                                DEFAULTS["auto_min_score_plain"]))
        c["auto_max"] = int(s.get("auto_max", DEFAULTS["auto_max"]))
        c["subs"] = bool(s["subs"])
        c["zoom"] = bool(s["zoom"])
        c["bleep"] = bool(s["bleep"])
        c["hook"] = bool(s["hook"])
        c["marks"] = bool(s["marks"])
        c["sub_y"] = autoclip.SUB_POSITIONS.get(s["sub_pos"], autoclip.CONFIG["sub_y"])
        c["safe_zone"] = bool(s["safe_zone"])
        c["nick"] = bool(s["nick"])
        c["nick_text"] = s["nick_text"]
        c["nick_corner"] = s["nick_corner"]
        c["nick_size"] = NICK_SIZES.get(s["nick_size"], 40)
        c["nick_opacity"] = int(s["nick_opacity"])
        c["hashtags"] = s["hashtags"]
        c["platform_tags"] = dict(s["platform_tags"])
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
        self.btn.setText("■   Остановить")
        self._busy_style(True)
        self.btn_folder.setEnabled(False)
        self.btn_clips.setEnabled(False)
        self.bar.setValue(0)
        for lb, st in zip(self.step_labels, autoclip.STAGES):
            self._step_state(lb, st, "")

    def _busy_style(self, on):
        self.btn.setProperty("busy", on)
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)

    def _step_state(self, lb, text, state):
        lb.setText(text)
        lb.setProperty("state", state)
        lb.style().unpolish(lb)
        lb.style().polish(lb)

    def show_progress(self, stage, pct, msg):
        stages = autoclip.STAGES
        if stage not in stages:
            return
        i = stages.index(stage)
        self.bar.setValue(int((i + pct / 100) / len(stages) * 1000))
        for j, (lb, st) in enumerate(zip(self.step_labels, stages)):
            if j < i or (j == i and pct >= 100):
                self._step_state(lb, "✓ " + st, "done")
            elif j == i:
                self._step_state(lb, f"{st}  {pct:.0f}%", "active")

    def finished(self, out):
        self.btn.setText("✂   Нарезать")
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

CLIP_PATH = Qt.UserRole + 2          # путь к файлу клипа в строке списка


class ClipList(QListWidget):
    """Список клипов: клип можно перетащить мышкой прямо в окно загрузки на сайте."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)

    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, items):
        from PySide6.QtCore import QMimeData
        md = QMimeData()
        paths = [it.data(CLIP_PATH) for it in items if it.data(CLIP_PATH)]
        md.setUrls([QUrl.fromLocalFile(p) for p in paths if os.path.isfile(p)])
        return md

    def supportedDropActions(self):
        return Qt.CopyAction


FILTERS = (("Все", None), ("Новые", {"new"}), ("Хорошие", {"good"}), ("Выложены", {"published"}),
           ("Кандидаты", {"candidate"}))
CAND = "cand:"       # так в списке помечены кандидаты (моменты без видео)
SHIFT = 2.0          # шаг сдвига начала и конца, сек
COVER_W, COVER_H = 34, 60   # обложка в списке клипов


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
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(12)
        lay.addLayout(page_title("Клипы"))

        top = QHBoxLayout()
        self.projects = QComboBox()
        self.projects.setMinimumWidth(360)
        self.projects.setPlaceholderText("Выбери нарезку")
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
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по расшифровке записи")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip("Можно часть слова: «смеш» найдёт «смешно». Регистр и ё не важны")
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self.run_search)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        ll.addWidget(self.search)
        self.left_stack = QStackedWidget()
        ll.addWidget(self.left_stack, 1)
        found = QWidget()
        fl = QVBoxLayout(found)
        fl.setContentsMargins(0, 0, 0, 0)
        self.found_count = hint("")
        fl.addWidget(self.found_count)
        self.found = QListWidget()
        self.found.setObjectName("clipList")
        self.found.currentRowChanged.connect(self.show_found)
        fl.addWidget(self.found, 1)
        frow2 = QHBoxLayout()
        self.btn_here = QPushButton("Клип отсюда")
        self.btn_here.setObjectName("primary")
        self.btn_here.setToolTip("Собрать новый клип вокруг этого места — по тем же правилам, "
                                 "что и автоматические")
        self.btn_here.setEnabled(False)
        self.btn_here.clicked.connect(self.clip_here)
        frow2.addWidget(self.btn_here)
        self.here_state = hint("")
        frow2.addWidget(self.here_state, 1)
        fl.addLayout(frow2)
        self.hits = []
        self.list = ClipList()
        self.list.setObjectName("clipList")
        self.list.setToolTip("Клип можно перетащить мышкой прямо в окно загрузки на сайте")
        self.list.setWordWrap(True)
        self.list.setTextElideMode(Qt.ElideNone)
        self.list.setIconSize(QSize(COVER_W, COVER_H))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._covers = {}              # обложки списка: путь → (время изменения, значок)
        self.list.currentRowChanged.connect(self._row_changed)
        self.list.itemDoubleClicked.connect(lambda _: self.player.play())
        self.left_stack.addWidget(self.list)
        self.left_stack.addWidget(found)
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
        self.btn_build = QPushButton("Собрать")
        self.btn_build.setObjectName("primary")
        self.btn_build.setToolTip("Сделать из кандидата обычный клип")
        self.btn_build.clicked.connect(self.build_candidate)
        self.btn_build.hide()
        rl.addWidget(self.btn_build, 0, Qt.AlignLeft)

        # --- редактор клипа ---
        self.editor, outer = card()
        outer.setSpacing(10)
        tabs = QHBoxLayout()
        tabs.setSpacing(6)
        self.ed_tabs = []
        for i, name in enumerate(("Клип", "Описание", "Публикация")):
            b = QPushButton(name)
            b.setObjectName("filter")
            b.setCheckable(True)
            b.clicked.connect(lambda _, i=i: self.show_tab(i))
            tabs.addWidget(b)
            self.ed_tabs.append(b)
        tabs.addStretch(1)
        outer.addLayout(tabs)
        self.ed_stack = QStackedWidget()
        outer.addWidget(self.ed_stack)
        page = QWidget()
        ed = QVBoxLayout(page)
        ed.setContentsMargins(0, 0, 0, 0)
        ed.setSpacing(10)
        self.ed_stack.addWidget(page)
        row = QHBoxLayout()
        row.setSpacing(18)
        self.e_hook = Toggle(tip="1–2 с яркой реакции из этого клипа в начале")
        self.e_zoom = Toggle()
        self.e_subs = Toggle()
        self.e_safe = Toggle(tip="Не заходить субтитрами под кнопки соцсетей")
        self.e_nick = Toggle(tip="Ник в углу — текст и угол в «Настройках»")
        for text, w in (("Хук", self.e_hook), ("Зум", self.e_zoom), ("Субтитры", self.e_subs),
                        ("Сейф-зона", self.e_safe), ("Ник", self.e_nick)):
            pair = QHBoxLayout()
            pair.setSpacing(8)
            pair.addWidget(w)
            pair.addWidget(QLabel(text))
            row.addLayout(pair)
            w.toggled.connect(self._changed)
        self.e_pos = QComboBox()
        self.e_pos.addItems(list(autoclip.SUB_POSITIONS))
        self.e_pos.setToolTip("Где субтитры")
        self.e_pos.currentTextChanged.connect(self._changed)
        row.addWidget(self.e_pos)
        self.e_subs.toggled.connect(self.e_pos.setEnabled)
        self.e_subs.toggled.connect(self.e_safe.setEnabled)
        row.addStretch(1)
        ed.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.e_bleep = Toggle()
        self.e_bleep.toggled.connect(self._changed)
        row.addWidget(self.e_bleep)
        row.addWidget(QLabel("Мат звуком"))
        row.addSpacing(6)
        self.e_sound = QComboBox()
        self.e_sound.setMinimumWidth(180)
        self.e_sound.currentTextChanged.connect(self._changed)
        self.e_bleep.toggled.connect(self.e_sound.setEnabled)
        row.addWidget(self.e_sound)
        row.addWidget(SoundButton(self.e_sound))
        row.addStretch(1)
        ed.addLayout(row)
        ed.addWidget(separator())

        row = QHBoxLayout()
        row.setSpacing(6)
        self.e_start = QLineEdit()
        self.e_end = QLineEdit()
        for label, edit in (("Начало", self.e_start), ("Конец", self.e_end)):
            lbl = QLabel(label)
            lbl.setObjectName("fieldLabel")
            row.addWidget(lbl)
            minus = QPushButton(f"−{SHIFT:g} с")
            plus = QPushButton(f"+{SHIFT:g} с")
            minus.clicked.connect(lambda _, e=edit: self.shift(e, -SHIFT))
            plus.clicked.connect(lambda _, e=edit: self.shift(e, SHIFT))
            edit.setFixedWidth(96)
            edit.setAlignment(Qt.AlignCenter)
            edit.setToolTip("Время в записи: 1:18 или 0:01:18.5")
            edit.textChanged.connect(self._changed)
            row.addWidget(minus)
            row.addWidget(edit)
            row.addWidget(plus)
            row.addSpacing(14)
        self.e_len = hint("")
        row.addWidget(self.e_len)
        row.addStretch(1)
        ed.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_rebuild = QPushButton("Пересобрать")
        self.btn_rebuild.setObjectName("primary")
        self.btn_rebuild.clicked.connect(self.rebuild)
        row.addWidget(self.btn_rebuild)
        self.state = hint("")
        row.addWidget(self.state, 1)
        ed.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_good = QPushButton("👍  Хороший")
        self.btn_good.clicked.connect(self.toggle_good)
        self.btn_trash = QPushButton("В корзину")
        self.btn_trash.setObjectName("danger")
        self.btn_trash.clicked.connect(self.to_trash)
        self.btn_save = QPushButton("Сохранить как…")
        self.btn_save.clicked.connect(self.save_as)
        self.btn_show = QPushButton("Показать в папке")
        self.btn_show.clicked.connect(self.show_file)
        for w in (self.btn_good, self.btn_trash, self.btn_save, self.btn_show):
            row.addWidget(w)
        row.addStretch(1)
        ed.addLayout(row)
        # --- описание для площадок ---
        page = QWidget()
        dl = QVBoxLayout(page)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(8)
        prow = QHBoxLayout()
        prow.setSpacing(6)
        self.desc_btns = {}
        for key, name in autoclip.PLATFORMS.items():
            b = QPushButton(name)
            b.setObjectName("filter")
            b.setCheckable(True)
            b.clicked.connect(lambda _, k=key: self.set_desc_platform(k))
            prow.addWidget(b)
            self.desc_btns[key] = b
        prow.addStretch(1)
        self.desc_tags = hint("")
        prow.addWidget(self.desc_tags)
        dl.addLayout(prow)
        self.desc = QPlainTextEdit()
        self.desc.setObjectName("desc")
        self.desc.setFixedHeight(96)
        self.desc.textChanged.connect(self._desc_edited)
        dl.addWidget(self.desc)
        row = QHBoxLayout()
        row.setSpacing(8)
        b = QPushButton("Копировать описание")
        b.setObjectName("primary")
        b.clicked.connect(self.copy_desc)
        row.addWidget(b)
        self.btn_desc_reset = QPushButton("Вернуть как было")
        self.btn_desc_reset.clicked.connect(self.reset_desc)
        row.addWidget(self.btn_desc_reset)
        self.desc_state = hint("")
        row.addWidget(self.desc_state, 1)
        dl.addLayout(row)
        dl.addStretch(1)
        self.ed_stack.addWidget(page)

        # --- публикация ---
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        top = QHBoxLayout()
        b = QPushButton("Во все три")
        b.setObjectName("primary")
        b.setToolTip("Три окна загрузки рядом на основном мониторе")
        b.clicked.connect(self.publish_all)
        top.addWidget(b)
        top.addWidget(hint("Окно загрузки откроется отдельно, описание будет в буфере — "
                           "вставь Ctrl+V. Клип перетащи мышкой из списка слева прямо "
                           "в окно загрузки."), 1)
        pl.addLayout(top)
        self.pub_rows = {}
        for key, name in autoclip.PLATFORMS.items():
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(name)
            lbl.setObjectName("rowLabel")
            lbl.setFixedWidth(84)
            row.addWidget(lbl)
            state = hint("")
            state.setFixedWidth(100)
            row.addWidget(state)
            go = QPushButton("Открыть")
            go.setToolTip(f"Окно загрузки {name}, описание — в буфер")
            go.clicked.connect(lambda _, k=key: self.publish(k))
            row.addWidget(go)
            mark = QPushButton()
            mark.clicked.connect(lambda _, k=key: self.toggle_published(k))
            row.addWidget(mark)
            link = QLineEdit()
            link.setPlaceholderText("ссылка на пост — по желанию")
            link.editingFinished.connect(lambda k=key: self.save_link(k))
            row.addWidget(link, 1)
            row.addStretch(0)
            pl.addLayout(row)
            self.pub_rows[key] = (state, link, mark)
        pl.addWidget(hint("Instagram в браузере: нажми «Создать» (+) в меню слева."))
        self.pub_state = hint("")
        pl.addWidget(self.pub_state)
        pl.addStretch(1)
        self.ed_stack.addWidget(page)

        self.desc_platform = "tiktok"
        self._desc_clip = None
        self._desc_timer = QTimer(self)
        self._desc_timer.setSingleShot(True)
        self._desc_timer.setInterval(600)
        self._desc_timer.timeout.connect(self.save_desc)
        self.show_tab(0)
        self.set_desc_platform("tiktok")

        rl.addWidget(self.editor)
        self.editor.setEnabled(False)

        split.addWidget(right)
        left.setMinimumWidth(430)          # пять фильтров в ряд
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([450, 690])
        self.split = split
        lay.addWidget(split, 1)

        # пока нарезка не выбрана — вместо пустого редактора подсказка
        self.blank = QWidget()
        bl = QVBoxLayout(self.blank)
        bl.addStretch(1)
        bt = QLabel("Нарезка не выбрана")
        bt.setObjectName("cardTitle")
        bt.setAlignment(Qt.AlignCenter)
        bl.addWidget(bt)
        bs = hint("Выбери нарезку в списке сверху или нарежь новую запись.")
        bs.setAlignment(Qt.AlignCenter)
        bl.addWidget(bs)
        bl.addSpacing(10)
        go = QPushButton("К нарезке")
        go.setObjectName("primary")
        go.clicked.connect(lambda: self.win.go("cut"))
        bl.addWidget(go, 0, Qt.AlignCenter)
        bl.addStretch(2)
        lay.addWidget(self.blank, 1)
        self.split.hide()

        self.empty = hint("")
        lay.addWidget(self.empty)
        self.empty.hide()
        self.win.bus.rebuilt.connect(self._rebuilt)
        self.win.bus.added.connect(self._added)
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
        # пока нарезку не выбрали — список пустой (при запуске «Клипы» пустые)
        cur = self.proj["_path"] if self.proj else None
        self.projects.setCurrentIndex(recent.index(cur) if cur in recent else -1)

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
        try:
            autoclip.register_project(proj["_path"])
        except OSError:
            pass
        self.projects.setCurrentIndex(0)
        self.search.blockSignals(True)
        self.search.clear()                          # поиск — по расшифровке этой записи
        self.search.blockSignals(False)
        self.left_stack.setCurrentIndex(0)
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
                f"{autoclip.fmt_time(c['start'])}–{autoclip.fmt_time(c['end'])}"
                f" · {c['end'] - c['start']:.0f} с · " + " · ".join(autoclip.clip_tags(c)))
            if c.get("marks"):
                it.setToolTip("Клип по метке из OBS")
            icon = self.cover_icon(c)
            if icon:
                it.setIcon(icon)
            it.setData(Qt.UserRole, c["id"])
            it.setData(CLIP_PATH, self.clip_path(c))
            self.list.addItem(it)
            if c["id"] == select_id:
                row = i
        # кандидаты — серыми, внизу списка («Все») или отдельно («Кандидаты»)
        if want is None or "candidate" in want:
            gray = QColor(MUTED)
            blank = QPixmap(COVER_W, COVER_H)          # пустое место вместо обложки — строки ровные
            blank.fill(Qt.transparent)
            for k in sorted(self.proj.get("candidates") or [], key=lambda k: -k["score"]):
                it = QListWidgetItem(
                    QIcon(blank), f"☆ {k['score']:.1f}   {k['title']}\n"
                    f"{autoclip.fmt_time(k['start'])}–{autoclip.fmt_time(k['end'])}"
                    f" · {k['end'] - k['start']:.0f} с · кандидат")
                it.setForeground(gray)
                it.setToolTip("Кандидат: момент без видео. «Собрать» — сделать из него клип")
                it.setData(Qt.UserRole, CAND + k["id"])
                self.list.addItem(it)
                if CAND + k["id"] == select_id:
                    row = self.list.count() - 1
        self.list.blockSignals(False)
        total = sum(c["status"] != "rejected" for c in self.proj["clips"])
        self.empty.setText("В этой нарезке клипов нет." if total == 0 and not
                           self.proj.get("candidates") else "В этом фильтре клипов нет.")
        self.empty.setVisible(self.list.count() == 0)
        self.blank.hide()
        self.split.show()
        self._row = -1
        if self.list.count():
            self.list.setCurrentRow(row)
            if self.list.currentRow() == row and self._row != row:
                self._row_changed(row)
        else:
            self.select()

    def current_clip(self):
        it = self.list.currentItem()
        if not (it and self.proj) or str(it.data(Qt.UserRole)).startswith(CAND):
            return None
        return autoclip.find_clip(self.proj, it.data(Qt.UserRole))

    def current_candidate(self):
        it = self.list.currentItem()
        ref = str(it.data(Qt.UserRole)) if (it and self.proj) else ""
        if not ref.startswith(CAND):
            return None
        return next((k for k in self.proj.get("candidates") or []
                     if k["id"] == ref[len(CAND):]), None)

    def cover_icon(self, c):
        """Маленькая обложка клипа для списка (пересчитывается, только если файл изменился)."""
        from PySide6.QtGui import QIcon
        if not c.get("cover"):
            return None
        path = os.path.join(os.path.dirname(self.proj["_path"]), c["cover"]["file"])
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        cached = self._covers.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        pm = QPixmap(path)
        if pm.isNull():
            return None
        pm = pm.scaled(COVER_W * 2, COVER_H * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(2)
        icon = QIcon(pm)
        self._covers[path] = (mtime, icon)
        return icon

    def clip_path(self, c):
        return os.path.join(os.path.dirname(self.proj["_path"]), c["file"])

    def _row_changed(self, row):
        if row == self._row:
            return
        self.save_desc()
        ans = self.ask_edits() if self._row >= 0 else "discard"
        if ans != "discard":
            self.list.blockSignals(True)
            self.list.setCurrentRow(self._row)
            self.list.blockSignals(False)
            if ans == "apply":
                item = self.list.item(row)
                self._then_select = item.data(Qt.UserRole) if item else None
                self.rebuild()
            return
        self._row = row
        self.select()

    def ask_edits(self):
        """Есть неприменённые правки — «Применить / Не применять / Отмена».
        Нет правок — "discard" (уходить можно без вопроса)."""
        if not self.pending():
            return "discard"
        ans = ask_choice(self, "Есть неприменённые правки.", EDITS_CHOICES)
        if ans == "discard":
            self.base = {}
        return ans

    def _leave_ok(self):
        """Перед сменой нарезки или фильтра: «Применить» пересобирает и остаётся на месте."""
        ans = self.ask_edits()
        if ans == "apply":
            self.rebuild()
        return ans == "discard"

    # ---------- выбранный клип ----------
    def select(self, *_):
        c = self.current_clip()
        self.editor.setEnabled(bool(c) and not self.busy)
        k = self.current_candidate()
        self.btn_build.setVisible(bool(k))
        if k:
            self.base = {}
            src = self.proj["source"]
            if os.path.isfile(src):
                self.player.show_at(src, k["start"] * 1000)
            else:
                self.player.clear()
            from html import escape
            self.btn_build.setEnabled(not self.busy and os.path.isfile(src))
            self.info.setText(
                f"<b>{escape(k['title'])}</b> <span style='color:{MUTED}'>· кандидат, без видео</span><br>"
                f"{autoclip.fmt_time(k['start'])}–{autoclip.fmt_time(k['end'])}, оценка {k['score']:.1f}"
                + (f"<br><span style='color:{MUTED}'>{escape(k.get('text', ''))}</span>"
                   if k.get("text") else ""))
            return
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
        lines = [f"<b>{c['title']}</b>"]
        feats = c.get("features") or self.features(c)
        if feats:
            fc = c.get("forecast") or forecast.predict(feats, c.get("score", 0),
                                                       forecast.load_model())
            lines.append(f"Прогноз: <b>{fc['value']:.1f} из 10</b> "
                         f"<span style='color:{MUTED}'>· {fc['note']}</span>")
            notes = forecast.retention_notes(c, feats)
            lines.append("&nbsp;&nbsp;".join(
                f"<span style='color:{NOTE_MARK[ok][1]}'>{NOTE_MARK[ok][0]} {t}</span>"
                for ok, t in notes))
        lines += [f"<span style='color:{MUTED}'>Оценка моментов {c['score']:.1f}"
                  + (f" — {parts}" if parts else "") + "</span>",
                  f"Зумов: {len(c['zooms'])}, запикано: "
                  f"{c['bleeps'] if c['bleeps'] is not None else '-'}"]
        if c.get("marks"):
            lines.append("📍 Метка из OBS: " + ", ".join(autoclip.fmt_time(t) for t in c["marks"]))
        ht = autoclip.hook_text(c)
        lines.append(ht[:1].upper() + ht[1:])
        if c.get("reason"):
            lines.append(f"Почему: {c['reason']}")
        self.info.setText("<br>".join(lines))
        self.fill_editor(c)

    def segments(self):
        """Расшифровка записи этой нарезки (кэшируется; нет — None)."""
        pp = self.proj["_path"]
        if getattr(self, "_segs_for", None) != pp:
            try:
                self._segs = autoclip.load_segments(self.proj)
            except autoclip.AutoClipError:
                self._segs = None
            self._segs_for = pp
        return self._segs

    def features(self, c):
        """Признаки старых клипов (до прогноза) — из расшифровки."""
        segs = self.segments()
        return forecast.clip_features(c, segs) if segs is not None else None

    # ---------- поиск по расшифровке ----------
    def run_search(self):
        q = self.search.text().strip()
        if q == getattr(self, "_last_q", None) and self.left_stack.currentIndex() == 1:
            return                                    # тот же запрос — выбор не сбрасываем
        self._last_q = q
        if not self.proj or len(q) < 2:
            self._last_q = None
            if self.left_stack.currentIndex() == 1:
                self.left_stack.setCurrentIndex(0)
                self.select()                         # вернуть выбранный клип в просмотр
            return
        segs = self.segments()
        self.left_stack.setCurrentIndex(1)
        self.editor.setEnabled(False)
        self.found.blockSignals(True)
        self.found.clear()
        self.found.blockSignals(False)
        self.btn_here.setEnabled(False)
        if segs is None:
            self.hits = []
            self.found_count.setText("Нет расшифровки этой записи.")
            return
        self.hits = autoclip.search_transcript(segs, q)
        n = len(self.hits)
        self.found_count.setText(f"Нашлось: {n}" if n else "Ничего не нашлось.")
        from html import escape
        for h in self.hits:
            a, b = h["hl_shown"]
            text = h["shown"]
            lo, hi = max(0, a - 28), min(len(text), b + 40)   # одна строка вокруг найденного
            snip = (("…" if lo else "") + escape(text[lo:a])
                    + f"<span style='color:{ACCENT}; font-weight:600'>{escape(text[a:b])}</span>"
                    + escape(text[b:hi]) + ("…" if hi < len(text) else ""))
            it = QListWidgetItem()
            it.setToolTip(text)
            lbl = QLabel(f"<b>{autoclip.fmt_time(h['t'])}</b>&nbsp;&nbsp;{snip}")
            lbl.setTextFormat(Qt.RichText)
            lbl.setContentsMargins(10, 0, 10, 0)
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            it.setSizeHint(QSize(100, 36))
            self.found.addItem(it)
            self.found.setItemWidget(it, lbl)

    def show_found(self, row):
        if not (0 <= row < len(self.hits)):
            self.btn_here.setEnabled(False)
            return
        h = self.hits[row]
        src = self.proj["source"]
        self.btn_here.setEnabled(not self.busy and os.path.isfile(src))
        if os.path.isfile(src):
            self.player.show_at(src, max(0.0, h["t"] - 1.0) * 1000)
            from html import escape
            self.info.setText(f"<b>Запись, {autoclip.fmt_time(h['t'])}</b><br>{escape(h['shown'])}")
        else:
            self.info.setText("Исходной записи нет на месте — перемотать некуда.")

    def clip_here(self):
        row = self.found.currentRow()
        if self.busy or not (0 <= row < len(self.hits)):
            return
        t = self.hits[row]["t"]
        self.busy = True
        self.btn_here.setEnabled(False)
        self.here_state.setText("Собираю клип…")
        pp, bus = self.proj["_path"], self.win.bus

        def work():
            try:
                rec = autoclip.clip_from_search(pp, t)
                bus.added.emit(rec["id"], None)
            except autoclip.AutoClipError as e:
                bus.added.emit(None, str(e))
            except Exception:
                bus.added.emit(None, "❌ " + traceback.format_exc()[-800:])
        threading.Thread(target=work, daemon=True).start()

    def build_candidate(self):
        k = self.current_candidate()
        if self.busy or not k:
            return
        self.busy = True
        self.btn_build.setEnabled(False)
        self.btn_build.setText("Собираю…")
        pp, bus, kid = self.proj["_path"], self.win.bus, k["id"]

        def work():
            try:
                rec = autoclip.build_candidate(pp, kid)
                bus.added.emit(rec["id"], None)
            except autoclip.AutoClipError as e:
                bus.added.emit(None, str(e))
            except Exception:
                bus.added.emit(None, "❌ " + traceback.format_exc()[-800:])
        threading.Thread(target=work, daemon=True).start()

    def _added(self, cid, err):
        self.btn_build.setText("Собрать")
        self.busy = False
        self.here_state.setText("")
        if err:
            self.btn_here.setEnabled(True)
            self.btn_build.setEnabled(True)
            QMessageBox.warning(self, "AutoClip", err)
            return
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.left_stack.setCurrentIndex(0)
        if self.filter not in (0, 1):                # новый клип виден в «Все» и «Новые»
            self.filter = 0
            for j, b in enumerate(self.filter_btns):
                b.setChecked(j == 0)
        self.base = {}
        self.reload(cid)

    def fill_editor(self, c):
        cfg = autoclip.clip_config(self.proj, c)
        self.base = {"hook": bool((c.get("hook") or {}).get("on")), "zoom": bool(cfg["zoom"]),
                     "bleep": bool(cfg["bleep"]), "subs": bool(cfg["subs"]),
                     "sub_y": autoclip.SUB_POSITIONS[autoclip.sub_position_name(cfg["sub_y"])],
                     "safe_zone": bool(cfg.get("safe_zone")), "bleep_sound": cfg["bleep_sound"],
                     "nick": bool(cfg.get("nick")),
                     "start": round(c["start"], 1), "end": round(c["end"], 1)}
        widgets = (self.e_hook, self.e_zoom, self.e_bleep, self.e_subs, self.e_pos, self.e_safe,
                   self.e_start, self.e_end, self.e_sound, self.e_nick)
        for w in widgets:
            w.blockSignals(True)
        fill_sounds(self.e_sound, cfg["bleep_sound"])
        b = self.base
        self.e_hook.setChecked(b["hook"])
        self.e_zoom.setChecked(b["zoom"])
        self.e_bleep.setChecked(b["bleep"])
        self.e_subs.setChecked(b["subs"])
        self.e_pos.setCurrentText(autoclip.sub_position_name(b["sub_y"]))
        self.e_safe.setChecked(b["safe_zone"])
        self.e_nick.setChecked(b["nick"])
        self.e_pos.setEnabled(b["subs"])
        self.e_safe.setEnabled(b["subs"])
        self.e_sound.setEnabled(b["bleep"])
        for w in (self.e_hook, self.e_zoom, self.e_bleep, self.e_subs, self.e_safe, self.e_nick):
            w.update()
        self.e_start.setText(autoclip.fmt_time_exact(b["start"]))
        self.e_end.setText(autoclip.fmt_time_exact(b["end"]))
        for w in widgets:
            w.blockSignals(False)
        good = c["status"] == "good"
        self.btn_good.setText("↩  Убрать из хороших" if good else "👍  Хороший")
        self._changed()
        self.refresh_desc()
        self.refresh_pub()

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
                "safe_zone": self.e_safe.isChecked(), "bleep_sound": self.e_sound.currentText(),
                "nick": self.e_nick.isChecked(),
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

    # ---------- описание ----------
    def show_tab(self, i):
        for j, b in enumerate(self.ed_tabs):
            b.setChecked(j == i)
        self.ed_stack.setCurrentIndex(i)

    def set_desc_platform(self, key):
        self.save_desc()
        self.desc_platform = key
        for k, b in self.desc_btns.items():
            b.setChecked(k == key)
        self.refresh_desc()

    def tag_cfg(self):
        """Хэштеги берутся из нынешних «Настроек», а не из тех, что были при нарезке."""
        s = self.win.settings
        return {"hashtags": s.get("hashtags", ""), "platform_tags": s.get("platform_tags", {})}

    def refresh_desc(self):
        c = self.current_clip()
        self._desc_timer.stop()
        self._desc_clip = c["id"] if c else None
        self.desc.blockSignals(True)
        self.desc.setPlainText(autoclip.clip_description(c, self.desc_platform, self.tag_cfg())
                               if c else "")
        self.desc.blockSignals(False)
        self._desc_info(c)

    def _desc_info(self, c):
        text = self.desc.toPlainText()
        n = len(re.findall(r"#\w+", text))
        self.desc_tags.setText(f"хэштегов: {n} из {autoclip.MAX_TAGS}" +
                               (" — многовато" if n > autoclip.MAX_TAGS else ""))
        custom = bool(c and (c.get("desc_custom") or {}).get(self.desc_platform))
        self.btn_desc_reset.setEnabled(custom)
        self.desc_state.setText("Твой текст" if custom else "Предложено программой")

    def _desc_edited(self):
        n = len(re.findall(r"#\w+", self.desc.toPlainText()))
        self.desc_tags.setText(f"хэштегов: {n} из {autoclip.MAX_TAGS}" +
                               (" — многовато" if n > autoclip.MAX_TAGS else ""))
        self._desc_timer.start()

    def save_desc(self):
        """Сохраняет правку описания (через 0,6 с после последней буквы)."""
        if not self._desc_timer.isActive() and not self._desc_pending():
            return
        self._desc_timer.stop()
        cid = self._desc_clip
        if not (cid and self.proj):
            return
        c = autoclip.find_clip(self.proj, cid)
        text = self.desc.toPlainText()
        auto = autoclip.auto_description(c, self.desc_platform, self.tag_cfg())
        autoclip.set_description(self.proj["_path"], cid, self.desc_platform,
                                 None if text.strip() == auto.strip() else text)
        self.proj = autoclip.load_project(self.proj["_path"])
        self._desc_info(autoclip.find_clip(self.proj, cid))

    def _desc_pending(self):
        if not (self._desc_clip and self.proj):
            return False
        c = autoclip.find_clip(self.proj, self._desc_clip)
        return self.desc.toPlainText().strip() != autoclip.clip_description(
            c, self.desc_platform, self.tag_cfg()).strip()

    def copy_desc(self):
        self.save_desc()
        QApplication.clipboard().setText(self.desc.toPlainText())
        self.desc_state.setText("Скопировано ✓")

    def reset_desc(self):
        c = self.current_clip()
        if c:
            self._desc_timer.stop()
            autoclip.set_description(self.proj["_path"], c["id"], self.desc_platform, None)
            self.proj = autoclip.load_project(self.proj["_path"])
            self.refresh_desc()

    # ---------- публикация ----------
    def refresh_pub(self):
        c = self.current_clip()
        pub = (c or {}).get("published") or {}
        for key, (state, link, mark) in self.pub_rows.items():
            p = pub.get(key)
            text = f"выложен {p['date'][8:10]}.{p['date'][5:7]}" if p else "не выложен"
            if p and isinstance(p.get("views"), (int, float)):
                text += f"\n{int(p['views']):,} просм.".replace(",", " ")
            state.setText(text)
            link.blockSignals(True)
            link.setText((p or {}).get("url", ""))
            link.blockSignals(False)
            link.setVisible(bool(p))                 # ссылка нужна, только когда выложил
            link.setEnabled(bool(p))
            mark.setText("Снять отметку" if p else "Выложил")

    def publish(self, platform, rect=None):
        """Описание — в буфер, страница загрузки — отдельным окном. Публикует сам Гоша."""
        c = self.current_clip()
        if not c:
            return
        self.save_desc()
        QApplication.clipboard().setText(
            autoclip.clip_description(c, platform, self.tag_cfg()))
        try:
            how = autoclip.open_upload(platform, rect)
        except autoclip.AutoClipError as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            return
        name = autoclip.PLATFORMS[platform]
        self.pub_state.setText(f"Открыл {name}{'' if how == 'edge' else ' в браузере'} · "
                               f"описание для {name} в буфере")

    def publish_all(self):
        scr = QApplication.primaryScreen()
        g = scr.availableGeometry()
        k = scr.devicePixelRatio()
        rects = autoclip.side_by_side((g.x() * k, g.y() * k, g.width() * k, g.height() * k),
                                      len(autoclip.PLATFORMS))
        for key, rect in reversed(list(zip(autoclip.PLATFORMS, rects))):
            self.publish(key, rect)                  # TikTok последним — его описание в буфере
        self.pub_state.setText("Открыл три окна · в буфере описание для TikTok, для остальных — "
                               "«Копировать описание» на вкладке «Описание»")

    def toggle_published(self, platform):
        c = self.current_clip()
        if not c:
            return
        on = platform not in (c.get("published") or {})
        url = self.pub_rows[platform][1].text()
        try:
            autoclip.mark_published(self.proj["_path"], c["id"], platform, on, url)
        except autoclip.AutoClipError as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            return
        self.base = {}
        self.reload(c["id"])
        self.show_tab(2)

    def save_link(self, platform):
        c = self.current_clip()
        if c and platform in (c.get("published") or {}):
            autoclip.mark_published(self.proj["_path"], c["id"], platform, True,
                                    self.pub_rows[platform][1].text())
            self.proj = autoclip.load_project(self.proj["_path"])

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
        nxt, self._then_select = getattr(self, "_then_select", None), None
        self.reload(nxt if nxt and not err else cid)
        self.state.setText(err or "Готово ✓")
        if err:
            self.win._close_after_rebuild = False
            QMessageBox.warning(self, "AutoClip", err)
        elif getattr(self.win, "_close_after_rebuild", False):
            QTimer.singleShot(0, self.win.close)    # «Применить» при закрытии — теперь закрываем

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


# ---------------- раздел «Подборка» ----------------

class WeeklyPage(QWidget):
    """Один ролик из «хороших» и «выложенных» клипов за последние дни.
    Клипы можно убрать галочкой и переставить (перетаскиванием или ↑ ↓)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.s = win.settings
        self.busy = False
        self.last = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(14)
        lay.addLayout(page_title("Подборка", "Один ролик из «хороших» и «выложенных» клипов "
                                             "за последние дни. Лучшие — первыми."))

        row = QHBoxLayout()
        row.setSpacing(18)
        self.days = Stepper(1, 30, int(self.s["weekly_days"]))
        self.days.valueChanged.connect(self._days_changed)
        row.addLayout(labeled("За последние дней", self.days))
        fmt = QHBoxLayout()
        fmt.setSpacing(6)
        self.fmt_btns = {}
        for key, text in (("vertical", "Вертикальная  1080×1920"),
                          ("horizontal", "Горизонтальная  1920×1080")):
            b = QPushButton(text)
            b.setObjectName("filter")
            b.setCheckable(True)
            b.clicked.connect(lambda _, k=key: self.set_format(k))
            fmt.addWidget(b)
            self.fmt_btns[key] = b
        box = QVBoxLayout()
        box.setSpacing(4)
        lbl = QLabel("Формат")
        lbl.setObjectName("fieldLabel")
        box.addWidget(lbl)
        box.addLayout(fmt)
        row.addLayout(box)
        row.addStretch(1)
        b = QPushButton("Обновить список")
        b.clicked.connect(self.refresh)
        row.addWidget(b, 0, Qt.AlignBottom)
        lay.addLayout(row)
        self.set_format(self.s["weekly_format"])

        body = QHBoxLayout()
        body.setSpacing(10)
        self.list = QListWidget()
        self.list.setObjectName("clipList")
        self.list.setWordWrap(True)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.itemChanged.connect(self._summary)
        self.list.model().rowsMoved.connect(self._summary)
        body.addWidget(self.list, 1)
        side = QVBoxLayout()
        side.setSpacing(6)
        self.up = QPushButton("↑")
        self.down = QPushButton("↓")
        for b, d in ((self.up, -1), (self.down, 1)):
            b.setObjectName("square")
            b.setToolTip("Выше" if d < 0 else "Ниже")
            b.clicked.connect(lambda _, d=d: self.move(d))
            side.addWidget(b)
        side.addStretch(1)
        body.addLayout(side)
        lay.addLayout(body, 1)

        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.addStretch(1)
        t = QLabel("Клипов для подборки нет")
        t.setObjectName("cardTitle")
        t.setAlignment(Qt.AlignCenter)
        el.addWidget(t)
        self.empty_hint = hint("")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        el.addWidget(self.empty_hint)
        el.addSpacing(10)
        go = QPushButton("К клипам")
        go.setObjectName("primary")
        go.clicked.connect(lambda: self.win.go("clips"))
        el.addWidget(go, 0, Qt.AlignCenter)
        el.addStretch(2)
        lay.addWidget(self.empty, 1)

        self.summary = hint("")
        lay.addWidget(self.summary)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn = QPushButton("🎞   Собрать подборку")
        self.btn.setObjectName("accent")
        self.btn.setMinimumWidth(260)
        self.btn.clicked.connect(self.build)
        row.addWidget(self.btn)
        col = QVBoxLayout()
        col.setSpacing(6)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        col.addWidget(self.bar)
        self.state = hint("")
        col.addWidget(self.state)
        row.addLayout(col, 1)
        self.btn_open = QPushButton("Открыть")
        self.btn_open.clicked.connect(lambda: self.last and open_path(self.last))
        self.btn_show = QPushButton("Показать в папке")
        self.btn_show.clicked.connect(lambda: self.last and show_in_folder(self.last))
        for b in (self.btn_open, self.btn_show):
            b.setEnabled(False)
            row.addWidget(b)
        lay.addLayout(row)

        row = QHBoxLayout()
        self.dir_hint = hint("")
        row.addWidget(self.dir_hint, 1)
        b = QPushButton("Папка…")
        b.setObjectName("ghost")
        b.clicked.connect(self.pick_dir)
        row.addWidget(b)
        lay.addLayout(row)
        self._show_dir()

        win.bus.weekly_progress.connect(self._progress)
        win.bus.weekly_done.connect(self._done)

    # ---------- настройки страницы ----------
    def _days_changed(self, v):
        self.s["weekly_days"] = v
        save_settings(self.s)
        self.refresh()

    def set_format(self, key):
        if key not in self.fmt_btns:
            key = "vertical"
        for k, b in self.fmt_btns.items():
            b.setChecked(k == key)
        self.s["weekly_format"] = key
        save_settings(self.s)

    def _show_dir(self):
        self.dir_hint.setText(f"Подборки сохраняются в {self.s['weekly_dir']}")

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Куда сохранять подборки", self.s["weekly_dir"])
        if d:
            self.s["weekly_dir"] = os.path.normpath(d)
            save_settings(self.s)
            self._show_dir()

    # ---------- список ----------
    def refresh(self):
        if self.busy:
            return
        items = autoclip.weekly_candidates(self.days.value())
        self.list.blockSignals(True)
        self.list.clear()
        for c in items:
            date = f"{c['date'][8:10]}.{c['date'][5:7]}" if c["date"] else ""
            it = QListWidgetItem(
                f"★ {c['score']:.1f}   {c['title']}\n"
                f"{c['dur']:.0f} с  ·  {autoclip.STATUSES.get(c['status'], c['status'])}"
                f"  ·  {date}  ·  {c['source']}")
            it.setData(Qt.UserRole, c["path"])
            it.setData(Qt.UserRole + 1, c["dur"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            it.setCheckState(Qt.Checked)
            self.list.addItem(it)
        self.list.blockSignals(False)
        has = self.list.count() > 0
        self.list.setVisible(has)
        self.up.setVisible(has)
        self.down.setVisible(has)
        self.empty.setVisible(not has)
        self.empty_hint.setText(f"За последние {self.days.value()} дн. нет клипов со статусом "
                                "«хороший» или «выложен». Отметь клипы в разделе «Клипы».")
        if has:
            self.list.setCurrentRow(0)
        self._summary()

    def chosen(self):
        """Отмеченные клипы в нынешнем порядке: [(путь, длина)]."""
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                out.append((it.data(Qt.UserRole), float(it.data(Qt.UserRole + 1) or 0)))
        return out

    def _summary(self, *_):
        ch = self.chosen()
        total = sum(d for _, d in ch)
        self.summary.setText(f"В подборке {len(ch)} из {self.list.count()} клипов  ·  "
                             f"{autoclip.fmt_time(total)}" if self.list.count() else "")
        self.btn.setEnabled(bool(ch) and not self.busy)

    def move(self, d):
        row = self.list.currentRow()
        new = row + d
        if row < 0 or not (0 <= new < self.list.count()):
            return
        it = self.list.takeItem(row)
        self.list.insertItem(new, it)
        self.list.setCurrentRow(new)
        self._summary()

    # ---------- сборка ----------
    def build(self):
        paths = [p for p, _ in self.chosen()]
        if not paths or self.busy:
            return
        self.busy = True
        self.btn.setEnabled(False)
        self.btn_open.setEnabled(False)
        self.btn_show.setEnabled(False)
        self.bar.setValue(0)
        self.state.setText("Собираю…")
        fmt = self.s["weekly_format"]
        autoclip.WEEKLY_DIR = self.s["weekly_dir"]
        bus = self.win.bus

        def work():
            try:
                out = autoclip.build_compilation(
                    paths, fmt, progress=lambda st, pct, msg: bus.weekly_progress.emit(float(pct), msg))
                bus.weekly_done.emit(out, None)
            except autoclip.AutoClipError as e:
                bus.weekly_done.emit("", str(e))
            except Exception:
                bus.weekly_done.emit("", "❌ " + traceback.format_exc()[-800:])
        threading.Thread(target=work, daemon=True).start()

    def _progress(self, pct, msg):
        self.bar.setValue(int(pct * 10))
        self.state.setText(f"Собираю… {pct:.0f}%  {msg}")

    def _done(self, out, err):
        self.busy = False
        self._summary()
        if err:
            self.bar.setValue(0)
            self.state.setText(err)
            return
        self.last = out
        self.bar.setValue(1000)
        self.state.setText(f"Готово: {os.path.basename(out)}")
        self.btn_open.setEnabled(True)
        self.btn_show.setEnabled(True)


# ---------------- раздел «Настройки» ----------------

class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.s = win.settings
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("scrollBody")
        scroll.setWidget(body)
        outer.addWidget(scroll)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(16)
        lay.addLayout(page_title("Настройки"))

        # --- новые клипы ---
        box, v = card("Новые клипы", "Так будут нарезаться новые клипы. "
                                     "У отдельного клипа всё можно поменять в «Клипах».")
        self.cb_subs = self._toggle("subs")
        v.addWidget(option_row("Субтитры", self.cb_subs))
        self.sub_pos = self._combo(autoclip.SUB_POSITIONS, "sub_pos")
        v.addWidget(option_row("Где субтитры", self.sub_pos))
        self.cb_safe = self._toggle("safe_zone")
        v.addWidget(option_row("Сейф-зона соцсетей", self.cb_safe,
                               "Субтитры не заходят под кнопки, ник и подпись "
                               "TikTok, Shorts и Reels"))
        self.preview = SubsPreview()
        v.addWidget(option_row("Как это выглядит", self.preview,
                               "Белое — субтитры, красное — зона кнопок соцсетей"))
        v.addWidget(separator())
        self.cb_zoom = self._toggle("zoom")
        v.addWidget(option_row("Зум на эмоциях", self.cb_zoom))
        self.cb_hook = self._toggle("hook")
        v.addWidget(option_row("Хук в начале", self.cb_hook,
                               "1–2 секунды яркой реакции из этого же клипа в самом начале"))
        self.cam = self._combo(WEBCAM, "cam")
        v.addWidget(option_row("Раскладка записи", self.cam, "Куда приближать зум"))
        v.addWidget(separator())
        self.cb_bleep = self._toggle("bleep")
        v.addWidget(option_row("Мат звуком", self.cb_bleep))
        snd = QHBoxLayout()
        snd.setSpacing(6)
        self.sound = QComboBox()
        self.sound.setMinimumWidth(190)
        self.sound.currentTextChanged.connect(lambda t: self._set("sound", t) if t else None)
        snd.addWidget(self.sound)
        snd.addWidget(SoundButton(self.sound))
        b = QPushButton("Свои звуки…")
        b.setToolTip("Положи в эту папку свой mp3 или wav — он появится в списке")
        b.clicked.connect(self.open_sounds)
        snd.addWidget(b)
        v.addWidget(option_row("Звук на мат", snd))
        v.addWidget(separator())
        self.cb_marks = self._toggle("marks")
        v.addWidget(option_row("Метки из OBS", self.cb_marks,
                               "Моменты, где ты нажал «Добавить маркер главы», идут первыми"))
        v.addWidget(separator())
        from PySide6.QtWidgets import QDoubleSpinBox

        def score_box(key):
            sb = QDoubleSpinBox()
            sb.setRange(0.5, 10.0)
            sb.setSingleStep(0.1)
            sb.setDecimals(1)
            sb.setValue(float(self.s.get(key, DEFAULTS[key])))
            sb.setFixedWidth(90)
            sb.valueChanged.connect(lambda x: self._set(key, round(x, 1)))
            return sb
        self.auto_min = score_box("auto_min_score")
        v.addWidget(option_row("Порог «Авто» с языковой моделью", self.auto_min,
                               "Оценка, с которой момент становится клипом. Ниже — кандидат"))
        self.auto_min_plain = score_box("auto_min_score_plain")
        v.addWidget(option_row("Порог «Авто» без модели", self.auto_min_plain,
                               "Без модели оценки ниже, поэтому и порог свой"))
        self.auto_max = Stepper(1, 100, int(self.s.get("auto_max", DEFAULTS["auto_max"])))
        self.auto_max.valueChanged.connect(lambda x: self._set("auto_max", x))
        v.addWidget(option_row("Не больше клипов в «Авто»", self.auto_max,
                               "Остальные яркие моменты — кандидатами, без видео"))
        lay.addWidget(box)

        # --- ник в углу ---
        box, v = card("Ник в углу", "Тестовая функция: небольшая подпись в углу клипа. "
                                    "Не заходит на субтитры и в зону кнопок соцсетей.")
        self.cb_nick = self._toggle("nick")
        v.addWidget(option_row("Показывать ник", self.cb_nick))
        self.nick = QLineEdit(self.s["nick_text"])
        self.nick.setMinimumWidth(220)
        self.nick.textChanged.connect(lambda t: self._set("nick_text", t.strip()))
        v.addWidget(option_row("Текст", self.nick))
        self.nick_corner = self._combo(autoclip.NICK_CORNERS, "nick_corner")
        v.addWidget(option_row("Угол", self.nick_corner))
        self.nick_size = self._combo(NICK_SIZES, "nick_size")
        v.addWidget(option_row("Размер", self.nick_size))
        op = QHBoxLayout()
        op.setSpacing(10)
        self.nick_opacity = QSlider(Qt.Horizontal)
        self.nick_opacity.setRange(30, 100)
        self.nick_opacity.setSingleStep(5)
        self.nick_opacity.setFixedWidth(180)
        self.nick_opacity.setValue(int(self.s["nick_opacity"]))
        self.nick_op_label = QLabel()
        self.nick_op_label.setFixedWidth(40)
        op.addWidget(self.nick_opacity)
        op.addWidget(self.nick_op_label)
        self.nick_opacity.valueChanged.connect(self._nick_opacity)
        self._nick_opacity(self.nick_opacity.value())
        v.addWidget(option_row("Видимость", op, "100% — ярко, 30% — едва заметно"))
        lay.addWidget(box)
        for w in (self.cb_nick,):
            w.toggled.connect(self._update_preview)
        for w in (self.nick_corner, self.nick_size, self.nick):
            (w.textChanged if isinstance(w, QLineEdit) else w.currentTextChanged).connect(
                self._update_preview)
        self.nick_opacity.valueChanged.connect(self._update_preview)
        for w in (self.nick, self.nick_corner, self.nick_size, self.nick_opacity):
            self.cb_nick.toggled.connect(w.setEnabled)
            w.setEnabled(self.cb_nick.isChecked())
        self._update_preview()
        for w in (self.cb_subs, self.cb_safe):
            w.toggled.connect(self._update_preview)
        self.sub_pos.currentTextChanged.connect(self._update_preview)
        self.cb_subs.toggled.connect(self.sub_pos.setEnabled)
        self.cb_subs.toggled.connect(self.cb_safe.setEnabled)
        self.cb_bleep.toggled.connect(self.sound.setEnabled)
        self.sub_pos.setEnabled(self.cb_subs.isChecked())
        self.cb_safe.setEnabled(self.cb_subs.isChecked())
        self.refresh_sounds()
        self.sound.setEnabled(self.cb_bleep.isChecked())
        self._update_preview()

        # --- пресеты экспорта ---
        box, v = card("Пресеты экспорта", "H.264, постоянный битрейт, MP4, цвет Rec. 709, "
                                          "звук AAC 320 кбит/с.")
        self.presets = QListWidget()
        self.presets.setObjectName("clipList")
        self.presets.setSelectionMode(QAbstractItemView.SingleSelection)
        self.presets.setFixedHeight(56)
        v.addWidget(self.presets)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.p_name = QLineEdit()
        self.p_name.setPlaceholderText("Название, например «Shorts 1080p30»")
        row.addLayout(labeled("Свой пресет", self.p_name), 1)
        self.p_w = self._spin(240, 4320, 1080, 2, "Ширина")
        self.p_h = self._spin(240, 4320, 1920, 2, "Высота")
        self.p_fps = self._spin(24, 120, 60, 1, "Кадров в секунду")
        self.p_kbps = self._spin(1000, 100000, 18000, 500, "Битрейт, Кбит/с")
        for label, w in (("Ширина", self.p_w), ("Высота", self.p_h), ("Кадров/с", self.p_fps),
                         ("Кбит/с", self.p_kbps)):
            w.setFixedWidth(84)
            row.addLayout(labeled(label, w))
        b = QPushButton("Добавить")
        b.setObjectName("primary")
        b.clicked.connect(self.add_preset)
        row.addWidget(b, 0, Qt.AlignBottom)
        v.addLayout(row)
        row = QHBoxLayout()
        self.btn_del = QPushButton("Удалить выбранный")
        self.btn_del.setObjectName("danger")
        self.btn_del.clicked.connect(self.delete_preset)
        row.addWidget(self.btn_del)
        self.p_state = hint("")
        row.addWidget(self.p_state, 1)
        v.addLayout(row)
        self.presets.currentRowChanged.connect(self._preset_selected)
        lay.addWidget(box)
        self.refresh_presets()

        # --- языковая модель ---
        box, v = card("Языковая модель", "Авто: Ollama, если запущена; иначе Claude API, если "
                                         "задан ключ ANTHROPIC_API_KEY; иначе только по звуку и речи.")
        self.llm = QComboBox()
        self.llm.addItems(list(LLM_MODES))
        cur = next((k for k, val in LLM_MODES.items() if val == self.s["llm"]), "Авто")
        self.llm.setCurrentText(cur)
        self.llm.currentTextChanged.connect(lambda t: self._set("llm", LLM_MODES[t]))
        v.addWidget(option_row("Как искать моменты", self.llm))
        self.ollama = QLineEdit(self.s["ollama_model"])
        self.ollama.setMinimumWidth(220)
        self.ollama.textChanged.connect(lambda t: self._set("ollama_model", t.strip()))
        v.addWidget(option_row("Модель Ollama", self.ollama))
        row = QHBoxLayout()
        b = QPushButton("Проверить")
        b.clicked.connect(self.check_llm)
        row.addWidget(b)
        self.llm_state = hint("")
        row.addWidget(self.llm_state, 1)
        v.addLayout(row)
        lay.addWidget(box)

        # --- хэштеги и описание ---
        box, v = card("Хэштеги и описание",
                      "Описание под клипом: название и хэштеги, всего не больше 5. Сначала "
                      "добавка площадки, потом постоянные, потом по содержанию клипа "
                      "(их придумывает языковая модель).")
        self.tags = QLineEdit(self.s["hashtags"])
        self.tags.setPlaceholderText("#стрим #игры")
        self.tags.setMinimumWidth(300)
        self.tags.textChanged.connect(lambda t: self._set("hashtags", t.strip()))
        v.addWidget(option_row("Всегда добавлять", self.tags))
        self.ptags = {}
        for key, name in autoclip.PLATFORMS.items():
            e = QLineEdit(self.s["platform_tags"].get(key, ""))
            e.setMinimumWidth(300)
            e.setPlaceholderText("ничего")
            e.textChanged.connect(lambda t, k=key: self._set_ptag(k, t))
            v.addWidget(option_row(f"Добавка для {name}", e))
            self.ptags[key] = e
        lay.addWidget(box)

        # --- прогноз ---
        box, v = card("Прогноз", "Оценка клипа из 10: правила удержания плюс то, чему программа "
                                 "научилась на твоих оценках и просмотрах. Это оценка, а не "
                                 "обещание просмотров.")
        self.views_days = Stepper(2, 7, int(self.s.get("views_days", 3)))
        self.views_days.valueChanged.connect(lambda d: self._set("views_days", d))
        vd = QHBoxLayout()
        vd.setSpacing(8)
        vd.addWidget(self.views_days)
        vd.addWidget(QLabel("дня"))
        v.addWidget(option_row("Спрашивать про просмотры через", vd,
                               "После «Выложил» — при запуске программы"))
        self.model_state = QLabel("")
        self.model_state.setWordWrap(True)
        self.model_state.setTextFormat(Qt.RichText)
        v.addWidget(self.model_state)
        b = QPushButton("Обучить сейчас")
        b.clicked.connect(lambda: (self.model_state.setText("Учусь…"), self.win.retrain()))
        row = QHBoxLayout()
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        lay.addWidget(box)

        # --- OBS ---
        box, v = card("OBS", "Новая запись в этой папке — AutoClip предложит её нарезать. "
                             "Пока слежка включена, крестик сворачивает программу в трей.")
        obs = QHBoxLayout()
        obs.setSpacing(6)
        self.obs = QLineEdit(self.s["obs_dir"])
        self.obs.setPlaceholderText("Папка, куда OBS пишет записи")
        self.obs.setMinimumWidth(300)
        self.obs.textChanged.connect(lambda t: self._set("obs_dir", t.strip()))
        obs.addWidget(self.obs)
        b = QPushButton("Выбрать…")
        b.clicked.connect(self.pick_obs)
        obs.addWidget(b)
        b = QPushButton("Найти в OBS")
        b.setToolTip("Взять папку записей из настроек OBS")
        b.clicked.connect(self.find_obs)
        obs.addWidget(b)
        v.addWidget(option_row("Папка OBS", obs))
        self.cb_watch = Toggle(bool(self.s["watch"]))
        self.cb_watch.toggled.connect(self.set_watch)
        v.addWidget(option_row("Следить за папкой", self.cb_watch,
                               "Предлагать нарезать новые записи, когда OBS их допишет"))
        self.min_minutes = Stepper(1, 120, int(self.s["min_minutes"]))
        self.min_minutes.valueChanged.connect(lambda m: self._set("min_minutes", m))
        mm = QHBoxLayout()
        mm.setSpacing(8)
        mm.addWidget(self.min_minutes)
        mm.addWidget(QLabel("мин"))
        v.addWidget(option_row("Не предлагать записи короче", mm, "Короткие записи — обычно тесты"))
        lay.addWidget(box)

        # --- обновления ---
        box, v = card("Обновления", f"Сейчас стоит версия {update.VERSION}. Обновляются только "
                                    "файлы программы, настройки и клипы остаются на месте.")
        self.cb_updates = self._toggle("check_updates")
        v.addWidget(option_row("Проверять при запуске", self.cb_updates,
                               "Спрашивать, если на GitHub вышла новая версия"))
        self.update_state = QLabel("" if update.REPO else
                                   "Репозиторий для обновлений ещё не подключён.")
        self.update_state.setWordWrap(True)
        v.addWidget(self.update_state)
        self.update_btn = QPushButton("Проверить сейчас")
        self.update_btn.setEnabled(bool(update.REPO))
        self.update_btn.clicked.connect(lambda: (self.update_state.setText("Проверяю…"),
                                                 self.win.check_updates(manual=True)))
        row = QHBoxLayout()
        row.addWidget(self.update_btn)
        row.addStretch(1)
        v.addLayout(row)
        lay.addWidget(box)

        # --- сборка ---
        box, v = card("Сборка клипов", "«На полную» — несколько клипов сразу, быстрее всего. "
                                       "«Фоновый» — по одному и с низким приоритетом, чтобы не "
                                       "мешать игре и стриму. «Авто» сам выбирает: запущены OBS "
                                       "или игра — фоновый, иначе на полную.")
        self.build_mode = QComboBox()
        self.build_mode.setMinimumWidth(190)
        for key, name in autoclip.BUILD_MODES.items():
            self.build_mode.addItem(name, key)
        i = self.build_mode.findData(self.s.get("build_mode", "auto"))
        self.build_mode.setCurrentIndex(max(0, i))
        self.build_mode.currentIndexChanged.connect(
            lambda i: self._set("build_mode", self.build_mode.itemData(i)))
        v.addWidget(option_row("Как собирать", self.build_mode))
        self.games = QLineEdit(self.s.get("game_processes", ""))
        self.games.setPlaceholderText("bg3.exe, cs2.exe")
        self.games.setMinimumWidth(300)
        self.games.textChanged.connect(lambda t: self._set("game_processes", t.strip()))
        v.addWidget(option_row("Мои игры", self.games,
                               "Для «Авто»: при этих программах — фоновый. Игру на весь экран "
                               "программа замечает и сама"))
        lay.addWidget(box)

        # --- отчёт об ошибке ---
        box, v = card("Отчёт об ошибке", "Что-то пошло не так — собери отчёт и отправь его. В нём "
                                         "логи, версии программ, настройки без ключей и токенов, "
                                         "отчёт последней нарезки. Записей и клипов в нём нет.")
        row = QHBoxLayout()
        self.report_btn = QPushButton("Отчёт об ошибке")
        self.report_btn.clicked.connect(self.win.make_report)
        row.addWidget(self.report_btn)
        self.report_state = hint("Архив появится на рабочем столе.")
        row.addWidget(self.report_state, 1)
        v.addLayout(row)
        lay.addWidget(box)

        lay.addWidget(hint(f"Настройки хранятся в {autoclip.user_dir()}"))
        lay.addStretch(1)

    def _set(self, key, value):
        self.s[key] = value
        save_settings(self.s)

    def _toggle(self, key):
        t = Toggle(bool(self.s.get(key)))
        t.toggled.connect(lambda v: self._set(key, v))
        return t

    def _combo(self, values, key):
        cb = QComboBox()
        cb.setMinimumWidth(190)
        cb.addItems(list(values))
        if self.s.get(key) in values:
            cb.setCurrentText(self.s[key])
        cb.currentTextChanged.connect(lambda t: self._set(key, t))
        return cb

    def _spin(self, lo, hi, val, step, tip):
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setValue(val)
        sp.setToolTip(tip)
        return sp

    def _set_ptag(self, key, text):
        tags = dict(self.s.get("platform_tags") or {})
        tags[key] = text.strip()
        self._set("platform_tags", tags)

    def _nick_opacity(self, v):
        self.nick_op_label.setText(f"{v}%")
        self._set("nick_opacity", int(v))

    def _update_preview(self, *_):
        if not hasattr(self, "nick_opacity"):          # карточка ника ещё строится
            return
        nick = {"nick": self.cb_nick.isChecked(), "nick_text": self.nick.text(),
                "nick_corner": self.nick_corner.currentText(),
                "nick_size": NICK_SIZES.get(self.nick_size.currentText(), 40),
                "nick_opacity": self.nick_opacity.value()}
        self.preview.set_state(autoclip.SUB_POSITIONS.get(self.sub_pos.currentText(), 0.6),
                               self.cb_safe.isChecked(), self.cb_subs.isChecked(), nick)

    def refresh_sounds(self):
        fill_sounds(self.sound, self.s.get("sound"))

    # --- пресеты ---
    def refresh_presets(self, select=None):
        self.all_presets = autoclip.load_presets()
        self.presets.clear()
        for p in self.all_presets:
            extra = "   ·   встроенный" if p.get("builtin") else ""
            self.presets.addItem(f"{p['name']}   —   {p['w']}×{p['h']}, {p['fps']} к/с, "
                                 f"{p['kbps']} Кбит/с{extra}")
        names = [p["name"] for p in self.all_presets]
        self.presets.setFixedHeight(min(220, 20 + 38 * len(self.all_presets)))
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

    def show_model(self, info):
        if not info or info.get("error"):
            self.model_state.setText(f"Не получилось обучиться: {(info or {}).get('error', '')}")
            return
        need = forecast.MIN_SAMPLES
        lines = [f"Оценок «Хороший» / «В корзину»: <b>{info['n_like']}</b> из {need}, "
                 f"клипов с просмотрами: <b>{info['n_views']}</b> из {need}."]
        if not (info.get("like") or info.get("views")):
            lines.append(f"<span style='color:{MUTED}'>Данных пока мало — прогноз считается "
                         "по правилам.</span>")
        else:
            lines.append(f"Модель учтена в прогнозе на {int(forecast.model_share(info) * 100)}%.")
            for key, title in (("views", "Что набирает просмотры"), ("like", "Что тебе нравится")):
                pairs = forecast.explain(info).get(key)
                if pairs:
                    lines.append(f"{title}: " + ", ".join(
                        f"<span style='color:{'#7dd99a' if w > 0 else '#ff7a90'}'>{n} "
                        f"{'+' if w > 0 else '−'}{abs(w):.2f}</span>" for n, w in pairs))
        self.model_state.setText("<br>".join(lines))

    def find_obs(self):
        d = autoclip.find_obs_record_dir()
        if d:
            self.obs.setText(d)
            self._set("obs_dir", d)
        else:
            QMessageBox.information(self, "AutoClip", "Папку записей в настройках OBS не нашёл — "
                                                      "выбери её кнопкой «Выбрать…».")

    def set_watch(self, on):
        if on and not self.s.get("obs_dir"):
            d = autoclip.find_obs_record_dir()
            if d:
                self.obs.setText(d)
                self._set("obs_dir", d)
        if on and not self.s.get("watch"):
            self.s["watch_since"] = time.time()      # предлагать только записи после включения
        self._set("watch", bool(on))
        self.win.watch_changed()

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
        if autoclip._ollama_alive():
            models = autoclip.ollama_models()
            want = autoclip.CONFIG["ollama_model"]
            got = autoclip.resolve_ollama_model(models)
            if not got:
                ollama = "Ollama работает, но моделей нет — ollama pull qwen3:14b"
            elif got.lower().split(":latest")[0] == want.lower().split(":latest")[0]:
                ollama = f"Ollama работает, {want} скачана"
            else:
                ollama = f"Ollama работает, но {want} не скачана — возьму {got}"
        else:
            ollama = "Ollama не запущена"
        key = "ключ Claude есть" if os.environ.get("ANTHROPIC_API_KEY") else "ключа Claude нет"
        mode = autoclip.pick_llm(self.s["llm"])
        names = {"ollama": "Ollama", "anthropic": "Claude API", "none": "без модели"}
        self.llm_state.setText(f"{ollama}, {key}. Сейчас будет: {names.get(mode, mode)}.")


# ---------------- вопрос про просмотры ----------------

class ViewsDialog(QDialog):
    """«Клип "…" выложен в TikTok 3 дня назад. Сколько просмотров?» — все вопросы одним списком."""

    def __init__(self, parent, questions):
        super().__init__(parent)
        self.questions = questions
        self.action = "snooze"
        self.setWindowTitle("AutoClip — просмотры")
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        t = QLabel("Сколько набрали клипы?")
        t.setObjectName("cardTitle")
        lay.addWidget(t)
        lay.addWidget(hint("Ответы учат прогноз. Процент досмотров — по желанию. Пустые строки "
                           "спрошу завтра."))
        from PySide6.QtGui import QIntValidator, QDoubleValidator
        self.rows = []
        for q in questions:
            row = QHBoxLayout()
            row.setSpacing(8)
            name = autoclip.PLATFORMS.get(q["platform"], q["platform"])
            d = q["days_ago"]
            lbl = QLabel(f"«{q['title']}»<br><span style='color:{MUTED}'>{name}, выложен "
                         f"{d} {plural(d, 'день', 'дня', 'дней')} назад</span>")
            lbl.setWordWrap(True)
            row.addWidget(lbl, 1)
            views = QLineEdit()
            views.setPlaceholderText("просмотры")
            views.setValidator(QIntValidator(0, 2_000_000_000, views))
            views.setFixedWidth(120)
            ret = QLineEdit()
            ret.setPlaceholderText("% досмотров")
            ret.setValidator(QDoubleValidator(0, 100, 1, ret))
            ret.setFixedWidth(110)
            row.addWidget(views)
            row.addWidget(ret)
            lay.addLayout(row)
            self.rows.append((q, views, ret))
        row = QHBoxLayout()
        skip = QPushButton("Пропустить")
        skip.setObjectName("ghost")
        skip.clicked.connect(lambda: self._done("skip"))
        later = QPushButton("Напомнить завтра")
        later.clicked.connect(lambda: self._done("snooze"))
        save = QPushButton("Сохранить")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(lambda: self._done("save"))
        row.addWidget(skip)
        row.addStretch(1)
        row.addWidget(later)
        row.addWidget(save)
        lay.addLayout(row)

    def _done(self, action):
        self.action = action
        self.accept()

    def apply(self):
        """Записать ответы. Возвращает, сколько клипов получили просмотры."""
        saved = 0
        for q, views, ret in self.rows:
            args = (q["project"], q["id"], q["platform"])
            v = views.text().strip()
            if self.action == "save" and v:
                r = ret.text().strip().replace(",", ".")
                forecast.record_views(*args, int(v), float(r) if r else None)
                saved += 1
            elif self.action == "skip":
                forecast.skip_views(*args)
            else:
                forecast.snooze_views(*args)
        return saved


# ---------------- «Что нового» ----------------

class NewsDialog(QDialog):
    """Список версий, новые сверху, с изменениями простыми словами."""

    def __init__(self, parent, entries, only_new=False):
        super().__init__(parent)
        self.setWindowTitle("AutoClip — что нового")
        self.setMinimumSize(560, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        t = QLabel(f"AutoClip обновился до {update.VERSION}" if only_new else "Что нового")
        t.setObjectName("cardTitle")
        lay.addWidget(t)
        body = QLabel(self.html(entries) if entries else "Список изменений не найден.")
        body.setWordWrap(True)
        body.setTextFormat(Qt.RichText)
        body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        body.setContentsMargins(0, 0, 8, 0)
        self.body = body
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setWidget(body)
        lay.addWidget(sa, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("Понятно")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)

    @staticmethod
    def html(entries):
        from html import escape
        parts = []
        for e in entries:
            date = f" <span style='color:{MUTED}'>· {escape(e['date'])}</span>" if e["date"] else ""
            cur = " <span style='color:#7dd99a'>· сейчас</span>" if e["version"] == update.VERSION else ""
            items = "".join(f"<li style='margin-bottom:4px'>{escape(i)}</li>" for i in e["items"])
            parts.append(f"<p style='margin-top:10px'><b>Версия {escape(e['version'])}</b>{date}{cur}</p>"
                         f"<ul style='margin-left:-18px'>{items}</ul>")
        return "".join(parts)


# ---------------- обновление ----------------

class UpdateDialog(QDialog):
    """«Вышла версия X» — Обновить / Не сейчас / Пропустить эту версию."""

    def __init__(self, parent, rel):
        super().__init__(parent)
        self.rel = rel
        self.action = "later"
        self.setWindowTitle("AutoClip — обновление")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        t = QLabel(f"Вышла версия {rel['version']}")
        t.setObjectName("cardTitle")
        lay.addWidget(t)
        lay.addWidget(hint(f"Сейчас стоит {update.VERSION}. Настройки, клипы и записи "
                           "не тронутся, программа перезапустится сама."))
        if rel.get("notes"):
            notes = QLabel(rel["notes"])
            notes.setWordWrap(True)
            notes.setTextFormat(Qt.PlainText)
            lay.addWidget(notes)
        self.state = QLabel("")
        lay.addWidget(self.state)
        row = QHBoxLayout()
        self.skip = QPushButton("Пропустить эту версию")
        self.skip.setObjectName("ghost")
        self.skip.clicked.connect(lambda: self._done("skip"))
        self.later = QPushButton("Не сейчас")
        self.later.clicked.connect(lambda: self._done("later"))
        self.go = QPushButton("Обновить")
        self.go.setObjectName("primary")
        self.go.setDefault(True)
        self.go.clicked.connect(lambda: self._done("update"))
        row.addWidget(self.skip)
        row.addStretch(1)
        row.addWidget(self.later)
        row.addWidget(self.go)
        lay.addLayout(row)

    def _done(self, action):
        self.action = action
        if action == "update":
            for b in (self.skip, self.later, self.go):
                b.setEnabled(False)
            self.state.setText("Скачиваю…")
            self.parent().install_update(self)
        else:
            self.accept()


# ---------------- новая запись OBS ----------------

class NewRecordingDialog(QDialog):
    """«Новая запись: <имя>, <длительность>, меток: N. Нарезать?»"""

    def __init__(self, parent, path, info):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle("AutoClip — новая запись")
        self.setModal(False)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(8)
        t = QLabel("Новая запись")
        t.setObjectName("cardTitle")
        lay.addWidget(t)
        lay.addWidget(QLabel(f"{os.path.basename(path)}\n{autoclip.fmt_time(info['dur'])}"
                             f"  ·  меток из OBS: {info['marks']}"))
        lay.addWidget(hint("Нарезать?"))
        row = QHBoxLayout()
        row.addStretch(1)
        no = QPushButton("Не надо")
        no.clicked.connect(self.reject)
        yes = QPushButton("Нарезать")
        yes.setObjectName("primary")
        yes.setDefault(True)
        yes.clicked.connect(self.accept)
        row.addWidget(no)
        row.addWidget(yes)
        lay.addLayout(row)


# ---------------- главное окно ----------------


class MainWindow(QMainWindow):
    PAGES = (("cut", "Нарезка", "\ue8c6"), ("clips", "Клипы", "\ue714"),
             ("weekly", "Подборка", "\ue8f1"), ("settings", "Настройки", "\ue713"))

    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.busy = False
        self.cancel = threading.Event()
        self.detached = None
        self.bus = Bus()

        self.setWindowTitle(f"AutoClip {update.VERSION}")
        self.resize(1200, 860)
        self.setMinimumSize(980, 720)
        if self.settings.get("geometry"):
            self.restoreGeometry(QByteArray.fromHex(self.settings["geometry"].encode()))

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(210)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 12)
        sl.setSpacing(0)
        brand = QLabel('Auto<span style="color:%s">Clip</span>' % ACCENT)
        brand.setObjectName("brand")
        sl.addWidget(brand)
        self.version_btn = QPushButton(f"версия {update.VERSION}")
        self.version_btn.setObjectName("version")
        self.version_btn.setCursor(Qt.PointingHandCursor)
        self.version_btn.setToolTip("Что нового")
        self.version_btn.clicked.connect(lambda: self.show_news())
        sl.addWidget(self.version_btn)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        f = QFont("Segoe UI", 10)
        self.nav.setIconSize(QSize(18, 18))
        for _, text, icon in self.PAGES:
            it = QListWidgetItem(glyph_icon(icon), "  " + text)
            it.setFont(f)
            self.nav.addItem(it)
        sl.addWidget(self.nav, 1)
        root.addWidget(side)

        self.stack = QStackedWidget()
        self.cut = CutPage(self)
        self.clips = ClipsPage(self)
        self.weekly = WeeklyPage(self)
        self.settings_page = SettingsPage(self)
        for w in (self.cut, self.clips, self.weekly, self.settings_page):
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
            self.settings_page.refresh_sounds()
            self.cut.write("Выбери запись и нажми «Нарезать».")
        except autoclip.AutoClipError as e:
            self.cut.write(str(e))
        for pp in self.settings.get("recent", []):
            try:
                if os.path.isfile(pp) and pp not in autoclip.known_projects():
                    autoclip.register_project(pp)
            except OSError:
                pass

        # --- трей и слежка за папкой OBS ---
        self._quitting = False
        self._queue = []             # записи, которые ждут, пока закончится текущая нарезка
        self._pending = []           # (путь, сведения) — спросить «Нарезать?», когда окно видно
        self._asked = set()          # уже спросили в этом запуске
        self._dialog = None
        self.tracker = autoclip.GrowthTracker()
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            from PySide6.QtGui import QIcon
            self.tray = QSystemTrayIcon(QIcon(ICON) if os.path.isfile(ICON) else self.windowIcon(), self)
            self.tray.setToolTip("AutoClip")
            menu = QMenu()
            menu.addAction("Открыть AutoClip", self.show_window)
            self.tray_watch = menu.addAction("Следить за папкой OBS")
            self.tray_watch.setCheckable(True)
            self.tray_watch.toggled.connect(self.settings_page.cb_watch.setChecked)
            menu.addSeparator()
            menu.addAction("Отчёт об ошибке", self.make_report)
            menu.addSeparator()
            menu.addAction("Выход", self.quit_from_tray)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda r: self.show_window()
                                        if r == QSystemTrayIcon.Trigger else None)
            self.tray.messageClicked.connect(self.show_window)
        self.fs_watch = None
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(3000)
        self.watch_timer.timeout.connect(self.scan_obs)
        self.watch_changed()

        # --- прогноз: обучиться на том, что есть, и спросить про просмотры ---
        self.bus.trained.connect(self.settings_page.show_model)
        self.retrain()
        QTimer.singleShot(1500, self.ask_views)

        # --- после обновления один раз показать «Что нового» ---
        self._news = None
        QTimer.singleShot(1200, self.news_after_update)

        # --- обновления: тихо спросить GitHub при запуске ---
        self.bus.report_done.connect(self.report_ready)
        self.bus.update_found.connect(self.update_found)
        self.bus.update_done.connect(self.update_installed)
        self._update_dialog = None
        if self.settings.get("check_updates", True) and update.REPO:
            QTimer.singleShot(3000, self.check_updates)

    # --- прогноз ---
    def retrain(self):
        def work():
            try:
                res = forecast.train()
            except Exception as e:
                res = {"error": str(e)}
            try:
                self.bus.trained.emit(res)
            except RuntimeError:                     # окно уже закрыли
                pass
        threading.Thread(target=work, daemon=True).start()

    def ask_views(self):
        qs = forecast.due_questions(int(self.settings.get("views_days", 3)))
        if not qs or getattr(self, "_views_dialog", None):
            return
        dlg = ViewsDialog(self, qs)
        self._views_dialog = dlg

        def done(_):
            self._views_dialog = None
            try:
                if dlg.apply():
                    self.retrain()
            except (autoclip.AutoClipError, ValueError) as e:
                QMessageBox.warning(self, "AutoClip", str(e))
            if self.clips.proj:
                self.clips.reload(self.clips.current_clip()["id"] if self.clips.current_clip() else None)
        dlg.finished.connect(done)
        dlg.show()

    # --- отчёт об ошибке ---
    def make_report(self):
        st = self.settings_page
        if not st.report_btn.isEnabled():
            return
        st.report_btn.setEnabled(False)
        st.report_state.setText("Собираю…")

        def work():
            try:
                path, err = diag.make_report(), None
            except Exception as e:
                path, err = None, f"❌ Отчёт не собрался: {e}"
            try:
                self.bus.report_done.emit(path, err)
            except RuntimeError:                     # окно уже закрыли
                pass
        threading.Thread(target=work, daemon=True).start()

    def report_ready(self, path, err):
        st = self.settings_page
        st.report_btn.setEnabled(True)
        if err:
            st.report_state.setText(err)
            return
        st.report_state.setText(f"Готово: {os.path.basename(path)} — на рабочем столе")
        self.last_report = path
        if ask_choice(self if self.isVisible() else None,
                      f"Отчёт собран: {os.path.basename(path)}\nОн на рабочем столе.",
                      (("show", "Показать в папке"), ("ok", "Готово"))) == "show":
            show_in_folder(path)

    # --- «Что нового» ---
    def news_after_update(self):
        seen = self.settings.get("seen_version") or ""
        if seen == update.VERSION or not self.isVisible():
            return
        self.settings["seen_version"] = update.VERSION
        save_settings(self.settings)
        fresh = update.news_since(seen)
        if seen and fresh:                       # первый запуск вообще — без окна
            self.show_news(fresh)

    def show_news(self, entries=None):
        if self._news:
            self._news.raise_()
            return
        self._news = NewsDialog(self, entries if entries is not None else update.changelog(),
                                only_new=entries is not None)
        self._news.finished.connect(lambda _: setattr(self, "_news", None))
        self._news.show()

    # --- обновления ---
    def check_updates(self, manual=False):
        skip = None if manual else self.settings.get("skip_version")

        def work():
            try:
                self.bus.update_found.emit(update.check(skip=skip), manual)
            except autoclip.AutoClipError as e:
                if manual:
                    self.bus.update_found.emit({"error": str(e)}, True)
        threading.Thread(target=work, daemon=True).start()

    def update_found(self, rel, manual):
        st = self.settings_page.update_state
        if rel and rel.get("error"):
            st.setText(rel["error"])
            return
        if not rel:
            st.setText(f"Стоит последняя версия — {update.VERSION}.")
            return
        st.setText(f"Есть версия {rel['version']}.")
        if self._update_dialog:
            return
        dlg = UpdateDialog(self, rel)
        self._update_dialog = dlg

        def done(_):
            self._update_dialog = None
            if dlg.action == "skip":
                self.settings["skip_version"] = rel["version"]
                save_settings(self.settings)
        dlg.finished.connect(done)
        dlg.show()

    def install_update(self, dlg):
        if self.busy:
            dlg.state.setText("Идёт нарезка — обновлю, когда она закончится. Нажми «Не сейчас».")
            dlg.later.setEnabled(True)
            return
        self.bus.update_progress.connect(
            lambda p: dlg.state.setText(f"Скачиваю… {p:.0%}"))

        def work():
            try:
                res = update.apply(dlg.rel, progress=self.bus.update_progress.emit)
                self.bus.update_done.emit(res, None)
            except autoclip.AutoClipError as e:
                self.bus.update_done.emit(None, str(e))
            except Exception as e:
                self.bus.update_done.emit(None, f"❌ Обновление не встало: {e}")
        threading.Thread(target=work, daemon=True).start()

    def update_installed(self, res, err):
        dlg = self._update_dialog
        if err:
            if dlg:
                dlg.state.setText(err)
                dlg.later.setEnabled(True)
            return
        if dlg:
            dlg.accept()
        if res["need_install"]:
            QMessageBox.information(self, "AutoClip", "Обновление встало. В новой версии новые "
                                    "библиотеки — сейчас откроется установка, потом запусти "
                                    "AutoClip снова.")
        update.restart(res["need_install"])
        self.quit_app()

    # --- слежка за папкой OBS ---
    def watch_changed(self):
        """Включить или выключить слежку по настройкам."""
        on = bool(self.settings.get("watch")) and os.path.isdir(self.settings.get("obs_dir", ""))
        if self.tray:
            self.tray.setVisible(bool(self.settings.get("watch")))
            self.tray_watch.blockSignals(True)
            self.tray_watch.setChecked(bool(self.settings.get("watch")))
            self.tray_watch.blockSignals(False)
        if self.fs_watch:
            self.fs_watch.deleteLater()
            self.fs_watch = None
        if on:
            from PySide6.QtCore import QFileSystemWatcher
            self.fs_watch = QFileSystemWatcher([self.settings["obs_dir"]], self)
            self.fs_watch.directoryChanged.connect(lambda _: self.scan_obs())
            self.watch_timer.start()
        else:
            self.watch_timer.stop()

    def scan_obs(self):
        """Новые записи в папке OBS: дописана ли, длинная ли, — и спросить «Нарезать?»."""
        s = self.settings
        if not (s.get("watch") and os.path.isdir(s.get("obs_dir", ""))):
            return
        for path in autoclip.new_recordings(s["obs_dir"], float(s.get("watch_since") or 0)):
            if path in self._asked or not self.tracker.update(path):
                continue
            info = autoclip.recording_info(path)
            if info is None:                          # ещё не читается — подождём
                continue
            self.tracker.forget(path)
            self._asked.add(path)
            if info["dur"] < int(s.get("min_minutes", 5)) * 60:
                autoclip.set_recording_state(path, "short")
                continue
            self.offer(path, info)

    def offer(self, path, info):
        """Уведомление Windows; сам вопрос — когда окно на экране (не поверх игры)."""
        self._pending.append((path, info))
        text = (f"{os.path.basename(path)}, {autoclip.fmt_time(info['dur'])}, "
                f"меток: {info['marks']}. Нарезать?")
        if self.tray:
            self.tray.showMessage("Новая запись", text, QSystemTrayIcon.Information, 15000)
        if self.isVisible() and self.isActiveWindow():
            self.ask_pending()

    def ask_pending(self):
        if self._dialog or not self._pending:
            return
        path, info = self._pending.pop(0)
        self._dialog = NewRecordingDialog(self, path, info)
        self._dialog.finished.connect(lambda r, p=path: self._answered(p, r))
        self._dialog.show()
        self._dialog.raise_()

    def _answered(self, path, result):
        self._dialog = None
        if result == QDialog.Accepted:
            autoclip.set_recording_state(path, "cut")
            self.cut_recording(path)
        else:
            autoclip.set_recording_state(path, "declined")
        QTimer.singleShot(0, self.ask_pending)

    def cut_recording(self, path):
        if self.busy:
            self._queue.append(path)
            self.cut.write(f"ℹ️  {os.path.basename(path)} нарежу после текущей записи.")
            return
        self.go("cut")
        self.cut.set_files([path])
        self.cut.start_or_stop()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(200, self.ask_pending)

    def changeEvent(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            QTimer.singleShot(200, self.ask_pending)
        super().changeEvent(e)

    def quit_app(self):
        self._quitting = True
        if not self.close():
            self._quitting = False

    def quit_from_tray(self):
        if self.settings.get("watch"):
            if ask_choice(self if self.isVisible() else None,
                          "Слежка за папкой OBS остановится. Выйти?",
                          (("quit", "Выйти"), ("cancel", "Отмена"))) != "quit":
                return
        self.quit_app()

    def _page(self, i):
        self.stack.setCurrentIndex(i)
        if self.PAGES[i][0] == "weekly":
            self.weekly.refresh()
        if self.PAGES[i][0] != "clips" and not self.detached:
            self.clips.player.player.pause()

    def go(self, key):
        self.nav.setCurrentRow([p[0] for p in self.PAGES].index(key))

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
        if self._queue:
            QTimer.singleShot(500, lambda: self.cut_recording(self._queue.pop(0)))

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
        if self.settings.get("watch") and self.tray and not self._quitting:
            # со слежкой — в трей, чтобы новые записи ловились и с закрытым окном
            e.ignore()
            self.hide()
            if not self.settings.get("tray_hint_shown"):
                self.tray.showMessage("AutoClip работает в трее",
                                      "Слежу за папкой OBS. Выход — правой кнопкой по значку.",
                                      QSystemTrayIcon.Information, 8000)
                self.settings["tray_hint_shown"] = True
                save_settings(self.settings)
            return
        if self.busy:
            r = QMessageBox.question(self, "AutoClip", "Нарезка ещё идёт. Остановить и закрыть?")
            if r != QMessageBox.Yes:
                e.ignore()
                return
            self.cancel.set()
        if self.clips.busy:
            # клип пересобирается — дождаться, иначе файл останется недоделанным
            self._close_after_rebuild = True
            e.ignore()
            return
        ans = self.clips.ask_edits()
        if ans != "discard":
            e.ignore()
            if ans == "apply":
                self._close_after_rebuild = True
                self.clips.rebuild()
                if not self.clips.busy:              # пересобрать не вышло (ошибка во времени)
                    self._close_after_rebuild = False
            return
        self._close_after_rebuild = False
        if self.detached:
            self.detached.close()
        self.clips.player.clear()
        self.settings["geometry"] = bytes(self.saveGeometry().toHex()).decode()
        save_settings(self.settings)
        if self.tray:
            self.tray.hide()
        super().closeEvent(e)
        if getattr(self, "standalone", False):
            QApplication.quit()                      # окно закрыли по-настоящему — выходим


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
    app.setStyleSheet(STYLE.replace("@ARROW@", arrow_icon()))


ICON = os.path.join(HERE, "icon", "autoclip.ico")


def main():
    autoclip.migrate_user_data()
    if os.name == "nt":
        # своя иконка на панели задач, а не значок Python
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FinalKFCBoss.AutoClip")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("AutoClip")
    if os.path.isfile(ICON):
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(ICON))
    dark_palette(app)
    # из трея программа выходит сама (окно может быть спрятано, а диалог — закрыться)
    app.setQuitOnLastWindowClosed(False)
    flog = diag.FileLog()
    win = MainWindow()
    win.bus.log.connect(flog.write)
    app.aboutToQuit.connect(flog.close)
    win.standalone = True
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
            diag.FileLog().write("❌ Программа упала:\n" + traceback.format_exc())
        except Exception:
            pass
        try:
            QMessageBox.critical(None, "AutoClip", msg)
        except Exception:
            pass
        raise
