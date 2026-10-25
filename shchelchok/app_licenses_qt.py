# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Строка «Открытые компоненты» с кнопкой «Открыть лицензии» для окон Qt (13, 18, 19).

Вид и слова - те же, что в веб-окнах линейки (`app_licenses.py`): заголовок, одна человеческая
строка и кнопка, которая открывает перечень компонентов в блокноте. Простыни лицензий в окне нет.

    from .app_licenses_qt import licenses_row
    row = licenses_row((brand.base_dir(),), font=brand.font, parent=self)   # None - файла лицензий рядом нет
    if row:
        layout.addWidget(row)

КОПИЯ ~/office_tools/_brand/app_licenses_qt.py - не править здесь: `python3 _brand/sync.py`.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from . import app_licenses


class LicensesRow(QWidget):
    """Одна строка: «Открытые компоненты», человеческая подпись и кнопка «Открыть лицензии» справа.

    В окнах Qt строка ОДНОСТРОЧНАЯ: окна «Маркера», «Суфлёра» и «Щелчка» и без того на пределе высоты
    (должны влезать в 1920x1080 при 150 %), а слова при этом те же, что в веб-окнах линейки."""

    def __init__(self, extra_dirs=(), font=None, parent=None, opener=None):
        super().__init__(parent)
        self._dirs = tuple(extra_dirs)
        self._opener = opener or app_licenses.open_licenses
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        title = QLabel(app_licenses.TITLE)
        hint = QLabel(app_licenses.SETTINGS_LINE)
        hint.setObjectName("hint")
        hint.setWordWrap(False)
        if font is not None:
            from PySide6.QtGui import QFont
            title.setFont(font(14, QFont.DemiBold))
            hint.setFont(font(12, QFont.DemiBold))
        lay.addWidget(title, 0, Qt.AlignVCenter)
        lay.addWidget(hint, 1, Qt.AlignVCenter)
        self.button = QPushButton(app_licenses.BUTTON)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setToolTip("Перечень сторонних открытых компонентов и их лицензии - файлом рядом с программой")
        self.button.clicked.connect(self.open_licenses)
        lay.addWidget(self.button, 0, Qt.AlignVCenter)

    def open_licenses(self):
        return self._opener(self._dirs)


def licenses_row(extra_dirs=(), font=None, parent=None, opener=None):
    """Готовая строка или None, если рядом с программой нет файла с перечнем лицензий."""
    if not app_licenses.components_file(extra_dirs):
        return None
    return LicensesRow(extra_dirs, font=font, parent=parent, opener=opener)
