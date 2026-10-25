"""Окна, запущенные ОТ ИМЕНИ АДМИНИСТРАТОРА (жалоба владельца 16.10.2026: «командную строку не поднимает»).

Windows не даёт обычной программе управлять окнами программ с повышенными правами (разделение уровней
целостности, UIPI): ShowWindowAsync/SetForegroundWindow для такого окна молча ничего не делают. Значит, такие
окна надо: узнавать ЗАРАНЕЕ, честно говорить о них человеку и дать рабочий выход (запуск с правами).
По риску - отдельная проверка.
"""
import types

import pytest

from shchelchok import events, winapi
from shchelchok.hider import Hider
from test_hider import FakeAPI


class RightsAPI(FakeAPI):
    """Как Windows: окно «от администратора» наши команды игнорирует, а проводник его сворачивает."""

    def __init__(self, wins, admin=(), titles=None, shell_works=True):
        super().__init__(wins, stubborn=set(admin))
        self.admin = set(admin)
        self.titles = titles or {}
        self.shell_works = shell_works

    def window_rights(self, h):
        return winapi.ADMIN if h in self.admin else winapi.OURS

    def window_title(self, h):
        return self.titles.get(h, f"Окно {h}")

    def restore(self, h):
        self.log.append(("restore", h))
        if h not in self.admin:                  # UIPI: команда уходит в пустоту
            self.state[h] = "shown"

    def shell_minimize_all(self, undo=False):
        if not self.shell_works:
            self.shell.append(undo)
            return False
        return super().shell_minimize_all(undo)


# ---------------------------------------------------------------- узнать заранее
def test_admin_window_is_detected_before_minimizing():
    """Окно «от администратора» узнаём ДО сворачивания и не делаем вид, что сворачиваем его сами."""
    api = RightsAPI([1, 2, 3], admin={2})
    h = Hider(api)
    assert h.hide() == 3
    assert h.admin == {2}
    assert ("min", 2) not in api.log, "команда окну «от администратора» - впустую, её не посылаем"
    assert api.shell == [False], "его сворачивает проводник, и зовём его сразу, а не через 0,25 с"
    assert api.state[2] == "min"


def test_admin_window_not_counted_as_restored():
    """Главное: «вернул все окна» не должно быть неправдой - такое окно остаётся свёрнутым, и это видно."""
    api = RightsAPI([1, 2], admin={2})
    h = Hider(api)
    h.hide()
    h.restore()
    assert api.state[1] == "shown" and api.state[2] == "min"
    # в «не вернулось» окна «от администратора» не попадают: про них сказано своей строкой, а доворачивать их
    # бесполезно - именно из-за этого в журнале владельца 16.10.2026 было 11 строк «вернулись только со
    # второго раза», все про одно и то же окно командной строки
    assert h.not_restored() == []
    assert h.not_restored(with_admin=True) == [2]
    assert [t for _, t in h.admin_windows([2])] == ["Окно 2"]
    assert h.restore_verify() == 0, "доворачивать окно от администратора бесполезно"


def test_nothing_is_called_not_restored_right_after_a_new_hide():
    """Журнал владельца 16.10.2026: «свернул окна: 3» и сразу «не вернулось: 3 окна осталось свёрнутым» -
    проверка возврата сработала уже ПОСЛЕ нового сворачивания и приняла свёрнутое за «не вернулось»."""
    api = RightsAPI([1, 2, 3])
    h = Hider(api)
    h.hide()
    h.restore()
    assert h.not_restored() == []
    h.hide()                                   # человек щёлкнул ещё раз - окна свёрнуты нарочно
    assert h.not_restored() == [], "свёрнутые нарочно окна - не «не вернулись»"


def test_admin_window_that_stays_on_screen_is_visible_to_program():
    """Проводника нет (панель задач не ответила) - окно так и осталось на экране: программа это знает."""
    api = RightsAPI([1, 2], admin={2}, shell_works=False)
    h = Hider(api)
    h.hide()
    assert h.verify() == 1
    assert h.not_hidden() == [2] and api.state[2] == "shown"


def test_ordinary_windows_are_not_called_admin():
    api = RightsAPI([1, 2, 3])
    h = Hider(api)
    h.hide()
    assert h.admin == set() and api.shell == [] and h.not_restored() == []


def test_hider_works_with_api_without_rights_check():
    """Старый api без window_rights (тесты, Linux) - считаем окна обычными, ничего не падает."""
    api = FakeAPI([1, 2])
    h = Hider(api)
    assert h.hide() == 2 and h.admin == set()
    assert h.rights(1) == "ours" and h.title(1) == ""


# ---------------------------------------------------------------- слова человеку
def test_admin_line_names_the_window_and_the_way_out():
    t = events.admin_line(["Командная строка"])
    assert t.startswith("окно «Командная строка» запущено от имени администратора - свернуть/вернуть его без "
                        "прав нельзя")
    assert "Запускать с правами администратора" in t
    assert events.admin_line([]) == ""


def test_admin_line_for_several_windows():
    t = events.admin_line(["Командная строка", "Диспетчер задач"], fix=False)
    assert t.startswith("2 окна запущены от имени администратора")
    assert "«Командная строка»" in t and "Запускать" not in t


def test_journal_and_window_say_the_same_about_admin_window(qapp, tmp_path):
    """Одна и та же строка - в журнал и в раздел «Что происходило» (чтобы человек видел это в окне)."""
    from shchelchok import journal
    from test_app import make_ctl
    ctl, _ = make_ctl(qapp, tmp_path)
    api = RightsAPI([21, 22], admin={22}, titles={22: "Командная строка"})
    ctl.hider.api = api
    ctl.toggle_windows()                      # свернуть
    ctl.verify_hidden()
    ctl.toggle_windows()                      # вернуть
    ctl.restore_final()
    text = "\n".join(journal.tail(40))
    assert "«Командная строка» запущено от имени администратора" in text
    assert "вернул окна: 1, а 1 окно от имени администратора без прав не вернуть" in text, \
        "число в журнале обязано быть честным"
    assert any("Командная строка" in s for _, s in ctl.log.items)
    assert "Командная строка" in ctl.admin_note()
    ctl.listener.shutdown()


def test_admin_note_disappears_when_we_have_rights(qapp, tmp_path, monkeypatch):
    """Программа работает с правами - про окна «от администратора» больше не предупреждаем."""
    from test_app import make_ctl
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.admin_seen = [(1, "Командная строка")]
    assert ctl.admin_note()
    monkeypatch.setattr(winapi, "is_elevated", lambda: True)
    assert ctl.admin_note() == ""
    ctl.listener.shutdown()


def test_window_shows_admin_warning_and_restart_button(qapp, tmp_path):
    from test_app import make_ctl
    ctl, _ = make_ctl(qapp, tmp_path, admin=True)
    ctl.open_main()
    w = ctl.main
    ctl.admin_seen = [(1, "Командная строка")]
    w.refresh()
    assert w.admin_b.isVisible(), "кнопки «Нужны права - перезапустить» нет"
    assert "администратора" in w.admin_b.toolTip()
    ctl.settings["admin"] = False          # права не включены - тогда видно строку-предупреждение
    w.refresh()
    assert w.admin_l.isVisible() and "администратора" in w.admin_l.text()
    w.close()
    ctl.listener.shutdown()


# ---------------------------------------------------------------- как узнаём права
@pytest.mark.parametrize("lvl,why,expect", [
    (0x3000, "", "admin"),              # высокий уровень при нашем обычном - окно нам не подчинится
    (0x2000, "", "ours"),               # тот же уровень - обычное окно
    (0x1000, "", "ours"),               # ниже нашего - тоже наше
    (None, winapi.ABOVE_US, "admin"),   # токен не открылся (отказ в доступе) - права выше наших
    (None, "процесса нет", "unknown"),
])
def test_window_rights_by_integrity_level(monkeypatch, lvl, why, expect):
    """Решение «наше окно / от администратора» принимается по уровню целостности процесса окна."""
    monkeypatch.setattr(winapi, "WIN", True)
    monkeypatch.setattr(winapi, "_pid", lambda h: 4321)
    monkeypatch.setattr(winapi, "process_level", lambda pid: (lvl, why))
    monkeypatch.setattr(winapi, "own_level", lambda: 0x2000)
    monkeypatch.setattr(winapi, "wt", types.SimpleNamespace(HWND=lambda h: h), raising=False)
    winapi._rights_cache.clear()
    assert winapi.window_rights(123) == expect


def test_window_rights_survives_broken_winapi(monkeypatch):
    monkeypatch.setattr(winapi, "WIN", True)
    monkeypatch.setattr(winapi, "_pid", lambda h: (_ for _ in ()).throw(OSError("нет окна")))
    monkeypatch.setattr(winapi, "wt", types.SimpleNamespace(HWND=lambda h: h), raising=False)
    winapi._rights_cache.clear()
    assert winapi.window_rights(5) == "unknown"


def test_window_rights_are_remembered_per_process(monkeypatch):
    """При 20 окнах права спрашиваются 20 раз на каждый щелчок - ответ помним по процессу (владелец щёлкает
    подряд, сворачивание должно оставаться мгновенным)."""
    calls = []
    monkeypatch.setattr(winapi, "WIN", True)
    monkeypatch.setattr(winapi, "_pid", lambda h: 777)
    monkeypatch.setattr(winapi, "own_level", lambda: 0x2000)
    monkeypatch.setattr(winapi, "wt", types.SimpleNamespace(HWND=lambda h: h), raising=False)
    monkeypatch.setattr(winapi, "process_level", lambda pid: (calls.append(pid), (0x2000, ""))[1])
    winapi._rights_cache.clear()
    assert [winapi.window_rights(i) for i in range(20)] == ["ours"] * 20
    assert len(calls) == 1, "спросили Windows один раз на процесс"


# ---------------------------------------------------------------- одна копия при разных правах
def test_mutex_access_denied_means_already_running():
    """Первая копия с правами администратора: её мьютекс обычной программе не открыть (отказ 5) - это «уже
    открыта», а не «можно запустить вторую»."""
    assert winapi.mutex_result(0) is True
    assert winapi.mutex_result(183) is False, "мьютекс уже есть"
    assert winapi.mutex_result(winapi.ERR_ACCESS_DENIED) is False, "есть, но с правами администратора"


def test_second_copy_asks_first_to_show_window(qapp, tmp_path, monkeypatch):
    """Окно-сервер между разными правами Windows не пускает - вторая копия просит показать окно файлом-флажком."""
    from shchelchok import app as appmod, settings
    monkeypatch.setattr(settings, "config_dir", lambda: str(tmp_path))
    from test_app import make_ctl
    ctl, _ = make_ctl(qapp, tmp_path)
    assert ctl.check_show_flag() is False
    assert appmod.ask_show() is True
    assert ctl.check_show_flag() is True
    assert ctl.main is not None and ctl.main.isVisible()
    assert ctl.check_show_flag() is False, "флажок убран - окно второй раз не открываем"
    ctl.main.close()
    ctl.listener.shutdown()


# ---------------------------------------------------------------- рабочий выход: запуск с правами
def test_admin_task_asks_for_highest_rights_at_logon():
    """Задание планировщика: при входе в систему, с наивысшими правами, с нашим exe и --autostart."""
    import xml.etree.ElementTree as ET
    xml = winapi.task_xml(r"C:\Users\u\AppData\Local\Щелчок\Shchelchok.exe", "--autostart", user="PC\\u")
    root = ET.fromstring(xml.split("?>", 1)[1])
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.find(".//t:RunLevel", ns).text == "HighestAvailable"
    assert root.find(".//t:LogonTrigger/t:UserId", ns).text == "PC\\u"
    assert root.find(".//t:Exec/t:Command", ns).text.endswith("Shchelchok.exe")
    assert root.find(".//t:Exec/t:Arguments", ns).text == "--autostart"
    assert 'encoding="UTF-16"' in xml, "schtasks /XML читает файл в UTF-16"


def test_admin_task_xml_escapes_path():
    xml = winapi.task_xml("C:\\a&b\\x.exe", "--autostart", user="PC\\u")
    assert "a&amp;b" in xml and "a&b" not in xml


def test_turning_admin_on_replaces_plain_autostart(qapp, tmp_path, monkeypatch):
    """Автозапуск ярлыком + задание планировщика = две копии. Включили права - ярлык автозапуска убираем."""
    from test_app import make_ctl
    ctl, _ = make_ctl(qapp, tmp_path, autostart=True)
    calls = []
    monkeypatch.setattr(winapi, "WIN", True)
    monkeypatch.setattr(winapi, "autostart_set", lambda name, on, exe=None: calls.append(("run", bool(on))))
    monkeypatch.setattr(winapi, "admin_task_create", lambda exe=None: calls.append(("task", True)) or True)
    monkeypatch.setattr(winapi, "admin_task_delete", lambda: calls.append(("task", False)) or True)
    ctl.demo = False
    ctl.set_admin(True)
    assert ("run", False) in calls and ("task", True) in calls
    calls.clear()
    ctl.set_admin(False)
    assert ("task", False) in calls and ("run", True) in calls, "выключили права - автозапуск вернулся как был"
    ctl.listener.shutdown()


def test_window_does_not_run_schtasks_on_every_tick(qapp, tmp_path, monkeypatch):
    """Строку про права рисует таймер окна (30 мс). Запускать из него schtasks.exe нельзя - это десятки
    процессов в секунду на настоящей Windows."""
    from test_app import make_ctl
    calls = []
    monkeypatch.setattr(winapi, "admin_task_exists", lambda name=None: calls.append(1) or True)
    ctl, _ = make_ctl(qapp, tmp_path, admin=True)
    ctl.open_main()
    for _ in range(20):
        ctl.main.refresh()
    assert calls == [], "задание планировщика спрашивали по таймеру окна"
    ctl.demo = False
    assert ctl.admin_task_ok() is True and len(calls) == 1, "по делу - спрашиваем"
    ctl.main.close()
    ctl.listener.shutdown()


def test_elevation_is_asked_once(monkeypatch):
    """Свои права не меняются, пока программа работает - спрашиваем Windows один раз."""
    calls = []
    monkeypatch.setattr(winapi, "WIN", True)
    monkeypatch.setattr(winapi, "_is_elevated_now", lambda: calls.append(1) or False)
    winapi._elev.clear()
    assert [winapi.is_elevated() for _ in range(5)] == [False] * 5
    assert len(calls) == 1
    winapi._elev.clear()
