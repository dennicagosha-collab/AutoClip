# -*- coding: utf-8 -*-
"""Таймлайн клипа как в CapCut (Патч 5.17): волна звука записи вокруг клипа, ручки начала и конца,
хук (цветной отрезок), писки на словах, вырезки, метки OBS, зумы, бегунок просмотра.

Время на таймлайне — время **записи**: видно запас до и после клипа, ручки можно вытянуть за
границы. Сам виджет ничего не решает — он показывает состояние и сообщает правки сигналами;
применяет их редактор клипа (ClipsPage)."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

BG = QColor("#16171c")
WAVE = QColor("#3b3e4a")
WAVE_IN = QColor("#8b8f9a")
ACCENT = QColor("#ff4f6d")
HOOK = QColor("#f5b942")
BLEEP = QColor("#ff7a90")
CUT = QColor(0, 0, 0, 150)
ZOOM = QColor("#7dd99a")
TEXT = QColor("#eceef2")
MUTED = QColor("#8b8f9a")
DEAD = QColor(139, 143, 154, 90)

HANDLE = 7          # ширина ручки, px
PAD = 10.0          # запас записи до и после клипа, сек (масштаб колесом)


class Timeline(QWidget):
    """Сигналы: bounds_changed(начало, конец), hook_changed(начало, конец), seek(время записи),
    selection_changed(от, до или -1), bleep_clicked(время слова), cut_requested()."""
    bounds_changed = Signal(float, float)
    hook_changed = Signal(float, float)
    seek = Signal(float)
    selection_changed = Signal(float, float)
    bleep_clicked = Signal(float)              # правой кнопкой — убрать/вернуть писк
    bleep_resized = Signal(object, float, float)   # ключ метки, новое начало и конец (в записи)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.dur = 0.0                    # длина записи
        self.s = self.e = 0.0             # границы клипа (в записи)
        self.view = (0.0, 1.0)            # что видно
        self.wave = []                    # [(время, громкость 0..1)]
        self.hook = None                  # (начало, конец) или None
        self.bleeps = []                  # [(начало, конец, снят ли[, ключ])]
        self.cuts = []                    # [[от, до]]
        self.marks = []                   # время меток OBS
        self.zooms = []                   # время зумов
        self.words = []                   # [(начало, конец, текст)] — подписи при крупном масштабе
        self.dead = []                    # мёртвые куски: нет речи и тихо в игре
        self.playhead = None              # время записи под бегунком
        self.sel = None                   # выделение [от, до] — для «Вырезать»
        self._drag = None

    # ---------- данные ----------
    def set_clip(self, s, e, dur, keep_view=False):
        self.s, self.e, self.dur = float(s), float(e), float(dur or e + PAD)
        if not keep_view:
            self.view = (max(0.0, self.s - PAD), min(self.dur, self.e + PAD))
        self.update()

    def set_bounds(self, s, e):
        self.s, self.e = float(s), float(e)
        self.update()

    def set_layers(self, hook=None, bleeps=(), cuts=(), marks=(), zooms=(), words=(), dead=None):
        if dead is not None:
            self.dead = [list(d) for d in dead]
        self.hook = tuple(hook) if hook else None
        self.bleeps, self.cuts = list(bleeps), [list(c) for c in cuts]
        self.marks, self.zooms, self.words = list(marks), list(zooms), list(words)
        self.update()

    def set_wave(self, wave):
        self.wave = list(wave)
        self.update()

    def set_playhead(self, t):
        self.playhead = t
        self.update()

    def clear_selection(self):
        self.sel = None
        self.selection_changed.emit(-1.0, -1.0)
        self.update()

    # ---------- время ↔ пиксели ----------
    def x_of(self, t):
        a, b = self.view
        return (t - a) / max(1e-6, b - a) * self.width()

    def t_of(self, x):
        a, b = self.view
        return min(self.dur, max(0.0, a + x / max(1, self.width()) * (b - a)))

    # ---------- рисование ----------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), BG)
        top, mid = 18, (18 + h - 14) / 2
        amp = (h - 14 - top) / 2
        # волна
        xs, xe = self.x_of(self.s), self.x_of(self.e)
        for t, v in self.wave:
            x = self.x_of(t)
            if 0 <= x <= w:
                p.setPen(QPen(WAVE_IN if xs <= x <= xe else WAVE, 1))
                p.drawLine(QPointF(x, mid - v * amp), QPointF(x, mid + v * amp))
        # вне клипа — притушено
        p.fillRect(QRectF(0, top, max(0, xs), h - top), QColor(0, 0, 0, 90))
        p.fillRect(QRectF(xe, top, max(0, w - xe), h - top), QColor(0, 0, 0, 90))
        # мёртвые куски — штриховка (нет речи и тихо в игре)
        for a, b in self.dead:
            r = QRectF(self.x_of(a), top, self.x_of(b) - self.x_of(a), h - top)
            if r.right() >= 0 and r.left() <= w:
                p.fillRect(r, QBrush(DEAD, Qt.BDiagPattern))
        # вырезки
        for a, b in self.cuts:
            p.fillRect(QRectF(self.x_of(a), top, self.x_of(b) - self.x_of(a), h - top), CUT)
            p.setPen(QPen(MUTED, 1, Qt.DashLine))
            p.drawRect(QRectF(self.x_of(a), top, self.x_of(b) - self.x_of(a), h - top - 1))
        # выделение
        if self.sel:
            a, b = sorted(self.sel)
            p.fillRect(QRectF(self.x_of(a), top, self.x_of(b) - self.x_of(a), h - top), QColor(255, 79, 109, 50))
        # хук
        if self.hook:
            a, b = self.hook
            r = QRectF(self.x_of(a), top - 14, self.x_of(b) - self.x_of(a), 10)
            p.setBrush(HOOK)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QPen(BG))
            p.setFont(QFont(self.font().family(), 7))
            if r.width() > 26:
                p.drawText(r, Qt.AlignCenter, "хук")
        # писки (края — ручки: тянутся мышью)
        for bl in self.bleeps:
            a, b, off = bl[0], bl[1], bl[2]
            r = QRectF(self.x_of(a), h - 13, max(4.0, self.x_of(b) - self.x_of(a)), 10)
            p.setBrush(QColor(MUTED) if off else BLEEP)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r, 3, 3)
            if r.width() >= 12:
                p.setBrush(QColor(255, 255, 255, 170))
                for ex in (r.left() + 2, r.right() - 4):
                    p.drawRoundedRect(QRectF(ex, r.top() + 2, 2, r.height() - 4), 1, 1)
        # зумы и метки
        p.setPen(QPen(ZOOM, 1))
        for z in self.zooms:
            x = self.x_of(z)
            p.drawLine(QPointF(x, top), QPointF(x, top + 6))
        p.setFont(QFont(self.font().family(), 9))
        for m in self.marks:
            p.setPen(QPen(TEXT))
            p.drawText(QPointF(self.x_of(m) - 6, top - 3), "📍")
        # слова при крупном масштабе
        a, b = self.view
        if self.words and (b - a) < 25:
            p.setPen(QPen(MUTED))
            p.setFont(QFont(self.font().family(), 7))
            for ws, we, text in self.words:
                if a <= ws <= b:
                    p.drawText(QPointF(self.x_of(ws) + 1, h - 15), str(text)[:14])
        # ручки начала и конца
        for x in (xs, xe):
            path = QPainterPath()
            path.addRoundedRect(QRectF(x - HANDLE / 2, top, HANDLE, h - top), 3, 3)
            p.fillPath(path, ACCENT)
        # бегунок
        if self.playhead is not None:
            x = self.x_of(self.playhead)
            p.setPen(QPen(TEXT, 2))
            p.drawLine(QPointF(x, 2), QPointF(x, h))
        # шкала времени
        p.setPen(QPen(MUTED))
        p.setFont(QFont(self.font().family(), 7))
        span = b - a
        step = next(st for st in (1, 2, 5, 10, 15, 30, 60, 120, 300) if span / st <= 12)
        t = math.ceil(a / step) * step
        while t <= b:
            x = self.x_of(t)
            p.drawText(QPointF(x + 2, 10), f"{int(t) // 60}:{int(t) % 60:02d}")
            p.drawLine(QPointF(x, 12), QPointF(x, 16))
            t += step
        p.end()

    # ---------- мышь ----------
    def _hit(self, x, y):
        if abs(x - self.x_of(self.s)) <= HANDLE + 2:
            return "start"
        if abs(x - self.x_of(self.e)) <= HANDLE + 2:
            return "end"
        if self.hook and y < 18:
            ha, hb = self.x_of(self.hook[0]), self.x_of(self.hook[1])
            if abs(x - ha) <= 5:
                return "hook_a"
            if abs(x - hb) <= 5:
                return "hook_b"
            if ha <= x <= hb:
                return "hook"
        if y > self.height() - 16:
            for i, bl in enumerate(self.bleeps):
                xa, xb = self.x_of(bl[0]), self.x_of(bl[1])
                if abs(x - xa) <= 4:
                    return ("bleep_a", i)
                if abs(x - xb) <= 4:
                    return ("bleep_b", i)
                if xa - 2 <= x <= xb + 2:
                    return ("bleep", bl[0])
        return None

    def mousePressEvent(self, ev):
        x, y = ev.position().x(), ev.position().y()
        hit = self._hit(x, y)
        t = self.t_of(x)
        if isinstance(hit, tuple):
            if ev.button() == Qt.RightButton:                       # правой — убрать/вернуть писк
                bl = self.bleeps[hit[1]] if hit[0] != "bleep" else None
                self.bleep_clicked.emit(bl[0] if bl else hit[1])
                return
            if hit[0] in ("bleep_a", "bleep_b"):                     # тянем край — длина писка
                self._drag = (hit[0], t, hit[1])
                return
            self._drag = ("seek", t, None)                           # клик по писку — просто перемотка
            self.seek.emit(t)
            self.update()
            return
        if hit in ("hook_a", "hook_b"):
            self._drag = (hit, t, self.hook)
        elif hit == "hook":
            self._drag = ("hook", t, self.hook)
        elif hit in ("start", "end"):
            self._drag = (hit, t, None)
        elif ev.modifiers() & Qt.ShiftModifier or ev.button() == Qt.RightButton:
            self._drag = ("sel", t, None)
            self.sel = [t, t]
        else:
            self._drag = ("seek", t, None)
            self.sel = None
            self.selection_changed.emit(-1.0, -1.0)
            self.seek.emit(t)
        self.update()

    def mouseMoveEvent(self, ev):
        x = ev.position().x()
        hit = self._hit(x, ev.position().y())
        edge = hit in ("start", "end", "hook_a", "hook_b") or (
            isinstance(hit, tuple) and hit[0] in ("bleep_a", "bleep_b"))
        self.setCursor(Qt.SizeHorCursor if edge else Qt.OpenHandCursor if hit == "hook" else Qt.ArrowCursor)
        if not self._drag:
            return
        kind, t0, extra = self._drag
        t = self.t_of(x)
        if kind == "start":
            self.s = min(t, self.e - 3.0)
        elif kind == "end":
            self.e = max(t, self.s + 3.0)
        elif kind in ("hook_a", "hook_b") and extra:           # длина хука: 0,5–6 с, внутри клипа
            a, b = extra
            if kind == "hook_a":
                a = max(self.s, min(t, b - 0.5), b - 6.0)
            else:
                b = min(self.e, max(t, a + 0.5), a + 6.0)
            self.hook = (a, b)
        elif kind in ("bleep_a", "bleep_b"):
            bl = list(self.bleeps[extra])
            if kind == "bleep_a":
                bl[0] = max(self.s, min(t, bl[1] - 0.1))
            else:
                bl[1] = min(self.e, max(t, bl[0] + 0.1))
            self.bleeps[extra] = tuple(bl)
        elif kind == "hook" and extra:
            d = t - t0
            a, b = extra
            d = max(self.s - a, min(self.e - b, d))          # хук — только внутри клипа (правило 5)
            self.hook = (a + d, b + d)
        elif kind == "sel":
            self.sel[1] = t
            if abs(self.sel[1] - self.sel[0]) > 0.05:          # тянешь — значит выделяешь, а не перематываешь
                pass
        elif kind == "seek" and abs(x - self.x_of(t0)) > 4:
            self._drag = ("sel", t0, None)                     # потянул — выделение куска
            self.sel = [t0, t]
        else:
            self.seek.emit(t)
        self.update()

    def mouseReleaseEvent(self, ev):
        if not self._drag:
            return
        kind, extra = self._drag[0], self._drag[2]
        self._drag = None
        if kind in ("start", "end"):
            self.bounds_changed.emit(round(self.s, 2), round(self.e, 2))
        elif kind in ("hook", "hook_a", "hook_b") and self.hook:
            self.hook_changed.emit(round(self.hook[0], 2), round(self.hook[1], 2))
        elif kind in ("bleep_a", "bleep_b"):
            bl = self.bleeps[extra]
            key = bl[3] if len(bl) > 3 else bl[0]
            self.bleep_resized.emit(key, round(bl[0], 2), round(bl[1], 2))
        elif kind == "sel" and self.sel:
            a, b = sorted(self.sel)
            if b - a >= 0.1:
                self.selection_changed.emit(round(a, 2), round(b, 2))
            else:
                self.sel = None
        self.update()

    def wheelEvent(self, ev):
        """Колесо — масштаб вокруг мыши."""
        a, b = self.view
        t = self.t_of(ev.position().x())
        k = 0.8 if ev.angleDelta().y() > 0 else 1.25
        span = min(max(3.0, (b - a) * k), max(10.0, self.dur))
        left = t - (t - a) * span / (b - a)
        left = max(0.0, min(left, max(0.0, self.dur - span)))
        self.view = (left, left + span)
        self.update()


def wave_of(audio, start, sr=8000, step=0.05):
    """Громкость звука записи кусками по step секунд: [(время, 0..1)]."""
    import numpy as np
    x = np.asarray(audio, dtype=np.float32)
    n = max(1, int(sr * step))
    k = len(x) // n
    if not k:
        return []
    m = np.abs(x[:k * n].reshape(k, n)).max(axis=1)
    m = m / (float(m.max()) or 1.0)
    return [(start + i * step, float(v)) for i, v in enumerate(m)]


def estimate_dead(audio, start, words, sr=8000, min_len=3):
    """Мёртвые куски для старых нарезок (без сохранённых): секунды без слов и тише обычного —
    приблизительно, по громкости кусочка записи. [[начало, конец]] во времени записи."""
    import numpy as np
    x = np.asarray(audio, dtype=np.float32)
    n = len(x) // sr
    if n < min_len:
        return []
    rms = np.sqrt((x[:n * sr].reshape(n, sr) ** 2).mean(axis=1))
    quiet = rms < 0.6 * float(np.median(rms))
    for a, b in words:
        for i in range(max(0, int(a - start)), min(n, int(math.ceil(b - start)))):
            quiet[i] = False
    out, i = [], 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if j - i >= min_len:
                out.append([start + i, start + j])
            i = j
        else:
            i += 1
    return out
