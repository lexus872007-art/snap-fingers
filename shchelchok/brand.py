# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Фирменный перелив плашки Local Voice в Qt, шрифт Manrope, значки (рисуются линиями - без файлов картинок).
Взято из «Суфлёра» / «Маркера на экране» - формула перелива одна на всю линейку.

Перелив - ТОЧНАЯ формула эталона (whisper_tray.py Painter): цвет = LUT[(0.8·x + 0.45·y + фаза) mod 1], x, y - доли
ширины и высоты. Полосы зависят только от u = 0.8·x/W + 0.45·y/H, то есть это линейный градиент вдоль вектора
g = (0.8/W, 0.45/H): от точки S = -фаза·g/|g|² до S + g/|g|² u+фаза проходит ровно 0..1, повтор (RepeatSpread) даёт
mod 1. Пятна: + exp(-((x-cx)² + 2.5·(y-cy)²)·9)·(28 + 60·energy) к каждому каналу = белый радиальный градиент со
сложением (CompositionMode_Plus) в растянутых координатах (y·√2.5). Векторно - чётко при любом масштабе экрана.
"""
from __future__ import annotations

import math
import os
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)

# «Цвет оформления» (владелец 15.10) - ОБЩИЙ код линейки: brand_theme.py (копия ~/office_tools/_brand, раздаёт
# sync.py; поворот оттенка в OKLCH - светлота и насыщенность те же, что у фиолетового). Перелив (направление полос,
# скорость, 2 пятна, формула) не меняется, жёлтые и зелёные акценты не трогаем. «Графит» - та же палитра почти без
# цвета, «Свой» - любой оттенок ползунком. Значение темы - строка: "blue" | … | "custom:200".
from . import brand_theme as bt           # noqa: E402

BASE_PALETTE = list(bt.PALETTE)
PALETTE = list(BASE_PALETTE)
THEMES = [(k, n, h) for k, n, h, _c in bt.PRESETS] + [("custom", bt.CUSTOM_LABEL, None)]
_theme = {"value": bt.DEFAULT}


def theme_value():
    """Значение темы строкой ("violet" | "custom:200") - как хранят 13, 18 и веб-окна."""
    return _theme["value"]


def theme_name():
    return bt.parse(_theme["value"])[0]


def theme_hue():
    """Оттенок «Своего» (градусы) или None у пресета."""
    return bt.parse(_theme["value"])[1] if theme_name() == "custom" else None


def tint_rgb(r, g, b):
    """Цвет фирменной (фиолетовой) гаммы -> тот же цвет в выбранной теме. Остальные цвета (белый, жёлтый,
    зелёный) - без изменений."""
    return tuple(bt.tint((r, g, b), _theme["value"]))


def tint(c) -> QColor:
    c = QColor(c)
    r, g, b = tint_rgb(c.red(), c.green(), c.blue())
    return QColor(r, g, b, c.alpha())


def tint_css(css: str) -> str:
    """Стили Qt: все цвета гаммы (#RRGGBB, rgb(), rgba()) - в выбранный оттенок."""
    return bt.tint_text(css, _theme["value"])


def set_theme(name="violet", hue=None):
    """Выбрать цвет оформления: имя пресета или ("custom", оттенок). -> имя темы (неизвестное -> фиолетовый)."""
    global PALETTE
    value = name if name is not None else bt.DEFAULT
    if str(value).startswith("custom") and not str(value).startswith("custom:"):
        try:
            value = f"custom:{int(float(hue)) % 360}"
        except (TypeError, ValueError):
            value = f"custom:{bt.CUSTOM_DEFAULT_HUE}"
    _theme["value"] = bt.normalize(value)
    PALETTE = [tuple(c) for c in bt.palette(_theme["value"])]
    return theme_name()
SPEED_IDLE, SPEED_WORK = 0.08, 0.35
YELLOW = QColor(255, 214, 10)
FAMILY = "Segoe UI"


def base_dir():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_fonts():
    """Manrope (OFL) из ui/fonts - одинаковые буквы на любом компьютере. Статические файлы 600/700/800
    (tools/make_fonts.py): переменный шрифт старый движок Windows рисует самым тонким начертанием."""
    global FAMILY
    fams = []
    for style in ("SemiBold", "Bold", "ExtraBold"):
        fid = QFontDatabase.addApplicationFont(os.path.join(base_dir(), "ui", "fonts", f"Manrope-{style}.ttf"))
        if fid >= 0:
            fams += QFontDatabase.applicationFontFamilies(fid)
    if "Manrope" in fams:
        FAMILY = "Manrope"
    return FAMILY


def set_weight(f: QFont, weight):
    f.setWeight(weight)
    return f


def font(px, weight=QFont.Bold):
    f = QFont(FAMILY)
    f.setPixelSize(max(6, int(round(px))))
    return set_weight(f, weight)


def stripes_gradient(w, h, phase):
    gx, gy = 0.8 / w, 0.45 / h
    n2 = gx * gx + gy * gy
    dx, dy = gx / n2, gy / n2
    s = QPointF(-phase * dx, -phase * dy)
    g = QLinearGradient(s, QPointF(s.x() + dx, s.y() + dy))
    pal = PALETTE + [PALETTE[0]]
    for i, c in enumerate(pal):
        g.setColorAt(i / (len(pal) - 1), QColor(*c))
    g.setSpread(QLinearGradient.RepeatSpread)
    return g


def paint_flow(p: QPainter, w, h, t, speed=SPEED_IDLE, energy=0.0):
    """Кадр перелива в прямоугольник 0,0,w,h (логические точки)."""
    p.save()
    p.setPen(Qt.NoPen)
    p.fillRect(QRectF(0, 0, w, h), stripes_gradient(w, h, (t * speed) % 1.0))
    amp = (28 + 60 * max(0.0, energy)) / 255.0
    sq = math.sqrt(2.5)
    p.setCompositionMode(QPainter.CompositionMode_Plus)
    for k, (fx, fy) in enumerate(((0.9, 0.6), (0.6, 0.9))):
        cx = 0.5 + 0.45 * math.sin(t * fx + k * 2.1)
        cy = 0.5 + 0.45 * math.cos(t * fy + k * 1.3)
        p.save()
        p.scale(w, h / sq)                      # единица по x = ширина, по y = высота/√2.5
        rad = 0.8                               # exp(-9·0.8²) = 0,3 % - дальше пятна нет
        rg = QRadialGradient(QPointF(cx, cy * sq), rad)
        for i in range(9):
            r = i / 8
            a = math.exp(-9 * (r * rad) ** 2) * amp
            rg.setColorAt(r, QColor(255, 255, 255, int(round(255 * a))))
        p.setBrush(rg)
        p.drawRect(QRectF(0, 0, 1, sq))
        p.restore()
    p.restore()


def flow_image(w, h, t, speed=SPEED_IDLE, energy=0.0, dpr=1.0) -> QImage:
    img = QImage(max(1, int(math.ceil(w * dpr))), max(1, int(math.ceil(h * dpr))), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(*PALETTE[1]))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    paint_flow(p, w, h, t, speed, energy)
    p.end()
    return img


def rounded(r: QRectF, radius) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    return path


def shadow_text(p: QPainter, rect: QRectF, flags, text, color=QColor("white"), d=1.0):
    """Текст с тёмной тенью, как на плашке Local Voice: читается и на светлых полосах."""
    p.save()
    p.setPen(tint(QColor(20, 0, 60, 150)))
    p.drawText(rect.translated(d, d), flags, text)
    p.setPen(color)
    p.drawText(rect, flags, text)
    p.restore()


# ---------------------------------------------------------------- значки
def draw_icon(p: QPainter, name: str, r: QRectF, color=QColor("white"), lw=None):
    """Значок в квадрате r: линии толщиной ~1/11 стороны, скруглённые концы (сетка 24x24)."""
    s = min(r.width(), r.height())
    lw = lw or max(1.4, s / 11)
    cx, cy = r.center().x(), r.center().y()
    u = s / 24.0

    def P(x, y):
        return QPointF(cx + (x - 12) * u, cy + (y - 12) * u)

    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color, lw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    def poly(*pts, close=False, fill=None):
        path = QPainterPath(P(*pts[0]))
        for q in pts[1:]:
            path.lineTo(P(*q))
        if close:
            path.closeSubpath()
        if fill is not None:
            p.setBrush(fill)
        p.drawPath(path)
        p.setBrush(Qt.NoBrush)

    if name == "play":
        poly((8, 5), (19, 12), (8, 19), close=True, fill=color)
    elif name == "pause":
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(P(6.5, 5), P(10.5, 19)), 1.2 * u, 1.2 * u)
        p.drawRoundedRect(QRectF(P(13.5, 5), P(17.5, 19)), 1.2 * u, 1.2 * u)
    elif name == "minus":
        poly((6, 12), (18, 12))
    elif name == "plus":
        poly((6, 12), (18, 12))
        poly((12, 6), (12, 18))
    elif name == "home":                      # в начало: стрелка вверх к черте
        poly((6, 5), (18, 5))
        poly((12, 20), (12, 9))
        poly((7.5, 13), (12, 8.5), (16.5, 13))
    elif name == "text":                      # лист с строками
        poly((6, 3.5), (14.5, 3.5), (19, 8), (19, 20.5), (6, 20.5), close=True)
        poly((14.5, 3.5), (14.5, 8), (19, 8))
        poly((9, 12), (16, 12))
        poly((9, 15.5), (16, 15.5))
    elif name == "gear":
        p.drawEllipse(QRectF(P(9, 9), P(15, 15)))
        for a in range(0, 360, 45):
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            p.drawLine(P(12 + 5.5 * ca, 12 + 5.5 * sa), P(12 + 8.5 * ca, 12 + 8.5 * sa))
        p.drawEllipse(QRectF(P(6.5, 6.5), P(17.5, 17.5)))
    elif name == "close":
        poly((7, 7), (17, 17))
        poly((17, 7), (7, 17))
    elif name in ("mic", "mic_off"):
        p.drawRoundedRect(QRectF(P(9, 3.5), P(15, 14.5)), 3 * u, 3 * u)
        path = QPainterPath(P(6, 11.5))
        path.cubicTo(P(6, 19), P(18, 19), P(18, 11.5))
        p.drawPath(path)
        poly((12, 17.5), (12, 21))
        poly((9, 21), (15, 21))
        if name == "mic_off":
            poly((4, 20), (20, 4))
    elif name == "font":                      # «Аа»
        poly((3.5, 19), (8.5, 5.5), (13.5, 19))
        poly((5.5, 14), (11.5, 14))
        p.drawEllipse(QRectF(P(14, 12), P(20, 19)))
        poly((20, 11.5), (20, 19))
    elif name == "grip":
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        for x in (9.5, 14.5):
            for y in (7, 12, 17):
                p.drawEllipse(P(x, y), 1.3 * u, 1.3 * u)
    elif name == "check":
        poly((5, 12.5), (10, 17.5), (19, 7))
    elif name == "eye_off":
        path = QPainterPath(P(2.5, 12))
        path.quadTo(P(12, 2.5), P(21.5, 12))
        path.quadTo(P(12, 21.5), P(2.5, 12))
        p.drawPath(path)
        p.drawEllipse(QRectF(P(9, 9), P(15, 15)))
        poly((4, 20), (20, 4))
    p.restore()


def draw_spark(p: QPainter, cx, cy, r, color=QColor("white"), center=YELLOW, lw=None):
    """Знак «щелчок»: лучи вокруг жёлтой точки (как вспышка от щелчка пальцами)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    lw = lw or r * 0.16
    p.setPen(QPen(color, lw, Qt.SolidLine, Qt.RoundCap))
    for i in range(8):
        a = math.radians(i * 45 - 90)
        r0, r1 = (0.42, 1.0) if i % 2 == 0 else (0.48, 0.78)
        p.drawLine(QPointF(cx + r0 * r * math.cos(a), cy + r0 * r * math.sin(a)),
                   QPointF(cx + r1 * r * math.cos(a), cy + r1 * r * math.sin(a)))
    p.setPen(Qt.NoPen)
    p.setBrush(center)
    p.drawEllipse(QPointF(cx, cy), r * 0.22, r * 0.22)
    p.restore()


def app_icon_image(size=256, paused=False) -> QImage:
    """Значок программы: перелив в скруглённом квадрате и белая «вспышка щелчка» с жёлтой серединой.
    paused - приглушённый (значок в трее, когда программа на паузе)."""
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    r = QRectF(0, 0, size, size)
    fl = flow_image(size, size, 1.7, energy=0.3)
    p.setPen(Qt.NoPen)
    p.setBrush(fl)
    p.drawPath(rounded(r, size * 0.22))
    p.setBrush(tint(QColor(20, 0, 60, 170 if paused else 70)))
    p.drawPath(rounded(r, size * 0.22))
    col = QColor(255, 255, 255, 150 if paused else 255)
    mid = QColor(170, 160, 190) if paused else YELLOW
    draw_spark(p, size * 0.5, size * 0.5, size * 0.38, col, mid, lw=size * 0.075)
    p.end()
    return img
