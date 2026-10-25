"""Настройки (%APPDATA%\\Щелчок\\settings.json) и горячая клавиша. Без Qt.

Клавиша хранится строкой «Ctrl+Alt+Z»; для Windows (RegisterHotKey) - пара (модификаторы, код клавиши).
Шаблон щелчка (калибровка) хранится по микрофону: у ноутбука и гарнитуры щелчок звучит по-разному.
"""
from __future__ import annotations

import json
import os
import re

from . import app_update

TITLE = "Щелчок"
APP = "shchelchok"

HOTKEY_ACTIONS = [
    ("toggle", "Свернуть / вернуть", "Ctrl+Alt+Z"),
]

# Клавиши соседних программ линейки: по умолчанию не берём, при назначении - предупреждение, чья это клавиша.
LINE_HOTKEYS = {
    "Ctrl+Alt+Space": "Local Voice",
    "Ctrl+Alt+G": "Голос в Excel",
    "Ctrl+Alt+D": "Маркер на экране", "Ctrl+Alt+F": "Маркер на экране", "Ctrl+Alt+H": "Маркер на экране",
    "Ctrl+Alt+S": "Маркер на экране", "Ctrl+Alt+W": "Маркер на экране",
    "Ctrl+Alt+P": "Суфлёр", "Ctrl+Alt+O": "Суфлёр", "Ctrl+Alt+Up": "Суфлёр", "Ctrl+Alt+Down": "Суфлёр",
    "Ctrl+Alt+PgUp": "Суфлёр", "Ctrl+Alt+PgDown": "Суфлёр", "Ctrl+Alt+Home": "Суфлёр",
}

MODES = [(1, "Один щелчок"), (2, "Два щелчка подряд"), (3, "Три щелчка подряд")]
# Сколько щелчков возвращают окна - выбор владельца 16.10.2026. Цифры случайных возвратов - на 30-минутной
# записи сплошного шума офиса при включённой защите от клавиатуры и мыши (eval/fast_toggle.py).
BACK_MODES = [(1, "Один щелчок", "Быстро: свернул - вернул - свернул, в любом темпе"),
              (2, "Два подряд", "Страховка: случайный стук не вернёт окна, пока вы отошли"),
              (3, "Три подряд", "Самая надёжная страховка - и самая медленная")]
# Честная разница, числом (30 минут записи сплошного шума офиса, защита от клавиатуры и мыши включена):
BACK_WHY = "Два или три подряд - страховка от случайного стука."
BACK_WHY_FULL = ("На записи сплошного офисного шума окна возвращались сами: при одном щелчке - 40 раз в час, "
                 "при двух - 13, при трёх - 8 (защита от клавиатуры и мыши включена).\n"
                 "В тихой комнате этого не бывает: в журнале владельца за 7 часов - ни одного раза.")
SENS_MIN, SENS_MAX = 1, 10
THR_MIN, THR_MAX = 25, 75          # порог оценки: шаг 1 очко (у чувствительности шаг был 5 - «40 или 45, между
THR_SAFE = 35                      # ними ничего»); ниже THR_SAFE в окне честно написано про посторонние звуки

# Возврат окон (владелец 16.10.2026: «на 2 щелчка возврат всех окон, которые свернул»): окна свёрнуты - возвращают
# ДВА щелчка подряд (до 16.10 было три - владелец не смог вернуть окна); одиночный щелчок по умолчанию ничего не
# делает (случайный шум не вернёт окна в неподходящий момент). Клавиша и значок у часов - всегда.
RESTORE_WORD = {1: "Один щелчок", 2: "Два щелчка подряд", 3: "Три щелчка подряд"}


def back_series(n=None, lower=False):
    """«Два щелчка подряд» - сколько щелчков возвращает окна (одно место на программу)."""
    if n is None:
        from .detector import RESTORE_N
        n = RESTORE_N
    t = RESTORE_WORD.get(int(n), f"{int(n)} щелчка подряд")
    return t[0].lower() + t[1:] if lower else t


BACK_WARN_SAME = "Та же серия и свернёт, и вернёт."
BACK_WARN_SAME_WHY = ("Сколько щелчков сворачивает, столько же и возвращает - что произойдёт, решает состояние "
                      "окон. Надёжнее возвращать клавишей или значком у часов.")

# Ссылки в окне. Программа бесплатная, остальные - на сайте (владелец 16.10.2026). Место под репозиторий есть:
# добавить строку ("Исходники", "https://github.com/…") - больше ничего менять не нужно.
LINKS = [("Ещё бесплатные программы", "https://ty-biznesmen.ru/")]

DEFAULTS = {
    "listening": True,             # слушаю / пауза
    "mode": 1,                     # свернуть: 1 - одиночный щелчок (решение владельца 15.10), 2/3 - по желанию
    "back": 1,                     # сколько щелчков ВОЗВРАЩАЮТ окна: 1 (по умолчанию - быстро), 2 или 3 подряд
                                   # (страховка: случайный стук не вернёт окна, пока человек отошёл)
    "sens": 5,                     # чувствительность 1-10 (старое имя порога; оставлено для прежних настроек)
    "thr": 45,                     # порог оценки «это щелчок», 25-75 (владелец 17.10: «порог можно регулировать»)
    "admin": False,                # запускать с правами администратора (окна «от администратора» - п. 1 задачи)
    **app_update.DEFAULTS,         # самообновление (галочка «Проверять обновления» и т.д.) - общий набор линейки
    "mic": "",                     # имя микрофона; пусто - как в Windows
    "templates": {},               # имя микрофона ("" - как в Windows) -> шаблон щелчка
    "mute": False,                 # заодно выключать звук компьютера
    "unmute": True,                # при возврате - вернуть звук как был
    "toast": True,                 # плашка «Свернул» на 1 с
    "ignore_output": True,         # не реагировать на удары в звуке самого компьютера
    "ignore_typing": True,         # не реагировать, пока печатают/щёлкают мышью на этом компьютере
    "hotkeys": {k: v for k, _, v in HOTKEY_ACTIONS},
    "autostart": False,
    "first_run": True,
    "ver": "",                     # версия, которая записала файл (нужна для переноса настроек между выпусками)
    "theme": "violet",             # цвет оформления (brand.THEMES)
    "hue": 263,                    # оттенок для темы «Свой», градусы
}
THEME_IDS = ("violet", "blue", "teal", "green", "red", "orange", "pink", "graphite", "custom")


def theme_value(data):
    """Тема строкой для общего выбора цвета линейки (ThemePicker, brand_theme): "violet" | "custom:200"."""
    if data.get("theme") == "custom":
        return f"custom:{_clamp_int(data.get('hue'), 0, 359, DEFAULTS['hue'])}"
    return data.get("theme") if data.get("theme") in THEME_IDS else DEFAULTS["theme"]


def theme_parts(value):
    """Обратно: "custom:200" -> ("custom", 200), "blue" -> ("blue", None). Оттенок по кругу (725 -> 5)."""
    v = str(value or "")
    if v.startswith("custom:"):
        try:
            return "custom", int(float(v.split(":", 1)[1])) % 360
        except ValueError:
            return "custom", DEFAULTS["hue"]
    return (v if v in THEME_IDS else DEFAULTS["theme"]), None


def line_owner(text):
    """Клавиша занята другой программой линейки -> её название, иначе None."""
    p = parse_hotkey(text)
    if p is None:
        return None
    for k, owner in LINE_HOTKEYS.items():
        if parse_hotkey(k) == p:
            return owner
    return None


# ---------------------------------------------------------------- клавиши
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MODS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN, "meta": MOD_WIN}
_NAMED_VK = {"ESC": 0x1B, "SPACE": 0x20, "PRINT": 0x2C, "PRTSC": 0x2C, "PRINTSCREEN": 0x2C, "INS": 0x2D,
             "INSERT": 0x2D, "DEL": 0x2E, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23, "PGUP": 0x21, "PAGEUP": 0x21,
             "PGDOWN": 0x22, "PGDN": 0x22, "PAGEDOWN": 0x22, "PAUSE": 0x13, "TAB": 0x09, "BACKSPACE": 0x08,
             "ENTER": 0x0D, "RETURN": 0x0D, "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28}


def parse_hotkey(text: str):
    """«Ctrl+Alt+Z» -> (MOD_CONTROL|MOD_ALT, 0x5A). Неверная строка или клавиша без Ctrl/Alt/Win (кроме F1-F24 и
    Print Screen) -> None: одиночную клавишу нельзя забирать у всей системы."""
    if not text:
        return None
    parts = [p.strip() for p in text.replace(" ", "").split("+") if p.strip()]
    if text.strip().endswith("++"):
        parts.append("+")
    if not parts:
        return None
    mods = 0
    for p in parts[:-1]:
        m = _MODS.get(p.lower())
        if m is None:
            return None
        mods |= m
    key = parts[-1].upper()
    if key.lower() in _MODS:
        return None
    if len(key) == 1 and ("A" <= key <= "Z" or "0" <= key <= "9"):
        vk = ord(key)
    elif re.fullmatch(r"F([1-9]|1\d|2[0-4])", key):
        vk = 0x6F + int(key[1:])
    elif key in _NAMED_VK:
        vk = _NAMED_VK[key]
    else:
        return None
    fkey = 0x70 <= vk <= 0x87 or vk == 0x2C
    if not fkey and not (mods & (MOD_CONTROL | MOD_ALT | MOD_WIN)):
        return None
    return mods, vk


def hotkey_problem(text):
    """Текст для человека: что не так с клавишей (None - всё хорошо, пусто - клавиша выключена)."""
    if not text:
        return None
    if parse_hotkey(text) is None:
        return "нужна Ctrl, Alt или Win"
    owner = line_owner(text)
    if owner:
        return f"занято программой {owner}"
    return None


def hotkey_problem_full(text):
    """То же подробнее - для подсказки (в окне строка короткая, она стоит рядом с полем ввода)."""
    if not text:
        return None
    if parse_hotkey(text) is None:
        return "Нужна клавиша вместе с Ctrl, Alt или Win (или F1-F24): одиночную клавишу нельзя забирать у всей системы."
    owner = line_owner(text)
    if owner:
        return f"{text} уже занято программой «{owner}» из этой же линейки - лучше выбрать другую клавишу."
    return None


# ---------------------------------------------------------------- файлы
def config_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, TITLE)


def show_flag():
    """Файл-просьба «покажи окно» от второй копии (когда первая работает с правами администратора и окно-сервер
    между разными правами Windows не пускает)."""
    return os.path.join(config_dir(), "show.flag")


def _clamp_int(v, lo, hi, default):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def valid_template(t):
    try:
        from .detector import NBANDS, DEC_POINTS
        if not (isinstance(t, dict) and len(t["shape"]) == NBANDS and len(t["dec"]) == len(DEC_POINTS)
                and all(isinstance(v, (int, float)) for v in t["shape"] + t["dec"])
                and isinstance(t["peak_min"], (int, float))):
            return False
    except (KeyError, TypeError):
        return False
    if "samples" in t:                 # образцы щелчка (с 1.3.0); испорченные - просто выбрасываем
        t["samples"] = [s for s in t["samples"] if valid_sample(s)] if isinstance(t["samples"], list) else []
    return True


def valid_sample(s):
    """Один образец щелчка в шаблоне: форма, затухание, громкость."""
    try:
        from .detector import NBANDS, DEC_POINTS
        return (isinstance(s, dict) and len(s["shape"]) == NBANDS and len(s["dec"]) == len(DEC_POINTS)
                and all(isinstance(v, (int, float)) for v in s["shape"] + s["dec"])
                and isinstance(s["peak"], (int, float)))
    except (KeyError, TypeError):
        return False


def mic_id(name):
    """Имя микрофона -> «отпечаток» устройства для поиска настройки. Общий режим Windows обрезает имя до 31 знака
    («Набор микрофонов (Realtek(R) Au»), регистр и пробелы тоже плавают - сравниваем по началу имени."""
    return " ".join(str(name or "").lower().split())[:24]


def match_template_key(templates, key):
    """Настройка щелчка для этого микрофона, даже если имя пришло обрезанным или в другом регистре.
    -> ключ из templates или None (баг 16.10.2026: «микрофон «» без своей настройки»)."""
    k = mic_id(key)
    if not k:
        return None
    for name in templates:
        if mic_id(name) == k:
            return name
    for name in templates:              # одно имя - начало другого (31 знак общего режима)
        a, b = mic_id(name), k
        if a and b and (a.startswith(b) or b.startswith(a)):
            return name
    return None


def load(path=None):
    path = path or os.path.join(config_dir(), "settings.json")
    data = json.loads(json.dumps(DEFAULTS))
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        for k, v in saved.items():
            if k == "hotkeys" and isinstance(v, dict):
                data["hotkeys"].update({a: s for a, s in v.items() if a in data["hotkeys"] and isinstance(s, str)})
            elif k in data:
                data[k] = v
        migrate(data, saved)
    except (OSError, ValueError, AttributeError):
        pass
    return normalize(data)


def migrate(data, saved):
    """Обновление НЕ меняет того, как программа слушает (чек-лист п. 11), кроме одного решения владельца.

    Порог оценки («щелчок принимается от 45 из 100») появился в 1.3.0; до этого то же самое настраивалось
    ползунком «Чувствительность» 1-10. У кого в файле есть только чувствительность - порог считаем из неё
    (у владельца чувствительность 8 - это порог 45, ровно как было), а не берём новое значение по умолчанию."""
    from .detector import threshold
    if "thr" not in saved and isinstance(saved.get("sens"), (int, float)):
        s = _clamp_int(saved.get("sens"), SENS_MIN, SENS_MAX, DEFAULTS["sens"])
        data["thr"] = int(round(threshold(s)))
    # Исключение, о котором владелец попросил прямо (16.10.2026): «щёлкнул один раз - свернулось, щёлкнул второй
    # раз - развернулось». В файлах до 1.3.0 (у них нет ключа "ver") стояло «возврат двумя щелчками» - это было
    # значение по умолчанию, а не выбор человека, поэтому переносим его на новое поведение. Всё остальное из
    # старого файла остаётся как было.
    if "back" not in saved:
        # в 1.3.0 это была галочка single_restores; осознанный выбор «двумя щелчками» сохраняем
        data["back"] = RESTORE_WORD and (2 if (saved.get("ver") and saved.get("single_restores") is False)
                                         else DEFAULTS["back"])
    return data


def normalize(data):
    """Испорченные или чужие значения - в допустимые пределы (файл могли поправить руками)."""
    d = DEFAULTS
    data["mode"] = data["mode"] if data.get("mode") in (1, 2, 3) else d["mode"]
    data["sens"] = _clamp_int(data.get("sens"), SENS_MIN, SENS_MAX, d["sens"])
    data["thr"] = _clamp_int(data.get("thr"), THR_MIN, THR_MAX, d["thr"])
    data["back"] = data["back"] if data.get("back") in (1, 2, 3) else d["back"]
    for k in ("listening", "mute", "unmute", "toast", "ignore_output", "ignore_typing",
              "autostart", "admin", "first_run"):
        data[k] = bool(data.get(k)) if data.get(k) is not None else d[k]
    if data.get("theme") not in THEME_IDS:
        data["theme"] = d["theme"]
    data["hue"] = _clamp_int(data.get("hue"), 0, 359, d["hue"])
    for k in ("mic", "ver"):
        if not isinstance(data.get(k), str):
            data[k] = DEFAULTS[k]
    app_update.normalize(data)          # ключи самообновления - по общим правилам линейки
    tp = data.get("templates")
    data["templates"] = {k: v for k, v in tp.items() if isinstance(k, str) and valid_template(v)} \
        if isinstance(tp, dict) else {}
    return data


def save(data, path=None):
    path = path or os.path.join(config_dir(), "settings.json")
    try:
        from . import __version__
        data["ver"] = __version__
    except ImportError:
        pass
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
