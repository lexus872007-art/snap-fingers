# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Общее для окон «Текст» и «Настройки»: фирменный перелив фоном, «стеклянные» панели, стили кнопок и полей,
шрифт Manrope явно (стили Qt не знают про начертания). Окна не видно в записи экрана."""
from __future__ import annotations

import os
import tempfile
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QFrame, QKeySequenceEdit, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from . import brand, settings

QSS = """
QWidget#flowwin { background: transparent; }
QLabel { color: white; background: transparent; }
QLabel#hint { color: #F0E8FF; }
QLabel#err { color: #FFD60A; }
QLabel#key { color: #FFE9A0; }
QFrame#glass { background: rgba(20, 0, 60, 110); border: 1px solid rgba(255, 255, 255, 50); border-radius: 12px; }
QCheckBox, QRadioButton { color: white; spacing: 9px; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1.5px solid rgba(255,255,255,200);
                       background: rgba(255,255,255,30); }
QCheckBox::indicator:checked { background: #FFD60A; border-color: #FFD60A; image: url(CHECK); }
QCheckBox:disabled { color: rgba(255,255,255,110); }
QCheckBox::indicator:checked:disabled { background: rgba(255,214,10,90); border-color: rgba(255,214,10,90); }
QRadioButton::indicator { width: 16px; height: 16px; border-radius: 9px; border: 1.5px solid rgba(255,255,255,200);
                          background: rgba(255,255,255,30); }
QRadioButton::indicator:checked { background: #FFD60A; border: 4px solid #4C1D95; }
QKeySequenceEdit, QLineEdit, QSpinBox, QComboBox { background: rgba(255,255,255,235); color: #2A0A5E; border: none;
        border-radius: 8px; padding: 4px 8px; selection-background-color: #C084FC; min-height: 22px; }
QComboBox QAbstractItemView { background: white; color: #2A0A5E; selection-background-color: #EDE9FE;
                              selection-color: #2A0A5E; }
QComboBox::drop-down { border: none; width: 22px; }
QSpinBox::up-button, QSpinBox::down-button { width: 18px; border: none; }
QPlainTextEdit { background: rgba(255,255,255,240); color: #1E0A46; border: none; border-radius: 10px; padding: 8px;
                 selection-background-color: #C084FC; }
QPushButton { color: white; background: rgba(30,0,80,120); border: 1px solid rgba(255,255,255,45); border-radius: 9px;
              padding: 6px 14px; }
QPushButton:hover { background: rgba(30,0,80,170); border-color: rgba(255,255,255,90); }
QPushButton#primary { background: white; color: #4C1D95; }
QPushButton#primary:hover { background: #EDE9FE; }
QPushButton#primary:disabled { background: rgba(255,255,255,90); color: rgba(76,29,149,140); }
QPushButton#quiet { background: transparent; border: none; color: #F0E8FF; text-decoration: underline; padding: 6px 4px; }
QPushButton#link { background: transparent; border: none; color: #FFD60A; text-decoration: underline; padding: 0px 2px; }
QSlider::groove:horizontal { height: 6px; border-radius: 3px; background: rgba(255,255,255,70); }
QSlider::sub-page:horizontal { height: 6px; border-radius: 3px; background: #FFD60A; }
QSlider::handle:horizontal { width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: white; }
QToolTip { background: #2A0A5E; color: white; border: 1px solid rgba(255,255,255,70); border-radius: 6px; padding: 5px 8px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 2px; }
QScrollBar::handle:vertical { background: rgba(76,29,149,120); border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def check_icon_path():
    """Галочка для QCheckBox (стили Qt берут картинку из файла) - рисуем один раз во временную папку."""
    path = os.path.join(tempfile.gettempdir(), f"{settings.APP}-check-{brand.theme_name()}{brand.tint_rgb(76, 29, 149)}.png")
    if not os.path.exists(path):
        img = QImage(36, 36, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        brand.draw_icon(p, "check", QRectF(4, 4, 28, 28), brand.tint(QColor(76, 29, 149)), lw=4.5)
        p.end()
        img.save(path)
    return path.replace("\\", "/")


def qss():
    return brand.tint_css(QSS).replace("CHECK", check_icon_path())


def glass(caption=None):
    f = QFrame()
    f.setObjectName("glass")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 9, 16, 10)
    lay.setSpacing(6)
    if caption:
        h = QLabel(caption)
        h.setFont(brand.font(15, QFont.ExtraBold))
        lay.addWidget(h)
    return f, lay


def label(text, size=14, weight=QFont.DemiBold, obj=None, wrap=False):
    lb = QLabel(text)
    lb.setFont(brand.font(size, weight))
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def fix_fonts(root):
    """Кнопкам, галочкам и полям - фирменный шрифт явно; надписи со своим шрифтом не трогаем."""
    for c in root.findChildren(QWidget):
        if c.testAttribute(Qt.WA_SetFont):
            continue
        if isinstance(c, (QPushButton, QLineEdit, QKeySequenceEdit, QSpinBox, QComboBox)):
            c.setFont(brand.font(14, QFont.Bold))
        elif isinstance(c, QPlainTextEdit):
            c.setFont(brand.font(16, QFont.DemiBold))
        elif isinstance(c, (QAbstractButton, QLabel)):
            c.setFont(brand.font(14, QFont.DemiBold))


class FlowWindow(QWidget):
    """Окно с фирменным переливом фоном (кадры ~15 в секунду, пока окно открыто)."""

    def __init__(self, ctl, title):
        super().__init__(None, Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowTitleHint | Qt.WindowStaysOnTopHint)
        self.ctl = ctl
        self.setObjectName("flowwin")
        self.setWindowTitle(title)
        self.setWindowIcon(ctl.icon)
        self.setStyleSheet(qss())
        self.setFont(brand.font(14, QFont.DemiBold))
        self.t0 = time.monotonic()
        self.t_fixed = None
        self.flow_timer = QTimer(self)
        self.flow_timer.setInterval(66)
        self.flow_timer.timeout.connect(self.update)

    def showEvent(self, ev):
        self.flow_timer.start()
        self.ctl.on_window_shown(self)

    def hideEvent(self, ev):
        self.flow_timer.stop()

    def paintEvent(self, ev):
        p = QPainter(self)
        t = self.t_fixed if self.t_fixed is not None else time.monotonic() - self.t0 + 1.3
        img = brand.flow_image(self.width(), self.height(), t, dpr=self.devicePixelRatioF())
        p.drawImage(QRectF(0, 0, self.width(), self.height()), img)
        p.end()
