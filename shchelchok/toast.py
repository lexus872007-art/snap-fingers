# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Короткое сообщение в фирменном стиле в правом нижнем углу экрана: «Свернул» (на 1 с), «Вернул», «Программа уже
открыта», «Клавиша занята», «Жду микрофон». Не забирает фокус, исчезает сама (под мышкой - ждёт)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import brand

W = 420
PAD = 14


def wrap(text, fm, width):
    lines = []
    for para in (text or "").split("\n"):
        cur = ""
        for word in para.split(" "):
            cand = (cur + " " + word).strip()
            if fm.horizontalAdvance(cand) <= width or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def toast_layout(title, text):
    fm_t = QFontMetricsF(brand.font(16, QFont.ExtraBold))
    fm_x = QFontMetricsF(brand.font(13, QFont.DemiBold))
    tw = W - 2 * PAD
    th = fm_t.height()
    lines = wrap(text, fm_x, tw)[:4]
    xh = fm_x.lineSpacing() * len(lines)
    out = {"title": QRectF(PAD, PAD - 2, tw - 24, th), "text": QRectF(PAD, PAD - 2 + th + 4, tw, xh),
           "close": QRectF(W - PAD - 18, PAD - 4, 22, 22), "lines": lines}
    return out, int(PAD - 2 + th + 4 + xh + PAD)


class Toast(QWidget):
    def __init__(self, ctl):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
                         | Qt.NoDropShadowWindowHint)
        self.ctl = ctl
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setWindowTitle("Уведомление")
        self.title = self.text = ""
        self.lay = None
        self.hover = False
        self.t = QTimer(self)
        self.t.setSingleShot(True)
        self.t.timeout.connect(self._maybe_hide)

    def show_message(self, title, text, ms=6000):
        self.title, self.text = title, text
        self.lay, h = toast_layout(title, text)
        self.setFixedSize(W, h)
        self.place(h)
        self.show()
        self.raise_()
        self.ctl.on_window_shown(self)
        self.t.start(ms)
        self.update()

    def place(self, h):
        """Правый нижний угол основного монитора (над панелью задач)."""
        from PySide6.QtGui import QGuiApplication
        g = QGuiApplication.primaryScreen().availableGeometry()
        self.move(g.right() - W - 16, g.bottom() - h - 16)

    def _maybe_hide(self):
        if self.underMouse():
            self.t.start(1500)
        else:
            self.hide()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        img = brand.flow_image(w, h, 2.6, energy=0.25, dpr=self.devicePixelRatioF())
        p.setPen(Qt.NoPen)
        p.setBrush(img)
        p.drawPath(brand.rounded(QRectF(0, 0, w, h), 14))
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(brand.rounded(QRectF(0.5, 0.5, w - 1, h - 1), 13.5))
        L = self.lay
        p.setFont(brand.font(16, QFont.ExtraBold))
        brand.shadow_text(p, L["title"], Qt.AlignLeft | Qt.AlignTop, self.title)
        p.setFont(brand.font(13, QFont.DemiBold))
        brand.shadow_text(p, L["text"], Qt.AlignLeft | Qt.AlignTop, "\n".join(L["lines"]), brand.tint(QColor(240, 232, 255)))
        cr = L["close"]
        if self.hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 50))
            p.drawEllipse(cr)
        brand.draw_icon(p, "close", cr.adjusted(4, 4, -4, -4), QColor(255, 255, 255, 220))
        p.end()

    def mouseMoveEvent(self, ev):
        h = self.lay["close"].contains(ev.position())
        if h != self.hover:
            self.hover = h
            self.setCursor(Qt.PointingHandCursor if h else Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, ev):
        self.hide()
