# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Самообновление программы - ОДИН механизм на всю линейку (вынесен из «Щелчка» 1.4.1, владелец 17.10.2026:
«программа сама следит за новыми обновлениями и если они есть, то предложит их установить» - про это он
рассказывает в видеоинструкции к КАЖДОЙ программе, значит работать должно везде и одинаково).

Открыто и честно, без «скрытого» скачивания: скрытая самозагрузка для антивирусов выглядит как вирус и
закрывает дорогу в каталоги программ.

Как устроено:
1. Раз в неделю (а после неудачной попытки - через сутки) программа ТИХО смотрит `latest.json` на нашем сервере.
   Версия та же - никаких окон и никаких слов, только строка в журнал.
2. Версия новее - СПРАШИВАЕМ человека: «Вышла версия X. Что нового: … Обновить сейчас?» Кнопки «Обновить» и
   «Позже». «Позже» - не спрашиваем ещё неделю.
3. «Обновить» - качаем установщик с показом прогресса (сколько МБ, скорость, сколько осталось - тот же модуль,
   что в установщике), проверяем sha256 из `latest.json`, запускаем установку поверх и закрываемся. ЭСТАФЕТА
   (баг 17.10.2026): установщику передаём номер своего процесса (--wait-pid), он ждёт, пока мы исчезнем, и
   только потом заменяет файлы; программа закрывается по-хорошему, а через EXIT_HARD_AFTER секунд - принудительно.
   Не получилось - текст по ПРИЧИНЕ (fail_texts): занятый файл не называем обрывом связи.
4. Галочка «Проверять обновления» (включена) и кнопка «Проверить сейчас» - в настройках каждой программы:
   человек видит, что происходит, и может выключить. Выключенная галочка - в сеть не ходим вовсе. В самом окне
   вопроса есть галочка «Ставить обновления сразу, не спрашивая» - выключена, это его отдельное решение.
5. Сеть - как в установщике (`net_proxy`): сначала напрямую, через прокси Windows - только если он отвечает;
   обрыв - докачка с того же байта; не получилось - молча откладываем до следующего раза, без тревожных окон.
6. Настройки и данные человека обновление не трогает: они лежат вне папки, которую заменяет установщик, а
   установщик при обновлении ничего не спрашивает и не вызывает удаление.

Каждая проверка - строкой в журнал программы: когда смотрели, что ответил сервер, что решили.

Своё у программы только адрес и имя установщика (BASE/SETUP в её `update.py`), журнал и окно вопроса.
КОПИЯ ~/office_tools/_brand/app_update.py - не править копии, раздаёт python3 _brand/sync.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time

try:                                     # модуль лежит в пакете программы (рядом net_proxy.py и dl_progress.py)
    from . import dl_progress, fail_texts, net_proxy
except ImportError:                      # ... или просто рядом: общие тесты _brand, отдельные проверки
    import dl_progress
    import fail_texts
    import net_proxy

CHECK_EVERY = 7 * 24 * 3600.0        # раз в неделю
RETRY_AFTER = 24 * 3600.0            # не получилось связаться - ещё раз через сутки
ASK_AGAIN = 7 * 24 * 3600.0          # «Позже» - не спрашиваем неделю
FIRST_DELAY = 120.0                  # первая проверка - через 2 минуты после запуска (не мешаем старту)
RECHECK_IDLE = 3600.0                # не вышло посмотреть сейчас - вернёмся к этому через час
INSTALL_DELAY = 0.8                  # человек успевает прочитать «Запускаю установку новой версии…»
# Сколько ждём, пока программа закроется сама, прежде чем выйти принудительно: установщик всё это время стоит
# и ждёт исчезновения нашего процесса (--wait-pid), заменять занятые файлы он не начинает.
EXIT_HARD_AFTER = 4.0

# Настройки самообновления - одни и те же во всех программах линейки (их DEFAULTS дополняются этим набором).
DEFAULTS = {
    "updates": True,               # раз в неделю тихо смотреть, вышла ли новая версия (и спрашивать человека)
    "update_auto": False,          # ставить сразу, не спрашивая (отдельное решение человека, по умолчанию нет)
    "update_last": 0.0,            # когда в последний раз смотрели сервер (epoch)
    "update_failed": False,        # прошлая проверка не удалась - повторим через сутки, а не через неделю
    "update_later": "",            # про эту версию человек сказал «Позже»
    "update_asked": 0.0,           # когда спрашивали
}

VERSION_RE = re.compile(r"^\d{1,4}(\.\d{1,4}){1,3}$")
SETUP_RE = re.compile(r"^[A-Za-z0-9._-]{3,80}\.exe$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
NOTES_MAX = 400


def normalize(settings, defaults=DEFAULTS):
    """Ключи самообновления в настройках: недостающие - умолчанием, негодные (строка вместо числа и т.п.) -
    тоже умолчанием. Миграция старого файла настроек: ничего, кроме этих ключей, не трогаем."""
    for k, d in defaults.items():
        v = settings.get(k, d)
        if isinstance(d, bool):
            ok = isinstance(v, bool)
        elif isinstance(d, float):
            ok = isinstance(v, (int, float)) and not isinstance(v, bool)
            v = float(v) if ok else d
        else:
            ok = isinstance(v, type(d))
        settings[k] = v if ok else d
    return settings


def parse_info(data, setup=""):
    """Ответ сервера -> проверенные поля или None, если в них мусор.

    Всё, что приходит снаружи, разбираем защищённо: при «setup_size»: «abc» поток скачивания раньше умирал с
    необработанной ошибкой, и окно навсегда застревало на «Скачиваю новую версию…» (нашла независимая приёмка
    16.10.2026). Негодный ответ = как недоступный сервер: строка в журнал и повтор позже."""
    if not isinstance(data, dict):
        return None
    ver = data.get("version")
    if not isinstance(ver, str) or not VERSION_RE.match(ver.strip()):
        return None
    out = {"version": ver.strip()}
    notes = data.get("notes")
    out["notes"] = notes.strip()[:NOTES_MAX] if isinstance(notes, str) else ""
    name = data.get("setup")
    name = os.path.basename(str(name)) if isinstance(name, str) else setup
    out["setup"] = name if SETUP_RE.match(name or "") else setup      # имя файла - только имя, без путей
    size = data.get("setup_size")
    try:
        out["setup_size"] = max(0, int(size)) if size is not None else 0
    except (TypeError, ValueError):
        out["setup_size"] = 0
    sha = data.get("setup_sha256")
    out["setup_sha256"] = sha.strip().lower() if isinstance(sha, str) and SHA_RE.match(sha.strip()) else ""
    return out


def ver_tuple(v):
    """Версия числами: «1.0.9» -> (1, 0, 9). Четвёртое число НЕ отбрасываем: было `[:3]`, и 1.0.0.2 равнялась
    1.0.0.1 - обновление молча не приходило (долг 17.10.2026; правило «одна строка - и обновления нет»)."""
    out = []
    for part in str(v or "").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out + [0, 0, 0])[:max(3, len(out))]


def newer(remote, local):
    """Версия на сервере новее установленной? Числа сравниваем по одной длине: 1.0.1 новее 1.0, а не наоборот."""
    a, b = ver_tuple(remote), ver_tuple(local)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Updater:
    """Проверка и скачивание. Без окон: всё проверяется тестами на числах и подменённой сетью.

    base   - адрес папки программы на сервере (там latest.json и установщик);
    setup  - имя установщика, если сервер его не прислал;
    folder - куда качать (по умолчанию %TEMP%\\<имя установщика без Setup>-update);
    save   - чем сохранить настройки после того, как мы их поменяли (может быть None).
    """

    def __init__(self, version, settings, log=None, base="", setup="Setup.exe", folder=None,
                 clock=time.time, net=None, save=None):
        self.version = version
        self.s = settings
        self.log = log or (lambda text: None)
        self.base = str(base).rstrip("/")
        self.setup = setup
        self.folder = folder
        self.clock = clock
        self.net = net or net_proxy.Net()
        self.save = save or (lambda: None)
        self.info = None              # что ответил сервер в прошлый раз
        self.busy = False
        # почему не вышло в прошлый раз (fail_texts: net / sha / space / server / busy / other) - окно говорит
        # человеку именно про это, а не «нет связи» про любую беду (баг 17.10.2026)
        self.fail_kind = ""
        # настройки, изменённые в потоке проверки, сохраняет окно (Controller.tick): у программ на Qt сохранение
        # заводит таймер, а таймеры Qt работают только в своём потоке - из чужого отметка «когда смотрели сервер»
        # молча не сохранялась бы, и проверка повторялась бы чаще, чем раз в неделю (нашла приёмка 17.10.2026)
        self.dirty = False
        self._th = None

    # ------------------------------------------------------------ когда пора
    def due(self, now=None):
        """Пора ли смотреть сервер. Выключена галочка - НИКОГДА (в сеть не ходим вовсе)."""
        if not self.s.get("updates", True):
            return False
        now = self.clock() if now is None else now
        last = float(self.s.get("update_last") or 0)
        wait = RETRY_AFTER if self.s.get("update_failed") else CHECK_EVERY
        return now - last >= wait

    def ask_due(self, version, now=None):
        """Спрашивать ли про эту версию (после «Позже» - не раньше чем через неделю)."""
        now = self.clock() if now is None else now
        if self.s.get("update_later") == str(version):
            return now - float(self.s.get("update_asked") or 0) >= ASK_AGAIN
        return True

    # ------------------------------------------------------------ сеть
    def fetch(self):
        """Прочитать latest.json. -> dict или None (сеть недоступна - это не ошибка, просто отложим)."""
        url = f"{self.base}/latest.json"
        try:
            with self.net.open(url, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - сеть; тревожных окон не показываем
            self.s["update_failed"] = True
            self.s["update_last"] = self.clock()
            self.dirty = True
            self.log(f"обновление: сервер не ответил ({type(e).__name__}) - посмотрю через сутки")
            return None
        self.s["update_last"] = self.clock()
        self.dirty = True
        info = parse_info(data, self.setup)
        if info is None:
            self.s["update_failed"] = True
            self.log("обновление: сервер ответил непонятным - посмотрю через сутки")
            return None
        self.s["update_failed"] = False
        self.info = info
        if not newer(info["version"], self.version):
            self.log(f"обновление: на сервере {info['version']}, у вас {self.version} - обновлять нечего")
            return None
        self.log(f"обновление: на сервере {info['version']}, у вас {self.version}")
        return info

    def check_async(self, done):
        """Проверка в отдельном потоке (окно не замирает). done(info|None) вызывается из того же потока."""
        if self.busy:
            return False
        self.busy = True

        def run():
            try:
                info = self.fetch()
            finally:
                self.busy = False
            done(info)
        self._th = threading.Thread(target=run, name="update-check", daemon=True)
        self._th.start()
        return True

    # ------------------------------------------------------------ скачивание
    def setup_name(self, info=None):
        info = info or self.info or {}
        return str(info.get("setup") or self.setup)

    def temp_folder(self):
        base = re.sub(r"[^A-Za-z0-9._-]", "", self.setup).replace(".exe", "") or "app"
        return os.path.join(tempfile.gettempdir(), base.lower() + "-update")

    def download(self, info, on_status, folder=None, cancel=None):
        """Скачать установщик с прогрессом и проверить sha256. -> путь или None.

        БЕЗ контрольной суммы обновление НЕ ставим: защита не должна зависеть от того, что лежит на сервере
        (независимая приёмка 16.10.2026). Нет суммы в ответе или она не сошлась - файл удаляем, пишем причину
        в журнал и пробуем в другой раз."""
        info = parse_info(info, self.setup) or {}
        self.fail_kind = ""
        if not info:
            self.fail_kind = fail_texts.SERVER
            self.log("обновление: ответ сервера непонятный - обновлять не буду")
            return None
        folder = folder or self.folder or self.temp_folder()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, self.setup_name(info))
        part = path + ".part"
        url = f"{self.base}/{self.setup_name(info)}"
        size = info.get("setup_size") or 0
        want = info.get("setup_sha256") or ""
        if not want:
            self.fail_kind = fail_texts.SERVER
            self.log("обновление ОТМЕНЕНО: сервер не прислал контрольную сумму установщика - без неё не ставлю")
            return None
        # Качаем в «.part» и переименовываем ТОЛЬКО после сверки суммы. Раньше качали прямо в итоговое имя, и
        # установщик от прошлого обновления оставался лежать: докачка принимала его размер за «уже скачано» и
        # либо считала работу сделанной, либо дописывала хвост новой версии к старому телу. У человека это
        # выглядело как «Файл скачался с ошибкой» на ровном месте - каждое второе обновление (найдено
        # приёмкой 17.10.2026; мы сами видели это на стенде и сочли случайностью).
        self._drop_stale(path, part, want, size)
        try:
            dl_progress.download(self.net.open, url, part, size, on_status, label="новую версию", log=self.log,
                                 cancel=cancel)
        except dl_progress.Cancelled:
            raise                      # «Отмена»: недокачанное оставляем, в другой раз продолжим с того байта
        except Exception as e:  # noqa: BLE001 - связь или диск; тревожных окон не показываем
            self.fail_kind = fail_texts.reason(e)
            self.log(f"обновление: скачать не вышло ({type(e).__name__}, причина «{self.fail_kind}») - попробую позже")
            return None
        got = sha256(part)
        if got != want:
            self.fail_kind = fail_texts.SHA
            self.log(f"обновление ОТМЕНЕНО: файл скачался с ошибкой (проверка не сошлась: {got[:12]}… "
                     f"вместо {want[:12]}…) - качаю заново в следующий раз")
            self._rm(part)
            return None
        try:
            os.replace(part, path)
        except OSError as e:
            self.fail_kind = fail_texts.reason(e)
            self.log(f"обновление: не смог переложить скачанное ({e!r})")
            return None
        self.log("обновление: файл скачан и проверен")
        return path

    @staticmethod
    def _rm(path):
        try:
            os.remove(path)
        except OSError:
            pass

    def _drop_stale(self, path, part, want, size):
        """Убрать то, что осталось от прошлых обновлений и мешает докачке.

        Докачка продолжает файл «с того же байта», поэтому недокачанный кусок ЧУЖОЙ версии надо выбросить:
        иначе к старому телу допишется хвост новой и сумма не сойдётся."""
        if os.path.exists(path):
            if sha256(path) == want:
                self.log("обновление: эта версия уже скачана - качать нечего")
            else:
                self.log("обновление: убираю установщик от прошлого раза")
            self._rm(path)
        if os.path.exists(part):
            got = os.path.getsize(part)
            if size and got > size:
                self.log(f"обновление: недокачанный кусок больше нужного ({got} из {size}) - начинаю заново")
                self._rm(part)
            elif size and got == size and sha256(part) != want:
                self.log("обновление: недокачанный кусок полон, но это другая версия - начинаю заново")
                self._rm(part)

    def install(self, path, run=None, pid=None):
        """Запустить установщик поверх и вернуть True (программа сразу после этого закрывается).

        Эстафета (баг 17.10.2026): установщику передаём НОМЕР СВОЕГО ПРОЦЕССА (--wait-pid). Он сначала ждёт,
        пока этот процесс исчезнет, и только потом заменяет файлы. Раньше установщик стартовал наперегонки с
        закрытием программы, упирался в занятый файл и падал - у владельца семь раз подряд.

        РАБОЧАЯ ПАПКА установщика - %TEMP%, а не наша (баг 17.10.2026 вечером, измерено на Windows 11): нас
        запускает ярлык, у которого рабочая папка - папка программы; установщик наследовал её и после этого
        САМ не давал себе заменить папку («файл занят другим процессом», 15 попыток подряд, программы при этом
        на компьютере уже не было). См. swap_dir.leave."""
        pid = os.getpid() if pid is None else pid
        args = [path, fail_texts.WAIT_ARG, str(pid)]
        run = run or (lambda a: subprocess.Popen(a, close_fds=True, cwd=tempfile.gettempdir()))   # noqa: S603
        try:
            run(args)
        except Exception as e:  # noqa: BLE001
            # step="launch": тут ничего не записывали, и прежний текст «Windows не дала записать файлы
            # программы» уводил человека не туда (долг 17.10.2026)
            self.fail_kind = fail_texts.reason(e, step="launch")
            self.log(f"обновление: установщик не запустился ({type(e).__name__}: {e})")
            return False
        self.log(f"обновление: запустил установку новой версии, закрываюсь (установщик ждёт процесс {pid})")
        return True


class Controller:
    """Когда смотреть сервер, кого спрашивать, что качать - без окон и без Qt.

    Окно даёт две вещи: `ask(info, auto)` - показать вопрос «Вышла версия X», и таймер, который зовёт `tick()`
    (раз в секунду). Ответы потоков складываются в буфер и разбираются в `tick()`, то есть ВСЕГДА в потоке окна:
    так сделано в «Щелчке» и так это переносится и на окна Qt, и на окна WebView2 без оговорок.
    """

    def __init__(self, updater, ask, log=None, quit=None, on_checked=None, first_delay=FIRST_DELAY,
                 mono=time.monotonic, exit_hard=False, exit_fn=None):
        self.u = updater
        self.ask = ask
        self.log = log or updater.log
        self.quit = quit or (lambda: None)
        # exit_hard=True (его передаёт каждая программа линейки) - после quit() процесс обязан исчезнуть:
        # через EXIT_HARD_AFTER секунд выходим принудительно. Иначе значок у часов, фоновый поток или веб-окно
        # держат процесс живым, его файлы заняты, и установщик не может их заменить (баг 17.10.2026).
        self.exit_hard = exit_hard
        self._exit = exit_fn or os._exit
        # чем ответить на кнопку «Проверить сейчас», когда новой версии нет: "none" - у вас последняя версия,
        # "fail" - сервер не ответил, "found" - показываем окно. Тихая недельная проверка молчит всегда.
        self.on_checked = on_checked or (lambda status: None)
        self.mono = mono
        self._next = mono() + first_delay
        self._found = None
        self._manual = False
        self._dl = None
        self._dl_thread = None        # живой поток скачивания: по нему отсекаем второе «Обновить»
        self._install_at = 0.0
        self._watch = None

    # ------------------------------------------------------------ часы
    def tick(self):
        """Раз в секунду: не пришёл ли ответ из потока проверки, не пора ли посмотреть сервер.

        Здесь же сохраняем настройки, которые изменил поток проверки: сохранение идёт ТОЛЬКО из потока окна."""
        if self.u.dirty:
            self.u.dirty = False
            self.u.save()
        found, self._found = self._found, None
        if found is not None:
            self.deliver(found)
        self._dl_tick()
        if self.mono() >= self._next and self.u.due():
            self._next = self.mono() + RECHECK_IDLE
            self.u.check_async(self._got)
            return True
        return False

    def watch(self, period=1.0):
        """Свой поток-таймер для окон, у которых нет своего (окна WebView2). Qt-программы зовут tick() из QTimer."""
        if self._watch is not None:
            return self._watch

        def loop():
            while True:
                time.sleep(period)
                try:
                    self.tick()
                except Exception as e:  # noqa: BLE001 - обновление не имеет права уронить программу
                    self.log(f"обновление: сбой проверки ({type(e).__name__})")
        self._watch = threading.Thread(target=loop, name="update-watch", daemon=True)
        self._watch.start()
        return self._watch

    def check_now(self):
        """Кнопка «Проверить сейчас»: смотрим сервер прямо сейчас, даже если галочка выключена."""
        if self.u.busy:
            return False
        self._manual = True
        self.log("смотрю, нет ли новой версии…")
        self.u.check_async(self._got)
        return True

    def _got(self, info):
        self._found = info or False          # False - «ответ был, новой версии нет»

    def deliver(self, info):
        """Ответ сервера. Версия та же (False) - молчим; новее - спрашиваем человека.

        Нажали «Проверить сейчас» - отвечаем всегда, даже если про эту версию человек говорил «Позже»: он сам
        спросил, и кнопка, которая молчит, выглядит как поломка."""
        manual, self._manual = self._manual, False
        if info is False or not info:
            if manual:
                self.on_checked("fail" if self.u.s.get("update_failed") else "none")
            return False
        if not manual and not self.u.ask_due(info.get("version")):
            self.log(f"обновление {info.get('version')}: вы просили спросить позже - подожду")
            return False
        self.u.s["update_asked"] = self.u.clock()
        self.u.save()
        if manual:
            self.on_checked("found")
        self.ask(info, bool(self.u.s.get("update_auto")))
        return True

    def later(self, info):
        """«Позже»: не спрашиваем про эту версию неделю."""
        self.u.s["update_later"] = str((info or {}).get("version") or "")
        self.u.s["update_asked"] = self.u.clock()
        self.u.save()
        self.log(f"обновление {(info or {}).get('version')}: отложено - спрошу через неделю")

    def set_auto(self, on):
        self.u.s["update_auto"] = bool(on)
        self.u.save()

    def set_enabled(self, on):
        self.u.s["updates"] = bool(on)
        self.u.save()
        self.log("проверка обновлений " + ("включена" if on else "выключена"))

    # ------------------------------------------------------------ скачивание
    def download(self, info, on_text, finished):
        """Скачать новую версию в отдельном потоке; строки прогресса и итог отдаём в окно из tick().

        Повторное «Обновить» (например, после «Отмены») не должно запускать ВТОРОЙ поток в тот же файл -
        иначе два скачивания пишут в один `.part` и ломают друг другу докачку (приёмка 17.10.2026).

        Защиту приходилось делать заново (долг 17.10.2026): она смотрела только на `self._dl`, а `cancel()`
        его обнулял - сам поток при этом жил и продолжал качать. Теперь отмену видит ПОТОК (флаг `stop`,
        его читает dl_progress), а второй запуск отсекается по живому потоку."""
        if self._dl_thread is not None and self._dl_thread.is_alive():
            self.log("обновление: скачивание уже идёт - второе не начинаю")
            return
        dl = self._dl = {"text": "", "said": "", "done": None, "told": False, "path": None,
                         "on_text": on_text, "finished": finished, "stop": False}

        def status(st):
            dl["text"] = st.line if hasattr(st, "line") else str(st)

        def run():
            try:
                path = self.u.download(info, status, cancel=lambda: bool(dl["stop"]))
            except dl_progress.Cancelled:
                self.log("обновление: скачивание прервано по кнопке «Отмена»")
                return
            except Exception as e:  # noqa: BLE001 - что бы ни случилось, окно не должно висеть на «Скачиваю…»
                self.u.fail_kind = fail_texts.reason(e)
                self.log(f"обновление: сорвалось ({type(e).__name__}, причина «{self.u.fail_kind}») - "
                         "можно попробовать ещё раз")
                path = None
            if dl["stop"]:
                self.log("обновление: скачалось, но человек уже нажал «Отмена» - не ставлю")
                return
            if path is None:
                dl["done"] = (False, fail_texts.update_message(self.u.fail_kind or fail_texts.OTHER))
                return
            dl["path"] = path
            dl["done"] = (True, "Запускаю установку новой версии…")
        self._dl_thread = threading.Thread(target=run, name="update-download", daemon=True)
        self._dl_thread.start()

    def _dl_tick(self):
        dl = self._dl
        if dl is None:
            return
        if dl["text"] and dl["text"] != dl["said"]:
            dl["said"] = dl["text"]
            dl["on_text"](dl["text"])
        if dl["done"] is not None and not dl["told"]:
            dl["told"] = True
            dl["finished"](*dl["done"])
            self._install_at = (self.mono() + INSTALL_DELAY) if dl["done"][0] else 0.0
        if self._install_at and self.mono() >= self._install_at:
            self._install_at = 0.0
            path = dl.get("path")
            finished = dl["finished"]
            self._dl = None
            if path and self.u.install(path):
                self.leave()
            else:
                # Установщик не запустился (антивирус унёс свежий файл в карантин, нет прав, файл занят) -
                # окно обязано об этом СКАЗАТЬ. Раньше оно навсегда застывало на «Запускаю установку новой
                # версии…»: кнопки «Повторить» нет, программа не закрывается, обновления нет (приёмка
                # 17.10.2026).
                kind = self.u.fail_kind or fail_texts.OTHER
                self.log(f"обновление: установщик не запустился (причина «{kind}») - говорю человеку")
                finished(False, fail_texts.update_message(kind))

    def leave(self):
        """Закрыться ПОЛНОСТЬЮ: установщик уже запущен и ждёт, пока наш процесс исчезнет (--wait-pid).

        Сначала просим программу закрыться по-хорошему (quit: окна, значок у часов, потоки, сохранение
        настроек). Если через EXIT_HARD_AFTER секунд процесс всё ещё жив - выходим принудительно: пока он жив,
        файлы программы заняты и установщик не может их заменить (баг 17.10.2026, семь отказов подряд)."""
        delay = EXIT_HARD_AFTER if self.exit_hard is True else float(self.exit_hard or 0)
        if self.exit_hard:
            # Сторожевой выход взводим ДО quit(): если quit() где-то заблокируется (окно, значок у часов,
            # сохранение настроек), таймер иначе не взведётся никогда, программа останется жить, а
            # установщик будет ждать её файлы до упора (приёмка 17.10.2026).
            def bye():
                time.sleep(delay)
                self.log("обновление: закрываюсь принудительно - установщик ждёт, когда освободятся файлы")
                self._exit(0)
            threading.Thread(target=bye, name="update-exit", daemon=True).start()
        self.quit()

    def cancel(self):
        """«Отмена» в окне: говорим ПОТОКУ остановиться и установку не запускаем.

        Раньше здесь только обнулялся `self._dl` - поток качал дальше, а следующее «Обновить» запускало
        второй поток в тот же файл (долг 17.10.2026)."""
        if self._dl is not None:
            self._dl["stop"] = True              # флаг видит сам поток: dl_progress бросит Cancelled
        self._dl = None
        self._install_at = 0.0


class WebApi:
    """Мостик для окон WebView2 (app-update.js): что окно зовёт у программы и что программа шлёт в окно.

    send(имя, что) - как программа шлёт событие в окно (обычно window.evaluate_js("app.onUpdateX(…)")); всегда
    РОВНО один свёрток данных, чтобы подошёл любой мостик окна.
    Методы ниже подставляются в класс Api программы: update_set_enabled, update_check_now, update_set_auto,
    update_later, update_start, update_cancel.
    """

    def __init__(self, controller, send):
        self.c = controller
        self.send = send
        self.info = None
        controller.ask = self.ask
        controller.on_checked = self.checked

    # ------------------------------------------------------------ в окно
    def ask(self, info, auto=False):
        self.info = info
        data = dict(info or {})
        data["auto"] = bool(auto)
        self.send("onUpdateFound", data)

    def checked(self, status):
        self.send("onUpdateChecked", str(status))

    # ------------------------------------------------------------ из окна
    def set_enabled(self, on):
        self.c.set_enabled(bool(on))
        return {"ok": True}

    def set_auto(self, on):
        self.c.set_auto(bool(on))
        return {"ok": True}

    def check_now(self):
        if not self.c.check_now():
            return {"ok": False}
        return {"ok": True}

    def later(self):
        self.c.later(self.info)
        return {"ok": True}

    def start(self):
        """«Обновить»: качаем и ставим; строки прогресса и итог уходят в окно."""
        if self.info is None:
            return {"ok": False}
        self.c.download(self.info, lambda text: self.send("onUpdateProgress", text),
                        lambda ok, text: self.send("onUpdateDone", {"ok": bool(ok), "text": text}))
        return {"ok": True}

    def cancel(self):
        self.c.cancel()
        return {"ok": True}
