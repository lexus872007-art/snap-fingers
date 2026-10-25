"""Окна возвращаются в ТЕ ЖЕ места и с теми же размерами (владелец 17.10.2026: «На данный момент такого нет»).

Раньше возврат был одной командой SW_RESTORE, а Windows возвращает развёрнутое на весь экран окно в ОБЫЧНЫЙ
размер - человек видел не то, что сворачивал. Теперь перед сворачиванием запоминается полное положение окна
(развёрнуто / обычное + прямоугольник), при возврате ставится обратно.

Каждый риск - отдельная проверка:
(а) развёрнутое на весь экран возвращается развёрнутым;
(б) обычное - ровно с теми же координатами и размером (сравниваем ЧИСЛА);
(в) окно со второго монитора возвращается на свой монитор;
(г) человек сам развернул окно, пока оно было свёрнуто - его выбор не ломаем;
(д) монитор отключили между сворачиванием и возвратом - окно не уезжает за край экрана;
(е) разрешение поменялось - то же самое;
(ж) окно закрыли - просто пропускаем, остальные возвращаются;
(з) пять кругов подряд - и геометрия, и порядок наложения те же;
(и) «Вернуть все окна» из трея тоже ставит окна на место;
(к) окна «от администратора» не трогаем (их Windows нам не отдаёт);
(л) fit_rect - чистая функция: что делает с прямоугольником при пропавшем мониторе.
"""
from shchelchok.hider import Hider
from shchelchok.winapi import fit_rect

MON1 = (0, 0, 1920, 1040)
MON2 = (1920, 0, 3840, 1080)
NORMAL, MAXIMIZED = 1, 3


class FakeAPI:
    """Окна с настоящей геометрией: номер -> (состояние, показ, прямоугольник)."""

    def __init__(self, wins, mons=(MON1,), premin=(), admin=()):
        self.z = list(wins)                       # сверху вниз
        self.state = {h: "shown" for h in wins}
        self.show = {h: NORMAL for h in wins}
        self.rect = {h: (100 + 50 * i, 100 + 40 * i, 900 + 50 * i, 700 + 40 * i) for i, h in enumerate(wins)}
        self.mons = list(mons)
        self.admin = set(admin)
        for h in premin:
            self.state[h] = "min"
        self.fg = next((h for h in wins if self.state[h] == "shown"), 0)
        self.log = []

    # -- что видит программа
    def app_windows(self):
        return [h for h in self.z if self.state.get(h) == "shown"]

    def minimized_windows(self):
        return [h for h in self.z if self.state.get(h) == "min"]

    def foreground(self):
        return self.fg

    def window_alive(self, h):
        return h in self.state

    def is_minimized(self, h):
        return self.state.get(h) == "min"

    def is_shown(self, h):
        return self.state.get(h) == "shown"

    def window_rights(self, h):
        return "admin" if h in self.admin else "ours"

    def window_title(self, h):
        return f"Окно {h}"

    # -- что программа делает
    def minimize(self, h):
        if h not in self.admin:
            self.state[h] = "min"

    def restore(self, h):
        """Как Windows: разворачивает в ОБЫЧНЫЙ размер, про «было развёрнуто» не помнит."""
        self.state[h] = "shown"
        self.show[h] = NORMAL
        self.log.append(("restore", h))

    def get_placement(self, h):
        if h not in self.state:
            return None
        return {"show": self.show[h], "rect": self.rect[h]}

    def set_placement(self, h, pl, mons=None):
        if h not in self.state or not pl:
            return False
        self.state[h] = "shown"
        self.show[h] = pl["show"]
        if pl["show"] == NORMAL:
            self.rect[h] = fit_rect(pl["rect"], self.mons)
        self.log.append(("place", h, self.show[h], self.rect[h]))
        return True

    def set_order(self, hwnds):
        for h in reversed(list(hwnds)):
            if h in self.z:
                self.z.remove(h)
                self.z.insert(0, h)
        return len(hwnds)

    def shell_minimize_all(self, undo=False):
        for h in self.state:
            if not undo and self.state[h] == "shown":
                self.state[h] = "min"
        return True

    def bring_to_front(self, h):
        self.fg = h
        return True


def hide_and_restore(api):
    h = Hider(api)
    h.hide()
    h.restore()
    return h


# ---------------------------------------------------------------- (а) развёрнутое
def test_развёрнутое_окно_возвращается_развёрнутым():
    api = FakeAPI([1, 2])
    api.show[1] = MAXIMIZED
    hide_and_restore(api)
    assert api.show[1] == MAXIMIZED, "окно было на весь экран - должно вернуться на весь экран"
    assert api.show[2] == NORMAL


# ---------------------------------------------------------------- (б) обычное: те же числа
def test_обычное_окно_возвращается_с_теми_же_числами():
    api = FakeAPI([1, 2, 3])
    was = dict(api.rect)
    hide_and_restore(api)
    for h in (1, 2, 3):
        assert api.rect[h] == was[h], f"окно {h}: было {was[h]}, стало {api.rect[h]}"


# ---------------------------------------------------------------- (в) второй монитор
def test_окно_со_второго_монитора_возвращается_на_свой_монитор():
    api = FakeAPI([1, 2], mons=(MON1, MON2))
    api.rect[2] = (2100, 120, 2900, 720)
    hide_and_restore(api)
    assert api.rect[2] == (2100, 120, 2900, 720)
    assert api.rect[2][0] >= MON2[0], "окно уехало с своего монитора"


# ---------------------------------------------------------------- (г) человек развернул окно сам
def test_человек_сам_развернул_окно_пока_оно_было_свёрнуто():
    api = FakeAPI([1, 2])
    h = Hider(api)
    h.hide()
    api.state[1] = "shown"            # достал из панели задач
    api.show[1] = MAXIMIZED           # и развернул на весь экран
    api.rect[1] = (0, 0, 1920, 1040)
    h.restore()
    assert api.show[1] == MAXIMIZED, "мы сломали выбор человека"
    assert api.rect[1] == (0, 0, 1920, 1040)


# ---------------------------------------------------------------- (д) монитор отключили
def test_монитор_отключили_окно_не_уезжает_за_край():
    api = FakeAPI([1, 2], mons=(MON1, MON2))
    api.rect[2] = (2100, 120, 2900, 720)
    h = Hider(api)
    h.hide()
    api.mons = [MON1]                 # второй монитор отключили
    h.restore()
    l, t, r, b = api.rect[2]
    assert l < MON1[2] and r <= MON1[2], f"окно за краем экрана: {api.rect[2]}"
    assert (r - l, b - t) == (800, 600), "размер окна менять не просили"


# ---------------------------------------------------------------- (е) разрешение поменялось
def test_разрешение_поменялось():
    api = FakeAPI([1], mons=((0, 0, 3840, 2120),))
    api.rect[1] = (3000, 1800, 3800, 2100)
    h = Hider(api)
    h.hide()
    api.mons = [(0, 0, 1280, 680)]    # стало меньше
    h.restore()
    l, t, r, b = api.rect[1]
    assert 0 <= l and r <= 1280 and 0 <= t and b <= 680, f"окно вне экрана: {api.rect[1]}"


# ---------------------------------------------------------------- (ж) окно закрыли
def test_закрытое_окно_пропускаем():
    api = FakeAPI([1, 2, 3])
    was = dict(api.rect)
    h = Hider(api)
    h.hide()
    del api.state[2]                  # окно закрыли, пока было свёрнуто
    h.restore()
    assert api.rect[1] == was[1] and api.rect[3] == was[3]
    assert api.state.get(1) == "shown" and api.state.get(3) == "shown"


# ---------------------------------------------------------------- (з) пять кругов
def test_пять_кругов_подряд_геометрия_и_порядок_те_же():
    api = FakeAPI([1, 2, 3, 4])
    api.show[2] = MAXIMIZED
    was_rect, was_z = dict(api.rect), list(api.z)
    h = Hider(api)
    for _ in range(5):
        h.hide()
        h.restore()
    assert api.z == was_z, f"порядок наложения разъехался: {api.z} вместо {was_z}"
    assert api.show[2] == MAXIMIZED, "развёрнутое окно перестало быть развёрнутым"
    for k in was_rect:
        assert api.rect[k] == was_rect[k], f"окно {k}: {api.rect[k]} вместо {was_rect[k]}"


# ---------------------------------------------------------------- (и) «Вернуть все окна» из трея
def test_вернуть_все_окна_из_трея_ставит_на_место():
    api = FakeAPI([1, 2])
    api.show[1] = MAXIMIZED
    h = Hider(api)
    h.hide()
    h.restore()
    api.state[1] = api.state[2] = "min"      # человек свернул их снова руками
    api.show[1] = NORMAL
    h.restore_all()
    assert api.show[1] == MAXIMIZED
    assert api.state[2] == "shown"


# ---------------------------------------------------------------- (к) окна «от администратора»
def test_окна_от_администратора_не_трогаем():
    api = FakeAPI([1, 2], admin=(2,))
    was = api.rect[2]
    h = Hider(api)
    h.hide()
    h.restore()
    assert api.rect[2] == was
    assert not any(e[0] == "place" and e[1] == 2 for e in api.log), "трогали окно с правами выше наших"


# ---------------------------------------------------------------- (л) сама подгонка
def test_подгонка_прямоугольника():
    assert fit_rect((100, 100, 900, 700), [MON1]) == (100, 100, 900, 700)
    assert fit_rect((2100, 50, 2900, 650), [MON1, MON2]) == (2100, 50, 2900, 650)
    # монитора нет - переносим в ближайший, размер сохраняем
    got = fit_rect((2100, 50, 2900, 650), [MON1])
    assert got[2] <= MON1[2] and (got[2] - got[0], got[3] - got[1]) == (800, 600)
    # окно, чуть выглядывающее за край, человек подвинул сам - не трогаем
    assert fit_rect((1850, 100, 2650, 700), [MON1]) == (1850, 100, 2650, 700)
    assert fit_rect(None, [MON1]) is None
    assert fit_rect((1, 2, 3, 4), []) == (1, 2, 3, 4)


# ---------------------------------------------------------------- без поддержки положения всё работает по-старому
def test_старый_api_без_положения_просто_разворачивает():
    class Old(FakeAPI):
        get_placement = None
        set_placement = None
    api = Old([1, 2])
    api.show[1] = MAXIMIZED
    h = Hider(api)
    h.hide()
    h.restore()
    assert api.state[1] == "shown" and api.state[2] == "shown"


# ---------------------------------------------------------------- свёрнутое окно: запоминать нечего
def test_у_свёрнутого_окна_положение_не_берём():
    """Под Wine у свёрнутого окна в «нормальном» прямоугольнике лежат координаты значка на панели задач
    (-32000): такое запоминать нельзя, иначе окно вернётся крошечным и за краем экрана (опыт 17.10.2026)."""
    from shchelchok.winapi import placement_from
    assert placement_from(2, (-32000, -32000, -31840, -31969)) is None
    assert placement_from(7, (100, 100, 900, 700)) is None
    assert placement_from(1, (0, 0, 40, 20)) is None, "слишком маленький прямоугольник - не окно"
    assert placement_from(1, (10, 20, 810, 620)) == {"show": 1, "rect": (10, 20, 810, 620)}
    assert placement_from(3, (10, 20, 810, 620)) == {"show": 3, "rect": (10, 20, 810, 620)}
