# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Замена папки программы новой версией - так, чтобы занятый файл не ломал обновление. ОДИН модуль на линейку.

Баг 17.10.2026 («Маркер на экране» 1.0.7 -> 1.0.9, журнал владельца `%TEMP%\\marker-na-ekrane-install.log`):
обновление не доходило до конца НИ из настроек программы, НИ установщиком вручную. Все 15 попыток замены
падали подряд с `PermissionError(13, 'Процесс не может получить доступ к файлу, так как этот файл занят другим
процессом')`, при этом процессов программы на компьютере НЕ БЫЛО ни одного, новая версия была уже скачана и
распакована рядом (папка «… .new», 60 МБ), а в папке программы оставалась старая версия.

ЧТО ИЗМЕРЕНО НА НАСТОЯЩЕЙ WINDOWS 11 (стенд STAND-WIN, 17.10.2026, `_brand/tools/lab_swap.ps1`):

| Кто держит | Переименовать ПАПКУ | Перенести ФАЙЛ внутри | RestartManager |
|---|---|---|---|
| процесс, у которого рабочая папка = папка программы | НЕЛЬЗЯ, winerror 32 «файл занят другим процессом» | можно | про папку молчит (rc=5) |
| процесс, который держит открытым файл внутри | НЕЛЬЗЯ, winerror 5 «отказано в доступе» | сам файл - нельзя (32), соседние - можно | НАЗЫВАЕТ процесс (pid + имя) |
| открытый handle на саму папку (проводник, поиск) | можно | можно | про папку молчит (rc=5) |

Отсюда причина бага владельца: папку программы держал САМ УСТАНОВЩИК. Программа запускается ярлыком, у
которого рабочая папка - папка программы; самообновление запускало установщик из себя, и он наследовал эту
рабочую папку. Дальше установщик сам себе не давал переименовать папку - бесконечно, сколько бы попыток ни
делал. Ошибка в журнале совпадает с измерением (winerror 32 на переименовании папки) побайтово.

Отсюда и лечение, в этом порядке:
1. `leave()` - уйти из папки программы (и установщик, запущенный программой, передаёт рабочую папку %TEMP%);
2. быстрый путь - папку целиком отставить в сторону («… .old-<время>») и поставить новую на её место;
3. не дали (кто-то держит саму папку) - медленный путь: перенести файлы ПО ОДНОМУ (измерение показывает, что
   это работает даже тогда, когда папку переименовать нельзя). Папка программы при этом остаётся той же -
   ярлыки, запись об удалении и путь установки не меняются;
4. файл занят, но в новой версии он РОВНО ТАКОЙ ЖЕ (sha256) - оставляем как есть, заменять нечего;
5. занят файл, который и правда меняется - откат к старой версии (программа остаётся рабочей!), и человеку
   говорим КТО держит файл: `RestartManager` называет процесс по имени и номеру;
6. паузы между попытками 1, 2, 4, 8, 15, 30, 30, 30 с - всего около двух минут: антивирус, который проверяет
   только что распакованные 60 МБ, за 20 с (15 попыток по секунде, как было) отпустить файл не успевает;
7. за собой убираем: «… .new» и «… .old-*» не остаются на диске (у владельца осталось 60 МБ мусора);
8. всё, что переносим, идёт через ЖУРНАЛ ЗАМЕНЫ (строка пишется ДО переноса, со сбросом на диск): убили
   установщик посреди дела - следующий запуск доиграет замену и вернёт программу к рабочей версии. Пока в
   журнале есть невозвращённое, уборка не трогает «… .old-…». Проверено живьём на Windows 11
   (`_brand/tools/lab_journal_win.py`): прежний код оставлял смесь версий и терял файлы.

Переименование «на следующую перезагрузку» (`MoveFileEx` + `MOVEFILE_DELAY_UNTIL_REBOOT`) оставлено ТОЛЬКО
для уборки старой папки, которую не дали удалить, - и то лишь попыткой: без прав администратора Windows его
не делает, а установка у нас идёт в папку пользователя. Для самой замены он не годится: половина новых файлов
и половина старых - это сломанная программа, лучше честный отказ и «закройте то, что держит файл».

Только стандартная библиотека, Python 3.8+ (идёт в установщики PyInstaller).
КОПИЯ ~/office_tools/_brand/swap_dir.py - не править копии, раздаёт python3 _brand/sync.py.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import tempfile
import time

import fail_texts

# Паузы между попытками замены, с. 17.10.2026 было 15 попыток по 1 с - антивирус за 20 с не успевает.
PAUSES = (1, 2, 4, 8, 15, 30, 30, 30)
# Сколько раз ждём при «нет прав». Ждать вообще - потому что защита папок антивируса отвечает именно отказом
# в доступе и отпускает файл через несколько секунд. Ждать КОРОТКО (1 + 2 + 4 с) - потому что настоящая
# нехватка прав за две минуты не изменится, а человек всё это время читает «пробую снова» (долг 17.10.2026).
RIGHTS_TRIES = 3
NEW_SUFFIX = ".new"
OLD_PREFIX = ".old-"
MAX_ASK = 24          # у скольких файлов максимум спрашиваем держателя (RestartManager не бесплатный)


# ------------------------------------------------------------------ мелочи
def _noop(*_a, **_kw):
    pass


def new_path(dest):
    """Куда распаковывать новую версию."""
    return dest + NEW_SUFFIX


def _old_path(dest):
    return f"{dest}{OLD_PREFIX}{time.strftime('%Y%m%d-%H%M%S')}"


def _files(root, log=_noop):
    """Все файлы внутри папки: (полный путь, путь относительно папки).

    onerror обязателен: без него os.walk МОЛЧА пропускает недоступное поддерево, и замена окажется неполной,
    а мы об этом не узнаем (наш баг-класс «плоский обход прячет содержимое», нашла приёмка 17.10.2026)."""
    def boom(e):
        log(f"не смог прочитать {getattr(e, 'filename', '?')}: {e!r}")
        raise e

    for base, _dirs, names in os.walk(root, onerror=boom):
        for name in names:
            p = os.path.join(base, name)
            yield p, os.path.relpath(p, root)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _same(a, b):
    """Один и тот же файл по содержимому? (занятый файл можно читать, даже если нельзя переносить.)"""
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        return _sha(a) == _sha(b)
    except OSError:
        return False


# os.rename / os.replace одной точкой: на том же диске это переименование (мгновенно, без копирования).
# Отдельные обёртки нужны и проверкам: они подменяют их и получают ровно ошибку Windows «файл занят».
def _rename(src, dst):
    os.rename(src, dst)


def _replace(src, dst):
    os.replace(src, dst)


def _move(src, dst):
    """Перенести файл в папку, которой может ещё не быть (а на его месте мог быть каталог)."""
    parent = os.path.dirname(dst)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    if os.path.isdir(dst):
        # в старой версии тут был КАТАЛОГ, а в новой файл: os.replace так не умеет и дал бы «занято»
        shutil.rmtree(dst, ignore_errors=True)
    _replace(src, dst)


def _err(e):
    win = getattr(e, "winerror", None)
    return f"{type(e).__name__} winerror={win}: {e}" if win else repr(e)


# ------------------------------------------------------------------ уйти из папки программы
def leave(dest, log=_noop):
    """Уйти из папки программы: пока она наша рабочая папка, Windows не даёт её переименовать.

    Ровно это и было причиной бага 17.10.2026: установщик запускался из программы и наследовал её рабочую
    папку (ярлык программы указывает на папку программы)."""
    try:
        cur = os.path.abspath(os.getcwd())
    except OSError:
        return False
    d = os.path.abspath(dest)
    if cur != d and not cur.startswith(d + os.sep):
        return False
    tmp = tempfile.gettempdir()
    try:
        os.chdir(tmp)
    except OSError as e:
        log(f"не смог уйти из папки программы: {_err(e)}")
        return False
    log(f"моя рабочая папка была папкой программы - ушёл в {tmp} (иначе Windows не даёт заменить файлы)")
    return True


# ------------------------------------------------------------------ кто держит файл (RestartManager)
class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


class _RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [("dwProcessId", ctypes.c_uint32), ("ProcessStartTime", _FILETIME)]


class _RM_PROCESS_INFO(ctypes.Structure):
    _fields_ = [("Process", _RM_UNIQUE_PROCESS),
                ("strAppName", ctypes.c_wchar * 256),
                ("strServiceShortName", ctypes.c_wchar * 64),
                ("ApplicationType", ctypes.c_uint32),
                ("AppStatus", ctypes.c_uint32),
                ("TSSessionId", ctypes.c_uint32),
                ("bRestartable", ctypes.c_int)]


_RM_MORE_DATA = 234


def _rm_lib():
    """rstrtmgr.dll с ЗАДАННЫМИ типами аргументов: без них ctypes угадывает ширину сам, и на 64-битной
    Windows неверно переданный указатель даёт не код ошибки, а падение процесса."""
    rm = ctypes.WinDLL("rstrtmgr.dll")
    u32, pu32 = ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)
    rm.RmStartSession.argtypes = [pu32, u32, ctypes.POINTER(ctypes.c_wchar)]
    rm.RmStartSession.restype = ctypes.c_int
    rm.RmRegisterResources.argtypes = [u32, u32, ctypes.POINTER(ctypes.c_wchar_p), u32, ctypes.c_void_p,
                                       u32, ctypes.c_void_p]
    rm.RmRegisterResources.restype = ctypes.c_int
    rm.RmGetList.argtypes = [u32, pu32, pu32, ctypes.POINTER(_RM_PROCESS_INFO), pu32]
    rm.RmGetList.restype = ctypes.c_int
    rm.RmEndSession.argtypes = [u32]
    rm.RmEndSession.restype = ctypes.c_int
    return rm


def holders(paths, log=_noop):
    """Кто держит эти файлы: [(номер процесса, «Имя программы»), …]. Не Windows / не вышло - пустой список.

    Штатный способ Windows - служба перезапуска приложений (RestartManager): она и говорит установщикам, что
    закрыть. На ПАПКУ отвечает отказом (rc=5, измерено), поэтому спрашиваем про ФАЙЛЫ.

    ЭТА ФУНКЦИЯ НЕ ИМЕЕТ ПРАВА УПАСТЬ, что бы ни случилось: её зовут В ОБРАБОТЧИКЕ ошибки «файл занят», и
    падение здесь означало бы аварийное закрытие установщика вместо понятного окна - хуже исходного бага.
    Поэтому всё тело в try/except: любая беда превращается в строку журнала и пустой список."""
    if isinstance(paths, str):
        paths = [paths]
    paths = [p for p in paths if p][:MAX_ASK]
    if os.name != "nt" or not paths:
        return []
    session = None
    rm = None
    try:
        rm = _rm_lib()
        session = ctypes.c_uint32(0)
        key = ctypes.create_unicode_buffer(33)              # CCH_RM_SESSION_KEY + 1
        rc = rm.RmStartSession(ctypes.byref(session), 0, key)
        if rc != 0:
            log(f"кто держит файл: RmStartSession rc={rc}")
            return []
        arr = (ctypes.c_wchar_p * len(paths))(*paths)
        rc = rm.RmRegisterResources(session, len(paths), arr, 0, None, 0, None)
        if rc != 0:
            log(f"кто держит файл: RmRegisterResources rc={rc}")
            return []
        need = ctypes.c_uint32(0)
        count = ctypes.c_uint32(0)
        reason = ctypes.c_uint32(0)
        info = ()
        rc = rm.RmGetList(session, ctypes.byref(need), ctypes.byref(count), None, ctypes.byref(reason))
        # список процессов может измениться между вызовами, и тогда снова придёт «нужно больше места» -
        # это не отказ, а повод попробовать ещё раз (замечание приёмки 17.10.2026)
        for _ in range(3):
            if rc != _RM_MORE_DATA or not need.value:
                break
            count = ctypes.c_uint32(need.value)
            info = (_RM_PROCESS_INFO * need.value)()
            rc = rm.RmGetList(session, ctypes.byref(need), ctypes.byref(count), info, ctypes.byref(reason))
        if rc != 0:
            log(f"кто держит файл: RmGetList rc={rc}")
            return []
        out = []
        for i in range(min(count.value, len(info))):
            pid = int(info[i].Process.dwProcessId)
            name = (info[i].strAppName or "").strip() or (info[i].strServiceShortName or "").strip()
            if (pid, name) not in out:
                out.append((pid, name))
        return out
    except Exception as e:  # noqa: BLE001 - см. докстринг: падать здесь нельзя ни при каких обстоятельствах
        log(f"кто держит файл: определить не удалось ({_err(e)})")
        return []
    finally:
        if rm is not None and session is not None:
            try:
                rm.RmEndSession(session)
            except Exception:  # noqa: BLE001 - закрыть сеанс не вышло, это не повод ронять установку
                pass


# ------------------------------------------------------------------ уборка за собой
def delete_after_reboot(path, log=_noop):
    """Последняя попытка убрать то, что не удаляется: пометить на удаление при перезагрузке.

    Без прав администратора Windows этого не делает (запись в HKLM) - поэтому только попытка и строка в
    журнале. Основная уборка - при следующей установке (`cleanup`)."""
    if os.name != "nt":
        return False
    try:
        ok = ctypes.windll.kernel32.MoveFileExW(ctypes.c_wchar_p(path), None, 0x4)   # DELAY_UNTIL_REBOOT
    except Exception as e:  # noqa: BLE001
        log(f"уборка при перезагрузке не вышла: {_err(e)}")
        return False
    log(f"{'помечено на удаление при перезагрузке' if ok else 'помечать на удаление при перезагрузке не дали'}: {path}")
    return bool(ok)


def drop(path, log=_noop):
    """Удалить папку. Не вышло - честно сказать и пометить на перезагрузку, но установку не ронять."""
    if not os.path.exists(path):
        return True
    shutil.rmtree(path, ignore_errors=True)
    if not os.path.exists(path):
        return True
    left = sum(1 for _ in _files(path, log=_noop))
    log(f"удалить папку сразу не дали ({left} файл(ов) осталось): {path}")
    # MoveFileEx снимает КАТАЛОГ только пустым, поэтому помечаем и файлы внутри - иначе «пометили» не значит
    # «уберётся» (замечание приёмки 17.10.2026)
    for f, _rel in _files(path, log=_noop):
        delete_after_reboot(f, log=_noop)
    delete_after_reboot(path, log)
    return False


MARK_SUFFIX = ".swapping"
MARK_STALE = 15 * 60          # с: метка старше этого - от установщика, которого уже нет


def mark_path(dest):
    return dest + MARK_SUFFIX


def mark_start(dest, log=_noop):
    """Пометить «я меняю файлы»: номер процесса и время.

    Раньше признаком было наличие «… .old-…», но она остаётся и от ПРЕРВАННОЙ попытки - и тогда следующий
    установщик молча закрывался, решив, что работает кто-то другой. При самообновлении человек видел, что
    программа просто исчезла и ничего не произошло (нашла независимая приёмка 17.10.2026)."""
    try:
        with open(mark_path(dest), "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "time": time.time()}, f)
    except OSError as e:
        log(f"метку «идёт замена» записать не вышло: {_err(e)}")


def mark_done(dest):
    try:
        os.remove(mark_path(dest))
    except OSError:
        pass


def swap_in_progress(dest, alive=None):
    """Кто-то прямо сейчас меняет файлы этой программы?

    Да - только если метка свежая И её процесс ещё жив. Залипшая метка от убитого установщика не считается:
    иначе новый установщик молча уступал бы призраку."""
    alive = alive or fail_texts.pid_alive
    try:
        with open(mark_path(dest), encoding="utf-8") as f:
            mark = json.load(f)
        pid = int(mark.get("pid") or 0)
        when = float(mark.get("time") or 0)
    except (OSError, ValueError, TypeError):
        return False
    if time.time() - when > MARK_STALE:
        return False
    return bool(pid) and pid != os.getpid() and alive(pid)


def _olds(dest, with_files=True):
    """Отставленные версии рядом с папкой программы - самая свежая первой.

    По ВРЕМЕНИ изменения, а не по имени: так надёжнее, если две оборванные попытки попали в одну секунду."""
    base = os.path.dirname(dest) or "."
    start = os.path.basename(dest) + OLD_PREFIX
    paths = [os.path.join(base, n) for n in (os.listdir(base) if os.path.isdir(base) else [])
             if n.startswith(start) and os.path.isdir(os.path.join(base, n))]
    if with_files:
        paths = [p for p in paths if any(True for _ in _files(p))]
    return sorted(paths, key=lambda p: (os.path.getmtime(p), os.path.basename(p)), reverse=True)


def _newest_old(dest):
    """Самая свежая отставленная версия с файлами (или пусто)."""
    olds = _olds(dest)
    return olds[0] if olds else ""


def repair(dest, log=_noop):
    """Прошлая установка оборвалась между переименованиями? Вернуть программу на место.

    Второй установщик намеренно закрывает первый (одна линия установки), и если это случилось ровно между
    «папку в сторону» и «новую на место», папки программы не было бы вовсе (нашла независимая приёмка
    17.10.2026). Теперь при старте смотрим: папки нет или она пуста, а рядом лежит «… .old-…» с файлами -
    возвращаем её. Так человек в худшем случае остаётся на старой версии, а не без программы."""
    if os.path.isdir(dest) and any(True for _ in _files(dest)):
        return False
    # Самая свежая отставленная версия - первая (по ВРЕМЕНИ изменения, а не по имени: так надёжнее, если две
    # оборванные попытки попали в одну секунду - вопрос приёмки 17.10.2026).
    olds = _olds(dest)
    if not olds:
        return False
    if os.path.isdir(new_path(dest)):
        # Рядом лежит распакованная новая версия: ставить её нельзя - распаковка могла оборваться на
        # середине, и целой она только выглядит. Возвращаем ПРОВЕРЕННУЮ старую, новую уберёт cleanup.
        log("рядом лежит распакованная новая версия - не ставлю её (могла распаковаться не до конца), "
            "возвращаю прежнюю")
    if len(olds) > 1:
        log("отставленных версий несколько - беру самую свежую (" + os.path.basename(olds[0]) + "), "
            "остальные не трогаю: " + ", ".join(os.path.basename(p) for p in olds[1:]))
    old = olds[0]
    try:
        if os.path.isdir(dest):
            os.rmdir(dest)                   # пустую папку убираем, чтобы переименование прошло
        _rename(old, dest)
    except OSError as e:
        log(f"вернуть программу из {os.path.basename(old)} не вышло: {_err(e)}")
        return False
    log(f"прошлая установка оборвалась - вернул программу из {os.path.basename(old)}")
    return True


def cleanup(dest, log=_noop, keep=()):
    """Убрать за собой: распакованную «… .new» и отставленные «… .old-*».

    У владельца 17.10.2026 после неудачи осталась папка «Маркер на экране.new» на 60 МБ - и так после каждой
    попытки обновления. Зовём и перед установкой (освобождает место), и после неудачи."""
    gone = []
    base = os.path.dirname(dest) or "."
    name = os.path.basename(dest)
    if not keep:
        keep = keep_read(dest)                # памятка переживает обрыв: что поднять из отставленной версии
        if keep:
            log("памятка рядом с программой: из отставленной версии нужно поднять " + ", ".join(keep))
    olds = sorted(os.path.join(base, n) for n in (os.listdir(base) if os.path.isdir(base) else [])
                  if n.startswith(name + OLD_PREFIX))
    # Если папка программы пуста или её нет, «.old-…» - ЕДИНСТВЕННАЯ целая копия программы (так бывает,
    # когда откат не доделался). Удалять её нельзя: человек останется вообще без программы (приёмка
    # 17.10.2026). Чиним это при следующей установке, а пока - только говорим.
    # Внутри «.new»/«.old-…» могли остаться МОДЕЛИ и ГОЛОСА от оборванной установки - это гигабайты,
    # скачанные человеком. Сначала возвращаем их в папку программы и только потом убираем (приёмка 17.10.2026).
    held = set()
    if keep and os.path.isdir(dest):
        for folder in [new_path(dest)] + olds:
            if os.path.isdir(folder):
                if not move_back(folder, dest, keep, log):
                    # документация обещает «старую папку не удаляем, если не всё перенесли» - теперь это
                    # не только слова: уборка смотрит на результат (приёмка 18.10.2026, вечер)
                    held.add(folder)
                    log("из " + os.path.basename(folder) + " перенесли не всё - эту папку не удаляю")
    if held:
        olds = [p for p in olds if p not in held]
    alive = os.path.isdir(dest) and any(True for _ in _files(dest))
    if olds and not alive:
        log("папка программы пуста - старую версию (" + ", ".join(os.path.basename(p) for p in olds) +
            ") НЕ удаляю: это единственная копия")
        olds = []
    keep_new = False
    if plan_exists(dest):
        # Рядом лежит журнал незаконченной замены: значит, что-то ещё не вернулось на место, и «… .old-…» -
        # единственная копия этих файлов. Раньше журнал удалялся при любом исходе, и следующая уборка
        # уносила невозвращённое (дыра 3 из разбора независимой приёмки 18.10.2026: у неё пропали exe и
        # скачанная модель). Папка программы при этом выглядит живой - по ней беду не видно.
        log("рядом журнал незаконченной замены (" + os.path.basename(plan_path(dest)) +
            ") - ничего из отложенного НЕ удаляю, пока файлы не вернулись на место"
            + (": " + ", ".join(os.path.basename(p) for p in olds) if olds else ""))
        olds = []
        # «… .new» тоже не трогаем: пока журнал жив, в нём есть строки «из .new в папку программы», и без
        # этой папки починка начнёт уносить туда рабочие файлы (приёмка 18.10.2026, вечер).
        keep_new = True
    for path in ([] if (keep_new or new_path(dest) in held) else [new_path(dest)]) + olds:
        if os.path.exists(path):
            drop(path, log)
            gone.append(path)
    left = [p for p in gone if os.path.exists(p)]
    if gone:
        log("убрал за собой: " + ", ".join(os.path.basename(p) for p in gone if p not in left))
    if left:
        # не пишем «убрал», если на диске осталось: это ровно та ложь, которую мы ловим у других сторожей
        log("убрать сразу не дали: " + ", ".join(os.path.basename(p) for p in left) +
            " - уберу при следующей установке")
    return gone


# ------------------------------------------------------------------ сама замена
def _busy(e, path, log=_noop):
    """Ошибка «файл занят» -> наш отказ с причиной, именем файла и держателями (их назовёт RestartManager)."""
    who = holders([path], log=log)
    if who:
        log("файл «%s» держит: %s" % (os.path.basename(path),
                                      "; ".join(f"процесс {pid} «{name}»" for pid, name in who)))
    else:
        log(f"файл «{os.path.basename(path)}» занят, определить держателя не удалось ({_err(e)})")
    kind = fail_texts.reason(e, step="install")
    if getattr(e, "winerror", None) == fail_texts.ERR_DENIED and os.path.isfile(path) and not who:
        # «отказано в доступе» на ОДНОМ файле, и держателя нет: это права или защита папок антивирусом,
        # а не занятость - повторять бессмысленно (приёмка 17.10.2026)
        kind = fail_texts.RIGHTS
    return fail_texts.Fail(kind, _err(e), path=path, holders=who)


def _undo(moved, log=_noop):
    """Вернуть перенесённые файлы на место (откат: старая версия остаётся рабочей).

    Возвращает число файлов, которые вернуть НЕ удалось. Это важно: если откат неполный, старую версию в
    «.old-…» удалять нельзя - она единственная целая (замечание приёмки 17.10.2026)."""
    left = 0
    for src, dst in reversed(moved):
        try:
            _move(dst, src)
        except OSError as e:
            left += 1
            log(f"откат: {os.path.basename(src)} не вернулся - {_err(e)}")
    if left:
        log(f"откат неполный: {left} файл(ов) остались не на месте - старую версию не трогаю")
    return left


PLAN_SUFFIX = ".swap-plan.json"
KEEP_SUFFIX = ".swap-keep.json"


def plan_path(dest):
    return dest + PLAN_SUFFIX


def keep_path(dest):
    return dest.rstrip("\\/") + KEEP_SUFFIX


def keep_write(dest, rels, log=_noop):
    """Запомнить НА ДИСКЕ, что нужно поднять из отставленной версии (модели, голоса, пакет видеокарты).

    Зачем файл: обрыв между «новая папка встала» и переносом данных оставлял их в «… .old-…», а следующий
    установщик про них уже не знал - в новой папке нет `installed.json`, список пакетов пустой, уборка
    сносила старую папку, и человек качал до 3,2 ГБ заново (приёмка 18.10.2026, вечер). Теперь список
    лежит рядом с папкой программы и переживает любой обрыв."""
    rels = [r for r in (rels or ()) if r]
    try:
        if not rels:
            keep_drop(dest)
            return
        with open(keep_path(dest), "w", encoding="utf-8") as f:
            json.dump(rels, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except OSError as e:
        log(f"памятку о скачанном записать не вышло: {_err(e)}")


def keep_read(dest):
    try:
        with open(keep_path(dest), encoding="utf-8", errors="replace") as f:
            rows = json.load(f)
        return [r for r in rows if isinstance(r, str)] if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def keep_drop(dest):
    try:
        os.remove(keep_path(dest))
    except OSError:
        pass


def plan_exists(dest):
    """Рядом с папкой программы лежит журнал незаконченной замены?

    Пока он лежит, уборка НЕ имеет права удалять «… .old-…»: там единственная копия файлов, которые ещё не
    вернулись на место (дыра, которую нашла независимая приёмка 18.10.2026 - у неё пропали exe и модель)."""
    return os.path.exists(plan_path(dest))


def _plan_add(dest, src, dst, log=_noop):
    """Намерение перенести файл - В ЖУРНАЛ ДО САМОГО ПЕРЕНОСА, одной строкой, со сбросом на диск.

    Так было (и так ломалось): журнал перезаписывался целиком одним `json.dump` после каждого переноса.
    Обрыв РОВНО в момент записи (человек закрыл окно крестиком, выключили питание) оставлял полуфайл -
    `json.load` на нём падал, `finish_plan` молча отвечал «журнала нет», следующая уборка сносила «… .old-…»,
    и человек оставался с половиной новой версии и без резерва. Приёмка 18.10.2026 воспроизвела это подменой
    файловой системы: исчезли и exe, и скачанная модель.

    Теперь журнал дописывается строками (одна строка - один перенос) и всегда ОПЕРЕЖАЕТ действие: строка на
    диске, потом перенос. Оборванная последняя строка поэтому безопасна - перенос по ней ещё не начинался.

    Возвращает None, если записалось, и саму ошибку, если нет."""
    line = json.dumps({"from": src, "to": dst}, ensure_ascii=False) + "\n"
    try:
        with open(plan_path(dest), "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())      # без этого строка живёт в кэше Windows и при обрыве питания пропадает
        return None
    except OSError as e:
        log(f"журнал замены записать не вышло: {_err(e)} - менять файлы без журнала не буду")
        return e


def _journal(dest, src, dst, log, *undo_lists):
    """Записать перенос в журнал ДО действия, а если журнал не пишется - отказаться от замены.

    Молча переносить файлы без журнала нельзя: при обрыве следующий запуск не узнает, что куда ушло, уборка
    снесёт «… .old-…», и человек останется без файлов (разбор приёмки 18.10.2026). Поэтому откатываем уже
    перенесённое и говорим человеку настоящую причину - нет места или нет прав, а не «файл занят»."""
    bad = _plan_add(dest, src, dst, log)
    if bad is None:
        return
    left = 0
    for items in undo_lists:
        left += _undo(items, log)
    if left == 0:
        # Откат ПОЛНЫЙ - значит журнал больше ничего не описывает, и оставлять его нельзя. Приёмка
        # 18.10.2026 (вечер): журнал переживал откат, человек жал «Повторить», `finish_plan` проигрывал
        # строки второй половины - место занято возвращённым рабочим файлом, источника в «.new» уже нет -
        # и рабочий файл уезжал в «.new», откуда его сносила уборка. Программа переставала запускаться.
        _plan_drop(dest)
    raise fail_texts.Fail(fail_texts.reason(bad), _err(bad), path=plan_path(dest))


def _plan_read(dest):
    """Журнал замены -> (строки [(откуда, куда)], испорчен ли). Журнала нет - (None, False).

    «Испорчен» - это НЕ обрыв последней строки: её мы пишем и сбрасываем на диск ДО переноса, значит перенос
    по ней не начинался и возвращать нечего. Испорчен - когда нечитаема строка в середине: тогда мы не знаем,
    что успели унести, и собираем прежнюю версию по отставленной папке."""
    try:
        # errors="replace": обрыв питания посреди русской буквы («Маркер на экране») оставляет в файле
        # половину символа. Раньше здесь падал UnicodeDecodeError, `finish_plan` падал следом, и КАЖДОЕ
        # нажатие «Повторить» падало снова - тупик без выхода (приёмка 18.10.2026, вечер). Теперь битый
        # кусок просто не разберётся как строка журнала и попадёт в общий счёт испорченных.
        with open(plan_path(dest), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except (OSError, ValueError):
        return None, False
    rows, bad = [], 0
    if text.lstrip().startswith("["):
        # прежний вид журнала (до 18.10.2026) - один JSON-массив на весь план; читаем, чтобы доиграть замену,
        # начатую установщиком прошлой версии
        try:
            for row in json.loads(text) or []:
                rows.append((row[0], row[1]))
            return rows, False
        except (ValueError, IndexError, TypeError, KeyError):
            return rows, True
    lines = text.split("\n")
    torn_tail = lines[-1] != ""            # файл не кончается переводом строки - последняя строка оборвана
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            rows.append((row["from"], row["to"]))
        except (ValueError, KeyError, TypeError, IndexError):
            if torn_tail and i == len(lines) - 1:
                continue                   # оборванный хвост: перенос по нему не начинался
            bad += 1
    return rows, bool(bad)


def _plan_drop(dest):
    try:
        os.remove(plan_path(dest))
    except OSError:
        pass


def _plan_old_dir(dest, rows):
    """Какая именно «… .old-…» участвует в этом журнале: рядом могут лежать несколько от разных попыток.

    Брать «самую свежую» здесь нельзя: чужая старая папка подсунула бы в программу файлы позапрошлой версии."""
    start = os.path.basename(dest) + OLD_PREFIX
    for _src, dst in rows:
        d = os.path.dirname(dst)
        while d and os.path.basename(d) and not os.path.basename(d).startswith(start):
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        if os.path.basename(d or "").startswith(start):
            return d
    return ""


def _fill_from_old(dest, old, log=_noop, aside=False):
    """Сверить папку программы с отставленной старой версией и вернуть недостающее. Возвращает число неудач.

    Это страховка на случай, когда журналу верить нельзя (испорчен, не дописался). `aside=True` - журнал
    точно про ЭТУ отставленную папку: тогда файл новой версии, уже положенный в папку программы, уносим в
    «… .new», а на его место возвращаем старый. Иначе получается смесь версий: новый exe и старая библиотека -
    программа «обновилась» и не запускается (дыра, которую нашла независимая приёмка 18.10.2026).
    Без `aside` трогаем только пустые места: что лежит в папке программы - не знаем, портить не будем."""
    if not old or not os.path.isdir(old):
        return 0
    left = 0
    try:
        items = sorted(_files(old))
    except OSError as e:
        # Прочитать отставленную папку не дали. Это не повод уронить запуск установщика: говорим и считаем
        # неудачей - тогда журнал останется, а уборка не тронет «… .old-…».
        log(f"прежнюю версию ({os.path.basename(old)}) прочитать не вышло: {_err(e)}")
        return 1
    for path, rel in items:
        target = os.path.join(dest, rel)
        if os.path.exists(target):
            if not aside:
                continue
            spare = os.path.join(new_path(dest), rel)
            try:
                _move(target, spare)      # это файл новой версии - ему место в «… .new», а не в программе
                log(f"смесь версий: {rel} из новой версии унёс обратно в «{os.path.basename(new_path(dest))}»")
            except OSError as e:
                left += 1
                log(f"смесь версий: {rel} из новой версии унести не вышло - {_err(e)}")
                continue
        try:
            _move(path, target)
            log(f"вернул из прежней версии: {rel}")
        except OSError as e:
            left += 1
            log(f"НЕ вернул из прежней версии {rel}: {_err(e)}")
    return left


def finish_plan(dest, log=_noop):
    """Доиграть прерванную пофайловую замену: вернуть программу к той версии, которая работала.

    Возвращает True, если что-то чинили. Зовётся при старте установщика (вместе с repair).

    Три дыры, которые нашла независимая приёмка 18.10.2026 (воспроизвела подменой файловой системы):
    1. обрыв в момент записи журнала оставлял полуфайл, `json.load` падал, функция молча отвечала «нечего
       делать», и уборка сносила резерв - теперь журнал пишется строками и читается построчно;
    2. обрыв ПОСЛЕ того, как часть новых файлов уже легла в папку программы, давал смесь версий: прежний файл
       возвращался только туда, где места не занято, а новый файл место занимал - теперь в журнале обе
       половины замены, обход идёт с конца (новое уносим, старое возвращаем), а в конце ещё и сверка с
       отставленной папкой;
    3. неудача возврата лишь писалась в журнал, план всё равно удалялся, и следующая уборка уносила
       невозвращённое - теперь при любой неудаче журнал остаётся, и уборка «… .old-…» не трогает."""
    rows, damaged = _plan_read(dest)
    if rows is None:
        return False
    old = _plan_old_dir(dest, rows)
    back, left = 0, 0
    for src, dst in reversed(rows):           # с конца: сначала уносим новое, потом возвращаем старое
        if not os.path.exists(dst):
            continue                          # перенос не состоялся (или уже отыгран) - возвращать нечего
        src_root = os.path.dirname(src)
        while src_root and not os.path.isdir(src_root) and os.path.dirname(src_root) != src_root:
            src_root = os.path.dirname(src_root)
        if not os.path.isdir(src_root) or (src.startswith(new_path(dest)) and not os.path.isdir(new_path(dest))):
            # Папки, откуда брали файл, больше нет (например, «… .new» уже убрали). Возвращать некуда, а
            # унести туда то, что сейчас работает у человека, - прямая потеря файлов: ровно так приёмка
            # 18.10.2026 осталась без рабочей библиотеки после «Повторить».
            left += 1
            log(f"прерванная замена: {os.path.basename(dst)} трогать не буду - папки {os.path.basename(src_root) or src_root} больше нет")
            continue
        if os.path.exists(src):
            # Место занято. Обычно это файл новой версии, и его уносит своя же строка журнала - она идёт
            # позже и обрабатывается раньше. Если он всё ещё тут, молча затирать нельзя.
            left += 1
            log(f"прерванная замена: {os.path.basename(src)} не вернуть - на его месте другой файл")
            continue
        try:
            _move(dst, src)
            back += 1
        except OSError as e:
            left += 1
            log(f"прерванная замена: {os.path.basename(src)} не вернулся - {_err(e)}")
    if damaged:
        log("журнал прерванной замены испорчен - собираю прежнюю версию по отставленной папке")
    # Сверка с отставленной папкой: журнал мог не дописаться (нет места, обрыв питания), и тогда в папке
    # программы остаётся новый файл рядом со старыми - то самое «новый exe и старая библиотека».
    # Какую папку считаем своей: названную в журнале, а если журнал нечитаем - самую свежую. Разбирать
    # смесь (`aside`) по чужой папке нельзя, поэтому во втором случае нужен ещё признак оборванной
    # пофайловой замены: рядом лежит «… .new» (при замене папки целиком её уже нет).
    target = old or _newest_old(dest)
    aside = bool(old) or os.path.isdir(new_path(dest))
    if not old and target:
        log("журнал не называет отставленную папку - беру самую свежую: " + os.path.basename(target))
    left += _fill_from_old(dest, target, log, aside=aside)
    log(f"нашёл прерванную замену файлов - вернул на место {back} файл(ов)"
        + (f", не вернулось {left}" if left else ""))
    if left:
        # Журнал НЕ удаляем: пока он рядом, уборка не снесёт «… .old-…» - в ней единственная копия того,
        # что не вернулось (дыра 3 из разбора приёмки 18.10.2026).
        log("журнал замены оставляю рядом: пока не всё вернулось, старую версию удалять нельзя")
    else:
        _plan_drop(dest)
    return True


def _swap_by_files(dest, new, old, log=_noop, rescue=None):
    """Папку переименовать не дали - меняем файлы по одному (измерение: это работает).

    Папка программы остаётся той же: путь установки, ярлыки и запись об удалении не меняются.

    Обе половины замены - старое из папки программы и новое на её место - пишутся в журнал ОДИНАКОВО и до
    действия. Иначе обрыв посреди второй половины оставлял смесь версий: новый exe уже на месте, а старая
    библиотека лежит в «… .old-…», и вернуть её было некуда (нашла независимая приёмка 18.10.2026)."""
    os.makedirs(old, exist_ok=True)
    moved, kept = [], set()
    for path, rel in sorted(_files(dest)):
        _journal(dest, path, os.path.join(old, rel), log, moved)   # журнал опережает перенос
        try:
            _move(path, os.path.join(old, rel))
            moved.append((path, os.path.join(old, rel)))
        except OSError as e:
            fresh = os.path.join(new, rel)
            if os.path.isfile(fresh) and _same(path, fresh):
                kept.add(rel)
                log(f"файл занят, но в новой версии такой же - оставляю как есть: {rel}")
                continue
            if _undo(moved, log) == 0:    # откат полный - «.old-…» пуста и не нужна
                _plan_drop(dest)
                drop(old, log)
            raise _busy(e, path, log)
    placed = []
    for path, rel in sorted(_files(new)):
        if rel in kept:
            continue                      # этот файл уже на месте и не изменился
        _journal(dest, path, os.path.join(dest, rel), log, placed, moved)
        try:
            _move(path, os.path.join(dest, rel))
            placed.append((path, os.path.join(dest, rel)))
        except OSError as e:
            # держат ИСХОДНЫЙ файл новой версии (path), а не его будущее место в папке программы:
            # того ещё нет, и служба перезапуска про него ничего не скажет (приёмка 17.10.2026)
            left = _undo(placed, log)     # новое - назад в «.new»
            left += _undo(moved, log)     # старое - назад в папку программы
            if left == 0:
                _plan_drop(dest)
                drop(old, log)
            raise _busy(e, path, log)
    log(f"заменил файлов: {len(placed)}, оставил без изменений: {len(kept)}")
    _plan_drop(dest)                          # замена дошла до конца - план больше не нужен
    _drop_empty_dirs(dest)                # папки, которых в новой версии больше нет, не остаются пустыми
    _rescue_or_fail(old, dest, log, rescue)
    drop(new, log)                        # от распакованной папки остались пустые каталоги
    return sorted(kept)


def _drop_empty_dirs(root):
    """Убрать пустые каталоги внутри папки программы (сама папка остаётся)."""
    for base, dirs, _names in os.walk(root, topdown=False):     # не «_files»: так зовётся наша же функция
        for name in dirs:
            try:
                os.rmdir(os.path.join(base, name))
            except OSError:
                pass


def move_back(old, dest, rels, log=_noop):
    """Перенести из отставленной старой версии то, что человек УЖЕ скачал: модели распознавания, голоса,
    пакет для видеокарты (у «Транскрибатора» это до 3,2 ГБ, у «Озвучки» - голоса, у «Голоса в Excel» - модель).

    Раньше установщик переносил их в «… .new» ДО замены - и при любой неудаче они пропадали вместе с ней
    (нашла независимая приёмка 17.10.2026: человек оставался со старой версией и без своих мегабайт).
    Теперь их не трогают до успеха, а потом забирают отсюда. Не получилось перенести - возвращаем False, и
    старую папку не удаляют: пусть лучше останется лишняя копия, чем пропадут гигабайты."""
    ok = True
    for rel in rels or ():
        src, dst = os.path.join(old, rel), os.path.join(dest, rel)
        if not os.path.exists(src):
            continue
        if os.path.exists(dst):
            # В новой версии такая папка уже есть. Молча пропустить нельзя: в старой лежат гигабайты человека,
            # и после «успеха» их удалили бы вместе со старой папкой (приёмка 17.10.2026). Переносим то, чего
            # в новой нет, а если что-то осталось - честно возвращаем неудачу.
            moved_any = False
            for path, sub in sorted(_files(src)):
                target = os.path.join(dst, sub)
                if os.path.exists(target):
                    continue
                try:
                    _move(path, target)
                    moved_any = True
                except OSError as e:
                    ok = False
                    log(f"НЕ перенёс {rel}/{sub} из прошлой версии: {_err(e)}")
            # «осталось» - только то, чего в новой папке НЕТ: файл, который уже есть, переносить незачем
            left = [sub for _p, sub in _files(src) if not os.path.exists(os.path.join(dst, sub))]
            if moved_any:
                log(f"дополнил {rel} из прошлой версии")
            if left:
                ok = False
                log(f"в прошлой версии осталось {len(left)} файл(ов) в {rel} - старую папку не удаляю")
            continue
        try:
            parent = os.path.dirname(dst)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            _rename(src, dst)
            log(f"перенёс из прошлой версии: {rel}")
        except OSError as e:
            ok = False
            log(f"НЕ перенёс из прошлой версии {rel}: {_err(e)} - старую папку не удаляю")
    return ok


def _rescue_or_fail(old, dest, log, rescue):
    """Перенести данные человека из отставленной версии - и НЕ называть успехом, если не вышло.

    Приёмка 18.10.2026 (вечер): файлы менялись, «Готово» показывалось, а модели оставались в старой папке -
    человек видел успех и программу, которая говорит «распознавание не установлено». Теперь это отказ с
    понятной причиной, старая папка остаётся на месте, и её содержимое никто не трогает."""
    if rescue is None:
        drop(old, log)
        keep_drop(dest)
        return
    if rescue(old, dest):
        drop(old, log)
        keep_drop(dest)                   # данные на месте - памятка больше не нужна
        return
    log(f"старую версию НЕ удаляю: из неё не всё перенесли ({os.path.basename(old)})")
    raise fail_texts.Fail(fail_texts.OTHER,
                          "новая версия встала, но не удалось перенести скачанное (модели, голоса) из "
                          f"прошлой версии - она осталась в {os.path.basename(old)}", path=old)


def _drop_empty_olds(dest, log=_noop):
    """Убрать ПУСТЫЕ «… .old-…» рядом с программой. Папка с файлами остаётся: в ней может быть единственная
    копия того, что не вернулось (правило 13 чек-листа)."""
    for old in _olds(dest, with_files=False):
        if any(True for _ in _files(old)):
            continue
        drop(old, log)


def _first_file(folder):
    """Первый файл внутри папки - служба перезапуска умеет отвечать только про файлы, не про папки."""
    for path, _rel in sorted(_files(folder)):
        return path
    return ""


def _swap_once(dest, new, log=_noop, rescue=None):
    """Одна попытка: папку целиком, а если не дали - по файлам. Возвращает список оставленных файлов."""
    # распакованной папки нет (её могла убрать уборка после прошлой неудачи) - это не «файл занят»
    if not os.path.isdir(new):
        raise fail_texts.Fail(fail_texts.OTHER, f"распакованной новой версии нет: {new}")
    # пустая новая версия = битый архив; поставить её - значит стереть программу у человека
    if not any(True for _ in _files(new)):
        raise fail_texts.Fail(fail_texts.OTHER, f"новая версия пуста: {new}")
    if not os.path.isdir(dest):
        _rename(new, dest)
        log("папки программы не было - поставил новую")
        return []
    old = _old_path(dest)
    try:
        _rename(dest, old)
    except OSError as e:
        kind = fail_texts.reason(e, step="install")
        if kind != fail_texts.BUSY:
            # «нет места», «слишком длинный путь» и прочее заменой по файлам не лечится - не морочим голову
            log(f"папку программы отставить в сторону не дали, причина «{kind}» ({_err(e)})")
            raise fail_texts.Fail(kind, _err(e), path=dest)
        log(f"папку программы целиком отставить в сторону не дали ({_err(e)}) - меняю файлы по одному")
        return _swap_by_files(dest, new, old, log, rescue)
    try:
        _rename(new, dest)
    except OSError as e:
        # Держат не «папку .new» (про папки служба перезапуска молчит - измерено), а какой-то файл внутри
        # неё: так ведёт себя антивирус на только что распакованных мегабайтах. Возвращаем старую версию
        # и идём по файлам - там видно, КАКОЙ файл занят и кем (приёмка 17.10.2026).
        log(f"новую папку поставить на место не дали ({_err(e)}) - возвращаю старую версию и меняю по файлам")
        try:
            _rename(old, dest)             # откат: старая версия возвращается на место
        except OSError as back:
            log(f"ОТКАТ НЕ ВЫШЕЛ: {_err(back)} (старая версия лежит в {os.path.basename(old)})")
            raise _busy(e, _first_file(new) or new, log)
        return _swap_by_files(dest, new, _old_path(dest), log, rescue)
    log("заменил папку программы целиком")
    _rescue_or_fail(old, dest, log, rescue)
    return []


def swap(dest, new, log=_noop, on_busy=None, pauses=None, sleep=None, rescue=None, rights_tries=RIGHTS_TRIES,
         keep=()):
    """Поставить распакованную папку `new` на место папки программы `dest`.

    Возвращает список файлов, оставленных как были (заняты, но в новой версии такие же).
    Так и не вышло - `fail_texts.Fail` с причиной, путём занятого файла и списком держателей; папка
    программы при этом остаётся рабочей (откат), а «… .new» убирает вызывающий (`cleanup`).

    `on_busy(fail, pause)` - что сказать человеку перед следующей попыткой (сколько ждём и кто держит файл).
    """
    pauses = PAUSES if pauses is None else pauses
    sleep = sleep or time.sleep
    keep_write(dest, keep, log)           # памятка о скачанном - ДО замены: обрыв не должен её стереть
    leave(dest, log)
    mark_start(dest, log)
    last = None
    for n, pause in enumerate((0,) + tuple(pauses)):
        if pause:
            if on_busy:
                on_busy(last, pause)
            sleep(pause)
        try:
            out = _swap_once(dest, new, log, rescue)
            mark_done(dest)
            # Замена УДАЛАСЬ - журналу верить больше не во что: программа новая, возвращать нечего.
            # Находка приёмки 18.10.2026 (поздний вечер): `_plan_drop` был только на пофайловом пути, и
            # журнал от прошлой неудачи оставался рядом с программой навсегда; через месяцы `finish_plan`
            # на старте мог подменить файл нынешней версии старым из залежавшейся «… .old-…».
            _plan_drop(dest)
            _drop_empty_olds(dest, log)
            return out
        except fail_texts.Fail as e:
            last = e
            log(f"замена файлов: попытка {n + 1} из {len(pauses) + 1} не вышла ({e.kind})")
            if e.kind == fail_texts.RIGHTS and n < rights_tries:
                # «Отказано в доступе» чаще всего даёт не нехватка прав, а защита папок антивируса - она
                # отпускает файл через несколько секунд. Короткое ожидание тут помогает (долг 17.10.2026).
                log("«нет прав» - подожду немного: так отвечает защита папок антивируса")
                continue
            if e.kind != fail_texts.BUSY:
                # ждать и повторять имеет смысл, только когда файл ЗАНЯТ (его отпустят). Пустой архив,
                # нет места, слишком длинный путь за две минуты сами не исправятся, а человек всё это
                # время смотрит на «пробую снова» (приёмка 17.10.2026).
                log(f"причина «{e.kind}» от ожидания не пройдёт - больше не повторяю")
                mark_done(dest)
                raise
    mark_done(dest)
    raise last
