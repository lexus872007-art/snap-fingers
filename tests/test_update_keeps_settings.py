"""Обновление не меняет настроек пользователя (владелец 15.10.2026): %APPDATA%\\Щелчок\\settings.json (калибровка щелчка по микрофону, режим, чувствительность, клавиша).

Старый файл настроек с нестандартными значениями (без ключа theme - как у прежних версий) -> установщик заменяет
папку программы (как loader.py) -> программа читает настройки -> всё как было, новые ключи - умолчанием;
сохранение и повторное чтение -> те же значения. Настройки лежат вне папки, которую заменяет установщик.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOADER_DIR = os.path.join(ROOT, "loader")
ENV_OVERRIDES = ()


# ---- общий каркас (одинаковый во всех программах линейки) ----
def _isolate(tmp_path, monkeypatch):
    """%APPDATA%, %LOCALAPPDATA% (и их Linux-аналоги) - во временной папке, переопределения путей сняты."""
    roam, local = tmp_path / "Roaming", tmp_path / "Local"
    roam.mkdir(); local.mkdir()
    for k, v in (("APPDATA", roam), ("XDG_CONFIG_HOME", roam), ("LOCALAPPDATA", local), ("XDG_DATA_HOME", local)):
        monkeypatch.setenv(k, str(v))
    for k in ENV_OVERRIDES:
        monkeypatch.delenv(k, raising=False)
    return roam, local


def _loader(monkeypatch, loader_dir):
    """loader.py установщика (tkinter заглушкой): DEST и текст install() - как в настоящем Setup.exe."""
    import importlib, types
    monkeypatch.setitem(sys.modules, "tkinter", types.ModuleType("tkinter"))
    monkeypatch.syspath_prepend(loader_dir)
    for m in ("loader", "install_version", "brandflow_tk"):
        sys.modules.pop(m, None)
    ld = importlib.import_module("loader")
    for m in ("loader", "install_version", "brandflow_tk"):
        sys.modules.pop(m, None)
    return ld


def _update_like_loader(dest):
    """То, что делает установщик с папкой программы при обновлении: новая версия в <DEST>.new, старая папка
    целиком удаляется, .new -> DEST (uninstall.ps1 при этом НЕ запускается)."""
    import shutil
    os.makedirs(dest, exist_ok=True)
    open(os.path.join(dest, "version.txt"), "w").write("1.0.0")
    open(os.path.join(dest, "old.exe"), "w").write("old")
    new = dest + ".new"
    os.makedirs(new)
    open(os.path.join(new, "new.exe"), "w").write("new")
    os.rename(dest, dest + ".old")
    shutil.rmtree(dest + ".old")
    os.rename(new, dest)


def _check_loader_keeps_settings(ld, settings_file):
    src = open(ld.__file__, encoding="utf-8").read()
    body = src[src.index("def install("):src.index("\ndef ", src.index("def install(") + 10)]
    dest = os.path.abspath(ld.DEST)
    sf = os.path.abspath(settings_file)
    for d in (dest, dest + ".new", dest + ".old"):
        assert not (sf + os.sep).startswith(d + os.sep), f"настройки {sf} внутри папки, которую заменяет установщик ({d})"
    # uninstall.ps1 установщик только пишет и кладёт в ярлык «Удалить …», но не запускает
    for line in body.splitlines():
        if re.search(r"subprocess\.(run|Popen|call)|os\.startfile|\bps\(", line):
            assert "un)" not in line and "uninstall" not in line, line
    return dest



def test_update_keeps_settings(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    sys.path.insert(0, ROOT)
    from shchelchok import settings
    from shchelchok.detector import DEC_POINTS, NBANDS
    tpl = {"shape": [0.1 * (i + 1) for i in range(NBANDS)], "dec": [0.5] * len(DEC_POINTS), "peak_min": 0.12}
    old = {"listening": False, "mode": 3, "sens": 8, "mic": "Микрофон (USB Audio)",
           "templates": {"Микрофон (USB Audio)": tpl, "": tpl}, "mute": True, "unmute": False, "toast": False,
           "ignore_output": False, "ignore_typing": False, "hotkeys": {"toggle": "Ctrl+Alt+K"}, "autostart": True,
           "first_run": False, "hue": 120}
    path = os.path.join(settings.config_dir(), "settings.json")
    os.makedirs(os.path.dirname(path))
    json.dump(old, open(path, "w", encoding="utf-8"))
    ld = _loader(monkeypatch, LOADER_DIR)
    _update_like_loader(_check_loader_keeps_settings(ld, path))
    s = settings.load()
    assert {k: s[k] for k in old} == old and s["theme"] == "violet"
    # единственное, что обновление меняет нарочно (решение владельца 16.10.2026): возврат одним щелчком.
    # В старом файле стояло «возврат двумя щелчками», но это было умолчание, а не выбор человека.
    assert s["back"] == 1
    assert s["admin"] is False                      # новый ключ 1.3.0 - умолчанием
    # порог (1.3.0) считается из прежней чувствительности: программа слушает ровно как до обновления
    assert s["thr"] == 45 and s["sens"] == 8
    s["theme"] = "custom"
    s["back"] = 3                                   # теперь это ОСОЗНАННЫЙ выбор - он обязан пережить перезапуск
    s["thr"] = 40
    settings.save(s)
    again = settings.load()
    assert {k: again[k] for k in old} == old and again["theme"] == "custom"
    assert again["back"] == 3                      # свой выбор держится (в файле появился ключ "ver")
    assert again["thr"] == 40, "свой порог переживает перезапуск"
    # калибровка (шаблон щелчка владельца) - главное, что обязано пережить обновление
    assert again["templates"]["Микрофон (USB Audio)"] == tpl and again["mic"] == "Микрофон (USB Audio)"
