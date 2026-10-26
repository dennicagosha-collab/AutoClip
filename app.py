# -*- coding: utf-8 -*-
"""AutoClip — окно на PySide6. Вся обработка — в autoclip.py, здесь только интерфейс."""

import datetime
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

import recover  # noqa: E402
recover.recover()                  # обновление прервали посередине — вернуть рабочую версию
os.environ["PATH"] = HERE + os.pathsep + os.environ.get("PATH", "")

import autoclip  # noqa: E402
import forecast  # noqa: E402
import update  # noqa: E402
import diag  # noqa: E402
import telegram_bot  # noqa: E402

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
    QAbstractButton, QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
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
    "sub_style": "Обычный", "sub_x": None, "sub_y_free": 0.6,
    "sub_font": "Arial Black", "sub_mode": "words", "sub_size": 82, "sub_color": "#FFFFFF",
    "sub_hl_color": "#FFE600", "sub_outline_color": "#000000", "sub_outline": 7,
    "subs": True, "zoom": "auto", "hook": "auto", "bleep": True,
    "sound": "перелистывание", "marks": True, "nick": False, "cam": "Вебка сверху",
    "sub_pos": autoclip.sub_position_name(autoclip.CONFIG["sub_y"]), "safe_zone": True,
    "nick_corner": autoclip.CONFIG["nick_corner"], "nick_size": "Средний",
    "nick_opacity": autoclip.CONFIG["nick_opacity"],
    "preset": autoclip.CONFIG["preset"], "llm": "auto", "ollama_model": autoclip.CONFIG["ollama_model"],
    "nick_text": "", "hashtags": "", "obs_dir": "", "recent": [],
    "platform_tags": dict(autoclip.CONFIG["platform_tags"]),
    "watch": False, "min_minutes": 5, "watch_since": 0.0, "tray_hint_shown": False,
    "views_days": 3, "check_updates": True, "skip_version": "", "seen_version": "",
    "geometry": "", "player_geometry": "",
    "weekly_days": 7, "weekly_format": "vertical", "weekly_dir": autoclip.WEEKLY_DIR,
    "music_dir": "", "weekly_music": "", "bleep_rel_db": 0, "subs_team": False,
    "censor": "partial", "clip_length": "normal", "bleep_pool": [],
    "backup_remind": True, "backup_since": "", "backup_told": "",
    "clips_dir": autoclip.CONFIG["clips_dir"], "cache_days": 30,
    "whisper_device": "auto", "whisper_model": autoclip.CONFIG["whisper_model"], "setup_done": False,
}

TRI_NAMES = {"Авто": "auto", "Вкл": "on", "Выкл": "off"}


def tri_combo(value, tip=""):
    cb = QComboBox()
    cb.setMinimumWidth(96)
    for name, key in TRI_NAMES.items():
        cb.addItem(name, key)
    cb.setCurrentIndex(max(0, cb.findData(autoclip.tri(value) or "auto")))
    if tip:
        cb.setToolTip(tip)
    return cb


LENGTH_NAMES = {"Короче": "short", "Обычно": "normal", "Длиннее": "long"}
CENSOR = {"Частичная (е*ать)": "partial", "Полная (б****)": "full"}


def censor_combo(value):
    cb = QComboBox()
    cb.setMinimumWidth(170)
    for name, key in CENSOR.items():
        cb.addItem(name, key)
    cb.setCurrentIndex(max(0, cb.findData(value)))
    return cb

import theme  # noqa: E402

BG, SURFACE, SURFACE2, BORDER = theme.BG, theme.SURFACE, theme.SURFACE2, theme.BORDER
FG, MUTED, ACCENT = theme.FG, theme.MUTED, theme.ACCENT
PANEL, PANEL2 = SURFACE, SURFACE2          # старые имена — для схемы субтитров и окна просмотра

STYLE = f"""
QWidget {{ font-family: "Inter", "Segoe UI Variable Text", "Segoe UI"; font-size: 13px; color: {FG}; }}
QMainWindow, #page, #scrollBody {{ background: {BG}; }}
QScrollArea {{ background: {BG}; border: none; }}
#side {{ background: {theme.SIDE}; border-right: 1px solid #1a1c23; }}
#brand {{ font-size: 20px; font-weight: 700; color: white; padding: 24px 24px 4px 24px; }}
#version {{ color: {theme.DIM}; font-size: 11px; text-align: left; padding: 0 0 16px 25px;
            border: none; background: transparent; min-height: 16px; }}
#version:hover {{ color: {FG}; background: transparent; }}
#nav {{ background: transparent; border: none; outline: none; padding: 0 12px; }}
#nav::item {{ padding: 11px 12px; border-radius: 10px; margin: 2px 0; color: {MUTED};
              border-left: 3px solid transparent; }}
#nav::item:selected {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2b1620, stop:1 #17181e);
                       color: white; border-left: 3px solid {ACCENT}; }}
#nav::item:hover:!selected {{ background: #15161c; color: {FG}; }}
#title {{ font-size: 26px; font-weight: 700; color: white; }}
#subtitle {{ color: {MUTED}; font-size: 13px; }}
#hint {{ color: {MUTED}; font-size: 12px; }}
#card {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #17181f, stop:1 #14151b);
         border: 1px solid {BORDER}; border-top-color: #2e313c; border-radius: 16px; }}
#panel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px; }}
#cardTitle {{ font-size: 15px; font-weight: 600; color: white; }}
#cardIcon {{ background: {theme.ACCENT_DEEP}; border-radius: 8px; }}
#rowLabel {{ color: {FG}; }}
#rowHint {{ color: {MUTED}; font-size: 12px; }}
#sep {{ background: {BORDER}; }}
#fieldLabel {{ color: {MUTED}; font-size: 12px; font-weight: 500; }}
#drop {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #17181f, stop:1 #131419);
         border: none; border-radius: 20px; }}
#drop[hover="true"] {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #241820, stop:1 #16161b); }}
#dropText {{ font-size: 17px; font-weight: 600; color: white; }}
#dropHint {{ color: {MUTED}; font-size: 13px; }}
QPushButton {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 10px;
              padding: 0 16px; min-height: 32px; font-weight: 500; }}
QPushButton:hover {{ background: {theme.SURFACE3}; border-color: {theme.BORDER_HI}; color: white; }}
QPushButton:pressed {{ background: #18191f; border-color: {BORDER}; padding-top: 2px; }}
QPushButton:disabled {{ color: {theme.DIM}; background: #15161b; border-color: #1f2128; }}
#accent {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff6680, stop:1 #e8344f);
          border: none; color: white; font-size: 16px; font-weight: 600;
          min-height: 48px; border-radius: 14px; padding: 0 28px; }}
#accent:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff7a91, stop:1 #f2405c); }}
#accent:pressed {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e8475f, stop:1 #c92a44);
                  padding-top: 2px; }}
#accent[busy="true"] {{ background: #2c1820; color: #ffb3c0; border: 1px solid #5a2433; }}
#primary {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff6680, stop:1 #e8344f);
           border: none; color: white; font-weight: 600; padding: 0 18px; }}
#primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff7a91, stop:1 #f2405c); }}
#primary:pressed {{ background: #c92a44; padding-top: 2px; }}
#primary:disabled {{ background: #2c1820; color: #8a5a66; }}
#ghost {{ background: transparent; border: none; color: {MUTED}; padding: 0 8px; }}
#ghost:hover {{ color: {FG}; background: {SURFACE2}; }}
#danger:hover {{ color: #ff8094; border-color: #5a2a35; background: #2a1a20; }}
#square {{ padding: 0; min-width: 32px; max-width: 32px; font-size: 15px; }}
#filter {{ background: transparent; border: 1px solid {BORDER}; border-radius: 15px;
          padding: 0 12px; min-height: 30px; color: {MUTED}; }}
#filter:hover {{ color: white; border-color: {theme.BORDER_HI}; background: #17181e; }}
#filter:checked {{ background: {theme.ACCENT_DEEP}; border-color: {ACCENT}; color: white; }}
#segBox {{ background: #121318; border: 1px solid {BORDER}; border-radius: 12px; }}
#seg {{ background: transparent; border: none; border-radius: 9px; padding: 0 14px; min-height: 30px;
       color: {MUTED}; font-weight: 500; }}
#seg:hover {{ color: white; background: #1b1c23; }}
#seg:checked {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff6680, stop:1 #e8344f);
               color: white; }}
#viewBtn {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 0;
           min-width: 32px; max-width: 32px; min-height: 30px; }}
#viewBtn:hover {{ background: {SURFACE2}; }}
#viewBtn:checked {{ background: {theme.ACCENT_DEEP}; border-color: #5a2433; }}
#stepValue {{ font-size: 16px; font-weight: 600; min-width: 34px; }}
QComboBox, QLineEdit, QSpinBox {{ background: #15161c; border: 1px solid {BORDER};
    border-radius: 10px; padding: 0 12px; min-height: 32px; }}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{ border-color: {theme.BORDER_HI}; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; background: #18141a; }}
QComboBox:disabled, QLineEdit:disabled {{ color: {theme.DIM}; background: #131419; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url(@ARROW@); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{ background: {SURFACE2}; border: 1px solid {BORDER};
    padding: 4px; outline: none; selection-background-color: #3a1e29; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QDoubleSpinBox {{ background: #15161c; border: 1px solid {BORDER}; border-radius: 10px; padding: 0 12px;
    min-height: 32px; }}
QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
#card QScrollArea, #card QScrollArea > QWidget > QWidget {{ background: transparent; }}
#card QStackedWidget {{ background: transparent; }}
QPlainTextEdit {{ background: #121318; border: 1px solid {BORDER}; border-radius: 14px;
    font-family: "Cascadia Mono", Consolas; font-size: 12px; padding: 12px; color: #b9bcc6; }}
#desc {{ font-family: "Inter", "Segoe UI"; font-size: 13px; color: {FG};
         background: #15161c; padding: 8px; }}
QProgressBar {{ background: #121318; border: 1px solid {BORDER}; border-radius: 11px;
               color: white; font-weight: 600; font-size: 12px; }}
QProgressBar::chunk {{ border-radius: 10px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #c92a44, stop:1 #ff6680); }}
#step {{ color: {MUTED}; font-size: 12px; padding: 4px 12px; border-radius: 12px;
        background: #15161c; border: 1px solid {BORDER}; }}
#step[state="active"] {{ color: white; border-color: {ACCENT}; background: {theme.ACCENT_DEEP}; }}
#step[state="done"] {{ color: #9fe3b4; border-color: #2c4a37; background: #14211a; }}
#stepTotal {{ color: {FG}; font-size: 12px; font-weight: 600; }}
#clipList {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px;
    outline: none; padding: 8px; }}
#clipList::item {{ padding: 8px 10px; border-radius: 10px; margin: 1px 0; }}
#clipList::item:selected {{ background: #2a1a22; color: white; }}
#clipList::item:hover:!selected {{ background: #1c1d24; }}
#cardList {{ background: transparent; border: none; outline: none; }}
QSlider::groove:horizontal {{ height: 4px; background: #2e313c; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; margin: -5px 0; border-radius: 7px; }}
QSplitter::handle {{ background: {BG}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2a2d37; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a3e4a; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2a2d37; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{ background: {SURFACE2}; color: {FG}; border: 1px solid {theme.BORDER_HI}; padding: 6px;
           border-radius: 6px; }}
QToolButton#more {{ background: transparent; border: none; color: {MUTED}; padding: 4px 6px;
                   border-radius: 8px; }}
QToolButton#more:hover, QToolButton#more:checked {{ color: white; background: #17181e; }}
QPushButton:checked {{ background: {theme.ACCENT_DEEP}; border-color: {ACCENT}; color: white; }}
#toast {{ background: #1f2129; color: {FG}; border: 1px solid {theme.BORDER_HI};
          border-left: 3px solid {ACCENT}; border-radius: 12px; padding: 12px 18px; }}
#scissors {{ background: transparent; }}
#plane {{ color: #7ec8ff; font-size: 17px; background: transparent; }}
#feedBody {{ background: transparent; }}
#feedRow {{ background: transparent; border-radius: 12px; border-left: 3px solid transparent; }}
#feedRow:hover {{ background: #1a1b22; }}
#feedRow[fresh="true"] {{ background: #22161c; border-left: 3px solid {ACCENT}; }}
#feedText {{ color: {FG}; font-size: 13px; }}
#feedTime {{ color: {theme.DIM}; font-size: 11px; padding-top: 2px; }}
#pill {{ border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600; }}
#playerBox {{ background: #08090b; border: 1px solid {BORDER}; border-radius: 16px; }}
QMenu {{ background: {SURFACE2}; border: 1px solid {theme.BORDER_HI}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {theme.ACCENT_DEEP}; color: white; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {theme.BORDER_HI};
                       background: #15161c; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
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
        autoclip.write_json(autoclip.SETTINGS_PATH, data)           # атомарно (P3)
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
    rebuild_progress = Signal(float)       # пересборка клипа, проценты
    send_state = Signal(str)               # отправка клипа в Telegram: что сейчас происходит
    weekly_progress = Signal(float, str)
    weekly_done = Signal(str, object)      # путь к подборке, текст ошибки или None
    trained = Signal(object)               # итог обучения прогноза
    update_found = Signal(object, bool)    # релиз или None, проверка вручную?
    update_progress = Signal(float)
    update_done = Signal(object, object)   # итог установки, текст ошибки или None
    report_done = Signal(object, object)   # путь к отчёту об ошибке, текст ошибки или None
    sub_layer = Signal(int, str)           # номер запроса, картинка субтитров для предпросмотра
    tg_action = Signal(str, object)        # действие из Telegram: cut / no / views
    music_ready = Signal(str, object)      # «Прослушать с клипом»: файл или текст ошибки
    tg_state = Signal(str)                 # что с подключением Telegram (текст для «Настроек»)


class Stream:
    """Перехват print и ошибок библиотек в лог (у pythonw нет консоли)."""
    def __init__(self, bus):
        self.bus = bus

    def write(self, s):
        if s.strip():
            self.bus.log.emit(s.rstrip())

    def flush(self):
        pass


CONTENT_MAX = 1440      # на широком мониторе содержимое раздела — по центру, не шире этого (2.3.0)


def center_content(widget, lay, side=32):
    """Поля раздела растут на широком окне, чтобы содержимое было по центру."""
    extra = max(0, (widget.width() - 2 * side - CONTENT_MAX) // 2)
    m = lay.contentsMargins()
    if m.left() != side + extra:
        lay.setContentsMargins(side + extra, m.top(), side + extra, m.bottom())


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


SUB_MODES = {"words": "По 2–3 слова", "single": "По одному слову"}
CUSTOM_POS = "Своё место"     # субтитры перетащили мышкой в предпросмотре


def sub_settings(s):
    """Субтитры из «Настроек» → ключи CONFIG: стиль, высота и место по ширине."""
    out = {k: s.get(k, DEFAULTS[k]) for k in autoclip.STYLE_KEYS}
    out["sub_size"] = int(out["sub_size"])
    out["sub_outline"] = int(out["sub_outline"])
    out["sub_style"] = s.get("sub_style", "Обычный")
    if s.get("sub_pos") in autoclip.SUB_POSITIONS:
        out.update(sub_y=autoclip.SUB_POSITIONS[s["sub_pos"]], sub_x=None)
    else:
        out.update(sub_y=float(s.get("sub_y_free", 0.6)), sub_x=s.get("sub_x"))
    return out


def latest_cover():
    """Кадр для предпросмотра субтитров: обложка последнего клипа (без субтитров)."""
    for pp in reversed(autoclip.known_projects()):
        try:
            with open(pp, encoding="utf-8") as f:
                clips = json.load(f).get("clips", [])
        except (OSError, ValueError):
            continue
        for c in reversed(clips):
            cv = (c.get("cover") or {}).get("file")
            path = autoclip.cover_path_for(autoclip.cut_root({"_path": pp}), c["file"]) if cv else ""
            if cv and os.path.isfile(path):
                return path
    return None


class ColorButton(QPushButton):
    """Кнопка-образец цвета: по клику — выбор цвета."""
    changed = Signal(str)

    def __init__(self, color, tip=""):
        super().__init__()
        self.setFixedSize(44, 30)
        self.setToolTip(tip)
        self.set_color(color)
        self.clicked.connect(self.pick)

    def set_color(self, color):
        self.color = QColor(color).name().upper()
        self.setStyleSheet(f"background: {self.color}; border: 2px solid #3a3d48; border-radius: 8px;")

    def pick(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(self.color), self, "Цвет")
        if c.isValid():
            self.set_color(c.name())
            self.changed.emit(self.color)


class LivePreview(QWidget):
    """Кадр клипа с субтитрами — их рисует тот же libass, что и в клипе. Строку можно
    перетащить мышкой; сейф-зона — рамкой, за неё строку не вытащить."""
    moved = Signal(float, float)      # новый центр строки: доли ширины и высоты кадра

    W, H = 1080, 1920

    def __init__(self):
        super().__init__()
        self.setFixedSize(243, 432)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Перетащи субтитры мышкой")
        self.frame = None
        self.layer = None
        self.cfg = dict(autoclip.CONFIG)
        self.drag = None              # (точка нажатия, смещение)
        self.offset = (0.0, 0.0)

    def set_frame(self, path):
        pm = QPixmap(path) if path else QPixmap()
        self.frame = None if pm.isNull() else pm
        self.update()

    def set_layer(self, path, cfg):
        img = QPixmap(path) if path else QPixmap()
        self.layer = None if img.isNull() else img
        self.cfg = cfg
        self.offset = (0.0, 0.0)
        self.update()

    def _k(self):
        return self.width() / self.W

    def center(self):
        lay = autoclip.subs_layout(self.W, self.H, self.cfg)
        return lay["x"], lay["y"], lay

    def _clamped(self, dx, dy):
        x, y, lay = self.center()
        left, top, right, bottom = lay["box"]
        half, fs = 0.6 * lay["fs"], lay["fs"]
        nx = min(max(x + dx, left + 2 * fs), right - 2 * fs) if right - left > 4 * fs else x
        ny = min(max(y + dy, top + half), bottom - half)
        return nx - x, ny - y

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        if self.frame:
            p.drawPixmap(self.rect(), self.frame)
        else:
            from PySide6.QtGui import QLinearGradient
            g = QLinearGradient(0, 0, 0, h)
            g.setColorAt(0, QColor("#2b2f3a"))
            g.setColorAt(1, QColor("#14161c"))
            p.fillRect(self.rect(), g)
        if self.cfg.get("safe_zone"):
            z = autoclip.SAFE_ZONE
            pen = QPen(QColor(255, 79, 109, 220), 1, Qt.DashLine)
            p.setPen(pen)
            p.drawRect(QRectF(z["left"] * w, z["top"] * h, w * (1 - z["left"] - z["right"]) - 1,
                              h * (1 - z["top"] - z["bottom"]) - 1))
        if self.layer and self.cfg.get("subs", True):
            k = self._k()
            dx, dy = self.offset
            p.drawPixmap(QRectF(dx * k, dy * k, w, h), self.layer, QRectF(self.layer.rect()))
        p.setPen(QColor("#3a3d48"))
        p.drawRect(0, 0, w - 1, h - 1)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.layer:
            self.drag = (e.position(), self.offset)
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self.drag:
            start, (ox, oy) = self.drag
            k = self._k()
            d = e.position() - start
            self.offset = self._clamped(ox + d.x() / k, oy + d.y() / k)
            self.update()

    def mouseReleaseEvent(self, e):
        if self.drag:
            self.drag = None
            self.setCursor(Qt.OpenHandCursor)
            if self.offset != (0.0, 0.0):
                x, y, _ = self.center()
                self.moved.emit((x + self.offset[0]) / self.W, (y + self.offset[1]) / self.H)


class TelegramLink:
    """Связь с ботом в фоне: забирает ответы (long polling) и отправляет уведомления.
    Всё общение с Telegram — в этом потоке, по очереди, чтобы не мешать окну."""

    alive = []                                        # все потоки связи (тесты гасят их после себя)

    def __init__(self, bus):
        import queue
        TelegramLink.alive.append(self)
        self.bus = bus
        self.jobs = queue.Queue()
        self.stop = threading.Event()
        self._warned = False
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def do(self, job):
        """job(bot) — выполнить в потоке связи, если Telegram подключён."""
        if telegram_bot.is_connected():
            self.jobs.put(job)

    def _log(self, text):
        if not self._warned:                         # нет связи — в лог один раз
            self._warned = True
            try:
                self.bus.log.emit(text)
            except RuntimeError:
                pass

    def loop(self):
        bot = None
        while not self.stop.is_set():
            st = telegram_bot.load_state()
            if not (st.get("token") and st.get("chat_id")):
                bot = None
                self.stop.wait(2)
                continue
            if bot is None or (st["token"], st["chat_id"]) != (bot.st.get("token"), bot.st.get("chat_id")):
                bot = telegram_bot.Bot(log=self._log)    # подключили заново — новый бот
            while not self.jobs.empty():
                job = self.jobs.get()
                try:
                    job(bot)
                except Exception as e:
                    self._log(f"⚠️  Telegram: {e} Работаю без него.")
            try:
                actions = bot.poll(timeout=2)       # коротко: отправка клипа не ждёт долго своей очереди
            except OSError as e:                     # например, файл состояния занят — не падаем
                self._log(f"⚠️  Telegram: {e}")
                self.stop.wait(1)
                continue
            if actions:
                self._warned = False
            for kind, arg in actions:
                try:
                    self.bus.tg_action.emit(kind, arg)
                except RuntimeError:
                    return
            if bot._offline_since is not None:
                self.stop.wait(10)                   # нет связи — не долбим Telegram


def fit_on_screen(w, margin=8):
    """Окно — целиком на мониторе, который сейчас есть. Был на отключённом (или вылез за край) —
    переезжает на основной монитор и при необходимости уменьшается."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QGuiApplication
    screens = QGuiApplication.screens()
    if not screens:
        return False
    g = w.normalGeometry() if w.isMaximized() else w.geometry()
    if not g.isValid():
        return False

    def overlap(sc):
        r = sc.availableGeometry().intersected(g)
        return max(0, r.width()) * max(0, r.height())
    best = max(screens, key=overlap)
    if overlap(best) < 0.5 * g.width() * g.height():     # почти всё окно вне мониторов
        best = QGuiApplication.primaryScreen() or screens[0]
    area = best.availableGeometry().adjusted(margin, margin, -margin, -margin)
    if w.minimumWidth() > area.width() or w.minimumHeight() > area.height():
        # маленький экран — окно может стать меньше обычного минимума
        w.setMinimumSize(min(w.minimumWidth(), area.width()), min(w.minimumHeight(), area.height()))
    width = min(g.width(), area.width())
    height = min(g.height(), area.height())
    x = min(max(g.x(), area.left()), area.right() - width + 1)
    y = min(max(g.y(), area.top()), area.bottom() - height + 1)
    new = QRect(x, y, width, height)
    if new == g:
        return False
    if w.isMaximized():
        w.showNormal()
        w.setGeometry(new)
        w.showMaximized()                             # развёрнутым — уже на видимом мониторе
    else:
        w.setGeometry(new)
    return True


MUSIC_HINT = ("Для TikTok лучше добавить звук в самом TikTok. Сюда — только свои треки или "
              "свободные: YouTube Audio Library, Pixabay Music.")


class WaveView(QWidget):
    """Волна трека и рамка длиной с клип: двигаешь рамку — выбираешь кусок трека."""
    moved = Signal(float)             # начало куска, секунды трека

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(70)
        self.setCursor(Qt.SizeHorCursor)
        self.peaks, self.dur, self.length, self.offset = [], 0.0, 0.0, 0.0
        self._drag = None

    def set_track(self, peaks, dur):
        self.peaks, self.dur = list(peaks), float(dur)
        self.update()

    def set_window(self, length, offset):
        self.length = float(length)
        self.offset = self._clamp(offset)
        self.update()

    def _clamp(self, off):
        return max(0.0, min(float(off), max(0.0, self.dur - self.length)))

    def paintEvent(self, e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#0d0e11"))
        if self.peaks and self.dur:
            n = len(self.peaks)
            bw = w / n
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#5c606b"))
            for i, v in enumerate(self.peaks):
                bh = max(1.0, v * (h - 8))
                p.drawRect(QRectF(i * bw, (h - bh) / 2, max(1.0, bw - 0.5), bh))
            x0 = self.offset / self.dur * w
            x1 = min(w, (self.offset + self.length) / self.dur * w)
            c = QColor(ACCENT)
            c.setAlpha(70)
            p.setBrush(c)
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawRoundedRect(QRectF(x0, 1, max(4.0, x1 - x0), h - 2), 4, 4)
        else:
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "Выбери трек")
        p.end()

    def mousePressEvent(self, e):
        if self.dur:
            self._drag = (e.position().x(), self.offset)

    def mouseMoveEvent(self, e):
        if self._drag and self.dur:
            x, off = self._drag
            self.offset = self._clamp(off + (e.position().x() - x) / self.width() * self.dur)
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = None
            self.moved.emit(round(self.offset, 2))


# сколько времени обычно занимает этап нарезки (доли): так полоса идёт ровнее, чем «поровну»
STAGE_WEIGHTS = {"звук": 0.05, "расшифровка": 0.35, "модель": 0.2, "поиск": 0.05, "рендер": 0.35}


_ANIM = {"t": 0.0, "ok": True}


def animations_ok(widget=None):
    """Анимации не грузят ПК: окно скрыто, свернуто, в трее или идёт игра на весь экран — без них."""
    import time as _time
    w = widget.window() if widget is not None else None
    if w is not None and (not w.isVisible() or w.isMinimized()):
        return False
    now = _time.time()
    if now - _ANIM["t"] > 10:                      # игру проверяем не чаще раза в 10 с
        _ANIM["t"] = now
        try:
            _ANIM["ok"] = not autoclip.fullscreen_app()
        except Exception:
            _ANIM["ok"] = True
    return _ANIM["ok"]


def fade_in(widget, ms=160):
    """Плавное появление (переход разделов, список клипов)."""
    if widget is None or not animations_ok(widget):
        return
    from PySide6.QtCore import QPropertyAnimation
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"opacity", widget)
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start()
    widget._fade = anim


class GlowButton(QObject):
    """Красное свечение под главной кнопкой; при наведении — ярче (150–250 мс), при нажатии — тише."""

    def __init__(self, button, radius=22, alpha=90):
        super().__init__(button)
        self.btn = button
        self.base = (radius, alpha)
        self.eff = theme.glow(button, radius=radius, alpha=alpha)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(200)
        self.anim.valueChanged.connect(self._apply)
        button.installEventFilter(self)

    def _apply(self, v):
        r, a = self.base
        self.eff.setBlurRadius(r + 14 * v)
        c = QColor(ACCENT)
        c.setAlpha(int(min(255, a + 80 * v)))
        self.eff.setColor(c)

    def _to(self, v):
        if not animations_ok(self.btn):
            self._apply(v)
            return
        self.anim.stop()
        self.anim.setStartValue(self.anim.currentValue() if self.anim.currentValue() is not None else 0.0)
        self.anim.setEndValue(float(v))
        self.anim.start()

    def eventFilter(self, obj, e):
        t = e.type()
        if t == e.Type.Enter and self.btn.isEnabled():
            self._to(1.0)
        elif t == e.Type.Leave:
            self._to(0.0)
        elif t == e.Type.MouseButtonPress:
            self._to(-0.4)
        elif t == e.Type.MouseButtonRelease:
            self._to(1.0 if self.btn.underMouse() else 0.0)
        elif t == e.Type.EnabledChange:
            self.eff.setEnabled(self.btn.isEnabled())
        return False


def glow_button(button, radius=22, alpha=90):
    button._glow = GlowButton(button, radius, alpha)
    return button


class CenterNotice(QWidget):
    """Крупное сообщение по центру окна (2.3.1): «Отправляю в Telegram…» с крутящимся кольцом,
    «Отправлено» — самолётик улетает, на его месте галочка; «Не отправилось» — красным. Само гаснет."""
    COLORS = {"busy": "#2aabee", "ok": "#2aabee", "error": "#ff6b84"}

    def __init__(self, parent):
        # своё прозрачное окошко поверх окна программы: видео в окне — отдельное «окно» и закрыло бы
        # обычный виджет; фокус не забирает, мышь пропускает
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.resize(440, 200)
        self.kind, self.title, self.sub = "ok", "", ""
        self.t = 1.0                     # 0..1 — самолётик улетает
        self.spin = 0.0
        self.hide()
        self.fly = QVariantAnimation(self)
        self.fly.setDuration(900)
        self.fly.setStartValue(0.0)
        self.fly.setEndValue(1.0)
        self.fly.valueChanged.connect(self._set_t)
        self.fade = QVariantAnimation(self)
        self.fade.setDuration(220)
        self.fade.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))
        self.fade.finished.connect(self._faded)
        self.spinner = QTimer(self)
        self.spinner.setInterval(30)
        self.spinner.timeout.connect(self._spin)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.dismiss)

    def _set_t(self, v):
        self.t = float(v)
        self.update()

    def _spin(self):
        self.spin = (self.spin + 9) % 360
        self.update()

    def show_notice(self, kind, title, sub="", ms=2600):
        was = self.isVisible() and self.windowOpacity() > 0.5
        self.kind, self.title, self.sub = kind, title, sub
        p = self.parent()
        c = p.mapToGlobal(p.rect().center())
        self.move(c.x() - self.width() // 2, c.y() - self.height() // 2)
        self.show()
        self.raise_()
        anim = animations_ok(self)
        self.fade.stop()
        if anim and not was:
            self.fade.setStartValue(0.0)
            self.fade.setEndValue(1.0)
            self.fade.start()
        else:
            self.setWindowOpacity(1.0)
        if kind == "busy":
            self.t = 0.0
            if anim:
                self.spinner.start()
        else:
            self.spinner.stop()
            if kind == "ok" and anim:
                self.fly.stop()
                self.fly.start()
            else:
                self.t = 1.0
        self.hide_timer.start(ms if kind != "busy" else 120000)
        self.update()

    def dismiss(self):
        self.spinner.stop()
        if not self.isVisible():
            return
        if animations_ok(self):
            self.fade.stop()
            self.fade.setStartValue(self.windowOpacity())
            self.fade.setEndValue(0.0)
            self.fade.start()
        else:
            self.hide()

    def _faded(self):
        if self.windowOpacity() < 0.05:
            self.hide()

    def paintEvent(self, e):
        from PySide6.QtGui import QFontMetrics
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        for k in range(10, 0, -2):                     # мягкая тень
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 14))
            p.drawRoundedRect(r.adjusted(-k, -k + 6, k, k + 6), 22 + k, 22 + k)
        p.setBrush(QColor("#1b1c23"))
        p.setPen(QPen(QColor("#33364a"), 1))
        p.drawRoundedRect(r, 22, 22)
        color = QColor(self.COLORS.get(self.kind, ACCENT))
        cx, cy, rad = r.center().x(), r.top() + 54, 30
        glow = QColor(color)
        glow.setAlpha(40)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), rad + 8, rad + 8)
        p.setBrush(QColor(color.red(), color.green(), color.blue(), 70))
        p.drawEllipse(QPointF(cx, cy), rad, rad)
        if self.kind == "busy":                        # крутится кольцо
            pen = QPen(color, 3)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(cx - rad - 8, cy - rad - 8, 2 * rad + 16, 2 * rad + 16),
                      int(-self.spin * 16), 100 * 16)
        if self.kind == "error":
            p.drawPixmap(int(cx - 14), int(cy - 14), theme.pixmap("x", "#ffffff", 28))
        else:
            fly = self.t if self.kind == "ok" else 0.0
            if fly < 1.0:                              # самолётик улетает вверх-вправо и тает
                p.setOpacity(1.0 - fly)
                p.drawPixmap(int(cx - 13 + 70 * fly), int(cy - 13 - 46 * fly), theme.pixmap("send", "#ffffff", 26))
                p.setOpacity(1.0)
            if self.kind == "ok" and fly > 0.45:      # на его месте — галочка
                p.setOpacity(min(1.0, (fly - 0.45) / 0.4))
                p.drawPixmap(int(cx - 14), int(cy - 14), theme.pixmap("check", "#ffffff", 28))
                p.setOpacity(1.0)
        f = QFont(theme.FAMILY or "Segoe UI")
        f.setPixelSize(18)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(r.left() + 16, cy + rad + 14, r.width() - 32, 26), Qt.AlignCenter, self.title)
        if self.sub:
            f2 = QFont(f)
            f2.setPixelSize(13)
            f2.setWeight(QFont.Normal)
            p.setFont(f2)
            p.setPen(QColor(MUTED))
            sub = QFontMetrics(f2).elidedText(self.sub, Qt.ElideMiddle, int(r.width() - 40))
            p.drawText(QRectF(r.left() + 16, cy + rad + 42, r.width() - 32, 20), Qt.AlignCenter, sub)
        p.end()


class Toast(QLabel):
    """Короткое сообщение внизу окна вместо всплывающего окна — само исчезает."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setWordWrap(True)
        self.hide()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def show_text(self, text, ms=4000):
        self.setText(text)
        self.setMaximumWidth(min(560, max(240, self.parent().width() - 80)))
        self.adjustSize()
        p = self.parent()
        self.move((p.width() - self.width()) // 2, p.height() - self.height() - 28)
        self.raise_()
        self.show()
        fade_in(self, 180)
        self.timer.start(ms)


def in_game():
    """Игра (или любая программа) на весь экран — никаких всплывающих окон (P3)."""
    try:
        return autoclip.fullscreen_app() is not None
    except Exception:
        return False


def stage_name(st):
    return st[:1].upper() + st[1:]


def stage_fraction(stage, pct):
    """Общая доля нарезки по этапу и проценту внутри этапа."""
    stages = list(autoclip.STAGES)
    w = [STAGE_WEIGHTS.get(st, 1 / len(stages)) for st in stages]
    total = sum(w)
    i = stages.index(stage)
    return min(1.0, (sum(w[:i]) + w[i] * max(0.0, min(100.0, pct)) / 100) / total)


UPDATE_EVERY_MS = 6 * 3600 * 1000


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


def text_width(text, px=13, weight=None):
    """Ширина текста шрифтом программы — чтобы подписи не обрезались (2.3.0)."""
    from PySide6.QtGui import QFontMetrics
    f = QFont(theme.FAMILY or "Segoe UI")
    f.setPixelSize(px)
    if weight is not None:
        f.setWeight(weight)
    return QFontMetrics(f).horizontalAdvance(text)


def hint(text):
    h = QLabel(text)
    h.setObjectName("hint")
    h.setWordWrap(True)
    return h


CARD_ICONS = {"OBS": "video", "Telegram": "send", "Запуск": "rocket", "Музыка": "music",
              "Ник в углу": "user", "Новые клипы": "sparkles", "Обновления": "download",
              "Отчёт об ошибке": "bug", "Папка для клипов": "folder", "Пресеты экспорта": "film",
              "Прогноз": "chart-column", "Резервная копия": "hard-drive", "Сборка клипов": "layers",
              "Состояние системы": "activity", "Субтитры": "captions", "Хэштеги и описание": "hash",
              "Языковая модель": "bot", "Нарезка": "scissors"}


def icon_label(name, color=ACCENT, size=18, box=32):
    """Значок раздела в красном квадратике."""
    lb = QLabel()
    lb.setObjectName("cardIcon")
    lb.setFixedSize(box, box)
    lb.setAlignment(Qt.AlignCenter)
    lb.setPixmap(theme.pixmap(name, color, size))
    return lb


def card(title=None, sub=None, icon=None):
    """Карточка: (рамка, раскладка содержимого). У заголовка — значок раздела (2.3.0)."""
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(4)
    if title:
        t = QLabel(title)
        t.setObjectName("cardTitle")
        name = icon or CARD_ICONS.get(title)
        if name and theme.has_icon(name):
            head = QHBoxLayout()
            head.setSpacing(12)
            head.addWidget(icon_label(name))
            head.addWidget(t, 1)
            lay.addLayout(head)
        else:
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

    def __init__(self, lo, hi, value, step=1):
        super().__init__()
        self.lo, self.hi, self.step = lo, hi, step
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
        self.minus.clicked.connect(lambda: self.setValue(self._v - self.step))
        self.plus.clicked.connect(lambda: self.setValue(self._v + self.step))
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
    """Кнопка-значок «прослушать звук на мат»."""

    def __init__(self, combo):
        super().__init__()
        self.setObjectName("square")
        theme.set_icon(self, "volume-2", FG, 16)
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
    names = autoclip.list_sounds() + [autoclip.RANDOM_SOUND]
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

        self.btn_play = QPushButton()
        self.btn_play.setObjectName("primary")
        self.btn_play.setFixedSize(44, 36)
        theme.set_icon(self.btn_play, "play", "#ffffff", 18)
        self.btn_play.clicked.connect(self.toggle)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.time = QLabel("0:00 / 0:00")
        self.time.setObjectName("hint")
        self.btn_detach = QPushButton("Открепить")
        theme.set_icon(self.btn_detach, "external-link", FG, 15)
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
        if not autoplay:
            self._stop_at = None
        self._first_frame = not autoplay
        self._may_play = autoplay
        self._seek = int(at_ms)
        self._pending_seek = int(at_ms) or None
        self.audio.setMuted(not autoplay)    # пока показываем первый кадр — без звука
        self.player.setSource(QUrl.fromLocalFile(path))
        if autoplay:
            self.play()

    def play_range(self, path, a_ms, b_ms):
        """Сыграть кусок файла от a до b и встать на паузу."""
        self._stop_at = int(b_ms)
        if self.player.source() == QUrl.fromLocalFile(path) and \
                self.player.mediaStatus() not in (QMediaPlayer.NoMedia, QMediaPlayer.InvalidMedia,
                                                  QMediaPlayer.LoadingMedia):
            self.player.setPosition(int(a_ms))
            self.play()
        else:
            self.open(path, autoplay=True, at_ms=a_ms)

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
        stop = getattr(self, "_stop_at", None)
        if stop is not None and ms >= stop:
            self._stop_at = None
            self._may_play = False
            self.player.pause()
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
        theme.set_icon(self.btn_play, "pause" if st == QMediaPlayer.PlayingState else "play", "#ffffff", 18)


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
        self.setMinimumHeight(200)
        self._dash = 0.0                              # сдвиг пунктира — рамка медленно «бежит» (2.3.0)
        self._dash_timer = QTimer(self)
        self._dash_timer.setInterval(50)
        self._dash_timer.timeout.connect(self._tick)   # идёт, только пока рамку видно
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(24)
        self.pic = QLabel()
        self.pic.setFixedSize(0, 0)
        lay.addWidget(self.pic)
        col = QVBoxLayout()
        col.setSpacing(6)
        col.addStretch(1)
        self.up_icon = QLabel()
        self.up_icon.setPixmap(theme.pixmap("upload", ACCENT, 34))
        self.up_icon.setAlignment(Qt.AlignCenter)
        col.addWidget(self.up_icon)
        col.addSpacing(6)
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
        self.up_icon.setVisible(on)

    def showEvent(self, e):
        super().showEvent(e)
        self._dash_timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._dash_timer.stop()

    def _tick(self):
        if not self.isVisible() or not animations_ok(self):
            return
        self._dash = (self._dash + (0.9 if self.property("hover") else 0.35)) % 16
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hover = bool(self.property("hover"))
        pen = QPen(QColor(ACCENT if hover else "#3a3e4a"), 2)
        pen.setDashPattern([5, 3])
        pen.setDashOffset(-self._dash)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 20, 20)
        p.end()

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


class StageBar(QWidget):
    """Полоса нарезки (2.3.1): внутри — текущий этап («Расшифровка») и его процент от 0 до 100,
    сбоку — «этап 2 из 5». По заполненной части бежит блик, пока идёт работа."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(52)
        self.setMinimumWidth(320)
        self.name, self.pct, self.index, self.count = "", 0.0, 0, len(autoclip.STAGES)
        self.target = 0.0                         # куда идёт полоса; pct — что сейчас нарисовано (плавно догоняет)
        self.state = "idle"                       # idle / busy / done
        self.text = "Готов к нарезке"
        self.shine = 0.0
        self.snip = 0                             # ножницы «щёлкают»
        self.scissors = QLabel(self)              # крупные ножницы в красном кружке — на краю полосы
        self.scissors.setObjectName("scissors")
        self.scissors.setFixedSize(34, 34)
        self.scissors.setAlignment(Qt.AlignCenter)
        self.scissors.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.scissors.setStyleSheet(f"background: {ACCENT}; border-radius: 17px; border: 2px solid #ffffff;")
        self._snips = [self._snip_pm(a) for a in (0, -14)]
        self.scissors.setPixmap(self._snips[0])
        self.scissors.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    @staticmethod
    def _snip_pm(angle):
        from PySide6.QtGui import QTransform
        pm = theme.pixmap("scissors", "#ffffff", 20, stroke=2.4)
        if angle:
            pm = pm.transformed(QTransform().rotate(angle), Qt.SmoothTransformation)
            pm.setDevicePixelRatio(2)
        return pm

    def set_stage(self, name, pct, index, count):
        pct = max(0.0, min(100.0, float(pct)))
        if index != self.index or self.state != "busy":
            self.pct = 0.0                         # новый этап — полоса с нуля
        self.name, self.target, self.index, self.count = name, pct, index, count
        self.state = "busy"
        if not animations_ok(self):
            self.pct = pct                         # без анимаций — сразу
        if not self._timer.isActive():
            self._timer.start()
        self._place_scissors()
        self.update()

    def set_idle(self, text="Готов к нарезке"):
        self.state, self.text, self.pct, self.target = "idle", text, 0.0, 0.0
        self._timer.stop()
        self.scissors.hide()
        self.update()

    def set_done(self, text="Готово"):
        self.state, self.text, self.pct, self.target = "done", text, 100.0, 100.0
        self._timer.stop()
        self.scissors.hide()
        self.update()

    def fraction(self):
        return self.pct / 100.0

    def _place_scissors(self):
        if self.state != "busy" or not animations_ok(self):
            self.scissors.hide()
            return
        r = self.rect().adjusted(1, 1, -1, -1)
        fw = max(28.0, r.width() * self.pct / 100)
        x = int(r.left() + fw - self.scissors.width() / 2)
        x = max(0, min(self.width() - self.scissors.width(), x))
        self.scissors.move(x, (self.height() - self.scissors.height()) // 2)
        self.scissors.show()
        self.scissors.raise_()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        if self.state == "busy":
            self._timer.start()

    def _tick(self):
        if not animations_ok(self):
            self.pct = self.target
            self.scissors.hide()
            return
        gap = self.target - self.pct              # полоса плавно догоняет, без рывков
        self.pct = self.target if abs(gap) < 0.05 else self.pct + gap * 0.18
        self.shine = (self.shine + 0.012) % 1.0
        self.snip = (self.snip + 1) % 16
        if self.snip in (0, 8):
            self.scissors.setPixmap(self._snips[self.snip // 8])
        self._place_scissors()
        self.update()

    def paintEvent(self, e):
        from PySide6.QtGui import QLinearGradient, QFontMetrics
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(BORDER), 1))
        p.setBrush(QColor("#111217"))
        p.drawRoundedRect(r, 14, 14)
        if self.pct > 0:
            fw = max(28.0, r.width() * self.pct / 100)
            fill = QRectF(r.left(), r.top(), fw, r.height())
            g = QLinearGradient(fill.left(), 0, fill.right(), 0)
            if self.state == "done":
                g.setColorAt(0, QColor("#1f7a4a"))
                g.setColorAt(1, QColor("#36c47a"))
            else:
                g.setColorAt(0, QColor("#a8223c"))
                g.setColorAt(1, QColor("#ff6680"))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(fill, 14, 14)
            if self.state == "busy":                   # блик бежит по заполненной части
                x = fill.left() + (fill.width() + 120) * self.shine - 60
                sh = QLinearGradient(x - 60, 0, x + 60, 0)
                sh.setColorAt(0, QColor(255, 255, 255, 0))
                sh.setColorAt(0.5, QColor(255, 255, 255, 46))
                sh.setColorAt(1, QColor(255, 255, 255, 0))
                p.save()
                p.setClipPath(_rounded(fill, 14))
                p.fillRect(fill, sh)
                p.restore()
        f = QFont(theme.FAMILY or "Segoe UI")
        f.setPixelSize(15)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        tr = r.adjusted(18, 0, -18, 0)
        if self.state == "busy":
            p.drawText(tr, Qt.AlignVCenter | Qt.AlignLeft, self.name)
            p.drawText(tr.adjusted(0, 0, -30 if self.pct > 93 else 0, 0), Qt.AlignVCenter | Qt.AlignRight,
                       f"{self.target:.0f}%")
            nw = QFontMetrics(f).horizontalAdvance(self.name)
            f2 = QFont(f)
            f2.setPixelSize(12)
            f2.setWeight(QFont.Medium)
            p.setFont(f2)
            p.setPen(QColor(255, 255, 255, 170))
            p.drawText(tr.adjusted(nw + 12, 1, 0, 0), Qt.AlignVCenter | Qt.AlignLeft,
                       f"этап {self.index + 1} из {self.count}")
        else:
            p.setPen(QColor("#ffffff" if self.state == "done" else MUTED))
            p.drawText(tr, Qt.AlignCenter, self.text)
        p.end()


FEED_KINDS = (       # значок строки лога → (значок Lucide, цвет)
    ("✅", "circle-check", "#5fd38d"), ("⚠️", "circle-alert", "#f5c451"), ("❌", "circle-x", "#ff6b84"),
    ("⛔", "circle-x", "#ff6b84"), ("🎬", "clapperboard", ACCENT), ("🔊", "volume-2", "#6aa8ff"),
    ("🧠", "cpu", "#b48cff"), ("📝", "captions", "#6aa8ff"), ("🤖", "bot", "#b48cff"),
    ("✂️", "scissors", ACCENT), ("📍", "flag", ACCENT), ("📁", "folder", "#8b8f9a"), ("🎙", "mic", "#6aa8ff"),
    ("⚙️", "settings", "#8b8f9a"), ("ℹ️", "info", "#6aa8ff"), ("🔁", "refresh-cw", "#6aa8ff"),
    ("➕", "plus", "#5fd38d"), ("😕", "circle-alert", "#f5c451"), ("🎞", "film", ACCENT),
)


def feed_item(line):
    """Строка лога → (значок, цвет, текст) для ленты — или None, если строка служебная."""
    line = str(line).rstrip()
    if not line or line[0].isspace() or line.startswith("Traceback"):
        return None
    first = line.split("\n", 1)[0]
    for mark, ic, color in FEED_KINDS:
        if first.startswith(mark):
            text = first[len(mark):].lstrip("\ufe0f ").strip()
            for m, _, _ in FEED_KINDS:                 # значки внутри текста — лишние, цвет и так есть
                text = text.replace(m + " ", "").replace(m, "")
            text = " ".join(text.split())
            return (ic, color, text) if text else None
    return None


class ActivityFeed(QFrame):
    """Лента «Что происходит» (2.3.1): только важное — со значками, временем и плавным появлением.
    Весь лог — по кнопке «Весь лог»."""
    MAX = 60

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 14)
        lay.setSpacing(10)
        self.head = QHBoxLayout()
        self.head.setSpacing(12)
        self.head.addWidget(icon_label("activity"))
        t = QLabel("Что происходит")
        t.setObjectName("cardTitle")
        self.head.addWidget(t)
        self.head.addStretch(1)
        lay.addLayout(self.head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("feedBody")
        self.rows = QVBoxLayout(body)
        self.rows.setContentsMargins(0, 0, 6, 0)
        self.rows.setSpacing(2)
        self.empty = QLabel("Здесь появится ход нарезки: что программа сделала и что нашла.")
        self.empty.setObjectName("hint")
        self.empty.setAlignment(Qt.AlignCenter)
        self.rows.addWidget(self.empty)
        self.rows.addStretch(1)
        self.scroll.setWidget(body)
        lay.addWidget(self.scroll, 1)
        self.items = []
        # новые строки — внизу; лента сама держится у последней, пока её не прокрутили вверх
        self.scroll.verticalScrollBar().rangeChanged.connect(self._stick)

    def add(self, line):
        """Добавить строку, если она важная. → True, если добавлена."""
        got = feed_item(line)
        if not got:
            return False
        ic, color, text = got
        self.empty.hide()
        row = QFrame()
        row.setObjectName("feedRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(12)
        dot = QLabel()
        dot.setObjectName("feedDot")
        dot.setFixedSize(30, 30)
        dot.setAlignment(Qt.AlignCenter)
        c = QColor(color)
        dot.setStyleSheet(f"background: rgba({c.red()},{c.green()},{c.blue()},38); border-radius: 15px;")
        dot.setPixmap(theme.pixmap(ic, color, 16))
        h.addWidget(dot, 0, Qt.AlignTop)
        lb = QLabel(text)
        lb.setObjectName("feedText")
        lb.setWordWrap(True)
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        h.addWidget(lb, 1)
        tm = QLabel(time.strftime("%H:%M"))
        tm.setObjectName("feedTime")
        h.addWidget(tm, 0, Qt.AlignTop)
        self.rows.insertWidget(self.rows.count() - 1, row)
        self.items.append(row)
        while len(self.items) > self.MAX:
            old = self.items.pop(0)
            old.setParent(None)
            old.deleteLater()
        self._appear(row)
        return True

    def _stick(self, _lo, hi):
        sb = self.scroll.verticalScrollBar()
        if not sb.isSliderDown():
            sb.setValue(hi)

    def _appear(self, row):
        """Новая строка плавно проявляется и выезжает снизу, красная подсветка гаснет (≈250 мс)."""
        row.setProperty("fresh", True)
        row.style().unpolish(row)
        row.style().polish(row)

        def calm():
            try:
                row.setProperty("fresh", False)
                row.style().unpolish(row)
                row.style().polish(row)
            except RuntimeError:
                pass
        QTimer.singleShot(1600, calm)
        if not animations_ok(self):
            return
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        h = row.sizeHint().height()
        row.setMaximumHeight(0)
        a = QPropertyAnimation(row, b"maximumHeight", row)
        a.setDuration(240)
        a.setStartValue(0)
        a.setEndValue(h + 4)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.finished.connect(lambda: row.setMaximumHeight(16777215))
        a.start()
        row._anim = a
        fade_in(row, 240)

    def clear(self):
        for r in self.items:
            r.setParent(None)
            r.deleteLater()
        self.items = []
        self.empty.show()


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
        self._lay = lay
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
        self.btn = QPushButton("Нарезать")
        self.btn.setObjectName("accent")
        self.btn.setMinimumWidth(240)
        theme.set_icon(self.btn, "scissors", "#ffffff", 20)
        glow_button(self.btn, 26, 100)
        self.btn.clicked.connect(self.start_or_stop)
        row.addWidget(self.btn, 0, Qt.AlignBottom)
        lay.addLayout(row)

        self.prog_card, pc = card()                    # прогресс — своей карточкой (2.3.0)
        pc.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(icon_label("scissors"))
        ht = QLabel("Ход нарезки")
        ht.setObjectName("cardTitle")
        head.addWidget(ht)
        head.addStretch(1)
        self.total = QLabel("")                         # «Всего 38% · осталось ~4 мин»
        self.total.setObjectName("stepTotal")
        head.addWidget(self.total)
        pc.addLayout(head)
        self.bar = StageBar()                           # этап и его 0–100% — прямо в полосе (2.3.1)
        pc.addWidget(self.bar)
        lay.addWidget(self.prog_card)
        self.eta = None

        self.resume_bar = QWidget()                 # прерванная нарезка — доделать с места обрыва (P3)
        rb = QHBoxLayout(self.resume_bar)
        rb.setContentsMargins(0, 0, 0, 0)
        self.resume_text = QLabel("")
        rb.addWidget(self.resume_text, 1)
        self.btn_resume = QPushButton("Доделать")
        self.btn_resume.setObjectName("primary")
        self.btn_resume.clicked.connect(lambda: self.win.resume_cut(self.resume_path))
        rb.addWidget(self.btn_resume)
        self.resume_bar.hide()
        self.resume_path = None
        lay.addWidget(self.resume_bar)
        from PySide6.QtWidgets import QToolButton
        self.feed = ActivityFeed()                  # только важное, красиво (2.3.1)
        self.btn_log = QToolButton()                # весь лог — по кнопке
        self.btn_log.setObjectName("more")
        self.btn_log.setText("Весь лог")
        self.btn_log.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        theme.set_icon(self.btn_log, "list", MUTED, 14)
        self.btn_log.setCheckable(True)
        self.btn_log.setToolTip("Все строки, как раньше — для разбора ошибок")
        self.btn_log.toggled.connect(self._toggle_log)
        self.feed.head.addWidget(self.btn_log)
        lay.addWidget(self.feed, 1)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.hide()
        lay.addWidget(self.log, 1)

        row = QHBoxLayout()
        self.btn_folder = QPushButton("Открыть папку с клипами")
        theme.set_icon(self.btn_folder, "folder-open", FG, 16)
        self.btn_folder.setEnabled(False)
        self.btn_folder.clicked.connect(lambda: self.last_out and open_path(self.last_out))
        self.btn_clips = QPushButton("К клипам")
        theme.set_icon(self.btn_clips, "film", FG, 16)
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

    def resizeEvent(self, e):
        super().resizeEvent(e)
        center_content(self, self._lay)

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
        self.drop.set_preview(None, os.path.basename(paths[0]), more)
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
        c["zoom"] = autoclip.tri(s["zoom"]) or "auto"
        c["bleep"] = bool(s["bleep"])
        c["hook"] = autoclip.tri(s["hook"]) or "auto"
        c["marks"] = bool(s["marks"])
        c.update(sub_settings(s))
        c["safe_zone"] = bool(s["safe_zone"])
        c["nick"] = bool(s["nick"])
        c["nick_text"] = s["nick_text"]
        c["nick_corner"] = s["nick_corner"]
        c["nick_size"] = NICK_SIZES.get(s["nick_size"], 40)
        c["nick_opacity"] = int(s["nick_opacity"])
        c["hashtags"] = s["hashtags"]
        c["platform_tags"] = dict(s["platform_tags"])
        c["bleep_sound"] = s["sound"]
        c["bleep_pool"] = list(s.get("bleep_pool") or [])
        c["bleep_rel_db"] = float(s.get("bleep_rel_db", 0))
        c["censor"] = "full" if s.get("censor") == "full" else "partial"
        c["clips_dir"] = s.get("clips_dir", DEFAULTS["clips_dir"]) or ""
        c["cache_days"] = int(s.get("cache_days", 30))
        c["clip_length"] = s.get("clip_length") if s.get("clip_length") in autoclip.LENGTHS else "normal"
        autoclip.apply_length(c)
        c["subs_team"] = bool(s.get("subs_team", False))
        c["zoom_focus_y"] = WEBCAM.get(s["cam"], 0.3)
        c["preset"] = s["preset"]
        c["llm"] = s["llm"]
        c["ollama_model"] = s["ollama_model"] or DEFAULTS["ollama_model"]
        c["whisper_device"] = "cpu" if s.get("whisper_device") == "cpu" else "auto"
        if s.get("whisper_model") in ("large-v3", "medium", "small"):
            c["whisper_model"] = s["whisper_model"]

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
        self.eta = autoclip.Eta()
        self.win.start_cut(list(self.files))
        self.btn.setText("Остановить")
        self._busy_style(True)
        self.btn_folder.setEnabled(False)
        self.btn_clips.setEnabled(False)
        self.bar.set_stage(stage_name(autoclip.STAGES[0]), 0, 0, len(autoclip.STAGES))
        self.total.setText("")
        self.feed.clear()

    @property
    def scissors(self):
        """Ножницы едут по краю полосы (их рисует сама полоса)."""
        return self.bar.scissors

    def show_unfinished(self):
        """Есть прерванная нарезка — предложить доделать."""
        try:
            items = autoclip.unfinished_cuts()
        except Exception:
            items = []
        if not items or self.win.busy:
            self.resume_bar.hide()
            return
        pp, left = items[0]
        self.resume_path = pp
        name = os.path.basename(autoclip.cut_root({"_path": pp}))
        self.resume_text.setText(f"Нарезка «{name}» прервалась — не собрано клипов: {left}.")
        self.resume_bar.show()

    def _toggle_log(self, on):
        self.log.setVisible(on)
        self.feed.scroll.setVisible(not on)
        self.feed.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum if on else QSizePolicy.Expanding)
        if on:
            fade_in(self.log, 180)

    def _busy_style(self, on):
        theme.set_icon(self.btn, "square" if on else "scissors", "#ffb3c0" if on else "#ffffff", 20 if not on else 16)
        self.btn.setProperty("busy", on)
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)

    def show_progress(self, stage, pct, msg):
        stages = autoclip.STAGES
        if stage not in stages:
            return
        i = stages.index(stage)
        frac = stage_fraction(stage, pct)
        self.bar.set_stage(stage_name(stage), pct, i, len(stages))       # в полосе — этап и его 0–100%
        left = self.eta.update(frac) if self.eta else None
        self.total.setText(f"Всего {frac * 100:.0f}%" + (f"  ·  {autoclip.fmt_left(left)}" if left is not None else ""))

    def finished(self, out):
        self.eta = None
        if out:
            self.bar.set_done("Готово — клипы в папке")
            self.total.setText("Всего 100%")
        else:
            self.bar.set_idle()
        self.btn.setText("Нарезать")
        self.btn.setEnabled(True)
        self._busy_style(False)
        if out:
            self.last_out = out
            self.btn_folder.setEnabled(True)
            self.btn_clips.setEnabled(True)

    def write(self, msg):
        self.feed.add(msg)
        self.log.appendPlainText(msg)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())


class _LeftClick:
    def button(self):
        return Qt.LeftButton


# ---------------- раздел «Клипы» ----------------

CLIP_PATH = Qt.UserRole + 2          # путь к файлу клипа в строке списка
CARD = Qt.UserRole + 3               # что рисовать на карточке клипа (2.3.0)
STATUS_NAMES = {"new": "Новый", "post": "Выложу", "ok": "Норм", "published": "Выложен",
                "candidate": "Кандидат", "deleted": "Удалён"}


def _rounded(rect, r):
    from PySide6.QtGui import QPainterPath
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), r, r)
    return path


class ClipCards(QObject):
    """Карточки клипов (2.3.0): крупная вертикальная обложка, плашка статуса, оценка; при наведении
    карточка приподнимается, превью играет без звука; пока обложки грузятся — заглушки-скелеты.
    Список остаётся обычным QListWidget — текст строк прежний, рисует карточки делегат."""

    LIST_H = 116                    # высота строки в режиме «список»
    GRID_W, GRID_COVER = 156, 248   # ширина карточки и высота обложки в «сетке»

    def __init__(self, view, page):
        super().__init__(view)
        self.view = view
        self.page = page
        self.grid = False
        self.hover = {}                 # строка → 0..1 (приподнята)
        self.target = {}
        self.hover_row = -1
        self.phase = 0.0                # бегущий блик на скелетах
        self.pixmaps = {}               # путь обложки → (время изменения, картинка)
        self.queue = []                 # обложки, которые ещё грузятся
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(450)
        self.preview_timer.timeout.connect(self._start_preview)
        self._pp = None                 # проигрыватель превью (создаётся при первом наведении)
        self._sink = None
        self.preview_row = -1           # на какой карточке сейчас играет превью
        self.preview_pm = None          # последний кадр превью
        self._last_frame = 0.0
        from PySide6.QtWidgets import QStyledItemDelegate

        cards = self

        class Delegate(QStyledItemDelegate):
            def paint(self, p, opt, index):
                cards.paint(p, opt, index)

            def sizeHint(self, opt, index):
                return cards.size_hint()

        self.delegate = Delegate(view)
        view.setItemDelegate(self.delegate)
        view.setMouseTracking(True)
        view.viewport().setMouseTracking(True)
        view.viewport().installEventFilter(self)
        view.verticalScrollBar().valueChanged.connect(lambda _: self.stop_preview())

    # --- режим ---
    def set_grid(self, on):
        from PySide6.QtWidgets import QListView
        self.grid = bool(on)
        v = self.view
        self.stop_preview()
        if on:
            v.setViewMode(QListView.IconMode)
            v.setFlow(QListView.LeftToRight)
            v.setWrapping(True)
            v.setResizeMode(QListView.Adjust)
            v.setMovement(QListView.Static)
            v.setSpacing(6)
        else:
            v.setViewMode(QListView.ListMode)
            v.setFlow(QListView.TopToBottom)
            v.setWrapping(False)
            v.setSpacing(0)
        v.setDragEnabled(True)
        v.setDragDropMode(QAbstractItemView.DragOnly)
        v.setUniformItemSizes(True)
        v.doItemsLayout()

    def _grid_size(self):
        """Карточки сетки тянутся на всю ширину списка: столько столбцов, сколько влезает."""
        vw = max(160, self.view.viewport().width() - 6)
        cols = max(1, vw // (self.GRID_W + 12))
        w = vw // cols - 12
        return w, int((w - 16) * 16 / 9) + 16

    def size_hint(self):
        if self.grid:
            w, ch = self._grid_size()
            return QSize(w, ch + 74)
        return QSize(max(200, self.view.viewport().width() - 4), self.LIST_H)

    # --- обложки ---
    def cover(self, path):
        """Обложка, если уже загружена; иначе — поставить в очередь (пока рисуется скелет)."""
        if not path:
            return None
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        got = self.pixmaps.get(path)
        if got and got[0] == mtime:
            return got[1]
        if path not in self.queue:
            self.queue.append(path)
            self.timer.start()
        return False

    def load_all_now(self):
        """Догрузить все обложки сразу (снимки экрана, тесты)."""
        while self.queue:
            self._load_one()
        self.view.viewport().update()

    def _load_one(self):
        path = self.queue.pop(0)
        pm = QPixmap(path)
        if pm.isNull():
            self.pixmaps[path] = (0, None)
            return
        pm = pm.scaledToHeight(self.GRID_COVER * 2, Qt.SmoothTransformation)
        try:
            self.pixmaps[path] = (os.path.getmtime(path), pm)
        except OSError:
            pass

    def _tick(self):
        busy = False
        for _ in range(3):                           # по 3 обложки за кадр — окно не подвисает
            if self.queue:
                self._load_one()
                busy = True
        step = 16 / 180                              # приподнимание — 180 мс
        for row, want in list(self.target.items()):
            cur = self.hover.get(row, 0.0)
            if abs(cur - want) > 0.01:
                self.hover[row] = cur + max(-step, min(step, want - cur))
                busy = True
            else:
                self.hover[row] = want
                if want == 0:
                    self.target.pop(row, None)
                    self.hover.pop(row, None)
        if self.queue:
            self.phase = (self.phase + 0.025) % 1.0
        self.view.viewport().update()
        if not busy and not self.queue:
            self.timer.stop()

    # --- наведение ---
    def eventFilter(self, obj, e):
        t = e.type()
        if t == e.Type.Resize and self.grid:
            QTimer.singleShot(0, self.view.doItemsLayout)
        if t == e.Type.MouseMove:
            idx = self.view.indexAt(e.position().toPoint())
            self._hover_to(idx.row() if idx.isValid() else -1)
        elif t == e.Type.Leave:
            self._hover_to(-1)
        return False

    def _hover_to(self, row):
        if row == self.hover_row:
            return
        self.stop_preview()
        if self.hover_row >= 0:
            self.target[self.hover_row] = 0.0
        self.hover_row = row
        if row >= 0:
            self.target[row] = 1.0
            self.preview_timer.start()
        if animations_ok(self.view):
            self.timer.start()
        else:                                        # без анимаций — сразу
            for r, want in list(self.target.items()):
                self.hover[r] = want
            self.view.viewport().update()

    def _cover_rect(self, rect):
        if self.grid:
            w, ch = self._grid_size()
            return QRectF(rect.x() + 8, rect.y() + 8, rect.width() - 16, ch - 16)
        h = rect.height() - 16
        return QRectF(rect.x() + 8, rect.y() + 8, h * 9 / 16, h)

    def _start_preview(self):
        """Превью клипа без звука прямо на обложке. Кадры рисуются на карточке сами — без второго
        окна видео (оно гасило основной плеер: серый экран со звуком)."""
        from PySide6.QtGui import QGuiApplication
        row = self.hover_row
        if row < 0 or not animations_ok(self.view) or QGuiApplication.platformName() == "offscreen":
            return
        it = self.view.item(row)
        path = it.data(CLIP_PATH) if it else None
        if not path or not os.path.isfile(path):
            return
        if self._pp is None:                          # один проигрыватель на весь список
            from PySide6.QtMultimedia import QVideoSink
            self._pp = QMediaPlayer(self)             # без QAudioOutput — звука нет
            self._sink = QVideoSink(self)
            self._pp.setVideoSink(self._sink)
            self._pp.setLoops(QMediaPlayer.Infinite)
            self._sink.videoFrameChanged.connect(self._frame)
        self.preview_row = row
        self.preview_pm = None
        self._last_frame = 0.0
        self._pp.setSource(QUrl.fromLocalFile(path))
        self._pp.play()

    def _frame(self, frame):
        import time as _time
        if self.preview_row < 0:
            return
        now = _time.monotonic()
        if now - self._last_frame < 1 / 20:            # 20 кадров в секунду — хватает и не грузит
            return
        self._last_frame = now
        img = frame.toImage()
        if img.isNull():
            return
        self.preview_pm = QPixmap.fromImage(img.scaledToHeight(self.GRID_COVER * 2, Qt.FastTransformation))
        it = self.view.item(self.preview_row)
        if it is not None:
            self.view.viewport().update(self.view.visualItemRect(it))

    def stop_preview(self):
        self.preview_timer.stop()
        if self.preview_row >= 0:
            row = self.preview_row
            self.preview_row = -1
            self.preview_pm = None
            if self._pp is not None:
                self._pp.stop()
                self._pp.setSource(QUrl())
            it = self.view.item(row)
            if it is not None:
                self.view.viewport().update(self.view.visualItemRect(it))

    # --- рисование ---
    def paint(self, p, opt, index):
        from PySide6.QtWidgets import QStyle
        d = index.data(CARD)
        if not d:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        t = self.hover.get(index.row(), 0.0)
        sel = bool(opt.state & QStyle.State_Selected)
        rect = QRectF(opt.rect).adjusted(4, 4, -4, -4)
        rect.translate(0, -3 * t)
        if t > 0:                                    # мягкая тень под приподнятой карточкой
            for k in range(4):
                c = QColor(0, 0, 0, int(28 * t))
                p.setPen(Qt.NoPen)
                p.setBrush(c)
                p.drawRoundedRect(rect.adjusted(-k, k + 2, k, k + 4), 14 + k, 14 + k)
        bg = QColor("#2a1a22") if sel else QColor("#17181e").lighter(100 + int(18 * t))
        p.setBrush(bg)
        p.setPen(QPen(QColor(ACCENT if sel else ("#3a3e4a" if t > 0.5 else "#24262e")), 1.6 if sel else 1))
        p.drawRoundedRect(rect, 14, 14)
        cand = d["kind"] != "clip"
        cr = self._cover_rect(rect.toRect())
        pm = None if cand else self.cover(d.get("cover"))
        if index.row() == self.preview_row and self.preview_pm is not None:
            pm = self.preview_pm                       # превью при наведении — кадр клипа
        p.save()
        p.setClipPath(_rounded(cr, 10))
        if pm:
            sw = cr.width() / cr.height() * pm.height()
            src = QRectF((pm.width() - sw) / 2, 0, sw, pm.height())     # по центру, как 9:16
            p.drawPixmap(cr, pm, src)
        elif pm is False:                              # грузится — скелет с бегущим бликом
            from PySide6.QtGui import QLinearGradient
            g = QLinearGradient(cr.left() - cr.width() + 3 * cr.width() * self.phase, 0,
                                cr.left() + 3 * cr.width() * self.phase, 0)
            g.setColorAt(0, QColor("#1c1d24"))
            g.setColorAt(0.5, QColor("#2a2c35"))
            g.setColorAt(1, QColor("#1c1d24"))
            p.fillRect(cr, g)
        else:
            p.fillRect(cr, QColor("#1c1d24"))
            ic = theme.pixmap("sparkles" if cand else "film", "#4a4e5a", 22)
            p.drawPixmap(int(cr.center().x() - 11), int(cr.center().y() - 11), ic)
        p.restore()
        if self.grid:
            self._paint_grid(p, rect, cr, d, sel)
        else:
            self._paint_list(p, rect, cr, d, sel)
        p.restore()

    def _font(self, px, weight=QFont.Normal):
        f = QFont(theme.FAMILY or "Segoe UI")
        f.setPixelSize(px)
        f.setWeight(weight)
        return f

    def _pill(self, p, x, y, status):
        name = STATUS_NAMES.get(status, status)
        fg, bg = theme.STATUS_COLORS.get(status, theme.STATUS_COLORS["rejected"])
        f = self._font(11, QFont.DemiBold)
        p.setFont(f)
        from PySide6.QtGui import QFontMetrics
        w = QFontMetrics(f).horizontalAdvance(name) + 18
        r = QRectF(x, y, w, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(QColor(fg))
        p.drawText(r, Qt.AlignCenter, name)
        return w

    def _score(self, p, x, y, score, on_cover=False):
        r = QRectF(x, y, 30 + text_width(f"{score:.1f}", 12, QFont.DemiBold), 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 160) if on_cover else QColor("#22242c"))
        p.drawRoundedRect(r, 11, 11)
        hot = score >= 6
        p.drawPixmap(int(x + 7), int(y + 4), theme.pixmap("star", ACCENT if hot else "#f5c451", 14))
        p.setFont(self._font(12, QFont.DemiBold))
        p.setPen(QColor("#ffffff"))
        p.drawText(r.adjusted(22, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, f"{score:.1f}")

    def _paint_list(self, p, rect, cr, d, sel):
        x = cr.right() + 14
        w = rect.right() - x - 10
        y = rect.top() + 10
        p.setFont(self._font(12, QFont.DemiBold))
        p.setPen(QColor(theme.DIM if d["kind"] != "clip" else MUTED))
        num = f"{d['num']:02d}" if d.get("num") is not None else ""
        p.drawText(QRectF(x, y, 30, 20), Qt.AlignVCenter | Qt.AlignLeft, num)
        tx = x + (28 if num else 0)
        p.setFont(self._font(14, QFont.DemiBold))
        p.setPen(QColor("#ffffff" if d["kind"] == "clip" else MUTED))
        from PySide6.QtGui import QFontMetrics
        title = QFontMetrics(p.font()).elidedText(d["title"], Qt.ElideRight, int(w - (tx - x)))
        p.drawText(QRectF(tx, y, w - (tx - x), 20), Qt.AlignVCenter | Qt.AlignLeft, title)
        p.setFont(self._font(12))
        p.setPen(QColor(MUTED))
        meta = QFontMetrics(p.font()).elidedText(d["meta"], Qt.ElideRight, int(w))
        p.drawText(QRectF(x, y + 24, w, 18), Qt.AlignVCenter | Qt.AlignLeft, meta)
        if d.get("tags"):
            p.setPen(QColor(theme.DIM))
            tags = QFontMetrics(p.font()).elidedText(d["tags"], Qt.ElideRight, int(w))
            p.drawText(QRectF(x, y + 44, w, 18), Qt.AlignVCenter | Qt.AlignLeft, tags)
        by = rect.bottom() - 32
        px = x + self._pill(p, x, by + 1, d["status"]) + 8
        self._score(p, px, by, d["score"])
        if d.get("marks"):
            sx = px + 38 + text_width(f"{d['score']:.1f}", 12, QFont.DemiBold)
            p.drawPixmap(int(sx), int(by + 3), theme.pixmap("flag", ACCENT, 16))

    def _paint_grid(self, p, rect, cr, d, sel):
        self._score(p, cr.left() + 6, cr.top() + 6, d["score"], on_cover=True)
        if d.get("marks"):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 160))
            p.drawEllipse(QRectF(cr.right() - 28, cr.top() + 6, 22, 22))
            p.drawPixmap(int(cr.right() - 24), int(cr.top() + 10), theme.pixmap("flag", ACCENT, 14))
        self._pill(p, cr.left() + 6, cr.bottom() - 26, d["status"])
        x, w = rect.left() + 10, rect.width() - 20
        y = cr.bottom() + 8
        from PySide6.QtGui import QFontMetrics
        p.setFont(self._font(13, QFont.DemiBold))
        p.setPen(QColor("#ffffff" if d["kind"] == "clip" else MUTED))
        fm = QFontMetrics(p.font())
        text = (f"{d['num']:02d}  " if d.get("num") is not None else "") + d["title"]
        lines, rest = [], text
        for _ in range(2):                           # название — в две строки, дальше «…»
            if not rest:
                break
            cut = len(rest)
            while cut > 1 and fm.horizontalAdvance(rest[:cut]) > w:
                cut = rest.rfind(" ", 0, cut - 1) if rest.rfind(" ", 0, cut - 1) > 0 else cut - 1
            lines.append(rest[:cut].strip())
            rest = rest[cut:].strip()
        if rest and lines:
            lines[-1] = fm.elidedText(lines[-1] + " " + rest, Qt.ElideRight, int(w))
        for k, line in enumerate(lines):
            p.drawText(QRectF(x, y + 18 * k, w, 18), Qt.AlignVCenter | Qt.AlignLeft, line)
        p.setFont(self._font(11))
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(x, y + 40, w, 16), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(p.font()).elidedText(d["meta"], Qt.ElideRight, int(w)))


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


FILTERS = (("Все", None), ("Новые", {"new"}), ("Выложу", {"post"}), ("Норм", {"ok"}), ("Выложены", {"published"}),
           ("Кандидаты", {"candidate"}), ("Удалённые", {"deleted"}))
CAND = "cand:"       # так в списке помечены кандидаты (моменты без видео)
SHIFT = 2.0          # шаг сдвига начала и конца, сек
COVER_W, COVER_H = 34, 60   # обложка в списке клипов


class ClipsPage(QWidget):
    """Список клипов нарезки и редактор выбранного клипа."""
    wave_ready = Signal(str, object)          # волна звука для таймлайна (id клипа, точки)

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
        b = QPushButton("Копировать путь")
        b.setToolTip("Путь к папке этой нарезки — в буфер")
        b.clicked.connect(self.copy_cut_path)
        top.addWidget(b)
        b = QPushButton("Открыть папку")
        b.clicked.connect(self.open_cut_folder)
        top.addWidget(b)
        b = QPushButton("Другая…")
        b.setToolTip("Открыть нарезку из другой папки")
        b.clicked.connect(self.pick)
        top.addWidget(b)
        lay.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        from PySide6.QtWidgets import QGridLayout
        frow = QGridLayout()                       # фильтры в два ряда — подписи не обрезаются (D.1)
        frow.setHorizontalSpacing(4)
        frow.setVerticalSpacing(4)
        self.filter_btns = []
        per_row = (len(FILTERS) + 1) // 2
        for i, (name, _) in enumerate(FILTERS):
            fb = QPushButton(name)
            fb.setCheckable(True)
            fb.setObjectName("filter")
            fb.setMinimumWidth(text_width(name, 13) + 30)
            fb.clicked.connect(lambda _, i=i: self.set_filter(i))
            frow.addWidget(fb, i // per_row, i % per_row)
            self.filter_btns.append(fb)
        frow.setColumnStretch(per_row, 1)
        vbox = QHBoxLayout()                       # «список / сетка» (2.3.0)
        vbox.setSpacing(2)
        self.view_btns = {}
        for key, ic, tip in (("list", "list", "Список"), ("grid", "layout-grid", "Сетка")):
            vb = QPushButton()
            vb.setObjectName("viewBtn")
            vb.setCheckable(True)
            vb.setToolTip(tip)
            theme.set_icon(vb, ic, MUTED, 16, active="#ffffff")
            vb.clicked.connect(lambda _, k=key: self.set_view(k))
            vbox.addWidget(vb)
            self.view_btns[key] = vb
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
        srow = QHBoxLayout()
        srow.setSpacing(8)
        srow.addWidget(self.search, 1)
        srow.addLayout(vbox)
        ll.addLayout(srow)
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
        self.cards = ClipCards(self.list, self)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)    # Ctrl/Shift — несколько (5.15)
        self._covers = {}              # обложки списка: путь → (время изменения, значок)
        self.list.currentRowChanged.connect(self._row_changed)
        self.list.itemDoubleClicked.connect(lambda _: self.player.play())
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.clip_menu)
        self.left_stack.addWidget(self.list)
        self.left_stack.addWidget(found)
        split.addWidget(left)

        right = QWidget()
        rl_outer = QVBoxLayout(right)
        rl_outer.setContentsMargins(16, 0, 0, 0)
        rl_outer.setSpacing(12)
        upper = QHBoxLayout()
        upper.setSpacing(16)
        self.upper = upper
        rl_outer.addLayout(upper, 1)
        player_col = QFrame()
        player_col.setObjectName("playerBox")
        rl = QVBoxLayout(player_col)
        rl.setContentsMargins(12, 12, 12, 10)
        rl.setSpacing(8)
        upper.addWidget(player_col, 1)
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

        from PySide6.QtWidgets import QToolButton
        self.info_line = QToolButton()                  # «Прогноз 7.5 ▾» — разбор по клику (5.18)
        self.info_line.setObjectName("more")
        self.info_line.setCheckable(True)
        self.info_line.toggled.connect(self._toggle_info)
        self.info_line.hide()
        rl.addWidget(self.info_line)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rl.addWidget(self.info)
        self.btn_build = QPushButton("Собрать")
        self.btn_build.setObjectName("primary")
        self.btn_build.setToolTip("Сделать из кандидата обычный клип")
        self.btn_build.clicked.connect(self.build_candidate)
        self.cand_bar = QWidget()
        cb = QHBoxLayout(self.cand_bar)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(6)
        cb.addWidget(self.btn_build)
        self.btn_cand_play = QPushButton("Просмотр")
        self.btn_cand_play.setToolTip("Запись в границах кандидата: от начала до конца, без сборки")
        self.btn_cand_play.clicked.connect(self.play_candidate)
        cb.addWidget(self.btn_cand_play)
        self.btn_cand_del = QPushButton("Удалить кандидата")
        self.btn_cand_del.setObjectName("ghost")
        self.btn_cand_del.clicked.connect(self.delete_candidate)
        cb.addWidget(self.btn_cand_del)
        cb.addWidget(hint("Кандидаты сами не пропадают — собрать или удалить можно в любой момент"), 1)
        self.cand_bar.hide()
        rl.addWidget(self.cand_bar)

        # --- редактор клипа: справа от плеера, вкладки — сегментированный переключатель (2.3.0) ---
        self.editor, outer = card()
        outer.setSpacing(12)
        seg = QFrame()
        seg.setObjectName("segBox")
        tabs = QHBoxLayout(seg)
        tabs.setContentsMargins(3, 3, 3, 3)
        tabs.setSpacing(2)
        self.ed_tabs = []
        for i, name in enumerate(("Клип", "Текст", "Описание", "Публикация", "Музыка")):
            b = QPushButton(name)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.clicked.connect(lambda _, i=i: self.show_tab(i))
            tabs.addWidget(b, 1)
            self.ed_tabs.append(b)
        outer.addWidget(seg)
        self.ed_stack = QStackedWidget()
        outer.addWidget(self.ed_stack)
        page = QWidget()
        ed = QVBoxLayout(page)
        ed.setContentsMargins(0, 0, 6, 0)
        ed.setSpacing(10)
        clip_scroll = QScrollArea()
        clip_scroll.setWidgetResizable(True)
        clip_scroll.setFrameShape(QFrame.NoFrame)
        clip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        clip_scroll.setWidget(page)
        self.ed_stack.addWidget(clip_scroll)
        # ---- на виду (5.18): таймлайн, название, Субтитры / Мат / Хук, оценка, «Пересобрать» ----
        from timeline import Timeline
        self.tl = Timeline()
        self.tl.setToolTip("Тяни красные ручки — начало и конец. Жёлтый отрезок — хук, его можно двигать. "
                           "Клик — перемотка, потянуть по пустому месту — выделить кусок (X — вырезать). "
                           "Метки внизу — писки (клик — убрать/вернуть). Колесо — масштаб")
        self.tl.bounds_changed.connect(self._tl_bounds)
        self.tl.hook_changed.connect(self._tl_hook)
        self.tl.seek.connect(self._tl_seek)
        self.tl.selection_changed.connect(self._tl_selection)
        self.tl.bleep_clicked.connect(self._tl_bleep)
        self.tl_box = QFrame()                       # таймлайн — во всю ширину под плеером (2.3.0)
        self.tl_box.setObjectName("panel")
        tlb = QVBoxLayout(self.tl_box)
        tlb.setContentsMargins(12, 10, 12, 10)
        tlb.addWidget(self.tl)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.e_title = QLineEdit()
        self.e_title.setPlaceholderText("Название клипа")
        self.e_title.textEdited.connect(self._title_edited)
        row.addWidget(self.e_title, 1)
        self.btn_rebuild = QPushButton("Пересобрать")
        self.btn_rebuild.setObjectName("primary")
        theme.set_icon(self.btn_rebuild, "refresh-cw", "#ffffff", 15)
        glow_button(self.btn_rebuild, 16, 70)
        self.btn_rebuild.clicked.connect(self.rebuild)
        row.addWidget(self.btn_rebuild)
        ed.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(18)
        self.e_subs = Toggle()
        self.e_bleep = Toggle(tip="Закрыть мат звуком")
        for text, w in (("Субтитры", self.e_subs), ("Мат", self.e_bleep)):
            pair = QHBoxLayout()
            pair.setSpacing(8)
            pair.addWidget(w)
            pair.addWidget(QLabel(text))
            row.addLayout(pair)
            w.toggled.connect(self._changed)
        self.e_hook = tri_combo("auto", "Кульминация 1,5–3 с из этого клипа в самом начале. "
                                        "Авто — когда кульминация найдена")
        self.e_hook.currentIndexChanged.connect(self._changed)
        pair = QHBoxLayout()
        pair.setSpacing(6)
        pair.addWidget(QLabel("Хук"))
        pair.addWidget(self.e_hook)
        row.addLayout(pair)
        row.addStretch(1)
        ed.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_good = QPushButton("Выложу")
        theme.set_icon(self.btn_good, "thumbs-up", FG, 16, active="#ffffff")
        self.btn_good.setToolTip("Момент хороший — буду выкладывать  (G)")
        self.btn_good.setCheckable(True)
        self.btn_good.clicked.connect(lambda: self.rate("post"))
        self.btn_ok = QPushButton("Норм")
        self.btn_ok.setToolTip("Момент найден правильно, но выкладывать не буду  (N)")
        self.btn_ok.setCheckable(True)
        self.btn_ok.clicked.connect(lambda: self.rate("ok"))
        self.btn_trash = QPushButton("Не то")
        self.btn_trash.setToolTip("Так больше не надо — клип в корзину Windows  (D)")
        self.btn_trash.setObjectName("danger")
        self.btn_trash.clicked.connect(self.to_trash)
        for w in (self.btn_good, self.btn_ok, self.btn_trash):
            row.addWidget(w)
        self.state = hint("")
        row.addWidget(self.state, 1)
        ed.addLayout(row)

        from PySide6.QtWidgets import QToolButton
        self.btn_more = QToolButton()
        self.btn_more.setText("Ещё настройки")
        self.btn_more.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        theme.set_icon(self.btn_more, "chevron-right", MUTED, 14)
        self.btn_more.setCheckable(True)
        self.btn_more.setObjectName("more")
        self.btn_more.toggled.connect(self._toggle_more)
        ed.addWidget(self.btn_more)
        self.more = QWidget()
        ml = QVBoxLayout(self.more)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(10)
        ed.addWidget(self.more)
        self.more.hide()

        def head(text):
            lb = QLabel(text)
            lb.setObjectName("fieldLabel")
            return lb

        # вид
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(head("Вид"))
        self.e_zoom = tri_combo("auto", "Авто — только на смехе и крике, не больше 3. Вкл — на всех громких местах")
        self.e_zoom.currentIndexChanged.connect(self._changed)
        pair = QHBoxLayout()
        pair.setSpacing(6)
        pair.addWidget(QLabel("Зум"))
        pair.addWidget(self.e_zoom)
        row.addLayout(pair)
        self.e_safe = Toggle(tip="Субтитры не заходят под кнопки, ник и подпись TikTok, Shorts и Reels")
        self.e_nick = Toggle(tip="Ник в углу — текст и угол в «Настройках»")
        for text, w in (("Не залезать под кнопки TikTok", self.e_safe), ("Ник", self.e_nick)):
            pair = QHBoxLayout()
            pair.setSpacing(8)
            pair.addWidget(w)
            pair.addWidget(QLabel(text))
            row.addLayout(pair)
            w.toggled.connect(self._changed)
        row.addStretch(1)
        ml.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("Субтитры"))
        self.e_pos = QComboBox()
        self.e_pos.addItems(list(autoclip.SUB_POSITIONS))
        self.e_pos.setToolTip("Где субтитры")
        self.e_pos.currentTextChanged.connect(self._changed)
        row.addWidget(self.e_pos)
        self.e_subs.toggled.connect(self.e_pos.setEnabled)
        self.e_subs.toggled.connect(self.e_safe.setEnabled)
        row.addWidget(QLabel("Стиль"))
        self.e_style = QComboBox()
        self.e_style.setMinimumWidth(150)
        self.e_style.setToolTip("Стиль субтитров этого клипа. Свои стили — в «Настройках»")
        self.e_style.currentIndexChanged.connect(self._changed)
        row.addWidget(self.e_style)
        row.addStretch(1)
        ml.addLayout(row)

        # мат
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(head("Мат"))
        self.e_sound = QComboBox()
        self.e_sound.setMinimumWidth(180)
        self.e_sound.setToolTip("Звук на мат")
        self.e_sound.currentTextChanged.connect(self._changed)
        self.e_bleep.toggled.connect(self.e_sound.setEnabled)
        row.addWidget(self.e_sound)
        row.addWidget(SoundButton(self.e_sound))
        self.btn_shuffle = QPushButton("Другие звуки мата")
        self.btn_shuffle.setToolTip("Звук «Случайный»: на этом клипе — другие звуки")
        self.btn_shuffle.clicked.connect(self.shuffle_sounds)
        self.e_sound.currentTextChanged.connect(
            lambda t: self.btn_shuffle.setVisible(t == autoclip.RANDOM_SOUND))
        row.addWidget(self.btn_shuffle)
        self.e_censor = censor_combo("partial")
        self.e_censor.setToolTip("Частичная: «е*ать». TikTok может распознать полузапиканный мат и урезать охват")
        self.e_censor.currentIndexChanged.connect(self._changed)
        row.addWidget(self.e_censor)
        row.addStretch(1)
        ml.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Мат найден автоматически"))
        self.e_bleeps = QComboBox()
        self.e_bleeps.setMinimumWidth(160)
        self.e_bleeps.setToolTip("Где в клипе закрыт мат. «Убрать писк» — если запикано зря")
        row.addWidget(self.e_bleeps, 1)
        b = QPushButton("Запикать здесь")
        b.setToolTip("Закрыть звуком полсекунды на месте просмотра — для слова, которого нет в субтитрах  (B)")
        b.clicked.connect(self.bleep_here)
        row.addWidget(b)
        b = QPushButton("Убрать писк")
        b.setObjectName("ghost")
        b.clicked.connect(self.bleep_toggle)
        row.addWidget(b)
        ml.addLayout(row)
        self.b_add, self.b_rem = [], []

        # хук
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(head("Хук"))
        self.h_label = hint("")
        self.h_label.setMinimumWidth(150)
        row.addWidget(self.h_label)
        b = QPushButton("Хук отсюда")
        b.setToolTip("Хук — целая фраза у места просмотра  (H). Жёлтый отрезок на таймлайне можно двигать")
        b.clicked.connect(self.hook_here)
        row.addWidget(b)
        b = QPushButton("Просмотр хука")
        b.clicked.connect(self.hook_preview)
        row.addWidget(b)
        self.hook_btns = [b]
        row.addStretch(1)
        ml.addLayout(row)
        self.hook_at = None

        # точное время
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(head("Время"))
        self.e_start = QLineEdit()
        self.e_end = QLineEdit()
        for label, edit in (("Начало", self.e_start), ("Конец", self.e_end)):
            row.addWidget(QLabel(label))
            edit.setFixedWidth(96)
            edit.setAlignment(Qt.AlignCenter)
            edit.setToolTip("Время в записи: 1:18 или 0:01:18.5 (или тяни ручки на таймлайне, I / O)")
            edit.textChanged.connect(self._changed)
            row.addWidget(edit)
            row.addSpacing(10)
        self.e_len = hint("")
        row.addWidget(self.e_len)
        row.addStretch(1)
        ml.addLayout(row)

        # вырезки
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(head("Вырезки"))
        self.btn_cut = QPushButton("Вырезать выделенное")
        self.btn_cut.setToolTip("Выдели кусок на таймлайне (потяни мышкой) и вырежи  (X)")
        self.btn_cut.clicked.connect(self.cut_piece)
        row.addWidget(self.btn_cut)
        self.cut_info = hint("")
        self.cut_info.setMinimumWidth(170)
        row.addWidget(self.cut_info)
        self.btn_cuts_reset = QPushButton("Сбросить вырезки")
        self.btn_cuts_reset.setObjectName("ghost")
        self.btn_cuts_reset.clicked.connect(self.cuts_reset)
        row.addWidget(self.btn_cuts_reset)
        row.addStretch(1)
        ml.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(6)
        from PySide6.QtWidgets import QDoubleSpinBox
        self.btn_pauses = QPushButton("Сжать паузы")
        self.btn_pauses.setToolTip("Вырезать паузы без речи длиннее заданной, по 0,3 с тишины остаётся")
        self.btn_pauses.clicked.connect(self.squeeze_pauses)
        row.addWidget(self.btn_pauses)
        row.addWidget(QLabel("длиннее"))
        self.pause_len = QDoubleSpinBox()
        self.pause_len.setRange(0.8, 6.0)
        self.pause_len.setSingleStep(0.5)
        self.pause_len.setDecimals(1)
        self.pause_len.setSuffix(" с")
        self.pause_len.setValue(autoclip.PAUSE_MIN)
        self.pause_len.setFixedWidth(80)
        self.pause_len.valueChanged.connect(self.pause_preview)
        row.addWidget(self.pause_len)
        self.pause_info = hint("")
        row.addWidget(self.pause_info)
        row.addSpacing(10)
        self.btn_split = QPushButton("Разделить на 2 клипа")
        self.btn_split.setToolTip("Два клипа: до места просмотра и после (граница — в паузе между словами)")
        self.btn_split.clicked.connect(self.split_here)
        row.addWidget(self.btn_split)
        row.addStretch(1)
        ml.addLayout(row)
        self.cuts, self.cut_ab, self._voice = [], [None, None], {}
        self.bleep_seed = None

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_save = QPushButton("Сохранить как…")
        self.btn_save.clicked.connect(self.save_as)
        self.btn_show = QPushButton("Показать в папке")
        self.btn_show.clicked.connect(self.show_file)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_show)
        row.addStretch(1)
        ml.addLayout(row)
        ed.addStretch(1)
        self._undo = []
        self._shortcuts()
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
            lbl.setMinimumWidth(text_width("Instagram", 13) + 8)
            row.addWidget(lbl)
            state = hint("")
            state.setMinimumWidth(100)
            row.addWidget(state)
            go = QPushButton("Открыть")
            go.setToolTip(f"Окно загрузки {name}, описание — в буфер")
            go.clicked.connect(lambda _, k=key: self.publish(k))
            row.addWidget(go)
            mark = QPushButton()
            mark.clicked.connect(lambda _, k=key: self.toggle_published(k))
            row.addWidget(mark)
            row.addStretch(1)
            pl.addLayout(row)
            self.pub_rows[key] = (state, None, mark)      # ссылки на пост больше нет (5.5)
        pl.addWidget(hint("Instagram в браузере: нажми «Создать» (+) в меню слева."))
        self.pub_state = hint("")
        pl.addWidget(self.pub_state)
        pl.addStretch(1)
        self.ed_stack.addWidget(page)

        # --- музыка ---
        self._build_text_tab()
        page = QWidget()
        ml = QVBoxLayout(page)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(8)
        ml.addWidget(hint(MUSIC_HINT))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.m_search = QLineEdit()
        self.m_search.setPlaceholderText("Поиск трека в папке «Музыка»")
        self.m_search.setClearButtonEnabled(True)
        self.m_search.textChanged.connect(self.fill_tracks)
        row.addWidget(self.m_search, 1)
        b = QPushButton("Файл…")
        b.setToolTip("Выбрать свой трек: mp3, wav, ogg, flac, m4a")
        b.clicked.connect(self.pick_track)
        row.addWidget(b)
        self.m_none = QPushButton("Без музыки")
        self.m_none.setObjectName("ghost")
        self.m_none.clicked.connect(lambda: self.set_track(None))
        row.addWidget(self.m_none)
        ml.addLayout(row)
        self.m_list = QListWidget()
        self.m_list.setFixedHeight(84)
        self.m_list.itemClicked.connect(lambda it: self.set_track(it.data(Qt.UserRole)))
        ml.addWidget(self.m_list)
        self.m_name = hint("Без музыки")
        ml.addWidget(self.m_name)
        self.m_wave = WaveView()
        self.m_wave.moved.connect(lambda off: self._music_set(offset=off))
        ml.addWidget(self.m_wave)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("Громкость"))
        self.m_vol = QSlider(Qt.Horizontal)
        self.m_vol.setRange(-40, -3)
        self.m_vol.setValue(-18)
        self.m_vol.setFixedWidth(150)
        self.m_vol_l = hint("−18 дБ к голосу")
        self.m_vol_l.setWordWrap(False)
        self.m_vol.valueChanged.connect(lambda v: (self.m_vol_l.setText(f"−{abs(v)} дБ к голосу"),
                                                   self._music_set(volume=float(v))))
        row.addWidget(self.m_vol)
        row.addWidget(self.m_vol_l)
        row.addStretch(1)
        ml.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.m_duck = Toggle(True, tip="Когда говорят — музыка уходит ещё тише")
        self.m_duck.toggled.connect(lambda v: self._music_set(duck=bool(v)))
        row.addWidget(self.m_duck)
        row.addWidget(QLabel("Тише под речью"))
        row.addSpacing(10)
        row.addWidget(QLabel("Края"))
        self.m_fade = Stepper(0, 5, 1)
        self.m_fade.valueChanged.connect(lambda v: self._music_set(fade=float(v)))
        row.addWidget(self.m_fade)
        row.addWidget(hint("с"))
        row.addStretch(1)
        ml.addLayout(row)
        row = QHBoxLayout()
        self.m_listen = QPushButton("Прослушать с клипом")
        self.m_listen.setToolTip("Клип и музыка вместе, с этой громкостью. В клип — после «Пересобрать»")
        self.m_listen.clicked.connect(self.listen_music)
        row.addWidget(self.m_listen)
        self.m_state = hint("")
        row.addWidget(self.m_state, 1)
        ml.addLayout(row)
        ml.addStretch(1)
        self.ed_stack.addWidget(page)
        self.music = None
        self._waves = {}
        self.win.bus.music_ready.connect(self._music_ready)

        self.desc_platform = "tiktok"
        self._desc_clip = None
        self._desc_timer = QTimer(self)
        self._desc_timer.setSingleShot(True)
        self._desc_timer.setInterval(600)
        self._desc_timer.timeout.connect(self.save_desc)
        self.show_tab(0)
        self.set_desc_platform("tiktok")
        self.set_view(self.win.settings.get("clips_view", "grid"))

        self.editor.setMinimumWidth(420)
        self.editor.setMaximumWidth(600)
        self.editor.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        upper.addWidget(self.editor)
        rl_outer.addWidget(self.tl_box)
        self.editor.setEnabled(False)

        split.addWidget(right)
        left.setMinimumWidth(max(400, sum(b.minimumWidth() for b in self.filter_btns[4:]) + 3 * 4 +
                                 max(b.minimumWidth() for b in self.filter_btns[:4]) + 8))
        split.setStretchFactor(0, 1)                # на широком мониторе растёт и список
        split.setStretchFactor(1, 3)
        split.setSizes([410, 1000])
        right.installEventFilter(self)              # ширина правой части — раскладка редактора
        self.split = split
        split.splitterMoved.connect(lambda *_: self._relayout())
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
        self.win.bus.rebuild_progress.connect(self._rebuild_progress)
        self.win.bus.send_state.connect(self._send_state)
        self.refresh_recent()

    def _send_state(self, text):
        """Ход отправки в Telegram — крупно по центру окна (2.3.1), строкой — у кнопок."""
        self.state.setText(text)
        text = str(text).replace(" ✓", "")
        if text.startswith("Отправлено в Telegram"):
            c = self.current_clip()
            extra = text[len("Отправлено в Telegram"):].strip(" :")
            sub = extra or (c["title"] if c else "")
            self.win.notice("ok", "Отправлено в Telegram", sub)
        elif "не отправил" in text.lower():
            reason = text.split(":", 1)[1].strip() if ":" in text else text
            self.win.notice("error", "Не отправилось", reason, 5000)
        elif text.startswith("Telegram"):
            what = text.split(":", 1)[1].strip() if ":" in text else ""
            self.win.notice("busy", "Отправляю в Telegram", what)

    # ---------- нарезки ----------
    def refresh_recent(self):
        """Список нарезок AutoClip (5.14): все нарезки — по маркеру и из списка нарезок."""
        self.cuts = autoclip.cut_summaries(self.win.settings.get("recent", []))
        self.projects.clear()
        for x in self.cuts:
            self.projects.addItem(autoclip.cut_label(x), x["path"])
        # пока нарезку не выбрали — список пустой (при запуске «Клипы» пустые)
        cur = os.path.normcase(os.path.abspath(self.proj["_path"])) if self.proj else None
        idx = next((k for k, x in enumerate(self.cuts) if os.path.normcase(x["path"]) == cur), -1)
        self.projects.setCurrentIndex(idx)

    def copy_cut_path(self):
        if self.proj:
            QApplication.clipboard().setText(autoclip.cut_root(self.proj))
            self.state.setText("Путь к папке — в буфере")

    def open_cut_folder(self):
        if self.proj:
            open_path(autoclip.cut_root(self.proj))

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
        self.refresh_recent()
        self.search.blockSignals(True)
        self.search.clear()                          # поиск — по расшифровке этой записи
        self.search.blockSignals(False)
        self.left_stack.setCurrentIndex(0)
        self.refill(select_id)

    def reload(self, select_id=None):
        """Перечитать project.json после изменений ядра."""
        fade_in(self.list, 140)
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

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    def eventFilter(self, obj, e):
        if e.type() == e.Type.Resize and obj is self.split.widget(1):
            self._relayout()
        return False

    def _relayout(self):
        """Широкое окно — редактор справа от плеера; узкое — под плеером (ничего не обрезается)."""
        from PySide6.QtWidgets import QBoxLayout
        right = self.split.widget(1)
        if right is None:
            return
        wide = right.width() >= 860
        if wide == getattr(self, "_wide", None):
            return
        self._wide = wide
        self.upper.setDirection(QBoxLayout.LeftToRight if wide else QBoxLayout.TopToBottom)
        self.editor.setMaximumWidth(600 if wide else 16777215)
        self.editor.setMinimumWidth(420 if wide else 0)
        self.upper.setStretch(0, 1 if wide else 3)
        self.upper.setStretch(1, 0 if wide else 2)

    def set_view(self, key):
        """«Список» или «Сетка» — запоминается."""
        key = "list" if key == "list" else "grid"
        for k, b in self.view_btns.items():
            b.setChecked(k == key)
        self.cards.set_grid(key == "grid")
        if self.win.settings.get("clips_view") != key:
            self.win.settings["clips_view"] = key
            save_settings(self.win.settings)
        fade_in(self.list, 160)

    def refill(self, select_id=None):
        want = FILTERS[self.filter][1]
        self.cards.stop_preview()
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
            tags = [t for t in autoclip.clip_tags(c)[1:]]
            it.setData(CARD, {"kind": "clip", "num": c["num"], "score": float(c["score"]), "title": c["title"],
                              "status": c["status"], "marks": bool(c.get("marks")), "tags": " · ".join(tags),
                              "meta": f"{autoclip.fmt_time(c['start'])}–{autoclip.fmt_time(c['end'])}"
                                      f" · {c['end'] - c['start']:.0f} с",
                              "cover": autoclip.cover_path_for(autoclip.cut_root(self.proj), c["file"])
                              if c.get("cover") else None})
            it.setData(Qt.UserRole, c["id"])
            it.setData(CLIP_PATH, self.clip_path(c))
            self.list.addItem(it)
            if c["id"] == select_id:
                row = i
        # кандидаты — серыми, внизу списка («Все») или отдельно («Кандидаты»)
        if want is None or "candidate" in want or "deleted" in want:
            show_deleted = want is not None and "deleted" in want
            gray = QColor(MUTED)
            blank = QPixmap(COVER_W, COVER_H)          # пустое место вместо обложки — строки ровные
            blank.fill(Qt.transparent)
            for k in sorted(self.proj.get("candidates") or [], key=lambda k: -k["score"]):
                if bool(k.get("deleted")) != show_deleted:
                    continue
                it = QListWidgetItem(
                    QIcon(blank), f"☆ {k['score']:.1f}   {k['title']}\n"
                    f"{autoclip.fmt_time(k['start'])}–{autoclip.fmt_time(k['end'])}"
                    f" · {k['end'] - k['start']:.0f} с · " + ("удалён" if show_deleted else "кандидат"))
                it.setForeground(gray)
                it.setData(CARD, {"kind": "cand", "num": None, "score": float(k["score"]), "title": k["title"],
                                  "status": "deleted" if show_deleted else "candidate", "marks": False,
                                  "tags": "момент без видео",
                                  "meta": f"{autoclip.fmt_time(k['start'])}–{autoclip.fmt_time(k['end'])}"
                                          f" · {k['end'] - k['start']:.0f} с"})
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
        path = autoclip.cover_path_for(autoclip.cut_root(self.proj), c["file"])
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
        return os.path.join(autoclip.cut_root(self.proj), c["file"])

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
        self.cand_bar.setVisible(bool(k))
        if k:
            self.base = {}
            src = self.proj["source"]
            if os.path.isfile(src):
                self.player.show_at(src, k["start"] * 1000)
            else:
                self.player.clear()
            from html import escape
            self.btn_build.setEnabled(not self.busy and os.path.isfile(src) and not k.get("deleted"))
            self.btn_build.setVisible(not k.get("deleted"))
            self.btn_cand_play.setEnabled(os.path.isfile(src))
            self.btn_cand_del.setText("Вернуть" if k.get("deleted") else "Удалить кандидата")
            self.info_line.hide()
            self.info.show()
            self.info.setText(
                f"<b>{escape(k['title'])}</b> <span style='color:{MUTED}'>· кандидат, без видео</span><br>"
                f"{autoclip.fmt_time(k['start'])}–{autoclip.fmt_time(k['end'])}, оценка {k['score']:.1f}"
                + (f"<br><span style='color:{MUTED}'>{escape(k.get('text', ''))}</span>"
                   if k.get("text") else ""))
            return
        if not c:
            self.player.clear()
            self.info.setText("")
            self.info_line.hide()
            self.base = {}
            return
        path = self.clip_path(c)
        if os.path.isfile(path):
            self.player.open(path)
        else:
            self.player.clear()
        parts = ", ".join(f"{k} {v:+.1f}" for k, v in c.get("score_parts", {}).items()
                          if abs(v) >= 0.05)
        lines = []
        feats = c.get("features") or self.features(c)
        fc = None
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
                  f"Запикано: {c['bleeps'] if c['bleeps'] is not None else '-'}; "
                  + autoclip.clip_zooms(c, autoclip.clip_config(self.proj, c))[1]]
        if c.get("marks"):
            lines.append("📍 Метка из OBS: " + ", ".join(autoclip.fmt_time(t) for t in c["marks"]))
        if c.get("bounds_why"):
            lines.append("Границы — " + c["bounds_why"])
        ht = autoclip.hook_text(c)
        lines.append(ht[:1].upper() + ht[1:])
        if c.get("reason"):
            lines.append(f"Почему: {c['reason']}")
        self.info.setText("<br>".join(lines))
        self.info_line.setText((f"Прогноз {fc['value']:.1f}" if fc else "Подробнее") +
                               ("  ▴" if self.info_line.isChecked() else "  ▾"))
        self.info_line.show()
        self.info.setVisible(self.info_line.isChecked())
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

    # ---------- меню по правой кнопке ----------
    def clip_menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        if not it.isSelected():
            self.list.setCurrentItem(it)
        menu = self.build_menu()
        if menu:
            menu.exec(self.list.viewport().mapToGlobal(pos))

    def selected_clips(self):
        """Выбранные клипы (Ctrl/Shift), без кандидатов."""
        ids = {it.data(Qt.UserRole) for it in self.list.selectedItems()}
        return [c for c in (self.proj or {}).get("clips", []) if c["id"] in ids and c["status"] != "rejected"]

    def build_multi_menu(self, clips):
        """Действия сразу для нескольких клипов (5.15)."""
        n = len(clips)
        menu = QMenu(self)
        menu.addAction(f"Выложу ({n})", lambda: self.bulk_rate(clips, "post"))
        menu.addAction(f"Норм ({n})", lambda: self.bulk_rate(clips, "ok"))
        menu.addSeparator()
        for key, name in autoclip.PLATFORMS.items():
            menu.addAction(f"Выложил на {name} ({n})", lambda k=key: self.bulk_published(clips, k))
        tg = menu.addAction(f"Отправить в Telegram по очереди ({n})", lambda: self.bulk_telegram(clips))
        tg.setEnabled(telegram_bot.is_connected())
        menu.addAction(f"Пересобрать ({n})", lambda: self.bulk_rebuild(clips))
        menu.addAction("Показать в папке", lambda: show_in_folder(self.clip_path(clips[0])))
        menu.addSeparator()
        menu.addAction(f"Не то — в корзину ({n})", lambda: self.bulk_rate(clips, "bad"))
        menu.addAction(f"Удалить без оценки ({n})", lambda: self.bulk_remove(clips))
        return menu

    def _bulk(self, clips, fn, done_text):
        self.player.release_file()
        errors = []
        for c in clips:
            try:
                fn(c)
            except autoclip.AutoClipError as e:
                errors.append(f"{c['title']}: {e}")
        self.base = {}
        self.reload()
        self.state.setText(done_text if not errors else "Не со всеми вышло: " + "; ".join(errors)[:300])

    def bulk_rate(self, clips, rating):
        if rating == "bad":
            r = QMessageBox.question(self, "AutoClip", f"«Не то»: {len(clips)} клипов — в корзину Windows?")
            if r != QMessageBox.Yes:
                return
        self._bulk(clips, lambda c: autoclip.set_rating(self.proj["_path"], c["id"], rating),
                   f"Оценка у {len(clips)} клипов: {autoclip.RATINGS[rating]}")

    def bulk_published(self, clips, platform):
        self._bulk(clips, lambda c: autoclip.mark_published(self.proj["_path"], c["id"], platform, True),
                   f"Отмечено выложенными на {autoclip.PLATFORMS[platform]}: {len(clips)}")

    def bulk_remove(self, clips):
        r = QMessageBox.question(self, "AutoClip", f"Удалить {len(clips)} клипов без оценки?\n"
                                 "Файлы уйдут в корзину Windows, на обучение это не повлияет.")
        if r != QMessageBox.Yes:
            return
        self._bulk(clips, lambda c: autoclip.remove_clip(self.proj["_path"], c["id"]), f"Удалено: {len(clips)}")

    def bulk_telegram(self, clips):
        bus = self.win.bus
        items = [(self.clip_path(c), autoclip.clip_description(c, "tiktok", self.tag_cfg()), c["title"])
                 for c in clips]
        bus.send_state.emit(f"Telegram: в очереди {len(items)}")

        def job(bot):
            for k, (path, text, title) in enumerate(items, 1):
                try:
                    bot.send_clip(path, text, on_state=lambda t, k=k: bus.send_state.emit(
                        f"Telegram {k}/{len(items)}: {t}"))
                except autoclip.AutoClipError as e:
                    bus.send_state.emit(f"«{title}» не отправился: " + str(e).replace("❌ ", ""))
            bus.send_state.emit(f"Отправлено в Telegram: {len(items)} ✓")
        self.win.telegram.do(job)

    def bulk_rebuild(self, clips):
        if self.busy:
            return
        self.busy = True
        self.editor.setEnabled(False)
        self.player.release_file()
        pp, bus, ids = self.proj["_path"], self.win.bus, [c["id"] for c in clips]

        def work():
            err = None
            for k, cid in enumerate(ids, 1):
                bus.send_state.emit(f"Пересобираю {k} из {len(ids)}…")
                try:
                    autoclip.rebuild_clip(pp, cid)
                except autoclip.AutoClipError as e:
                    err = str(e)
            bus.rebuilt.emit(ids[0], err)
        threading.Thread(target=work, daemon=True).start()

    def build_menu(self):
        """Действия для выбранного клипа или кандидата (меню по правой кнопке)."""
        many = self.selected_clips()
        if len(many) > 1:
            return self.build_multi_menu(many)
        k = self.current_candidate()
        menu = QMenu(self)
        if k:
            menu.addAction("Просмотр", self.play_candidate)
            if not k.get("deleted"):
                menu.addAction("Собрать", self.build_candidate)
            menu.addAction("Вернуть" if k.get("deleted") else "Удалить кандидата", self.delete_candidate)
            return menu
        c = self.current_clip()
        if not c:
            return None
        path = self.clip_path(c)
        menu.addAction("Показать в папке", lambda: show_in_folder(path))
        menu.addAction("Открыть в плеере", lambda: open_path(path))
        tg = menu.addAction("Отправить в Telegram", self.send_to_telegram)
        tg.setEnabled(telegram_bot.is_connected() and os.path.isfile(path))
        if not tg.isEnabled():
            tg.setToolTip("Подключи бота в «Настройках» → «Telegram»")
        menu.addSeparator()
        menu.addAction("Переименовать", self.rename_clip)
        menu.addAction("Пересобрать", self.rebuild)
        menu.addAction("Выложу", lambda: self.rate("post"))
        menu.addAction("Норм", lambda: self.rate("ok"))
        menu.addSeparator()
        menu.addAction("Не то (в корзину)", self.to_trash)
        menu.addAction("Удалить (без оценки)", self.remove_clip)
        return menu

    def rename_clip(self):
        self.show_tab(1)                                    # «Текст» — там название
        self.t_title.setFocus()
        self.t_title.selectAll()

    def remove_clip(self):
        c = self.current_clip()
        if not c:
            return
        r = QMessageBox.question(self, "AutoClip", f"Удалить клип «{c['title']}» без оценки?\n"
                                 "Файл уйдёт в корзину Windows, на обучение это не повлияет.")
        if r != QMessageBox.Yes:
            return
        row = self.list.currentRow()
        self.player.release_file()
        try:
            autoclip.remove_clip(self.proj["_path"], c["id"])
        except autoclip.AutoClipError as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            return
        self.base = {}
        self.reload()
        if self.list.count():
            self.list.setCurrentRow(min(row, self.list.count() - 1))

    def send_to_telegram(self):
        c = self.current_clip()
        if not c:
            return
        path = self.clip_path(c)
        text = autoclip.clip_description(c, "tiktok", self.tag_cfg())
        bus = self.win.bus
        bus.send_state.emit("Telegram: готовлю…")

        def job(bot):
            try:
                light = bot.send_clip(path, text, on_state=lambda t: bus.send_state.emit("Telegram: " + t))
                bus.send_state.emit("Отправлено в Telegram" + (" (облегчённая копия)" if light else "") + " ✓")
            except autoclip.AutoClipError as e:
                bus.send_state.emit("Не отправилось: " + str(e).replace("❌ ", ""))
        self.win.telegram.do(job)

    # ---------- текст: слова субтитров, мат, название ----------
    def _build_text_tab(self):
        from PySide6.QtWidgets import QTableWidget, QHeaderView
        page = QWidget()
        tl = QVBoxLayout(page)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(QLabel("Название"))
        self.t_title = QLineEdit()
        self.t_title.setPlaceholderText("Название клипа — оно же в имени файла после «Пересобрать»")
        self.t_title.textEdited.connect(self._changed)
        row.addWidget(self.t_title, 1)
        tl.addLayout(row)
        tl.addWidget(hint("Двойной клик по слову — исправить. Галочка «мат» — закрыть звуком; "
                          "снять — если запикано зря. Пустое слово уберётся из субтитров."))
        self.t_words = QTableWidget(0, 3)
        self.t_words.setHorizontalHeaderLabels(["Время", "Слово", "Мат"])
        self.t_words.verticalHeader().setVisible(False)
        self.t_words.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.t_words.setMinimumHeight(150)
        self.t_words.itemChanged.connect(self._word_changed)
        tl.addWidget(self.t_words, 1)
        row = QHBoxLayout()
        b = QPushButton("Добавить слово здесь")
        b.setToolTip("Слово, которого нет в субтитрах (например, мат, который слышно), — на месте "
                     "просмотра. Мат замаскируется и закроется звуком сам")
        b.clicked.connect(self.add_word_here)
        row.addWidget(b)
        row.addStretch(1)
        tl.addLayout(row)
        # вкладки: Клип, Текст, Описание, Публикация, Музыка
        self.ed_stack.insertWidget(1, page)
        self.w_edit, self.m_words, self.w_add = {}, [], []

    def add_word_here(self):
        c = self.current_clip()
        if not c:
            return
        from PySide6.QtWidgets import QInputDialog
        t = self.rec_at_player(c)
        text, ok = QInputDialog.getText(self, "AutoClip", f"Слово на {autoclip.fmt_time_exact(t)}:")
        if not ok or not text.strip():
            return
        a, b = autoclip.word_span_at(self.proj["source"], t)
        self.w_add.append([a, b, text.strip()])
        self.fill_words(c)
        self.refresh_bleeps()
        self._changed()

    def fill_words(self, c):
        from PySide6.QtWidgets import QTableWidgetItem
        self._filling_words = True
        self.t_words.setRowCount(0)
        for w in autoclip.clip_words(self.segments() or [], c["start"], c["end"]):
            src = round(c["start"] + w["s"], 2)
            key = next((k for k in self.w_edit if abs(float(k) - src) < 0.06), None)
            text = self.w_edit[key] if key is not None else w["w"]
            auto = autoclip.is_profane(w["w"])
            on = (auto and not any(abs(src - t) < 0.06 for t in self.b_rem)) or \
                any(abs(src - t) < 0.06 for t in self.m_words)
            r = self.t_words.rowCount()
            self.t_words.insertRow(r)
            ti = QTableWidgetItem(autoclip.fmt_time_exact(src))
            ti.setFlags(Qt.ItemIsEnabled)
            ti.setData(Qt.UserRole, (src, w["w"], auto))
            self.t_words.setItem(r, 0, ti)
            self.t_words.setItem(r, 1, QTableWidgetItem(text))
            mi = QTableWidgetItem("")
            mi.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            mi.setCheckState(Qt.Checked if on else Qt.Unchecked)
            self.t_words.setItem(r, 2, mi)
        for i, (a, b, text) in enumerate(self.w_add):            # добавленные вручную (5.8)
            r = self.t_words.rowCount()
            self.t_words.insertRow(r)
            ti = QTableWidgetItem(autoclip.fmt_time_exact(a) + " +")
            ti.setFlags(Qt.ItemIsEnabled)
            ti.setToolTip("Добавлено вручную. Сотри слово — уберётся")
            ti.setData(Qt.UserRole, ("add", i, None))
            self.t_words.setItem(r, 0, ti)
            self.t_words.setItem(r, 1, QTableWidgetItem(text))
            mi = QTableWidgetItem("мат" if autoclip.is_profane(text) else "")
            mi.setFlags(Qt.ItemIsEnabled)
            self.t_words.setItem(r, 2, mi)
        self._filling_words = False

    def _word_changed(self, item):
        if getattr(self, "_filling_words", False):
            return
        src, orig, auto = self.t_words.item(item.row(), 0).data(Qt.UserRole)
        if src == "add":                                          # добавленное вручную слово
            if item.column() == 1:
                text = item.text().strip()
                if text:
                    self.w_add[orig][2] = text
                else:
                    self.w_add.pop(orig)
                    QTimer.singleShot(0, lambda: self.fill_words(self.current_clip()))
                self.refresh_bleeps()
                self._changed()
            return
        if item.column() == 1:
            text = item.text().strip()
            self.w_edit = {k: v for k, v in self.w_edit.items() if abs(float(k) - src) >= 0.06}
            if text != orig:
                self.w_edit[f"{src:.2f}"] = text
        elif item.column() == 2:
            on = item.checkState() == Qt.Checked
            self.b_rem = [t for t in self.b_rem if abs(t - src) >= 0.06]
            self.m_words = [t for t in self.m_words if abs(t - src) >= 0.06]
            if auto and not on:
                self.b_rem.append(src)                  # «не мат» — снять писк
            elif on and not auto:
                self.m_words.append(src)                # «это мат» — фильтр пропустил
            self.refresh_bleeps()
        self._changed()

    # ---------- хук: ручная подстройка ----------
    def show_hook(self):
        h = self.hook_at
        self.h_label.setText(f"{autoclip.fmt_time_exact(h[0])} – {autoclip.fmt_time_exact(h[1])}"
                             f"  ({h[1] - h[0]:.2f} с)" if h else "места для хука нет")
        for b in self.hook_btns:
            b.setEnabled(h is not None)

    def _set_hook(self, hs, he):
        c = self.current_clip()
        if not c:
            return
        hs, he = round(max(c["start"], hs), 2), round(min(c["end"], he), 2)   # только из этого клипа
        if he - hs < 0.5:
            return
        self.hook_at = [hs, he]
        if self.e_hook.currentData() != "on":
            self.e_hook.setCurrentIndex(self.e_hook.findData("on"))   # выбрал хук — значит, он нужен
        self.show_hook()
        self._changed()

    def hook_shift(self, side, d):
        if not self.hook_at:
            return
        h = list(self.hook_at)
        h[side] += d
        self._set_hook(*h)

    def hook_here(self):
        c = self.current_clip()
        if not c:
            return
        t = self.rec_at_player(c)
        hs, he = autoclip.hook_window_at(self.segments() or [], c["start"], c["end"], t)
        if hs is None:
            self.state.setText("Тут хук не поставить: слова идут без пауз")
            return
        self._set_hook(hs, he)

    def hook_preview(self):
        c = self.current_clip()
        if not (c and self.hook_at) or not os.path.isfile(self.proj["source"]):
            return
        self.player.play_range(self.proj["source"], self.hook_at[0] * 1000, self.hook_at[1] * 1000)

    def shuffle_sounds(self):
        import random
        self.bleep_seed = random.randint(1, 10 ** 9)
        self._changed()

    # ---------- вырезки ----------
    def rec_at_player(self, c):
        """Место просмотра → время в записи (в готовом клипе могут быть хук и вырезки)."""
        t = self.player.player.position() / 1000
        tl = autoclip.rendered_timeline(c)
        if tl and tl[0][3] == 0 and t < tl[0][1] - tl[0][0]:
            t = tl[0][1] - tl[0][0]                    # внутри хука — считаем с начала клипа
        return min(c["end"], max(c["start"], autoclip.out_to_rec(t, tl)))

    def show_cuts(self):
        a, b = self.cut_ab
        f = autoclip.fmt_time_exact
        if a is not None or b is not None:
            self.cut_info.setText(f"кусок {f(a) if a is not None else '…'} – {f(b) if b is not None else '…'}")
        elif self.cuts:
            n = len(self.cuts)
            self.cut_info.setText(f"вырезано кусков: {n}")
        else:
            self.cut_info.setText("выдели кусок на таймлайне")
        self.btn_cut.setEnabled(a is not None and b is not None and b - a >= 0.1)
        self.btn_cuts_reset.setEnabled(bool(self.cuts))
        self.tl_refresh()

    def cut_mark(self, side):
        c = self.current_clip()
        if not c:
            return
        self.cut_ab[side] = round(self.rec_at_player(c), 2)
        a, b = self.cut_ab
        if a is not None and b is not None and b < a:
            self.cut_ab = [b, a]
        self.show_cuts()

    def cut_piece(self):
        a, b = self.cut_ab
        if a is None or b is None:
            return
        self.cuts = autoclip.merge_cuts(self.cuts + [[a, b]])
        self.cut_ab = [None, None]
        self.show_cuts()
        self._changed()

    def cuts_reset(self):
        self.cuts, self.cut_ab = [], [None, None]
        self.show_cuts()
        self.pause_info.setText("")
        self._changed()

    def _pause_cuts(self):
        c = self.current_clip()
        now = self.edited()
        if not c or now["start"] is None or now["end"] is None:
            return None
        key = (c["id"], now["start"], now["end"])
        if key not in self._voice:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._voice[key] = (autoclip.clip_voice(self.proj["source"], now["start"], now["end"])
                                    if os.path.isfile(self.proj["source"]) else [])
            finally:
                QApplication.restoreOverrideCursor()
        return autoclip.suggest_pause_cuts(self.proj["_path"], c["id"], self.pause_len.value(),
                                           autoclip.PAUSE_KEEP, now["start"], now["end"], self.cuts,
                                           self._voice[key], self.segments() or [])

    def pause_preview(self, *_):
        r = self._pause_cuts()
        if r is None:
            return
        self.pause_info.setText(f"будет короче на {r[1]:.1f} с" if r[1] > 0.05 else "таких пауз нет")

    def squeeze_pauses(self):
        r = self._pause_cuts()
        if r is None:
            return
        cuts, less = r
        if less <= 0.05:
            self.pause_info.setText("таких пауз нет")
            return
        self.cuts = cuts
        self.pause_info.setText(f"станет короче на {less:.1f} с — нажми «Пересобрать»")
        self.show_cuts()
        self._changed()

    def split_here(self):
        c = self.current_clip()
        if not c or self.busy:
            return
        if self.pending():
            self.win.toast("Сначала пересобери клип или отмени правки.")
            return
        t = self.rec_at_player(c)
        words = autoclip.all_words(self.segments() or [])
        at = autoclip.split_point(t, c["start"], c["end"], words)
        if at is None or at - c["start"] < 3 or c["end"] - at < 3:
            self.state.setText("Тут не разбить: обе части — не короче 3 с, граница — в паузе")
            return
        self.busy = True
        self.editor.setEnabled(False)
        self.state.setText("Разбиваю на два клипа…")
        self.player.release_file()
        cid, pp, bus = c["id"], self.proj["_path"], self.win.bus

        def work():
            try:
                autoclip.split_clip(pp, cid, at)
                bus.rebuilt.emit(cid, None)
            except autoclip.AutoClipError as e:
                bus.rebuilt.emit(cid, str(e))
            except Exception:
                bus.rebuilt.emit(cid, "❌ " + traceback.format_exc()[-800:])
        threading.Thread(target=work, daemon=True).start()

    # ---------- ручной писк ----------
    def hook_len(self, c):
        h = c.get("hook") or {}
        return (h["end"] - h["start"]) if h.get("on") and h.get("start") is not None else 0.0

    def refresh_bleeps(self):
        """Список писков клипа: по фильтру, снятые и добавленные вручную."""
        c = self.current_clip()
        self.e_bleeps.clear()
        if not c:
            return
        segs = self.segments() or []
        for w in autoclip.clip_words(segs, c["start"], c["end"]):
            t = c["start"] + w["s"]
            if not autoclip.is_profane(w["w"]):
                continue
            off = any(abs(t - x) < 0.06 for x in self.b_rem)
            label = (f"{autoclip.fmt_time_exact(t)}  «{autoclip.censor_word(w['w'])}»  — "
                     + ("писк снят" if off else "по фильтру"))
            self.e_bleeps.addItem(label, ("rem", round(t, 2)))
        for i, (a, b) in enumerate(self.b_add):
            self.e_bleeps.addItem(f"{autoclip.fmt_time_exact(a)}–{autoclip.fmt_time_exact(b)}  — вручную",
                                  ("add", i))
        if not self.e_bleeps.count():
            self.e_bleeps.addItem("мата в клипе нет", None)

    def bleep_here(self):
        """Полсекунды писка на месте просмотра (время — в записи, переживёт пересборку)."""
        c = self.current_clip()
        if not c:
            return
        rec = self.rec_at_player(c)
        self.b_add.append([round(max(c["start"], rec - 0.1), 2), round(min(c["end"], rec + 0.4), 2)])
        self.refresh_bleeps()
        self._changed()

    def bleep_toggle(self):
        d = self.e_bleeps.currentData()
        if not d:
            return
        kind, x = d
        if kind == "add":
            self.b_add.pop(x)
        elif any(abs(x - t) < 0.06 for t in self.b_rem):
            self.b_rem = [t for t in self.b_rem if abs(x - t) >= 0.06]     # вернуть писк
        else:
            self.b_rem.append(x)
        self.refresh_bleeps()
        self._changed()

    # ---------- музыка ----------
    def fill_tracks(self, *_):
        self.m_list.clear()
        folder = self.win.settings.get("music_dir", "")
        if not folder:
            it = QListWidgetItem("Папка «Музыка» не выбрана — «Настройки» → «Музыка»")
            it.setFlags(Qt.NoItemFlags)
            self.m_list.addItem(it)
            return
        for path in autoclip.list_music(folder, self.m_search.text()):
            it = QListWidgetItem(os.path.relpath(path, folder))
            it.setData(Qt.UserRole, path)
            self.m_list.addItem(it)

    def pick_track(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Трек", self.win.settings.get("music_dir", ""),
            "Музыка (" + " ".join("*" + e for e in autoclip.MUSIC_EXT) + ")")
        if path:
            self.set_track(path)

    def wave(self, path):
        key = (path, os.path.getmtime(path) if os.path.exists(path) else 0)
        if key not in self._waves:
            try:
                self._waves[key] = autoclip.waveform(path, 400)
            except autoclip.AutoClipError:
                self._waves[key] = ([], 0.0)
        return self._waves[key]

    def clip_len(self):
        c = self.current_clip()
        if not c:
            return 0.0
        return autoclip.timeline_len(autoclip.rendered_timeline(c))   # с хуком и без вырезок

    def set_track(self, path):
        if path is None:
            self.music = None
        else:
            old = self.music or {}
            self.music = dict(autoclip.MUSIC_DEFAULT, file=path, offset=0.0,
                              volume=old.get("volume", -18.0), duck=old.get("duck", True),
                              fade=old.get("fade", 1.0))
        self.show_music()
        self._changed()

    def _music_set(self, **kw):
        if self.music is None or getattr(self, "_filling_music", False):
            return
        self.music.update(kw)
        self._changed()

    def show_music(self):
        m = self.music
        self._filling_music = True
        for w in (self.m_vol, self.m_duck, self.m_fade, self.m_listen, self.m_wave):
            w.setEnabled(m is not None)
        if m:
            peaks, dur = self.wave(m["file"])
            self.m_wave.set_track(peaks, dur)
            self.m_wave.set_window(self.clip_len(), m.get("offset", 0))
            self.m_name.setText(f"♪ {os.path.basename(m['file'])}  ·  с {autoclip.fmt_time(m.get('offset', 0))}")
            self.m_vol.setValue(int(round(m.get("volume", -18))))
            self.m_duck.setChecked(bool(m.get("duck", True)))
            self.m_fade.setValue(int(round(m.get("fade", 1))))
        else:
            self.m_wave.set_track([], 0)
            self.m_name.setText("Без музыки")
        self._filling_music = False

    def listen_music(self):
        c = self.current_clip()
        if not (c and self.music):
            return
        self.m_state.setText("Смешиваю…")
        self.m_listen.setEnabled(False)
        self.player.release_file()
        pp, cid, m, bus = self.proj["_path"], c["id"], dict(self.music), self.win.bus
        out = os.path.join(tempfile.gettempdir(), f"autoclip_music_{os.getpid()}.mp4")

        def work():
            try:
                bus.music_ready.emit(autoclip.music_preview(pp, cid, m, out), None)
            except autoclip.AutoClipError as e:
                bus.music_ready.emit("", str(e))
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _music_ready(self, path, err):
        self.m_listen.setEnabled(self.music is not None)
        self.m_state.setText(err or "Играет клип с музыкой. В сам клип — после «Пересобрать».")
        if path and not err:
            self.player.open(path, autoplay=True)

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

    def play_candidate(self):
        k = self.current_candidate()
        if k and os.path.isfile(self.proj["source"]):
            self.player.play_range(self.proj["source"], k["start"] * 1000, k["end"] * 1000)

    def delete_candidate(self):
        k = self.current_candidate()
        if not k:
            return
        row = self.list.currentRow()
        try:
            autoclip.set_candidate_deleted(self.proj["_path"], k["id"], not k.get("deleted"))
        except autoclip.AutoClipError as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            return
        self.reload()
        if self.list.count():
            self.list.setCurrentRow(min(row, self.list.count() - 1))
        self.win.retrain()                              # удалённый кандидат — слабое «не нравится»

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
        self.base = {"hook": cfg["hook"], "zoom": cfg["zoom"],
                     "bleep": bool(cfg["bleep"]), "subs": bool(cfg["subs"]),
                     "sub_y": autoclip.SUB_POSITIONS[autoclip.sub_position_name(cfg["sub_y"])],
                     "safe_zone": bool(cfg.get("safe_zone")), "bleep_sound": cfg["bleep_sound"],
                     "nick": bool(cfg.get("nick")),
                     "censor": "full" if cfg.get("censor") == "full" else "partial",
                     "bleep_seed": (c.get("overrides") or {}).get("bleep_seed"),
                     "style": (c.get("overrides") or {}).get("sub_style") or "",
                     "music": (c.get("overrides") or {}).get("music"),
                     "bleep_add": list((c.get("overrides") or {}).get("bleep_add") or []),
                     "hook_at": (c.get("overrides") or {}).get("hook_at"),
                     "words_edit": dict((c.get("overrides") or {}).get("words_edit") or {}),
                     "mat_words": list((c.get("overrides") or {}).get("mat_words") or []),
                     "words_add": [list(x) for x in (c.get("overrides") or {}).get("words_add") or []],
                     "title": (c.get("overrides") or {}).get("title") or c["title"],
                     "bleep_remove": list((c.get("overrides") or {}).get("bleep_remove") or []),
                     "cuts": [list(x) for x in (c.get("overrides") or {}).get("cuts") or []],
                     "start": round(c["start"], 1), "end": round(c["end"], 1)}
        widgets = (self.e_hook, self.e_zoom, self.e_bleep, self.e_subs, self.e_pos, self.e_safe,
                   self.e_start, self.e_end, self.e_sound, self.e_nick, self.e_style, self.e_censor)
        for w in widgets:
            w.blockSignals(True)
        fill_sounds(self.e_sound, cfg["bleep_sound"])
        self.e_style.clear()
        self.e_style.addItem("как у нарезки", "")
        for st in autoclip.load_styles():
            self.e_style.addItem(st["name"], st["name"])
        if self.base["style"] and self.e_style.findData(self.base["style"]) < 0:
            self.e_style.addItem(self.base["style"], self.base["style"])   # стиль потом удалили
        self.e_style.setCurrentIndex(max(0, self.e_style.findData(self.base["style"])))
        b = self.base
        self.e_hook.setCurrentIndex(max(0, self.e_hook.findData(b["hook"])))
        self.e_zoom.setCurrentIndex(max(0, self.e_zoom.findData(b["zoom"])))
        self.e_bleep.setChecked(b["bleep"])
        self.e_subs.setChecked(b["subs"])
        self.e_pos.setCurrentText(autoclip.sub_position_name(b["sub_y"]))
        self.e_safe.setChecked(b["safe_zone"])
        self.e_nick.setChecked(b["nick"])
        self.e_censor.setCurrentIndex(max(0, self.e_censor.findData(b["censor"])))
        self.bleep_seed = b["bleep_seed"]
        self.btn_shuffle.setVisible(self.e_sound.currentText() == autoclip.RANDOM_SOUND)
        self.e_pos.setEnabled(b["subs"])
        self.e_safe.setEnabled(b["subs"])
        self.e_sound.setEnabled(b["bleep"])
        for w in (self.e_bleep, self.e_subs, self.e_safe, self.e_nick):
            w.update()
        self.e_start.setText(autoclip.fmt_time_exact(b["start"]))
        self.e_end.setText(autoclip.fmt_time_exact(b["end"]))
        for w in widgets:
            w.blockSignals(False)
        self.music = dict(self.base["music"]) if self.base.get("music") else None
        self.b_add = [list(x) for x in self.base["bleep_add"]]
        h = c.get("hook") or {}
        self.hook_at = (list(self.base["hook_at"]) if self.base.get("hook_at") else
                        ([h["start"], h["end"]] if h.get("start") is not None else None))
        self.base["hook_at"] = list(self.hook_at) if self.hook_at else None   # показанный — не правка
        self.show_hook()
        self.b_rem = list(self.base["bleep_remove"])
        self.cuts = [list(x) for x in self.base["cuts"]]
        self.cut_ab = [None, None]
        self.show_cuts()
        self.w_edit = dict(self.base["words_edit"])
        self.w_add = [list(x) for x in self.base["words_add"]]
        self.m_words = list(self.base["mat_words"])
        self.t_title.setText(self.base["title"])
        self.e_title.setText(self.base["title"])
        self._undo = []
        self.tl.set_clip(c["start"], c["end"], (self.proj.get("source_info") or {}).get("dur", c["end"] + 30))
        self.load_wave(c)
        self.fill_words(c)
        self.refresh_bleeps()
        self.fill_tracks()
        self.show_music()
        self.btn_good.setChecked(c.get("rating") == "post")
        self.btn_ok.setChecked(c.get("rating") == "ok")
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
        return {"hook": self.e_hook.currentData(), "zoom": self.e_zoom.currentData(),
                "bleep": self.e_bleep.isChecked(), "subs": self.e_subs.isChecked(),
                "sub_y": autoclip.SUB_POSITIONS[self.e_pos.currentText()],
                "safe_zone": self.e_safe.isChecked(), "bleep_sound": self.e_sound.currentText(),
                "nick": self.e_nick.isChecked(),
                "censor": self.e_censor.currentData(),
                "bleep_seed": self.bleep_seed,
                "style": self.e_style.currentData() or "",
                "music": dict(self.music) if self.music else None,
                "bleep_add": [list(x) for x in self.b_add],
                "hook_at": list(self.hook_at) if self.hook_at else None,
                "words_edit": dict(self.w_edit),
                "words_add": [list(x) for x in self.w_add],
                "mat_words": list(self.m_words),
                "title": self.t_title.text().strip() or (self.base or {}).get("title", ""),
                "bleep_remove": list(self.b_rem),
                "cuts": [list(x) for x in self.cuts],
                "start": self._time(self.e_start), "end": self._time(self.e_end)}

    def pending(self):
        """Что поменяли в редакторе и ещё не пересобрали."""
        if not self.base:
            return {}
        now = self.edited()
        return {k: v for k, v in now.items() if v != self.base.get(k)}

    # ---------- таймлайн (5.17) ----------
    def tl_refresh(self):
        """Слои таймлайна по нынешнему (ещё не пересобранному) состоянию редактора."""
        c = self.current_clip()
        if not c or not hasattr(self, "tl"):
            return
        now = self.edited()
        if now["start"] is not None and now["end"] is not None:
            self.tl.set_bounds(now["start"], now["end"])
        segs = self.segments() or []
        words = [w for seg in segs for w in seg.get("words", [])
                 if self.tl.view[0] <= w["s"] <= self.tl.view[1]]
        bleeps = []
        for w in words:
            if autoclip.is_profane(w["w"]):
                off = any(abs(w["s"] - t) < 0.06 for t in self.b_rem)
                bleeps.append((w["s"], w["e"], off))
        bleeps += [(a, b, False) for a, b in self.b_add]
        bleeps += [(a, b, False) for a, b, t in self.w_add if autoclip.is_profane(t)]
        try:
            zooms = autoclip.clip_zooms(c, autoclip.clip_config(self.proj, c))[0]
        except Exception:
            zooms = []
        dead = self.proj.get("dead_runs")
        if dead is None:
            dead = getattr(self, "_dead_est", {}).get(c["id"], [])     # старая нарезка — по громкости
        self.tl.set_layers(hook=self.hook_at, bleeps=bleeps, cuts=self.cuts, marks=c.get("marks") or [],
                           zooms=zooms, words=[(w["s"], w["e"], w["w"]) for w in words], dead=dead)

    def load_wave(self, c):
        """Волна звука записи вокруг клипа — в фоне (ffmpeg), чтобы окно не подвисало."""
        src = self.proj.get("source", "")
        if not os.path.isfile(src):
            self.tl.set_wave([])
            return
        a = max(0.0, c["start"] - 30.0)
        b = c["end"] + 30.0
        cid = c["id"]
        spans = [(w["s"], w["e"]) for seg in (self.segments() or []) for w in seg.get("words", [])
                 if w["e"] > a and w["s"] < b]
        need_dead = self.proj.get("dead_runs") is None

        def work():
            try:
                import numpy as np
                p = autoclip.run(["ffmpeg", "-v", "error", "-ss", f"{a:.2f}", "-t", f"{b - a:.2f}", "-i", src,
                                  "-map", "0:a:0", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], binary=True)
                x = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768
                from timeline import estimate_dead, wave_of
                dead = estimate_dead(x, a, spans) if need_dead else None
                self.wave_ready.emit(cid, (wave_of(x, a), dead))
            except Exception:
                self.wave_ready.emit(cid, ([], None))
        threading.Thread(target=work, daemon=True).start()

    def _wave_ready(self, cid, data):
        wave, dead = data
        if dead is not None:
            self._dead_est = getattr(self, "_dead_est", {})
            self._dead_est[cid] = dead
        c = self.current_clip()
        if c and c["id"] == cid:
            self.tl.set_wave(wave)
            self.tl_refresh()

    def _snapshot(self):
        return {"start": self.e_start.text(), "end": self.e_end.text(),
                "hook_at": list(self.hook_at) if self.hook_at else None,
                "cuts": [list(x) for x in self.cuts], "b_add": [list(x) for x in self.b_add],
                "b_rem": list(self.b_rem), "w_add": [list(x) for x in self.w_add]}

    def push_undo(self):
        self._undo.append(self._snapshot())
        del self._undo[:-50]

    def undo(self):
        """Ctrl+Z — отменить последнюю правку на таймлайне (до «Пересобрать»)."""
        if not self._undo:
            return
        st = self._undo.pop()
        self.e_start.setText(st["start"])
        self.e_end.setText(st["end"])
        self.hook_at = st["hook_at"]
        self.cuts, self.b_add, self.b_rem, self.w_add = st["cuts"], st["b_add"], st["b_rem"], st["w_add"]
        self.show_hook()
        self.show_cuts()
        self.refresh_bleeps()
        self._changed()

    def _tl_bounds(self, s, e):
        self.push_undo()
        self.e_start.setText(autoclip.fmt_time_exact(s))
        self.e_end.setText(autoclip.fmt_time_exact(e))

    def _tl_hook(self, hs, he):
        self.push_undo()
        self._set_hook(hs, he)
        self.tl_refresh()

    def _tl_seek(self, t):
        """Клик по таймлайну — перемотка просмотра на это место записи."""
        c = self.current_clip()
        if not c:
            return
        tl = autoclip.rendered_timeline(c)
        out = autoclip.rec_to_out(t, tl)
        if out is None:                                    # вырезано или вне клипа — ближайший край
            out = 0.0 if t < c["start"] else autoclip.timeline_len(tl)
            for a, b, o, part in tl:
                if part and t < a:
                    out = o
                    break
        self.player.player.setPosition(int(out * 1000))
        self.tl.set_playhead(t)

    def _tl_playhead(self, ms):
        c = self.current_clip()
        if c and hasattr(self, "tl"):
            try:
                self.tl.set_playhead(autoclip.out_to_rec(ms / 1000, autoclip.rendered_timeline(c)))
            except Exception:
                pass

    def _tl_selection(self, a, b):
        self.cut_ab = [None, None] if a < 0 else [a, b]
        self.show_cuts()

    def _tl_bleep(self, t):
        """Клик по писку на таймлайне: автоматический — убрать/вернуть, ручной — убрать."""
        self.push_undo()
        for i, (a, b) in enumerate(self.b_add):
            if a - 0.05 <= t <= b + 0.05:
                self.b_add.pop(i)
                break
        else:
            if any(abs(x - t) < 0.06 for x in self.b_rem):
                self.b_rem = [x for x in self.b_rem if abs(x - t) >= 0.06]
            else:
                self.b_rem.append(round(t, 2))
        self.refresh_bleeps()
        self._changed()
        self.tl_refresh()

    def _title_edited(self, text):
        self.t_title.setText(text)
        self._changed()

    def _toggle_info(self, on):
        self.info.setVisible(on)
        t = self.info_line.text().rstrip(" ▾▴")
        self.info_line.setText(t + ("  ▴" if on else "  ▾"))

    def _toggle_more(self, on):
        self.more.setVisible(on)
        theme.set_icon(self.btn_more, "chevron-down" if on else "chevron-right", MUTED, 14)

    def _shortcuts(self):
        """Горячие клавиши редактора (5.17)."""
        keys = (("I", lambda: self._key_bound(0)), ("O", lambda: self._key_bound(1)),
                ("X", self._key_cut), ("H", self.hook_here), ("B", self.bleep_here),
                ("W", self.add_word_here), ("G", lambda: self.rate("post")), ("N", lambda: self.rate("ok")),
                ("D", self.to_trash), ("Ctrl+Z", self.undo))
        for key, fn in keys:
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda fn=fn: None if self._typing() else fn())
        self.player.player.positionChanged.connect(self._tl_playhead)
        self.wave_ready.connect(self._wave_ready)

    def _typing(self):
        """В поле ввода буквы — это текст, а не команды."""
        w = QApplication.focusWidget()
        return isinstance(w, (QLineEdit, QPlainTextEdit)) or type(w).__name__ in ("QTableWidget",)

    def _key_bound(self, side):
        c = self.current_clip()
        if not c:
            return
        self.push_undo()
        t = self.rec_at_player(c) if self.tl.playhead is None else self.tl.playhead
        (self.e_start if side == 0 else self.e_end).setText(autoclip.fmt_time_exact(t))

    def _key_cut(self):
        if self.cut_ab[0] is not None and self.cut_ab[1] is not None:
            self.push_undo()
            self.cut_piece()
            self.tl.clear_selection()

    def _changed(self, *_):
        now = self.edited()
        bad = now["start"] is None or now["end"] is None
        for edit, val in ((self.e_start, now["start"]), (self.e_end, now["end"])):
            edit.setStyleSheet("border: 1px solid #ff4f6d;" if val is None else "")
        if not bad:
            ln = now["end"] - now["start"]
            left = sum(b - a for a, b in autoclip.keep_pieces(now["start"], now["end"], now["cuts"]))
            self.e_len.setText((f"длина {left:.1f} с" + (f" (вырезано {ln - left:.1f} с)" if ln - left > 0.05 else ""))
                               if ln > 0 else "конец раньше начала")
        if self.busy:
            return
        p = self.pending()
        self.tl_refresh()
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
        if self.ed_stack.currentIndex() != i:
            self.ed_stack.setCurrentIndex(i)
            fade_in(self.ed_stack.currentWidget(), 180)       # плавная смена вкладки

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
            mark.setText("Снять отметку" if p else f"Выложил на {autoclip.PLATFORMS[key]}")

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
        try:
            autoclip.mark_published(self.proj["_path"], c["id"], platform, on)
        except autoclip.AutoClipError as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            return
        self.base = {}
        self.reload(c["id"])
        self.show_tab(3)                          # «Публикация»

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
        overrides = {k: (v if v not in ({}, [], "") else None) for k, v in p.items()
                     if k in autoclip.OVERRIDE_KEYS}
        if "style" in p:                              # свой стиль — все его значения клипу
            st = autoclip.get_style(p["style"]) if p["style"] else None
            overrides.update({k: (st[k] if st else None) for k in autoclip.STYLE_KEYS})
            overrides["sub_style"] = st["name"] if st else None
        start = now["start"] if "start" in p else None
        end = now["end"] if "end" in p else None
        self.busy = True
        self.editor.setEnabled(False)
        self.state.setText("Пересобираю…")
        self.player.release_file()               # иначе Windows не даст заменить файл
        cid, pp = c["id"], self.proj["_path"]
        bus = self.win.bus
        self._reta = autoclip.Eta()

        def work():
            try:
                autoclip.rebuild_clip(pp, cid, start, end, overrides,
                                      progress=lambda st, pct, msg: bus.rebuild_progress.emit(float(pct)))
                bus.rebuilt.emit(cid, None)
            except autoclip.AutoClipError as e:
                bus.rebuilt.emit(cid, str(e))
            except Exception:
                bus.rebuilt.emit(cid, "❌ " + traceback.format_exc()[-800:])
        threading.Thread(target=work, daemon=True).start()

    def _rebuild_progress(self, pct):
        if not self.busy:
            return
        left = self._reta.update(pct / 100) if getattr(self, "_reta", None) else None
        self.state.setText(f"Пересобираю… {pct:.0f}%" + (f" · {autoclip.fmt_left(left)}" if left is not None else ""))

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
        self.rate("post")

    def rate(self, rating):
        """«Выложу» / «Норм»; повторное нажатие снимает оценку."""
        c = self.current_clip()
        if not c:
            return
        try:
            autoclip.set_rating(self.proj["_path"], c["id"], None if c.get("rating") == rating else rating)
        except autoclip.AutoClipError as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            return
        self.base = {}
        self.reload(c["id"])

    def to_trash(self):
        c = self.current_clip()
        if not c:
            return
        r = QMessageBox.question(self, "AutoClip", f"«Не то»: клип «{c['title']}» — в корзину?\n"
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
        self._lay = lay
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
            b.setMinimumWidth(text_width(text, 13) + 34)
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
        self.cb_used = QCheckBox("Показывать и уже использованные")
        self.cb_used.setToolTip("Клипы, которые уже были в собранной подборке, сами в новую не попадают")
        self.cb_used.setChecked(bool(self.s.get("weekly_show_used", False)))
        self.cb_used.toggled.connect(lambda v: (self.s.__setitem__("weekly_show_used", bool(v)),
                                                save_settings(self.s), self.refresh()))
        row.addWidget(self.cb_used, 0, Qt.AlignBottom)
        b = QPushButton("Очистить")
        b.setToolTip("Убрать все клипы из текущей подборки (снять отметки)")
        b.clicked.connect(self.clear_all)
        row.addWidget(b, 0, Qt.AlignBottom)
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
        self.up = QPushButton()
        self.down = QPushButton()
        theme.set_icon(self.up, "arrow-up", FG, 16)
        theme.set_icon(self.down, "arrow-down", FG, 16)
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
        el.addWidget(icon_label("layers", ACCENT, 28, 64), 0, Qt.AlignCenter)
        el.addSpacing(8)
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
        self.btn = QPushButton("Собрать подборку")
        theme.set_icon(self.btn, "clapperboard", "#ffffff", 20)
        glow_button(self.btn, 26, 100)
        self.btn.setObjectName("accent")
        self.btn.setMinimumWidth(260)
        self.btn.clicked.connect(self.build)
        self.build_card, bc = card("Сборка подборки", icon="clapperboard")   # сборка — своей карточкой (2.3.0)
        bc.setSpacing(10)
        mrow = QHBoxLayout()
        mrow.setSpacing(6)
        b = QPushButton("Музыка…")
        theme.set_icon(b, "music", FG, 15)
        b.setToolTip("Один трек на всю подборку — свой или свободный")
        b.clicked.connect(self.pick_music)
        mrow.addWidget(b)
        self.music_none = QPushButton("Без музыки")
        self.music_none.setObjectName("ghost")
        self.music_none.clicked.connect(lambda: self.set_music(""))
        mrow.addWidget(self.music_none)
        self.music_label = hint("")
        mrow.addWidget(self.music_label, 1)
        bc.addLayout(mrow)
        self.set_music(self.s.get("weekly_music", ""))
        row.addWidget(self.btn)
        col = QVBoxLayout()
        col.setSpacing(6)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(8)
        self.bar.setTextVisible(False)
        col.addWidget(self.bar)
        self.state = hint("")
        col.addWidget(self.state)
        row.addLayout(col, 1)
        self.btn_open = QPushButton("Открыть")
        self.btn_open.clicked.connect(lambda: self.last and open_path(self.last))
        self.btn_show = QPushButton("Показать в папке")
        self.btn_show.clicked.connect(lambda: self.last and show_in_folder(self.last))
        theme.set_icon(self.btn_open, "play", FG, 14)
        theme.set_icon(self.btn_show, "folder-open", FG, 15)
        for b in (self.btn_open, self.btn_show):
            b.setEnabled(False)
            row.addWidget(b)
        bc.addLayout(row)

        row = QHBoxLayout()
        self.dir_hint = hint("")
        row.addWidget(self.dir_hint, 1)
        b = QPushButton("Папка…")
        b.setObjectName("ghost")
        b.clicked.connect(self.pick_dir)
        row.addWidget(b)
        bc.addLayout(row)
        lay.addWidget(self.build_card)
        self._show_dir()

        win.bus.weekly_progress.connect(self._progress)
        win.bus.weekly_done.connect(self._done)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        center_content(self, self._lay)

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
        items = autoclip.weekly_candidates(self.days.value(), include_used=bool(self.s.get("weekly_show_used")))
        self.list.blockSignals(True)
        self.list.clear()
        for c in items:
            date = f"{c['date'][8:10]}.{c['date'][5:7]}" if c["date"] else ""
            it = QListWidgetItem(
                f"★ {c['score']:.1f}   {c['title']}\n"
                f"{c['dur']:.0f} с  ·  {autoclip.STATUSES.get(c['status'], c['status'])}"
                f"  ·  {date}  ·  {c['source']}" + ("  ·  уже был в подборке" if c.get("used") else ""))
            it.setData(Qt.UserRole, c["path"])
            it.setData(Qt.UserRole + 1, c["dur"])
            it.setData(Qt.UserRole + 2, (c["project"], c["id"]))
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

    def clear_all(self):
        """«Очистить»: убрать все клипы из текущей подборки (5.16)."""
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Unchecked)
        self.list.blockSignals(False)
        self._summary()

    def chosen_ids(self):
        return [self.list.item(i).data(Qt.UserRole + 2) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]

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

    def pick_music(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Трек для подборки", self.s.get("music_dir", ""),
            "Музыка (" + " ".join("*" + e for e in autoclip.MUSIC_EXT) + ")")
        if path:
            self.set_music(path)

    def set_music(self, path):
        self.s["weekly_music"] = path or ""
        save_settings(self.s)
        self.music_none.setVisible(bool(path))
        self.music_label.setText(f"♪ {os.path.basename(path)} — тихо, под голосом ещё тише"
                                 if path else "Без музыки. " + MUSIC_HINT)

    # ---------- сборка ----------
    def build(self):
        paths = [p for p, _ in self.chosen()]
        if not paths or self.busy:
            return
        self.busy = True
        self._building = self.chosen_ids()
        self.btn.setEnabled(False)
        self.btn_open.setEnabled(False)
        self.btn_show.setEnabled(False)
        self.bar.setValue(0)
        self.state.setText("Собираю…")
        fmt = self.s["weekly_format"]
        music = self.s.get("weekly_music", "")
        self.eta = autoclip.Eta()
        autoclip.WEEKLY_DIR = self.s["weekly_dir"]
        bus = self.win.bus

        def work():
            try:
                out = autoclip.build_compilation(
                    paths, fmt, progress=lambda st, pct, msg: bus.weekly_progress.emit(float(pct), msg),
                    music=dict(autoclip.MUSIC_DEFAULT, file=music) if music else None)
                bus.weekly_done.emit(out, None)
            except autoclip.AutoClipError as e:
                bus.weekly_done.emit("", str(e))
            except Exception:
                bus.weekly_done.emit("", "❌ " + traceback.format_exc()[-800:])
        threading.Thread(target=work, daemon=True).start()

    def _progress(self, pct, msg):
        self.bar.setValue(int(pct * 10))
        if getattr(self, "eta", None) is None:
            self.eta = autoclip.Eta()
        left = self.eta.update(pct / 100)
        self.state.setText(f"Собираю… {pct:.0f}%" + (f" · {autoclip.fmt_left(left)}" if left is not None else "")
                           + f"  {msg}")

    def _done(self, out, err):
        self.busy = False
        self._summary()
        if err:
            self.bar.setValue(0)
            self.state.setText(err)
            return
        self.last = out
        try:                                       # эти клипы в следующую подборку сами не попадут
            autoclip.mark_compiled([x for x in getattr(self, "_building", []) if x], out)
        except Exception:
            pass
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
        self._lay = lay
        lay.addLayout(page_title("Настройки"))

        # --- новые клипы ---
        box, v = card("Новые клипы", "Так будут нарезаться новые клипы. "
                                     "У отдельного клипа всё можно поменять в «Клипах».")
        self.length = QComboBox()
        self.length.setMinimumWidth(190)
        for name, key in LENGTH_NAMES.items():
            self.length.addItem(name, key)
        self.length.setCurrentIndex(max(0, self.length.findData(self.s.get("clip_length", "normal"))))
        self.length.currentIndexChanged.connect(lambda _: self._set("clip_length", self.length.currentData()))
        v.addWidget(option_row("Длина клипов", self.length,
                               "Длиннее — больше того, что было до и после момента. Короче — только самое яркое"))
        v.addWidget(separator())
        self.cb_subs = self._toggle("subs")
        v.addWidget(option_row("Субтитры", self.cb_subs))
        self.cb_subs_team = self._toggle("subs_team")
        v.addWidget(option_row("Субтитры и для тиммейтов", self.cb_subs_team,
                               "Если OBS пишет Discord отдельной дорожкой. Мат тиммейтов пикается всегда"))
        self.sub_pos = self._combo(list(autoclip.SUB_POSITIONS) +
                                   ([CUSTOM_POS] if self.s.get("sub_pos") == CUSTOM_POS else []),
                                   "sub_pos")
        v.addWidget(option_row("Где субтитры", self.sub_pos))
        self.cb_safe = self._toggle("safe_zone")
        v.addWidget(option_row("Сейф-зона соцсетей", self.cb_safe,
                               "Субтитры не заходят под кнопки, ник и подпись "
                               "TikTok, Shorts и Reels"))
        self.preview = SubsPreview()            # маленькая схема — в карточке «Ник в углу»
        v.addWidget(hint("Шрифт, цвета и место субтитров — в карточке «Субтитры» ниже."))
        v.addWidget(separator())
        self.cb_zoom = tri_combo(self.s.get("zoom"))
        self.cb_zoom.currentIndexChanged.connect(lambda _: self._set("zoom", self.cb_zoom.currentData()))
        v.addWidget(option_row("Зум", self.cb_zoom,
                               "Авто — только на смехе и крике, не больше 3 на клип. Вкл — на всех громких местах"))
        self.cb_hook = tri_combo(self.s.get("hook"))
        self.cb_hook.currentIndexChanged.connect(lambda _: self._set("hook", self.cb_hook.currentData()))
        v.addWidget(option_row("Хук в начале", self.cb_hook,
                               "1–2 секунды яркой реакции из этого же клипа в самом начале. "
                               "Авто — когда есть яркий момент, Вкл — всегда, когда есть место"))
        self.cam = self._combo(WEBCAM, "cam")
        v.addWidget(option_row("Раскладка записи", self.cam, "Куда приближать зум"))
        v.addWidget(separator())
        self.cb_bleep = self._toggle("bleep")
        v.addWidget(option_row("Мат звуком", self.cb_bleep))
        self.censor = censor_combo(self.s.get("censor", "partial"))
        self.censor.currentIndexChanged.connect(lambda _: self._set("censor", self.censor.currentData()))
        v.addWidget(option_row("Цензура", self.censor,
                               "Частичная: «е*ать», звук закрывает только эти буквы. "
                               "TikTok может распознать полузапиканный мат и урезать охват"))
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
        self.pool_box = QWidget()
        self.pool_lay = QHBoxLayout(self.pool_box)
        self.pool_lay.setContentsMargins(0, 0, 0, 0)
        self.pool_lay.setSpacing(10)
        self.pool_row = option_row("Какие звуки в «Случайном»", self.pool_box,
                                   "На каждый мат — свой звук, один и тот же не два раза подряд. "
                                   "Ничего не выбрано — все")
        v.addWidget(self.pool_row)
        self.sound.currentTextChanged.connect(lambda t: self.pool_row.setVisible(t == autoclip.RANDOM_SOUND))
        brow = QHBoxLayout()
        brow.setSpacing(8)
        self.bleep_db = QSlider(Qt.Horizontal)
        self.bleep_db.setRange(-12, 6)
        self.bleep_db.setValue(int(self.s.get("bleep_rel_db", 0)))
        self.bleep_db.setFixedWidth(180)
        self.bleep_db_l = QLabel()
        self.bleep_db_l.setMinimumWidth(text_width("на уровне голоса", 13) + 6)

        def show_bleep_db(v):
            self.bleep_db_l.setText("на уровне голоса" if v == 0 else f"{v:+d} дБ к голосу")
            self._set("bleep_rel_db", int(v))
        self.bleep_db.valueChanged.connect(show_bleep_db)
        show_bleep_db(self.bleep_db.value())
        brow.addWidget(self.bleep_db)
        brow.addWidget(self.bleep_db_l)
        v.addWidget(option_row("Громкость звука на мат", brow,
                               "Подстраивается под голос рядом с матом"))
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

        # --- субтитры: стиль и живой предпросмотр ---
        box, v = card("Субтитры", "Как выглядят субтитры в новых клипах. Справа — кадр клипа: "
                                  "строку можно перетащить мышкой, пунктир — сейф-зона.")
        body = QHBoxLayout()
        body.setSpacing(24)
        form = QVBoxLayout()
        form.setSpacing(10)
        st_row = QHBoxLayout()
        st_row.setSpacing(6)
        self.style_box = QComboBox()
        self.style_box.setMinimumWidth(190)
        self.style_box.activated.connect(lambda i: self.apply_style(self.style_box.itemText(i)))
        st_row.addWidget(self.style_box)
        b = QPushButton("Сохранить как…")
        b.clicked.connect(self.save_style_as)
        st_row.addWidget(b)
        self.style_del = QPushButton("Удалить")
        self.style_del.setObjectName("ghost")
        self.style_del.clicked.connect(self.delete_style)
        st_row.addWidget(self.style_del)
        form.addWidget(option_row("Стиль", st_row, "Выбранный — по умолчанию для новых клипов"))
        f_row = QHBoxLayout()
        f_row.setSpacing(6)
        self.font_box = QComboBox()
        self.font_box.setMinimumWidth(220)
        self.font_box.setMaxVisibleItems(18)
        self.font_box.activated.connect(lambda i: self._set_style_key("sub_font", self.font_box.itemText(i)))
        f_row.addWidget(self.font_box)
        b = QPushButton("Свой файл шрифта…")
        b.setToolTip("ttf или otf — копия ляжет в папку программы с настройками")
        b.clicked.connect(self.pick_font_file)
        f_row.addWidget(b)
        form.addWidget(option_row("Шрифт", f_row, "Только шрифты с русскими буквами"))
        self.mode_box = QComboBox()
        self.mode_box.setMinimumWidth(190)
        for k, name in SUB_MODES.items():
            self.mode_box.addItem(name, k)
        self.mode_box.activated.connect(lambda i: self._set_style_key("sub_mode", self.mode_box.itemData(i)))
        form.addWidget(option_row("Показ", self.mode_box))
        self.size_box = Stepper(40, 160, int(self.s.get("sub_size", 82)), step=4)
        self.size_box.valueChanged.connect(lambda x: self._set_style_key("sub_size", int(x)))
        form.addWidget(option_row("Размер", self.size_box))
        c_row = QHBoxLayout()
        c_row.setSpacing(8)
        self.c_text = ColorButton(self.s.get("sub_color", "#FFFFFF"), "Текст")
        self.c_hl = ColorButton(self.s.get("sub_hl_color", "#FFE600"), "Слово, которое сейчас звучит")
        self.c_out = ColorButton(self.s.get("sub_outline_color", "#000000"), "Обводка")
        for lbl, btn, key in (("текст", self.c_text, "sub_color"), ("слово", self.c_hl, "sub_hl_color"),
                              ("обводка", self.c_out, "sub_outline_color")):
            c_row.addWidget(btn)
            c_row.addWidget(hint(lbl))
            c_row.addSpacing(6)
            btn.changed.connect(lambda col, key=key: self._set_style_key(key, col))
        form.addWidget(option_row("Цвета", c_row))
        self.outline_box = Stepper(0, 20, int(self.s.get("sub_outline", 7)))
        self.outline_box.valueChanged.connect(lambda x: self._set_style_key("sub_outline", int(x)))
        form.addWidget(option_row("Толщина обводки", self.outline_box))
        p_row = QHBoxLayout()
        p_row.setSpacing(6)
        for name, pos in (("Верх", "Сверху"), ("Середина", "Середина"), ("Низ", "Снизу")):
            b = QPushButton(name)
            b.clicked.connect(lambda _, pos=pos: self.sub_pos.setCurrentText(pos))
            p_row.addWidget(b)
        form.addWidget(option_row("Место", p_row, "Или перетащи строку мышкой в кадре справа"))
        form.addStretch(1)
        body.addLayout(form, 1)
        self.live = LivePreview()
        self.live.set_frame(latest_cover())
        self.live.moved.connect(self.subs_moved)
        body.addWidget(self.live, 0, Qt.AlignTop)
        v.addLayout(body)
        lay.addWidget(box)
        self._live_n = 0
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(200)
        self._live_timer.timeout.connect(self.render_live)
        self.win.bus.sub_layer.connect(self._live_ready)
        self.fill_style_widgets()

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
        v.addWidget(option_row("Где ник", self.preview,
                               "Белое — субтитры, красное — зона кнопок соцсетей"))
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
        box, v = card("Запуск", "AutoClip стартует вместе с Windows сразу в трей: окно не "
                                "открывается, работают слежка за OBS, Telegram и проверка обновлений.")
        import autostart
        self.cb_autostart = Toggle(autostart.is_enabled())
        self.cb_autostart.toggled.connect(self.set_autostart)
        v.addWidget(option_row("Запускать вместе с Windows", self.cb_autostart,
                               "Окно — по значку AutoClip в трее"))
        lay.addWidget(box)

        box, v = card("Папка для клипов", "Каждая нарезка — папка «Клипы ДД.ММ.ГГГГ» с подпапками Новые, "
                                          "Выложу, Норм, Выложенные. Записи остаются в своей папке.")
        row = QHBoxLayout()
        self.clips_dir = QLineEdit(self.s.get("clips_dir", ""))
        self.clips_dir.setPlaceholderText("пусто — рядом с записью")
        self.clips_dir.textChanged.connect(lambda t: self._set("clips_dir", t.strip()))
        row.addWidget(self.clips_dir, 1)
        b = QPushButton("Выбрать…")
        b.clicked.connect(self.pick_clips_dir)
        row.addWidget(b)
        v.addLayout(row)
        self.cache_days = Stepper(3, 365, int(self.s.get("cache_days", 30)))
        self.cache_days.valueChanged.connect(lambda x: self._set("cache_days", x))
        v.addWidget(option_row("Хранить кэш расшифровки, дней", self.cache_days,
                               "Кэш лежит в папке настроек, не в папке записей. Неиспользуемый удаляется "
                               "сам — понадобится, запись расшифруется заново"))
        lay.addWidget(box)

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

        # --- музыка ---
        box, v = card("Музыка", "Папка со своими треками — они появятся во вкладке «Музыка» у клипа. "
                                "По умолчанию клипы без музыки. " + MUSIC_HINT)
        mrow = QHBoxLayout()
        mrow.setSpacing(6)
        self.music_dir = QLineEdit(self.s.get("music_dir", ""))
        self.music_dir.setPlaceholderText("Папка «Музыка»")
        self.music_dir.setMinimumWidth(300)
        self.music_dir.textChanged.connect(lambda t: self._set("music_dir", t.strip()))
        mrow.addWidget(self.music_dir)
        b = QPushButton("Выбрать…")
        b.clicked.connect(lambda: (lambda d: d and self.music_dir.setText(d))(
            QFileDialog.getExistingDirectory(self, "Папка с музыкой", self.music_dir.text())))
        mrow.addWidget(b)
        v.addWidget(option_row("Папка «Музыка»", mrow))
        lay.addWidget(box)

        # --- Telegram ---
        box, v = card("Telegram", "Уведомления в телефон: нарезка готова, новая запись в OBS "
                                  "(«Нарезать» прямо оттуда), вопросы про просмотры. Работает, пока "
                                  "AutoClip запущен, хотя бы в трее.")
        v.addWidget(hint("1. В Telegram найди @BotFather, отправь ему /newbot и придумай имя боту.\n"
                         "2. Он пришлёт токен — длинную строку с двоеточием. Вставь её сюда и нажми "
                         "«Подключить».\n3. Открой своего бота и напиши ему /start."))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.tg_token = QLineEdit()
        self.tg_token.setPlaceholderText("Токен бота от @BotFather")
        self.tg_token.setEchoMode(QLineEdit.Password)
        self.tg_token.setMinimumWidth(320)
        row.addWidget(self.tg_token, 1)
        self.tg_connect = QPushButton("Подключить")
        self.tg_connect.setObjectName("primary")
        self.tg_connect.clicked.connect(self.connect_telegram)
        row.addWidget(self.tg_connect)
        v.addLayout(row)
        row = QHBoxLayout()
        self.tg_status = QLabel("")
        self.tg_status.setWordWrap(True)
        row.addWidget(self.tg_status, 1)
        self.tg_test = QPushButton("Проверить")
        self.tg_test.setToolTip("Отправить боту тестовое сообщение")
        self.tg_test.clicked.connect(self.test_telegram)
        row.addWidget(self.tg_test)
        self.tg_off = QPushButton("Отключить")
        self.tg_off.setObjectName("ghost")
        self.tg_off.clicked.connect(self.disconnect_telegram)
        row.addWidget(self.tg_off)
        v.addLayout(row)
        lay.addWidget(box)
        self.win.bus.tg_state.connect(self.show_telegram)
        self.show_telegram()

        # --- отчёт об ошибке ---
        box, v = card("Резервная копия", "Все настройки, звуки, шрифты, стили, список нарезок, история "
                                         "просмотров, прогноз, Telegram и вход в соцсети — в один файл. "
                                         "Пригодится при переустановке Windows.")
        row = QHBoxLayout()
        row.setSpacing(8)
        b = QPushButton("Сохранить копию…")
        b.clicked.connect(self.save_backup)
        row.addWidget(b)
        b = QPushButton("Восстановить из копии…")
        b.clicked.connect(self.restore_backup)
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(hint("В копии лежит токен Telegram-бота — никому её не пересылай."))
        self.backup_state = hint("")
        v.addWidget(self.backup_state)
        self.cb_backup_remind = self._toggle("backup_remind")
        v.addWidget(option_row("Напоминать раз в месяц", self.cb_backup_remind,
                               "Тихо, в трее или в Telegram: «Давно не сохранял копию настроек»"))
        self.show_backup_state()
        b = QPushButton("Мастер первого запуска…")
        b.setToolTip("Ник, папки записей и клипов, видеокарта — по шагам, как при первом запуске")
        b.clicked.connect(self.win.show_setup)
        v.addWidget(b, 0, Qt.AlignLeft)
        lay.addWidget(box)

        box, v = card("Состояние системы", "Всё, от чего зависит нарезка: ffmpeg, видеокарта, Whisper, "
                                           "Ollama, Telegram, место на дисках, дорожки в записи.")
        self.health_text = QLabel("Нажми «Проверить».")
        self.health_text.setWordWrap(True)
        self.health_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.health_text)
        self.health_btn = QPushButton("Проверить")
        self.health_btn.clicked.connect(self.check_health)
        v.addWidget(self.health_btn, 0, Qt.AlignLeft)
        lay.addWidget(box)

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

    # --- Telegram ---
    def show_telegram(self, text=None):
        st = telegram_bot.load_state()
        on = bool(st.get("token") and st.get("chat_id"))
        self.tg_test.setEnabled(on)
        self.tg_off.setEnabled(bool(st.get("token")))
        self.tg_connect.setEnabled(True)
        if text:
            self.tg_status.setText(text)
        elif on:
            self.tg_status.setText(f"Подключён: @{st.get('bot', 'бот')}.")
        else:
            self.tg_status.setText("Не подключён.")

    def connect_telegram(self):
        token = self.tg_token.text().strip()
        if not token:
            self.show_telegram("Вставь токен от @BotFather.")
            return
        self.tg_connect.setEnabled(False)
        self.tg_status.setText("Проверяю токен…")
        bus = self.win.bus

        def work():
            try:
                bot = telegram_bot.Bot(log=lambda m: None)
                name = bot.set_token(token)
                bus.tg_state.emit(f"Теперь открой @{name} в Telegram и напиши ему /start. Жду 2 минуты…")
                if bot.wait_start(120):
                    bus.tg_state.emit(f"Подключён: @{name}. Тестовое сообщение уже в Telegram.")
                else:
                    bus.tg_state.emit(f"Не дождался /start. Напиши @{name} /start и нажми «Подключить» ещё раз.")
            except telegram_bot.TelegramError as e:
                bus.tg_state.emit(str(e))
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()
        self.tg_token.clear()                            # токен на экране не держим

    def test_telegram(self):
        self.tg_status.setText("Отправляю…")
        self.win.telegram.do(lambda bot: (bot.test(), self.win.bus.tg_state.emit(
            "Тестовое сообщение отправлено — проверь Telegram.")))

    def disconnect_telegram(self):
        telegram_bot.disconnect()
        self.show_telegram("Отключён. Бот больше ничего не пришлёт.")

    # --- субтитры ---
    def fill_style_widgets(self):
        """Поля стиля — по нынешним настройкам."""
        from PySide6.QtGui import QFontDatabase
        names = [st["name"] for st in autoclip.load_styles()]
        self.style_box.blockSignals(True)
        self.style_box.clear()
        self.style_box.addItems(names)
        cur = self.s.get("sub_style", "Обычный")
        self.style_box.setCurrentText(cur if cur in names else names[0])
        self.style_box.blockSignals(False)
        self.style_del.setEnabled(self.style_box.currentText() != "Обычный")
        fams = sorted(set(QFontDatabase.families(QFontDatabase.WritingSystem.Cyrillic))
                      | set(autoclip.user_fonts()) | {self.s.get("sub_font", "Arial Black")},
                      key=str.lower)
        self.font_box.blockSignals(True)
        self.font_box.clear()
        self.font_box.addItems([f for f in fams if not f.startswith("@")])
        self.font_box.setCurrentText(self.s.get("sub_font", "Arial Black"))
        self.font_box.blockSignals(False)
        self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(self.s.get("sub_mode", "words"))))
        for w, key in ((self.size_box, "sub_size"), (self.outline_box, "sub_outline")):
            w.blockSignals(True)
            w.setValue(int(self.s.get(key, DEFAULTS[key])))
            w.blockSignals(False)
        for btn, key in ((self.c_text, "sub_color"), (self.c_hl, "sub_hl_color"),
                         (self.c_out, "sub_outline_color")):
            btn.set_color(self.s.get(key, DEFAULTS[key]))
        self.refresh_live()

    def _set_style_key(self, key, value):
        self._set(key, value)
        self.refresh_live()

    def apply_style(self, name):
        st = autoclip.get_style(name)
        for k in autoclip.STYLE_KEYS:
            self.s[k] = st[k]
        self.s["sub_style"] = st["name"]
        save_settings(self.s)
        self.fill_style_widgets()

    def save_style_as(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Сохранить стиль", "Название стиля:",
                                        text="" if self.s.get("sub_style") == "Обычный"
                                        else self.s.get("sub_style", ""))
        if not ok or not name.strip():
            return
        try:
            autoclip.save_style(name, {k: self.s.get(k, DEFAULTS[k]) for k in autoclip.STYLE_KEYS})
        except autoclip.AutoClipError as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            return
        self._set("sub_style", name.strip())
        self.fill_style_widgets()

    def delete_style(self):
        name = self.style_box.currentText()
        if name == "Обычный":
            return
        autoclip.delete_style(name)
        self.apply_style("Обычный")

    def pick_font_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Файл шрифта", "", "Шрифты (*.ttf *.otf)")
        if not path:
            return
        try:
            fam = autoclip.add_font(path)
        except autoclip.AutoClipError as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            return
        from PySide6.QtGui import QFontDatabase
        QFontDatabase.addApplicationFont(os.path.join(autoclip.FONTS_DIR, os.path.basename(path)))
        self._set("sub_font", fam)
        self.fill_style_widgets()

    def subs_moved(self, x, y):
        self.s["sub_x"] = round(x, 4)
        self.s["sub_y_free"] = round(y, 4)
        if self.sub_pos.findText(CUSTOM_POS) < 0:
            self.sub_pos.addItem(CUSTOM_POS)
        self.sub_pos.setCurrentText(CUSTOM_POS)       # сохранит sub_pos и перерисует
        self._set("sub_pos", CUSTOM_POS)
        self.refresh_live()

    def live_cfg(self):
        cfg = dict(autoclip.CONFIG, subs=self.cb_subs.isChecked(), safe_zone=self.cb_safe.isChecked())
        cfg.update(sub_settings(self.s))
        cfg.update(nick=False)                       # ник — на маленькой схеме у «Ника в углу»
        return cfg

    def refresh_live(self, *_):
        if hasattr(self, "_live_timer"):
            self._live_timer.start()

    def render_live(self):
        self._live_n += 1
        n, cfg, bus = self._live_n, self.live_cfg(), self.win.bus
        out = os.path.join(tempfile.gettempdir(), f"autoclip_live_{os.getpid()}_{n % 4}.png")

        def work():
            try:
                autoclip.render_sub_layer(cfg, LivePreview.W, LivePreview.H, out)
                path = out
            except Exception:
                path = ""
            try:
                bus.sub_layer.emit(n, path)
            except RuntimeError:
                pass
        self._live_cfg = cfg
        threading.Thread(target=work, daemon=True).start()

    def _live_ready(self, n, path):
        if n == self._live_n:                        # пришёл последний запрос, старые — мимо
            self.live.set_layer(path, self._live_cfg)

    def _update_preview(self, *_):
        self.refresh_live()
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
        while self.pool_lay.count():
            w = self.pool_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.pool_checks = {}
        chosen = set(self.s.get("bleep_pool") or [])
        for name in autoclip.list_sounds():
            if name == "тишина":
                continue
            cb = QCheckBox(os.path.splitext(name)[0])
            cb.setChecked(name in chosen)
            cb.toggled.connect(self._pool_changed)
            self.pool_lay.addWidget(cb)
            self.pool_checks[name] = cb
        self.pool_lay.addStretch(1)
        self.pool_row.setVisible(self.sound.currentText() == autoclip.RANDOM_SOUND)

    def _pool_changed(self, *_):
        self._set("bleep_pool", [n for n, cb in self.pool_checks.items() if cb.isChecked()])

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
        lines = [f"Оценок «Выложу» / «Норм» / «Не то»: <b>{info['n_like']}</b> из {need}, "
                 f"клипов с просмотрами: <b>{info['n_views']}</b> из {need}, "
                 f"с досмотрами: <b>{info.get('n_retention', 0)}</b> из {forecast.MIN_RETENTION}."]
        if not (info.get("like") or info.get("views") or info.get("retention")):
            lines.append(f"<span style='color:{MUTED}'>Данных пока мало — прогноз считается "
                         "по правилам.</span>")
        else:
            lines.append(f"Модель учтена в прогнозе на {int(forecast.model_share(info) * 100)}%.")
            for key, title in (("views", "Что набирает просмотры"), ("retention", "Что досматривают"),
                               ("like", "Что тебе нравится")):
                pairs = forecast.explain(info).get(key)
                if pairs:
                    lines.append(f"{title}: " + ", ".join(
                        f"<span style='color:{'#7dd99a' if w > 0 else '#ff7a90'}'>{n} "
                        f"{'+' if w > 0 else '−'}{abs(w):.2f}</span>" for n, w in pairs))
        self.model_state.setText("<br>".join(lines))

    def check_health(self):
        """«Состояние системы»: проверка в фоне, итог — списком ✓ / ✗ / ·."""
        import health
        self.health_btn.setEnabled(False)
        self.health_text.setText("Проверяю…")
        out = {}

        def work():
            try:
                out["rows"] = health.status()
            except Exception as e:
                out["rows"] = [("Проверка", False, str(e))]

        th = threading.Thread(target=work, daemon=True)
        th.start()

        def poll():
            if th.is_alive():
                QTimer.singleShot(200, poll)
                return
            mark = {True: ("✓", "#7dd99a"), False: ("✗", "#ff7a90"), None: ("·", MUTED)}
            self.health_text.setText("<br>".join(
                f"<span style='color:{mark[ok][1]}'>{mark[ok][0]}</span> <b>{name}</b> — {text}"
                for name, ok, text in out["rows"]))
            self.health_btn.setEnabled(True)
        QTimer.singleShot(200, poll)

    def show_backup_state(self):
        import backup
        last = backup.last_saved()
        self.backup_state.setText(f"Последняя копия: {last:%d.%m.%Y %H:%M}" if last else "Копию ещё не сохранял.")

    def save_backup(self):
        import backup
        name = f"AutoClip копия {datetime.date.today():%Y-%m-%d}.zip"
        start = os.path.join(os.path.expanduser("~"), "Documents", name)
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить копию", start, "Копия AutoClip (*.zip)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = backup.save_backup(path)
        except (OSError, autoclip.AutoClipError) as e:
            QMessageBox.warning(self, "AutoClip", f"Копию сохранить не получилось: {e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.show_backup_state()
        extra = (f"\nНе вошли занятые файлы ({len(res['skipped'])}) — закрой окна соцсетей и сохрани ещё раз, "
                 "если важен вход в соцсети." if res["skipped"] else "")
        self.win.toast(f"Копия сохранена: {path}\nВ ней токен Telegram-бота — никому её не пересылай.{extra}",
                       8000)

    def restore_backup(self):
        import backup
        import update
        path, _ = QFileDialog.getOpenFileName(self, "Восстановить из копии",
                                              os.path.join(os.path.expanduser("~"), "Documents"),
                                              "Копия AutoClip (*.zip)")
        if not path:
            return False
        try:
            m = backup.read_manifest(path)
        except autoclip.AutoClipError as e:
            QMessageBox.warning(self, "AutoClip", str(e))
            return False
        when = str(m.get("date", ""))[:16].replace("T", " ")
        if ask_choice(self, f"Восстановить копию от {when} (версия {m.get('version', '?')})? Нынешние "
                            "настройки и данные уйдут в корзину Windows, AutoClip перезапустится.",
                      [("yes", "Восстановить"), ("no", "Отмена")]) != "yes":
            return False
        try:
            res = backup.restore_backup(path)
        except (OSError, autoclip.AutoClipError) as e:
            QMessageBox.warning(self, "AutoClip", f"Восстановить не получилось: {e}")
            return False
        self.win.settings.clear()
        self.win.settings.update(load_settings())       # при закрытии сохранятся уже восстановленные
        self.s = self.win.settings
        note = f"\nНарезок, папок которых нет, пропущено: {res['missing']}." if res["missing"] else ""
        QMessageBox.information(self, "AutoClip", "Копия восстановлена. AutoClip перезапустится." + note)
        if getattr(self.win, "standalone", False):
            update.restart(False)
            self.win.quit_app()
        return True

    def resizeEvent(self, e):
        super().resizeEvent(e)
        center_content(self, self._lay)

    def set_autostart(self, on):
        import autostart
        try:
            if not on:
                autostart.disable()
                return
            autostart.enable()
            extra = autostart.startup_shortcuts()
            if extra:
                names = ", ".join(os.path.basename(x) for x in extra)
                ans = ask_choice(self, f"В автозагрузке Windows уже есть ярлык AutoClip ({names}). "
                                       "С ним программа будет стартовать дважды. Убрать ярлык в корзину?",
                                 [("remove", "Убрать"), ("keep", "Оставить")])
                if ans == "remove":
                    autostart.remove_shortcuts(extra)
        except (OSError, autoclip.AutoClipError) as e:
            QMessageBox.warning(self, "AutoClip", f"Не получилось поменять автозапуск: {e}")
            self.cb_autostart.blockSignals(True)
            self.cb_autostart.setChecked(autostart.is_enabled())
            self.cb_autostart.blockSignals(False)

    def pick_clips_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка для клипов", self.clips_dir.text())
        if d:
            self.clips_dir.setText(os.path.normpath(d))

    def find_obs(self):
        d = autoclip.find_obs_record_dir()
        if d:
            self.obs.setText(d)
            self._set("obs_dir", d)
        else:
            self.win.toast("Папку записей в настройках OBS не нашёл — "
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
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(20)
        self.bar.setAlignment(Qt.AlignCenter)
        self.bar.hide()
        lay.addWidget(self.bar)
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


def default_clips_dir():
    """Куда класть клипы на новом компьютере: D:\\Клипы, если есть диск D, иначе «Видео\\AutoClip клипы»."""
    if os.name == "nt" and os.path.isdir("D:\\"):
        return r"D:\Клипы"
    return os.path.join(os.path.expanduser("~"), "Videos", "AutoClip клипы")


class SetupDialog(QDialog):
    """Мастер первого запуска (P4): ник, папки записей и клипов, видеокарта, восстановить из копии.
    Одно окно, всё видно сразу; «Пропустить» — оставить как есть."""

    def __init__(self, win):
        super().__init__(win)
        import health
        self.win = win
        s = win.settings
        self.setWindowTitle("AutoClip — первый запуск")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(8)
        t = QLabel("Настроим AutoClip")
        t.setObjectName("cardTitle")
        lay.addWidget(t)
        lay.addWidget(hint("Четыре шага. Всё можно поменять потом в «Настройках»."))

        row = QHBoxLayout()
        self.btn_restore = QPushButton("Восстановить из копии…")
        self.btn_restore.setToolTip("Есть файл копии со старого компьютера — вернуть все настройки из него")
        self.btn_restore.clicked.connect(self.restore)
        row.addWidget(self.btn_restore)
        row.addWidget(hint("если переносишь AutoClip со старого компьютера"), 1)
        lay.addLayout(row)
        lay.addWidget(separator())

        lay.addWidget(self._title("1. Ник"))
        self.nick = QLineEdit(s.get("nick_text", ""))
        self.nick.setPlaceholderText("твой ник — пишется в углу клипа, если включить «Ник в углу»")
        lay.addWidget(self.nick)

        lay.addWidget(self._title("2. Папка записей OBS"))
        obs = s.get("obs_dir") or autoclip.find_obs_record_dir() or ""
        self.obs = QLineEdit(obs)
        self.obs.setPlaceholderText("где OBS сохраняет записи")
        lay.addLayout(self._pick_row(self.obs, "Папка записей OBS"))
        if obs and not s.get("obs_dir"):
            lay.addWidget(hint("Нашёл в настройках OBS."))

        lay.addWidget(self._title("3. Папка для клипов"))
        clips = s.get("clips_dir") or ""
        if not clips or not os.path.isdir(os.path.splitdrive(clips)[0] + os.sep):
            clips = default_clips_dir()
        self.clips = QLineEdit(clips)
        lay.addLayout(self._pick_row(self.clips, "Папка для клипов"))

        lay.addWidget(self._title("4. Видеокарта"))
        self.gpu = health.gpu_name()
        self.dev = QComboBox()
        self.dev.addItem("Видеокарта — быстро", "auto")
        self.dev.addItem("Процессор — медленно, но работает везде", "cpu")
        if self.gpu:
            note = f"Нашёл {self.gpu}. Расшифровка речи пойдёт на ней."
        else:
            note = ("Видеокарту NVIDIA не нашёл — расшифровка пойдёт на процессоре, модель поменьше "
                    "(medium): медленнее и чуть хуже, но работает.")
        self.dev.setCurrentIndex(0 if self.gpu else 1)
        if s.get("setup_done"):
            self.dev.setCurrentIndex(1 if s.get("whisper_device") == "cpu" else 0)
        lay.addWidget(self.dev)
        self.gpu_note = hint(note)
        lay.addWidget(self.gpu_note)

        lay.addSpacing(6)
        row = QHBoxLayout()
        row.addStretch(1)
        skip = QPushButton("Пропустить")
        skip.clicked.connect(self.skip)
        ok = QPushButton("Готово")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.done_ok)
        row.addWidget(skip)
        row.addWidget(ok)
        lay.addLayout(row)

    def _title(self, text):
        t = QLabel(text)
        t.setObjectName("rowLabel")
        return t

    def _pick_row(self, edit, caption):
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        b = QPushButton("Выбрать…")
        b.clicked.connect(lambda: self._pick(edit, caption))
        row.addWidget(b)
        return row

    def _pick(self, edit, caption):
        d = QFileDialog.getExistingDirectory(self, caption, edit.text())
        if d:
            edit.setText(os.path.normpath(d))

    def restore(self):
        if self.win.settings_page.restore_backup():   # восстановили — там свои настройки
            self.accept()

    def skip(self):
        self.win.settings["setup_done"] = True
        save_settings(self.win.settings)
        self.reject()

    def done_ok(self):
        s = self.win.settings
        s["nick_text"] = self.nick.text().strip()
        s["obs_dir"] = os.path.normpath(self.obs.text().strip()) if self.obs.text().strip() else ""
        clips = self.clips.text().strip()
        if clips:
            clips = os.path.normpath(clips)
            try:
                os.makedirs(clips, exist_ok=True)
            except OSError as e:
                QMessageBox.warning(self, "AutoClip", f"Не получилось создать папку для клипов: {e}")
                return
        s["clips_dir"] = clips
        cpu = self.dev.currentData() == "cpu"
        s["whisper_device"] = "cpu" if cpu else "auto"
        s["whisper_model"] = "medium" if cpu else "large-v3"
        s["setup_done"] = True
        save_settings(s)
        st = self.win.settings_page
        for w, val in ((st.nick, s["nick_text"]), (st.obs, s["obs_dir"]), (st.clips_dir, s["clips_dir"])):
            w.blockSignals(True)
            w.setText(val)
            w.blockSignals(False)
        self.accept()


def need_setup(settings, settings_existed):
    """Мастер — только на новом компьютере: файла настроек ещё не было и мастер не проходили."""
    return not settings_existed and not settings.get("setup_done")


# ---------------- главное окно ----------------


class MainWindow(QMainWindow):
    PAGES = (("cut", "Нарезка", "scissors"), ("clips", "Клипы", "film"),
             ("weekly", "Подборка", "layers"), ("settings", "Настройки", "settings"))

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
            fit_on_screen(self)                       # монитор, где было окно, могли отключить

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
        self.version_btn.setFlat(True)
        self.version_btn.setObjectName("version")
        self.version_btn.setCursor(Qt.PointingHandCursor)
        self.version_btn.setToolTip("Что нового")
        self.version_btn.clicked.connect(lambda: self.show_news())
        sl.addWidget(self.version_btn)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(18, 18))
        for _, text, icon in self.PAGES:
            it = QListWidgetItem(theme.icon(icon, MUTED, 18, active="#ffffff"), "  " + text)
            f = it.font()
            f.setPixelSize(14)
            f.setWeight(QFont.Medium)
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

        # --- Telegram ---
        self.telegram = TelegramLink(self.bus)
        self.bus.tg_action.connect(self.telegram_action)

        # --- прогноз: обучиться на том, что есть, и спросить про просмотры ---
        self.bus.trained.connect(self.settings_page.show_model)
        self.retrain()
        QTimer.singleShot(1500, self.ask_views)

        # --- резервная копия: тихо напомнить раз в месяц ---
        if not self.settings.get("backup_since"):
            self.settings["backup_since"] = datetime.datetime.now().isoformat(timespec="seconds")
            save_settings(self.settings)
        QTimer.singleShot(8000, self.remind_backup)

        QTimer.singleShot(1500, self.cut.show_unfinished)     # прерванная нарезка — предложить доделать

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
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(UPDATE_EVERY_MS)            # и потом раз в 6 часов, пока запущена
        self.update_timer.timeout.connect(
            lambda: self.check_updates() if self.settings.get("check_updates", True) and update.REPO else None)
        self.update_timer.start()
        self._pending_update = None

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
        days = int(self.settings.get("views_days", 3))
        if telegram_bot.is_connected():                  # вопросы — в Telegram, по одному
            def ask(bot):
                bot.st["days"] = days
                bot.ask_views(days)
            self.telegram.do(ask)
            return
        qs = forecast.due_questions(days)
        if not qs or getattr(self, "_views_dialog", None):
            return
        if in_game():                                    # в игре окно не показываем — спросим позже
            QTimer.singleShot(120000, self.ask_views)
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
    def show_setup(self):
        dlg = SetupDialog(self)
        dlg.exec()
        return dlg

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
        if in_game():
            QTimer.singleShot(120000, self.news_after_update)
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

    def working(self):
        """Идёт нарезка, пересборка, сборка клипа или подборки — обновлять нельзя."""
        return bool(self.busy or self.clips.busy or getattr(self.weekly, "busy", False))

    def update_found(self, rel, manual):
        st = self.settings_page.update_state
        if rel and rel.get("error"):
            st.setText(rel["error"])
            return
        if not rel:
            st.setText(f"Стоит последняя версия — {update.VERSION}.")
            return
        st.setText(f"Есть версия {rel['version']}.")
        if not manual and self.settings.get("tg_update_told") != rel["version"]:
            self.settings["tg_update_told"] = rel["version"]
            save_settings(self.settings)
            self.telegram.do(lambda bot, rel=rel: bot.notify_update(rel, update.VERSION))
        if self._update_dialog:
            return
        if not manual and (not self.isVisible() or self.working() or in_game()):
            # окна нет (в трее, идёт игра) или идёт работа — спросим, когда откроют / закончится
            self._pending_update = rel
            if self.tray and not self.isVisible():
                self.tray.showMessage("AutoClip", f"Вышла версия {rel['version']}. Откройте окно, чтобы обновить.",
                                      QSystemTrayIcon.Information, 10000)
            return
        self._pending_update = None
        dlg = UpdateDialog(self, rel)
        self._update_dialog = dlg

        def done(_):
            self._update_dialog = None
            if dlg.action == "skip":
                self.settings["skip_version"] = rel["version"]
                save_settings(self.settings)
        dlg.finished.connect(done)
        dlg.show()

    def ask_pending_update(self):
        rel = self._pending_update
        if rel and self.isVisible() and not self.working() and not self._update_dialog and not in_game():
            self.update_found(rel, False)

    def install_update(self, dlg):
        if self.working():
            dlg.state.setText("Идёт работа — обновлю, когда она закончится. Нажми «Не сейчас», "
                              "программа спросит снова.")
            dlg.later.setEnabled(True)
            self._pending_update = dlg.rel
            return
        eta = autoclip.Eta()
        dlg.bar.show()

        def show(p):
            left = eta.update(p)
            dlg.bar.setValue(int(p * 1000))
            dlg.bar.setFormat(f"{p:.0%}" + (f"  ·  {autoclip.fmt_left(left)}" if left is not None else ""))
            dlg.state.setText("Скачиваю…" if p < 1 else "Ставлю…")
        try:
            self.bus.update_progress.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.bus.update_progress.connect(show)

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
            self.tray.setVisible(bool(self.settings.get("watch")) or getattr(self, "in_tray", False))
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
        """Уведомление Windows и Telegram; вопрос в окне — когда оно на экране (не поверх игры)."""
        self._pending.append((path, info))
        self.telegram.do(lambda bot: bot.notify_recording(path, info))
        text = (f"{os.path.basename(path)}, {autoclip.fmt_time(info['dur'])}, "
                f"меток: {info['marks']}. Нарезать?")
        if self.tray:
            self.tray.showMessage("Новая запись", text, QSystemTrayIcon.Information, 15000)
        if self.isVisible() and self.isActiveWindow():
            self.ask_pending()

    def ask_pending(self):
        if self._dialog or not self._pending or in_game():
            return
        path, info = self._pending.pop(0)
        self._dialog = NewRecordingDialog(self, path, info)
        self._dialog.finished.connect(lambda r, p=path: self._answered(p, r))
        self._dialog.show()
        self._dialog.raise_()

    def _answered(self, path, result):
        self._dialog = None
        self.telegram.do(lambda bot: bot.drop_recording(path))     # кнопки в Telegram — не нужны
        if result == QDialog.Accepted:
            autoclip.set_recording_state(path, "cut")
            self.cut_recording(path)
        else:
            autoclip.set_recording_state(path, "declined")
        QTimer.singleShot(0, self.ask_pending)

    def telegram_action(self, kind, arg):
        """Ответ из Telegram: «Нарезать» / «Не надо» по новой записи или записанные просмотры."""
        if kind in ("cut", "no"):
            if self._dialog and getattr(self._dialog, "path", None) == arg:
                self._dialog.blockSignals(True)
                self._dialog.close()
                self._dialog = None
            self._pending = [(p, i) for p, i in self._pending if p != arg]
            autoclip.set_recording_state(arg, "cut" if kind == "cut" else "declined")
            if kind == "cut":
                self.cut_recording(arg)
        elif kind == "update":
            rel = self._pending_update or {}
            if arg and rel.get("version") == arg:
                if self.working():
                    self.telegram.do(lambda bot: bot.send("Сейчас идёт работа — обновлю, когда закончится, "
                                                          "и спрошу ещё раз."))
                    return
                self.update_found(rel, True)               # показать окно и сразу ставить
                if self._update_dialog:
                    self._update_dialog._done("update")
        elif kind == "skip_update":
            self.settings["skip_version"] = arg
            save_settings(self.settings)
            self._pending_update = None
        elif kind == "views":
            self.retrain()
            c = self.clips.current_clip() if self.clips.proj else None
            if self.clips.proj:
                self.clips.reload(c["id"] if c else None)

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
        QTimer.singleShot(400, self.ask_pending_update)

    def changeEvent(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            QTimer.singleShot(200, self.ask_pending)
        super().changeEvent(e)

    def remind_backup(self):
        import backup
        try:
            since = datetime.datetime.fromisoformat(self.settings.get("backup_since") or "")
        except ValueError:
            since = None
        if not backup.need_reminder(self.settings, first_run=since):
            return
        text = "Давно не сохранял копию настроек AutoClip — «Настройки» → «Резервная копия»."
        if self.tray and self.tray.isVisible():
            self.tray.showMessage("AutoClip", text, QSystemTrayIcon.Information, 8000)
        self.telegram.do(lambda bot: bot.send(text))
        self.bus.log.emit("💾 " + text)
        self.settings["backup_told"] = datetime.datetime.now().isoformat(timespec="seconds")
        save_settings(self.settings)

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
        if self.PAGES[i][0] != "clips":                   # у «Клипов» — видео: оно не проявляется плавно
            fade_in(self.stack.currentWidget())           # плавный переход раздела
        if self.PAGES[i][0] == "weekly":
            self.weekly.refresh()
        if self.PAGES[i][0] != "clips" and not self.detached:
            self.clips.player.player.pause()

    def go(self, key):
        self.nav.setCurrentRow([p[0] for p in self.PAGES].index(key))

    def toast(self, text, ms=4000):
        if getattr(self, "_toast", None) is None:
            self._toast = Toast(self)
        self._toast.show_text(text, ms)

    def notice(self, kind, title, sub="", ms=2600):
        """Крупное сообщение по центру окна: busy / ok / error."""
        if getattr(self, "_notice", None) is None:
            self._notice = CenterNotice(self)
        self._notice.show_notice(kind, title, sub, ms)

    def resume_cut(self, pp):
        if self.busy or not pp:
            return
        self.busy = True
        self.cancel.clear()
        self.cut.resume_bar.hide()
        self.cut.eta = autoclip.Eta()
        self.cut.btn.setText("Остановить")
        self.cut._busy_style(True)

        def work():
            out = None
            try:
                out = autoclip.resume_cut(pp, progress=lambda st, pct, msg: self.bus.progress.emit(st, float(pct), msg),
                                          cancel=self.cancel)
            except autoclip.Cancelled as e:
                self.bus.log.emit(str(e))
            except autoclip.AutoClipError as e:
                self.bus.log.emit(str(e))
            except Exception:
                self.bus.log.emit("❌ Неожиданная ошибка:\n" + traceback.format_exc()[-1500:])
            self.bus.done.emit(out)
        threading.Thread(target=work, daemon=True).start()

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
        QTimer.singleShot(500, self.cut.show_unfinished)
        got = autoclip.CONFIG.get("ollama_model")
        if got and got != self.settings.get("ollama_model"):     # программа взяла другую модель (5.6)
            self.settings["ollama_model"] = got
            save_settings(self.settings)
            self.settings_page.ollama.blockSignals(True)
            self.settings_page.ollama.setText(got)
            self.settings_page.ollama.blockSignals(False)
        QTimer.singleShot(1500, self.ask_pending_update)     # отложенное обновление — после работы
        if out:
            self.telegram.do(lambda bot: bot.notify_cut(out))
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
                fit_on_screen(self.detached)          # второй монитор могли отключить
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
        if (self.settings.get("watch") or getattr(self, "in_tray", False)) and self.tray and not self._quitting:
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
        self.telegram.stop.set()
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
    fam = theme.load_fonts()                      # Inter из папки программы (2.3.0)
    if fam:
        f = QFont(fam)
        f.setPixelSize(13)
        app.setFont(f)
    app.setStyleSheet(STYLE.replace("@ARROW@", arrow_icon()))


ICON = os.path.join(HERE, "icon", "autoclip.ico")
INSTANCE = "FinalKFCBoss.AutoClip"     # имя «канала» единственной копии программы


def ping_running(name=INSTANCE, message=b"show", wait_ms=800, ack_ms=3000):
    """Уже запущена копия? Тогда передать ей message («показать окно») и вернуть True.
    Отключаемся, только когда первая копия ответила «ok»: иначе Windows теряет сообщение, если первая
    не успела принять соединение (окно не всплывало). Старая копия не отвечает — ждём ack_ms и уходим."""
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(wait_ms):
        return False
    sock.write(message)
    sock.flush()
    sock.waitForBytesWritten(wait_ms)
    if message:
        sock.waitForReadyRead(ack_ms)
    sock.disconnectFromServer()
    return True


def wait_old_gone(name=INSTANCE, seconds=20):
    """После обновления: подождать, пока прежняя копия закроется."""
    end = time.time() + seconds
    while time.time() < end and ping_running(name, b"", 300):
        time.sleep(0.3)


class InstanceServer:
    """Слушает вторые запуски: они просят показать окно первой копии."""

    def __init__(self, on_message, name=INSTANCE):
        from PySide6.QtNetwork import QLocalServer
        self.on_message = on_message
        self.server = QLocalServer()
        if not self.server.listen(name):
            QLocalServer.removeServer(name)          # остался от упавшей копии
            self.server.listen(name)
        self.server.newConnection.connect(self._new)

    def _new(self):
        while self.server.hasPendingConnections():
            c = self.server.nextPendingConnection()
            # вторая копия пишет «show» и сразу отключается: под нагрузкой данные приходят раньше, чем
            # мы подписались на readyRead, — дочитываем и сразу, и при отключении (иначе окно не всплывёт)
            c.readyRead.connect(lambda c=c: self._read(c))
            c.disconnected.connect(lambda c=c: (self._read(c), c.deleteLater()))
            self._read(c)

    def _read(self, c):
        try:
            data = bytes(c.readAll()).decode("utf-8", "replace")
        except RuntimeError:                         # сокет уже удалён
            return
        if data:
            try:
                c.write(b"ok")                           # вторая копия ждёт ответа, прежде чем уйти
                c.flush()
            except RuntimeError:
                pass
            self.on_message(data)

    def close(self):
        self.server.close()


def start_window(win, argv):
    """Обычный запуск — окно; с --tray (вместе с Windows) — только значок в трее: слежка за OBS,
    Telegram и проверка обновлений работают, окно открывается по значку."""
    import autostart
    if autostart.TRAY_FLAG in argv and win.tray:
        win.in_tray = True
        win.watch_changed()
        return False
    win.show()
    return True


def friendly_error(exc_type, exc, tb_text=""):
    """Понятный текст вместо трассировки: что случилось и что делать."""
    name = getattr(exc_type, "__name__", "Ошибка")
    text = str(exc) or name
    if isinstance(exc, MemoryError):
        return "Не хватило памяти. Закрой лишние программы (или игру) и попробуй ещё раз."
    if isinstance(exc, PermissionError):
        return f"Файл занят другой программой или нет доступа: {text}. Закрой его там и попробуй снова."
    if isinstance(exc, FileNotFoundError):
        return f"Не найден файл: {text}."
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 112:
        return "На диске закончилось место. Освободи место и попробуй ещё раз."
    if isinstance(exc, autoclip.AutoClipError):
        return text.replace("❌ ", "")
    return f"Что-то пошло не так ({name}: {text[:200]})."


def install_error_hook(win):
    """Любая непойманная ошибка — в лог и понятным окном с кнопкой «Отчёт об ошибке»
    (во время игры — без окна, только в лог и в трей)."""
    import threading as _threading

    def show(exc_type, exc, tb):
        tb_text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            diag.FileLog().write("❌ Непойманная ошибка:\n" + tb_text)
        except Exception:
            pass
        msg = friendly_error(exc_type, exc, tb_text)
        try:
            win.bus.log.emit("❌ " + msg)
        except Exception:
            pass

        def ui():
            if in_game() or not win.isVisible():
                if win.tray:
                    win.tray.showMessage("AutoClip — ошибка", msg, QSystemTrayIcon.Warning, 8000)
                return
            box = QMessageBox(win)
            box.setWindowTitle("AutoClip")
            box.setIcon(QMessageBox.Warning)
            box.setText(msg)
            rep_btn = box.addButton("Отчёт об ошибке", QMessageBox.ActionRole)
            box.addButton("Закрыть", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is rep_btn:
                win.make_report()
        QTimer.singleShot(0, ui)

    sys.excepthook = show
    _threading.excepthook = lambda a: show(a.exc_type, a.exc_value, a.exc_traceback)
    return show


def main():
    autoclip.migrate_user_data()
    settings_existed = os.path.isfile(autoclip.SETTINGS_PATH)
    try:
        import autostart
        autostart.refresh()                     # автозапуск включён — команда на эту папку программы
    except Exception:
        pass
    if os.name == "nt":
        # своя иконка на панели задач, а не значок Python
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FinalKFCBoss.AutoClip")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("AutoClip")
    if "--after-update" in sys.argv:
        wait_old_gone()                              # прежняя копия закрывается — дождаться
    elif ping_running():
        return                                       # уже запущена: показали её окно, вторая не нужна
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
    instance = InstanceServer(lambda m: win.show_window() if "show" in m else None)
    app.aboutToQuit.connect(instance.close)
    install_error_hook(win)
    shown = start_window(win, sys.argv)
    if shown and need_setup(win.settings, settings_existed):
        QTimer.singleShot(400, win.show_setup)       # новый компьютер — мастер первого запуска (P4)
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
