# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows через ctypes: свернуть/вернуть окна, клавиатура и мышь этого компьютера, горячая клавиша, автозапуск,
одна копия. На Linux (тесты) - безопасные заглушки.

Свернуть и вернуть (главная жалоба на аналоги - «окна не вернулись»): программа сама запоминает СПИСОК окон
(сверху вниз, какое было активным) и сама их сворачивает и возвращает, а не надеется на повторный Win+D.
Окно, которое не свернулось (программа «от администратора» или зависла), досворачивает проводник Windows
(команда панели задач «свернуть все»); возврат - ТОЛЬКО по своему списку, поимённо. «Отменить свернуть все»
проводника (416) не зовём: она разворачивает и те окна, которые пользователь свернул сам (баг 15.10.2026).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque

WIN = sys.platform == "win32"
WM_HOTKEY = 0x0312
SW_RESTORE, SW_MINIMIZE, SW_SHOWMINNOACTIVE = 9, 6, 7
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_NOACTIVATE = 0x80, 0x40000, 0x08000000
WS_MINIMIZE, WS_VISIBLE = 0x20000000, 0x10000000
GW_OWNER = 4
SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
                "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow", "TopLevelWindowForOverflowXamlIsland",
                "Shell_InputSwitchTopLevelWindow", "ApplicationManager_ImmersiveShellWindow", "EdgeUiInputTopWndClass",
                "ForegroundStaging", "MultitaskingViewFrame", "Windows.Internal.Shell.TabProxyWindow",
                "Shell_LightDismissOverlay", "tooltips_class32", "#32768", "IME", "MSCTFIME UI"}

if WIN:
    import ctypes
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
    except OSError:
        dwmapi = None
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetWindow.restype = wt.HWND
    user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsIconic.argtypes = [wt.HWND]
    user32.IsWindow.argtypes = [wt.HWND]
    user32.ShowWindowAsync.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetForegroundWindow.restype = wt.HWND
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.FindWindowW.restype = wt.HWND
    user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
    user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
    user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
    user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wt.DWORD, ctypes.c_size_t]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wt.UINT]

    class WINDOWPLACEMENT(ctypes.Structure):
        """Полное положение окна: развёрнуто/обычное и прямоугольник «нормального» положения."""
        _fields_ = [("length", wt.UINT), ("flags", wt.UINT), ("showCmd", wt.UINT),
                    ("ptMinPosition", wt.POINT), ("ptMaxPosition", wt.POINT),
                    ("rcNormalPosition", wt.RECT)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

    user32.GetWindowPlacement.argtypes = [wt.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
    user32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.EnumDisplayMonitors.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), ctypes.c_void_p, wt.LPARAM]

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.GetCurrentProcess.restype = wt.HANDLE
    advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
                                             ctypes.POINTER(wt.DWORD)]
    advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wt.DWORD)
    advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wt.DWORD]
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    shell32.ShellExecuteW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_int]


def _cls(h):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, b, 256)
    return b.value


def _title(h):
    n = user32.GetWindowTextLengthW(h)
    b = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, b, n + 1)
    return b.value


def _pid(h):
    p = wt.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(p))
    return p.value


def _cloaked(h):
    if dwmapi is None:
        return False
    v = ctypes.c_int(0)
    try:
        if dwmapi.DwmGetWindowAttribute(h, 14, ctypes.byref(v), ctypes.sizeof(v)) == 0:
            return v.value != 0
    except Exception:  # noqa: BLE001
        pass
    return False


def is_task_window(h, own_pid=None):
    """Окно программы с кнопкой на панели задач - свёрнутое или нет (служебные и свои окна не считаются)."""
    if not user32.IsWindowVisible(h):
        return False
    ex = user32.GetWindowLongW(h, GWL_EXSTYLE)
    if ex & WS_EX_TOOLWINDOW:
        return False
    if user32.GetWindow(h, GW_OWNER) and not ex & WS_EX_APPWINDOW:
        return False
    if (own_pid or os.getpid()) == _pid(h):
        return False
    if _cls(h) in SKIP_CLASSES or not _title(h).strip():
        return False
    return not _cloaked(h)


def is_app_window(h, own_pid=None):
    """Обычное окно программы на экране (как кнопка на панели задач): видно, НЕ свёрнуто, не служебное."""
    return not user32.IsIconic(h) and is_task_window(h, own_pid)


def _enum(pred):
    """Окна сверху вниз (по z-порядку), для которых pred(hwnd, свой pid) - правда."""
    if not WIN:
        return []
    out = []
    own = os.getpid()

    def cb(h, _):
        try:
            if pred(h, own):
                out.append(int(h))
        except Exception:  # noqa: BLE001
            pass
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def app_windows():
    """Окна программ сверху вниз (по z-порядку)."""
    return _enum(is_app_window)


def minimized_windows():
    """Окна программ, которые УЖЕ свёрнуты (их свернул сам пользователь - мы их не трогаем и не возвращаем)."""
    return _enum(lambda h, own: bool(user32.IsIconic(h)) and is_task_window(h, own))


def foreground():
    return int(user32.GetForegroundWindow() or 0) if WIN else 0


def window_alive(h):
    return bool(WIN and user32.IsWindow(wt.HWND(h)))


def is_minimized(h):
    return bool(WIN and user32.IsIconic(wt.HWND(h)))


def is_shown(h):
    """Окно видно и не свёрнуто."""
    return bool(WIN and user32.IsWindowVisible(wt.HWND(h)) and not user32.IsIconic(wt.HWND(h)))


def minimize(h):
    if WIN:
        user32.ShowWindowAsync(wt.HWND(h), SW_MINIMIZE)


def restore(h):
    if WIN:
        user32.ShowWindowAsync(wt.HWND(h), SW_RESTORE)


def maximize(h):
    """Развернуть окно на весь экран (нужно проверке --maximize: так на экране появляется развёрнутое окно)."""
    if WIN:
        user32.ShowWindowAsync(wt.HWND(h), 3)


HWND_TOP = 0
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
SWP_NOSENDCHANGING, SWP_ASYNCWINDOWPOS = 0x400, 0x4000
# БЕЗ SWP_ASYNCWINDOWPOS: с ним каждая команда уходит в очередь СВОЕГО окна, разные окна - разные потоки, и
# порядок выполнения разъезжается (проверено под Wine настоящими «Блокнотами»: из [A,B,C,D] выходило [A,B,D,C]).
# Без него порядок наложения меняется сразу, в нашем порядке вызовов. SWP_NOSENDCHANGING - чтобы не ждать
# ответа зависшего окна.
SWP_ORDER = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOSENDCHANGING


def set_order(hwnds):
    """Выставить порядок наложения окон явно - снизу вверх, как было до сворачивания.

    Требование владельца 16.10.2026 («свернулись 1,2,3,4,5 - восстанавливаются 5,4,3,2,1, и мы видим всё
    обратно»): одной очерёдности вызовов ShowWindowAsync мало - Windows выполняет их асинхронно, и при многих
    окнах фактический порядок разъезжается. Поэтому каждое окно поднимаем наверх по очереди, начиная с самого
    нижнего: последним наверх встанет то окно, которое и было сверху. Окно не двигаем, не меняем размер и не
    делаем активным (SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE), команда асинхронная - зависшее окно не держит
    программу. -> сколько окон расставили."""
    if not WIN:
        return 0
    n = 0
    for h in reversed(list(hwnds or ())):          # снизу вверх
        try:
            if user32.SetWindowPos(wt.HWND(h), wt.HWND(HWND_TOP), 0, 0, 0, 0, SWP_ORDER):
                n += 1
        except Exception:  # noqa: BLE001
            pass
    return n


# ---------------------------------------------------------------- где и какого размера было окно
# Владелец 17.10.2026: «Может Щелчок возвращать окна в те же места и с теми же размерами? На данный момент
# такого нет». Раньше мы звали SW_RESTORE и полагались на память Windows - а она возвращает развёрнутое на весь
# экран окно в ОБЫЧНЫЙ размер. Теперь перед сворачиванием запоминаем GetWindowPlacement (развёрнуто/обычное и
# прямоугольник «нормального» положения), а при возврате ставим это обратно.
#
# Команды - только асинхронные (ShowWindowAsync, SetWindowPos с SWP_ASYNCWINDOWPOS): зависшее чужое окно не
# должно держать нашу программу. Поэтому вместо SetWindowPlacement (он синхронный и ждёт ответа окна) -
# «развернуть» или «вернуть + поставить прямоугольник».
SW_SHOWMAXIMIZED = 3
SWP_NOZORDER = 0x4
SWP_PLACE = SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOSENDCHANGING | SWP_ASYNCWINDOWPOS


def get_placement(h):
    """Где и в каком виде окно: {"show": 1 обычное / 3 развёрнутое, "rect": (слева, сверху, справа, снизу)}.

    rect - «нормальное» положение окна (куда оно вернётся из развёрнутого), в координатах рабочего стола.
    Окно не отвечает - вернётся None, и мы просто развернём его как раньше."""
    if not WIN:
        return None
    try:
        wp = WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(WINDOWPLACEMENT)
        if not user32.GetWindowPlacement(wt.HWND(h), ctypes.byref(wp)):
            return None
        r = wp.rcNormalPosition
        return placement_from(int(wp.showCmd), (int(r.left), int(r.top), int(r.right), int(r.bottom)))
    except Exception:  # noqa: BLE001
        return None


def placement_from(show, rect):
    """Что запоминать по сырым данным GetWindowPlacement (чистая функция - её проверяют тесты и на Linux).

    Окно уже свёрнуто - None: «нормального» прямоугольника у него сейчас может не быть (под Wine там лежат
    координаты значка на панели задач, -32000, опыт 17.10.2026), и запоминать нечего - такое окно вернётся
    обычной командой «развернуть», как раньше. Слишком маленький прямоугольник - тоже None."""
    if show in (2, SW_SHOWMINNOACTIVE) or not rect:
        return None
    if rect[2] - rect[0] < 100 or rect[3] - rect[1] < 60:
        return None
    return {"show": SW_SHOWMAXIMIZED if show == SW_SHOWMAXIMIZED else SW_SHOWNORMAL, "rect": tuple(rect)}


def monitors():
    """Рабочие области всех мониторов [(слева, сверху, справа, снизу)] - без панели задач. Первым - основной."""
    if not WIN:
        return []
    out = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HANDLE, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)

    def cb(hmon, hdc, lprc, lparam):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcWork
            item = (int(r.left), int(r.top), int(r.right), int(r.bottom))
            out.insert(0, item) if mi.dwFlags & 1 else out.append(item)      # MONITORINFOF_PRIMARY
        return True
    try:
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    except Exception:  # noqa: BLE001
        return []
    return out


def fit_rect(rect, mons):
    """Прямоугольник окна -> видимый прямоугольник. Чистая функция (её проверяют тесты и на Linux).

    Монитор отключили или поменялось разрешение - окно не должно уехать за край экрана: если прямоугольник не
    пересекается ни с одной рабочей областью, переносим его в ближайшую (по центру окна), сохраняя размер;
    окно больше экрана - ужимаем. Пересекается хотя бы на 40 точек - оставляем как есть (человек мог нарочно
    сдвинуть окно за край)."""
    if not rect or not mons:
        return rect
    l, t, r, b = rect
    w, hgt = max(1, r - l), max(1, b - t)
    EDGE = 40
    for ml, mt, mr, mb in mons:
        if min(r, mr) - max(l, ml) >= min(EDGE, w) and min(b, mb) - max(t, mt) >= min(EDGE, hgt):
            return rect
    cx, cy = l + w // 2, t + hgt // 2
    def dist(m):
        ml, mt, mr, mb = m
        dx = max(ml - cx, 0, cx - mr)
        dy = max(mt - cy, 0, cy - mb)
        return dx * dx + dy * dy
    ml, mt, mr, mb = min(mons, key=dist)
    w, hgt = min(w, mr - ml), min(hgt, mb - mt)
    nl = min(max(l, ml), mr - w)
    nt = min(max(t, mt), mb - hgt)
    return (nl, nt, nl + w, nt + hgt)


def set_placement(h, pl, mons=None):
    """Вернуть окно туда же и таким же: развёрнутое - развёрнутым, обычное - с теми же координатами и размером.

    -> True, если команду отправили. pl=None - ничего не делаем (окно вернёт обычный restore)."""
    if not WIN or not pl:
        return False
    try:
        if pl.get("show") == SW_SHOWMAXIMIZED:
            user32.ShowWindowAsync(wt.HWND(h), SW_SHOWMAXIMIZED)
            return True
        rect = fit_rect(pl.get("rect"), monitors() if mons is None else mons)
        if not rect:
            return False
        l, t, r, b = rect
        # ВАЖНО: не зовём здесь ShowWindowAsync - окно уже развернули раньше, а повторная команда делает окно
        # активным и поднимает его наверх, ломая порядок наложения (проверено под Wine: из [A,B,C,D,E]
        # выходило [E,A,B,C,D]). Ставим только место и размер, порядок не трогаем (SWP_NOZORDER).
        user32.SetWindowPos(wt.HWND(h), wt.HWND(0), int(l), int(t), int(r - l), int(b - t), SWP_PLACE)
        return True
    except Exception:  # noqa: BLE001
        return False


def shell_minimize_all(undo=False):
    """Команда панели задач: «свернуть все окна» (419) / «отменить» (416) - так же, как делает проводник."""
    if not WIN:
        return False
    tray = user32.FindWindowW("Shell_TrayWnd", None)
    if not tray:
        return False
    return bool(user32.PostMessageW(tray, 0x0111, 416 if undo else 419, 0))


def bring_to_front(h):
    """Вернуть фокус окну, которое было активным. Windows не даёт фоновой программе забирать фокус - обходим
    короткой «пустой» Alt (так делают и другие программы-переключатели)."""
    if not WIN or not h:
        return False
    hw = wt.HWND(h)
    if user32.SetForegroundWindow(hw):
        return True
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    return bool(user32.SetForegroundWindow(hw))


# ---------------------------------------------------------------- окна «от имени администратора»
# Windows не даёт обычной программе управлять окнами программ с повышенными правами (разделение уровней
# целостности, UIPI): ShowWindow/ShowWindowAsync и SetForegroundWindow для такого окна НИЧЕГО не делают и об
# ошибке не сообщают - функция возвращает «успех». Поэтому такие окна надо узнавать ЗАРАНЕЕ и говорить о них
# человеку, а не делать вид, что окно свернули (жалоба владельца 16.10.2026: «командную строку не поднимает»).
# Узнаём по уровню целостности процесса окна: его токен старше нашего - значит, оно нам не подчинится. Если
# токен вообще не даёт себя открыть (отказ в доступе) - это тот же случай: права выше наших.
ERR_ACCESS_DENIED = 5
TOKEN_QUERY = 0x0008
TOKEN_INTEGRITY_LEVEL, TOKEN_ELEVATION = 25, 20
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ABOVE_US = "выше наших прав"
OURS, ADMIN, UNKNOWN = "ours", "admin", "unknown"


def process_level(pid):
    """Уровень целостности процесса. -> (число или None, почему None).

    Число: 0x1000 - низкий, 0x2000 - обычный, 0x3000 - «от имени администратора», 0x4000 - система."""
    if not WIN:
        return None, "не Windows"
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return None, (ABOVE_US if ctypes.get_last_error() == ERR_ACCESS_DENIED else "процесса нет")
    try:
        tok = wt.HANDLE()
        if not advapi32.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return None, (ABOVE_US if ctypes.get_last_error() == ERR_ACCESS_DENIED else "права не читаются")
        try:
            need = wt.DWORD(0)
            advapi32.GetTokenInformation(tok, TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(need))
            if not need.value:
                return None, "права не читаются"
            buf = ctypes.create_string_buffer(need.value)
            if not advapi32.GetTokenInformation(tok, TOKEN_INTEGRITY_LEVEL, buf, need, ctypes.byref(need)):
                return None, (ABOVE_US if ctypes.get_last_error() == ERR_ACCESS_DENIED else "права не читаются")
            sid = ctypes.c_void_p.from_buffer(buf).value     # TOKEN_MANDATORY_LABEL.Label.Sid
            cnt = advapi32.GetSidSubAuthorityCount(sid)
            n = int(cnt[0]) if cnt else 0
            if not n:
                return None, "права не читаются"
            return int(advapi32.GetSidSubAuthority(sid, n - 1)[0]), ""
        finally:
            kernel32.CloseHandle(tok)
    finally:
        kernel32.CloseHandle(h)


_own = []


def own_level():
    """Наш собственный уровень целостности (кэш: он не меняется, пока программа работает)."""
    if not _own:
        _own.append(process_level(os.getpid())[0] or 0)
    return _own[0]


_rights_cache = {}
RIGHTS_TTL = 20.0


def window_rights(h):
    """Можем ли мы управлять этим окном. -> "ours" | "admin" (права выше наших) | "unknown".

    Ответ помним по процессу на RIGHTS_TTL секунд: при 20 открытых окнах это 20 обращений к Windows на каждый
    щелчок, а щёлкать владелец будет подряд - сворачивание должно оставаться мгновенным."""
    if not WIN:
        return OURS
    try:
        pid = _pid(wt.HWND(h))
        if not pid:
            return UNKNOWN
        now = time.monotonic()
        hit = _rights_cache.get(pid)
        if hit is not None and now - hit[1] < RIGHTS_TTL:
            return hit[0]
        lvl, why = process_level(pid)
        if lvl is None:
            out = ADMIN if why == ABOVE_US else UNKNOWN
        else:
            out = ADMIN if lvl > own_level() else OURS
        if len(_rights_cache) > 200:
            _rights_cache.clear()
        _rights_cache[pid] = (out, now)
        return out
    except Exception:  # noqa: BLE001 - узнать права не вышло; считаем, что окно обычное
        return UNKNOWN


def window_title(h):
    """Заголовок окна - для понятной строки в журнале («окно «Командная строка» …»)."""
    if not WIN:
        return ""
    try:
        return _title(wt.HWND(h))
    except Exception:  # noqa: BLE001
        return ""


_elev = []


def is_elevated():
    """Сама программа запущена с правами администратора? (ответ не меняется, пока программа работает)."""
    if not WIN:
        return False
    if _elev:
        return _elev[0]
    _elev.append(_is_elevated_now())
    return _elev[0]


def _is_elevated_now():
    try:
        tok = wt.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(tok)):
            return False
        try:
            val, need = wt.DWORD(0), wt.DWORD(0)
            if not advapi32.GetTokenInformation(tok, TOKEN_ELEVATION, ctypes.byref(val), ctypes.sizeof(val),
                                                ctypes.byref(need)):
                return False
            return bool(val.value)
        finally:
            kernel32.CloseHandle(tok)
    except Exception:  # noqa: BLE001
        return False


SW_HIDE, SW_SHOWNORMAL = 0, 1


def run_as_admin(exe, args="", show=SW_SHOWNORMAL):
    """Запустить программу с правами администратора (Windows один раз спросит подтверждение).
    -> True - запустили; False - человек отказался или не вышло."""
    if not WIN:
        return False
    try:
        rc = shell32.ShellExecuteW(None, "runas", exe, args or None, None, show)
        return int(rc or 0) > 32
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- запуск с правами администратора при входе
# Ярлык «запускать от имени администратора» не годится для автозапуска: Windows каждый раз спрашивала бы
# подтверждение, а при входе в систему - просто не запустила бы. Поэтому задание планировщика «при входе в
# систему» с наивысшими правами: подтверждение спрашивается ОДИН раз, когда задание создаётся.
TASK_NAME = "Щелчок - запуск с правами администратора"
NO_WINDOW = 0x08000000


def _user_id():
    dom = os.environ.get("USERDOMAIN") or os.environ.get("COMPUTERNAME") or ""
    user = os.environ.get("USERNAME") or ""
    return f"{dom}\\{user}" if dom and user else user


def task_xml(exe, args="--autostart", user=None):
    """Задание планировщика: при входе в систему, с наивысшими правами, без ограничения по времени."""
    user = _user_id() if user is None else user
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")   # noqa: E731
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        f"  <RegistrationInfo><Description>Программа «Щелчок» - запуск с правами администратора, чтобы сворачивать "
        f"и возвращать окна, открытые от имени администратора.</Description></RegistrationInfo>\n"
        f"  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{esc(user)}</UserId></LogonTrigger></Triggers>\n"
        f'  <Principals><Principal id="Author"><UserId>{esc(user)}</UserId>'
        "<LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal></Principals>\n"
        "  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
        "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>"
        "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate>"
        "<StartWhenAvailable>false</StartWhenAvailable>"
        "<RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>"
        "<IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>"
        "<AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden>"
        "<RunOnlyIfIdle>false</RunOnlyIfIdle><ExecutionTimeLimit>PT0S</ExecutionTimeLimit>"
        "<Priority>7</Priority></Settings>\n"
        f'  <Actions Context="Author"><Exec><Command>{esc(exe)}</Command>'
        f"<Arguments>{esc(args)}</Arguments></Exec></Actions>\n"
        "</Task>\n")


def _schtasks(args):
    """schtasks без мелькающего чёрного окна. -> (код возврата, вывод)."""
    import subprocess
    try:
        p = subprocess.run(["schtasks.exe"] + args, capture_output=True, creationflags=NO_WINDOW,  # noqa: S603
                           timeout=20)
        return p.returncode, (p.stdout or b"").decode("cp866", "replace") + (p.stderr or b"").decode("cp866",
                                                                                                     "replace")
    except Exception as e:  # noqa: BLE001
        return -1, repr(e)


def admin_task_exists(name=TASK_NAME):
    """Задание «запускать с правами администратора» создано? (проверка не требует прав).

    ВНИМАНИЕ: это запуск schtasks.exe - по таймеру окна (30 мс) его звать нельзя, только по делу."""
    if not WIN:
        return False
    return _schtasks(["/Query", "/TN", name])[0] == 0


def admin_task_create(exe=None, name=TASK_NAME, args="--autostart"):
    """Создать задание - через запрос прав у Windows (подтверждение спрашивается один раз).
    -> True - запрос прав отправлен (создалось ли, проверяем потом `admin_task_exists`)."""
    if not WIN:
        return False
    exe = exe or sys.executable
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "shchelchok-task.xml")
    try:
        with open(path, "w", encoding="utf-16") as f:
            f.write(task_xml(exe, args))
    except OSError:
        return False
    return run_as_admin("schtasks.exe", f'/Create /F /TN "{name}" /XML "{path}"', show=SW_HIDE)


def admin_task_run(name=TASK_NAME):
    """Запустить задание сейчас - программа стартует с наивысшими правами и БЕЗ нового вопроса Windows
    (подтверждение спрашивалось один раз, когда задание создавали). -> True, если задание запущено."""
    if not WIN or not admin_task_exists(name):
        return False
    rc, out = _schtasks(["/Run", "/TN", name])
    return rc == 0


def admin_task_delete(name=TASK_NAME):
    """Убрать задание (тоже через запрос прав - задание создавалось с правами администратора)."""
    if not WIN:
        return False
    if _schtasks(["/Delete", "/TN", name, "/F"])[0] == 0:
        return True
    return run_as_admin("schtasks.exe", f'/Delete /F /TN "{name}"', show=SW_HIDE)


# ---------------------------------------------------------------- клавиатура и мышь этого компьютера
MOUSE_VK = (0x01, 0x02, 0x04, 0x05, 0x06)      # левая, правая, средняя, боковые кнопки мыши


class InputWatch:
    """Поток: моменты нажатий клавиш и щелчков мыши (без записи - только время и что это было: клавиша или мышь).
    GetLastInputInfo меняется и от движения мыши - движение отличаем по сдвигу курсора и не считаем (щёлкнуть
    пальцами, держа мышь, можно). Кнопку мыши узнаём через GetAsyncKeyState - чтобы в журнале было честно
    написано, печатали в этот момент или щёлкнули мышью."""

    def __init__(self):
        self.times = deque(maxlen=400)         # [(время, "key" | "mouse")]
        self._stop = threading.Event()
        self._th = None

    def start(self):
        if not WIN or self._th is not None:
            return
        self._th = threading.Thread(target=self._run, name="input-watch", daemon=True)
        self._th.start()

    def stop(self):
        self._stop.set()

    @staticmethod
    def _mouse_down():
        try:
            return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in MOUSE_VK)
        except Exception:  # noqa: BLE001
            return False

    def _run(self):
        li = LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(li)
        pt = wt.POINT()
        last_tick, last_pt = None, None
        while not self._stop.is_set():
            try:
                user32.GetLastInputInfo(ctypes.byref(li))
                user32.GetCursorPos(ctypes.byref(pt))
                cur = (pt.x, pt.y)
                if last_tick is not None and li.dwTime != last_tick and cur == last_pt:
                    self.times.append((time.monotonic(), "mouse" if self._mouse_down() else "key"))
                last_tick, last_pt = li.dwTime, cur
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(0.008)

    def near_kind(self, t, before=0.3, after=0.2):
        """Что было на этом компьютере около времени t: "key", "mouse" или None."""
        for x, kind in list(self.times):
            if t - before <= x <= t + after:
                return kind
        return None

    def near(self, t, before=0.3, after=0.2):
        return self.near_kind(t, before, after) is not None


# ---------------------------------------------------------------- горячая клавиша, автозапуск, одна копия
def register_hotkey(hwnd, hid, mods, vk):
    """True - клавиша наша; False - занята другой программой (или Windows)."""
    if not WIN:
        return True
    return bool(user32.RegisterHotKey(wt.HWND(int(hwnd)), hid, mods | 0x4000, vk))


def unregister_hotkey(hwnd, hid):
    if WIN:
        user32.UnregisterHotKey(wt.HWND(int(hwnd)), hid)


def parse_msg(message):
    if not WIN:
        return (0, 0)
    msg = wt.MSG.from_address(int(message))
    return (msg.message, msg.wParam)


def hide_from_capture(hwnd):
    """Окна «Щелчка» в записи экрана видны (прятать нечего) - функция для общего кода окон линейки."""
    return "n/a"


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_get(name):
    if not WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, name)
            return True
    except OSError:
        return False


def autostart_set(name, on, exe=None):
    """Автозапуск с Windows (по желанию): HKCU\\...\\Run, программа стартует в трей."""
    if not WIN:
        return False
    import winreg
    exe = exe or sys.executable
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            if on:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, f'"{exe}" --autostart')
            else:
                try:
                    winreg.DeleteValue(k, name)
                except OSError:
                    pass
        return True
    except OSError:
        return False


_mutex = []
_mutex_err = []


def release_mutex():
    """Отпустить мьютекс одной копии (перед тем как запустить себя же с правами администратора: иначе новая
    копия решит, что программа уже открыта, и тихо выйдет)."""
    if not WIN:
        return False
    ok = False
    while _mutex:
        h = _mutex.pop()
        try:
            kernel32.CloseHandle(wt.HANDLE(h))
            ok = True
        except Exception:  # noqa: BLE001
            pass
    _mutex_err.clear()
    return ok


def first_instance(name):
    """Именованный мьютекс сеанса: False - программа уже открыта.

    Отказ в доступе (5) - это тоже «уже открыта»: первая копия работает с правами администратора, и её мьютекс
    обычной программе не открыть. Без этого после включения «Запускать с правами администратора» ярлык запускал
    ВТОРУЮ копию (чек-лист п. 1)."""
    if not WIN:
        return True
    kernel32.CreateMutexW.restype = wt.HANDLE
    h = kernel32.CreateMutexW(None, False, f"Local\\{name}_single")
    err = ctypes.get_last_error()
    _mutex.append(h)
    _mutex_err.append(err)
    return mutex_result(err)


def mutex_result(err):
    """Код от CreateMutexW -> мы первая копия? 183 - мьютекс уже есть; 5 (отказ в доступе) - он есть, но
    создан копией с правами администратора."""
    return int(err) not in (183, ERR_ACCESS_DENIED)


def other_copy_elevated():
    """Вторая копия: первая работает с правами администратора (поэтому ни мьютекс, ни окно ей не отдать)."""
    return bool(_mutex_err) and _mutex_err[-1] == ERR_ACCESS_DENIED
