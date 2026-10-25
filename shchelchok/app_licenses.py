"""Открытые компоненты: один вид во ВСЕХ программах линейки (решение владельца 17.10.2026).

В настройках программы - одна строка и кнопка:

    Открытые компоненты
    Программа использует открытые компоненты, их лицензии - в файле рядом с программой
                                                              [ Открыть лицензии ]

Кнопка открывает в блокноте файл `licenses\\Сторонние компоненты.txt` в папке программы: перечень
сторонних компонентов, их правообладатели и лицензии. Полные тексты лицензий лежат там же, файлами
(этого требуют сами лицензии). Простыню лицензий в окно НЕ выводим (владелец 17.10.2026: «если не
требуется - то не пиши об этом»): в окне - только строка и кнопка.

Что в перечне можно писать, а что нельзя:
- можно и НУЖНО: кто правообладатель, какая лицензия, где её полный текст, для LGPL - что библиотека
  подключена динамически и где взять её исходный код, для Apache - отметка, что файлы изменены;
- НЕЛЬЗЯ: как именно мы готовим модели и собираем программу (это не требование лицензии, а наше
  описание). Список слов-примет и проверка - в tests/test_licenses.py каждой программы (в саму
  программу он не попадает: внутри exe не должно быть даже перечня того, что мы скрываем).

КОПИЯ ~/office_tools/_brand/app_licenses.py - не править здесь: `python3 _brand/sync.py`.
Перечень и тексты для каждой программы делает `_brand/tools/make_licenses.py` по `_brand/licenses_data.py`.
"""
from __future__ import annotations

import os
import subprocess
import sys

FOLDER = "licenses"
FILE_NAME = "Сторонние компоненты.txt"

# Строка и кнопка - ОДИНАКОВЫЕ во всех программах (слова владельца 17.10.2026)
TITLE = "Открытые компоненты"
SETTINGS_LINE = "Программа использует открытые компоненты, их лицензии - в файле рядом с программой"
BUTTON = "Открыть лицензии"


def _candidates(extra=()) -> list:
    """Где искать папку licenses: ресурсы сборки, папка exe, корень проекта (запуск из исходников)."""
    out = [p for p in extra if p]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        out.append(meipass)
        out.append(os.path.dirname(os.path.abspath(meipass)))      # onedir: рядом с exe
    if getattr(sys, "frozen", False):
        out.append(os.path.dirname(os.path.abspath(sys.executable)))
    here = os.path.dirname(os.path.abspath(__file__))
    out.append(here)
    out.append(os.path.dirname(here))                               # <программа>/<пакет>/.. - корень репозитория
    return out


def licenses_dir(extra=()) -> str | None:
    """Папка с лицензиями - первая, где лежит перечень. Нет такой - None (кнопку не показываем)."""
    for base in _candidates(extra):
        d = os.path.join(base, FOLDER)
        if os.path.isfile(os.path.join(d, FILE_NAME)):
            return d
    return None


def components_file(extra=()) -> str | None:
    """Полный путь к «Сторонние компоненты.txt» или None."""
    d = licenses_dir(extra)
    return os.path.join(d, FILE_NAME) if d else None


def open_licenses(extra=(), runner=None) -> bool:
    """Открыть перечень лицензий в блокноте (на Windows - notepad.exe). True - открыли."""
    path = components_file(extra)
    if not path:
        return False
    run = runner or subprocess.Popen
    if sys.platform.startswith("win"):
        for cmd in (["notepad.exe", path], ["cmd", "/c", "start", "", path]):
            try:
                run(cmd)
                return True
            except OSError:
                continue
        try:
            os.startfile(path)      # type: ignore[attr-defined]
            return True
        except OSError:
            return False
    try:
        run(["xdg-open", path])
        return True
    except OSError:
        return False


# --- уведомление рядом с голосами/моделями, которые качает установщик ------------------------------
# Старые пакеты голосов «Озвучки» (выложены до 17.10.2026) несли в себе описание нашей подготовки
# моделей. Программа при запуске заменяет такой файл короткой нейтральной строкой - и у тех, кто
# установил программу раньше, описание тоже пропадает.
PACK_NOTICE = """{title}: голоса программы.

Модели синтеза речи и интонации - сторонние открытые компоненты под лицензией Apache License 2.0;
модели работают на вашем компьютере. Правообладатели, перечень всех компонентов и полные
тексты лицензий - в папке программы: licenses\\{file_name}
"""


def fix_pack_notice(path: str, title: str) -> bool:
    """Файл рядом с голосами/моделями - привести к короткой нейтральной строке. True - перезаписали.

    Пакеты, выложенные до 17.10.2026, несли рядом с голосами наше описание подготовки моделей.
    Содержимое другое - значит это старый файл: пишем нейтральный текст (условия Apache и перечень
    всех компонентов лежат в licenses\\ рядом с программой)."""
    want = PACK_NOTICE.format(title=title, file_name=FILE_NAME)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            cur = fh.read()
    except OSError:
        return False
    if cur.strip() == want.strip():
        return False
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(want)
    except OSError:
        return False
    return True
