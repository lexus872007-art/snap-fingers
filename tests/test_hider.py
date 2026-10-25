"""Свернуть и вернуть окна: свой список, порядок, фокус, досворачивание проводником, закрытые/развёрнутые окна,
чужие свёрнутые окна (баг владельца 15.10.2026 - «иногда показывает другие папки»)."""
from shchelchok.hider import Hider


class FakeAPI:
    def __init__(self, wins, stubborn=(), premin=()):
        self.wins = list(wins)            # сверху вниз
        self.state = {h: "shown" for h in wins}
        for h in premin:                  # пользователь свернул сам ДО щелчка
            self.state[h] = "min"
        self.stubborn = set(stubborn)     # «от администратора» - не сворачиваются нами
        self.log = []
        self.fg = next((h for h in wins if self.state[h] == "shown"), 0)
        self.shell = []

    def app_windows(self):
        return [h for h in self.wins if self.state.get(h) == "shown"]

    def minimized_windows(self):
        return [h for h in self.wins if self.state.get(h) == "min"]

    def foreground(self):
        return self.fg

    def minimize(self, h):
        self.log.append(("min", h))
        if h not in self.stubborn:
            self.state[h] = "min"

    def restore(self, h):
        self.log.append(("restore", h))
        self.state[h] = "shown"

    def window_alive(self, h):
        return h in self.state

    def is_minimized(self, h):
        return self.state.get(h) == "min"

    def is_shown(self, h):
        return self.state.get(h) == "shown"

    def shell_minimize_all(self, undo=False):
        """Как проводник: «свернуть все» сворачивает всё открытое, «отменить» (416) разворачивает ВСЁ свёрнутое -
        включая окна, которые пользователь свернул сам (из-за этого её и не зовём)."""
        self.shell.append(undo)
        for h in self.state:
            if undo and self.state[h] == "min":
                self.state[h] = "shown"
            elif not undo and self.state[h] == "shown":
                self.state[h] = "min"
        return True

    def bring_to_front(self, h):
        self.log.append(("front", h))
        return True


def test_hide_minimizes_bottom_up_and_remembers():
    api = FakeAPI([1, 2, 3])
    h = Hider(api)
    assert h.hide() == 3
    assert api.log == [("min", 3), ("min", 2), ("min", 1)]
    assert h.hidden and h.fg == 1


def test_restore_bottom_up_and_focus():
    api = FakeAPI([1, 2, 3])
    api.fg = 2
    h = Hider(api)
    h.hide()
    api.log.clear()
    assert h.restore() == 3
    # снизу вверх, каждому окну команда дважды (ShowWindowAsync не мгновенный), фокус - прежнему окну последним
    assert api.log == [("restore", 3), ("restore", 2), ("restore", 1),
                       ("restore", 3), ("restore", 2), ("restore", 1), ("front", 2)]
    assert not h.hidden


def test_closed_and_manually_restored_windows_skipped():
    api = FakeAPI([1, 2, 3])
    h = Hider(api)
    h.hide()
    del api.state[2]                 # закрыли
    api.state[3] = "shown"           # развернули вручную
    api.log.clear()
    assert h.restore() == 1
    assert ("restore", 1) in api.log and ("restore", 3) not in api.log


def test_stubborn_window_shell_fallback():
    api = FakeAPI([1, 2], stubborn={1})
    h = Hider(api)
    h.hide()
    assert h.verify() == 1 and api.shell == [False]      # досворачивает проводник
    assert api.state[1] == "min"
    h.restore()
    # возврат - поимённо, «отменить свернуть все» (416) НЕ зовём
    assert api.shell == [False] and api.state[1] == "shown" and api.state[2] == "shown"


def test_windows_minimized_by_user_stay_minimized():
    """Баг владельца 15.10.2026: при возврате всплывали папки, которые он свернул сам до щелчка."""
    api = FakeAPI([1, 2, 3, 4], stubborn={3}, premin=(1, 2))
    h = Hider(api)
    assert h.hide() == 2 and h.saved == [3, 4] and h.before == [1, 2]
    assert h.verify() == 1 and api.shell == [False]      # окно 3 «от администратора» - через проводника
    assert all(api.state[x] == "min" for x in (1, 2, 3, 4))
    assert h.restore() == 2
    assert api.state[1] == "min" and api.state[2] == "min"      # чужие свёрнутые остались свёрнутыми
    assert api.state[3] == "shown" and api.state[4] == "shown"
    assert api.shell == [False] and not h.hidden


def test_restore_verify_minimizes_nothing_and_retries_ours():
    api = FakeAPI([1, 2], premin=(2,))
    h = Hider(api)
    h.hide()
    h.restore()
    assert h.restore_verify() == 0 and api.shell == []
    api.state[1] = "min"                      # наше окно так и не развернулось
    assert h.restore_verify() == 1 and api.state[1] == "shown"
    assert api.state[2] == "min" and api.shell == []


def test_toggle_cycle():
    api = FakeAPI([1, 2])
    h = Hider(api)
    assert h.toggle() == ("hide", 2)
    assert h.toggle() == ("restore", 2)
    assert h.toggle() == ("hide", 2)


def test_after_user_restored_everything_next_toggle_hides():
    api = FakeAPI([1, 2])
    clock = [0.0]
    h = Hider(api, clock=lambda: clock[0])
    h.hide()
    api.state = {1: "shown", 2: "shown"}
    clock[0] = 2.0                        # прошла секунда «верю своему действию» - смотрим на Windows
    assert h.toggle()[0] == "hide"


def test_restore_all_keeps_foreign_minimized():
    """Трей «Вернуть все окна»: ничего своего не свёрнуто - возвращать нечего, чужие свёрнутые не трогаем."""
    api = FakeAPI([1, 2], premin=(1, 2))
    h = Hider(api)
    assert h.restore_all() == 0
    assert api.shell == [] and api.state[1] == "min" and api.state[2] == "min"


def test_restore_all_returns_our_windows_after_hide():
    api = FakeAPI([1, 2, 3], premin=(3,))
    h = Hider(api)
    h.hide()
    assert h.restore_all() == 2 and api.state[3] == "min"
    assert h.restore_all() == 0                     # второй раз возвращать нечего
    api.state[1] = "min"                            # пользователь свернул наше окно сам - вернём по памяти
    assert h.restore_all() == 1 and api.state[1] == "shown"
    assert api.shell == []


def test_nothing_open():
    api = FakeAPI([])
    h = Hider(api)
    assert h.toggle() == ("hide", 0)
    assert not h.hidden


# ---------------------------------------------------------------- «вернуть ВСЕ окна, которые свернул» (16.10.2026)
def test_window_opened_after_hide_is_not_touched():
    """Между сворачиванием и возвратом пользователь открыл новое окно - программа его не трогает и не ломается."""
    api = FakeAPI([1, 2])
    h = Hider(api)
    h.hide()
    api.wins.append(9)
    api.state[9] = "shown"                    # новое окно (владелец открыл сам, пока окна были свёрнуты)
    assert h.restore() == 2
    assert api.state[9] == "shown" and ("restore", 9) not in api.log and ("min", 9) not in api.log


def test_window_opened_before_shell_fallback_is_restored_too():
    """Окно открылось до того, как проводник досворачивал упрямое окно: проводник свернул и его - значит, вернуть
    надо и его тоже, иначе «не вернул все окна»."""
    api = FakeAPI([1, 2], stubborn={1})
    h = Hider(api)
    h.hide()
    api.wins.append(9)
    api.state[9] = "shown"
    assert h.verify() == 1 and api.state[9] == "min"        # проводник свернул всё, включая новое окно
    assert 9 in h.saved
    assert h.restore() == 3 and api.state[9] == "shown"


def test_restore_returns_windows_from_previous_round_too():
    """«Возврат всех окон, которые свернул»: окно, не вернувшееся в прошлый раз, возвращается вместе с новыми."""
    api = FakeAPI([1, 2, 3])
    h = Hider(api)
    h.hide()
    h.restore()
    api.state[1] = "min"                      # осталось свёрнутым (не успело развернуться)
    api.state[2] = "shown"
    api.state[3] = "shown"
    h.hide()                                  # второй раз: сворачиваем 2 и 3, а 1 уже свёрнуто
    assert h.before == [1] or 1 in h.before   # 1 для нового раза - «чужое свёрнутое», его не трогаем
    assert h.restore() == 2 and api.state[1] == "min"


def test_closed_window_between_hide_and_restore_does_not_break():
    api = FakeAPI([1, 2, 3])
    h = Hider(api)
    h.hide()
    del api.state[2]
    del api.state[3]
    assert h.restore() == 1 and api.state[1] == "shown"
    assert h.restore_verify() == 0


# ---------------------------------------------------------------- 1.2.0: упрямые окна и «только что свернули»
def test_stubborn_window_calls_explorer_at_once_next_time():
    """Окно «от администратора» само не сворачивается (журнал владельца: «1 не свернулись сами»). В первый раз
    проводника зовём после проверки, во второй - сразу, чтобы рабочий стол был чистым с первого раза."""
    api = FakeAPI([1, 2, 3], stubborn={2})
    h = Hider(api)
    h.hide()
    assert api.shell == []                       # сразу проводника не зовём
    assert h.verify() == 1 and api.shell == [False] and 2 in h.stubborn
    h.restore()
    api.shell.clear()
    h.hide()
    assert api.shell == [False], "упрямое окно известно - проводник зовётся сразу"
    assert h.verify() == 0
    assert all(api.state[x] == "min" for x in (1, 2, 3))


def test_every_window_gets_second_restore_attempt_at_once():
    """«Вернул окна: 1 вернулись только со второго раза» в журнале владельца 16.10.2026: вторую попытку делаем
    СРАЗУ для каждого окна, а не через 0,6 с - тогда человек и не узнает, что был второй раз."""
    api = FakeAPI([1, 2], stubborn={2})
    h = Hider(api)
    h.hide()
    h.verify()
    api.log.clear()
    h.restore()
    assert api.log.count(("restore", 2)) == 2 and api.log.count(("restore", 1)) == 2
    assert h.restore_verify() == 0, "доворачивать через 0,6 с уже нечего"


def test_hidden_right_after_hide_even_if_windows_not_marked_yet():
    """ShowWindowAsync - асинхронный: сразу после сворачивания Windows ещё не отметила окна свёрнутыми. Полсекунды
    программа верит своему действию (иначе в окне написано «Слушаю» вместо «Окна свёрнуты»), а потом - Windows."""
    api = FakeAPI([1, 2], stubborn={1, 2})           # ни одно окно не отметилось как свёрнутое
    clock = [0.0]
    h = Hider(api, clock=lambda: clock[0])
    h.hide()
    assert h.hidden is True
    clock[0] = 2.0
    h.settle()
    assert h.hidden is False


# ---------------------------------------------------------------- порядок наложения окон (владелец 16.10.2026)
class OrderAPI(FakeAPI):
    """Как Windows: порядок наложения - отдельное состояние, SetWindowPos поднимает окно наверх."""

    def __init__(self, wins, **kw):
        super().__init__(wins, **kw)
        self.z = list(wins)                      # сверху вниз

    def app_windows(self):
        return [h for h in self.z if self.state.get(h) == "shown"]

    def minimized_windows(self):
        return [h for h in self.z if self.state.get(h) == "min"]

    def set_order(self, hwnds):
        n = 0
        for h in reversed(list(hwnds)):          # снизу вверх: каждое окно наверх
            if h in self.z:
                self.z.remove(h)
                self.z.insert(0, h)
                n += 1
        return n

    def shuffle(self, order):
        """Windows выполнила наши команды в другом порядке (так и бывает: ShowWindowAsync асинхронный)."""
        self.z = list(order)


def test_restore_puts_windows_back_in_the_same_order():
    """Свернулись 1,2,3,4,5 - вернулись так же: 1 сверху, 5 снизу. Порядок выставляем явно, а не надеемся на
    очерёдность команд (требование владельца 16.10.2026)."""
    api = OrderAPI([1, 2, 3, 4, 5])
    h = Hider(api)
    h.hide()
    api.shuffle([3, 5, 1, 4, 2])                 # Windows подняла окна в своём порядке
    h.restore()
    assert api.z == [1, 2, 3, 4, 5], api.z


def test_order_survives_closed_and_user_restored_windows():
    """Окно закрыли или человек развернул его сам - порядок остальных не ломается."""
    api = OrderAPI([1, 2, 3, 4, 5])
    h = Hider(api)
    h.hide()
    del api.state[3]                             # закрыли
    api.z.remove(3)
    api.state[4] = "shown"                       # развернул сам
    api.shuffle([4, 5, 2, 1])
    h.restore()
    assert api.z == [1, 2, 4, 5], api.z


def test_order_skips_admin_windows():
    """Окно «от администратора» Windows нам не отдаёт - порядок остальных всё равно верный."""
    from shchelchok import winapi
    api = OrderAPI([1, 2, 3])
    api.window_rights = lambda hh: winapi.ADMIN if hh == 2 else winapi.OURS
    api.window_title = lambda hh: f"Окно {hh}"
    h = Hider(api)
    h.hide()
    api.state[2] = "min"                         # его свернул проводник, нам он не подчиняется
    api.shuffle([3, 1, 2])
    h.restore()
    assert [x for x in api.z if x != 2] == [1, 3]


def test_five_cycles_in_a_row_keep_order():
    """Пять кругов «свернул - вернул» подряд: каждый раз возвращаются все окна и в том же порядке."""
    api = OrderAPI([1, 2, 3, 4, 5])
    h = Hider(api)
    for _ in range(5):
        assert h.hide() == 5
        api.shuffle([5, 1, 4, 2, 3])
        assert h.restore() == 5
        assert api.z == [1, 2, 3, 4, 5]
        assert all(api.state[x] == "shown" for x in (1, 2, 3, 4, 5))


def test_restore_order_is_skipped_for_old_api():
    api = FakeAPI([1, 2])                        # без set_order (старый api в тестах)
    h = Hider(api)
    h.hide()
    assert h.restore() == 2 and h.restore_order([1, 2]) == 0


def test_order_is_applied_to_all_our_windows_not_only_restored_ones():
    """Команды окнам асинхронные: если расставить только те окна, которые Windows УЖЕ развернула, эта половина
    уедет наверх и порядок прокрутится (под Wine [A,B,C] -> [B,C,A] на каждом втором круге)."""
    api = OrderAPI([1, 2, 3])
    h = Hider(api)
    h.hide()
    h.restore()
    api.state[1] = "min"                      # окно ещё не успело подняться
    api.shuffle([3, 2, 1])
    h.restore_order(h.last)                   # доворот по ходу возврата
    assert api.z == [1, 2, 3], api.z
