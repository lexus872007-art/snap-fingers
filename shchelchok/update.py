"""Самообновление «Щелчка»: где на сервере лежит новая версия и как называется установщик.

Сам механизм - общий на всю линейку: app_update.py (копия ~/office_tools/_brand/app_update.py). Здесь только то,
что у программы своё: адрес, имя установщика и строка про настройки в окне вопроса.
"""
from __future__ import annotations

from . import app_update
from .app_update import Controller, Updater, newer, parse_info as _parse, sha256   # noqa: F401 - для тестов и окна

BASE = "https://ty-biznesmen.ru/apps/shchelchok"
SETUP = "Shchelchok-Setup.exe"
NOTE = "Ваши настройки и калибровка щелчка останутся как есть. Обновления бесплатные."
FIRST_DELAY = app_update.FIRST_DELAY


def make(version, settings, log=None, save=None, net=None, clock=None):
    """Проверка обновлений для этой программы (адрес и имя установщика уже подставлены)."""
    kw = {}
    if clock is not None:
        kw["clock"] = clock
    return Updater(version, settings, log=log, base=BASE, setup=SETUP, net=net, save=save, **kw)


def parse_info(data):
    """Ответ сервера -> проверенные поля (имя установщика по умолчанию - наше)."""
    return _parse(data, SETUP)
