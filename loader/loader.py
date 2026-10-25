"""Установщик программ линейки (решение владельца 11.10.2026): маленький файл, который скачивает программу с нашего
сервера ty-biznesmen.ru (Москва), ставит её в %LOCALAPPDATA%\\Programs, создаёт ярлыки и сообщает серверу об установке
(счётчик установок; ограничений и ключей нет - «на честное слово»).

Устойчивость (баги 12.10 с ноутбука владельца):
- соединение: сначала напрямую (сервер в России), если не вышло - через системный прокси «трёх букв» (Hiddify и т. п.), только
  если прокси отвечает (net_proxy.py; мёртвый прокси в настройках Windows - сразу напрямую);
- докачка: архив качается в %TEMP%\\<APP>-<версия>.part, при обрыве - пауза и продолжение с того же байта (Range),
  до 40 попыток; недокачанный файл переживает перезапуск установщика;
- одна копия установщика; если программа открыта - ждёт, пока её закроют;
- на экране короткие понятные сообщения, технические подробности - в %TEMP%\\<APP>-install.log; кнопка «Повторить».

На сервере: /apps/<APP>/latest.json {"version","zip","sha256","size","exe","title"}, /apps/<APP>/<zip>,
Проверка вида окна: loader.py --demo progress|update|first|done|error|wait|busy|busyfile|busywait (без скачивания).
"""
import ctypes, datetime, hashlib, json, os, subprocess, sys, tempfile, threading, time
import uuid, webbrowser, zipfile
import tkinter as tk

from brandflow_tk import Flow
from install_version import VERSION_FILL, VERSION_FONT, VERSION_WIDTH, VERSION_Y, VERSION_FILE, done_line, version_line, installed_version as _installed_version

APP = "shchelchok"
TITLE = "Щелчок"
BASE = f"https://ty-biznesmen.ru/apps/{APP}"
DEST = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", TITLE)
# Журнал «пишется бесконечно» (решение владельца 17.10.2026): %LOCALAPPDATA%\<Название>\logs,
# файл на каждый день, объём папки ограничен, старые дни убираются с записью об этом. Раньше журнал
# лежал в %TEMP% - его чистит сама Windows, и единственное доказательство причины могло пропасть.
import app_log                                   # копия _brand, раздаёт sync.py
_LOG = app_log.Log(APP, TITLE, kind="install")
LOG = _LOG.path
PALETTE = ["#310A6E", "#5B21B6", "#8B5CF6", "#C084FC", "#6D28D9", "#43148F"]   # фон, если перелив не построился
ATTEMPTS = 40


def log(msg):
    """Одна запись - одна строка со временем (журнал читается глазами и обычным поиском)."""
    _LOG(msg)


# ---------------------------------------------------------------- сеть: напрямую, потом через ЖИВОЙ прокси
# net_proxy.py (копия ~/office_tools/_brand, раздаёт sync.py): «напрямую» - явно без прокси (ProxyHandler({}), иначе
# urllib сам берёт прокси из настроек Windows); прокси из реестра/переменных проверяется TCP за 2 с перед КАЖДОЙ
# попыткой и докачкой - выключенные «три буквы», оставившие прокси в настройках (баг 15.10.2026, Hiddify 127.0.0.1:12334),
# не роняет и не тормозит установку; прокси умер посреди скачивания - следующая попытка напрямую с того же байта.
from net_proxy import Net
import fail_texts               # причина и текст: занятый файл - не «нет связи» (баг 17.10.2026, копия _brand)
import dl_progress                # прогресс: скачано / всего · скорость · осталось (копия _brand)
import swap_dir                  # замена папки программы: папку не дали - меняем по файлам (копия _brand)

_NET = Net(prefer="direct", user_agent=f"{APP}-installer", log=log)


def open_url(url, headers=None, timeout=30):
    """Открыть URL: сначала способом, который сработал в прошлый раз (без истории - напрямую), затем другим."""
    return _NET.open(url, headers=headers, timeout=timeout)


def get_json(url, w):
    """Спросить сервер, какая версия выложена. Причину отказа называем своим именем.

    Долг 17.10.2026: любая ошибка здесь крутилась восемь попыток под текстом «Нет связи с сервером» -
    и 404 на latest.json, и отказ записи, и сломанное окружение процесса. «Нет связи» - подозрительный
    диагноз: он уводит человека выключать «три буквы», которые тут ни при чём."""
    last = None
    for n in range(8):
        try:
            return json.loads(open_url(url, timeout=20).read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            # ответ пришёл, но это не наш json: сервер отдал мусор или страницу-заглушку. Советовать человеку
            # чинить интернет тут нечестно - дело не в нём (приёмка 17.10.2026)
            log(f"сервер ответил непонятным: {e!r}")
            raise fail_texts.Fail(fail_texts.SERVER, "ответ сервера не разобрать")
        except Exception as e:  # noqa: BLE001
            last = e
            kind = fail_texts.reason(e)
            code = int(getattr(e, "code", 0) or 0)
            if kind not in (fail_texts.NET, fail_texts.OTHER) and not 500 <= code < 600:
                # 404 (файла нет), 403, отказ записи, нет места - за восемь попыток это не изменится
                log(f"сервер/окружение: причина «{kind}» ({e!r}) - повторять нечего")
                raise fail_texts.Fail(kind, str(e) or repr(e))
            if code:                       # у нас упало на сервере: повторить стоит, но говорим прямо
                w.say(f"Сервер ответил ошибкой {code}, пробую ещё раз ({n + 1} из 8)…")
            elif kind == fail_texts.NET:
                # с третьей попытки добавляем подсказку про «три буквы»: чаще всего связь рвут именно они
                hint = " " + fail_texts.HINT_CAP if n + 1 >= 3 else ""
                w.say(f"Нет связи с сервером, пробую ещё раз ({n + 1} из 8)…" + hint)
            else:
                # что это было - непонятно. Повторить стоит, но объявлять это обрывом связи нельзя
                log(f"неизвестная ошибка при запросе к серверу: {e!r}")
                w.say(f"Сервер не ответил, пробую ещё раз ({n + 1} из 8)…")
            time.sleep(min(2 ** n, 10))
    kind = fail_texts.reason(last) if last is not None else fail_texts.NET
    raise fail_texts.Fail(kind, f"сервер так и не ответил ({last!r})" if last is not None else "нет связи с сервером")


def need_fields(info, *keys):
    """Проверить, что в latest.json есть всё, без чего установка не пойдёт.

    Долг 18.10.2026 (живой опыт на стенде, «Озвучка»): не было поля `packages` - установщик падал
    `KeyError('packages')` и показывал «Установка не получилась». Негодные поля в latest.json ведём себя
    как недоступный сервер: строка в журнал, понятный текст, кнопка «Повторить»."""
    bad = [k for k in keys if not (info or {}).get(k)]
    if bad:
        log("в latest.json не хватает полей: " + ", ".join(bad))
        raise fail_texts.Fail(fail_texts.SERVER, "в ответе сервера нет полей: " + ", ".join(bad))
    return info


def download(url, path, size, w, label="программу"):
    """Скачать с докачкой и строкой «скачано из всего · скорость · осталось» (общий модуль dl_progress.py - копия
    ~/office_tools/_brand, раздаёт sync.py): после обрыва - с того же байта (Range), 60 с без данных - «соединение
    подвисло, переподключаюсь» и новая попытка (владелец 15.10.2026: «может он завис»)."""
    dl_progress.download(open_url, url, path, size, lambda st: w.say(st.text, 5 + 80 * st.frac), label=label,
                         attempts=ATTEMPTS, log=log)


# ---------------------------------------------------------------- Windows: ярлыки, процессы
def ps(script, what=""):
    """Выполнить кусочек PowerShell. Код возврата ПРОВЕРЯЕМ: раньше ярлык мог не создаться, а окно всё равно
    обещало «ярлык на рабочем столе» (замечание приёмки 17.10.2026)."""
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, creationflags=0x08000000)
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip().replace("\n", " ")[:200]
        log(f"{what or 'команда Windows'}: не получилось (код {r.returncode}) {err}")
    return r.returncode == 0


def q(s):
    return "'" + s.replace("'", "''") + "'"


def shortcut(lnk, target, workdir, icon, args=""):
    """Создать ярлык и ПРОВЕРИТЬ, что он появился (иначе обещание «ярлык на рабочем столе» - неправда)."""
    ok = ps(f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({q(lnk)});$s.TargetPath={q(target)};"
            f"$s.Arguments={q(args)};$s.WorkingDirectory={q(workdir)};$s.IconLocation={q(icon + ',0')};$s.Save()",
            what=f"ярлык {os.path.basename(lnk)}")
    if not ok or not os.path.exists(lnk):
        log(f"ярлык не создан: {lnk}")
        return False
    return True

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\TyBiznesmen-" + APP


def register_uninstall(exe, un, version):
    """Запись в «Установка и удаление программ» Windows (для текущего пользователя, без прав администратора).
    12.10.2026: без неё программу нельзя было удалить из Параметров Windows - только ярлыком в «Пуске»."""
    import winreg
    size_kb = 0
    for root, _, files in os.walk(DEST):
        for name in files:
            try:
                size_kb += os.path.getsize(os.path.join(root, name)) // 1024
            except OSError:
                pass
    cmd = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{un}"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, value in (("DisplayName", TITLE), ("DisplayVersion", str(version)), ("Publisher", "ТЫ - бизнесмен"),
                            ("DisplayIcon", exe), ("InstallLocation", DEST), ("UninstallString", cmd),
                            ("QuietUninstallString", cmd), ("URLInfoAbout", "https://ty-biznesmen.ru/")):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        for name, value in (("NoModify", 1), ("NoRepair", 1), ("EstimatedSize", min(size_kb, 0xFFFFFFFF))):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)



DEMO_OLD, DEMO_NEW = "1.4.5", "1.4.6"        # только для --demo update/first/done


def installed_version():
    """Версия, которая уже стоит (реестр DisplayVersion, запасной - version.txt); нет - None. Общая логика -
    install_version.py (копия из ~/office_tools/_brand, одна на всю линейку)."""
    return _installed_version(DEST, UNINSTALL_KEY)


def desktop_dir():
    """Настоящий рабочий стол этого человека.

    Склеивать «~/Desktop» нельзя: на Windows 11 папку часто переносит OneDrive, и ярлык лёг бы туда, где его
    не видно, а окно обещало бы «ярлык на рабочем столе» (замечание приёмки 17.10.2026). Спрашиваем у Windows
    известную папку Desktop; не вышло - возвращаемся к прежнему пути."""
    try:
        import ctypes
        import ctypes.wintypes as wt
        import uuid as _uuid
        guid = _uuid.UUID("B4BFCC3A-DB2C-424C-B029-7FE99A87C641")        # FOLDERID_Desktop

        class GUID(ctypes.Structure):
            _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16),
                        ("d", ctypes.c_ubyte * 8)]

        g = GUID()
        g.a, g.b, g.c = guid.fields[0], guid.fields[1], guid.fields[2]
        rest = bytes([guid.fields[3], guid.fields[4]]) + guid.fields[5].to_bytes(6, "big")
        g.d = (ctypes.c_ubyte * 8)(*rest)
        out = ctypes.c_wchar_p()
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        if shell.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0 and out.value:
            path = out.value
            ctypes.windll.ole32.CoTaskMemFree(out)
            return path
    except Exception as e:  # noqa: BLE001 - не Windows или не вышло: берём прежний путь
        log(f"рабочий стол у Windows не спросился ({e!r}) - беру обычный путь")
    return os.path.join(os.path.expanduser("~"), "Desktop")


def folder(name):
    if name == "programs":
        return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
    return desktop_dir()


def app_running(exe_name):
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/NH"], capture_output=True, text=True,
                         creationflags=0x08000000).stdout
    return exe_name.lower() in out.lower()


WAIT_EXIT = 30.0          # с: столько ждём, пока программа закроется сама (её запустило самообновление)
WAIT_CLOSE = 300          # с: столько ждём человека, если программу открыли руками
EXE = {"name": ""}        # имя exe программы - чтобы кнопка «Закрыть программу и продолжить» работала и в окне отказа


def pid_is_ours(exe_name, pid):
    """Процесс с этим номером - точно наша программа?

    Windows быстро переиспользует номера процессов, а между запуском установщика (номер пришёл ключом
    --wait-pid) и заменой файлов проходят десятки секунд: скачиваются мегабайты. К этому времени номер мог
    достаться чужой программе - и наша «просьба закрыться» улетела бы, например, в браузер со всеми его
    вкладками (замечание независимой приёмки 17.10.2026). Поэтому перед закрытием сверяем ИМЯ файла."""
    if not pid:
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH", "/FO", "CSV"],
                             capture_output=True, text=True, creationflags=0x08000000).stdout or ""
    except (OSError, ValueError) as e:
        log(f"не смог проверить, чей процесс {pid}: {e!r}")
        return False
    return exe_name.lower() in out.lower()


def kill_app(exe_name=None, pid=0):
    """Закрыть программу: сначала по-хорошему (окну - просьба закрыться), через 1,5 с - принудительно."""
    exe_name = exe_name or EXE["name"]
    if not exe_name:
        return
    # по номеру - только если это ТОЧНО наша программа (номера переиспользуются, см. pid_is_ours)
    ours = pid and pid_is_ours(exe_name, pid)
    if pid and not ours:
        log(f"процесс {pid} - уже не «{exe_name}», закрываю программу по имени")
    first = ["taskkill", "/PID", str(pid)] if ours else ["taskkill", "/IM", exe_name]
    subprocess.run(first, capture_output=True, creationflags=0x08000000)
    time.sleep(1.5)
    if app_running(exe_name):
        # без /T: он завершает ВСЁ дерево процессов, а установщик - потомок программы, которую мы закрываем,
        # и мог бы убить сам себя (замечание приёмки 17.10.2026)
        subprocess.run(["taskkill", "/IM", exe_name, "/F"], capture_output=True, creationflags=0x08000000)
        time.sleep(0.5)


def wait_exit(w, exe_name):
    """Эстафета самообновления (баг 17.10.2026): программа запустила установщик и передала номер своего
    процесса (--wait-pid). Пока этот процесс жив, файлы программы заняты - ждём, пока он исчезнет, и только
    потом меняем файлы. Раньше установщик начинал наперегонки с закрытием программы и падал с «файл занят»."""
    pid = fail_texts.wait_pid_arg(sys.argv)
    if not pid:
        return
    if not pid_is_ours(exe_name, pid):      # номер уже чужой - ждать нечего и трогать чужое нельзя
        log(f"процесс {pid} - уже не «{exe_name}»: программа закрылась, жду только её файлы")
        return
    w.say(fail_texts.waiting(TITLE), 88)
    log(f"жду, пока закроется программа (процесс {pid})")
    if fail_texts.wait_pid(pid, WAIT_EXIT):
        log(f"процесс {pid} закрылся - можно менять файлы")
    else:
        log(f"процесс {pid} не закрылся за {WAIT_EXIT:.0f} с - закрываю программу сам")
        kill_app(exe_name, pid)


def ask_close(w, exe_name):
    """Программа всё ещё открыта - просим закрыть и даём кнопку, которая закрывает её сама."""
    if not app_running(exe_name):
        return
    w.say(f"Программа «{TITLE}» сейчас открыта. Закройте её - установка продолжится сама.", 88)
    w.buttons([(fail_texts.close_button(), lambda: kill_app(exe_name), True)])
    for _ in range(WAIT_CLOSE):
        if not app_running(exe_name):
            break
        time.sleep(1)
    else:
        raise fail_texts.Fail(fail_texts.BUSY, "программа всё ещё открыта")
    w.buttons([])
    time.sleep(1)


def swap(w, new, exe_name):
    """Заменить папку программы свежей - общий swap_dir (копия _brand, раздаёт sync.py).

    Баг 17.10.2026: папку программы держал САМ установщик (программа запускала его и передавала свою рабочую
    папку), и все 15 попыток переименования падали подряд с «файл занят другим процессом», хотя программы на
    компьютере уже не было. Теперь: уходим из папки, не дали переименовать - меняем файлы по одному, занятый
    файл называем по имени вместе с программой, которая его держит, паузы растут (всего ~2 минуты, антивирусу
    хватает), при неудаче - откат к старой версии."""
    def on_busy(last, pause):
        ask_close(w, exe_name)          # вдруг программу всё-таки открыли руками - кнопка её закроет
        w.say(fail_texts.busy_wait(getattr(last, "path", ""), getattr(last, "holders", ()), pause,
                                   kind=getattr(last, "kind", fail_texts.BUSY)), 90)

    kept = swap_dir.swap(DEST, new, log=log, on_busy=on_busy)
    if kept:
        log("файлы, оставленные как были (в новой версии такие же): " + ", ".join(kept))


def close_other_installers():
    """Новый установщик заменяет старый (владелец 12.10: «линия должна быть одна»): закрыть другие окна установки
    этой программы, кроме своего процесса и своего родителя (сборка onefile = 2 процесса)."""
    me, parent = os.getpid(), os.getppid()
    script = (
        f"$title = {q('Установка - ' + TITLE)}\n"
        f"Get-Process | Where-Object {{ $_.MainWindowTitle -eq $title -and $_.Id -ne {me} -and $_.Id -ne {parent} }} | ForEach-Object {{\n"
        "  $pp = (Get-CimInstance Win32_Process -Filter \"ProcessId=$($_.Id)\").ParentProcessId\n"
        "  $par = Get-Process -Id $pp -ErrorAction SilentlyContinue\n"
        "  Stop-Process -Id $_.Id -Force\n"
        "  if ($par -and $par.ProcessName -eq $_.ProcessName) { Stop-Process -Id $pp -Force }   # только тот же установщик, не Проводник\n"
        "}\n")
    ps(script)
    time.sleep(1)


def resource(name):
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), name)


# ---------------------------------------------------------------- окно
class Win:
    W, H = 560, 290

    def __init__(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)            # чёткое окно при масштабе 125-200 %
            k = ctypes.windll.user32.GetDpiForSystem() / 96.0
        except Exception:  # noqa: BLE001
            k = 1.0
        self.k = k
        self.root = tk.Tk()
        self.root.tk.call("tk", "scaling", 96 * k / 72)
        self.root.title(f"Установка - {TITLE}")
        try:
            self.root.iconbitmap(resource("icon.ico"))
        except Exception:  # noqa: BLE001
            pass
        w, h = int(self.W * k), int(self.H * k)
        self.root.geometry(f"{w}x{h}+{(self.root.winfo_screenwidth() - w) // 2}+{(self.root.winfo_screenheight() - h) // 2}")
        self.root.resizable(False, False)
        self.c = tk.Canvas(self.root, width=w, height=h, highlightthickness=0, bd=0)
        self.c.pack(fill="both", expand=True)
        # фирменный перелив плашки Local Voice (общий набор _brand, brandflow_tk.py): полосы плывут из правого нижнего угла
        # в левый верхний, два световых пятна; при установке - быстрее. --still - неподвижный кадр той же формулы.
        try:
            self.flow = Flow(self.c, w, h, static="--still" in sys.argv)
        except Exception as e:  # noqa: BLE001 - без перелива окно всё равно рабочее
            log(f"перелив: {e!r}")
            self.flow = None
            self.c.configure(bg=PALETTE[1])
        S = self.s
        self.title = self.text(w // 2, S(44), TITLE, "white", ("Segoe UI", 17, "bold"))
        # сообщение - своя область под заголовком (y 78..158), перенос строк, ничего не накладывается
        self.ver = self.text(w // 2, S(VERSION_Y), "", VERSION_FILL, VERSION_FONT, width=S(VERSION_WIDTH))   # версия: было/стало (install_version.py)
        self.msg = self.text(w // 2, S(118), "Подготовка…", "#FFFFFF", ("Segoe UI", 10), width=S(480))
        self.c.create_rectangle(S(40), S(172), w - S(40), S(186), outline="#FFFFFF", width=1, fill="#2A0A5E")
        self.bar = self.c.create_rectangle(S(41), S(173), S(41), S(185), outline="", fill="#FFD60A")
        self.btns = []
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    def s(self, v):
        return int(v * self.k)

    def text(self, x, y, text, fill, font, width=0):
        """Текст с тёмной тенью (как надписи плашки Local Voice) - читается на светлых полосах перелива."""
        d = max(1, self.s(1))
        kw = dict(text=text, font=font, justify="center", width=width)
        shadow = self.c.create_text(x + d, y + d, fill="#14003C", **kw)
        main = self.c.create_text(x, y, fill=fill, **kw)
        return (shadow, main)

    def ui(self, fn):
        self.root.after(0, fn)

    def version(self, text):
        def f():
            for it in self.ver:
                self.c.itemconfigure(it, text=text)
        self.ui(f)

    def say(self, text, pct=None):
        def f():
            for it in self.msg:
                self.c.itemconfigure(it, text=text)
            if self.flow and pct is not None:
                self.flow.work(0 < pct < 100)                      # идёт установка - перелив как при записи
            if pct is not None:
                p = max(0.0, min(1.0, pct / 100))
                self.c.coords(self.bar, self.s(41), self.s(173), self.s(41) + (self.s(self.W - 41) - self.s(41)) * p, self.s(185))
        self.ui(f)

    def buttons(self, items):
        def f():
            for b in self.btns:
                b.destroy()
            self.btns = []
            n = len(items)
            for i, (label, cmd, primary) in enumerate(items):
                b = tk.Button(self.root, text=label, command=cmd, relief="flat", cursor="hand2",
                              bg="#FFFFFF" if primary else "#4C1D95", fg="#4C1D95" if primary else "#FFFFFF",
                              activebackground="#EDE9FE", font=("Segoe UI", 10, "bold"), padx=14, pady=4)
                x = self.s(self.W // 2 + (i - (n - 1) / 2) * 190)
                self.c.create_window(x, self.s(236), window=b)
                self.btns.append(b)
        self.ui(f)


def install(w, demo=None):
    if demo:
        return show_demo(w, demo)
    try:
        log("старт установки")
        swap_dir.leave(DEST, log)     # папку программы не должны держать мы сами (баг 17.10.2026)
        swap_dir.finish_plan(DEST, log)   # прерванную пофайловую замену доигрываем: файлы - на место
        swap_dir.repair(DEST, log)    # прошлая установка оборвалась на середине - вернуть программу на место
        w.say("Связываюсь с сервером…", 2)
        info = get_json(f"{BASE}/latest.json", w)
        need_fields(info, "version", "zip", "sha256", "exe", "size")
        old_version = installed_version()
        log(f"установлена сейчас: {old_version or 'нет'}, ставим {info['version']}")
        w.version(version_line(old_version, info["version"]))
        part = os.path.join(tempfile.gettempdir(), f"{APP}-{info['version']}.part")
        download(f"{BASE}/{info['zip']}", part, int(info.get("size") or 0), w)
        w.say("Проверяю скачанный файл…", 86)
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != info["sha256"]:
            os.remove(part)
            raise RuntimeError("файл скачался с ошибкой")
        exe_name = EXE["name"] = os.path.basename(info["exe"])
        wait_exit(w, exe_name)       # обновление из настроек программы: ждём, пока она сама закроется
        ask_close(w, exe_name)       # открыта руками - просим закрыть (кнопка закрывает сама)
        w.say("Устанавливаю…", 90)
        new = swap_dir.new_path(DEST)
        swap_dir.cleanup(DEST, log)          # остатки прошлой попытки (у владельца 17.10 осталось 60 МБ)
        with zipfile.ZipFile(part) as z:
            z.extractall(new)
        if not os.path.isfile(os.path.join(new, info["exe"])):
            # Сумма сошлась, но внутри не то: лишняя верхняя папка в архиве или антивирус унёс свежий exe.
            # Скачанное убираем, иначе «Повторить» мгновенно «докачает» из готового файла и упрётся в то же
            # самое - круг без выхода (приёмка 17.10.2026).
            log(f"в распакованном нет {info['exe']} - убираю скачанное, следующая попытка скачает заново")
            swap_dir.cleanup(DEST, log)
            try:
                os.remove(part)
            except OSError:
                pass
            raise fail_texts.Fail(fail_texts.SHA, f"в архиве нет {info['exe']}")
        swap(w, new, exe_name)
        os.remove(part)
        exe = os.path.join(DEST, info["exe"])
        w.say("Создаю ярлыки…", 95)
        shortcut(os.path.join(folder("desktop"), f"{TITLE}.lnk"), exe, DEST, exe)
        shortcut(os.path.join(folder("programs"), f"{TITLE}.lnk"), exe, DEST, exe)
        un = os.path.join(DEST, "uninstall.ps1")
        with open(un, "w", encoding="utf-8-sig") as f:
            f.write(f"Stop-Process -Name {q(os.path.splitext(exe_name)[0])} -Force -ErrorAction SilentlyContinue\n")
            for lnk in (os.path.join(folder("desktop"), TITLE + ".lnk"), os.path.join(folder("programs"), TITLE + ".lnk"),
                        os.path.join(folder("programs"), "Удалить " + TITLE + ".lnk")):
                f.write(f"Remove-Item -LiteralPath {q(lnk)} -ErrorAction SilentlyContinue\n")
            f.write(f"Start-Sleep 1; Remove-Item -LiteralPath {q(DEST)} -Recurse -Force -ErrorAction SilentlyContinue\n")
            # автозапуск (если включали в настройках) и настройки программы
            f.write("Remove-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' -Name "
                    + q(TITLE) + " -ErrorAction SilentlyContinue\n")
            # задание «запускать с правами администратора», если его создавали в настройках программы
            f.write("schtasks.exe /Delete /F /TN " + q("Щелчок - запуск с правами администратора")
                    + " 2>$null | Out-Null\n")
            # Настройки человека (цвет, клавиши, папки, калибровка) при удалении НЕ стираем: люди часто
            # удаляют, чтобы поставить начисто, и теряют всё, что настраивали руками (находка 18.10.2026 -
            # я сам так снёс настройки на стенде). Убираем только служебное, настройки и журналы оставляем
            # и говорим человеку, где они лежат.
            f.write(f"$cfg = Join-Path $env:APPDATA {q(TITLE)}\n")
            f.write("if (Test-Path -LiteralPath $cfg) { Get-ChildItem -LiteralPath $cfg -Force |"
                    " Where-Object { $_.Name -ne 'settings.json' } |"
                    " Remove-Item -Recurse -Force -ErrorAction SilentlyContinue }\n")
            f.write("if ((Test-Path -LiteralPath $cfg) -and -not (Get-ChildItem -LiteralPath $cfg -Force))"
                    " { Remove-Item -LiteralPath $cfg -Force -ErrorAction SilentlyContinue }\n")
            f.write(f"Remove-Item -LiteralPath {q('HKCU:' + chr(92) + UNINSTALL_KEY)} -Recurse -ErrorAction SilentlyContinue\n")
            f.write("Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show("
                    + q(f"Программа «{TITLE}» удалена.\n\nВаши настройки остались - если поставите её снова, всё "
                        f"будет как было: %APPDATA%\\{TITLE}. Журналы остались в %LOCALAPPDATA%\\{TITLE}\\logs. "
                        "Не нужны - эти папки можно удалить руками.")
                    + ", " + q(TITLE) + ") | Out-Null\n")
        shortcut(os.path.join(folder("programs"), "Удалить " + TITLE + ".lnk"), "powershell.exe", DEST, exe,
                 args=f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{un}"')
        try:
            register_uninstall(exe, un, info["version"])
        except Exception as e:  # noqa: BLE001 - без записи в список программ всё равно работает ярлык «Удалить»
            log(f"запись в «Установка и удаление программ»: {e!r}")
        try:
            with open(os.path.join(DEST, VERSION_FILE), "w", encoding="utf-8") as f:
                f.write(str(info["version"]))
        except OSError as e:
            log(f"{VERSION_FILE}: {e!r}")
        log(f"установлено {info['version']}")
        done(w, exe, info["version"])
        return                                   # дальше - только уборка, она не влияет на «Готово»
    except Exception as e:  # noqa: BLE001
        log(f"ошибка: {e!r}")
        # убираем только то, что сами распаковали; при обрыве связи трогать чужое и старое незачем
        if os.path.isdir(swap_dir.new_path(DEST)):
            swap_dir.cleanup(DEST, log)      # за собой убираем: распакованная папка на диске не остаётся
        fail(w, e)


SITE = "https://ty-biznesmen.ru/"


def done(w, exe, version=None):
    if version:
        w.version(done_line(version))
    # владелец 16.10.2026: программу раздаём бесплатно, на экране «Готово» - про остальные программы
    w.say(f"Готово! Программа установлена.\nЯрлык «{TITLE}» - на рабочем столе.\n"
          f"Эта программа бесплатная. Остальные мои программы - на сайте.", 100)
    w.buttons([("Открыть программу", lambda: (subprocess.Popen([exe], cwd=os.path.dirname(exe), env=child_env()) if exe else None,
                                             w.root.destroy()), True),
               ("Другие программы", lambda: webbrowser.open(SITE), False)])


TRIES = {"n": 0}        # сколько раз человек нажимал «Повторить» - второй отказ говорится другими словами


def fail(w, e):
    """У каждой причины свой текст (общий fail_texts - он же в самообновлении самой программы).

    Баг 17.10.2026: любая неузнанная ошибка объявлялась обрывом связи, и «файл занят другим процессом»
    показывался как «Связаться с сервером не удалось» - владелец и главный полчаса искали причину в
    «трёх буквах», которых там не было."""
    kind = fail_texts.reason(e)
    log(f"отказ: причина «{kind}»" + (f", занятый файл: {getattr(e, 'path', '')}" if getattr(e, "path", "") else ""))
    w.say(fail_texts.message(kind, TITLE, second=bool(TRIES["n"]), detail=str(e),
                             path=getattr(e, "path", ""), holders=getattr(e, "holders", ()))
          + "\n" + fail_texts.log_line(_LOG.path), 0)
    if kind == fail_texts.BUSY:
        # главная кнопка закрывает программу сама и сразу продолжает установку; вторая - та самая «Повторить»,
        # про которую сказано в тексте (закрыл программу руками - нажал «Повторить»)
        w.buttons([(fail_texts.close_button(), lambda: (kill_app(), retry(w)), True),
                   ("Повторить", lambda: retry(w), False)])
        return
    # второй отказ подряд - главной становится кнопка «Закрыть»: человек не должен бесконечно жать «Повторить»
    again = bool(TRIES["n"])
    w.buttons([("Повторить", lambda: retry(w), not again), ("Закрыть", w.root.destroy, again)])


def retry(w):
    """«Повторить» начинает с чистого листа (владелец 17.10.2026: ставил с включёнными «тремя буквами», выключил
    их, нажал «Повторить» - не пошло). Сбрасываем память о пути в сеть: настройки прокси Windows читаются заново,
    прокси заново проверяется живым соединением, соединение открывается новое."""
    TRIES["n"] += 1
    _NET.reset()
    log(f"повтор по кнопке (попытка {TRIES['n'] + 1}) - маршрут выбираю заново")
    w.buttons([])
    threading.Thread(target=install, args=(w,), daemon=True).start()


def show_demo(w, state):
    if state == "progress":
        w.version(version_line(None, DEMO_NEW))
        w.say(dl_progress.sample("программу", 14, 26).text, 52)
    elif state == "wait":
        w.say(dl_progress.sample("программу", 14, 24, kind="retry").text, 52)
    elif state == "stall":
        w.say(dl_progress.sample("программу", 14, 24, kind="stall").text, 52)
    elif state == "done":
        done(w, None, DEMO_NEW)
    elif state == "update":
        w.version(version_line(DEMO_OLD, DEMO_NEW))
        w.say(dl_progress.sample("программу", 14, 26).text, 52)
    elif state == "first":
        w.version(version_line(None, DEMO_NEW))
        w.say(dl_progress.sample("программу", 14, 26).text, 52)
    elif state == "error2":
        TRIES["n"] = 1          # второй отказ подряд - другие слова
        fail(w, fail_texts.Fail(fail_texts.NET))
    elif state == "busy":
        EXE["name"] = "demo.exe"
        fail(w, fail_texts.Fail(fail_texts.BUSY, "программа всё ещё открыта"))
    elif state == "busyfile":
        # занятый файл: в окне стоят имя файла и программа, которая его держит (баг 17.10.2026 вечером)
        EXE["name"] = "demo.exe"
        fail(w, fail_texts.Fail(fail_texts.BUSY, "файл занят", path=os.path.join(DEST, "program.exe"),
                                holders=[(4312, "Проводник")]))
    elif state == "busywait":
        w.say(fail_texts.busy_wait(os.path.join(DEST, "program.exe"), [(4312, "Проводник")], 15), 90)
    elif state == "waitclose":
        w.say(fail_texts.waiting(TITLE), 88)
        w.buttons([(fail_texts.close_button(), lambda: None, True)])
    else:
        fail(w, fail_texts.Fail(fail_texts.NET))


RELAUNCHED = "--relaunched"      # себя уже перезапустили из %TEMP% (ниже - зачем)


def child_env():
    """Окружение для процесса, который мы запускаем (программа после установки, мы сами при перезапуске).

    Служебные переменные однофайловой сборки надо убрать: иначе новый процесс решает, что уже распакован, и
    берёт НАШУ временную папку, а мы, завершаясь, её удаляем. Живой опыт на Windows 17.10.2026: программа
    после этого разваливалась на вещах, с ней не связанных, вплоть до «нет сети» при живой сети."""
    env = dict(os.environ)
    for v in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL"):
        env.pop(v, None)
    return env


def relaunch_outside_dest():
    """Уйти из папки программы ВСЕМ процессом, а не только питоном внутри него.

    Однофайловая сборка - это ДВА процесса: загрузчик (родитель) и питон (потомок). `os.chdir`
    меняет рабочую папку только потомка, а папку программы держит и родитель - поэтому «быстрый путь»
    (переименовать папку целиком) падал даже после swap_dir.leave(), и спасала только замена по файлам
    (измерено на Windows 11 17.10.2026 и подтверждено независимой приёмкой). Рабочую папку нам отдаёт
    самообновление СТАРОЙ версии: её ярлык указывает на папку программы.

    Поэтому: увидели, что мы внутри папки программы - запускаем себя заново из %TEMP% и выходим. Новый
    процесс (вместе со своим родителем) папку программы уже не держит."""
    if RELAUNCHED in sys.argv:
        return False
    try:
        cur = os.path.abspath(os.getcwd())
    except OSError:
        return False
    d = os.path.abspath(DEST)
    if cur != d and not cur.startswith(d + os.sep):
        return False
    tmp = tempfile.gettempdir()
    # ВАЖНО (найдено живым опытом на Windows 17.10.2026): из окружения надо убрать служебные переменные
    # однофайловой сборки. Запуская себя заново, мы передаём их новому процессу, он решает, что уже распакован, и
    # работает с НАШЕЙ временной папкой - а мы, завершаясь, её удаляем. Дальше у него пропадает всё, вплоть
    # до проверки сертификатов: в журнале это выглядело как «нет связи с сервером», хотя сеть была в порядке.
    env = child_env()
    try:
        subprocess.Popen([sys.executable] + sys.argv[1:] + [RELAUNCHED], cwd=tmp, close_fds=True, env=env,
                         creationflags=0x00000008)      # DETACHED_PROCESS: родитель сразу уходит
    except OSError as e:
        log(f"перезапуститься из {tmp} не вышло ({e!r}) - продолжаю здесь, заменю файлы по одному")
        return False
    log(f"меня запустили из папки программы - перезапускаюсь из {tmp}, чтобы её не держать")
    return True


def main():
    demo = sys.argv[sys.argv.index("--demo") + 1] if "--demo" in sys.argv else None
    if not demo and relaunch_outside_dest():      # мы в папке программы - перезапустились из %TEMP%
        return
    # use_last_error=True: код последней ошибки берём у ctypes, а не из windll.kernel32.GetLastError -
    # тот может вернуть ложный ноль (его успевает затереть чужой вызов), и тогда ДВА установщика пойдут
    # менять папку программы одновременно (замечание приёмки 17.10.2026)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = ctypes.c_void_p
    k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    main.mutex = k.CreateMutexW(None, False, f"Local\\{APP}_installer_single")   # одна линия установки
    if ctypes.get_last_error() == 183 and not demo:
        if swap_dir.swap_in_progress(DEST):
            # другой установщик уже меняет файлы: убьём - останется ни старой папки, ни новой (приёмка
            # 17.10.2026). Лучше уступить: он доведёт дело до конца сам.
            log("другой установщик уже меняет файлы - не мешаю ему, закрываюсь")
            return
        log("уже запущен другой установщик - закрываю его, продолжаю этим")
        close_other_installers()
    w = Win()
    threading.Thread(target=install, args=(w, demo), daemon=True).start()
    w.root.mainloop()


if __name__ == "__main__":
    main()
