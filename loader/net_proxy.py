# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Сеть линейки: напрямую или через прокси Windows - только если прокси жив (баг владельца 15.10.2026).

Владелец выключил «три буквы», а прокси Hiddify 127.0.0.1:12334 остался включённым в настройках Windows
(HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings: ProxyEnable=1, ProxyServer). urllib на
Windows берёт этот прокси сам (getproxies() читает реестр), requests/pip/huggingface_hub - тоже, и всё падает
«ProxyError ... WinError 10061». Правило линейки: всё, что качает по сети, идёт так:
- перед КАЖДОЙ попыткой (и перед каждой докачкой с Range) прокси проверяется TCP-соединением за 2 с;
- живой прокси - есть маршрут «через прокси»; мёртвый - его нет вовсе (ни ожидания, ни ошибки);
- «напрямую» - ЯВНО без прокси: ProxyHandler({}), иначе urllib снова пойдёт в прокси из реестра;
- порядок: маршрут, который сработал в прошлый раз, потом остальные; без истории - prefer ("direct" для нашего
  сервера в Москве, "proxy" - для сайтов, которые без «трёх букв» могут не открываться);
- прокси умер посреди скачивания - следующая попытка (с того же байта) идёт напрямую.

Жалоба владельца 17.10.2026 («ставил с включёнными «тремя буквами», выключил их, нажал «Повторить» - не пошёл»).
Измерено на настоящем loader.py: выключенные «три буквы» оставляют свой прокси в настройках Windows, и порт
ПРОДОЛЖАЕТ слушать, только ничего не отвечает. TCP-проверка такой прокси считает живым, а память «в прошлый раз
помог прокси» ставит его первым - и каждый заход в сеть висит на нём 20 с (а при скачивании 60 с), пока не
свалится на прямой путь. Установщик, запущенный заново, идёт напрямую сразу: 0,2 с против 20,2 с - для человека
это и есть «Повторить» не работает, а заново запустить помогает. Поэтому:
- `reset()` - «Повторить» начинает с чистого листа (память маршрута и список негодных прокси пусты);
- прокси, который принял соединение и не ответил, откладывается на PROXY_PAUSE секунд - повторные попытки
  скачивания больше не висят на нём; через минуту он проверяется заново (вдруг «три буквы» снова включили);
- оборвалась передача (а не открытие) - маршрут перестаёт считаться удачным: следующая попытка начнёт с prefer.

Только стандартная библиотека, Python 3.8+ (идёт и в установщики, и в setup Local Voice).
КОПИЯ ~/office_tools/_brand/net_proxy.py - не править копии, раздаёт python3 _brand/sync.py.

  net = Net(prefer="direct", user_agent="app-installer", log=print)
  r = net.open(url, headers={"Range": "bytes=100-"}, timeout=30)       # ответ urllib
  net.download(url, path, size)                                           # с докачкой
  apply_env()     # для дочерних процессов (pip) и requests/huggingface_hub: HTTP(S)_PROXY или NO_PROXY=*
"""
import os
import socket
import sys
import time
import urllib.parse
import urllib.request

PROBE_TIMEOUT = 2.0
PROXY_PAUSE = 60.0    # прокси принял соединение и не ответил - столько секунд не трогаем его вовсе
NO_PROXY_ALL = "*,pypi.org,pythonhosted.org,huggingface.co,hf.co,ty-biznesmen.ru"
_INET = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def read_registry():
    """Прокси из настроек Windows: {"http": url, "https": url, "raw": str, "override": str} или None.
    В тестах подменяется (net_proxy.read_registry = ...)."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INET) as k:
            enable = winreg.QueryValueEx(k, "ProxyEnable")[0]
            server = winreg.QueryValueEx(k, "ProxyServer")[0]
            try:
                override = winreg.QueryValueEx(k, "ProxyOverride")[0]
            except OSError:
                override = ""
    except OSError:
        return None
    if not enable or not server:
        return None
    return parse_server(str(server), str(override or ""))


def parse_server(raw, override=""):
    """'127.0.0.1:12334' или 'http=h:p;https=h:p;socks=h:p' -> {"http","https","raw","override"} (socks - не наш)."""
    http = https = None
    if "=" in raw:
        for part in raw.split(";"):
            k, _, v = part.partition("=")
            k, v = k.strip().lower(), v.strip()
            if k == "http":
                http = v
            elif k == "https":
                https = v
        https = https or http
        http = http or https
    else:
        http = https = raw.strip()
    if not http:
        return None

    def url(v):
        return v if "://" in v else "http://" + v
    return {"http": url(http), "https": url(https), "raw": raw, "override": override}


def system_proxy():
    """Прокси, который взял бы urllib: переменные HTTP(S)_PROXY, иначе реестр Windows. {} - прокси нет.
    -> {"http": url, "https": url, "override": str, "from": "env"|"registry"}"""
    env = {k: v for k, v in urllib.request.getproxies_environment().items() if k in ("http", "https") and v}
    if env:
        env.setdefault("https", env.get("http"))
        env.setdefault("http", env.get("https"))
        return {"http": env["http"], "https": env["https"], "override": "", "from": "env"}
    reg = read_registry()
    if reg:
        return {"http": reg["http"], "https": reg["https"], "override": reg.get("override", ""), "from": "registry"}
    return {}


def host_port(proxy_url):
    p = urllib.parse.urlsplit(proxy_url if "://" in proxy_url else "http://" + proxy_url)
    return p.hostname, p.port or (443 if p.scheme == "https" else 80)


def proxy_alive(proxy_url, timeout=PROBE_TIMEOUT):
    """True - на host:port прокси кто-то слушает (TCP за timeout с). Закрытый порт - сразу False."""
    try:
        h, p = host_port(proxy_url)
        if not h:
            return False
        with socket.create_connection((h, p), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def bypassed(url, override):
    """Адрес из исключений прокси Windows (ProxyOverride: '<local>;*.lan;10.*') - туда всегда напрямую."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    import fnmatch
    for pat in (override or "").replace(",", ";").split(";"):
        pat = pat.strip().lower()
        if not pat:
            continue
        if pat == "<local>":
            if "." not in host:
                return True
        elif fnmatch.fnmatch(host, pat):
            return True
    return False


class _Watched:
    """Ответ сервера, который замечает обрыв ПЕРЕДАЧИ (а не открытия) и говорит об этом Net.

    Без этого «три буквы», умершие посреди скачивания, оставались бы «удачным маршрутом»: следующая попытка
    снова шла бы в них первым делом и висела до таймаута (владелец 17.10.2026: «нажал «Повторить» - не пошёл»)."""

    def __init__(self, r, net, route, proxy_url):
        self._r, self._net, self._route, self._proxy = r, net, route, proxy_url
        self._got = 0
        self._told = False
        try:
            self._len = int(r.headers.get("Content-Length") or 0)
        except (AttributeError, TypeError, ValueError):
            self._len = 0

    def _failed(self):
        if not self._told:
            self._told = True
            self._net.transfer_failed(self._route, self._proxy)

    def _watch(self, name, *a, **kw):
        """Любое чтение через обёртку: считаем байты, замечаем обрыв и «закрылось, недодав байт».

        Почему не только read: боевое скачивание берёт у ответа `read1` (dl_progress._read), и защита,
        написанная для read(), обходилась в 100 % случаев - обрыв «трёх букв» посреди скачивания оставался
        незамеченным, а мёртвый маршрут считался удачным (нашла независимая приёмка 17.10.2026)."""
        fn = getattr(self._r, name)
        try:
            b = fn(*a, **kw)
        except Exception:  # noqa: BLE001
            self._failed()
            raise
        if isinstance(b, int):                 # readinto вернул число прочитанных байт
            if b:
                self._got += b
            elif self._len and self._got < self._len:
                self._failed()
            return b
        if b:
            self._got += len(b)
        elif self._len and self._got < self._len:
            self._failed()        # связь закрылась БЕЗ ошибки, недодав байт - так и умирают «три буквы»
        return b

    def read(self, *a, **kw):
        return self._watch("read", *a, **kw)

    def read1(self, *a, **kw):
        return self._watch("read1", *a, **kw)

    def readinto(self, *a, **kw):
        return self._watch("readinto", *a, **kw)

    def readline(self, *a, **kw):
        return self._watch("readline", *a, **kw)

    def close(self):
        try:
            self._r.close()
        except Exception:  # noqa: BLE001
            pass

    @property
    def status(self):
        return getattr(self._r, "status", 200)

    def __getattr__(self, name):
        return getattr(self._r, name)

    def __iter__(self):
        return iter(self._r)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Net:
    """Открыть URL / скачать файл: живой прокси или напрямую, выбор заново перед каждой попыткой."""

    def __init__(self, prefer="direct", user_agent=None, log=None, probe_timeout=PROBE_TIMEOUT, handlers=(),
                 clock=time.monotonic):
        self.prefer = prefer
        self.ua = user_agent
        self.log = log or (lambda m: None)
        self.probe_timeout = probe_timeout
        self.handlers = list(handlers)
        self.clock = clock
        self.good = None            # "direct" | "proxy" - что сработало в прошлый раз
        self.last_route = None      # чем открыт последний ответ (для тестов и журнала)
        self._dead_said = None
        self._paused = {}           # прокси, который подвёл -> до какого времени его не трогаем

    def reset(self):
        """Начать с чистого листа - это делает кнопка «Повторить» (владелец 17.10.2026). Забываем и удачный
        маршрут, и отложенные прокси: настройки Windows читаются заново, прокси щупается заново."""
        self.good = None
        self._dead_said = None
        self._paused.clear()

    def _pause_proxy(self, proxy_url, why=""):
        """Прокси открылся, но делу не помог - откладываем, чтобы следующие попытки не висели на нём."""
        if not proxy_url:
            return
        self._paused[proxy_url] = self.clock() + PROXY_PAUSE
        self.log(f"прокси {proxy_url} не помог ({why}) - дальше напрямую")

    def _opener(self, proxies):
        return urllib.request.build_opener(urllib.request.ProxyHandler(proxies), *self.handlers)

    def routes(self, url=""):
        """[(имя, opener)] в порядке попыток. Прокси проверяется заново при каждом вызове."""
        direct = ("direct", self._opener({}))                     # {} - явно без прокси (без реестра и переменных)
        sp = system_proxy()
        if not sp or (url and bypassed(url, sp.get("override"))):
            return [direct]
        until = self._paused.get(sp["https"])
        if until and self.clock() < until:
            return [direct]
        if until:
            self._paused.pop(sp["https"], None)                   # пауза вышла - пробуем его снова
        if not proxy_alive(sp["https"], self.probe_timeout):
            if self._dead_said != sp["https"]:
                self.log(f"прокси {sp['https']} ({sp['from']}) не отвечает - напрямую")
                self._dead_said = sp["https"]
            return [direct]
        self._dead_said = None
        proxy = ("proxy", self._opener({"http": sp["http"], "https": sp["https"]}))
        first = self.good or self.prefer
        return [proxy, direct] if first == "proxy" else [direct, proxy]

    def open(self, url, headers=None, timeout=30, data=None, method=None):
        err = None
        sp = system_proxy()
        purl = sp.get("https") if sp else None
        for name, opener in self.routes(url):
            h = dict(headers or {})
            if self.ua:
                h.setdefault("User-Agent", self.ua)
            try:
                r = opener.open(urllib.request.Request(url, data=data, headers=h, method=method), timeout=timeout)
                self.good = self.last_route = name
                return _Watched(r, self, name, purl)
            except Exception as e:  # noqa: BLE001
                self.log(f"{url} {'напрямую' if name == 'direct' else 'через прокси'}: {e!r}")
                if name == "proxy":
                    self._pause_proxy(purl, "не отвечает на запрос")
                err = e
        self.good = None             # не помог никто - следующий заход начинает с prefer, а не с мёртвого пути
        raise err

    def transfer_failed(self, route, proxy_url=None):
        """Передача оборвалась уже ПОСЛЕ открытия (так умирают «три буквы» посреди скачивания)."""
        if self.good == route:
            self.good = None
        if route == "proxy":
            self._pause_proxy(proxy_url, "оборвал передачу")

    def download(self, url, path, size=0, attempts=40, on_progress=None, on_retry=None, sleep=time.sleep,
                 chunk=1 << 18, timeout=30):
        """Скачать с докачкой (Range с уже скачанного байта); маршрут выбирается заново перед каждой попыткой."""
        for n in range(attempts):
            got = os.path.getsize(path) if os.path.exists(path) else 0
            if size and got >= size:
                return
            try:
                r = self.open(url, headers={"Range": f"bytes={got}-"} if got else None, timeout=timeout)
                if got and r.status != 206:          # сервер отдал файл целиком - начинаем заново
                    got = 0
                with open(path, "ab" if got else "wb") as out:
                    while True:
                        b = r.read(chunk)
                        if not b:
                            break
                        out.write(b)
                        got += len(b)
                        if on_progress:
                            on_progress(got)
                if not size or got >= size:
                    return
                self.log(f"соединение закрыто на {got} байт из {size}")
            except Exception as e:  # noqa: BLE001
                self.log(f"обрыв на {got} байт: {e!r}")
            if on_retry:
                on_retry(n, got)
            sleep(min(2 + n * 2, 15))
        raise ConnectionError("скачивание прерывалось слишком много раз")


def apply_env(environ=None, log=None):
    """Для дочерних процессов (pip) и библиотек на requests/httpx (huggingface_hub): они читают прокси из
    переменных и реестра сами. Живой прокси -> HTTP(S)_PROXY; мёртвый -> убрать их и NO_PROXY=* (напрямую).
    -> "proxy" | "direct" | "none" (прокси не настроен)."""
    env = os.environ if environ is None else environ
    reg = read_registry()
    cur = {k: env.get(k) or env.get(k.lower()) for k in ("HTTPS_PROXY", "HTTP_PROXY")}
    target = cur["HTTPS_PROXY"] or cur["HTTP_PROXY"] or (reg and reg["https"])
    if not target:
        return "none"
    if proxy_alive(target):
        if reg and not (cur["HTTPS_PROXY"] or cur["HTTP_PROXY"]):
            env["HTTP_PROXY"], env["HTTPS_PROXY"] = reg["http"], reg["https"]
        for k in ("NO_PROXY", "no_proxy"):
            if env.get(k, "").startswith("*"):
                env.pop(k, None)
        return "proxy"
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(k, None)
    env["NO_PROXY"] = env["no_proxy"] = NO_PROXY_ALL
    if log:
        log(f"прокси {target} не отвечает - напрямую (NO_PROXY=*)")
    return "direct"
