"""Свернуть все окна и вернуть их как были. Логика без Windows (api подменяется в тестах).

Свернуть: запоминаем, какие окна пользователь свернул САМ (их мы не тронем), остальные окна программ сверху вниз и
активное окно; сворачиваем свои сами (снизу вверх - без мигания фокуса). Через полсекунды проверяем: какое-то окно
не свернулось (программа «от администратора», зависла) - досворачивает проводник («свернуть все» панели задач).
Вернуть: ТОЛЬКО свои окна - ВСЕ, которые свернули мы (и сейчас, и в прошлый раз), поимённо, снизу вверх (порядок
как был), фокус - тому, кто был активным. Окна, закрытые за это время, пропускаем; развёрнутые вручную - не трогаем;
чужие свёрнутые - никогда. «Все окна, которые свернул» - требование владельца 16.10.2026.

Команду проводника «отменить свернуть все» (416) при возврате НЕ зовём (баг владельца 15.10.2026 - «иногда
показывает другие папки»): она разворачивает ВСЁ, что было свёрнуто, включая папки, которые пользователь свернул
сам до щелчка. Наши окна, не вернувшиеся с первого раза, разворачиваем ещё раз поимённо (restore_verify).
"""
from __future__ import annotations

import time

from . import winapi

HIDE_TRUST = 1.0        # столько секунд после сворачивания верим своему действию, а не отметке Windows


class Hider:
    def __init__(self, api=winapi, clock=time.monotonic):
        self.api = api
        self.clock = clock
        self.saved = None            # [hwnd сверху вниз] - что свернули мы
        self.last = []               # то же после возврата (трей «Вернуть все окна» помнит прошлый раз)
        self.before = []             # чужие окна, свёрнутые ДО нашего щелчка - не разворачиваем никогда
        self.fg = 0
        self.used_shell = False      # пришлось позвать проводника («свернуть все»); на возврат это не влияет
        self.stubborn = set()        # окна, которые сами не сворачиваются («от администратора», зависшие)
        self.trust_until = 0.0       # мы только что свернули (Windows ещё не отметила окна свёрнутыми)
        self.admin = set()           # окна с правами выше наших: ни свернуть, ни вернуть их мы не можем (UIPI)
        # где и какого размера было каждое окно до сворачивания: {hwnd: {"show": …, "rect": …}}
        # (владелец 17.10.2026: «Может Щелчок возвращать окна в те же места и с теми же размерами?»)
        self.places = {}
        self.last_places = {}        # то же для окон прошлого раза (их возвращает «Вернуть все окна»)

    def rights(self, h):
        """Можем ли мы управлять окном: "ours" / "admin" (права выше наших) / "unknown"."""
        fn = getattr(self.api, "window_rights", None)
        return fn(h) if fn is not None else "ours"

    def title(self, h):
        fn = getattr(self.api, "window_title", None)
        return (fn(h) or "") if fn is not None else ""

    def admin_windows(self, hwnds=None):
        """Окна «от имени администратора» среди наших: [(hwnd, заголовок)] - для понятной строки человеку."""
        hs = self.admin if hwnds is None else [h for h in hwnds if h in self.admin or self.rights(h) == "admin"]
        return [(h, self.title(h)) for h in hs if self.api.window_alive(h)]

    def _ours(self, h):
        """Это окно свернули мы и оно ещё живо (не из тех, что пользователь свернул сам)."""
        return h not in self.before and self.api.window_alive(h)

    @property
    def hidden(self):
        """Есть что возвращать: хотя бы одно из НАШИХ окон живо и свёрнуто. Сразу после сворачивания Windows ещё
        не успевает отметить окна свёрнутыми (ShowWindowAsync) - до первой проверки верим своему действию,
        иначе программа полсекунды думает, что окна на месте, и в окне написано не то."""
        alive = [h for h in (self.saved or []) if self._ours(h)]
        if not alive:
            return False
        return any(self.api.is_minimized(h) for h in alive) or self.clock() < self.trust_until

    def settle(self):
        """Проверка по таймеру: окна вернули мимо нас (панель задач, Win+D) - больше не считаем их свёрнутыми."""
        alive = [h for h in (self.saved or []) if self._ours(h)]
        if not any(self.api.is_minimized(h) for h in alive):
            self.trust_until = 0.0

    def hide(self):
        """-> сколько окон сворачиваем.

        Окна «от имени администратора» узнаём ЗАРАНЕЕ (права процесса окна) и не делаем вид, что сворачиваем их
        сами: Windows молча не выполнит команду. Их сворачивает проводник («свернуть все» панели задач) - его
        команда работает и для таких окон, потому что её выполняет сам проводник."""
        self.before = list(self.api.minimized_windows())
        wins = [h for h in self.api.app_windows() if h not in self.before]
        self.fg = self.api.foreground()
        self.saved = list(wins)
        self.used_shell = False
        self.admin = {h for h in wins if self.rights(h) == "admin"}
        self.trust_until = self.clock() + HIDE_TRUST if wins else 0.0
        self.places = {h: p for h, p in ((h, self.place_of(h)) for h in wins) if p}
        for h in reversed(wins):
            if h not in self.admin:
                self.api.minimize(h)
        if self.admin or self.stubborn.intersection(wins):
            self._call_shell()       # такое окно само не свернётся - не ждём лишние 0,25 с
        return len(wins)

    def _call_shell(self):
        """Проводник сворачивает ВСЁ открытое - значит, окна, открывшиеся уже после нашего щелчка, тоже
        свернутся: запоминаем их как свои, иначе они останутся свёрнутыми и «программа не вернула все окна»."""
        extra = [h for h in self.api.app_windows() if h not in self.before and h not in (self.saved or [])]
        self.saved = list(self.saved or []) + extra
        self.used_shell = bool(self.api.shell_minimize_all(False))

    def verify(self):
        """Через ~0,25 с после hide(): не свернувшиеся окна досворачивает проводник; такие окна запоминаем, и в
        следующий раз проводника зовём сразу. -> сколько не свернулось само."""
        left = [h for h in (self.saved or []) if self.api.window_alive(h) and self.api.is_shown(h)]
        if left:
            self.stubborn.update(left)
            self.admin.update(h for h in left if self.rights(h) == "admin")
            if not self.used_shell:
                self._call_shell()
        return len(left)

    def not_hidden(self):
        """Наши окна, которые так и остались на экране (проводник тоже не помог). -> [hwnd]."""
        return [h for h in (self.saved or []) if self.api.window_alive(h) and self.api.is_shown(h)]

    def place_of(self, h):
        """Где и какого размера окно сейчас (для возврата). Нет такой возможности у api - None."""
        fn = getattr(self.api, "get_placement", None)
        try:
            return fn(h) if fn is not None else None
        except Exception:  # noqa: BLE001 - чужое окно не должно ронять нас
            return None

    def put_back(self, h):
        """Поставить окно туда же и таким же, как было: развёрнутое - развёрнутым, обычное - с теми же
        координатами и размером. Запомненного положения нет - окно просто развернётся обычным restore."""
        pl = self.places.get(h) or self.last_places.get(h)
        fn = getattr(self.api, "set_placement", None)
        if not pl or fn is None or h in self.admin:
            return False                       # окну «от администратора» Windows наши команды не отдаёт
        try:
            return bool(fn(h, pl))
        except Exception:  # noqa: BLE001
            return False

    def _restore_saved(self, wins):
        """Разворачиваем поимённо, снизу вверх. Команду каждому окну посылаем ДВА раза подряд: Windows выполняет
        ShowWindowAsync не мгновенно, и окно, свёрнутое проводником, с первого раза иногда не поднималось
        («вернул окна: 1 вернулись только со второго раза» в журнале владельца 16.10.2026).

        Вместе с этим возвращаем ПОЛОЖЕНИЕ: SW_RESTORE возвращает развёрнутое на весь экран окно в обычный
        размер, а человек ждёт его развёрнутым (владелец 17.10.2026)."""
        n = 0
        todo = []
        for h in reversed(wins or []):
            if self._ours(h) and self.api.is_minimized(h):
                self.api.restore(h)
                todo.append(h)
                n += 1
        for h in todo:
            self.api.restore(h)
            self.put_back(h)
        return n

    def ours_minimized(self):
        """Все НАШИ окна, которые сейчас свёрнуты: этот раз + прошлый (порядок - снизу вверх по времени)."""
        now = list(self.saved or [])
        old = [h for h in self.last if h not in now]
        return old, now

    def restore(self):
        """Вернуть ВСЕ окна, которые мы сворачивали (и в прошлый раз тоже) - поимённо; «отменить свернуть все»
        проводника не зовём. -> сколько окон вернули.

        Порядок наложения выставляем ЯВНО (`set_order`), а не надеемся на очерёдность команд: окна обязаны
        встать точно так, как стояли до щелчка (требование владельца 16.10.2026)."""
        old, now = self.ours_minimized()
        n = self._restore_saved(old) + self._restore_saved(now)
        self.last = old + now
        self.restore_order(now + old)       # сверху - окна этого раза, под ними - окна прошлого
        if self.fg and self.api.window_alive(self.fg):
            self.api.bring_to_front(self.fg)
        # положение окон держим до следующего сворачивания: «Вернуть все окна» из трея и доворачивание
        # (restore_verify) должны ставить окна туда же, а не куда придётся
        # ... но только для окон, которые ещё в нашем списке: иначе запись о давно закрытом окне однажды
        # достанется новому окну с тем же номером и поставит его не туда
        keep = set(self.last)
        merged = dict(self.last_places)
        merged.update(self.places)                 # ключи - номера окон, не строки: update, а не dict(**…)
        self.last_places = {h: p for h, p in merged.items() if h in keep}
        self.places = {}
        self.saved, self.used_shell, self.fg, self.trust_until = None, False, 0, 0.0
        return n

    def restore_order(self, wins):
        """Порядок наложения, как был: сверху вниз - тот же список, что запомнили при сворачивании. Закрытые и
        окна «от администратора» (их Windows нам не отдаёт) пропускаем - порядок остальных от этого не ломается.

        ВАЖНО: берём ВСЕ свои окна, а не только те, которые Windows уже успела развернуть. Команды окнам
        асинхронные, и если расставить только половину списка, эта половина уедет наверх, а порядок
        прокрутится (под Wine было видно: [A,B,C] -> [B,C,A] на каждом втором круге). -> сколько окон
        расставили."""
        fn = getattr(self.api, "set_order", None)
        if fn is None:
            return 0
        order = [h for h in (wins or []) if h not in self.admin and self._ours(h)]
        return fn(order) if order else 0

    def restore_verify(self):
        """Через ~0,5 с после restore(): наши окна, которые всё ещё свёрнуты, разворачиваем ещё раз (проводника и
        его «отменить свернуть все» не зовём - иначе всплывут чужие свёрнутые окна). -> сколько доворачивали."""
        left = self.not_restored()
        for h in left:
            self.api.restore(h)
            self.put_back(h)
        # порядок выставляем ВСЕГДА, а не только когда кого-то доворачивали: «развернуть на весь экран» -
        # единственная команда, которая поднимает окно наверх, и выполняется она с задержкой (асинхронно),
        # уже после первой расстановки порядка (проверено под Wine 17.10.2026)
        self.restore_order(self.last)
        return len(left)

    def not_restored(self, with_admin=False):
        """Наши окна, которые после возврата всё ещё свёрнуты. -> [hwnd].

        Окна «от имени администратора» сюда НЕ попадают: про них уже сказано отдельной строкой, а доворачивать
        их бесполезно - Windows всё равно не выполнит команду. Из-за этого в журнале владельца 16.10.2026
        появлялось «вернул окна: 1 вернулись только со второго раза» (11 раз за сеанс) - каждый раз про одно и
        то же окно командной строки.

        Если мы уже успели свернуть окна ЗАНОВО (`saved` не пуст), ответ пустой: окна свёрнуты нарочно, и
        считать их «не вернувшимися» нельзя (в журнале владельца: «свернул окна: 3» и сразу «не вернулось:
        3 окна осталось свёрнутым»)."""
        if self.saved is not None:
            return []
        return [h for h in self.last
                if self._ours(h) and self.api.is_minimized(h) and (with_admin or h not in self.admin)]

    def restore_all(self):
        """«Вернуть все окна» из трея: только свои - те, что свернули мы сейчас или в прошлый раз. Чужие свёрнутые
        окна не трогаем. -> сколько вернули (0 - возвращать нечего)."""
        if self.saved is not None:
            return self.restore()
        return self._restore_saved(self.last)

    def toggle(self):
        """-> ("hide", n) или ("restore", n)."""
        if self.hidden:
            return "restore", self.restore()
        return "hide", self.hide()
