# -*- coding: utf-8 -*-
"""Оформление окна (редизайн 2.3.0): цвета, шрифт Inter из папки программы, векторные значки Lucide,
свечение и тени. Только внешний вид — логики здесь нет.

Шрифт Inter — SIL Open Font License 1.1 (fonts/LICENSE-Inter.txt).
Значки Lucide — ISC License (icon/lucide/LICENSE)."""

import os

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPainter, QPixmap

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")
ICON_DIR = os.path.join(HERE, "icon", "lucide")

# чёрно-красный стиль: почти чёрный фон, красный — только акцент
BG = "#0e0f13"
SIDE = "#0a0b0e"
SURFACE = "#16171d"
SURFACE2 = "#1e2028"
SURFACE3 = "#262935"
BORDER = "#272a34"
BORDER_HI = "#363a48"
FG = "#eceef2"
MUTED = "#8b8f9a"
DIM = "#5c606b"
ACCENT = "#ff4f6d"
ACCENT_HI = "#ff6b84"
ACCENT_LO = "#e23a58"
ACCENT_DEEP = "#3b1d27"

# статусы клипа — цветные плашки
STATUS_COLORS = {
    "new": ("#6aa8ff", "#16233a"),         # Новые
    "post": ("#ff6b84", "#3a1822"),        # Выложу
    "ok": ("#f5c451", "#3a2f14"),          # Норм
    "published": ("#5fd38d", "#15301f"),   # Выложены
    "rejected": ("#8b8f9a", "#24262d"),
}

FAMILY = None          # «Inter», если шрифт загрузился
_icons = {}


def load_fonts():
    """Шрифт программы из папки fonts (не надо ставить в Windows). → имя семейства или None."""
    global FAMILY
    if FAMILY:
        return FAMILY
    if not os.path.isdir(FONT_DIR):
        return None
    for name in sorted(os.listdir(FONT_DIR)):
        if name.lower().endswith((".ttf", ".otf")):
            fid = QFontDatabase.addApplicationFont(os.path.join(FONT_DIR, name))
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if fams and not FAMILY:
                FAMILY = fams[0]
    return FAMILY


def font_stack():
    """Для таблицы стилей: свой шрифт, если загрузился, иначе системный."""
    return f'"{FAMILY}", "Segoe UI Variable Text", "Segoe UI"' if FAMILY else '"Segoe UI Variable Text", "Segoe UI"'


def has_icon(name):
    return os.path.isfile(os.path.join(ICON_DIR, name + ".svg"))


def pixmap(name, color=FG, size=20, dpr=2.0, stroke=None):
    """Значок Lucide нужного цвета. Нет файла — пустая картинка (а не квадратик)."""
    from PySide6.QtSvg import QSvgRenderer
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    path = os.path.join(ICON_DIR, name + ".svg")
    try:
        with open(path, encoding="utf-8") as f:
            svg = f.read()
    except OSError:
        return pm
    svg = svg.replace("currentColor", QColor(color).name())
    if stroke:
        svg = svg.replace('stroke-width="2"', f'stroke-width="{stroke}"')
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def icon(name, color=FG, size=20, active=None, disabled=DIM):
    """QIcon из значка Lucide: обычный цвет, выбранный/включённый (active) и выключенный."""
    key = (name, color, size, active, disabled)
    if key in _icons:
        return _icons[key]
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    on = active or color
    ic.addPixmap(pixmap(name, on, size), QIcon.Selected, QIcon.Off)
    ic.addPixmap(pixmap(name, on, size), QIcon.Normal, QIcon.On)
    ic.addPixmap(pixmap(name, on, size), QIcon.Active, QIcon.Off)
    ic.addPixmap(pixmap(name, disabled, size), QIcon.Disabled, QIcon.Off)
    _icons[key] = ic
    return ic


def set_icon(button, name, color=FG, size=18, active=None):
    """Значок на кнопку (вместо символа-юникода, который в некоторых шрифтах — квадратик)."""
    button.setIcon(icon(name, color, size, active))
    button.setIconSize(QSize(size, size))
    return button


def glow(widget, color=ACCENT, radius=28, alpha=110, dy=4):
    """Лёгкое красное свечение под главной кнопкой."""
    from PySide6.QtWidgets import QGraphicsDropShadowEffect
    eff = QGraphicsDropShadowEffect(widget)
    c = QColor(color)
    c.setAlpha(alpha)
    eff.setColor(c)
    eff.setBlurRadius(radius)
    eff.setOffset(0, dy)
    widget.setGraphicsEffect(eff)
    return eff


def shadow(widget, radius=32, alpha=120, dy=8):
    """Мягкая тень панели."""
    return glow(widget, "#000000", radius, alpha, dy)
