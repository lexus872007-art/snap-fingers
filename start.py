# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""«Щелчок» - щёлкнул пальцами, и все окна свернулись (виден рабочий стол); щёлкнул ещё раз - окна вернулись.
Точка входа.

    Shchelchok.exe                       обычный запуск (одна копия; вторая показывает окно первой)
    Shchelchok.exe --autostart           из автозапуска Windows (сразу в трей)
    --demo main|hidden|check|checkdone|admin|fit|mode2|custom200|custom40|paused|nomic|needcal|keywarn
           |calib0|calib2|calibtest|calibdone|calibbad|toast_hide|toast_restore|toast_busy|toast_admin
                                         состояние для снимков проверки (кадр неподвижен, микрофон не включается)
    --selftest <папка>                   проверка на этом компьютере: микрофоны, звук, окна -> selftest.json
                                         (+ --gesture-test: весь путь «щелчок -> окна свернулись -> микрофон
                                          переподключился -> два щелчка -> окна вернулись» -> gesture.json)
                                         (+ --hide-test: свернуть и вернуть окна, записать, что получилось;
                                          --premin N: сначала свернуть N чужих окон «как пользователь» - проверка,
                                          что возврат их НЕ разворачивает)
    --settings <файл>                    свои настройки (тесты)
    --theme violet|blue|teal|green|red|orange|pink|graphite   цвет оформления (снимки)
"""
import argparse
import json
import math
import os
import sys
import traceback


def parse(argv):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--autostart", action="store_true")
    ap.add_argument("--hidden", action="store_true")
    ap.add_argument("--no-tray", action="store_true")
    ap.add_argument("--demo", default=None)
    ap.add_argument("--selftest", default=None)
    ap.add_argument("--hide-test", action="store_true")
    ap.add_argument("--maximize", type=int, default=0, help="развернуть N окон на весь экран до проверки")
    ap.add_argument("--gesture-test", action="store_true")
    ap.add_argument("--premin", type=int, default=0)
    ap.add_argument("--admin-sim", type=int, default=0)
    ap.add_argument("--settings", default=None)
    ap.add_argument("--quit-after", type=int, default=0)
    ap.add_argument("--theme", default=None)
    a, _ = ap.parse_known_args(argv)
    return a


def crash_log(exc):
    """Сбой - в тот же журнал, что и всё остальное (%APPDATA%\\Щелчок\\log.txt)."""
    try:
        from shchelchok import journal
        journal.write("СБОЙ: " + "".join(traceback.format_exception(exc)))
    except Exception:  # noqa: BLE001
        pass


def main(argv=None):
    args = parse(sys.argv[1:] if argv is None else argv)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Щелчок")
    app.setQuitOnLastWindowClosed(False)
    from shchelchok import app as appmod

    if not args.demo and not args.selftest and not appmod.single_instance_or_signal():
        return 0
    if args.demo or args.selftest:
        args.no_tray = True
    ctl = appmod.Controller(app, args)
    if not args.demo and not args.selftest:
        ctl.server = appmod.serve(ctl)
    if args.demo:
        QTimer.singleShot(200, lambda: run_demo(ctl, args.demo))
    if args.selftest:
        if args.gesture_test:
            QTimer.singleShot(300, lambda: run_gesture_test(ctl, args.selftest))
        else:
            QTimer.singleShot(300, lambda: run_selftest(ctl, args.selftest, args.hide_test, args.premin,
                                                        args.admin_sim, args.maximize))
    if args.quit_after:
        QTimer.singleShot(args.quit_after * 1000, ctl.quit)
    return app.exec()


DEMO_TEMPLATE = {"shape": [-14.3, -12.0, -11.0, -9.5, -8.6, -6.0, -4.9, 1.6, 6.5, 9.4, 9.9, 8.5, 7.5, 3.9],
                 "dec": [-3.1, -7.2, -15.8, -27.0, -33.5, -35.0], "peak_min": -14.0, "snr_min": 38.0,
                 "centroid": 3010.0, "spread": 2.1, "n": 5, "peak_mean": -12.0, "peak_max": -10.0,
                 # пять образцов щелчка (как после настройки 1.3.0) - с ними работают «Подобрать под меня» и
                 # оценка «узнаётся примерно на N из 100» на снимках
                 "samples": [{"shape": [v + d for v in [-14.3, -12.0, -11.0, -9.5, -8.6, -6.0, -4.9, 1.6, 6.5,
                                                        9.4, 9.9, 8.5, 7.5, 3.9]],
                              "dec": [-3.1 + d, -7.2 + d, -15.8, -27.0, -33.5, -35.0], "peak": -12.0 + d,
                              "snr": 38.0, "centroid": 3010.0}
                             for d in (-1.6, -0.8, 0.0, 0.9, 1.7)]}


DEMO_LOG = ["микрофон открыт: «Микрофон (Realtek High Definition Audio)»",
            "33 из 100 · не щелчок: похоже недостаточно (порог 60)",
            "81 из 100 · щелчок, окна свернул: 11",
            "47 из 100 · не щелчок: в этот момент печатали на клавиатуре",
            "76 из 100 · щелчок принят, жду второй щелчок (до 1 с)",
            "84 из 100 · щелчок - серия собрана",
            "вернул окна: 11"]


class HiddenStub:
    """--demo hidden: как будто окна сейчас свёрнуты нами (для снимка состояния «окна свёрнуты»)."""

    hidden = True
    saved = [1]

    def settle(self):
        pass

    def restore(self):
        return 7

    def restore_verify(self):
        return 0


def demo_scores(ctl, items):
    import time as _t
    now = _t.monotonic()
    ctl.recent.clear()
    for i, (sc, ok) in enumerate(items):
        ctl.recent.append((now - (len(items) - i) * 2.0, sc, ok))


def run_demo(ctl, state):
    """Неподвижные состояния окон для снимков (перелив стоит)."""
    s = ctl.settings
    if state.startswith("custom"):                 # «Свой» цвет с нужным оттенком: custom200, custom40
        s["theme"] = "custom"
        if state[6:].isdigit():
            s["hue"] = int(state[6:]) % 360
        ctl.apply_theme_colors()
        state = "main"
    ctl.listener.device_name = "Микрофон (Realtek High Definition Audio)"
    if state not in ("needcal", "calib0", "calib2", "calibbad"):
        s["templates"][ctl.mic_key()] = dict(DEMO_TEMPLATE)
    ctl.apply_detector()
    ctl.listener.state = "on"
    ctl.fixed_level = -38.0
    demo_scores(ctl, [(12, False), (31, False), (88, True), (8, False), (93, True), (45, False), (79, True)])
    ctl.last_event = {"score": 79.0, "reason": "", "cand": {}}
    for line in DEMO_LOG:                           # раздел «Что происходило» на снимках не пустой
        ctl.log.push(line)
    if state == "check":                            # «Проверить мой щелчок» - идёт проверка
        import time as _t
        ctl.check_until = _t.monotonic() + 23
        ctl.check_stat = [9, 3]
        ctl.log.push("проверка щелчка: слушаю 30 с - щёлкните несколько раз")
        ctl.log.push("проверка · 84 из 100 · щелчок - серия собрана")
        ctl.log.push("проверка · сработало бы: вернул окна")
        state = "main"
    if state == "checkdone":                        # проверка закончилась: итог и «учесть мои щелчки»
        ctl.check_stat = [14, 6]
        ctl.check_snaps = [(s, {}) for s in (27, 46, 52, 58, 64, 70)]
        ctl.check_result = "ваши щелчки: от 27 до 70, порог сейчас 45, предлагаю 40"
        ctl.log.push("проверка закончена: звуков 14, похожих на щелчок 6 · " + ctl.check_result)
        state = "main"
    if state == "admin":                            # окно «от имени администратора» нам не подчинилось
        s["admin"] = True
        ctl.admin_seen = [(1, "Командная строка")]
        ctl.log.push("окно «Командная строка» запущено от имени администратора - свернуть/вернуть его без прав "
                     "нельзя (чтобы и такие окна слушались, включите «Запускать с правами администратора» в окне "
                     "«Щелчок»)")
        state = "main"
    extra = state if state in ("fit",) else ""
    if state == "fit":                              # «Подобрать под меня» - показана подсказка с числами
        state = "main"
    if state == "paused":
        s["listening"] = False
        ctl.listener.state = "off"
        ctl.fixed_level = None
    elif state == "nomic":
        ctl.listener.state = "nomic"
        ctl.fixed_level = None
        ctl.listener.device_name = ""
    if state in ("main", "hidden", "mode2", "paused", "nomic", "needcal", "keywarn"):
        if state == "keywarn":
            s["hotkeys"]["toggle"] = "Ctrl+Alt+P"
            s["mode"] = 3
        if state == "mode2":
            s["mode"] = 2                      # свернуть и вернуть одной серией - видно предупреждение
            s["back"] = 2                      # (так настроит тот, кому важнее защита от случайного шума)
        if state == "hidden":
            ctl.hider = HiddenStub()           # «окна свёрнуты» - состояние для снимка
        ctl.open_main()
        ctl.main.t_fixed = 1.3
        ctl.main.refresh()
        if state == "keywarn":
            ctl.main.key_changed(save=False)
        if extra == "fit":
            ctl.main.fit_clicked()
        ctl.main.adjustSize()
    elif state.startswith("calib"):
        ctl.open_calibration()
        c = ctl.calib
        c.t_fixed = 1.3
        from shchelchok.calib import NEED, STEP_HINT
        if state == "calib2":
            c.dots.set_done(2)
            c.msg.setText(f"Есть! Жду щелчок 3 из {NEED}… {STEP_HINT[2]}")
        elif state in ("calibtest", "calibdone"):
            c.dots.set_done(NEED)
            c.stage = "test"
            c.scores.show()
            c.lead.setText("Готово! Проверьте: щёлкните ещё раз - точка на шкале должна уйти вправо, за жёлтую черту.")
            c.msg.setText(ctl.last_text())
            c.result.setText("Ваш щелчок узнаётся примерно на 86 из 100 - это хорошо. Оценки ваших щелчков: "
                             "от 52 до 78, порог 45. Образцов: 5.")
            c.result.setVisible(True)
            if state == "calibdone":                 # настройка вышла плохой - честно предлагаем переснять
                c.result.setText("Ваш щелчок узнаётся примерно на 41 из 100 - это мало. Оценки ваших щелчков: "
                                 "от 28 до 49, порог 45. Образцов: 4.")
                c.advice.setText("Лучше переснять настройку: щёлкайте ближе к микрофону - щелчок приходит тихим; "
                                 "щёлкайте резче - щелчок должен быть звонким, а не глухим.")
                c.advice.setVisible(True)
            c.done_b.setEnabled(True)
        elif state == "calibbad":
            c.dots.set_done(0)
            c.msg.setText("Щелчки получились очень разными - давайте ещё раз, одинаково")
        c.adjustSize()
    elif state == "toast_hide":
        ctl.toast.show_message("Свернул", f"7 окон. {ctl.back_hint()}", ms=600000)
    elif state == "toast_restore":
        ctl.toast.show_message("Вернул", "7 окон на месте.", ms=600000)
    elif state == "toast_admin":
        ctl.toast.show_message("Окно от администратора",
                               "1 окно не слушается без прав - включите «Запускать с правами администратора» "
                               "в окне «Щелчок».", ms=600000)
    elif state == "toast_busy":
        ctl.toast.show_message("Клавиша занята", "Ctrl+Alt+Z - занято другой программой. Поменяйте в окне «Щелчок».",
                               ms=600000)


# ---------------------------------------------------------------- проверка жеста на этом компьютере
def snap_samples(rnd, centroid=2900.0, decay_ms=9.0, peak=0.5, sr=16000):
    """Щелчок пальцами «на пальцах»: всплеск высокого шума + два резонанса с быстрым затуханием (без numpy -
    чтобы работало внутри собранной программы). Нужен для проверки всего пути: звук -> детектор -> окна."""
    n = int(0.08 * sr)
    d = decay_ms / 1000.0
    ph1, ph2 = rnd.uniform(0, 6.28), rnd.uniform(0, 6.28)
    out, prev = [], 0.0
    for i in range(n):
        t = i / sr
        e = math.exp(-t / d)
        w = rnd.uniform(-1.0, 1.0)
        hp, prev = w - prev, w                     # разность белого шума - энергия выше по частоте
        v = hp * e
        v += 0.5 * math.sin(2 * math.pi * centroid * t + ph1) * math.exp(-t / (d * 0.8))
        v += 0.3 * math.sin(2 * math.pi * centroid * 1.45 * t + ph2) * math.exp(-t / (d * 0.8))
        out.append(v)
    for i in range(6):                             # атака ~0,4 мс
        out[i] *= i / 6.0
    m = max(abs(v) for v in out) or 1.0
    return [peak * v / m for v in out]


def snap_track(rnd, seconds, at_times, sr=16000, peaks=None):
    """Дорожка int16: тихий фон комнаты + щелчки в заданные секунды (peaks - своя громкость каждому щелчку:
    тихий щелчок программа узнаёт хуже - так проверяется «промахнулся и щёлкнул ещё раз»)."""
    n = int(seconds * sr)
    y = [0.0015 * rnd.uniform(-1.0, 1.0) for _ in range(n)]
    for k, at in enumerate(at_times):
        cl = snap_samples(rnd, peak=(peaks[k] if peaks else 0.5))
        i0 = int(at * sr)
        for j, v in enumerate(cl):
            if i0 + j < n:
                y[i0 + j] += v
    return [max(-32767, min(32767, int(v * 32767))) for v in y]


def run_gesture_test(ctl, out):
    """Весь путь внутри настоящей программы: щелчок -> окна свернулись; микрофон переподключился;
    ДВА щелчка -> все окна вернулись. Звук синтетический (настоящего микрофона под Wine нет)."""
    import random
    import time as _t
    from PySide6.QtCore import QTimer
    from shchelchok import detector, journal, winapi
    os.makedirs(out, exist_ok=True)
    rnd = random.Random(7)
    res = {"version": __import__("shchelchok").__version__}

    def feed(track):
        for i in range(0, len(track), 480):
            ctl.listener.feed_samples(track[i:i + 480], mono=_t.monotonic())
        ctl.tick()

    def settle(seconds=0.5):
        """Дать Windows выполнить команды окнам (они асинхронные) - иначе состояние окон читается раньше, чем
        оно изменилось, и «порядок тот же» выходит ложным не по вине программы."""
        from PySide6.QtWidgets import QApplication
        end = _t.monotonic() + seconds
        while _t.monotonic() < end:
            QApplication.processEvents()
            _t.sleep(0.01)

    def step_hide():
        # калибровка: 3 щелчка тем же «голосом», как в окне «Настройка щелчка»
        cands = []
        fe = detector.Frontend()
        track = snap_track(rnd, 5.0, (1.0, 2.2, 3.4))
        for i in range(0, len(track), 480):
            cands += fe.feed(track[i:i + 480])
        good = [c for c in cands if not detector.gates(c, strict=False)]
        ok, why = detector.calib_consistent(good[:3])
        res.update(calib_candidates=len(cands), calib_good=len(good), calib_ok=bool(ok), calib_why=why)
        ctl.settings["templates"][ctl.mic_key()] = detector.make_template(good[:3])
        ctl.apply_detector()
        res["windows_before"] = len(winapi.app_windows())
        feed(snap_track(rnd, 3.0, (1.5,)))                     # ОДИН щелчок - свернуть
        res["hidden_after_one_snap"] = bool(ctl.hider.hidden)
        res["hide_saved"] = len(ctl.hider.saved or [])
        res["minimized"] = [winapi.is_minimized(h) for h in (ctl.hider.saved or [])]
        res["state_text_hidden"] = ctl.state_text()
        open(os.path.join(out, "hidden.flag"), "w").close()     # проверка снимает экран «свёрнуто»
        QTimer.singleShot(3000, step_restore)

    def step_restore():
        # микрофон «отвалился» и переподключился (баг 16.10: после этого программа глохла навсегда)
        t_before = ctl.listener.det.front.t
        ctl.listener.state = "on"                               # как будто поток был открыт и замолчал
        ctl.listener.last_data = _t.monotonic() - 5
        ctl.listener.watchdog(now=_t.monotonic())
        res["reconnects"] = ctl.listener.reconnects
        res["stream_time_before_reconnect"] = round(t_before, 2)
        res["stream_time_after_reconnect"] = round(ctl.listener.det.front.t, 2)
        res["block_until"] = round(ctl.listener.det.clicker.block_until, 2)
        res["deaf_seconds_left"] = round(ctl.listener.det.clicker.block_until - ctl.listener.det.front.t, 2)
        feed(snap_track(rnd, 4.0, (2.0, 2.45)))                 # ДВА щелчка - вернуть все окна
        res["hidden_after_two_snaps"] = bool(ctl.hider.hidden)
        res["shown_after_restore"] = [winapi.is_shown(h) for h in (ctl.hider.last or [])]
        res["state_text_after"] = ctl.state_text()
        QTimer.singleShot(1500, step_chain)

    def step_chain():
        """Главная жалоба 16.10.2026: «на третий раз перестал работать». Владелец щёлкает ПОДРЯД, и часть щелчков
        программа не узнаёт - возврат обязан сработать всё равно, а лишние щелчки не должны свернуть окна снова."""
        feed(snap_track(rnd, 4.0, ()))                          # тишина: запрет «не сворачивать после возврата» прошёл
        feed(snap_track(rnd, 3.0, (1.5,)))                      # снова свернули одним щелчком
        res["chain_hidden"] = bool(ctl.hider.hidden)
        n0 = len(ctl.hider.saved or [])
        res["chain_saved"] = n0
        feed(snap_track(rnd, 2.0, ()))                          # тишина: пауза после срабатывания прошла
        # восемь щелчков подряд, каждый второй тихий (такие программа узнаёт хуже - это и есть «промах»)
        times = [1.0 + 0.45 * k for k in range(8)]
        feed(snap_track(rnd, 6.0, times, peaks=[0.5 if k % 2 == 0 else 0.1 for k in range(8)]))
        res["chain_hidden_after"] = bool(ctl.hider.hidden)
        res["chain_shown"] = [winapi.is_shown(h) for h in (ctl.hider.last or [])]
        res["chain_restored_count"] = len([h for h in (ctl.hider.last or []) if winapi.is_shown(h)])
        res["chain_saved_before"] = n0
        QTimer.singleShot(1000, step_fast_cycles)

    def step_fast_cycles():
        """Требование владельца 17.10.2026: «щёлк - свернул, щёлк-щёлк - развернул, щёлк - свернул» подряд -
        каждый раз срабатывает, порядок окон тот же, ничего не виснет. Проверяем настоящими окнами."""
        if ctl.hider.hidden:
            ctl.toggle_windows()
        rows = []
        for _ in range(5):
            feed(snap_track(rnd, 2.2, ()))                      # тишина: эхо прошлого жеста кончилось
            before = [h for h in winapi.app_windows()]
            fg = winapi.foreground()
            feed(snap_track(rnd, 2.5, (1.0,)))                  # один щелчок - свернуть
            hid = bool(ctl.hider.hidden)
            settle(0.3)
            feed(snap_track(rnd, 1.6, ()))                      # пауза после срабатывания
            feed(snap_track(rnd, 2.5, (1.0, 1.45)))             # щелчок (или два) - вернуть
            back = not ctl.hider.hidden
            settle()
            after = [h for h in winapi.app_windows() if h in before]
            want = [h for h in before if winapi.is_shown(h)]
            # активное до сворачивания окно программа НАРОЧНО поднимает наверх (фокус - прежнему окну), поэтому
            # «тот же порядок» = прежний порядок с этим окном сверху
            want_fg = ([fg] + [h for h in want if h != fg]) if fg in want else want
            rows.append({"свернул": hid, "вернул": back, "окон": len(before), "активное": fg,
                         "порядок до": before, "порядок после": after,
                         "порядок тот же": after in (want, want_fg)})
        res["fast_cycles"] = rows
        res["journal"] = journal.tail(60)
        with open(os.path.join(out, "gesture.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        QTimer.singleShot(1500, ctl.quit)

    step_hide()


def admin_sim(n):
    """Эмуляция окна «от имени администратора» для проверки под Wine: уровни целостности Windows Wine не
    изображает, поэтому первые n окон объявляем «от администратора» и ПО-НАСТОЯЩЕМУ перестаём ими управлять -
    ровно так же, как это делает Windows (наши вызовы молча ничего не делают). Дальше всё настоящее: окна, их
    состояние по Win32, журнал, тексты в окне. -> список hwnd «от администратора»."""
    from shchelchok import winapi
    wins = winapi.app_windows()[:n]
    if not wins:
        return []
    mini, rest, rights = winapi.minimize, winapi.restore, winapi.window_rights
    winapi.minimize = lambda h: None if h in wins else mini(h)
    winapi.restore = lambda h: None if h in wins else rest(h)
    winapi.window_rights = lambda h: winapi.ADMIN if h in wins else rights(h)
    return wins


def _places(hwnds):
    """[[номер окна, развёрнуто(3)/обычное(1), [слева, сверху, справа, снизу]]] - для сравнения чисел."""
    from shchelchok import winapi
    out = []
    for h in hwnds:
        p = winapi.get_placement(h) or {}
        out.append([h, p.get("show"), list(p.get("rect") or ())])
    return out


def run_selftest(ctl, out, hide_test=False, premin=0, admin=0, maximize=0):
    """Проверка на этом компьютере (без щелчков): какие микрофоны видны, открывается ли микрофон и есть ли уровень,
    работает ли счётчик звука компьютера, какие окна свернёт программа. --hide-test - свернуть, проверить,
    вернуть, проверить. --premin N - сначала свернуть N чужих окон «как пользователь»: после возврата они ОБЯЗАНЫ
    остаться свёрнутыми (баг 15.10.2026 «иногда показывает другие папки»)."""
    from PySide6.QtCore import QTimer
    from shchelchok import audio, syscom, winapi
    os.makedirs(out, exist_ok=True)
    res = {"mics": audio.list_mics(), "mute": syscom.mute_get()}
    admin_wins = admin_sim(admin) if admin else []
    res["admin_windows"] = admin_wins
    res["admin_titles"] = [winapi.window_title(h) for h in admin_wins]
    user_min = []
    if premin:
        user_min = winapi.app_windows()[:premin]          # «пользователь свернул сам» - до нашего щелчка
        for h in user_min:
            winapi.minimize(h)
        res["user_minimized"] = user_min
    # --maximize N: развернуть N окон на весь экран ДО проверки. Главный случай владельца 17.10.2026:
    # «развернул на весь экран» -> свернул -> вернул; команда SW_RESTORE возвращала окно в обычный размер.
    if maximize:
        ws = winapi.app_windows()
        for h in ws[:maximize]:
            winapi.maximize(h)
        # остальные окна расставляем по РАЗНЫМ местам: иначе под Wine все «Блокноты» лежат в одной точке и
        # проверка «вернулось на то же место» ничего не доказывает
        for i, h in enumerate(ws[maximize:]):
            winapi.set_placement(h, {"show": 1, "rect": (40 + 90 * i, 30 + 70 * i, 640 + 90 * i, 450 + 70 * i)})
    ctl.outmeter.start()
    err = ctl.listener.start(ctl.settings["mic"])
    res["mic_error"] = err
    res["mic_name"] = ctl.listener.device_name
    wins = []
    levels = []

    def sample():
        levels.append(round(ctl.listener.level_db, 1))

    t = QTimer(ctl)
    t.timeout.connect(sample)
    t.start(100)

    def finish():
        t.stop()
        res["mic_levels_db"] = levels
        res["mic_state"] = ctl.listener.state
        res["output_meter_ok"] = ctl.outmeter.ok
        res["capture_id"] = bool(ctl.outmeter.capture_id)
        wins[:] = winapi.app_windows()            # уже без тех, что «свернул пользователь» (--premin)
        res["windows"] = [{"hwnd": h, "title": winapi._title(winapi.wt.HWND(h)) if winapi.WIN else ""} for h in wins]
        res["places_before"] = _places(wins)      # где и какого размера окна ДО сворачивания
        if hide_test:
            step_hide()
        else:
            write()

    def step_hide():
        n = ctl.hider.hide()
        res["hide_count"] = n
        res["minimized_before"] = list(ctl.hider.before)
        res["user_min_in_saved"] = [h for h in user_min if h in (ctl.hider.saved or [])]
        res["admin_detected"] = sorted(ctl.hider.admin)
        QTimer.singleShot(1200, step_check)

    def step_check():
        res["left_after_verify"] = ctl.hider.verify()
        res["minimized_after_hide"] = [winapi.is_minimized(h) for h in (ctl.hider.saved or [])]
        res["not_hidden"] = ctl.hider.not_hidden()
        ctl.verify_hidden_final()                      # честная строка про окна «от администратора» - в журнал
        res["admin_note"] = ctl.admin_note()
        open(os.path.join(out, "hidden.flag"), "w").close()          # проверка снимает экран «свёрнуто»
        QTimer.singleShot(2500, step_restore)

    def step_restore():
        res["restored"] = ctl.hider.restore()
        QTimer.singleShot(1200, step_after)

    def step_after():
        res["left_after_restore"] = ctl.hider.restore_verify()
        # ТЕ ЖЕ места и размеры (владелец 17.10.2026): сравниваем числа, а не «похоже на то же место»
        res["places_after"] = _places(wins)
        before = {h: (sh, r) for h, sh, r in res["places_before"]}
        res["places_same"] = [h for h, sh, r in res["places_after"] if before.get(h) == (sh, r)]
        res["places_diff"] = [[h, before.get(h), [sh, r]] for h, sh, r in res["places_after"]
                              if before.get(h) != (sh, r)]
        res["shown_after_restore"] = [winapi.is_shown(h) for h in wins]
        res["not_restored"] = ctl.hider.not_restored()
        res["not_restored_admin"] = [t for _, t in ctl.hider.admin_windows(ctl.hider.not_restored())]
        # главное в проверке --premin: окна, свёрнутые пользователем ДО щелчка, остались свёрнутыми
        res["user_minimized_still_min"] = [winapi.is_minimized(h) for h in user_min]
        # порядок наложения: окна обязаны встать так, как стояли (требование владельца 17.10.2026)
        ours = [h for h in wins if h not in admin_wins]      # окна «от администратора» не наши: их Windows
        res["order_before"] = ours                            # нам не отдаёт, порядок остальных от этого не ломается
        res["order_after"] = [h for h in winapi.app_windows() if h in ours]
        res["order_same"] = res["order_after"] == [h for h in ours if winapi.is_shown(h)]
        ctl.restore_final()
        step_speed()

    def step_speed():
        """Сколько миллисекунд занимают сами действия и пять кругов «свернул - вернул» подряд."""
        import time as _t
        ms = lambda t0: round((_t.perf_counter() - t0) * 1000, 1)   # noqa: E731
        t0 = _t.perf_counter()
        all_w = winapi.app_windows()
        res["ms_enum_windows"] = ms(t0)
        t0 = _t.perf_counter()
        rights = [winapi.window_rights(h) for h in all_w]
        res["ms_rights_all"] = ms(t0)
        t0 = _t.perf_counter()
        [winapi.window_rights(h) for h in all_w]
        res["ms_rights_cached"] = ms(t0)
        res["rights"] = rights
        res["windows_count"] = len(all_w)
        # пять кругов «свернул - вернул» подряд: между действиями даём Windows 0,4 с на выполнение (команды
        # окнам асинхронные), иначе мы считаем состояние окон раньше, чем оно изменилось
        res["cycles"] = []

        def cycle(i=0, stage="hide", t0=[None]):
            if i >= 5:
                from shchelchok import journal as jr
                res["journal"] = jr.tail(25)
                return write()
            if stage == "hide":
                before = [h for h in winapi.app_windows()]
                places = _places(before)              # ДО сворачивания: у свёрнутого окна места уже не спросишь
                t0[0] = _t.perf_counter()
                n = ctl.hider.hide()
                res["cycles"].append({"свернул": n, "мс": ms(t0[0]), "окон было": len(before),
                                      "порядок до": before, "места до": places})
                QTimer.singleShot(400, lambda: cycle(i, "restore"))
                return None
            row = res["cycles"][-1]
            t0[0] = _t.perf_counter()
            k = ctl.hider.restore()
            row["вернул"] = k
            row["мс возврата"] = ms(t0[0])
            def check():
                after = [h for h in winapi.app_windows() if h in row["порядок до"]]
                row["порядок тот же"] = after == [h for h in row["порядок до"] if winapi.is_shown(h)]
                row["порядок после"] = after
                # и геометрия: пять кругов подряд не должны ничего сдвинуть (владелец 17.10.2026)
                row["места те же"] = _places(row["порядок до"]) == row["места до"]
                cycle(i + 1, "hide")
            QTimer.singleShot(400, check)
            return None

        cycle()

    def write():
        with open(os.path.join(out, "selftest.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        QTimer.singleShot(200, ctl.quit)

    QTimer.singleShot(2500, finish)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        crash_log(e)
        raise
