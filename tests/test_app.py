"""Программа целиком (без Windows): срабатывание -> свернуть/вернуть, пауза, калибровка, звук, защита, одна копия."""
import types

import numpy as np
import pytest

import conftest
from conftest import calibrated, run_front
from eval import synth as S
from shchelchok import detector
from test_hider import FakeAPI


def make_ctl(qapp, tmp_path, **kw):
    from shchelchok import app as appmod
    args = types.SimpleNamespace(autostart=False, hidden=False, no_tray=True, demo=None, selftest="x",
                                 settings=str(tmp_path / "s.json"), quit_after=0, hide_test=False)
    ctl = appmod.Controller(qapp, args)
    ctl.demo = True
    api = FakeAPI([11, 12, 13])
    ctl.hider.api = api
    ctl.settings.update(kw)
    conftest.TRACKED.append(ctl)        # упал тест - окна и микрофон всё равно закроет conftest
    return ctl, api


def test_word_windows():
    from shchelchok.app import word_windows
    assert [word_windows(n) for n in (1, 2, 5, 11, 21, 22, 25, 112)] == \
        ["1 окно", "2 окна", "5 окон", "11 окон", "21 окно", "22 окна", "25 окон", "112 окон"]


def test_fire_hides_then_restores(qapp, tmp_path):
    ctl, api = make_ctl(qapp, tmp_path)
    ctl.listener.out.append(("fire", "hide"))
    ctl.tick()
    assert all(api.state[h] == "min" for h in (11, 12, 13))
    assert ctl.listener.det.clicker.hidden is True          # детектор знает: следующая серия возвращает
    ctl.listener.out.append(("fire", "restore"))
    ctl.tick()
    assert all(api.state[h] == "shown" for h in (11, 12, 13))
    assert ctl.listener.det.clicker.hidden is False
    ctl.listener.shutdown()


def test_fire_ignored_when_state_already_changed(qapp, tmp_path):
    """Окна уже вернули клавишей - запоздавшее «вернуть» их не сворачивает, и наоборот."""
    ctl, api = make_ctl(qapp, tmp_path)
    ctl.listener.out.append(("fire", "restore"))            # окна на месте - возвращать нечего
    ctl.tick()
    assert api.log == []
    ctl.toggle_windows()                                    # свернули клавишей
    api.log.clear()
    ctl.listener.out.append(("fire", "hide"))               # запоздавшее «свернуть» - уже свёрнуто
    ctl.tick()
    assert api.log == [] and all(api.state[h] == "min" for h in (11, 12, 13))
    ctl.listener.shutdown()


def test_detector_learns_user_restored_windows(qapp, tmp_path):
    """Окна вернули мимо нас (панель задач) - следующий одиночный щелчок снова сворачивает (проверка по таймеру)."""
    ctl, api = make_ctl(qapp, tmp_path)
    ctl.toggle_windows()
    assert ctl.listener.det.clicker.hidden is True
    for h in (11, 12, 13):
        api.state[h] = "shown"                   # пользователь развернул сам
    ctl.watchdog()
    assert ctl.listener.det.clicker.hidden is False
    ctl.listener.out.append(("fire", "hide"))
    ctl.tick()
    assert all(api.state[h] == "min" for h in (11, 12, 13))
    ctl.listener.shutdown()


def test_custom_color_picker(qapp, tmp_path):
    """«Свой» цвет (жалоба владельца 15.10): ползунок оттенка виден только у «Своего», таскание красит окно сразу,
    значение сохраняется, Esc возвращает прежний цвет."""
    from shchelchok import brand, settings
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.open_main()
    w = ctl.main
    assert not w.theme.hue_box.isVisible()                 # пресет - ползунка нет (нечего им настраивать)
    w.theme.set_value("custom:200")                        # выбрали кружок «Свой»
    assert w.theme.hue_box.isVisible() and w.theme.hue.value() == 200
    assert "200" in w.theme.hue_num.text()
    assert ctl.settings["theme"] == "custom" and ctl.settings["hue"] == 200
    hue200 = brand.PALETTE[2]
    w.theme.hue.setValue(40)                               # потащили ползунок - цвет меняется сразу
    assert ctl.settings["hue"] == 40 and brand.PALETTE[2] != hue200
    ctl.save_now()
    assert settings.theme_value(settings.load(ctl.args.settings)) == "custom:40"
    w.theme.set_value("blue")
    assert not w.theme.hue_box.isVisible() and ctl.settings["theme"] == "blue"
    ctl.listener.shutdown()


def test_escape_returns_previous_color(qapp, tmp_path):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from shchelchok import settings
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.set_theme("green")
    ctl.open_main()
    w = ctl.main
    w.theme.set_value("custom:300")
    assert settings.theme_value(ctl.settings) == "custom:300"
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert settings.theme_value(ctl.settings) == "green" and w.theme.value == "green"
    ctl.listener.shutdown()


def test_restore_choice_reaches_detector(qapp, tmp_path):
    """По умолчанию один щелчок переключает; в настройках - два или три подряд (страховка)."""
    ctl, _ = make_ctl(qapp, tmp_path)
    ck = ctl.listener.det.clicker
    assert ctl.settings["back"] == 1 and ck.restore_n == 1 and ck.toggle is True
    for n in (2, 3, 1):
        ctl.set_back(n)
        assert ck.restore_n == n and ck.toggle is (n == 1)
    ctl.listener.shutdown()


def test_back_hint_text(qapp, tmp_path):
    ctl, _ = make_ctl(qapp, tmp_path)
    assert "Щёлкните ещё раз" in ctl.back_hint() and "Ctrl+Alt+Z" in ctl.back_hint()
    assert "все окна" in ctl.back_hint()
    ctl.set_back(2)
    assert "Два щелчка подряд" in ctl.back_hint()
    ctl.set_back(3)
    assert "Три щелчка подряд" in ctl.back_hint()
    ctl.listener.shutdown()


def test_restore_all_keeps_user_minimized(qapp, tmp_path):
    """Трей «Вернуть все окна»: чужие свёрнутые окна остаются свёрнутыми (баг «показывает другие папки»)."""
    ctl, api = make_ctl(qapp, tmp_path)
    api.state[13] = "min"                                   # пользователь свернул сам до щелчка
    ctl.toggle_windows()
    ctl.restore_all()
    assert api.state[11] == "shown" and api.state[12] == "shown" and api.state[13] == "min"
    assert api.shell == []
    ctl.listener.shutdown()


def test_no_action_while_calibrating_or_paused(qapp, tmp_path):
    ctl, api = make_ctl(qapp, tmp_path)
    ctl.open_calibration()
    ctl.listener.out.append(("fire", "hide"))
    ctl.tick()
    assert api.log == []
    ctl.calib.close()
    ctl.settings["listening"] = False
    ctl.listener.out.append(("fire", "hide"))
    ctl.tick()
    assert api.log == []
    ctl.listener.shutdown()


def test_mute_and_unmute(qapp, tmp_path, monkeypatch):
    from shchelchok import syscom
    state = {"mute": False}
    monkeypatch.setattr(syscom, "mute_get", lambda: state["mute"])
    monkeypatch.setattr(syscom, "mute_set", lambda on: state.update(mute=on) or True)
    ctl, api = make_ctl(qapp, tmp_path, mute=True, unmute=True)
    ctl.toggle_windows()
    assert state["mute"] is True
    ctl.toggle_windows()
    assert state["mute"] is False
    state["mute"] = True                 # звук был выключен ещё до щелчка - так и оставляем
    ctl.toggle_windows()
    ctl.toggle_windows()
    assert state["mute"] is True
    ctl.listener.shutdown()


def test_guard_respects_settings(qapp, tmp_path):
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.inputs.times.append((100.0, "key"))
    assert ctl.guard(100.1) == "нажали клавишу"
    ctl.inputs.times.clear()
    ctl.inputs.times.append((100.0, "mouse"))
    assert ctl.guard(100.1) == "щёлкнули мышью"
    ctl.settings["ignore_typing"] = False
    assert ctl.guard(100.1) is None
    ctl.outmeter.hist.extend([(99.0 + i * 0.01, 0.02) for i in range(100)] + [(100.05, 0.8)])
    assert ctl.guard(100.1) == "звук компьютера"
    ctl.settings["ignore_output"] = False
    assert ctl.guard(100.1) is None
    ctl.listener.shutdown()


def test_main_window_restores_after_toggle(qapp, tmp_path):
    ctl, api = make_ctl(qapp, tmp_path)
    ctl.open_main()
    assert ctl.main.isVisible()
    ctl.toggle_windows()
    assert not ctl.main.isVisible()          # своё окно тоже не остаётся на рабочем столе
    ctl.toggle_windows()
    qapp.processEvents()
    import time
    t = time.monotonic()
    while time.monotonic() - t < 0.6:
        qapp.processEvents()
    assert ctl.main.isVisible()
    ctl.listener.shutdown()


def test_calibration_window_flow(qapp, tmp_path):
    ctl, _ = make_ctl(qapp, tmp_path)
    rng = np.random.default_rng(5)
    ctl.open_calibration()
    cw = ctl.calib
    from shchelchok.calib import NEED
    bed = S.room(rng, 2 + 1.5 * NEED, 0.003)
    for k in range(NEED):
        S.place(bed, S.snap(rng, centroid=3100, decay_ms=8), 1.5 + 1.5 * k)
    cands = run_front(bed)
    cw.on_candidate(cands[0])
    assert cw.dots.done == 1 and f"2 из {NEED}" in cw.msg.text()
    for c in cands[1:]:
        cw.on_candidate(c)
    assert cw.stage == "test" and ctl.template() is not None
    assert len(ctl.template()["samples"]) >= NEED - 1, "образцы щелчка хранятся все, а не только среднее"
    assert "из 100" in cw.result.text() and cw.result.isVisible(), "итог настройки числом не показан"
    from shchelchok import settings
    assert settings.load(ctl.args.settings)["templates"]          # шаблон сохранён на диск
    assert settings.load(ctl.args.settings)["templates"][ctl.mic_key()]["samples"]
    cw.close()
    ctl.listener.shutdown()


def test_calibration_rejects_knock_with_hint(qapp, tmp_path):
    ctl, _ = make_ctl(qapp, tmp_path)
    rng = np.random.default_rng(6)
    ctl.open_calibration()
    bed = S.room(rng, 3, 0.002)
    S.place(bed, S.knock(rng), 1.0)
    for c in run_front(bed):
        ctl.calib.on_candidate(c)
    assert ctl.calib.dots.done == 0 and "Жду щелчок 1" not in ctl.calib.msg.text()
    ctl.calib.close()
    ctl.listener.shutdown()


def test_status(qapp, tmp_path):
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.listener.state = "on"
    assert ctl.status() == "needcal"
    ctl.set_template(calibrated(np.random.default_rng(1)))
    assert ctl.status() == "on"
    ctl.listener.state = "nomic"
    assert ctl.status() == "nomic"
    ctl.settings["listening"] = False
    assert ctl.status() == "off"
    ctl.listener.shutdown()


def test_mode_and_sens_reach_detector(qapp, tmp_path):
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.set_mode(2)
    ctl.set_sens(8)
    assert ctl.listener.det.clicker.mode == 2 and ctl.listener.det.sens == 8
    ctl.listener.shutdown()


def test_single_instance_signal(qapp, tmp_path):
    from shchelchok import app as appmod
    ctl, _ = make_ctl(qapp, tmp_path)
    called = []
    ctl.another_copy = lambda: called.append(1)
    srv = appmod.serve(ctl)
    assert appmod.single_instance_or_signal() is False          # вторая копия: сигнал первой и выход
    import time
    t = time.monotonic()
    while not called and time.monotonic() - t < 3:
        qapp.processEvents()
    assert called
    srv.close()
    assert appmod.single_instance_or_signal() is True           # первой копии нет - эта и есть первая
    ctl.listener.shutdown()


# ---------------------------------------------------------------- жалобы владельца 16.10.2026
def test_hotkey_stays_registered_while_window_is_open(qapp, tmp_path, monkeypatch):
    """«Обратно не восстанавливает»: окно «Щелчок» снимало запасную клавишу на всё время, пока открыто, а при
    сворачивании окно прячется (не закрывается) - и Ctrl+Alt+Z не работал ровно тогда, когда он нужнее всего."""
    from shchelchok import winapi
    reg = []
    monkeypatch.setattr(winapi, "register_hotkey", lambda hw, i, m, v: reg.append(("reg", i)) or True)
    monkeypatch.setattr(winapi, "unregister_hotkey", lambda hw, i: reg.append(("unreg", i)))
    ctl, api = make_ctl(qapp, tmp_path)
    ctl.register_hotkeys()
    ctl.open_main()
    qapp.processEvents()
    reg.clear()
    ctl.toggle_windows()                              # окна свернулись, своё окно спряталось
    qapp.processEvents()
    assert ("unreg", 1) not in reg, "клавиша снята - вернуть окна будет нечем"
    ctl.on_hotkey(1)                                  # Ctrl+Alt+Z при открытом окне - возвращает окна
    assert all(api.state[h] == "shown" for h in (11, 12, 13))
    ctl.listener.shutdown()


def test_key_field_takes_hotkey_only_while_focused(qapp, tmp_path, monkeypatch):
    """Ctrl+Alt+… должно попадать в поле ввода клавиши - но только пока курсор в этом поле."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent
    from shchelchok import winapi
    reg = []
    monkeypatch.setattr(winapi, "register_hotkey", lambda hw, i, m, v: reg.append("reg") or True)
    monkeypatch.setattr(winapi, "unregister_hotkey", lambda hw, i: reg.append("unreg"))
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.open_main()
    w = ctl.main
    reg.clear()
    qapp.sendEvent(w.key, QFocusEvent(QEvent.FocusIn))
    assert reg == ["unreg"]
    qapp.sendEvent(w.key, QFocusEvent(QEvent.FocusOut))
    assert reg[-1] == "reg"
    ctl.listener.shutdown()


def test_window_says_windows_are_hidden(qapp, tmp_path):
    """Окно должно человеческими словами говорить, что происходит (требование владельца 16.10.2026)."""
    ctl, api = make_ctl(qapp, tmp_path)
    ctl.set_template(calibrated(np.random.default_rng(1)))
    ctl.listener.state = "on"
    ctl.open_main()
    assert ctl.status() == "on" and ctl.state_text() == "Слушаю"
    ctl.toggle_windows()
    assert ctl.status() == "hidden"
    assert "Окна свёрнуты" in ctl.state_text() and "щёлкните ещё раз" in ctl.state_text()
    ctl.main.refresh()
    assert "Окна свёрнуты" in ctl.main.status.text() and ctl.main.test_b.text() == "Вернуть все окна"
    ctl.toggle_windows()
    assert ctl.status() == "on"
    ctl.main.refresh()
    assert ctl.main.test_b.text() == "Свернуть сейчас"
    # окна свёрнуты, а микрофон пропал - говорим про микрофон (щелчками окна уже не вернуть)
    ctl.toggle_windows()
    ctl.listener.state = "nomic"
    assert ctl.status() == "nomic" and ctl.state_text() == "Не слышу микрофон"
    ctl.listener.shutdown()


def test_window_says_mic_is_not_heard(qapp, tmp_path):
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.set_template(calibrated(np.random.default_rng(1)))
    ctl.listener.state = "nomic"
    assert ctl.state_text() == "Не слышу микрофон"
    ctl.listener.state = "on"
    ctl.demo = False                                  # поток открыт, но звука из него нет - тоже «не слышу»
    ctl.listener.last_data = 0.0
    assert ctl.status() == "nomic" and ctl.state_text() == "Не слышу микрофон"
    ctl.listener.shutdown()


def test_template_survives_mic_renamed_by_windows(qapp, tmp_path):
    """Windows отдала микрофон под другим именем - программа берёт имеющуюся настройку, а не глохнет с «нужна
    настройка» (иначе щелчки молча перестают работать)."""
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.listener.device_name = "Микрофон (Realtek)"
    ctl.set_template(calibrated(np.random.default_rng(1)))
    assert ctl.status() in ("on", "hidden")
    ctl.listener.device_name = "Микрофон (Realtek High Definition Audio)"
    assert ctl.template() is not None and ctl.status() in ("on", "hidden")
    ctl.settings["templates"]["Гарнитура"] = dict(ctl.settings["templates"]["Микрофон (Realtek)"])
    ctl.listener.device_name = "Третий микрофон"      # две настройки - угадывать нельзя, нужна калибровка
    assert ctl.template() is None and ctl.status() == "needcal"
    ctl.listener.shutdown()


def test_actions_written_to_journal(qapp, tmp_path):
    """Свернул/вернул - в журнал: иначе «не работает» не отличить от «не услышал»."""
    from shchelchok import journal
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.toggle_windows()
    ctl.toggle_windows()
    lines = journal.tail(20)
    assert any("свернул окна: 3" in s for s in lines) and any("вернул окна: 3" in s for s in lines), lines
    ctl.listener.shutdown()


# ---------------------------------------------------------------- 1.2.0: журнал событий, проверка, микрофон
def test_journal_says_why_a_sound_did_not_fire(qapp, tmp_path):
    """Главное требование владельца 16.10.2026: в журнале видно ПОЧЕМУ не сработало, а не только удачи."""
    from shchelchok import detector as D, journal
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.calib = None
    ctl.listener.det.clicker.hidden = True          # окна свёрнуты: ждём второй щелчок до 1 с
    ctl.listener.out.append(("event", {"score": 41.0, "thr": 60.0, "ok": False, "kind": D.MAYBE,
                                       "reason": "не похоже на щелчок", "verdict": "maybe", "t": 1.0,
                                       "cand": {"snr": 20.0}}))
    ctl.listener.out.append(("event", {"score": 77.0, "thr": 60.0, "ok": False, "kind": D.MAYBE,
                                       "reason": "нажали клавишу", "verdict": "maybe", "t": 2.0,
                                       "cand": {"snr": 20.0}}))
    ctl.listener.out.append(("miss", ("timeout", 3.0)))
    ctl.tick()
    lines = journal.tail(20)
    assert any("41 из 100" in s and "похоже недостаточно (порог 60)" in s for s in lines), lines
    assert any("в этот момент печатали на клавиатуре" in s for s in lines), lines
    assert any("не дождался второго щелчка (ждал 1,4 с)" in s for s in lines), lines
    assert len(ctl.log.lines(10)) >= 3            # то же видно в окне «Что происходило»
    ctl.listener.shutdown()


def test_noise_does_not_flood_the_journal(qapp, tmp_path):
    """Посторонние звуки идут числом в сводке - иначе журнал забит шумом и щелчок в нём не найти."""
    from shchelchok import detector as D, journal
    ctl, _ = make_ctl(qapp, tmp_path)
    for i in range(30):
        ctl.listener.out.append(("event", {"score": 8.0, "thr": 60.0, "ok": False, "kind": D.NOISE,
                                           "reason": "долгий звук", "verdict": "noise", "t": float(i),
                                           "cand": {"snr": 20.0}}))
    ctl.tick()
    assert ctl.log.noise == 30
    assert not any("долгий звук" in s for s in journal.tail(40))
    ctl.listener.shutdown()


def test_check_mode_shows_sounds_and_never_touches_windows(qapp, tmp_path):
    """«Проверить мой щелчок»: 30 с показываем оценку каждого звука, окна при этом НЕ трогаем."""
    from shchelchok import detector as D
    ctl, api = make_ctl(qapp, tmp_path)
    ctl.start_check()
    assert ctl.checking and 25 <= ctl.check_left() <= 30
    ctl.listener.out.append(("event", {"score": 9.0, "thr": 60.0, "ok": False, "kind": D.NOISE,
                                       "reason": "долгий звук", "verdict": "noise", "t": 1.0,
                                       "cand": {"snr": 5.0}}))
    ctl.listener.out.append(("fire", "hide"))
    ctl.tick()
    assert api.log == [] and all(api.state[h] == "shown" for h in (11, 12, 13))     # окна не тронули
    assert ctl.check_stat[0] == 1                                                   # тихий звук тоже показан
    assert any("проверка · 9 из 100" in s for s in ctl.log.lines(10)), ctl.log.lines(10)
    assert any("сработало бы: свернул окна" in s for s in ctl.log.lines(10))
    ctl.stop_check()
    assert not ctl.checking and any("проверка закончена" in s for s in ctl.log.lines(10))
    ctl.listener.out.append(("fire", "hide"))                                       # после проверки - работает
    ctl.tick()
    assert all(api.state[h] == "min" for h in (11, 12, 13))
    ctl.listener.shutdown()


def test_guard_window_is_narrow_when_windows_are_hidden(qapp, tmp_path):
    """Владелец работает за ноутбуком: широкая защита «печатаю» глушила возврат почти всё время. Когда окна
    свёрнуты, защита узкая - нажатие за 0,2 с до щелчка возврат уже не отменяет, а сворачивание - отменяет."""
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.inputs.times.append((100.0, "key"))
    ctl.listener.det.clicker.hidden = False
    assert ctl.guard(100.2) == "нажали клавишу"
    ctl.listener.det.clicker.hidden = True
    assert ctl.guard(100.2) is None
    assert ctl.guard(100.05) == "нажали клавишу"        # сам удар по клавише - всё равно не щелчок
    ctl.listener.shutdown()


def test_silent_mic_is_reported(qapp, tmp_path):
    """Микрофон выключен в Windows: звук идёт, но это полная тишина - программа обязана это СКАЗАТЬ."""
    import time as _t
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.demo = False
    ctl.listener.state = "on"
    ctl.listener.last_data = _t.monotonic()
    ctl.listener.det.front.level_db = -100.0
    now = _t.monotonic()
    assert ctl.check_mic_mute(now) is False                      # ждём, а не кричим сразу
    assert ctl.check_mic_mute(now + 11) is True
    assert ctl.status() == "silent" and ctl.state_text() == "Микрофон молчит"
    assert any("микрофон молчит" in s for s in ctl.log.lines(5))
    ctl.listener.det.front.level_db = -45.0
    assert ctl.check_mic_mute(now + 12) is False and ctl.status() == "needcal"   # дальше - обычная проверка
    ctl.listener.shutdown()


def test_no_empty_mic_name_in_journal(qapp, tmp_path):
    """Баг 16.10.2026: в журнале владельца «микрофон «» без своей настройки» - имя ещё не пришло, а строка уже
    есть. Пока микрофон не открыт, про настройку не пишем."""
    from shchelchok import journal
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.settings["templates"]["Набор микрофонов (Realtek(R) Au"] = calibrated(np.random.default_rng(2))
    ctl.listener.state = "off"
    ctl.listener.device_name = ""
    ctl.template()
    assert not any("микрофон «»" in s for s in journal.tail(20)), journal.tail(20)
    ctl.listener.state = "on"
    ctl.listener.device_name = "Набор микрофонов (Realtek(R) Audio)"      # Windows отдала полное имя
    assert ctl.template() is not None
    assert any("то же устройство под другим именем" in s for s in journal.tail(20)), journal.tail(20)
    ctl.listener.shutdown()


def test_extra_snaps_after_restore_do_not_hide_windows_again(qapp, tmp_path):
    """Журнал владельца: вернул окна 20:21:28, свернул снова 20:21:31 - это были его же щелчки."""
    ctl, api = make_ctl(qapp, tmp_path)
    ctl.toggle_windows()                              # свернули
    ctl.listener.out.append(("fire", "restore"))
    ctl.tick()
    assert all(api.state[h] == "shown" for h in (11, 12, 13))
    ck = ctl.listener.det.clicker
    # Прежнее поведение (возврат двумя щелчками): после возврата лишние щелчки окна не прячут
    ctl.set_back(2)
    ck.hidden = True
    ck.push(20.0, True, -20.0)
    ck.push(20.4, True, -20.0)
    assert ck.poll(21.0) == "restore"
    ck.hidden = False
    assert ck.no_hide_until > 0
    for te in (21.5, 22.2):                           # его же щелчки в паузе после срабатывания
        assert ck.push(te, True, -20.0) == "cooldown"
    t = ck.block_until + 0.1
    assert ck.push(t, True, 0.0) == "just_restored", "щелчок сразу после возврата - эхо жеста"
    assert ck.push(t + 0.9, True, 0.0) == "just_restored", "эхо идёт подряд - окна не прячем"
    # а вот осознанный щелчок после тишины 1,5 с сворачивает сразу (владелец 16.10.2026: щёлкает подряд)
    assert ck.push(t + 2.6, True, 0.0) in ("series", "started")
    ctl.listener.shutdown()


# ---------------------------------------------------------------- порог в окне, подбор, дообучение (1.3.0)
def test_window_slider_shows_the_same_threshold_as_journal(qapp, tmp_path):
    """Ползунок, подпись рядом и строка журнала «похоже недостаточно (порог 45)» - одно и то же число
    (владелец 16.10.2026: «все возле 44 порога», а по окну этого было не понять)."""
    from shchelchok import events, settings
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.set_thr(40)
    ctl.open_main()
    w = ctl.main
    assert w.sens.value() == 40 and w.sens.minimum() == settings.THR_MIN and w.sens.maximum() == settings.THR_MAX
    assert w.sens.singleStep() == 1, "шаг - 1 очко, а не 5"
    assert w.sens_l.text() == "щелчок от 40 из 100"
    line = events.describe({"score": 38, "thr": ctl.threshold(), "ok": False, "reason": "не похоже на щелчок"})
    assert "порог 40" in line
    w.sens.setValue(38)                                  # двигаем ползунок - порог применяется сразу
    assert ctl.settings["thr"] == 38 and ctl.listener.det.thr == 38
    assert "Ниже 35" not in w.thr_hint.text()
    w.sens.setValue(30)
    assert "Ниже 35" in w.thr_hint.text(), "про посторонние звуки надо предупредить честно"
    w.close()
    ctl.listener.shutdown()


def test_threshold_survives_restart(qapp, tmp_path):
    from shchelchok import settings
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.set_thr(39)
    ctl.save_now()
    assert settings.load(ctl.args.settings)["thr"] == 39
    ctl.listener.shutdown()


def test_fit_button_sets_threshold_and_says_real_numbers(qapp, tmp_path):
    """«Подобрать под меня»: порог по образцам щелчка и по шуму комнаты + честные числа в окне."""
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.set_template(calibrated(np.random.default_rng(3)))
    ctl.set_thr(70)                                      # заведомо строгий порог
    ctl.open_main()
    w = ctl.main
    w.fit_clicked()
    assert ctl.settings["thr"] < 70 and w.sens.value() == ctl.settings["thr"]
    assert w.fit_l.isVisible() and "Предлагаю порог" in w.fit_l.text()
    assert str(ctl.settings["thr"]) in w.fit_l.text()
    w.close()
    ctl.listener.shutdown()


def test_fit_keeps_threshold_above_room_noise(qapp, tmp_path):
    """В комнате есть звуки, похожие на щелчок - порог ниже них не опускаем (иначе окна поедут сами)."""
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.set_template(calibrated(np.random.default_rng(4)))
    for _ in range(3):
        ctl.scores.add(48, False)                        # посторонние звуки с высокой оценкой
    info = ctl.suggest()
    assert info["thr"] >= 51 and info["noise_max"] == 48
    ctl.listener.shutdown()


def test_check_run_gives_summary_and_can_learn(qapp, tmp_path):
    """Режим «Проверить мой щелчок»: итог словами + кнопка «Это были мои щелчки - учесть» (дообучение)."""
    rng = np.random.default_rng(11)
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.set_template(calibrated(rng))
    ctl.open_main()
    w = ctl.main
    before = len(ctl.template()["samples"])
    ctl.start_check()
    bed = S.room(rng, 6, 0.003)
    for k in range(3):
        S.place(bed, S.snap(rng, centroid=2900, decay_ms=9), 1.2 + 1.5 * k)
    for c in run_front(bed):
        ctl.listener.out.append(("event", ctl.listener.det.judge_event(c) if hasattr(ctl.listener.det, "judge_event")
                                 else _event(ctl, c)))
    ctl.tick()
    ctl.stop_check()
    assert ctl.check_snaps, "щелчки проверки запомнены"
    assert "ваши щелчки: от" in ctl.check_result and "порог сейчас" in ctl.check_result
    w.refresh()
    assert w.learn_b.isVisible(), "кнопка «учесть мои щелчки» не показана"
    w.learn_clicked()
    assert len(ctl.template()["samples"]) > before, "образцов стало больше - программа дообучилась"
    assert "Учёл ваши щелчки" in w.fit_l.text()
    w.close()
    ctl.listener.shutdown()


def _event(ctl, c):
    from shchelchok import detector as D
    ev = D.judge(c, ctl.template(), ctl.listener.det.sens, thr=ctl.threshold())
    ev.update(t=c["t"], cand=c, verdict="series", hidden=False, need=1, gap_max=1.0)
    return ev


def test_quiet_snaps_bring_mic_hint(qapp, tmp_path):
    """Микрофон «Набор микрофонов (Realtek)» сам давит короткие звуки - об этом надо сказать, а не молча плохо
    работать (журнал владельца: «тише, чем на настройке»)."""
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.listener.device_name = "Набор микрофонов (Realtek(R) Au"
    assert ctl.mic_enhanced() and "Улучшения звука" in ctl.mic_hint()
    for _ in range(3):
        ctl.note_quiet({"reason": "тише щелчка", "ok": False, "score": 30})
    assert any("тише, чем на настройке" in s for s in ctl.log.lines(5))
    ctl.listener.device_name = "Микрофон (USB)"
    assert ctl.mic_hint() == ""
    ctl.listener.shutdown()


# ---------------------------------------------------------------- жалобы владельца 16.10.2026 (журнал 1.3.0)
def test_restore_choice_is_saved_and_applied(qapp, tmp_path):
    """«Двойные щелчки я поставил, по-моему, они не работают»: выбор обязан попасть и в файл, и в детектор."""
    from shchelchok import settings
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.open_main()
    w = ctl.main
    w.back_btns[2].setChecked(True)
    assert ctl.settings["back"] == 2 and ctl.listener.det.clicker.restore_n == 2
    ctl.save_now()
    assert settings.load(ctl.args.settings)["back"] == 2
    w.back_btns[3].setChecked(True)
    ctl.save_now()
    assert settings.load(ctl.args.settings)["back"] == 3 and ctl.listener.det.clicker.restore_n == 3
    assert "Три щелчка подряд" in w.back_l.text()
    w.close()
    ctl.listener.shutdown()


def test_two_snaps_with_a_slow_rhythm_restore_windows(qapp, tmp_path):
    """Его темп - щелчок примерно раз в секунду. Пара с промежутком 1,2 с обязана возвращать окна
    (до 16.10.2026 окно пары было 1,0 с, и такая пара не собиралась ВООБЩЕ)."""
    rng = np.random.default_rng(3)
    ctl, api = make_ctl(qapp, tmp_path, back=2)
    ctl.set_template(calibrated(rng))
    ctl.apply_detector()
    ctl.toggle_windows()                                   # окна свёрнуты
    assert ctl.hider.hidden
    bed = S.room(rng, 6, 0.003)
    for at in (1.5, 2.7):                                  # промежуток 1,2 с
        S.place(bed, S.snap(rng, centroid=2900, decay_ms=9), at)
    for c in run_front(bed):
        ctl.listener.det.clicker.push(c["t"], True, c["peak"], detector.SNAP)
    fired = ctl.listener.det.clicker.poll(4.0)
    assert fired == "restore", "пара с промежутком 1,2 с не собралась"
    ctl.listener.shutdown()


def test_no_waiting_message_when_one_snap_is_enough(qapp, tmp_path):
    """В журнале владельца 8 строк «не дождался второго щелчка», хотя у него возврат одним щелчком."""
    ctl, _ = make_ctl(qapp, tmp_path)
    ck = ctl.listener.det.clicker
    ck.hidden = True
    assert ck.push(10.0, False, -20.0, detector.MAYBE) == "maybe"
    assert ck.poll(12.0) is None
    assert ck.take_miss() is None, "ждать второго щелчка, когда он не нужен, - нечего"
    ctl.listener.shutdown()


def test_startup_line_says_the_real_restore_setting(qapp, tmp_path):
    from shchelchok import journal
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.demo = False
    ctl.settings["back"] = 1
    ctl.startup_notes()
    ctl.demo = True
    journal.write("запуск: версия 1.3.1, возврат окон - " + ("один щелчок" if ctl.settings["back"] == 1 else "x"))
    assert any("возврат окон - один щелчок" in s for s in journal.tail(5))
    ctl.listener.shutdown()


def test_old_template_asks_to_recalibrate(qapp, tmp_path):
    """У владельца настройка осталась от прежней версии (3 щелчка, без образцов) - программа должна сказать."""
    ctl, _ = make_ctl(qapp, tmp_path)
    old = calibrated(np.random.default_rng(1))
    old.pop("samples", None)
    old["n"] = 3
    ctl.set_template(old)
    assert ctl.old_template() is True
    assert "Переснимите" in ctl.calib_hint()
    ctl.open_main()
    ctl.main.refresh()
    assert ctl.main.calib_l.isVisible()
    rng = np.random.default_rng(7)
    fresh = calibrated(rng)
    fresh["samples"] = [detector.sample_of({"shape": fresh["shape"], "dec": fresh["dec"], "peak": -12.0})
                        for _ in range(5)]
    ctl.set_template(fresh)
    assert ctl.old_template() is False and ctl.calib_hint() == ""
    ctl.main.close()
    ctl.listener.shutdown()


def test_update_window_asks_before_downloading(qapp, tmp_path):
    """Ничего не качается и не ставится без ответа человека."""
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.demo = False
    info = {"version": "9.9.9", "notes": "новое и полезное"}
    ctl.open_update(info)
    w = ctl.update_win
    assert w.isVisible() and "9.9.9" in w.windowTitle() + w.findChildren(type(w.what))[0].text() + w.what.text()
    assert "новое и полезное" in w.what.text()
    assert w.go_b.isVisible() and w.later_b.isVisible()
    w.later()                                              # «Позже»
    assert ctl.settings["update_later"] == "9.9.9"
    assert ctl.updater.ask_due("9.9.9") is False
    ctl.demo = True
    ctl.listener.shutdown()


def test_update_check_button_does_not_block_the_window(qapp, tmp_path):
    ctl, _ = make_ctl(qapp, tmp_path)
    ctl.open_main()
    ctl.demo = False
    calls = []
    ctl.updater.check_async = lambda done: calls.append(done) or True
    assert ctl.check_updates_now() is True and calls
    calls[0]({"version": "9.9.9"})                         # ответ пришёл из потока
    assert ctl.upd._found["version"] == "9.9.9", "ответ потока ждёт своей очереди, окно его не трогает"
    ctl.update_tick()
    assert ctl.update_win is not None and ctl.update_win.isVisible()
    ctl.update_win.close()
    ctl.demo = True
    ctl.main.close()
    ctl.listener.shutdown()
