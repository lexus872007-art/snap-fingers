# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Журнал самой программы - там же, где журнал установщика: %LOCALAPPDATA%\\Щелчок\\logs.

Было: `%APPDATA%\\Щелчок\\log.txt` - один файл, который сам себя обрезал пополам при 200 КБ, а установщик писал
в другое место. Стало (решение владельца 17.10.2026, долг 11): общий модуль `app_log` - файл на день
`shchelchok-ГГГГ-ММ-ДД.log` рядом с файлами установщика `shchelchok-install-ГГГГ-ММ-ДД.log`, одна запись -
одна строка со временем, и журнал «пишется бесконечно»: по времени не удаляется ничего, ограничение - общий
объём папки (200 МБ, это примерно четыре года), и про удаление старых дней в журнале остаётся строка.
Место переживает и обновление программы, и её удаление - по журналу разбирают жалобы.

Зачем журнал вообще (правило владельца 16.10.2026): «молча умирать нельзя». Поток микрофона отвалился и
программа его подняла - это обязано быть видно, иначе «не работает щелчок» не отличить от «не услышал».

Имена и подписи здесь прежние (`path`, `set_path`, `set_hook`, `write`, `tail`) - вызовы по программе те же,
изменилось только место файла. Окно «Что происходило» и кнопка «Журнал» остались как были, рядом с ними в
главном окне появилась кнопка «Показать журнал» (открывает папку журналов).
"""
from __future__ import annotations

import datetime
import os
import threading

from . import app_log
from .settings import APP, TITLE, config_dir

OLD_NAME = "log.txt"          # прежний файл журнала (остаётся лежать как есть)
_lock = threading.Lock()
_over = None                  # свой файл журнала (тесты, проверки) - вместо папки журналов
_hook = None                  # ещё и в окно «Что происходило» (events.EventLog), чтобы владелец видел то же самое


def old_path():
    """Где журнал лежал до переезда - это и говорит человеку первая строка нового журнала."""
    return os.path.join(config_dir(), OLD_NAME)


class _Log(app_log.Log):
    """Общий `app_log.Log` + свои файлы списком (их читает окно «Что происходило») и сброс файла дня.

    Про файлы установщика в той же папке общий модуль знает сам (правка `_brand/app_log.py` 18.10.2026:
    `note_move` смотрит только файлы своего kind), поэтому своего `note_move` здесь больше нет - строку про
    переезд пишет общий модуль. Что его не заглушает журнал установки - проверяет `tests/test_journal.py`.
    """

    def mine(self):
        """Файлы журнала самой программы, от старых к свежим (файлы установщика - не наши)."""
        folder = app_log.logs_dir(self.title, self.app_data)
        head, install = f"{self.app}-", f"{self.app}-install-"
        try:
            names = os.listdir(folder)
        except OSError:
            return []
        out = [os.path.join(folder, n) for n in names
               if n.startswith(head) and n.endswith(".log") and not n.startswith(install)]
        return sorted(out)                       # в имени дата, поэтому имя = порядок по времени

    def forget(self):
        """Забыть запомненный файл дня: нужно при смене %LOCALAPPDATA% (тесты, проверки вида)."""
        self._day = None
        self._path = ""


LOG = _Log(APP, TITLE)        # kind="" - журнал ПРОГРАММЫ (у установщика kind="install", файлы рядом)


def path():
    """Файл журнала на сегодня (его путь показываем человеку и открываем кнопкой)."""
    return _over or LOG.path


def set_path(p):
    """Свой файл журнала (тесты, проверки); None - обычное место."""
    global _over
    _over = p
    LOG.forget()


def set_hook(fn):
    """Куда ещё отдавать каждую строку (окно «Что происходило»); None - никуда."""
    global _hook
    _hook = fn


def write(text):
    """Строка в журнал (ошибки записи не мешают работе программы). Одна запись - одна строка."""
    text = str(text).strip()
    if _hook is not None:
        try:
            _hook(text)
        except Exception:  # noqa: BLE001
            pass
    line = text.replace("\n", " ").replace("\r", " ")
    with _lock:
        if _over:
            stamped = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {line}"     # как пишет общий app_log
            try:
                os.makedirs(os.path.dirname(_over) or ".", exist_ok=True)
                with open(_over, "a", encoding="utf-8") as f:
                    f.write(stamped + "\n")
            except OSError:
                pass
            return stamped
        LOG(line)
    return line


def note_move(old=""):
    """Отметить переезд журнала (пишется один раз - при первом запуске после обновления)."""
    with _lock:
        if _over:                                  # свой файл: переезд отмечаем, если он ещё пуст
            if os.path.exists(_over) and os.path.getsize(_over):
                return False
            folder = os.path.dirname(_over)
        else:
            return LOG.note_move(old or old_path())
    where = f" прежний лежал в {old or old_path()}, записи из него не переносил."
    write(f"журнал программы теперь здесь: {folder}.{where}")
    return True


def tail(n=20):
    """Последние строки журнала (окно «Щелчок» и отчёты): файл дня, при нужде - и прежние дни."""
    files = [_over] if _over else LOG.mine()[-2:]
    lines = []
    for p in files:
        lines += _tail_lines(p)
    return lines[-n:]


def _tail_lines(p, nbytes=64 * 1024):
    """Хвост файла строками: журнал может быть большим, целиком его читать незачем."""
    try:
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            if size > nbytes:
                f.seek(size - nbytes)
            data = f.read()
    except OSError:
        return []
    out = data.decode("utf-8", "replace").splitlines()
    return out[1:] if size > nbytes and out else out        # первая строка обрезана посередине - не наша


def show():
    """Кнопка «Показать журнал»: папка журналов (на Windows - с выделенным файлом дня)."""
    return app_log.show(path())


def reset():
    """Забыть запомненный файл дня (тесты подменяют %LOCALAPPDATA% на свою папку)."""
    LOG.forget()
