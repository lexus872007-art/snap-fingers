"""«Цвет оформления» для окон Qt (PySide6) - КОПИЯ ~/office_tools/_brand (править там, раздавать: python3 _brand/sync.py).

ThemePicker - строка кружков пресетов + «Свой» (ползунок оттенка под кружками, inline=True - в той же строке).
Сигнал changed(str) - сразу при выборе и при ДВИЖЕНИИ ползунка (valueChanged): окно перекрашивается без
перезапуска, сохраняет программа (по «Сохранить» или сразу). Логика цветов - brand_theme.py (лежит рядом).

Ползунок оттенка показывается ТОЛЬКО при «Своём» (у пресета прятать, иначе непонятно, что он настраивает);
рядом с ним - образец выбранного цвета и число оттенка (жалоба владельца 15.10.2026: «цвет «Свой» не
настраивается» - ползунок был без подписи и перекрыт выпадающим списком).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QConicalGradient, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QSlider, QVBoxLayout, QWidget

try:
    from . import brand_theme as bt
except ImportError:                        # копия лежит не в пакете
    import brand_theme as bt

DOT, GAP = 24, 8
RAINBOW = ["#FF4D6D", "#FF9F1C", "#FFD60A", "#3DDC84", "#22D3EE", "#3B82F6", "#8B5CF6", "#EC4899", "#FF4D6D"]


class _Dots(QWidget):
    picked = Signal(str)

    def __init__(self, picker, dot=DOT, gap=GAP):
        super().__init__()
        self.p = picker
        self.dot, self.gap = dot, gap          # в узком окне кружки можно сделать мельче (ThemePicker(dot=20))
        self.items = [(k, n) for k, n, *_ in bt.PRESETS] + [("custom", bt.CUSTOM_LABEL)]
        self.hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(self.sizeHint())

    def sizeHint(self):
        n = len(self.items)
        return QSize(n * self.dot + (n - 1) * self.gap + 8, self.dot + 8)

    def rect_of(self, i):
        return QRectF(4 + i * (self.dot + self.gap), 4, self.dot, self.dot)

    def index_at(self, pos):
        for i in range(len(self.items)):
            if self.rect_of(i).adjusted(-3, -3, 3, 3).contains(QPointF(pos)):
                return i
        return -1

    def mouseMoveEvent(self, ev):
        i = self.index_at(ev.position())
        if i != self.hover:
            self.hover = i
            self.setToolTip(self.items[i][1] if i >= 0 else "")
            self.update()

    def leaveEvent(self, ev):
        self.hover = -1
        self.update()

    def mousePressEvent(self, ev):
        i = self.index_at(ev.position())
        if i >= 0:
            self.choose(i)

    def keyPressEvent(self, ev):
        cur = [k for k, _ in self.items].index(bt.parse(self.p.value)[0])
        d = {Qt.Key_Right: 1, Qt.Key_Down: 1, Qt.Key_Left: -1, Qt.Key_Up: -1}.get(ev.key())
        if d:
            self.choose((cur + d) % len(self.items))
        else:
            super().keyPressEvent(ev)

    def choose(self, i):
        key = self.items[i][0]
        self.picked.emit(f"custom:{self.p.last_hue}" if key == "custom" else key)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cur = bt.parse(self.p.value)[0]
        for i, (key, _name) in enumerate(self.items):
            r = self.rect_of(i)
            if i == self.hover:
                r = r.adjusted(-1.5, -1.5, 1.5, 1.5)
            if key == "custom":
                g = QConicalGradient(r.center(), 90)
                for j, c in enumerate(RAINBOW):
                    g.setColorAt(j / (len(RAINBOW) - 1), QColor(c))
                p.setBrush(g)
            else:
                p.setBrush(QColor(*bt.swatch(key)))
            on = key == cur
            p.setPen(QPen(QColor(255, 255, 255, 255 if on or i == self.hover else 100), 2))
            p.drawEllipse(r)
            if key == "custom" and on:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(*bt.swatch(self.p.value)))
                c = r.center()
                p.drawEllipse(c, r.width() * 0.22, r.height() * 0.22)
            if on:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(0, 0, 0, 110), 2))
                p.drawEllipse(r.adjusted(-3, -3, 3, 3))
                p.setPen(QPen(QColor("white"), 2))
                p.drawEllipse(r.adjusted(-4.5, -4.5, 4.5, 4.5))
        if self.hasFocus():
            i = [k for k, _ in self.items].index(cur)
            p.setPen(QPen(QColor("#FFD60A"), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(self.rect_of(i).adjusted(-6, -6, 6, 6))
        p.end()


class _Swatch(QWidget):
    """Маленький образец выбранного цвета рядом с ползунком оттенка."""

    def __init__(self, picker):
        super().__init__()
        self.p = picker
        self.setFixedSize(18, 18)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setBrush(QColor(*bt.swatch(self.p.value)))
        p.setPen(QPen(QColor(255, 255, 255, 170), 1.5))
        p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 5, 5)
        p.end()


class ThemePicker(QWidget):
    """picker = ThemePicker(value); picker.changed.connect(lambda v: ...) - v уже нормализовано.
    inline=True - ползунок оттенка в одной строке с кружками (для невысоких окон)."""
    changed = Signal(str)

    def __init__(self, value="violet", parent=None, font=None, inline=False, dot=DOT, gap=GAP):
        super().__init__(parent)
        self.value = bt.normalize(value)
        self.last_hue = bt.CUSTOM_DEFAULT_HUE
        if self.value.startswith("custom:"):
            self.last_hue = int(self.value.split(":")[1])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.dots = _Dots(self, dot, gap)
        self.dots.picked.connect(self.set_value)
        row.addWidget(self.dots)
        self.name = QLabel()
        if font is not None:
            self.name.setFont(font)
        self.name.setStyleSheet("color: rgba(255,255,255,220); background: transparent;")
        row.addWidget(self.name)
        self.hue = QSlider(Qt.Horizontal)
        self.hue.setRange(0, 359)
        self.hue.setAccessibleName("Оттенок")
        if not inline:            # строка ползунка не шире строки кружков (образец и число - в той же ширине)
            self.hue.setMaximumWidth(max(60, self.dots.sizeHint().width() - 76))
        else:
            self.hue.setMinimumWidth(140)
        stops = ", ".join(f"stop:{a / 360:.3f} rgb{bt.swatch(f'custom:{a}')}" for a in range(0, 361, 30))
        self.hue.setStyleSheet(
            "QSlider { background: transparent; min-height: 22px; }"
            f"QSlider::groove:horizontal {{ height: 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,110);"
            f" background: qlineargradient(x1:0, y1:0, x2:1, y2:0, {stops}); }}"
            "QSlider::handle:horizontal { width: 18px; height: 18px; margin: -4px 0; border-radius: 9px;"
            " background: white; border: 2px solid rgba(0,0,0,120); }"
            # закрашенная половина дорожки (жёлтая у ползунков громкости в окнах) радугу бы перекрыла
            "QSlider::sub-page:horizontal, QSlider::add-page:horizontal { background: transparent; border: none; }")
        self.hue.valueChanged.connect(self._slide)                 # цвет меняется ПРЯМО ПРИ ТАСКАНИИ
        self.swatch = _Swatch(self)
        self.hue_num = QLabel()
        if font is not None:
            self.hue_num.setFont(font)
        self.hue_num.setStyleSheet("color: rgba(255,255,255,220); background: transparent;")
        self.hue_num.setMinimumWidth(42)
        # ползунок + образец цвета + число оттенка - одной группой: показываем только у «Своего»
        self.hue_box = QWidget()
        hb = QHBoxLayout(self.hue_box)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(8)
        hb.addWidget(self.hue, 1)
        hb.addWidget(self.swatch)
        hb.addWidget(self.hue_num)
        sp = self.hue_box.sizePolicy()
        sp.setRetainSizeWhenHidden(True)              # окно не прыгает, когда ползунок появляется
        self.hue_box.setSizePolicy(sp)
        if inline:                       # кружки и ползунок одной строкой (окно ниже)
            row.addWidget(self.hue_box, 1)
            lay.addLayout(row)
        else:                            # ползунок под кружками
            row.addStretch(1)
            lay.addLayout(row)
            lay.addWidget(self.hue_box)
        self._sync()

    def _slide(self, v):
        if bt.parse(self.value)[0] == "custom" and v != self.last_hue:
            self.last_hue = v
            self.set_value(f"custom:{v}")

    def set_value(self, v, emit=True):
        v = bt.normalize(v)
        if v.startswith("custom:"):
            self.last_hue = int(v.split(":")[1])
        changed = v != self.value
        self.value = v
        self._sync()
        if emit and changed:
            self.changed.emit(v)

    def _sync(self):
        key = bt.parse(self.value)[0]
        self.name.setText(bt.CUSTOM_LABEL if key == "custom" else dict((k, n) for k, n, *_ in bt.PRESETS)[key])
        self.hue.blockSignals(True)
        self.hue.setValue(self.last_hue)
        self.hue.blockSignals(False)
        self.hue_num.setText(f"{self.last_hue}°")
        self.hue_box.setVisible(key == "custom")      # у пресета ползунок не показываем - он там ничего не меняет
        self.swatch.update()
        self.dots.update()
