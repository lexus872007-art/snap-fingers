"""Самообновление «Щелчка» (владелец 16-17.10.2026: «программа сама следит за новыми обновлениями и если они
есть, то предложит их установить»). По риску - отдельная проверка.

Сам механизм один на всю линейку и проверяется в ~/office_tools/_brand/tests/test_app_update.py. Здесь - что
ИМЕННО ЭТА программа подключена правильно: свой адрес на сервере, своё имя установщика, свои настройки,
галочка «Проверять обновления» и кнопка «Проверить сейчас» в окне, строка в журнал.
"""
import hashlib
import io
import json
import os
import subprocess

import pytest

from shchelchok import settings as St, update as U

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLUG = "shchelchok"
SETUP = "Shchelchok-Setup.exe"


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeNet:
    """Сеть вместо настоящей: отдаёт, что положили, или бросает, как при обрыве."""

    def __init__(self, payload=None, boom=None, data=b""):
        self.payload, self.boom, self.data = payload, boom, data
        self.calls = []

    def open(self, url, headers=None, timeout=30, **kw):
        self.calls.append(url)
        if self.boom:
            raise self.boom
        if url.endswith("latest.json"):
            return _Resp(json.dumps(self.payload).encode("utf-8"))
        return _Resp(self.data)


def mk(settings=None, version="1.4.1", net=None, clock=None, log=None):
    s = St.load("/nonexistent/s.json")
    s.update(settings or {})
    lines = [] if log is None else log
    u = U.make(version, s, log=lines.append if log is None else log, net=net or FakeNet(),
               clock=clock or (lambda: 1_700_000_000.0))
    return u, s, lines


# ---------------------------------------------------------------- свой адрес
def test_address_and_setup_name_are_this_program():
    assert U.BASE == f"https://ty-biznesmen.ru/apps/{SLUG}"
    assert U.SETUP == SETUP
    u, s, _ = mk(net=FakeNet({"version": "9.9.9"}))
    u.fetch()
    assert u.net.calls == [f"https://ty-biznesmen.ru/apps/{SLUG}/latest.json"]
    assert u.setup_name({}) == SETUP


def test_setup_name_from_server_is_only_a_file_name():
    assert U.parse_info({"version": "1.0.0", "setup": "../../evil.exe"})["setup"] == "evil.exe"
    assert U.parse_info({"version": "1.0.0", "setup": "C:\\x\\y.exe"})["setup"] == SETUP


# ---------------------------------------------------------------- настройки
def test_settings_have_update_keys_with_safe_defaults():
    s = St.load("/nonexistent/s.json")
    assert s["updates"] is True and s["update_auto"] is False
    assert s["update_last"] == 0.0 and s["update_later"] == "" and s["update_failed"] is False


def test_broken_update_settings_are_healed(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"updates": "ага", "update_last": "вчера", "update_later": 5}), encoding="utf-8")
    d = St.load(str(p))
    assert d["updates"] is True and d["update_last"] == 0.0 and d["update_later"] == ""


def test_update_settings_survive_restart(tmp_path):
    p = tmp_path / "s.json"
    d = St.load(str(p))
    d["updates"] = False
    d["update_later"] = "9.9.9"
    d["update_last"] = 123.5
    St.save(d, str(p))
    again = St.load(str(p))
    assert again["updates"] is False and again["update_later"] == "9.9.9" and again["update_last"] == 123.5


# ---------------------------------------------------------------- в сеть ходим по правилам
def test_switch_off_means_no_network_at_all():
    net = FakeNet({"version": "9.9.9"})
    u, s, _ = mk({"updates": False, "update_last": 0}, net=net)
    assert u.due() is False and net.calls == []


def test_check_once_a_week_and_after_failure_next_day():
    now = [1_700_000_000.0]
    u, s, _ = mk({"update_last": now[0]}, clock=lambda: now[0])
    assert u.due() is False
    now[0] += 6 * 24 * 3600
    assert u.due() is False
    now[0] += 2 * 24 * 3600
    assert u.due() is True
    s["update_last"], s["update_failed"] = now[0], True
    now[0] += 25 * 3600
    assert u.due() is True


def test_same_version_is_silent_but_logged():
    lines = []
    u, s, _ = mk(net=FakeNet({"version": "1.4.1"}), log=lines.append)
    assert u.fetch() is None
    assert any("обновлять нечего" in x for x in lines)


def test_newer_version_is_offered():
    u, s, _ = mk(net=FakeNet({"version": "9.9.9", "notes": "стало лучше"}))
    info = u.fetch()
    assert info["version"] == "9.9.9" and info["notes"] == "стало лучше"


def test_server_down_is_not_an_error_for_the_person():
    lines = []
    u, s, _ = mk(net=FakeNet(boom=OSError("сети нет")), log=lines.append)
    assert u.fetch() is None and s["update_failed"] is True
    assert any("сервер не ответил" in x for x in lines)


@pytest.mark.parametrize("payload", [{"нет": "версии"}, {"version": "ой"}, {"version": [9]}, "мусор", None])
def test_broken_answer_is_ignored(payload):
    lines = []
    u, s, _ = mk(net=FakeNet(payload), log=lines.append)
    assert u.fetch() is None and s["update_failed"] is True


# ---------------------------------------------------------------- скачивание
def test_no_checksum_means_no_update(tmp_path):
    lines = []
    u, s, _ = mk(net=FakeNet({"version": "9.9.9"}, data=b"x" * 100), log=lines.append)
    assert u.download({"version": "9.9.9", "setup_size": 100}, lambda st: None, folder=str(tmp_path)) is None
    assert any("не прислал контрольную сумму" in x for x in lines)
    assert not os.listdir(tmp_path)


def test_wrong_checksum_removes_the_file(tmp_path):
    lines = []
    data = b"\x00" * 4096
    u, s, _ = mk(net=FakeNet({"version": "9.9.9"}, data=data), log=lines.append)
    info = {"version": "9.9.9", "setup_size": len(data), "setup_sha256": "0" * 64}
    assert u.download(info, lambda st: None, folder=str(tmp_path)) is None
    assert any("ОТМЕНЕНО" in x for x in lines) and not os.listdir(tmp_path)


def test_good_checksum_keeps_the_file(tmp_path):
    data = b"\x01" * 8192
    good = hashlib.sha256(data).hexdigest()
    u, s, _ = mk(net=FakeNet({"version": "9.9.9"}, data=data))
    info = {"version": "9.9.9", "setup_size": len(data), "setup_sha256": good}
    path = u.download(info, lambda st: None, folder=str(tmp_path))
    assert path and U.sha256(path) == good


def test_download_shows_megabytes_and_speed(tmp_path):
    data = b"\x02" * (1 << 18)
    seen = []
    u, s, _ = mk(net=FakeNet({"version": "9.9.9"}, data=data))
    u.download({"version": "9.9.9", "setup_size": len(data), "setup_sha256": hashlib.sha256(data).hexdigest()},
               lambda st: seen.append(st.line), folder=str(tmp_path))
    assert seen and "МБ" in " ".join(seen)


def test_later_means_a_week_of_silence():
    now = [1_700_000_000.0]
    u, s, _ = mk(clock=lambda: now[0])
    s["update_later"], s["update_asked"] = "9.9.9", now[0]
    assert u.ask_due("9.9.9") is False
    now[0] += 8 * 24 * 3600
    assert u.ask_due("9.9.9") is True
    assert u.ask_due("9.9.8") is True


# ---------------------------------------------------------------- видно человеку
def test_window_has_checkbox_and_button():
    """Галочка «Проверять обновления» и кнопка «Проверить сейчас» - в окне программы."""
    src = open(os.path.join(ROOT, "shchelchok", "main_win.py"), encoding="utf-8").read()
    assert "Проверять обновления" in src and "Проверить сейчас" in src


def test_update_window_texts():
    src = open(os.path.join(ROOT, "shchelchok", "app_update_qt.py"), encoding="utf-8").read()
    for text in ("Вышла версия", "Что нового", "Обновить", "Позже", "Ставить обновления сразу, не спрашивая"):
        assert text in src, text


def test_no_forbidden_word_in_update_code():
    """Слово из трёх букв латиницей - нигде в текстах программы (правило владельца)."""
    word = "v" + "pn"
    for name in ("update.py", "app_update.py", "app_update_qt.py"):
        assert word not in open(os.path.join(ROOT, "shchelchok", name), encoding="utf-8").read().lower()


def test_check_goes_to_the_journal():
    """Каждая проверка - строкой в журнал программы, иначе о проблемах никто не узнает."""
    from shchelchok import journal
    import shutil
    import tempfile
    d = tempfile.mkdtemp(prefix="shch_journal_")        # за собой убираем: тесты тоже не мусорят в /tmp
    p = os.path.join(d, "log.txt")
    journal.set_path(p)
    try:
        u, s, _ = mk(net=FakeNet({"version": "1.4.1"}), log=journal.write)
        u.fetch()
        assert "обновлять нечего" in open(p, encoding="utf-8").read()
    finally:
        journal.set_path(None)
        shutil.rmtree(d, ignore_errors=True)


def test_copies_match_brand():
    """Общие модули в программе - свежие копии _brand (иначе правка механизма до программы не доедет)."""
    brand = os.path.join(os.path.dirname(ROOT), "_brand")
    if not os.path.isdir(brand):
        pytest.skip("_brand рядом нет (сервер сборки)")
    r = subprocess.run(["python3", os.path.join(brand, "sync.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
