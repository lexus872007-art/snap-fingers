"""Строка версии в окне установщика - ОДНА для всей линейки (владелец 15.10.2026, эталон - «Сверка документов»).

Источник: ~/office_tools/_brand/install_version.py. Копии лежат рядом с loader.py каждого установщика
(loader/, 02, 03, 09, 12, 13, 18, 19) - не править там, раздавать: python3 ~/office_tools/_brand/sync.py

- есть установленная версия (HKCU ...\\Uninstall\\<ключ> DisplayVersion, запасной - файл версии в папке программы)
  -> «Было: X → Стало: Y», в том числе когда X == Y (переустановка той же версии);
- установленной нет -> «Устанавливается версия Y»;
- в конце -> «Установлена версия Y».
"""
import os

VERSION_FILE = "version.txt"                 # запасной источник «что стоит сейчас» (пишет установщик)
# version_txt(dest) - прочитать его; им пользуются установщики с собственным installed.json (02, 09)
# вид строки версии в окне установщика (как у «Сверки документов»): y и ширина - в точках 96 dpi, окно 560 x 290
VERSION_Y, VERSION_WIDTH, VERSION_FILL, VERSION_FONT = 76, 480, "#FFE9A0", ("Segoe UI", 10, "bold")


def version_line(old, new):
    old = str(old).strip() if old else ""
    return f"Было: {old} → Стало: {new}" if old else f"Устанавливается версия {new}"


def done_line(new):
    return f"Установлена версия {new}"


def version_txt(dest):
    try:
        with open(os.path.join(dest, VERSION_FILE), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def installed_version(dest, uninstall_key, fallback=None):
    """Версия, которая уже стоит: запись «Установка и удаление программ» (DisplayVersion), запасной - fallback()
    (по умолчанию version.txt в папке программы). Папки программы нет - None (первая установка)."""
    if not os.path.isdir(dest):
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key) as k:
            v = str(winreg.QueryValueEx(k, "DisplayVersion")[0]).strip()
            if v:
                return v
    except Exception:  # noqa: BLE001 - нет записи или не Windows
        pass
    try:
        v = (fallback or version_txt)(dest)
    except Exception:  # noqa: BLE001
        v = None
    return str(v).strip() if v else None
