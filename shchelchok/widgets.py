"""Шкалы для окон: уровень микрофона, оценки последних звуков с порогом (как «чувствительность с оценкой каждого
звука»), точки калибровки. Рисуются сами - без картинок."""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import brand

GREEN = QColor(74, 222, 128)


class LevelMeter(QWidget):
    """Громкость микрофона: полоска (дБ -70..0)."""

    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.setFixedHeight(14)
        self.setMinimumWidth(160)
        self.fixed = None             # для снимков (--demo)

    @staticmethod
    def frac(db):
        return max(0.0, min(1.0, (db + 70.0) / 70.0))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 45))
        p.drawRoundedRect(QRectF(0, 2, w, h - 4), 5, 5)
        lv = self.fixed if self.fixed is not None else self.ctl.mic_level()
        if lv is not None:
            p.setBrush(brand.tint(QColor(200, 190, 225)))
            p.drawRoundedRect(QRectF(0, 2, max(6.0, w * self.frac(lv)), h - 4), 5, 5)
        p.end()


class ScoreBar(QWidget):
    """Оценки последних звуков 0-100: точки на шкале, жёлтая черта - порог («это щелчок» правее)."""

    H = 34

    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.setFixedHeight(self.H)
        self.setMinimumWidth(220)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        y = 12.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 45))
        p.drawRoundedRect(QRectF(0, y - 4, w, 8), 4, 4)
        thr = self.ctl.threshold()
        x_thr = w * thr / 100.0
        p.setBrush(QColor(74, 222, 128, 70))
        p.drawRoundedRect(QRectF(x_thr, y - 4, w - x_thr, 8), 4, 4)
        now = time.monotonic()
        for i, (t, sc, ok) in enumerate(self.ctl.recent_scores()):
            age = max(0.0, now - t) if t else 0.0
            a = int(255 * max(0.25, 1.0 - age / 30.0))
            c = QColor(GREEN if ok else QColor(255, 255, 255))
            c.setAlpha(a)
            p.setBrush(c)
            p.drawEllipse(QPointF(max(5.0, min(w - 5.0, w * sc / 100.0)), y), 5, 5)
        p.setBrush(brand.YELLOW)
        p.drawRoundedRect(QRectF(x_thr - 1.5, y - 9, 3, 18), 1.5, 1.5)
        p.setFont(brand.font(12, QFont.Bold))
        p.setPen(brand.tint(QColor(240, 232, 255)))
        p.drawText(QRectF(0, y + 8, w / 2, self.H - y - 8), Qt.AlignLeft | Qt.AlignVCenter, "не щелчок")
        p.drawText(QRectF(w / 2, y + 8, w / 2, self.H - y - 8), Qt.AlignRight | Qt.AlignVCenter, "щелчок")
        p.end()


class Dots(QWidget):
    """Калибровка: 3 кружка, закрашенные - услышанные щелчки."""

    def __init__(self, n=3):
        super().__init__()
        self.n = n
        self.done = 0
        self.setFixedHeight(56)
        self.setMinimumWidth(220)

    def set_done(self, k):
        self.done = k
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = 22.0
        gap = 26.0
        total = self.n * 2 * r + (self.n - 1) * gap
        x0 = (self.width() - total) / 2 + r
        for i in range(self.n):
            c = QPointF(x0 + i * (2 * r + gap), self.height() / 2)
            if i < self.done:
                p.setPen(Qt.NoPen)
                p.setBrush(brand.YELLOW)
                p.drawEllipse(c, r, r)
                dark = brand.tint(QColor(76, 29, 149))
                brand.draw_spark(p, c.x(), c.y(), r * 0.72, dark, dark, lw=r * 0.13)
            else:
                p.setPen(QPen(QColor(255, 255, 255, 170), 2, Qt.DashLine))
                p.setBrush(QColor(255, 255, 255, 25))
                p.drawEllipse(c, r - 1, r - 1)
                p.setPen(QColor(255, 255, 255, 200))
                p.setFont(brand.font(18, QFont.ExtraBold))
                p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), Qt.AlignCenter, str(i + 1))
        p.end()
