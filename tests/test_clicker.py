# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Решение: один/два/три щелчка сворачивают, ДВА щелчка подряд возвращают (владелец 16.10.2026), «тишина вокруг»,
пауза после срабатывания; щелчков подряд больше, чем нужно - серия не отменяется."""
import pytest

from shchelchok.detector import (Clicker, MAYBE, NO_HIDE_QUIET, NOISE, POST_MS, RESTORE_N, SNAP,
                                 series_window)

D = POST_MS / 1000.0
D_QUIET = NO_HIDE_QUIET


def run(ck, events, end=None, follow=False):
    """events: [(t, ok, peak дБ | None[, kind])] -> [(время, "hide"/"restore")] (опрос каждые 30 мс, удар
    разбирается 0,13 с)."""
    fired = []
    evs = sorted(events)
    t = 0.0
    i = 0
    end = end or (evs[-1][0] + 3 if evs else 3)
    while t < end:
        while i < len(evs) and evs[i][0] + D <= t:
            ck.push(*evs[i])
            i += 1
        a = ck.poll(t)
        if a:
            fired.append((t, a))
            if follow:
                ck.hidden = a == "hide"      # как в программе: состояние окон меняется сразу (set_windows)
        t += 0.03
    return fired


def snaps(*times, peak=0.0):
    return [(t, True, peak) for t in times]


def test_single_snap_fires_once():
    f = run(Clicker(mode=1), [(1.0, True, 0.0)])
    assert len(f) == 1 and f[0][1] == "hide" and 1.4 <= f[0][0] <= 1.5


def test_single_blocked_by_sound_after():
    assert run(Clicker(mode=1), [(1.0, True, 0.0), (1.2, False, 0.0)]) == []


def test_single_blocked_by_sound_before():
    assert run(Clicker(mode=1), [(0.7, False, 0.0), (1.0, True, 0.0)]) == []


def test_quiet_sound_around_does_not_block():
    assert len(run(Clicker(mode=1), [(0.8, False, None), (1.0, True, 0.0)])) == 1


def test_cooldown():
    ck = Clicker(mode=1, cooldown=1.5)
    f = run(ck, [(1.0, True, 0.0), (2.2, True, 0.0), (3.6, True, 0.0)])
    assert len(f) == 2          # 2,2 - в паузе после первого; 3,6 - уже можно


def test_double_mode():
    assert len(run(Clicker(mode=2), [(1.0, True, 0.0), (1.4, True, 0.0)])) == 1
    assert run(Clicker(mode=2), [(1.0, True, 0.0)]) == []
    assert run(Clicker(mode=2), [(1.0, True, 0.0), (1.05, True, 0.0)]) == []      # быстрее 0,15 с
    assert run(Clicker(mode=2), [(1.0, True, 0.0), (2.0, True, 0.0)]) == []       # дольше 0,8 с


def test_third_snap_does_not_cancel_the_pair():
    """Щёлкнул ещё раз, потому что не вышло с первого - серией считаются последние два щелчка, а не «всё отменить»
    (из-за отмены владелец 16.10.2026 не мог вернуть окна)."""
    f = run(Clicker(mode=2), [(1.0, True, 0.0), (1.4, True, 0.0), (1.6, True, 0.0)])
    assert [a for _, a in f] == ["hide"]


def test_triple_mode():
    assert len(run(Clicker(mode=3), [(1.0, True, 0.0), (1.4, True, 0.0), (1.8, True, 0.0)])) == 1
    assert run(Clicker(mode=3), [(1.0, True, 0.0), (1.4, True, 0.0)]) == []


def test_quiet_echo_after_does_not_cancel():
    assert len(run(Clicker(mode=1), [(1.0, True, -10.0), (1.08, False, -25.0)])) == 1
    assert run(Clicker(mode=1), [(1.0, True, -10.0), (1.08, False, -18.0)]) == []


def test_series_of_keys_never_fires():
    ev = [(1.0 + 0.18 * k, k % 4 == 0, -12.0) for k in range(30)]   # каждый 4-й «похож», но вокруг удары
    assert run(Clicker(mode=1), ev) == []


# ---------------------------------------------------------------- возврат окон: ДВА щелчка подряд
def test_restore_needs_two_snaps():
    assert RESTORE_N == 2                                                  # решение владельца 16.10.2026
    f = run(Clicker(mode=1, hidden=True), snaps(1.0, 1.4))
    assert [a for _, a in f] == ["restore"]


def test_single_snap_does_not_restore_by_default():
    """Окна свёрнуты, начальник рядом: случайный одиночный щелчок (звук) окна НЕ возвращает."""
    assert run(Clicker(mode=1, hidden=True), snaps(1.0)) == []
    assert run(Clicker(mode=1, hidden=True), snaps(1.0, 2.5)) == []       # два отдельных одиночных
    assert run(Clicker(mode=1, hidden=True), snaps(1.0, 1.05)) == []      # «двойной» быстрее 0,15 с - не серия


def test_more_snaps_in_a_row_still_restore():
    """Владелец щёлкает ещё и ещё, пока не вернётся: 3, 4, 5 щелчков подряд обязаны вернуть окна."""
    for times in ((1.0, 1.4, 1.8), (1.0, 1.3, 1.6, 1.9), (1.0, 1.2, 1.4, 1.6, 1.8)):
        f = run(Clicker(mode=1, hidden=True), snaps(*times))
        assert [a for _, a in f][:1] == ["restore"], times


def test_single_snap_restores_by_default():
    """Главное поведение: один щелчок возвращает окна (владелец 16.10.2026)."""
    f = run(Clicker(mode=1, hidden=True, single_restores=True), snaps(1.0))
    assert [a for _, a in f] == ["restore"]
    # щелчки подряд через 0,4 с: каждый отвечает (в режиме переключателя - следующий переключит обратно)
    f3 = run(Clicker(mode=1, hidden=True, single_restores=True), snaps(1.0, 1.4, 1.8), follow=True)
    assert len(f3) >= 2, f3


def test_series_window_limits():
    """Окно серии ВОЗВРАТА (с 1.2.0 шире, чем у сворачивания: промежуток 0,12-1,0 с, вся серия до 2 с - по тем же
    записям щелчков, 90 % промежутков 0,18-1,37 с, eval/series.py)."""
    lo, hi = series_window()
    # окно пары расширено до 1,4 с 16.10.2026: с 1,0 с пара с промежутком больше секунды не собиралась вообще
    # (владелец: «двойные щелчки не работают»), а 90 % живых промежутков укладываются в 1,37 с
    assert (lo, hi) == (0.12, 1.4)
    assert run(Clicker(mode=1, hidden=True), snaps(1.0, 1.08)) == []              # быстрее 0,12 с - не серия
    assert run(Clicker(mode=1, hidden=True), snaps(1.0, 2.6)) == []               # промежуток больше 1,4 с
    # «щёлк … щёлк» с промежутком 1,2 с - уже пара: это живой темп владельца, при окне 1,0 с она не собиралась
    assert [a for _, a in run(Clicker(mode=1, hidden=True), snaps(1.0, 2.2))] == ["restore"]
    assert [a for _, a in run(Clicker(mode=1, hidden=True), snaps(1.0, 1.95))] == ["restore"]   # 0,95 с - успели
    assert [a for _, a in run(Clicker(mode=1, hidden=True), snaps(1.0, 1.2))] == ["restore"]    # быстрая серия


def test_restore_cooldown_blocks_second_series():
    """После возврата - пауза 1,5 с: вторая серия сразу за первой не срабатывает (эхо, нервные щелчки)."""
    f = run(Clicker(mode=1, hidden=True, cooldown=1.5), snaps(1.0, 1.4, 1.8, 2.2, 2.6))
    assert len(f) == 1
    f2 = run(Clicker(mode=1, hidden=True, cooldown=1.5), snaps(1.0, 1.4) + snaps(4.0, 4.4))
    assert len(f2) == 2                   # через 2 с после паузы - можно снова


def test_fast_double_does_not_hide_in_single_mode():
    """Один щелчок сворачивает: быстрый «двойной» (0,25 с) не сворачивает - вокруг первого щелчка не было тишины
    (так было и до 16.10 - ложные срабатывания одиночного режима не выросли)."""
    assert run(Clicker(mode=1), snaps(1.0, 1.25, 1.5)) == []


def test_mode2_hides_and_restores_by_same_series():
    """Выбрано «Два щелчка» для сворачивания: та же серия сворачивает и возвращает (предупреждение в настройках)."""
    assert [a for _, a in run(Clicker(mode=2), snaps(1.0, 1.4))] == ["hide"]
    assert [a for _, a in run(Clicker(mode=2, hidden=True), snaps(1.0, 1.4))] == ["restore"]


def test_noise_around_series_blocks_restore():
    """Посторонний шум вокруг серии - возврата нет. Окно «тишины» у возврата короче (0,15 с до и после), поэтому
    удар за 0,3 с до серии её уже не отменяет: это чаще всего СВОЙ неузнанный щелчок (см. тест ниже)."""
    ck = lambda: Clicker(mode=1, hidden=True)                                     # noqa: E731
    assert run(ck(), [(0.93, False, 0.0)] + snaps(1.0, 1.4)) == []                # шум прямо перед серией
    assert run(ck(), snaps(1.0) + [(1.2, False, 0.0)] + snaps(1.4)) == []         # удар внутри серии
    assert run(ck(), snaps(1.0, 1.4) + [(1.5, False, 0.0)]) == []                 # удар сразу после серии


# ------------------------------------------------- 1.2.0: неузнанный щелчок больше не глушит следующие
def test_missed_snap_does_not_block_the_next_ones():
    """Главный баг 16.10.2026 («на третий раз перестал работать»): в 1.1.0 один неузнанный щелчок попадал в 0,5 с
    «тишины до» следующего и запрещал начинать серию - сколько ни щёлкай, возврат не срабатывал НИКОГДА
    (прогон: 12 щелчков подряд, второй мимо - ни одного возврата)."""
    for n in (4, 8, 12):
        ev = [(1.0 + 0.4 * k, k != 1, 0.0, SNAP if k != 1 else MAYBE) for k in range(n)]
        f = run(Clicker(mode=1, hidden=True), ev)
        assert [a for _, a in f][:1] == ["restore"], n


def test_every_third_snap_missed_still_restores():
    ev = [(1.0 + 0.4 * k, k % 3 != 0, 0.0, SNAP if k % 3 else MAYBE) for k in range(12)]
    f = run(Clicker(mode=1, hidden=True), ev)
    assert [a for _, a in f][:1] == ["restore"]


def test_pair_with_one_near_miss_restores():
    """Окна свёрнуты: уверенный щелчок + почти-щелчок (оценка чуть ниже порога) возвращают окна - цена ошибки
    мала, окна просто вернутся. Два почти-щелчка - НЕ возвращают."""
    assert [a for _, a in run(Clicker(mode=1, hidden=True),
                              [(1.0, False, 0.0, MAYBE), (1.4, True, 0.0, SNAP)])] == ["restore"]
    assert [a for _, a in run(Clicker(mode=1, hidden=True),
                              [(1.0, True, 0.0, SNAP), (1.4, False, 0.0, MAYBE)])] == ["restore"]
    assert run(Clicker(mode=1, hidden=True), [(1.0, False, 0.0, MAYBE), (1.4, False, 0.0, MAYBE)]) == []


def test_near_miss_never_hides_and_hide_isolation_unchanged():
    """Сворачивание не менялось (цифры 1.1.0 обязаны сохраниться): почти-щелчок не сворачивает, и любой удар
    в 0,5 с перед щелчком по-прежнему отменяет сворачивание."""
    assert run(Clicker(mode=1), [(1.0, False, 0.0, MAYBE)]) == []
    assert run(Clicker(mode=2), [(1.0, True, 0.0, SNAP), (1.4, False, 0.0, MAYBE)]) == []
    assert run(Clicker(mode=1), [(0.7, False, 0.0, MAYBE), (1.0, True, 0.0, SNAP)]) == []
    assert run(Clicker(mode=1), [(0.7, False, 0.0, NOISE), (1.0, True, 0.0, SNAP)]) == []


def test_extra_snaps_after_restore_do_not_hide_again():
    """Журнал владельца 16.10.2026: возврат в 20:21:28, а в 20:21:31 окна свернулись снова - это были его же
    щелчки, которыми он добивался возврата. Теперь после возврата сворачивание ждёт 3,5 с."""
    ev = snaps(*[1.0 + 0.4 * k for k in range(12)])
    f = run(Clicker(mode=1, hidden=True), ev, end=9, follow=True)
    assert [a for _, a in f] == ["restore"], f


def test_restore_fires_right_after_the_pair():
    """Возврат срабатывает сразу за парой (0,3 с тишины после + 0,13 с разбора), а не когда человек перестал
    щёлкать: лишние щелчки больше не отодвигают решение."""
    f = run(Clicker(mode=1, hidden=True), snaps(1.0, 1.4))
    assert 0.7 <= f[0][0] - 1.0 <= 0.9
    many = run(Clicker(mode=1, hidden=True), snaps(1.0, 1.4, 1.75, 2.1, 2.45), follow=True)
    assert [a for _, a in many] == ["restore"] and many[0][0] - 1.0 <= 0.9


def test_keyboard_series_does_not_restore():
    ev = [(1.0 + 0.18 * k, k % 4 == 0, -12.0) for k in range(30)]
    assert run(Clicker(mode=1, hidden=True), ev) == []


def test_state_changed_while_deciding_does_not_fire():
    """Пока ждали «тишину после» одиночного щелчка, окна свернулись клавишей - щелчок уже ничего не делает."""
    ck = Clicker(mode=1)
    ck.push(1.0, True, 0.0)
    ck.hidden = True
    assert ck.poll(1.5) is None and ck.hits == []


# ---------------------------------------------------------------- быстрые повторы (владелец 16.10.2026)
def test_new_snap_after_a_pause_hides_again():
    """«Щёлк - свернул, щёлк-щёлк - развернул, щёлк - свернул»: осознанный щелчок после тишины сворачивает
    окна сразу, а не ждёт 3,5 с (цена - см. ниже: эхо того же жеста по-прежнему гасится)."""
    ck = Clicker(mode=1, hidden=True)
    ck.push(10.0, True, -20.0)
    ck.push(10.4, True, -20.0)
    assert ck.poll(11.0) == "restore"
    ck.hidden = False
    t = ck.block_until + 0.1                      # пауза после срабатывания прошла, щелчков не было
    assert t < ck.no_hide_until, "иначе проверка ни о чём"
    assert t - ck.echo_t > D_QUIET, "тишина дольше, чем промежуток в серии"
    assert ck.push(t, True, -20.0) in ("series", "started"), "после тишины щелчок сворачивает"


def test_echo_snaps_right_after_restore_still_do_not_hide():
    """Его же щелчки, которыми он добивался возврата, идут подряд (около секунды) - окна не прячем."""
    ck = Clicker(mode=1, hidden=True)
    ck.push(10.0, True, -20.0)
    ck.push(10.4, True, -20.0)
    assert ck.poll(11.0) == "restore"
    ck.hidden = False
    assert ck.block_until == pytest.approx(12.5)   # 1,5 с после срабатывания не слушаем вообще
    for t in (11.2, 11.9):                         # щелчки в паузе: решения нет, но жест видно
        assert ck.push(t, True, -20.0) == "cooldown"
    for t in (12.6, 13.5, 14.2):                   # эхо продолжается: промежутки меньше 1,5 с
        assert ck.push(t, True, -20.0) == "just_restored", t


def test_echo_block_never_lasts_longer_than_before():
    ck = Clicker(mode=1, hidden=True)
    ck.push(10.0, True, -20.0)
    ck.push(10.4, True, -20.0)
    ck.poll(11.0)
    ck.hidden = False
    for t in (11.2, 11.9):
        ck.push(t, True, -20.0)
    for t in (12.6, 13.5, 14.2):                  # эхо шло подряд всё время запрета
        assert ck.push(t, True, -20.0) == "just_restored", t
    assert ck.push(15.0, True, -20.0) in ("series", "started"), "дольше 3,5 с запрет не держится"


def test_five_fast_cycles_fire_every_time():
    """Пять кругов подряд в быстром темпе: свернуть - вернуть - свернуть… каждый раз срабатывает.

    Темп - как у человека: щелчок, через 0,43 с окна свёрнуты, пауза 1,5 с, следующий жест. То есть новое
    действие возможно через ~2 с после прошлого, и ничего не «залипает» на 3,5 с, как было в 1.2.0."""
    ck = Clicker(mode=1, hidden=False)
    t = 10.0
    for i in range(5):
        ck.push(t, True, -20.0)
        assert ck.poll(t + 0.5) == "hide", f"круг {i}: не свернул"
        ck.hidden = True
        t = ck.block_until + 0.1
        ck.push(t, True, -20.0)
        ck.push(t + 0.4, True, -20.0)
        assert ck.poll(t + 1.0) == "restore", f"круг {i}: не вернул"
        ck.hidden = False
        t = ck.block_until + 0.1
    assert t - 10.0 < 25.0, "пять кругов укладываются в 25 с"


def test_one_snap_never_counts_twice():
    """Эхо щелчка в комнате приходит через 0,05-0,15 с - это тот же щелчок, а не второй."""
    ck = Clicker(mode=1, single_restores=True)
    assert ck.toggle is True
    ck.push(1.0, True, -20.0)
    assert ck.poll(1.3) == "hide"
    ck.hidden = True
    for t in (1.08, 1.2, 1.3):                     # эхо того же удара
        assert ck.push(t, True, -22.0) == "cooldown", t
    assert ck.poll(1.6) is None, "второго срабатывания от одного щелчка быть не должно"


def test_fast_toggle_answers_every_snap():
    """Владелец 16.10.2026: «щёлк, щёлк, щёлк - свернул, развернул, свернул, развернул» каждые 0,4-0,5 с."""
    ck = Clicker(mode=1, single_restores=True)
    want = []
    t = 1.0
    for i in range(10):
        ck.push(t, True, -20.0)
        at = t + 0.25
        a = ck.poll(at + 0.01)
        want.append(a)
        if a:
            ck.hidden = not ck.hidden
        t += 0.5
    assert all(want), want
    assert want[0] == "hide" and want[1] == "restore" and want[2] == "hide"


def test_two_snaps_checkbox_brings_back_the_old_behaviour():
    """Галочка «возвращать только двумя щелчками подряд» - прежнее поведение 1.2.0."""
    ck = Clicker(mode=1, hidden=True, single_restores=False)
    assert ck.toggle is False and ck.cd == 1.5
    assert run(ck, snaps(1.0)) == [], "одиночный щелчок окна не возвращает"
    assert [a for _, a in run(Clicker(mode=1, hidden=True), snaps(1.0, 1.4))] == ["restore"]


def test_toggle_profile_numbers():
    """Цифры режима переключателя - в одном месте (их видно в README и в журнале)."""
    ck = Clicker(mode=1, single_restores=True)
    assert ck.cd == 0.35 and ck.iso == (0.35, 0.12)
    ck.hidden = True
    assert ck.iso == (0.25, 0.12), "на возврат тишины нужно меньше - ошибиться там не страшно"
