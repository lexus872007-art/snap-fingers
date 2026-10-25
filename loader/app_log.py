"""Журнал программы и установщика - ОДИН на линейку. «Пишется бесконечно» (решение владельца 17.10.2026).

Его слова: «главное, чтобы всё писалось в журнал, журнал должен писаться бесконечно, иначе никак не
отследить баги и ошибки». Сегодня именно журнал дал настоящую причину беды с обновлением - и он же чуть не
пропал: лежал в `%TEMP%`, который чистит сама Windows, «Очистка диска» и любая чистилка.

Как теперь:
- **Место**: `%LOCALAPPDATA%\\<Название программы>\\logs`. Не `%TEMP%` (чистится) и НЕ папка программы
  (её целиком заменяет обновление - это мы чинили весь день 17.10.2026). Переживает и обновление, и удаление
  программы: при удалении журналы остаются, по ним разбирают жалобы.
- **Файл на день**: `<app>-2026-10-18.log`. У установщика и у самой программы - свои файлы в одной папке
  (`<app>-install-…` и `<app>-…`), чтобы не путать, кто что писал.
- **Храним долго**: ничего не удаляем по времени. Ограничение - общий объём папки (по умолчанию 200 МБ,
  это примерно четыре года при 50 КБ в день). Переполнилось - убираем самые старые дни и ПИШЕМ об этом
  строку в свежий журнал, чтобы пропажа не была молчаливой.
- **Одна запись - одна строка**, со временем: журнал читается глазами и ищется обычным поиском.

Только стандартная библиотека, Python 3.8+ (идёт и в установщики PyInstaller, и в программы).
КОПИЯ ~/office_tools/_brand/app_log.py - не править копии, раздаёт python3 _brand/sync.py.
"""
from __future__ import annotations

import datetime
import os
import re
import tempfile

MAX_BYTES = 200 * 1024 * 1024        # сколько всего места отдаём журналам этой программы
KEEP_AT_LEAST = 2                    # столько последних файлов не трогаем никогда


def logs_dir(title, app_data=None):
    """Папка журналов этой программы: %LOCALAPPDATA%\\<Название>\\logs (создаётся при надобности)."""
    base = app_data or os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, title, "logs")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return tempfile.gettempdir()      # совсем некуда писать - пусть будет хоть временная папка
    return path


def log_path(app, title, kind="", day=None, app_data=None):
    """Файл журнала на сегодня: <app>[-kind]-ГГГГ-ММ-ДД.log."""
    day = day or datetime.date.today()
    name = f"{app}-{kind}-{day:%Y-%m-%d}.log" if kind else f"{app}-{day:%Y-%m-%d}.log"
    return os.path.join(logs_dir(title, app_data), name)


def _name_re(app, kind=None):
    """Имена файлов журнала: «<app>-ГГГГ-ММ-ДД.log», а с kind - «<app>-install-ГГГГ-ММ-ДД.log».

    kind=None - любой (все файлы этой программы, по ним считаем общий объём папки); kind="" - ТОЛЬКО файлы
    самой программы, kind="install" - только установщика. Разделять обязательно: программа и установщик
    пишут в одну папку, и «у меня уже есть журнал» нельзя считать по чужим файлам (нашлось 18.10.2026 -
    строку про переезд журнала не увидел бы никто, потому что установщик всегда пишет раньше)."""
    middle = r"(?:-[a-z]+)?" if kind is None else (re.escape("-" + kind) if kind else "")
    return re.compile(r"^" + re.escape(app) + middle + r"-\d{4}-\d{2}-\d{2}\.log$")


def _files(folder, app, kind=None):
    out = []
    rx = _name_re(app, kind)
    try:
        for n in os.listdir(folder):
            if rx.match(n):
                p = os.path.join(folder, n)
                try:
                    out.append((p, os.path.getsize(p), os.path.getmtime(p)))
                except OSError:
                    pass
    except OSError:
        pass
    return sorted(out, key=lambda x: x[2])


def trim(folder, app, max_bytes=MAX_BYTES, keep=KEEP_AT_LEAST):
    """Папка журналов разрослась - убрать самые старые дни. Возвращает, что удалили (для записи в журнал)."""
    files = _files(folder, app)
    total = sum(size for _p, size, _t in files)
    gone = []
    while total > max_bytes and len(files) > keep:
        path, size, _t = files.pop(0)
        try:
            os.remove(path)
            total -= size
            gone.append(os.path.basename(path))
        except OSError:
            break
    return gone


def show(path):
    """Показать человеку журнал: открыть его папку (на Windows - с выделенным файлом дня).

    Кнопка «Показать журнал» есть в настройках каждой программы линейки: владелец 17.10.2026 - «главное,
    чтобы всё писалось в журнал», а чтобы журнал пригодился, человек должен уметь его найти и прислать.
    Возвращает True, если папку открыли."""
    path = str(path or "")
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    if not folder:
        return False
    try:
        if os.name == "nt":
            import subprocess
            if os.path.isfile(path):
                # /select выделяет сам файл; кавычки и запятую explorer понимает только в таком виде
                subprocess.Popen(["explorer", f"/select,{path}"], close_fds=True)
            else:
                subprocess.Popen(["explorer", folder], close_fds=True)
            return True
        import subprocess
        subprocess.Popen(["xdg-open", folder], close_fds=True)      # на Windows не бывает, нужно проверкам
        return True
    except Exception:  # noqa: BLE001 - не открылось, так не открылось: окно из-за этого падать не должно
        return False


class Log:
    """Запись в журнал: одна строка со временем. Ничего не бросает - журнал не должен ронять установку.

    writer = Log(APP, TITLE, kind="install"); writer("старт установки")
    """

    def __init__(self, app, title, kind="", max_bytes=MAX_BYTES, app_data=None):
        self.app, self.title, self.kind = app, title, kind
        self.max_bytes = max_bytes
        self.app_data = app_data
        self._day = None
        self._path = ""

    @property
    def path(self):
        """Файл сегодняшнего дня (его путь показываем человеку в окне отказа)."""
        today = datetime.date.today()
        if today != self._day or not self._path:
            self._day = today
            self._path = log_path(self.app, self.title, self.kind, today, self.app_data)
            self._rotate()
        return self._path

    def _rotate(self):
        gone = trim(os.path.dirname(self._path), self.app, self.max_bytes)
        if gone:
            self._write(f"журналы заняли больше {self.max_bytes >> 20} МБ - убрал самые старые: "
                        + ", ".join(gone))

    def _write(self, text):
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")
        except OSError:
            pass

    def __call__(self, text):
        path = self.path                      # заодно переключит день и подрежет объём
        if not path:
            return
        self._write(str(text).replace("\n", " ").replace("\r", " "))   # одна запись - одна строка

    def note_move(self, old_path=""):
        """Самая первая запись нового журнала: где лежал прежний и что записи из него не переносили.

        Пишется ОДИН раз - когда у этой программы ещё нет ни одного файла журнала в новом месте (то есть при
        первом запуске после обновления). Молчаливый переезд был бы тем же самым «нет данных ≠ нет беды»:
        человек ищет прежние записи и не понимает, куда они ушли (решение владельца 17.10.2026)."""
        folder = logs_dir(self.title, self.app_data)
        if _files(folder, self.app, self.kind):
            return False      # свои файлы уже есть - про переезд говорили; чужие (установщика) не считаем
        where = f" прежний лежал в {old_path}, записи из него не переносил." if old_path else ""
        self(f"журнал программы теперь здесь: {folder}.{where}")
        return True
