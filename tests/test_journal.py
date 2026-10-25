# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Журнал самой программы - в общем месте линейки (долг 11, решение владельца 17.10.2026).

На каждый риск - своя проверка: место файла, одинаковые APP/TITLE с установщиком, одна запись - одна строка,
строка про переезд (один раз, и даже если установщик уже писал в эту папку), прежний файл не тронут, журнал
программы и журнал установщика - разные файлы в одной папке, кнопка «Показать журнал» рядом с прежним окном
«Журнал», путь к журналу в окне неудавшегося обновления, настройки человека от всего этого не меняются.
"""
import datetime
import os
import re
import types

from PySide6.QtWidgets import QPushButton

from shchelchok import app_log, journal
from shchelchok import settings as St

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = f"{datetime.date.today():%Y-%m-%d}"


def loader_src():
    with open(os.path.join(ROOT, "loader", "loader.py"), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- место журнала
def test_journal_lives_in_localappdata_logs(tmp_path):
    """Файл дня - %LOCALAPPDATA%\\Щелчок\\logs\\shchelchok-ГГГГ-ММ-ДД.log.

    Не %TEMP% (его чистит Windows) и не папка программы (её целиком заменяет обновление)."""
    journal.set_path(None)
    p = journal.path()
    assert p == os.path.join(str(tmp_path), "Щелчок", "logs", f"shchelchok-{TODAY}.log"), p
    assert os.path.isdir(os.path.dirname(p)), "папка журналов создаётся сама"


def test_app_and_title_are_the_same_as_in_the_installer():
    """APP и TITLE взяты из loader.py: иначе программа и установщик писали бы в РАЗНЫЕ папки."""
    src = loader_src()
    assert re.search(r'^APP = "%s"$' % re.escape(St.APP), src, re.M), St.APP
    assert re.search(r'^TITLE = "%s"$' % re.escape(St.TITLE), src, re.M), St.TITLE
    assert journal.LOG.app == St.APP and journal.LOG.title == St.TITLE
    assert journal.LOG.kind == "", "журнал ПРОГРАММЫ (у установщика kind=install)"


def test_program_and_installer_keep_separate_files_in_one_folder():
    """Один разбор - одна папка, но файлы разные: видно, кто что писал."""
    journal.set_path(None)
    journal.write("это программа")
    setup = app_log.Log(St.APP, St.TITLE, kind="install")
    setup("это установщик")
    mine, theirs = journal.path(), setup.path
    assert os.path.dirname(mine) == os.path.dirname(theirs), "папка одна"
    assert mine != theirs, "файлы разные"
    assert "это установщик" not in open(mine, encoding="utf-8").read()
    assert "это программа" not in open(theirs, encoding="utf-8").read()


# ---------------------------------------------------------------- как пишем
def test_one_record_is_one_line():
    """Журнал читают глазами и обычным поиском: каждая запись - одна строка со временем."""
    journal.set_path(None)
    journal.write("первая")
    journal.write("вторая\nсо переносом строки\r и возвратом")
    journal.write("третья")
    lines = [s for s in open(journal.path(), encoding="utf-8").read().splitlines() if s]
    assert len(lines) == 3, lines
    for s in lines:
        assert re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ", s), s
    assert "со переносом строки" in lines[1] and "и возвратом" in lines[1]


def test_tail_reads_the_new_journal(qapp):
    """Окно «Что происходило» и отчёты читают тот же файл - хвостом, не целиком."""
    journal.set_path(None)
    for i in range(5):
        journal.write(f"строка {i}")
    got = journal.tail(3)
    assert len(got) == 3 and "строка 4" in got[-1], got


def test_audio_and_windows_lines_go_to_the_new_journal(qapp, tmp_path):
    """Прежний писатель заменён, а его вызовы - те же: `journal.write` из сторожа микрофона и окон."""
    journal.set_path(None)
    journal.write("микрофон открыт: «Набор микрофонов»")
    journal.write("свернул окна: 3")
    text = open(journal.path(), encoding="utf-8").read()
    assert "микрофон открыт" in text and "свернул окна: 3" in text


# ---------------------------------------------------------------- переезд
def test_move_line_is_written_once_and_names_the_old_file(tmp_path, monkeypatch):
    """Первая строка нового журнала: где лежал прежний и что записи из него не переносили. Один раз."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    journal.set_path(None)
    old = journal.old_path()
    assert journal.note_move() is True
    first = open(journal.path(), encoding="utf-8").read().splitlines()[0]
    assert "журнал программы теперь здесь" in first
    assert old in first and "не переносил" in first, first
    assert journal.note_move() is False, "второй раз про переезд не пишем"
    assert open(journal.path(), encoding="utf-8").read().count("теперь здесь") == 1


def test_move_line_appears_even_if_the_installer_already_wrote_here():
    """Установщик пишет в эту папку ВСЕГДА раньше программы - и не должен прятать строку про переезд.

    Прежде общий `app_log.note_move` считал его файлы нашими (имя начинается так же) и молчал - строку про
    переезд не увидел бы никто. Правка `_brand/app_log.py` 18.10.2026: `note_move` смотрит только файлы
    своего kind. Этот тест - сторож на случай, если разделение по kind снова потеряется."""
    journal.set_path(None)
    app_log.Log(St.APP, St.TITLE, kind="install")("установщик уже писал сюда")
    assert journal.note_move() is True
    assert "теперь здесь" in open(journal.path(), encoding="utf-8").read()


def test_old_journal_is_left_where_it_was(tmp_path, monkeypatch):
    """Прежний файл не переносим и не удаляем: человек может в него заглянуть."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    journal.set_path(None)
    old = journal.old_path()
    os.makedirs(os.path.dirname(old), exist_ok=True)
    with open(old, "w", encoding="utf-8") as f:
        f.write("старая запись\n")
    journal.note_move()
    journal.write("новая запись")
    assert open(old, encoding="utf-8").read() == "старая запись\n", "прежний журнал не тронут"
    assert "старая запись" not in open(journal.path(), encoding="utf-8").read(), "записи не переносим"


def test_move_line_comes_before_the_first_record(tmp_path, monkeypatch):
    """При запуске программы строка про переезд идёт ПЕРЕД строкой «запуск: версия …»."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    journal.set_path(None)
    journal.note_move()
    journal.write("запуск: версия 1.4.5, возврат окон - один щелчок")
    lines = open(journal.path(), encoding="utf-8").read().splitlines()
    assert "журнал программы теперь здесь" in lines[0], lines
    assert "запуск: версия" in lines[1], lines


def test_controller_notes_the_move_before_writing_the_start_line():
    """Сторож порядка в самой программе: `note_move` зовётся раньше строки «запуск»."""
    src = open(os.path.join(ROOT, "shchelchok", "app.py"), encoding="utf-8").read()
    assert src.index("journal.note_move()") < src.index('journal.write(f"запуск'), "переезд отмечаем первым"


# ---------------------------------------------------------------- кнопка в окне
def test_window_has_both_the_journal_and_show_journal_buttons(qapp, tmp_path, monkeypatch):
    """Окно «Журнал» (блокнот) осталось, рядом - «Показать журнал» (папка журналов)."""
    from test_app import make_ctl
    called = []
    monkeypatch.setattr(app_log, "show", lambda p: called.append(p) or True)
    ctl, _api = make_ctl(qapp, tmp_path)
    ctl.open_main()
    w = ctl.main
    names = [b.text() for b in w.findChildren(QPushButton)]
    assert "Журнал" in names and "Показать журнал" in names, names
    w.show_log_b.click()
    assert called == [journal.path()], called
    assert "открыл папку с журналом" in "\n".join(journal.tail(5))


def test_journal_does_not_touch_user_settings(qapp, tmp_path):
    """Чек-лист п. 11: от переезда журнала настройки человека (порог, калибровка) не меняются."""
    from test_app import make_ctl
    ctl, _api = make_ctl(qapp, tmp_path)
    before = dict(ctl.settings)
    journal.set_path(None)
    journal.note_move()
    journal.write("что-то случилось")
    ctl.show_journal()
    assert dict(ctl.settings) == before
    assert not os.path.exists(os.path.join(St.config_dir(), "logs")), "журнал не лезет к настройкам"


# ---------------------------------------------------------------- окно обновления
def test_update_failure_tells_where_the_journal_is(qapp):
    """«Обновиться не вышло» - окно говорит коротко, а путь к журналу показывает: его и просим прислать."""
    from shchelchok.app import UpdateWindow
    upd = types.SimpleNamespace(u=types.SimpleNamespace(s={}), set_auto=lambda on: None,
                                later=lambda info: None, download=lambda *a: None, cancel=lambda: None)
    w = UpdateWindow(upd, {"version": "1.4.6", "notes": "мелкие правки"}, title=St.TITLE)
    try:
        w.finished(False, "Связаться с сервером не удалось.")
        assert journal.path() in w.state.text(), w.state.text()
        assert "\n" not in w.state.text(), "в одну строку: перенос в этой надписи не нужен"
        w.finished(True, "Готово.")
        assert journal.path() not in w.state.text(), "при успехе про журнал не говорим"
    finally:
        w.close()
        w.deleteLater()
