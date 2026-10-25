# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Почему не получилось - и какими словами об этом сказать. ОДИН набор на всю линейку.

Баг 17.10.2026 (журнал владельца, «Маркер на экране» 1.0.7 -> 1.0.8). Обновление из настроек программы семь
раз подряд падало с PermissionError «файл занят другим процессом», а на экране было написано «Связаться с
сервером не удалось» - и владелец (и главный) полчаса искали причину в «трёх буквах», которых там не было.
Причина: в установщике любая неузнанная ошибка объявлялась обрывом связи. Неверное сообщение опаснее самой
поломки: оно уводит двоих людей по ложному следу.

Правила владельца, которые держит этот модуль (и tests/test_fail_texts.py):
- у каждой причины свой текст: нет связи / программа запущена / не хватило прав / сумма не сошлась / мало
  места / неизвестно. Неизвестная причина НИКОГДА не называется обрывом связи;
- в КАЖДОМ тексте про связь есть подсказка «если у вас включены «три буквы», выключите их» - и в первом, и во
  втором отказе, и в окне программы (владелец 17.10.2026: «там даже не написал про три буквы»);
- в текстах про занятый файл и про права про связь не говорим вовсе;
- но и без зацепки человека не оставляем: в тексте про занятый файл СТОЯТ имя файла и имя программы, которая
  его держит, с номером процесса (их называет служба перезапуска Windows, см. swap_dir.holders); не удалось
  определить - так и говорим: «чем - определить не удалось, закройте лишние окна, отключите на минуту
  антивирус» (владелец 17.10.2026 вечером: обновление «Маркера» падало с «файл занят», и ни он, ни мы не могли
  понять причину, потому что в окне не было ни файла, ни процесса);
- слова из трёх букв латиницей нет нигде.

Здесь же - эстафета «программа закрылась - установщик начал»: `wait_pid` ждёт, пока исчезнет процесс с
нужным номером (программа передаёт свой номер установщику ключом --wait-pid, см. app_update.install).

Только стандартная библиотека, Python 3.8+ (идёт и в установщики PyInstaller, и в программы).
КОПИЯ ~/office_tools/_brand/fail_texts.py - не править копии, раздаёт python3 _brand/sync.py.
"""
from __future__ import annotations

import errno
import os
import re
import socket
import time
import urllib.error

# ------------------------------------------------------------------ причины
NET = "net"            # не дозвонились до сервера
BUSY = "busy"          # файлы программы заняты - она ещё запущена
RIGHTS = "rights"      # Windows не дала записать
SHA = "sha"            # скачалось с ошибкой: контрольная сумма не сошлась
SPACE = "space"        # на диске нет места
SERVER = "server"      # сервер ответил непонятное
LAUNCH = "launch"      # установщик не запустился (его не пустили, файл унесли в карантин)
OTHER = "other"        # неизвестно - подробности в журнале, но про связь НЕ врём

# Подсказка про «три буквы» - дословная формулировка владельца; слово латиницей не писать нигде.
HINT = "если у вас включены «три буквы», выключите их"
HINT_CAP = "Если у вас включены «три буквы», выключите их."
LOG_TAIL = "Подробности - в журнале установки."

ERR_BUSY = 32          # ERROR_SHARING_VIOLATION: «файл занят другим процессом»
ERR_DENIED = 5         # ERROR_ACCESS_DENIED
ERR_FULL = 112         # ERROR_DISK_FULL
ERR_LOCK = 33          # ERROR_LOCK_VIOLATION


class Fail(Exception):
    """Ошибка с известной причиной: `raise Fail(BUSY)` - и окно скажет про запущенную программу, не про связь.

    `path` и `holders` - для занятого файла (баг 17.10.2026: окно говорило «файл занят» и не называло ни файл,
    ни программу, которая его держит, - причину не могли понять ни владелец, ни мы). `holders` - список
    (номер процесса, «Имя программы») от службы перезапуска Windows, см. swap_dir.holders."""

    def __init__(self, kind, detail="", path="", holders=()):
        self.kind = kind
        self.detail = detail
        self.path = path
        self.holders = list(holders or ())
        super().__init__(f"{kind}: {detail}" if detail else kind)


def reason(e, step=""):
    """Причина по исключению.

    step="install" - шаг замены файлов (там «нет прав» почти всегда «файл занят»);
    step="launch" - шаг «запустить установщик»: там ничего не записывают, и текст «Windows не дала записать
    файлы программы» уводит в сторону (долг, найденный приёмкой 17.10.2026)."""
    if isinstance(e, Fail):
        return e.kind
    win = getattr(e, "winerror", None)
    if step == "launch" and isinstance(e, OSError):
        return LAUNCH
    if win in (ERR_BUSY, ERR_LOCK):
        return BUSY
    if win == ERR_FULL or getattr(e, "errno", None) in (errno.ENOSPC, errno.EDQUOT):
        return SPACE
    if isinstance(e, PermissionError) or win == ERR_DENIED:
        return BUSY if step == "install" else RIGHTS
    if isinstance(e, urllib.error.HTTPError):
        # сервер ответил, но кодом ошибки (404 - пропал файл, 500 - упало у нас). Советовать человеку
        # ковыряться в своих настройках тут нечестно: дело не в его связи (приёмка 17.10.2026)
        return SERVER
    if isinstance(e, (ConnectionError, TimeoutError, socket.timeout, socket.gaierror, urllib.error.URLError)):
        return NET
    low = str(e).lower()
    if "занят" in low or "используется другим" in low or "всё ещё открыта" in low:
        return BUSY
    if "сумма" in low or "скачался с ошибкой" in low:
        return SHA
    if "мало места" in low or "не хватает места" in low:
        return SPACE
    return OTHER


def need_more(detail):
    """«мало места: нужно 6000 МБ, свободно 2500 МБ» -> « Нужно ещё 4 ГБ.» (не разобрали - пустая строка)."""
    try:
        need, free = (int(x) for x in re.findall(r"(\d+)\s*МБ", str(detail), re.I)[:2])
    except (TypeError, ValueError):
        return ""
    return f" Нужно ещё {max(1, round((need - free) / 1024))} ГБ."


# ------------------------------------------------------------------ кто держит файл
def holders_text(items):
    """[(1234, «Google Chrome»)] -> «программой «Google Chrome» (процесс 1234)». Пусто - пустая строка."""
    parts = []
    for pid, app in list(items or ())[:3]:
        app = (app or "").strip()
        parts.append(f"«{app}» (процесс {pid})" if app else f"процессом {pid}")
    if not parts:
        return ""
    word = "программой" if len(parts) == 1 else "программами"
    return word + " " + ", ".join(parts)


def file_name(path):
    """Имя файла из пути Windows - даже когда разбираем его не на Windows (там os.path не знает «\\»)."""
    return str(path or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def busy_file_message(path="", holders=(), title="", second=False):
    """Файл занят: называем ФАЙЛ и того, кто его держит, - и что сделать. Про связь здесь ни слова.

    Владелец 17.10.2026: окно говорило просто «файл занят», и причину нельзя было понять. Теперь в окне
    (и в журнале) стоит имя файла и имя программы с номером процесса - их называет служба перезапуска Windows."""
    name = file_name(path)
    who = holders_text(holders)
    tail = " Если не поможет - перезагрузите компьютер и запустите установку снова." if second else ""
    if name and who:
        return f"Файл «{name}» занят {who}. Закройте её и нажмите «Повторить»." + tail
    if name:
        return (f"Файл «{name}» чем-то занят, а чем - определить не удалось. Закройте лишние окна, "
                "на минуту отключите антивирус и нажмите «Повторить»." + tail)
    return (f"Файлы программы {'«' + title + '»' if title else ''} заняты другим процессом. Закройте лишние "
            "окна и нажмите «Повторить»." + tail)


def rights_message(path="", second=False):
    """«Не хватило прав» - свой текст, не про занятый файл.

    Было так: при известном пути отдавался текст про занятый файл с именем держателя, которого нет, - то есть
    человеку предлагали закрыть программу, которая ничего не держит, и жать «Повторить», от которого ничего не
    изменится (долг, найденный приёмкой 17.10.2026). Чаще всего за этим стоит защита папок антивируса."""
    name = file_name(path)
    what = f"файл «{name}»" if name else "файлы программы"
    tail = (" Если не помогло - перезагрузите компьютер и запустите установку снова." if second else
            " Потом нажмите «Повторить».")
    return (f"Windows не дала записать {what}: не хватило прав. Чаще всего так делает защита папок в "
            "антивирусе - отключите её на минуту или добавьте папку программы в исключения." + tail)


def busy_wait(path="", holders=(), pause=0, kind=BUSY):
    """Что показать, пока ждём освобождения файла (между попытками замены).

    kind=RIGHTS - Windows отказала в доступе: так отвечает защита папок антивируса, и говорить «файл занят»
    было бы неправдой (долг 17.10.2026)."""
    name = file_name(path)
    who = holders_text(holders)
    when = f" Пробую снова через {int(pause)} с…" if pause else " Пробую снова…"
    if kind == RIGHTS:
        what = f"файл «{name}»" if name else "файлы программы"
        return f"Windows пока не даёт записать {what} - похоже, его проверяет антивирус." + when
    about = f"Файл «{name}» занят {who}" if name and who else (
        f"Файл «{name}» пока занят" if name else "Файлы программы пока заняты")
    return about + "." + when


# ------------------------------------------------------------------ тексты установщика
def message(kind, title="", second=False, detail="", path="", holders=()):
    """Что написать в окне установщика. second=True - человек уже нажимал «Повторить» и получил то же самое.
    detail - текст ошибки (из него берём, сколько ещё нужно места на диске);
    path и holders - занятый файл и кто его держит (для причины BUSY)."""
    name = f"«{title}»" if title else "программа"
    if kind == NET:
        if second:
            return ("Связаться с сервером не удалось и во второй раз. " + HINT_CAP +
                    " Потом закройте это окно и запустите установщик заново - он начнёт проверку соединения с нуля.")
        return ("Не получилось связаться с сервером. Проверьте интернет - и " + HINT +
                ". Потом нажмите «Повторить».")
    if kind == BUSY:
        if path or holders:
            return busy_file_message(path, holders, title=title, second=second)
        return (f"Программа {name} сейчас запущена, поэтому обновить её не получается. "
                "Закройте её (значок у часов → Выход) и нажмите «Повторить».")
    if kind == RIGHTS:
        if holders:
            return busy_file_message(path, holders, title=title, second=second)   # держателя назвали - он и виноват
        return rights_message(path, second=second)
    if kind == LAUNCH:
        return ("Установщик новой версии не запустился. Скорее всего его придержал антивирус. Отключите "
                "защиту на минуту и нажмите «Повторить» - или скачайте новую версию с сайта.")
    if kind == SHA:
        return "Файл скачался с ошибкой - проверка не сошлась. Нажмите «Повторить», скачаю заново."
    if kind == SPACE:
        return ("На диске не хватает места для установки." + need_more(detail) +
                " Освободите место на диске C: и нажмите «Повторить».")
    if kind == SERVER:
        return "Сервер ответил непонятное - обновление пока не поставлю. Попробуйте позже."
    return "Установка не получилась. Нажмите «Повторить». " + LOG_TAIL



def log_line(path):
    """Строка под сообщением об отказе: где лежит журнал этого дня (владелец 17.10.2026 - «журнал должен
    писаться бесконечно»; человеку надо знать, что прислать)."""
    return f"Подробности - в журнале: {path}" if path else LOG_TAIL


def waiting(title=""):
    """Пока ждём, что программа закроется сама (эстафета самообновления)."""
    name = f"«{title}»" if title else "Программа"
    return f"Жду, пока программа {name} закроется…"


def close_button():
    return "Закрыть программу и продолжить"


# ------------------------------------------------------------------ тексты окна самой программы
def update_message(kind):
    """Что написать в окне «Вышла новая версия» самой программы, когда обновление не вышло."""
    if kind == NET:
        return ("Не получилось скачать новую версию: нет связи с сервером. " + HINT_CAP +
                " Потом нажмите «Повторить».")
    if kind == BUSY:
        return ("Обновить не получилось: файлы программы заняты другим процессом. Закройте лишние окна "
                "программы и нажмите «Повторить».")
    if kind == SHA:
        return "Файл скачался с ошибкой - проверка не сошлась. Нажмите «Повторить», скачаю заново."
    if kind == SPACE:
        return "На диске не хватает места для новой версии. Освободите место на диске C: и нажмите «Повторить»."
    if kind == SERVER:
        return "Сервер ответил непонятное - обновление пока не поставлю. Попробую позже сам."
    if kind == RIGHTS:
        return ("Windows не дала записать файлы программы: не хватило прав. Чаще всего так делает защита папок "
                "в антивирусе - отключите её на минуту или скачайте новую версию с сайта.")
    if kind == LAUNCH:
        return ("Установщик новой версии не запустился - скорее всего его придержал антивирус. Отключите "
                "защиту на минуту и нажмите «Повторить» или скачайте новую версию с сайта.")
    return "Обновить не получилось. Попробуйте ещё раз - или скачайте новую версию с сайта."


# ------------------------------------------------------------------ эстафета: программа закрылась - ставим
WAIT_ARG = "--wait-pid"


def wait_pid_arg(argv):
    """Номер процесса из ключа --wait-pid (его передаёт сама программа, запуская установщик). Нет - 0."""
    try:
        i = list(argv).index(WAIT_ARG)
        return int(argv[i + 1])
    except (ValueError, IndexError, TypeError):
        return 0


def pid_alive(pid):
    """Жив ли процесс с таким номером. Windows - через OpenProcess, иначе - сигнал 0."""
    pid = int(pid or 0)
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        # restype обязателен: без него ctypes считает, что функция вернула int, и 64-битный дескриптор
        # усекается до 32 бит со знаком - тогда CloseHandle закрывает «что-то другое» (приёмка 17.10.2026)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k.OpenProcess(0x1000, False, pid)         # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            err = ctypes.get_last_error()
            # 87 (неверный параметр) - такого процесса нет, он закрылся. А вот «нет прав» (5) НЕ значит,
            # что он закрылся: решив так, установщик пошёл бы менять файлы РАБОТАЮЩЕЙ программы
            # (замечание независимой приёмки 17.10.2026). В сомнении считаем, что процесс жив.
            return err not in (87, 0)
        code = ctypes.c_uint32(0)
        try:
            ok = k.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))
        finally:
            k.CloseHandle(ctypes.c_void_p(h))         # дескриптор закрываем всегда, а не «если повезло»
        return bool(ok) and code.value == 259          # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_pid(pid, timeout=30.0, on_wait=None, alive=None, sleep=time.sleep, clock=time.monotonic):
    """Подождать, пока процесс pid исчезнет. True - исчез (или его и не было), False - всё ещё жив.

    Так установщик, запущенный самой программой, не начинает заменять файлы, пока программа ещё жива
    (баг 17.10.2026: установщик стартовал первым и упирался в занятые файлы)."""
    alive = alive or pid_alive
    if not int(pid or 0):
        return True
    end = clock() + timeout
    while alive(pid):
        if clock() >= end:
            return False
        if on_wait:
            on_wait()
        sleep(0.5)
    return True
