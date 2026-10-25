# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Управление программой: микрофон и детектор, свернуть/вернуть окна, звук компьютера, защита от своего звука и
клавиатуры, окна «Щелчок» и «Настройка щелчка», трей, запасная клавиша, одна копия."""
from __future__ import annotations

import os
import time
from collections import deque

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from . import brand, detector, events, journal, settings, syscom, tuning, update, winapi
from .app_update_qt import UpdateWindow as _UpdateWindow
from .audio import Listener
from .events import word_windows
from .hider import Hider
from .settings import TITLE
from .toast import Toast

HK_TOGGLE = 1
CHECK_S = 30            # «Проверить мой щелчок»: столько секунд слушаем и показываем каждый звук
# Защита «клавиатура/мышь» и «звук компьютера»: когда окна свёрнуты, окна защиты узкие - иначе возврат не
# пробиться (владелец работает за ноутбуком, при окне 0,3/0,2 с защита глушит 79 % времени, eval/pressure.py)
GUARD_WIDE = {"typing": (0.3, 0.2), "output": (0.35, 0.12)}
GUARD_BACK = {"typing": (0.1, 0.06), "output": (0.15, 0.08)}
SILENT_DB, SILENT_S = -80.0, 10.0       # столько секунд полной тишины в звуке - «микрофон молчит»
def calib_need():
    """Сколько щелчков просит окно настройки (одно место на программу)."""
    from .calib import NEED
    return NEED


ADMIN_LOG_EVERY = 20.0                  # про окна «от администратора» пишем не чаще (иначе 4 строки на жест)
SERVER = f"{settings.APP}-{os.environ.get('USERNAME') or os.environ.get('USER') or 'u'}"

MENU_QSS = """
QMenu { background: #3A1080; color: white; border: 1px solid rgba(255,255,255,60); border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 26px 7px 14px; border-radius: 7px; }
QMenu::item:selected { background: rgba(255,255,255,55); }
QMenu::separator { height: 1px; background: rgba(255,255,255,50); margin: 5px 8px; }
QMenu::indicator { width: 14px; height: 14px; }
QToolTip { background: #2A0A5E; color: white; border: 1px solid rgba(255,255,255,70); border-radius: 6px; padding: 5px 8px; }
"""


# Микрофоны, которые Windows сама «улучшает» (подавление шума и автоусиление): короткий щелчок такой микрофон
# приглушает, и оценки падают - об этом надо сказать человеку, а не молча плохо работать.
ENHANCED_MIC = ("набор микрофонов", "microphone array", "стерео микшер", "stereo mix")
MIC_HINT = ("Это «набор микрофонов»: Windows сама давит короткие звуки и убавляет громкость. Если щелчок "
            "узнаётся плохо - Параметры Windows → Система → Звук → этот микрофон → выключите «Улучшения звука».")


class UpdateWindow(_UpdateWindow):
    """Общее окно «Вышла версия X», но неудача называет ПУТЬ К ЖУРНАЛУ: окно говорит коротко, а настоящая
    причина (какая ошибка, на каком шаге) остаётся в журнале, и человеку надо знать, что прислать.

    Общий `app_update_qt.py` (копия `_brand`) для этого править не нужно - достаточно переопределить
    `finished`. Перенос строки тут не нужен: надпись с переносом слов (`wrap=True`)."""

    def finished(self, ok, text):
        if not ok:
            text = f"{text} Журнал программы: {journal.path()}"
        super().finished(ok, text)


class HotkeyWindow(QWidget):
    """Невидимое окно - получатель WM_HOTKEY от Windows."""

    def __init__(self, ctl):
        super().__init__(None, Qt.Tool)
        self.ctl = ctl
        self.winId()

    def nativeEvent(self, etype, message):
        try:
            if bytes(etype) == b"windows_generic_MSG":
                msg, wparam = winapi.parse_msg(message)
                if msg == winapi.WM_HOTKEY:
                    QTimer.singleShot(0, lambda w=int(wparam): self.ctl.on_hotkey(w))
                    return True, 0
        except Exception:  # noqa: BLE001
            pass
        return False, 0


class Controller(QObject):
    def __init__(self, app: QApplication, args):
        super().__init__()
        self.app = app
        self.args = args
        self.settings = settings.load(args.settings)
        if getattr(args, "theme", None):
            self.settings["theme"] = args.theme
        brand.load_fonts()
        self.apply_theme_colors()
        self.demo = bool(args.demo or args.selftest)
        self.outmeter = syscom.OutputMeter()
        self.inputs = winapi.InputWatch()
        self.listener = Listener(guard=self.guard)
        self.hider = Hider()
        self.toast = Toast(self)
        self.hk = HotkeyWindow(self)
        self.main = None
        self.calib = None
        self.recent = deque(maxlen=14)          # (monotonic, оценка, щелчок?)
        self.last_event = None
        self.muted_by_us = False
        self.prev_mute = None
        self.reopen_main = False
        self.hk_failed = []
        self.fixed_level = None                 # --demo
        self.tray = None
        self._tpl_note = None
        self.log = events.EventLog()            # «Что происходило»: окно + файл журнала
        journal.set_hook(self.log.push)         # строки сторожа микрофона тоже видны в окне
        self.check_until = 0.0                  # «Проверить мой щелчок»: до какого времени слушаем
        self.check_stat = [0, 0]                # [звуков, из них щелчков] за проверку
        self.check_snaps = []                   # [(оценка, удар)] - похожие на щелчок звуки за проверку
        self.check_result = ""                  # итог проверки словами (его видно в окне)
        self.mic_mute = False                   # микрофон отдаёт полную тишину (выключен в Windows)
        self._silent_since = None
        self.scores = tuning.ScoreHistory()     # оценки звуков - для кнопки «Подобрать под меня»
        self.admin_seen = []                    # окна «от имени администратора», которые нам не подчинились
        self._admin_said = False                # про такие окна плашку показываем один раз за сеанс
        self._quiet_hits = 0                    # сколько раз звук был «тише, чем на настройке»
        self._mic_hint_said = False
        # самообновление: раз в неделю тихо смотрим сервер и СПРАШИВАЕМ человека (владелец 16.10.2026).
        # Механизм общий на всю линейку (app_update.py), своё здесь - только окно вопроса и журнал.
        self.updater = update.make(__import__("shchelchok").__version__, self.settings, log=self.log.add,
                                   save=self.save_later)
        self.upd = update.Controller(self.updater, self.open_update, quit=self.quit, on_checked=self.update_said, exit_hard=True)
        self.update_win = None
        if not self.demo:
            back = self.settings["back"]
            journal.note_move()          # первый запуск после обновления: где лежал прежний журнал
            journal.write(f"запуск: версия {__import__('shchelchok').__version__}, возврат окон - "
                          + ("один щелчок" if back == 1 else settings.back_series(back, lower=True)))
        if QSystemTrayIcon.isSystemTrayAvailable() and not args.no_tray:
            self.make_tray()
        self.apply_detector()
        self.register_hotkeys()
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.tick)
        self.wd = QTimer(self)
        self.wd.setInterval(1000)
        self.wd.timeout.connect(self.watchdog)
        if not self.demo:
            self.outmeter.start()
            self.inputs.start()
            if self.settings["listening"]:
                self.listener.start(self.settings["mic"])
            self.apply_detector()
            self.timer.start()
            self.wd.start()
            if self.settings["autostart"] and not self.settings["admin"]:
                winapi.autostart_set(TITLE, True)      # путь к программе мог смениться после обновления
            self.startup_notes()
            QTimer.singleShot(300, self.first_screen)

    def apply_theme_colors(self):
        """Цвет оформления -> палитра, стили, значки (сам перелив тот же)."""
        brand.set_theme(self.settings["theme"], self.settings["hue"])
        self.app.setStyleSheet(brand.tint_css(MENU_QSS))
        self.icon = QIcon(QPixmap.fromImage(brand.app_icon_image(256)))
        self.icon_paused = QIcon(QPixmap.fromImage(brand.app_icon_image(256, paused=True)))
        self.app.setWindowIcon(self.icon)

    def set_theme(self, name, hue=None):
        self.settings["theme"] = name
        if hue is not None:
            self.settings["hue"] = int(hue) % 360
        self.apply_theme_colors()
        from . import ui
        for w in (self.main, self.calib):
            if w is not None:
                w.setStyleSheet(ui.qss())
                w.setWindowIcon(self.icon)
                w.update()
                if hasattr(w, "refresh"):
                    w.refresh()
        self.update_tray()
        self.save_later()

    # ------------------------------------------------------------ старт
    def first_screen(self):
        if self.template() is None:
            self.open_calibration()
        elif not self.args.autostart and not self.args.hidden:
            self.open_main()
        if self.listener.state == "nomic" and self.settings["listening"]:
            self.toast.show_message("Жду микрофон", self.listener.error or "Микрофон не найден.", ms=6000)

    # ------------------------------------------------------------ детектор
    def mic_key(self):
        return self.listener.device_name or self.settings["mic"] or ""

    def mic_name(self):
        return self.listener.device_name or self.settings["mic"] or "как в Windows"

    def template(self):
        """Шаблон щелчка для текущего микрофона. Windows отдаёт одно и то же устройство то под полным именем, то
        обрезанным до 31 знака (так устроен общий режим), поэтому ищем ещё и по началу имени, и лишь потом берём
        единственную имеющуюся настройку. Пока микрофон не открыт, имени нет - в журнал об этом не пишем, иначе
        в нём появляется «микрофон «» без своей настройки» на каждом запуске (баг 16.10.2026)."""
        tp = self.settings["templates"]
        key = self.mic_key()
        t = tp.get(key) or (tp.get("") if not self.listener.device_name else None)
        how = "своя настройка"
        if t is None and key:
            match = settings.match_template_key(tp, key)
            if match:
                t, how = tp[match], f"настройка «{match}» (то же устройство под другим именем)"
                key = match
        if t is None and len(tp) == 1:
            key, t = next(iter(tp.items()))
            how = f"единственная настройка «{key}»"
        if t is not None and how != "своя настройка" and self.listener.state == "on":
            if self._tpl_note != (self.mic_key(), key):
                self._tpl_note = (self.mic_key(), key)
                self.log.add(f"микрофон «{self.mic_name()}»: беру {how}")
        return t

    def apply_detector(self):
        d = self.listener.det
        d.template = self.template()
        d.thr = float(self.settings["thr"])
        d.sens = detector.sens_of_thr(d.thr)      # допуск по громкости идёт от того же порога
        if d.clicker.mode != self.settings["mode"]:
            d.set_mode(self.settings["mode"])
        self.sync_windows_state()

    def sync_windows_state(self):
        """Состояние окон -> детектор: свёрнуты нами - возвращает серия из трёх щелчков (одиночный - только с
        галочкой). Пользователь мог вернуть окна сам (панель задач) - проверяем и по таймеру."""
        self.listener.det.set_windows(self.hider.hidden, self.settings["back"])

    def threshold(self):
        """Порог оценки «это щелчок»: одно число, его же видно в окне и в журнале («порог 45»)."""
        return float(self.settings["thr"])

    def mic_enhanced(self):
        """Микрофон, который Windows сама «улучшает» (подавление шума, автоусиление) - щелчок от этого тише."""
        name = (self.mic_name() or "").lower()
        return any(k in name for k in ENHANCED_MIC)

    def mic_hint(self):
        """Подсказка про микрофон или пусто (в окне и в окне настройки)."""
        return MIC_HINT if self.mic_enhanced() else ""

    def old_template(self):
        """Настройка снята прежней версией (3 щелчка, без образцов)? Тогда программа узнаёт хуже, чем могла бы:
        шаблон по трём громким щелчкам не похож на живой вялый щелчок (журнал владельца 16.10.2026)."""
        t = self.template()
        if t is None:
            return False
        return len(t.get("samples") or ()) < calib_need() - 1

    def calib_hint(self):
        """Строка в окне: стоит переснять настройку (или пусто)."""
        if not self.old_template():
            return ""
        return (f"Настройка снята в прежней версии ({int(self.template().get('n', 3))} щелчка). Переснимите - "
                f"программа будет узнавать ваш щелчок заметно лучше.")

    def suggest(self):
        """Что предложить по порогу: свои щелчки (настройка + подтверждённые живые) и посторонние звуки."""
        own = tuning.loo_scores(self.calib_samples(), thr=self.threshold()) + self.scores.own()
        noise = self.scores.noise()
        info = tuning.suggest_threshold(own, noise, cur=self.threshold())
        info["text"] = tuning.suggest_text(info, self.threshold(), noise_count=len(noise))
        return info

    def calib_samples(self):
        """Образцы щелчка из настройки (их несколько - щелчок не повторяется один в один)."""
        t = self.template() or {}
        return [s for s in (t.get("samples") or ()) if isinstance(s, dict) and "shape" in s]

    def apply_suggested(self):
        """Кнопка «Подобрать под меня»: ставим предложенный порог и говорим, что получилось."""
        info = self.suggest()
        self.set_thr(info["thr"])
        self.log.add(f"порог подобран: {info['thr']} ({info['text']})")
        return info

    def guard(self, mono):
        """Из потока детектора: удар совпал с клавиатурой/мышью или со звуком самого компьютера -> не щелчок.

        Когда окна СВЁРНУТЫ, окна защиты узкие: цена ошибки мала (окна просто вернутся), а широкая защита
        оставляла программу глухой почти всё время, пока владелец работает за ноутбуком."""
        s = self.settings
        g = GUARD_BACK if self.listener.det.clicker.hidden else GUARD_WIDE
        if s["ignore_typing"]:
            kind = self.inputs.near_kind(mono, *g["typing"])
            if kind == "mouse":
                return "щёлкнули мышью"
            if kind is not None:
                return "нажали клавишу"
        if s["ignore_output"] and self.outmeter.hit(mono, before=g["output"][0], after=g["output"][1]):
            return "звук компьютера"
        return None

    def status(self):
        """Состояние программы человеческими словами (окно и трей): off - пауза, nomic - не слышу микрофон,
        silent - микрофон открыт, но в звуке полная тишина (выключен в Windows), needcal - нужна настройка,
        hidden - окна свёрнуты (ждём возврата), on - слушаю."""
        if not self.settings["listening"]:
            return "off"
        if self.listener.state == "nomic" or self.mic_silent():
            return "nomic"
        if self.mic_mute:
            return "silent"
        if self.hider.hidden:              # окна спрятаны - это сейчас главное, что нужно сказать человеку
            return "hidden"
        if self.template() is None:
            return "needcal"
        return "on"

    def mic_silent(self):
        """Поток открыт, а звука из него нет дольше, чем терпит сторож (сейчас как раз переподключается)."""
        if self.demo or self.listener.state != "on":
            return False
        return time.monotonic() - self.listener.last_data > self.listener.STALL_S

    def check_mic_mute(self, now=None):
        """Микрофон отдаёт звук, но это полная тишина (микрофон выключен в Windows или на гарнитуре) - программа
        тогда не услышит ничего и должна об этом СКАЗАТЬ, а не молчать. -> True, если молчит."""
        now = time.monotonic() if now is None else now
        if self.demo or self.listener.state != "on" or self.listener.level_db > SILENT_DB:
            self._silent_since, self.mic_mute = None, False
            return False
        if self._silent_since is None:
            self._silent_since = now
        if now - self._silent_since >= SILENT_S and not self.mic_mute:
            self.mic_mute = True
            self.log.add("микрофон молчит: в звуке полная тишина - проверьте микрофон в Windows")
        return self.mic_mute

    def state_text(self):
        """Строка состояния для окна и подсказки трея."""
        if self.status() == "hidden":
            return f"Окна свёрнуты - {self.back_hint(short=True)}, чтобы вернуть"
        return {"on": "Слушаю", "off": "Пауза", "nomic": "Не слышу микрофон",
                "silent": "Микрофон молчит", "needcal": "Нужна настройка"}[self.status()]

    def mic_level(self):
        if self.fixed_level is not None:
            return self.fixed_level
        return self.listener.level_db if self.listener.state == "on" else None

    def recent_scores(self):
        return list(self.recent)

    def last_text(self):
        e = self.last_event
        if e is None:
            return "Щёлкните пальцами - здесь появится оценка звука."
        sc = int(round(e["score"]))
        if not e["reason"]:
            return f"Последний звук: {sc} из 100 - щелчок"
        return f"Последний звук: {sc} из 100 - не щелчок ({e['reason']})"

    def tick(self):
        """Каждые 30 мс: события детектора -> шкалы и журнал, срабатывание -> свернуть/вернуть."""
        for kind, e in self.listener.drain():
            if kind == "event":
                c = e["cand"]
                if self.calib is not None:
                    self.calib.on_candidate(c)
                if c["snr"] >= 12:
                    self.recent.append((time.monotonic(), e["score"], not e["reason"]))
                    self.last_event = e
                    self.scores.add(e["score"], not e["reason"])
                    self.note_quiet(e)
                if self.checking and e["kind"] in (detector.SNAP, detector.MAYBE):
                    self.check_snaps.append((e["score"], c))
                self.note_event(e)
            elif kind == "miss":
                self.note_miss(e)
            elif kind == "fire" and self.calib is None and self.settings["listening"]:
                if self.checking:
                    self.log.add(f"проверка · сработало бы: {'вернул окна' if e == 'restore' else 'свернул окна'}")
                else:
                    self.do_action(e)
        self.log.flush_noise()
        if self.checking and time.monotonic() >= self.check_until:
            self.finish_check()
        for w in (self.main, self.calib):
            if w is not None and w.isVisible():
                w.refresh()

    # ------------------------------------------------------------ журнал событий
    @property
    def checking(self):
        return time.monotonic() < self.check_until

    def note_event(self, e):
        """Звук -> строка в журнал («что происходило»): почему сработало или почему нет."""
        if self.calib is not None:
            return
        need, _ = self.listener.det.clicker.targets()
        text = events.describe(e, need=max(need), gap_max=self.listener.det.clicker.gaps[1])
        if self.checking:
            self.check_stat[0] += 1
            self.check_stat[1] += 1 if e["ok"] else 0
            self.log.add("проверка · " + text)
        elif events.worth_line(e):
            self.log.add(text)
        else:
            self.log.count_noise()

    def note_miss(self, miss):
        """Серия не сложилась (не дождался второго щелчка, шум сразу после) - это тоже надо видеть."""
        code = miss[0] if isinstance(miss, (tuple, list)) else miss
        text = events.miss_text(code, self.listener.det.clicker.gaps[1])
        if text:
            self.log.add(("проверка · " if self.checking else "") + text)

    def note_quiet(self, e):
        """Звук похож на щелчок, но тише, чем на настройке. Если так раз за разом - виноват не человек, а
        «улучшение звука» микрофона: скажем об этом один раз, а не будем молча плохо работать."""
        if e.get("reason") != "тише щелчка":
            self._quiet_hits = max(0, self._quiet_hits - 1) if e.get("ok") else self._quiet_hits
            return
        self._quiet_hits += 1
        if self._quiet_hits >= 3 and not self._mic_hint_said and self.mic_enhanced():
            self._mic_hint_said = True
            self.log.add("щелчки приходят тише, чем на настройке. " + MIC_HINT)

    def start_check(self):
        """«Проверить мой щелчок»: 30 с показываем каждый звук с оценкой, окна при этом не трогаем."""
        self.check_until = time.monotonic() + CHECK_S
        self.check_stat = [0, 0]
        self.check_snaps = []
        self.check_result = ""
        self.log.add(f"проверка щелчка: слушаю {CHECK_S} с - щёлкните несколько раз")
        self.update_tray()

    def stop_check(self):
        if self.checking:
            self.check_until = 0.0
            self.finish_check()

    def finish_check(self):
        """Итог проверки - словами и числами: «ваши щелчки: от 27 до 70, порог сейчас 45, предлагаю 40»."""
        self.check_until = 0.0
        n, ok = self.check_stat
        scores = [s for s, _ in self.check_snaps]
        info = self.suggest() if scores else None
        self.check_result = tuning.check_text(scores, self.threshold(),
                                              suggested=info["thr"] if info else None)
        self.log.add(f"проверка закончена: звуков {n}, похожих на щелчок {ok} · {self.check_result}")
        self.update_tray()

    def learn_check(self):
        """Кнопка «Это были мои щелчки - учесть»: добавляем услышанное к образцам щелчка, пересчитываем шаблон и
        порог. Дообучение в настоящей обстановке - то, чего не даёт настройка в идеальной тишине."""
        tpl = self.template()
        cands = [c for _, c in sorted(self.check_snaps, key=lambda x: -x[0])[:6]]
        if tpl is None or not cands:
            return None
        new, kept = detector.relearn(tpl, cands)
        if new is None:
            return None
        self.set_template(new)
        for s, _ in self.check_snaps:
            self.scores.add(s, True)
        info = self.apply_suggested()
        self.log.add(f"учёл ваши щелчки: образцов {len(kept)}, порог {info['thr']}")
        return info

    def check_left(self):
        return max(0, int(round(self.check_until - time.monotonic()))) if self.checking else 0

    def open_journal(self):
        """Открыть файл журнала в блокноте (владелец должен видеть его сам, без меня)."""
        p = journal.path()
        journal.write("журнал открыт в блокноте")
        if not winapi.WIN:
            return p
        import subprocess
        try:
            subprocess.Popen(["notepad.exe", p])     # noqa: S607 - именно блокнот, как просил владелец
        except OSError:
            try:
                os.startfile(p)                      # noqa: S606
            except OSError:
                return None
        return p

    def show_journal(self):
        """Кнопка «Показать журнал»: папка журналов, на Windows - с выделенным файлом сегодняшнего дня.

        Окно «Журнал» (блокнот) осталось как было: одно показывает текст, другое - где этот текст лежит."""
        journal.write("открыл папку с журналом")
        return journal.show()

    def check_show_flag(self):
        """Вторую копию запустили ярлыком, а мы работаем с правами администратора: окно открываем по файлу-флажку
        (окно-сервер между разными правами Windows не пускает)."""
        p = settings.show_flag()
        try:
            if not os.path.exists(p):
                return False
            fresh = time.time() - os.path.getmtime(p) < 60      # залежавшийся флажок окно не открывает
            os.remove(p)
        except OSError:
            return False
        if fresh:
            self.another_copy()
        return fresh

    def update_tick(self):
        """Раз в секунду: пора ли посмотреть сервер и не пришёл ли ответ из потока проверки."""
        if self.demo:
            return
        self.upd.tick()

    def check_updates_now(self):
        """Кнопка «Проверить сейчас»: смотрим сервер прямо сейчас, даже если галочка выключена."""
        if self.demo:
            return False
        return self.upd.check_now()

    def update_said(self, status):
        """Ответ на нажатую кнопку «Проверить сейчас» - строкой в «Что происходило» (и в журнал)."""
        if status == "none":
            self.log.add("у вас последняя версия")
        elif status == "fail":
            self.log.add("не получилось связаться с сервером - посмотрю ещё раз позже")

    def open_update(self, info, auto=False):
        """Окно «Вышла версия X» (общее для линейки на Qt, с путём к журналу при неудаче)."""
        if self.update_win is not None:
            self.update_win.close()
        self.update_win = UpdateWindow(self.upd, info, auto=auto, icon=self.icon, title=TITLE, note=update.NOTE,
                                       on_shown=self.on_window_shown)
        self.update_win.adjustSize()
        self.center(self.update_win)
        self.update_win.show()
        self.update_win.raise_()
        self.update_win.activateWindow()

    def watchdog(self):
        self.check_show_flag()
        self.update_tick()
        if not self.settings["listening"]:
            return
        self.hider.settle()            # окна могли вернуть мимо нас (панель задач, Win+D)
        self.sync_windows_state()
        self.check_mic_mute()
        before = (self.listener.state, self.listener.device_name)
        if self.listener.watchdog(self.outmeter.capture_id):
            self.apply_detector()
            after = (self.listener.state, self.listener.device_name)
            if after != before:
                if after[0] == "on" and self.template() is None:
                    self.toast.show_message("Новый микрофон", f"«{self.mic_name()}» - настройте щелчок (3 щелчка).",
                                            ms=6000)
                    self.open_calibration()
                elif after[0] == "on" and before[0] != "on":
                    self.toast.show_message(TITLE, "Микрофон снова на связи - слушаю.", ms=2500)

    # ------------------------------------------------------------ окна
    def back_hint(self, short=False):
        """Чем вернуть окна - для плашки и подсказки в окне (клавиша работает всегда)."""
        n = self.settings["back"]
        how = "щёлкните ещё раз" if n == 1 else settings.back_series(n, lower=True)
        if short:
            return how
        key = self.settings["hotkeys"].get("toggle", "")
        return f"{how[0].upper()}{how[1:]}{' или ' + key if key else ''} - верну все окна."

    def do_action(self, action):
        """Срабатывание детектора: "hide" - свернуть, "restore" - вернуть. Окна успели поменять состояние
        (клавиша, трей, сам пользователь) - ничего не делаем."""
        if action == "hide" and self.hider.hidden:
            return None
        if action == "restore" and not self.hider.hidden:
            return None
        return self.toggle_windows()

    def toggle_windows(self):
        """Свернуть или вернуть (клавиша, трей, кнопка в окне - всегда переключают)."""
        s = self.settings
        if self.hider.hidden:
            admin = [h for h, _ in self.hider.admin_windows()]
            n = self.hider.restore()
            k = len(admin)
            # число в журнале честное: окна «от администратора» без прав не вернутся, и писать «вернул» про них
            # нельзя (жалоба владельца 16.10.2026)
            self.log.add(f"вернул окна: {max(0, n - k)}, а {events.word_windows(k)} от имени администратора "
                         f"без прав не вернуть" if k else f"вернул окна: {n}")
            if k:
                self.note_admin(admin, where="вернул")
            self.after_restore(n, toast=s["toast"], ms=1000, admin=k)
            return "restore", n
        if self.main is not None and self.main.isVisible():
            self.reopen_main = True
            self.main.hide()
        n = self.hider.hide()
        self.log.add(f"свернул окна: {n}")
        self.note_admin(list(self.hider.admin), where="свернул")
        if s["mute"]:
            self.prev_mute = syscom.mute_get()
            self.muted_by_us = bool(syscom.mute_set(True))
        if s["toast"]:
            self.toast.show_message("Свернул", f"{word_windows(n)}. {self.back_hint()}" if n else
                                    "Открытых окон нет.", ms=1000)
        QTimer.singleShot(250, self.verify_hidden)
        self.apply_detector()
        self.update_tray()
        return "hide", n

    def verify_hidden(self):
        """Через 0,25 с после сворачивания: что не свернулось само - досворачивает проводник (и всё, что он
        свернул заодно, мы потом вернём). Окно «от администратора» свернуть напрямую Windows не даёт - такие
        окна программа помнит и в следующий раз зовёт проводника сразу."""
        left = self.hider.verify()
        if left:
            self.log.add(f"свернул окна: {left} не свернулись сами - досворачивает проводник")
        QTimer.singleShot(700, self.verify_hidden_final)
        self.sync_windows_state()

    def verify_hidden_final(self):
        """Через ~1 с: окна, которые так и остались на экране. Молчать об этом нельзя - человек думает, что
        рабочий стол чист, а окно видно (чаще всего это окно «от имени администратора»)."""
        left = self.hider.not_hidden()
        if not left or not self.hider.hidden:
            return
        rows = self.note_admin(left, where="свернул")
        if not rows:
            self.log.add(f"не свернулось: {events.word_windows(len(left))} осталось на экране")

    def after_restore(self, n, toast=True, ms=1500, admin=0):
        """После возврата: звук, своё окно, плашка, состояние детектора; через 0,15 и 0,6 с - доворот наших окон.
        И запрет сворачивать обратно на 3,5 с - лишние щелчки того же жеста не должны прятать окна снова."""
        self.listener.det.clicker.hold_hide(self.listener.det.front.t)
        if self.muted_by_us and self.settings["unmute"]:
            syscom.mute_set(bool(self.prev_mute))
        self.muted_by_us = False
        if self.reopen_main:
            self.reopen_main = False
            QTimer.singleShot(250, self.open_main)
        if toast:
            self.toast.show_message("Вернул", (f"окна на месте, кроме {word_windows(admin)} от администратора."
                                               if admin else f"все окна на месте ({word_windows(n)}).") if n else
                                    "Возвращать нечего.", ms=ms)
        QTimer.singleShot(150, lambda: self.restore_verify(quiet=True))
        QTimer.singleShot(600, self.restore_verify)
        QTimer.singleShot(1200, self.restore_final)
        self.apply_detector()
        self.update_tray()

    def restore_verify(self, quiet=False):
        """Через 0,15 с и через 0,6 с после возврата: наши окна, которые не вернулись с первого раза,
        разворачиваем ещё раз поимённо (общесистемное «отменить свернуть все» не зовём - оно поднимает и чужие
        свёрнутые окна). Первый, быстрый доворот человек не замечает - в журнал пишем только второй."""
        left = self.hider.restore_verify()
        if left and not quiet:
            self.log.add(f"вернул окна: {left} вернулись только со второго раза")
        self.sync_windows_state()

    def restore_final(self):
        """Через 1,2 с после возврата - ЧЕСТНАЯ проверка: какие окна так и не вернулись. Если за это время мы
        уже свернули окна заново (человек щёлкнул ещё раз), проверять нечего - `not_restored` вернёт пусто."""
        left = self.hider.not_restored()
        if not left:
            self.hider.restore_order(self.hider.last)     # всё поднялось - ставим порядок наложения начисто
            return
        rows = self.note_admin(left, where="вернул")
        if not rows:
            self.log.add(f"не вернулось: {events.word_windows(len(left))} осталось свёрнутым - "
                         f"откройте его с панели задач")
        self.sync_windows_state()

    def restore_all(self):
        """Трей «Вернуть все окна»: только наши окна (чужие свёрнутые не трогаем)."""
        n = self.hider.restore_all()
        self.after_restore(n, toast=True, ms=1500)

    def on_window_shown(self, w):
        pass

    def open_main(self):
        from .main_win import MainWindow
        if self.main is None:
            self.main = MainWindow(self)
            self.main.adjustSize()
            self.center(self.main)
        self.main.show()
        self.main.raise_()
        self.main.activateWindow()

    def open_calibration(self):
        from .calib import CalibWindow
        if self.calib is None:
            self.calib = CalibWindow(self)
            self.calib.adjustSize()
            self.center(self.calib)
        self.calib.show()
        self.calib.raise_()
        self.calib.activateWindow()

    def calibration_closed(self):
        self.calib = None
        if self.main is None or not self.main.isVisible():
            if self.template() is not None and not self.demo:
                self.toast.show_message(TITLE, "Слушаю. Щёлкните пальцами - окна свернутся.", ms=3500)

    def center(self, w):
        from PySide6.QtGui import QGuiApplication
        a = QGuiApplication.primaryScreen().availableGeometry()
        w.move(a.center().x() - w.width() // 2, max(a.top(), a.center().y() - w.height() // 2))

    # ------------------------------------------------------------ настройки
    def save_later(self):
        if not hasattr(self, "_save_t"):
            self._save_t = QTimer(self)
            self._save_t.setSingleShot(True)
            self._save_t.setInterval(500)
            self._save_t.timeout.connect(self.save_now)
        self._save_t.start()

    def save_now(self):
        if self.demo and self.args.settings is None:
            return
        try:
            settings.save(self.settings, self.args.settings)
        except OSError:
            pass

    def set_template(self, tpl):
        self.settings["templates"][self.mic_key()] = tpl
        self.settings["first_run"] = False
        self.apply_detector()
        self.save_now()

    def toggle_listening(self):
        on = not self.settings["listening"]
        self.settings["listening"] = on
        if on and not self.demo:
            self.listener.start(self.settings["mic"])
            self.apply_detector()
        else:
            self.listener.stop()
        self.update_tray()
        self.save_later()

    def set_mic(self, name):
        self.settings["mic"] = name
        if self.settings["listening"] and not self.demo:
            self.listener.start(name)
        self.apply_detector()
        self.save_later()
        if self.template() is None and not self.demo:
            self.open_calibration()

    def set_sens(self, v):
        self.settings["sens"] = int(v)
        self.settings["thr"] = int(round(detector.threshold(int(v))))
        self.apply_detector()
        self.save_later()

    def set_thr(self, v):
        """Порог оценки «это щелчок» (ползунок в окне, шаг 1 очко). Чувствительность держим в согласии с ним -
        её читают старые настройки и шкала в окне «Настройка щелчка»."""
        v = max(settings.THR_MIN, min(settings.THR_MAX, int(round(float(v)))))
        self.settings["thr"] = v
        self.settings["sens"] = int(round(detector.sens_of_thr(v)))
        self.apply_detector()
        self.save_later()
        return v

    def set_back(self, n):
        """Сколько щелчков возвращают окна: 1 (быстро), 2 или 3 подряд (страховка от случайного стука)."""
        self.settings["back"] = max(1, min(3, int(n)))
        self.apply_detector()
        self.save_later()

    def set_mode(self, m):
        self.settings["mode"] = int(m)
        self.apply_detector()
        self.save_later()

    def set_option(self, key, on):
        self.settings[key] = bool(on)
        if key == "autostart" and not self.demo:
            winapi.autostart_set(TITLE, bool(on) and not self.settings["admin"])
            if self.settings["admin"]:
                self.set_admin(True)            # автозапуск с правами - это задание планировщика, не ярлык

        self.save_later()

    # ------------------------------------------------------------ права администратора
    def elevated(self):
        """Программа работает с правами администратора (тогда ей подчиняются и окна «от администратора»)."""
        return winapi.is_elevated()

    def admin_state(self):
        """Что показать в окне: (включено ли в настройках, работаем ли сейчас с правами).

        Задание планировщика здесь НЕ спрашиваем: эту строку рисует таймер окна (30 мс), а проверка задания -
        это запуск schtasks.exe. Её делаем по делу - сразу после включения галочки (`admin_task_ok`)."""
        return bool(self.settings["admin"]), self.elevated()

    def admin_task_ok(self):
        """Задание «запускать с правами администратора» действительно создано? (по делу, не по таймеру)."""
        return False if self.demo else winapi.admin_task_exists()

    def set_admin(self, on):
        """«Запускать с правами администратора»: задание планировщика «при входе в систему» с наивысшими правами.

        Ярлык с галочкой «от имени администратора» для автозапуска не годится - Windows спрашивала бы
        подтверждение при каждом входе. Задание спрашивает один раз, когда его создают."""
        self.settings["admin"] = bool(on)
        self.save_now()
        if self.demo or not winapi.WIN:
            return bool(on)
        exe = os.path.abspath(__import__("sys").executable)
        if on:
            winapi.autostart_set(TITLE, False)          # иначе программа запустится дважды: ярлык + задание
            ok = winapi.admin_task_create(exe)
            self.log.add("включаю запуск с правами администратора: Windows спросит подтверждение один раз"
                         if ok else "не получилось попросить права у Windows - попробуйте ещё раз")
            return ok
        winapi.admin_task_delete()
        if self.settings["autostart"]:
            winapi.autostart_set(TITLE, True)
        self.log.add("запуск с правами администратора выключен")
        return True

    def restart_as_admin(self):
        """Перезапустить программу с правами администратора сейчас.

        Сначала пробуем ЗАДАНИЕ планировщика (оно уже создано и запускается с наивысшими правами БЕЗ нового
        вопроса Windows) и только потом - обычный запрос прав. Мьютекс одной копии отпускаем заранее, иначе
        новая копия увидит «программа уже открыта» и тихо выйдет."""
        if self.demo or not winapi.WIN:
            return False
        exe = os.path.abspath(__import__("sys").executable)
        winapi.release_mutex()
        how = "заданием планировщика" if winapi.admin_task_run() else None
        if how is None:
            how = "через запрос прав Windows" if winapi.run_as_admin(exe, "--hidden") else None
        if how is None:
            winapi.first_instance(settings.APP)        # не вышло - мьютекс берём обратно
            self.log.add("перезапуск с правами администратора не состоялся - Windows не дала прав")
            return False
        journal.write(f"перезапускаюсь с правами администратора ({how})")
        QTimer.singleShot(600, self.quit)
        return True

    def note_admin(self, hwnds, where="свернул"):
        """Окна, которыми Windows не даёт нам управлять: честная строка в журнал и в окно (один раз на событие)."""
        rows = self.hider.admin_windows(hwnds)
        if not rows:
            return []
        self.admin_seen = rows
        now = time.monotonic()
        if now - getattr(self, "_admin_log_at", -1e9) > ADMIN_LOG_EVERY:   # один раз на жест, а не 4 строки
            self._admin_log_at = now
            self.log.add(events.admin_line([t for _, t in rows]))
        if self.settings["toast"] and not self._admin_said and not self.elevated():
            self._admin_said = True
            self.toast.show_message("Окно от администратора",
                                    f"{events.word_windows(len(rows))} не слушается без прав - включите "
                                    f"«Запускать с правами администратора» в окне «{TITLE}».", ms=7000)
        return rows

    def admin_note(self):
        """Строка для окна: видели ли мы окна «от администратора» и что с этим делать."""
        if not self.admin_seen or self.elevated():
            return ""
        names = ", ".join(f"«{t}»" for _, t in self.admin_seen[:1] if t)
        return (f"{names} - от администратора: без прав не вернуть." if names
                else "Окно от администратора: без прав не вернуть.")

    def set_hotkey(self, txt):
        self.settings["hotkeys"]["toggle"] = txt
        self.save_later()

    # ------------------------------------------------------------ клавиша
    def register_hotkeys(self):
        hw = self.hk.winId()
        winapi.unregister_hotkey(hw, HK_TOGGLE)
        self.hk_failed = []
        p = settings.parse_hotkey(self.settings["hotkeys"].get("toggle", ""))
        if p is not None and not winapi.register_hotkey(hw, HK_TOGGLE, *p):
            self.hk_failed = [self.settings["hotkeys"]["toggle"]]
            journal.write(f"клавиша {self.hk_failed[0]} занята другой программой")
            QTimer.singleShot(1200, lambda: self.toast.show_message(
                "Клавиша занята", f"{self.hk_failed[0]} - занято другой программой. Поменяйте в окне «{TITLE}».",
                ms=8000))
        self.update_tray()
        return self.hk_failed

    def unregister_hotkeys(self):
        winapi.unregister_hotkey(self.hk.winId(), HK_TOGGLE)

    def on_hotkey(self, hid):
        if hid == HK_TOGGLE:
            self.toggle_windows()

    # ------------------------------------------------------------ трей, выход
    def make_tray(self):
        self.tray = QSystemTrayIcon(self.icon)
        self.tray.activated.connect(self._tray_activated)
        self.update_tray()
        self.tray.show()

    def update_tray(self):
        if self.tray is None:
            return
        on = self.settings["listening"]
        self.tray.setIcon(self.icon if on else self.icon_paused)
        self.tray.setToolTip(f"{TITLE} - {self.state_text().lower()}")
        self.tray.setContextMenu(self.build_menu())

    def build_menu(self):
        m = QMenu()
        key = self.settings["hotkeys"].get("toggle", "")
        a = QAction("Слушаю", m)
        a.setCheckable(True)
        a.setChecked(self.settings["listening"])
        a.triggered.connect(self.toggle_listening)
        m.addAction(a)
        m.addSeparator()
        items = [("Вернуть все окна" if self.hider.hidden else "Свернуть все окна", key, self.toggle_windows),
                 ("Вернуть все окна, которые свернул", "", self.restore_all),
                 None, (f"Открыть «{TITLE}»", "", self.open_main), ("Настроить щелчок", "", self.open_calibration),
                 None, ("Выйти", "", self.quit)]
        for it in items:
            if it is None:
                m.addSeparator()
                continue
            text, k, fn = it
            act = QAction(text + (f"\t{k}" if k else ""), m)
            act.triggered.connect(fn)
            m.addAction(act)
        self.menu = m
        return m

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_main()

    def another_copy(self):
        """Запустили ещё раз: показываем окно этой копии и говорим, что программа уже открыта."""
        self.open_main()
        self.toast.show_message(TITLE, "Программа уже открыта - значок в трее у часов.", ms=4000)

    def startup_notes(self):
        """Что сказать при запуске: программа с правами администратора или нет, и микрофон «с улучшениями»."""
        if not self.demo:
            if self.elevated():
                journal.write("работаю с правами администратора - окна «от администратора» тоже слушаются")
            elif self.settings["admin"]:
                journal.write("«Запускать с правами администратора» включено, но в этот раз программа запущена "
                              "без прав: окна «от администратора» свернуть/вернуть не смогу. Права появятся при "
                              "следующем входе в Windows или сразу - кнопкой «Нужны права - перезапустить».")

    def quit(self):
        try:
            self.unregister_hotkeys()
            self.listener.shutdown()
            self.outmeter.stop()
            self.inputs.stop()
            if self.hider.hidden:
                self.hider.restore()
            if self.muted_by_us and self.settings["unmute"]:
                syscom.mute_set(bool(self.prev_mute))
            if not self.demo:
                settings.save(self.settings, self.args.settings)
        except Exception:  # noqa: BLE001
            pass
        if self.tray:
            self.tray.hide()
        self.app.quit()


def single_instance_or_signal():
    """True - мы первая копия (сервер поднят); False - сигнал первой копии отправлен, выходим."""
    first = winapi.first_instance(settings.APP)
    if not first or not winapi.WIN:
        sock = QLocalSocket()
        sock.connectToServer(SERVER)
        if sock.waitForConnected(800):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(800)
            sock.disconnectFromServer()
            return False
        if not first:
            # первая копия работает с правами администратора: ни мьютекс, ни её окно обычной программе не
            # отдают (так устроена защита Windows) - просим показать окно через файл-флажок в своей папке
            ask_show()
            return False
    return True


def ask_show():
    """Вторая копия просит первую показать окно (когда через окно-сервер не вышло: разные права)."""
    try:
        os.makedirs(settings.config_dir(), exist_ok=True)
        with open(settings.show_flag(), "w", encoding="utf-8") as f:
            f.write("show")
        return True
    except OSError:
        return False


def serve(ctl):
    QLocalServer.removeServer(SERVER)
    srv = QLocalServer(ctl)
    srv.listen(SERVER)

    def on_conn():
        c = srv.nextPendingConnection()
        if c is not None:
            c.readyRead.connect(lambda: (c.readAll(), ctl.another_copy()))
    srv.newConnection.connect(on_conn)
    return srv
