# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Открытые компоненты: раздел в настройках есть, файл лицензий открывается, в видимых текстах нет
наших подробностей о том, КАК сделана программа (владелец 17.10.2026: «если не требуется - то не
пиши об этом, а то скопируют»).

Этот файл один на всю линейку: КОПИЯ ~/office_tools/_brand/tests/program_licenses.py, лежит в каждой
программе как tests/test_licenses.py (раздаёт `python3 _brand/sync.py`). Править - только в _brand.

Что проверяем:
1. рядом с программой есть licenses/«Сторонние компоненты.txt» и в нём перечислены компоненты;
2. каждый файл с текстом лицензии, на который ссылается перечень, лежит рядом и не пустой;
3. в перечне и в видимых текстах программы нет слов-примет нашей кухни (app_licenses.HIDDEN);
4. в окне настроек есть строка «Программа использует открытые компоненты…» и кнопка «Открыть лицензии»
   (ровно теми же словами, что в общем модуле - одинаково во всех программах);
5. кнопка открывает именно этот файл (на Windows - в блокноте);
6. папка licenses попадает в сборку (spec-файл или build.sh).
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Слова-приметы: наше описание «как это сделано» (подготовка моделей, средства сборки, устройство
# словаря, имена внутренних файлов). В видимых текстах - перечне лицензий, окне программы, установщике,
# уведомлении рядом с голосами - их быть не должно. Сам список в программу не попадает: он только здесь.
HIDDEN = (
    "float16", "float32", "int8", "квантиз", "quantize", "quant_pre_process", "quanttype",
    "выведены формы", "формы тензоров", "граф модели", "граф с заранее", "shape_inference",
    "таблица слов", "словарь произношений преобразован", "преобразован в sqlite",
    "wordpiece", "lexicon.sqlite", "voice.onnx", "prosody.onnx", "prosody_vocab",
    "pyinstaller", "docvoice/tts.py", "docvoice\\tts.py",
)


def hidden_in(text: str) -> list:
    """Какие слова-приметы встретились в тексте."""
    low = (text or "").lower()
    return [w for w in HIDDEN if w in low]


def _package_dir() -> str:
    """Папка с кодом программы (там лежит копия app_licenses.py)."""
    for name in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, name)
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, "app_licenses.py")) and name != "loader":
            return p
    raise AssertionError("не нашёл app_licenses.py в папке программы - запустите python3 _brand/sync.py")


def _load_app_licenses():
    path = os.path.join(_package_dir(), "app_licenses.py")
    spec = importlib.util.spec_from_file_location("app_licenses_copy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    AL = _load_app_licenses()
    LIC_DIR = os.path.join(ROOT, AL.FOLDER)
    NOTICE = os.path.join(LIC_DIR, AL.FILE_NAME)
except AssertionError:          # файл открыли не из программы (например, из _brand) - нужны только слова-приметы
    AL, LIC_DIR, NOTICE = None, "", ""


def _notice_text() -> str:
    with open(NOTICE, encoding="utf-8") as fh:
        return fh.read()


def _visible_files() -> list:
    """НАШИ тексты, которые видит человек: перечень лицензий, окно программы, установщик.

    Сами тексты лицензий (файлы сторонних правообладателей) не трогаем и не проверяем: они
    приводятся дословно, и слова вроде «quantization» в лицензии на JPEG - не про нас."""
    out = [NOTICE] if os.path.isfile(NOTICE) else []
    ui = os.path.join(ROOT, "ui")
    if os.path.isdir(ui):
        for name in sorted(os.listdir(ui)):
            if name.endswith((".html", ".js", ".css")) and name not in ("brand-flow.js", "brand-flow.css"):
                out.append(os.path.join(ui, name))
    loader = os.path.join(ROOT, "loader", "loader.py")
    if os.path.isfile(loader):
        out.append(loader)
    return out


def test_licenses_folder_with_notice():
    assert os.path.isfile(NOTICE), (
        f"нет {AL.FOLDER}/{AL.FILE_NAME} - соберите: python3 ~/office_tools/_brand/tools/make_licenses.py")
    text = _notice_text()
    items = [ln for ln in text.splitlines() if ln.startswith("- ")]
    assert len(items) >= 5, f"в перечне всего {len(items)} компонентов - похоже, он неполный"
    assert "ТЫ - бизнесмен" in text


def test_every_mentioned_license_text_lies_next_to_it():
    text = _notice_text()
    names = set()
    for m in re.finditer(r"Текст(?:ы)? лиценз[а-я]+:\s*([^\n]+(?:\n\s{2}[^\n]+)?)", text):
        for part in m.group(1).replace("\n", " ").split(","):
            part = part.strip().rstrip(".").strip()
            if part.endswith(".txt"):
                names.add(part)
    assert names, "перечень ни разу не ссылается на файл с текстом лицензии"
    for name in sorted(names):
        path = os.path.join(LIC_DIR, name)
        assert os.path.isfile(path), f"перечень ссылается на {name}, а файла рядом нет"
        assert os.path.getsize(path) > 200, f"{name} подозрительно короткий - текст лицензии неполный"


def test_no_license_file_left_unmentioned():
    """Лишних файлов в папке нет: всё, что лежит рядом, названо в перечне (иначе непонятно, чьё это)."""
    text = _notice_text()
    for name in sorted(os.listdir(LIC_DIR)):
        if name == AL.FILE_NAME:
            continue
        assert name in text, f"файл {name} лежит в {AL.FOLDER}, но в перечне не упомянут"


def test_no_hidden_details_in_visible_texts():
    for path in _visible_files():
        with open(path, encoding="utf-8", errors="replace") as fh:
            found = hidden_in(fh.read())
        assert not found, f"{os.path.relpath(path, ROOT)}: наше описание «как сделано» ({', '.join(found)})"


def test_settings_show_one_line_and_a_button():
    """Та же строка и та же кнопка, что во всех программах линейки."""
    hits = {"line": [], "button": []}
    for sub in ("ui", os.path.basename(_package_dir())):
        d = os.path.join(ROOT, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith((".html", ".js", ".py")):
                continue
            with open(os.path.join(d, name), encoding="utf-8", errors="replace") as fh:
                body = fh.read()
            if AL.SETTINGS_LINE in body:
                hits["line"].append(name)
            if AL.BUTTON in body:
                hits["button"].append(name)
    assert hits["line"], f"в окне нет строки «{AL.SETTINGS_LINE}»"
    assert hits["button"], f"в окне нет кнопки «{AL.BUTTON}»"


def test_button_opens_the_notice_file():
    cmds = []
    assert AL.open_licenses((ROOT,), runner=lambda cmd: cmds.append(cmd)) is True
    assert cmds, "кнопка «Открыть лицензии» ничего не запустила"
    assert NOTICE in cmds[0][-1], f"открыли не тот файл: {cmds[0]}"


def test_notepad_on_windows(monkeypatch):
    cmds = []
    monkeypatch.setattr(AL.sys, "platform", "win32")
    assert AL.open_licenses((ROOT,), runner=lambda cmd: cmds.append(cmd)) is True
    assert cmds[0][0] == "notepad.exe", f"на Windows открываем блокнотом, а не {cmds[0][0]}"


def test_build_puts_licenses_next_to_the_program():
    specs = [os.path.join(ROOT, n) for n in os.listdir(ROOT) if n.endswith(".spec")]
    builds = [os.path.join(ROOT, "tools", "wine", "build.sh"), os.path.join(ROOT, "tools", "build_win.sh")]
    texts = []
    for path in specs + builds:
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                texts.append(fh.read())
    assert texts, "не нашёл ни spec-файла, ни build-скрипта программы"
    assert any("licenses" in t for t in texts), "папка licenses не попадает в сборку (spec/build.sh)"


def test_pack_notice_loses_our_details(tmp_path):
    """Уведомление рядом с голосами/моделями: наше описание заменяется короткой строкой."""
    p = tmp_path / "LICENSE-голоса.txt"
    p.write_text("Модель: Apache 2.0.\nИзменения: веса хранятся в float16; словарь произношений преобразован в SQLite.\n",
                 encoding="utf-8")
    assert AL.fix_pack_notice(str(p), "Программа") is True
    body = p.read_text(encoding="utf-8")
    assert not hidden_in(body)
    assert "Apache License 2.0" in body
    assert AL.fix_pack_notice(str(p), "Программа") is False       # второй раз менять нечего


def test_pack_notice_untouched_when_already_neutral(tmp_path):
    """Нейтральный текст уже на месте - файл не трогаем (никаких лишних записей при каждом запуске)."""
    p = tmp_path / "LICENSE-голоса.txt"
    p.write_text(AL.PACK_NOTICE.format(title="Программа", file_name=AL.FILE_NAME), encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    assert AL.fix_pack_notice(str(p), "Программа") is False
    assert p.read_text(encoding="utf-8") == before


def test_marker_words_are_not_inside_the_program_itself():
    """Самого списка слов-примет в программе быть не должно (строки видны внутри exe)."""
    path = os.path.join(_package_dir(), "app_licenses.py")
    with open(path, encoding="utf-8") as fh:
        body = fh.read().lower()
    for word in ("float16", "lexicon.sqlite", "wordpiece"):
        assert word not in body, f"слово «{word}» лежит внутри программы - уберите его из app_licenses.py"


# ---------------------------------------------------------------- правда про сеть (приёмка 18.10.2026)
# Беда: в `licenses/Сторонние компоненты.txt` - файле, который человек открывает кнопкой ПРЯМО ИЗ ОКНА, -
# у всех программ стояло «Программа работает без интернета», хотя самообновление в сеть выходит. Прежний
# сторож смотрел выборочный список файлов (код, loader.py, README, release_notes) и папку licenses не читал.
# Теперь читаем ВСЕ текстовые файлы, которые попадают к человеку: код программы, окно, перечень лицензий,
# установщик, README и «что нового».
LIE_ABOUT_NET = ("не выходит в интернет", "без интернета", "не ходит в интернет", "интернет не нужен",
                 "не требует интернета", "работает офлайн")
TEXT_EXT = (".py", ".txt", ".md", ".html", ".js", ".css", ".json", ".ps1")
SKIP_DIRS = {"tests", "tests_ui", "tools", "promo", "video", "screens", "qa_out", "__pycache__", ".git",
             "node_modules", "vendor", "corpus", "examples", "demo"}


def visible_text_files() -> list:
    """Все тексты, которые видит человек: папка программы, окно (ui), перечень лицензий, установщик, README.

    Чужие тексты лицензий (licenses/texts, LICENSE-*) не наши - их не правим и не проверяем."""
    out = []
    for base in (_package_dir(), os.path.join(ROOT, "ui"), os.path.join(ROOT, AL.FOLDER),
                 os.path.join(ROOT, "loader")):
        if not os.path.isdir(base):
            continue
        for root, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for n in names:
                if not n.lower().endswith(TEXT_EXT):
                    continue
                if n.startswith("LICENSE") or n.startswith("COPYING") or "licenses/texts" in root.replace("\\", "/"):
                    continue          # дословные тексты чужих лицензий
                if n in ("brand-flow.js", "brand-flow.css", "app-update.js") or n.endswith(".min.js"):
                    continue          # общие файлы линейки, они проверяются в _brand
                out.append(os.path.join(root, n))
    p = os.path.join(ROOT, "release_notes.txt")       # его первая строка уходит в latest.json - это видит человек
    if os.path.isfile(p):
        out.append(p)
    return out                                        # README.md - доку для разработчика сюда НЕ берём


def _no_comments(path: str, body: str) -> str:
    """Убираем записки разработчика: /* … */ в css и js, строку-комментарий // в js, <!-- … --> в html.

    Комментарий человек не читает, обещанием он не является; иначе сторож гоняет переписывать пояснения
    про шрифты («всё офлайн: шрифт лежит в fonts/») в каждом файле оформления."""
    low = path.lower()
    if low.endswith((".css", ".js")):
        body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
    if low.endswith(".js"):
        body = re.sub(r"^[ \t]*//.*$", " ", body, flags=re.M)
    if low.endswith((".html", ".htm")):
        body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    return body


def visible_strings(path: str) -> str:
    """Текст, который может увидеть ЧЕЛОВЕК. У .py это строки-литералы без докстрингов: комментарий и
    докстринг - записка разработчику, а не обещание человеку (иначе сторож заставляет переписывать доку)."""
    try:
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
    except (OSError, UnicodeDecodeError):
        return ""
    if not path.lower().endswith(".py"):
        return _no_comments(path, body)
    import ast
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return body
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docs.add(d)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value not in docs:
            out.append(node.value)
    return "\n".join(out)


def test_no_false_promise_about_internet():
    """Есть самообновление - значит «без интернета» писать нельзя НИГДЕ, что видит человек."""
    has_update = os.path.isfile(os.path.join(_package_dir(), "app_update.py"))
    files = visible_text_files()
    assert len(files) >= 5, f"проверять нечего - нашлось файлов: {len(files)}"
    if not has_update:
        print(f"проверено файлов: {len(files)} (самообновления нет - обещание «без интернета» допустимо)")
        return
    bad = []
    for path in files:
        low = visible_strings(path).lower()
        for phrase in LIE_ABOUT_NET:
            if phrase in low:
                bad.append(f"{os.path.relpath(path, ROOT)}: «{phrase}»")
    assert not bad, ("у программы есть самообновление - эти обещания про сеть неправда: " + "; ".join(bad))
    print(f"проверено файлов: {len(files)}, ложных обещаний про сеть нет")


OFFLINE_WORD = re.compile(r"(?<![\w-])(офлайн|оффлайн)(?![\w-])", re.I)


def test_word_offline_alone_is_not_used_as_a_promise():
    """Отдельное слово «офлайн» - тоже обещание про сеть, хотя его не было в списке примет.

    Приёмка 18.10.2026: в шапке окна «Проверки формул Excel» стояло «Офлайн - файлы не покидают
    компьютер», а программа раз в неделю спрашивает про новую версию. Сторож ловил только «работает
    офлайн» и это место пропускал. Название с дефисом («Офлайн-транскрибатор», «офлайн-диктовка») -
    имя продукта, а не обещание: оно разрешено."""
    has_update = os.path.isfile(os.path.join(_package_dir(), "app_update.py"))
    files = visible_text_files()
    assert len(files) >= 5, f"проверять нечего - нашлось файлов: {len(files)}"
    if not has_update:
        print(f"проверено файлов: {len(files)} (самообновления нет - слово «офлайн» допустимо)")
        return
    bad = []
    for path in files:
        for m in OFFLINE_WORD.finditer(visible_strings(path)):
            bad.append(f"{os.path.relpath(path, ROOT)}: «{m.group(0)}»")
    assert not bad, ("у программы есть самообновление - отдельное слово «офлайн» обещает лишнее: "
                     + "; ".join(bad) + ". Название с дефисом («Офлайн-транскрибатор») можно, "
                     "отдельное слово - нет")
    print(f"проверено файлов: {len(files)}, отдельного слова «офлайн» в видимых текстах нет")


def test_licenses_notice_tells_the_truth_about_network():
    """Первая строка перечня лицензий - про сеть ИМЕННО ЭТОЙ программы (её пишет _brand/tools/make_licenses.py)."""
    text = _notice_text()
    has_update = os.path.isfile(os.path.join(_package_dir(), "app_update.py"))
    if has_update:
        assert "проверить, не вышла ли новая версия" in text, \
            "в перечне лицензий не сказано, что программа ходит в сеть за новой версией"
        assert "без интернета" not in text.lower(), "в перечне лицензий осталось старое «без интернета»"
    assert "никуда не уходят" in text or "никуда ничего не отправляет" in text


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([os.path.abspath(__file__), "-q"]))
