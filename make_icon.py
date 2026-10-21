# -*- coding: utf-8 -*-
"""Рисует иконку AutoClip: icon/autoclip.ico (все размеры) и icon/autoclip.png (256×256).
Рисуется кодом, без чужих картинок. Запуск: py -3.13 make_icon.py"""

import os
import struct
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPolygonF)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "icon")
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def draw(size):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)

    # фон: скруглённый квадрат с розовым градиентом — цвет кнопок программы
    m = s * 0.04
    bg = QRectF(m, m, s - 2 * m, s - 2 * m)
    g = QLinearGradient(bg.topLeft(), bg.bottomRight())
    g.setColorAt(0.0, QColor("#ff7a92"))
    g.setColorAt(1.0, QColor("#e3284f"))
    path = QPainterPath()
    path.addRoundedRect(bg, s * 0.23, s * 0.23)
    p.fillPath(path, g)

    # две вертикальные «карточки клипа» 9:16: задняя полупрозрачная, передняя белая
    cw, ch = s * 0.40, s * 0.40 * 16 / 9 * 0.86
    r = s * 0.07

    def card(dx, angle, color):
        p.save()
        p.translate(s / 2 + dx, s / 2 + s * 0.01)
        p.rotate(angle)
        rp = QPainterPath()
        rp.addRoundedRect(QRectF(-cw / 2, -ch / 2, cw, ch), r, r)
        p.fillPath(rp, color)
        p.restore()

    if size >= 24:                               # на самых маленьких — одна карточка, чётче
        card(-s * 0.10, -13, QColor(255, 255, 255, 105))
    card(s * 0.05 if size >= 24 else 0, 6 if size >= 24 else 0, QColor("#ffffff"))

    # кнопка ▶ на передней карточке
    p.save()
    p.translate(s / 2 + (s * 0.05 if size >= 24 else 0), s / 2 + s * 0.01)
    p.rotate(6 if size >= 24 else 0)
    t = s * 0.13
    tri = QPolygonF([QPointF(-t * 0.42, -t * 0.55), QPointF(-t * 0.42, t * 0.55),
                     QPointF(t * 0.58, 0)])
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#e3284f"))
    p.drawPolygon(tri)
    p.restore()
    p.end()
    return img


def png_bytes(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def write_ico(path, images):
    """ICO с PNG внутри — так Windows хранит иконки всех размеров в одном файле."""
    pngs = [png_bytes(im) for im in images]
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, data = b"", b""
    for im, png in zip(images, pngs):
        w = im.width() if im.width() < 256 else 0     # 0 означает 256
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    with open(path, "wb") as f:
        f.write(head + entries + data)


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841
    os.makedirs(OUT, exist_ok=True)
    images = [draw(n) for n in SIZES]
    write_ico(os.path.join(OUT, "autoclip.ico"), images)
    images[-1].save(os.path.join(OUT, "autoclip.png"))
    print("готово:", os.path.join(OUT, "autoclip.ico"))


if __name__ == "__main__":
    main()
