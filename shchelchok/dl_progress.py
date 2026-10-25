"""Прогресс каждого скачивания линейки (владелец 15.10.2026: «не пойму, сколько скачалось и сколько осталось, может
он завис; пусть показывается скорость; это относится ко всем программам, которые качают»).

Правило: любое скачивание показывает
- что качается и какая это часть («часть 2 из 3», «модель 1 из 2», «файл 7 из 45»);
- скачано / всего («640 из 1 547 МБ», «1,2 из 3,1 ГБ»), скорость («12,4 МБ/с»), «осталось ~2 мин»;
- строка обновляется раз в секунду и тогда, когда байты не идут: с 10 с без данных - «нет данных 25 с»;
- 60 с без единого байта - «Нет данных 60 с - соединение подвисло, переподключаюсь…» и новая попытка с того же
  байта (Range); обычный обрыв - «Связь пропала - продолжаю с 640 МБ (попытка 3 из 40)…».

Только стандартная библиотека, Python 3.8+ (установщики, setup Local Voice).
КОПИЯ ~/office_tools/_brand/dl_progress.py - не править копии, раздаёт python3 _brand/sync.py
(сам находит каждую папку */loader с loader.py - новые программы получают модуль автоматически).

  st = download(open_url, url, path, size, on_status, label="программу", part=(1, 3), done_before=0, total=size_all)
  # open_url(url, headers=None, timeout=30) -> ответ urllib (net_proxy.Net.open);
  # on_status(st): st.text - две строки для окна, st.line - одна строка для консоли, st.frac - доля 0..1 всего,
  #                st.kind - "progress" | "stall" | "retry" | "done"
"""
import errno
import math
import os
import socket
import sys
import threading
import time
import urllib.error

STALL = 60            # с без единого байта - соединение подвисло, переподключаемся
ATTEMPTS = 40
TICK = 1.0            # как часто обновляется строка
QUIET_SHOW = 10       # с без данных - показать «нет данных N с»
WINDOW = 8.0          # окно, по которому считается скорость, с
MB = 1 << 20
GB = 1 << 30
# Подсказка про «три буквы» - в каждом сообщении про связь (дословная формулировка владельца; слово из трёх
# букв латиницей не писать нигде). Тот же текст в fail_texts.HINT - сверяет _brand/tests/test_fail_texts.py.
HINT_FROM = "Если у вас включены «три буквы», выключите их."
HINT_ATTEMPT = 3      # с какой попытки докачки показываем подсказку (первый обрыв бывает и сам по себе)


# ---------------------------------------------------------------- форматы (русская запятая, пробел в тысячах)
def num(x, nd=0):
    s = f"{x:,.{nd}f}".replace(",", " ").replace(".", ",")
    return s


def size_pair(got, total=0, approx=False):
    """'640 из 1 547 МБ' -> до 1 ГБ в МБ; '640 МБ из 1,5 ГБ', '1,2 из 3,1 ГБ'; без total - '640 МБ'.
    approx - «из ~2,3 ГБ» (всего известно приблизительно)."""
    a = "~" if approx else ""
    if not total:
        return f"{num(got / GB, 1)} ГБ" if got >= GB else f"{num(got / MB)} МБ"
    if total < 10 * MB:
        return f"{num(got / MB, 1)} из {a}{num(total / MB, 1)} МБ"
    if total < GB:
        return f"{num(got / MB)} из {a}{num(total / MB)} МБ"
    if got < GB:
        return f"{num(got / MB)} МБ из {a}{num(total / GB, 1)} ГБ"
    return f"{num(got / GB, 1)} из {a}{num(total / GB, 1)} ГБ"


def speed_text(bps):
    if bps >= 10 * MB:
        return f"{num(bps / MB)} МБ/с"
    if bps >= MB:
        return f"{num(bps / MB, 1)} МБ/с"
    return f"{num(max(0.0, bps) / 1024)} КБ/с"


def dur(sec):
    """'~40 с', '~2 мин', '~1 ч 5 мин'; None - неизвестно."""
    if sec is None:
        return None
    sec = max(0.0, sec)
    if sec < 55:
        return f"~{max(5, int(math.ceil(sec / 5.0)) * 5)} с"
    m = int(math.ceil(sec / 60.0))
    if m < 60:
        return f"~{m} мин"
    return f"~{m // 60} ч {m % 60} мин" if m % 60 else f"~{m // 60} ч"


def eta_text(sec):
    d = dur(sec)
    return f"осталось {d}" if d else "осталось - считаю…"


class Meter:
    """Скорость по последним WINDOW секундам; без новых байт скорость падает к нулю."""

    def __init__(self, clock=time.monotonic, window=WINDOW):
        self.clock = clock
        self.window = window
        self.samples = []            # (t, got)
        self.t_grow = clock()
        self.last = None

    def reset(self, got):
        now = self.clock()
        self.samples = [(now, got)]
        self.last = got
        self.t_grow = now

    def update(self, got):
        now = self.clock()
        if self.last is None or got > self.last:
            self.t_grow = now
        self.last = got
        self.samples.append((now, got))
        while len(self.samples) > 2 and now - self.samples[1][0] > self.window:
            self.samples.pop(0)

    def speed(self):
        if len(self.samples) < 2:
            return 0.0
        now = self.clock()
        t0, g0 = self.samples[0]
        g1 = self.samples[-1][1]
        dt = max(now - t0, 0.5)
        return max(0.0, (g1 - g0) / dt)

    def idle(self):
        return self.clock() - self.t_grow


class State:
    """Что показать: всё в байтах и секундах; text/line - готовые строки."""

    def __init__(self, label, got, size, done_before, total, speed, idle, part, kind="progress", message="",
                 render=None, approx=False):
        self.label, self.got, self.size = label, got, size
        self.done_before, self.total = done_before, total or size
        self.speed, self.idle = speed, idle
        self.i, self.n = part
        self.kind, self.message, self.approx = kind, message, approx
        self.frac = min(1.0, (done_before + got) / self.total) if self.total else 0.0
        fast = speed > 1024
        self.eta = (size - got) / speed if fast and size else None
        self.eta_total = (self.total - done_before - got) / speed if fast and self.total else None
        head, detail = (render or default_render)(self)
        if message:                                   # подвисло / обрыв - сообщение вместо цифр
            detail = message
        self.head, self.detail = head, detail
        self.text = head + "\n" + detail
        self.line = head + ": " + detail


def default_render(s):
    """Окно установщика: «Скачиваю модель распознавания (часть 2 из 3)» / «640 из 1 547 МБ · 12,4 МБ/с · осталось ~2 мин»."""
    head = f"Скачиваю {s.label}" + (f" (часть {s.i} из {s.n})" if s.n > 1 else "")
    eta = "готово" if s.kind == "done" else eta_text(s.eta)
    if s.kind != "done" and s.n > 1 and s.eta_total is not None and s.eta is not None and s.eta_total - s.eta > 30:
        eta += f", всего {dur(s.eta_total)}"
    parts = [size_pair(s.got, s.size), speed_text(s.speed), eta]
    if s.idle >= QUIET_SHOW:
        parts.append(f"нет данных {int(s.idle)} с")
    return head, " · ".join(parts)


def stall_message(stall=STALL):
    return f"Нет данных {stall} с - соединение подвисло, переподключаюсь… {HINT_FROM}"


def retry_message(got, n, attempts):
    """Обрыв посреди скачивания. С третьей попытки добавляем подсказку про «три буквы»: именно они чаще всего
    рвут связь, и человек должен видеть это в КАЖДОМ сообщении про связь, а не только в первом (владелец
    17.10.2026: «там даже не написал про три буквы»)."""
    tail = f" {HINT_FROM}" if n >= HINT_ATTEMPT else ""
    return f"Связь пропала - продолжаю с {size_pair(got)} (попытка {n} из {attempts})…{tail}"


# ---------------------------------------------------------------- скачивание
def _read(r, chunk):
    rd = getattr(r, "read1", None)          # read1 - сколько пришло, не ждать полный кусок (медленная связь)
    try:
        return rd(chunk) if rd else r.read(chunk)
    except TypeError:
        return r.read(chunk)


def _is_timeout(e):
    if isinstance(e, (socket.timeout, TimeoutError)):
        return True
    if isinstance(e, urllib.error.URLError) and isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
        return True
    return "timed out" in str(e).lower()


class Cancelled(Exception):
    """Человек нажал «Отмена» - скачивание бросаем сами, а не ждём, пока поток доживёт до конца."""


def _err_text(e):
    win = getattr(e, "winerror", None)
    return f"{type(e).__name__} winerror={win}: {e}" if win else repr(e)


def _is_net(e):
    """Это и правда обрыв связи?

    Нет: ответ сервера кодом ошибки (404, 500) - сервер ответил; отказ записи в файл - дело не в связи.
    Долг 17.10.2026: после всех попыток модуль ВСЕГДА бросал ConnectionError, и любая беда объявлялась
    «нет связи» - вместе с советом выключить «три буквы», которые тут ни при чём."""
    if isinstance(e, urllib.error.HTTPError):
        return False
    if isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32):
        return False
    return isinstance(e, (ConnectionError, TimeoutError, socket.timeout, socket.gaierror,
                          urllib.error.URLError)) or _is_timeout(e)


def server_message(code, n, attempts):
    """Сервер ответил ошибкой (500 и подобные). Про «три буквы» здесь ни слова: дело не в связи человека."""
    return f"Сервер ответил ошибкой {code} - пробую ещё раз (попытка {n} из {attempts})…"


STAMP_SUFFIX = ".src"       # рядом с «.part»: чем сервер назвал этот файл, когда мы начали качать


def _stamp_read(path):
    try:
        with open(path + STAMP_SUFFIX, encoding="utf-8") as f:
            return dict(line.split("\t", 1) for line in f.read().splitlines() if "\t" in line)
    except (OSError, ValueError):
        return {}


def _stamp_of(r):
    """Приметы файла на сервере: длина, ETag, дата. По ним видно, что на сервере уже ДРУГОЙ файл."""
    h = getattr(r, "headers", None)
    get = (lambda k: h.get(k) or "") if h is not None else (lambda _k: "")
    out = {"etag": (get("ETag") or "").strip(), "modified": (get("Last-Modified") or "").strip()}
    return {k: v for k, v in out.items() if v}


def _stamp_write(path, r):
    try:
        with open(path + STAMP_SUFFIX, "w", encoding="utf-8") as f:
            for k, v in _stamp_of(r).items():
                f.write(f"{k}\t{v}\n")
    except OSError:
        pass


def _stamp_drop(path):
    try:
        os.remove(path + STAMP_SUFFIX)
    except OSError:
        pass


def _range_total(r):
    """Полный размер файла из «Content-Range: bytes 100-999/1000» (0 - сервер не сказал)."""
    h = getattr(r, "headers", None)
    value = (h.get("Content-Range") or "") if h is not None else ""
    try:
        return int(value.rsplit("/", 1)[1])
    except (IndexError, ValueError):
        return 0


def changed_on_server(path, r, size=0):
    """Докачиваем не ту версию? Возвращает, чем именно файл на сервере отличается (или пустую строку).

    Сумма ловит подмену только ПОСЛЕ скачивания: человек ждёт весь файл, а потом слышит «скачалось с
    ошибкой». Длина и ETag видны сразу (долг 17.10.2026)."""
    total = _range_total(r)
    if size and total and total != size:
        return f"на сервере файл другой длины ({total} вместо {size})"
    was, now = _stamp_read(path), _stamp_of(r)
    for key, what in (("etag", "метка ETag"), ("modified", "дата файла")):
        if was.get(key) and now.get(key) and was[key] != now[key]:
            return f"на сервере сменилась {what}"
    return ""


def download(open_url, url, path, size, on_status, label="программу", part=(1, 1), done_before=0, total=None,
             attempts=ATTEMPTS, stall=STALL, tick=TICK, log=None, sleep=time.sleep, chunk=1 << 16, render=None,
             approx=False, clock=time.monotonic, cancel=None):
    """Скачать url в path с докачкой (Range с уже скачанного байта) и строкой прогресса. -> байт в файле.

    `cancel()` -> True - человек нажал «Отмена»: бросаем `Cancelled` и выходим, не дожидаясь конца файла."""
    log = log or (lambda m: None)
    meter = Meter(clock)
    lock = threading.Lock()
    cur = {"got": os.path.getsize(path) if os.path.exists(path) else 0, "active": False}

    def emit(kind="progress", message=""):
        st = State(label, cur["got"], size, done_before, total, meter.speed(), meter.idle(), part, kind, message,
                   render, approx)
        with lock:
            try:
                on_status(st)
            except Exception as e:  # noqa: BLE001 - окно закрыто и т.п.: скачивание не роняем
                log(f"прогресс: {e!r}")
        return st

    stop = threading.Event()

    def ticker():
        while not stop.wait(tick):
            if cur["active"]:
                emit()

    th = threading.Thread(target=ticker, daemon=True)
    th.start()
    last = None
    try:
        for n in range(attempts):
            if cancel and cancel():
                raise Cancelled("скачивание отменено")
            got = os.path.getsize(path) if os.path.exists(path) else 0
            if size and got > size:                       # чужой/испорченный хвост - заново
                os.remove(path)
                _stamp_drop(path)
                got = 0
            cur["got"] = got
            if size and got >= size:
                emit("done")
                _stamp_drop(path)
                return got
            meter.reset(got)
            stalled = False
            code = 0
            try:
                try:
                    r = open_url(url, headers={"Range": f"bytes={got}-"} if got else None, timeout=stall)
                except urllib.error.HTTPError as e:
                    if e.code == 416 and got:             # сервер: диапазон за концом - файл уже целиком у нас
                        if not size:
                            emit("done")
                            _stamp_drop(path)
                            return got
                        os.remove(path)
                        _stamp_drop(path)
                        raise
                    raise
                if got and getattr(r, "status", 200) != 206:   # сервер не умеет докачку - с начала
                    got = 0
                    cur["got"] = 0
                    meter.reset(0)
                elif got:
                    # Докачиваем ли мы ТО ЖЕ САМОЕ? Контрольная сумма ответит только в конце, а длина и ETag -
                    # сразу. Версия на сервере сменилась посреди обновления - начинаем с нуля, а не дарим
                    # человеку девять минут ожидания и «файл скачался с ошибкой» (долг 17.10.2026).
                    what = changed_on_server(path, r, size)
                    if what:
                        log(f"{label}: {what} - качаю заново с нуля")
                        try:
                            r.close()
                        except Exception:  # noqa: BLE001
                            pass
                        os.remove(path)
                        _stamp_drop(path)
                        got = 0
                        cur["got"] = 0
                        meter.reset(0)
                        r = open_url(url, headers=None, timeout=stall)
                if not got:
                    _stamp_write(path, r)         # запомним приметы файла: по ним узнаем подмену при докачке
                cur["active"] = True
                emit()
                with open(path, "ab" if got else "wb") as out:
                    while True:
                        if cancel and cancel():
                            raise Cancelled("скачивание отменено")
                        b = _read(r, chunk)
                        if not b:
                            break
                        out.write(b)
                        got += len(b)
                        cur["got"] = got
                        meter.update(got)
                try:
                    r.close()
                except Exception:  # noqa: BLE001
                    pass
                cur["active"] = False
                if not size or got >= size:
                    emit("done")
                    _stamp_drop(path)
                    return got
                log(f"{label}: соединение закрыто на {got} байт из {size}")
            except Cancelled:
                cur["active"] = False
                log(f"{label}: скачивание отменено на {cur['got']} байт - файл оставляю, докачаю в другой раз")
                raise
            except Exception as e:  # noqa: BLE001
                cur["active"] = False
                if getattr(e, "errno", None) == errno.ENOSPC or getattr(e, "winerror", None) == 112:
                    raise          # на диске нет места: докачка не поможет, и это НЕ обрыв связи (17.10.2026)
                code = getattr(e, "code", 0) if isinstance(e, urllib.error.HTTPError) else 0
                if 400 <= code < 500 and code != 416:
                    # «нет такого файла» (404) или «не пущу» (403) за сорок попыток не изменятся, а человек
                    # девять минут читал бы «пробую снова» под текстом про интернет (долг 17.10.2026)
                    log(f"{label}: сервер ответил {code} - повторять нечего")
                    raise
                if isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32):
                    log(f"{label}: записать файл не дали ({_err_text(e)}) - это не связь, не повторяю")
                    raise
                last = e
                stalled = _is_timeout(e)
                log(f"{label}: {'нет данных ' + str(stall) + ' с' if stalled else 'обрыв'} на {cur['got']} байт: {e!r}")
            if n + 1 >= attempts:
                break
            if stalled:
                emit("stall", stall_message(stall))
                sleep(2)
            else:
                emit("retry", server_message(code, n + 2, attempts) if code
                     else retry_message(cur["got"], n + 2, attempts))
                sleep(min(2 + n * 2, 15))
        if last is not None and not _is_net(last):
            raise last          # не выдаём чужую беду за обрыв связи: пусть её назовут своим именем
        raise ConnectionError("скачивание прерывалось слишком много раз"
                              + (f" (последняя ошибка: {last!r})" if last is not None else ""))
    finally:
        stop.set()


# ---------------------------------------------------------------- консоль (setup Local Voice)
def _enable_vt():
    if not sys.platform.startswith("win"):
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k.SetConsoleMode(h, mode.value | 0x0004))       # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:  # noqa: BLE001
        return False


class Console:
    """Одна перезаписываемая строка (\\r); сообщения «подвисло»/«обрыв» - отдельной жёлтой строкой."""

    def __init__(self, stream=None, indent="  "):
        self.stream = stream or sys.stdout
        self.indent = indent
        self.color = self.stream.isatty() and _enable_vt() if hasattr(self.stream, "isatty") else False
        self.open = False

    def width(self):
        try:
            import shutil
            return max(40, shutil.get_terminal_size((120, 25)).columns - 1)
        except Exception:  # noqa: BLE001
            return 119

    def __call__(self, st):
        w = self.width()
        if st.kind in ("stall", "retry"):
            msg = self.indent + st.message
            if self.color:
                msg = "\x1b[33m" + msg + "\x1b[0m"
            self.stream.write(("\r" + " " * w + "\r" if self.open else "") + msg + "\n")
            self.open = False
        else:
            line = (self.indent + st.line)[:w]
            self.stream.write("\r" + line.ljust(w))          # и «done» не переводит строку: следующий файл - в ней же,
            self.open = True                                  # перевод строки - end() в конце всего скачивания
        self.stream.flush()

    def end(self):
        if self.open:
            self.stream.write("\n")
            self.stream.flush()
            self.open = False


def sample(label, got_mb, size_mb, speed_mb=3.4, part=(1, 1), done_before_mb=0, total_mb=None, idle=0, kind="progress"):
    """Строка для --demo (снимки окна установщика) - тот же вид, что при настоящем скачивании.
    kind="stall" - «соединение подвисло», "retry" - «связь пропала… попытка 3 из 40»."""
    message = stall_message() if kind == "stall" else retry_message(int(got_mb * MB), 3, ATTEMPTS) if kind == "retry" else ""
    return State(label, int(got_mb * MB), int(size_mb * MB), int(done_before_mb * MB),
                 int((total_mb or size_mb) * MB), speed_mb * MB if not message else 0.0, idle, part, kind, message)
