"""Окно «Вышла новая версия» для программ на Qt (Маркер на экране, Суфлёр, Щелчок): что нового, кнопки
«Обновить» и «Позже», прогресс скачивания в том же окне.

Ничего не качается и не ставится без ответа человека (владелец 16.10.2026). «Позже» - не спрашиваем неделю;
включена галочка «Ставить сразу, не спрашивая» - окно показывает только прогресс.

Окно самодостаточное: из программы берёт только её `brand` (перелив, шрифт, иконки) и название. Механизм -
app_update.Controller, он же приносит сюда строки прогресса в потоке окна.
КОПИЯ ~/office_tools/_brand/app_update_qt.py - не править копии, раздаёт python3 _brand/sync.py.
"""
from __future__ import annotations

import os
import tempfile
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import (QAbstractButton, QCheckBox, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton,
                               QVBoxLayout, QWidget)

try:
    from . import brand, settings
except ImportError:                      # отдельная проверка вида вне пакета программы
    import brand
    import settings

QSS = """
QWidget#updwin { background: transparent; }
QLabel { color: white; background: transparent; }
QLabel#hint { color: #F0E8FF; }
QLabel#key { color: #FFE9A0; }
QFrame#glass { background: rgba(20, 0, 60, 110); border: 1px solid rgba(255, 255, 255, 50); border-radius: 12px; }
QCheckBox { color: white; spacing: 9px; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1.5px solid rgba(255,255,255,200);
                       background: rgba(255,255,255,30); }
QCheckBox::indicator:checked { background: #FFD60A; border-color: #FFD60A; image: url(CHECK); }
QPushButton { color: white; background: rgba(30,0,80,120); border: 1px solid rgba(255,255,255,45); border-radius: 9px;
              padding: 6px 14px; }
QPushButton:hover { background: rgba(30,0,80,170); border-color: rgba(255,255,255,90); }
QPushButton#primary { background: white; color: #4C1D95; }
QPushButton#primary:hover { background: #EDE9FE; }
QToolTip { background: #2A0A5E; color: white; border: 1px solid rgba(255,255,255,70); border-radius: 6px; padding: 5px 8px; }
"""


def accent():
    """Цвет галочки в текущем «Цвете оформления» (у программ линейки два имени одного и того же)."""
    tc = getattr(brand, "tc", None)
    if tc is not None:
        return tc(76, 29, 149)
    return brand.tint(QColor(76, 29, 149))


def tint_css(css):
    fn = getattr(brand, "tq", None) or brand.tint_css
    return fn(css)


def check_icon_path():
    """Галочка для QCheckBox (стили Qt берут картинку из файла) - рисуем один раз во временную папку."""
    c = accent()
    path = os.path.join(tempfile.gettempdir(), f"{settings.APP}-upd-check-{c.name()[1:]}.png")
    if not os.path.exists(path):
        img = QImage(36, 36, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        brand.draw_icon(p, "check", QRectF(4, 4, 28, 28), c, lw=4.5)
        p.end()
        img.save(path)
    return path.replace("\\", "/")


def label(text, size=14, weight=QFont.DemiBold, obj=None, wrap=False):
    lb = QLabel(text)
    lb.setFont(brand.font(size, weight))
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def glass():
    f = QFrame()
    f.setObjectName("glass")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 12, 16, 14)
    lay.setSpacing(8)
    return f, lay


class UpdateWindow(QWidget):
    """upd - app_update.Controller; info - что ответил сервер; auto - сразу качать, не спрашивая."""

    def __init__(self, upd, info, auto=False, icon=None, title="", note="", on_shown=None):
        super().__init__(None, Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowTitleHint | Qt.WindowStaysOnTopHint)
        self.upd = upd
        self.info = info or {}
        self.on_shown = on_shown
        self.setObjectName("updwin")
        self.setWindowTitle(f"{title} - новая версия")
        if icon is not None:
            self.setWindowIcon(icon)
        self.setStyleSheet(tint_css(QSS).replace("CHECK", check_icon_path()))
        self.setFont(brand.font(14, QFont.DemiBold))
        self.t0 = time.monotonic()
        self.t_fixed = None            # замереть на одном кадре перелива: снимки для проверки вида
        self.flow_timer = QTimer(self)
        self.flow_timer.setInterval(66)
        self.flow_timer.timeout.connect(self.update)

        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SetMinimumSize)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)
        root.addWidget(label(f"Вышла версия {self.info.get('version', '')}", 22, QFont.ExtraBold))
        g, lay = glass()
        self.what = label(self.notes_text(), 14, QFont.DemiBold, wrap=True)
        self.what.setMinimumWidth(460)
        lay.addWidget(self.what)
        self.state = label("", 13, QFont.Bold, "key", wrap=True)
        self.state.setVisible(False)
        lay.addWidget(self.state)
        root.addWidget(g)
        root.addWidget(label(note or "Ваши настройки останутся как есть. Обновления бесплатные.",
                             12, QFont.DemiBold, "hint", wrap=True))
        self.cb_auto = QCheckBox("Ставить обновления сразу, не спрашивая")
        self.cb_auto.setChecked(bool(upd.u.s.get("update_auto")))
        self.cb_auto.setToolTip("Тогда в следующий раз программа скачает новую версию и поставит её сама.\n"
                                "Проверять обновления можно выключить в настройках.")
        self.cb_auto.toggled.connect(upd.set_auto)
        root.addWidget(self.cb_auto)
        bot = QHBoxLayout()
        bot.addStretch(1)
        self.later_b = QPushButton("Позже")
        self.later_b.clicked.connect(self.later)
        bot.addWidget(self.later_b)
        self.go_b = QPushButton("Обновить")
        self.go_b.setObjectName("primary")
        self.go_b.setDefault(True)
        self.go_b.clicked.connect(self.start)
        bot.addWidget(self.go_b)
        root.addLayout(bot)
        self.fix_fonts()
        if auto:
            self.start()

    def fix_fonts(self):
        """Кнопкам и галочкам - фирменный шрифт явно (стили Qt не знают про начертания)."""
        for c in self.findChildren(QWidget):
            if c.testAttribute(Qt.WA_SetFont):
                continue
            if isinstance(c, QPushButton):
                c.setFont(brand.font(14, QFont.Bold))
            elif isinstance(c, (QAbstractButton, QLabel)):
                c.setFont(brand.font(14, QFont.DemiBold))

    def notes_text(self):
        notes = str(self.info.get("notes") or "").strip()
        return f"Что нового: {notes}" if notes else "Что нового - написано на сайте."

    # ------------------------------------------------------------ кнопки
    def later(self):
        self.upd.later(self.info)
        self.close()

    def start(self):
        """«Обновить»: качаем с прогрессом прямо в этом окне, потом запускаем установку и закрываемся."""
        self.go_b.setVisible(False)
        self.later_b.setText("Отмена")
        self.later_b.clicked.disconnect()
        self.later_b.clicked.connect(self.cancel)
        self.state.setText("Скачиваю новую версию…")
        self.state.setVisible(True)
        self.adjustSize()
        self.upd.download(self.info, self.progress, self.finished)

    def cancel(self):
        self.upd.cancel()
        self.close()

    def progress(self, text):
        """Строка прогресса (МБ, скорость, сколько осталось) - из того же модуля, что в установщике."""
        self.state.setText(text)

    def finished(self, ok, text):
        self.state.setText(text)
        self.later_b.setText("Закрыть")
        if not ok:
            self.go_b.setText("Повторить")
            self.go_b.setVisible(True)
        self.adjustSize()

    # ------------------------------------------------------------ вид
    def showEvent(self, ev):
        self.flow_timer.start()
        if self.on_shown is not None:
            self.on_shown(self)

    def hideEvent(self, ev):
        self.flow_timer.stop()

    def paintEvent(self, ev):
        p = QPainter(self)
        t = self.t_fixed if self.t_fixed is not None else time.monotonic() - self.t0 + 1.3
        img = brand.flow_image(self.width(), self.height(), t, dpr=self.devicePixelRatioF())
        p.drawImage(QRectF(0, 0, self.width(), self.height()), img)
        p.end()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.later()
            return
        super().keyPressEvent(ev)
