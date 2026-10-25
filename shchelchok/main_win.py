# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Окно «Щелчок»: слушаю/пауза, микрофон и его уровень, оценки звуков и чувствительность, один/два/три щелчка,
что делать (звук, плашка, защита от звука компьютера и клавиатуры), запасная клавиша, автозапуск.
Всё применяется сразу и сохраняется; «Готово» - окно в трей, программа слушает дальше."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QFont, QKeySequence
from PySide6.QtWidgets import (QLayout, QButtonGroup, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QKeySequenceEdit,
                               QLabel, QPlainTextEdit, QPushButton, QRadioButton, QSizePolicy, QSlider,
                               QVBoxLayout)

from . import audio, detector, settings, ui
from .app_licenses_qt import licenses_row
from .qt_theme import ThemePicker
from .settings import TITLE
from .widgets import LevelMeter

# цвет кружка состояния; сам текст - у контроллера (ctl.state_text), чтобы окно и трей говорили одно и то же
STATUS_COLOR = {"on": "#4ADE80", "off": "#E9D5FF", "nomic": "#FFD60A", "needcal": "#FFD60A", "hidden": "#FFD60A",
                "silent": "#FFD60A"}
# Одна строка про права администратора - зачем они и почему Windows спросит (чек-лист: тексты человеческие)
ADMIN_WHY = ("Нужно, чтобы сворачивать и возвращать окна, открытые от имени администратора\n"
             "(командную строку и подобные): без прав Windows этого не разрешает.\n"
             "Подтверждение Windows спросит один раз - когда создаёт задание на запуск.")


class MainWindow(ui.FlowWindow):
    def __init__(self, ctl):
        super().__init__(ctl, TITLE)
        s = ctl.settings
        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SetMinimumSize)   # окно не меньше содержимого при любом масштабе
        root.setContentsMargins(22, 10, 22, 10)   # окно должно влезать в 1920x1080 при 150 %
        root.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(ui.label(TITLE, 24, QFont.ExtraBold))
        head.addSpacing(10)
        self.status = QLabel()
        self.status.setFont(ui.brand.font(14, QFont.ExtraBold))
        head.addWidget(self.status)
        head.addStretch(1)
        self.listen_b = QPushButton()
        self.listen_b.setObjectName("primary")
        self.listen_b.clicked.connect(ctl.toggle_listening)
        head.addWidget(self.listen_b)
        root.addLayout(head)
        self.lead = ui.label("", 14, QFont.DemiBold, "hint", wrap=True)
        root.addWidget(self.lead)

        cols = QHBoxLayout()
        cols.setSpacing(10)
        WCOL = 540          # ширина колонки: с ней длинные подписи - в одну строку, и окно ниже по высоте
        left = QVBoxLayout()
        left.setSpacing(8)

        # ---- микрофон и оценки
        g1, l1 = ui.glass("Микрофон")
        row = QHBoxLayout()
        row.setSpacing(10)
        self.mic = QComboBox()
        self.mic.addItem("Как в Windows (по умолчанию)", "")
        for name in audio.list_mics():
            self.mic.addItem(name, name)
        if s["mic"] and self.mic.findData(s["mic"]) < 0:
            self.mic.addItem(s["mic"], s["mic"])
        self.mic.setCurrentIndex(max(0, self.mic.findData(s["mic"])))
        self.mic.setMinimumWidth(250)
        self.mic.currentIndexChanged.connect(lambda *_: ctl.set_mic(self.mic.currentData() or ""))
        row.addWidget(self.mic, 1)
        l1.addLayout(row)
        self.meter = LevelMeter(ctl)
        l1.addWidget(self.meter)
        self.mic_hint = ui.label(ctl.mic_hint(), 12, QFont.DemiBold, "hint", wrap=True)
        self.mic_hint.setVisible(bool(ctl.mic_hint()))
        l1.addWidget(self.mic_hint)
        # ---- порог: то же число, что в журнале («порог 45»), шаг 1 очко (владелец 16.10.2026)
        sg = QGridLayout()
        sg.setHorizontalSpacing(10)
        sg.addWidget(ui.label("Чувствительность"), 0, 0)
        self.sens = QSlider(Qt.Horizontal)
        self.sens.setRange(settings.THR_MIN, settings.THR_MAX)
        self.sens.setInvertedAppearance(True)          # левее - мягче (ловит даже слабый щелчок)
        self.sens.setInvertedControls(True)
        self.sens.setSingleStep(1)
        self.sens.setPageStep(5)
        self.sens.setValue(int(s["thr"]))
        self.sens.setMinimumWidth(150)
        self.sens.valueChanged.connect(self.thr_changed)
        sg.addWidget(self.sens, 0, 1)
        self.sens_l = ui.label("", 13, QFont.Bold, "key")
        self.sens_l.setMinimumWidth(self.sens_l.fontMetrics().horizontalAdvance("щелчок от 100 из 100") + 6)
        sg.addWidget(self.sens_l, 0, 2)
        sg.setColumnStretch(1, 1)
        l1.addLayout(sg)
        br = QHBoxLayout()
        br.setSpacing(10)
        self.fit_b = QPushButton("Подобрать под меня")
        self.fit_b.setToolTip("Посчитаю порог по вашим щелчкам и по тому, что слышно в комнате,\n"
                              "и скажу, сколько ваших щелчков прошло бы.")
        self.fit_b.clicked.connect(self.fit_clicked)
        br.addWidget(self.fit_b)
        cal = QPushButton("Настроить щелчок заново")
        cal.clicked.connect(ctl.open_calibration)
        self.cal_b = cal
        br.addWidget(cal)
        br.addStretch(1)
        l1.addLayout(br)
        self.fit_l = ui.label("", 12, QFont.DemiBold, "hint", wrap=True)
        l1.addWidget(self.fit_l)
        self.calib_l = ui.label("", 12, QFont.Bold, "err", wrap=True)
        self.calib_l.setVisible(False)
        l1.addWidget(self.calib_l)
        self.thr_hint = self.fit_l          # одна надпись на две подсказки - окно и так высокое
        g1.setMinimumWidth(WCOL)
        left.addWidget(g1)

        # ---- сколько щелчков сворачивает (строкой в той же карточке - окно и так высокое)
        self.mode_btns = {}
        bg = QButtonGroup(self)
        mrow = QHBoxLayout()
        mrow.setSpacing(14)
        mrow.addWidget(ui.label("Свернуть"))
        for m, text in settings.MODES:
            rb = QRadioButton(text.replace(" подряд", ""))
            rb.setToolTip("Если окна сворачиваются сами - выберите два щелчка")
            rb.setChecked(s["mode"] == m)
            rb.toggled.connect(lambda on, m=m: on and self.mode_changed(m))
            bg.addButton(rb)
            mrow.addWidget(rb)
            self.mode_btns[m] = rb
        mrow.addStretch(1)
        l1.addLayout(mrow)


        # ---- что происходило: каждый звук с оценкой и вердиктом (владелец 16.10.2026: «добавь журнал событий»)
        g5, l5 = ui.glass()
        lr = QHBoxLayout()
        lr.setSpacing(10)
        self.log_head = ui.label("Что происходило", 15, QFont.ExtraBold)
        lr.addWidget(self.log_head)
        lr.addStretch(1)
        self.check_b = QPushButton("Проверить мой щелчок")
        self.check_b.setToolTip("30 секунд показываю оценку каждого звука - окна при этом не трогаю.\n"
                                "Звук не записывается и никуда не уходит, только числа.")
        self.check_b.clicked.connect(self.check_clicked)
        lr.addWidget(self.check_b)
        self.learn_b = QPushButton("Учесть мои щелчки")
        self.learn_b.setToolTip("Это были мои щелчки - учесть их: добавлю услышанное к образцам\n"
                                "и пересчитаю порог под вашу настоящую обстановку, а не под тишину.")
        self.learn_b.clicked.connect(self.learn_clicked)
        self.learn_b.setVisible(False)
        lr.addWidget(self.learn_b)
        jb = QPushButton("Журнал")
        jb.setToolTip("Открыть журнал событий в блокноте")
        jb.clicked.connect(ctl.open_journal)
        lr.addWidget(jb)
        l5.addLayout(lr)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(ui.brand.font(12, QFont.DemiBold))
        # ровно 3 строки текущим шрифтом плюс поля (иначе последняя строка режется пополам); длинная строка
        # переносится и занимает две - поэтому кладём в окно не больше трёх строк, остальное - в «Журнале»
        self.log_view.setFixedHeight(self.log_view.fontMetrics().lineSpacing() * 3 + 18)
        self.log_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        l5.addWidget(self.log_view)
        left.addWidget(g5)
        left.addStretch(1)
        cols.addLayout(left, 1)

        # ---- что делать
        g3, l3 = ui.glass("Что делать")
        self.cbs = {}
        for key, text in (("toast", "Показывать плашку «Свернул»"),
                          ("mute", "Заодно выключать звук компьютера"),
                          ("unmute", "При возврате окон - вернуть звук"),
                          ("ignore_output", "Не реагировать на звук из колонок компьютера"),
                          ("ignore_typing", "Не реагировать, пока печатаю или щёлкаю мышью")):
            cb = QCheckBox(text)
            cb.setChecked(s[key])
            cb.toggled.connect(lambda on, k=key: ctl.set_option(k, on))
            l3.addWidget(cb)
            self.cbs[key] = cb
        self.cbs["mute"].toggled.connect(self.cbs["unmute"].setEnabled)
        self.cbs["unmute"].setEnabled(s["mute"])
        kr = QHBoxLayout()
        kr.setSpacing(10)
        klab = ui.label("Запасная клавиша")
        klab.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)   # поле ввода - рядом с подписью, а не
        kr.addWidget(klab)                                               # у правого края карточки
        self.key = QKeySequenceEdit(QKeySequence(s["hotkeys"]["toggle"]))
        try:
            self.key.setMaximumSequenceLength(1)
            self.key.setClearButtonEnabled(False)
        except AttributeError:
            pass
        self.key.setFixedWidth(170)
        self.key.keySequenceChanged.connect(self.key_changed)
        self.key.installEventFilter(self)
        kr.addWidget(self.key)
        self.key_err = ui.label("", 12, QFont.Bold, "err", wrap=True)
        kr.addWidget(self.key_err, 1)
        l3.addLayout(kr)
        # ---- цвет оформления: кружки пресетов + «Свой» с ползунком оттенка (общий ThemePicker линейки)
        tr = QHBoxLayout()
        tr.setSpacing(10)
        tr.addWidget(ui.label("Цвет оформления"))
        self.theme = ThemePicker(settings.theme_value(s), font=ui.brand.font(12, QFont.DemiBold), dot=20, gap=6)
        self.theme.changed.connect(self.theme_changed)
        tr.addWidget(self.theme, 1)
        l3.addLayout(tr)
        self.cb_auto = QCheckBox("Запускать вместе с Windows")
        self.cb_auto.setChecked(s["autostart"])
        self.cb_auto.toggled.connect(lambda on: ctl.set_option("autostart", on))
        l3.addWidget(self.cb_auto)
        # ---- права администратора: без них Windows не даёт управлять окнами программ «от администратора»
        self.cb_admin = QCheckBox("Запускать с правами администратора")
        self.cb_admin.setObjectName("admin")
        self.cb_admin.setChecked(s["admin"])
        self.cb_admin.toggled.connect(self.admin_changed)
        l3.addWidget(self.cb_admin)
        self.cb_admin.setToolTip(ADMIN_WHY)
        l3.addStretch(1)

        # ---- как вернуть окна (владелец 16.10.2026: «щёлкнул один раз - свернулось, щёлкнул второй раз -
        # развернулось»; два щелчка на возврат остались выбором для шумных мест)
        g4, l4 = ui.glass("Как вернуть все окна обратно")
        self.back_l = ui.label("", 13, QFont.Bold, "key", wrap=True)
        l4.addWidget(self.back_l)
        brow = QHBoxLayout()
        brow.setSpacing(14)
        self.back_btns = {}
        bgb = QButtonGroup(self)
        for n, text, why in settings.BACK_MODES:
            rb = QRadioButton(text)
            rb.setChecked(s["back"] == n)
            rb.setToolTip(why)
            rb.toggled.connect(lambda on, n=n: on and self.back_changed(n))
            bgb.addButton(rb)
            brow.addWidget(rb)
            self.back_btns[n] = rb
        brow.addStretch(1)
        l4.addLayout(brow)
        self.back_why = ui.label(settings.BACK_WHY, 12, QFont.DemiBold, "hint", wrap=True)
        self.back_why.setToolTip(settings.BACK_WHY_FULL)
        l4.addWidget(self.back_why)
        self.mode_warn = ui.label(settings.BACK_WARN_SAME, 12, QFont.Bold, "err", wrap=True)
        self.mode_warn.setToolTip(settings.BACK_WARN_SAME_WHY)
        l4.addWidget(self.mode_warn)
        self.admin_l = ui.label("", 12, QFont.Bold, "err", wrap=True)
        self.admin_l.setVisible(False)
        l4.addWidget(self.admin_l)
        self.mode_warn.setVisible(s["mode"] == s["back"] and s["back"] > 1)

        right = QVBoxLayout()
        right.setSpacing(8)
        g3.setMinimumWidth(WCOL)
        right.addWidget(g3)
        right.addWidget(g4)
        right.addStretch(1)
        cols.addLayout(right, 1)
        root.addLayout(cols)

        pr = QHBoxLayout()
        pr.addWidget(ui.label("Звук не записывается и никуда не уходит. Всё считается на вашем компьютере.", 12,
                              QFont.DemiBold, "hint"), 1)
        for text, url in settings.LINKS:
            lnk = QPushButton(text)
            lnk.setObjectName("link")
            lnk.setCursor(Qt.PointingHandCursor)
            lnk.setToolTip(url)
            lnk.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            pr.addWidget(lnk)
        from . import __version__
        self.cb_upd = QCheckBox("Проверять обновления")
        self.cb_upd.setChecked(s["updates"])
        self.cb_upd.setToolTip("Раз в неделю программа тихо смотрит, вышла ли новая версия, и СПРАШИВАЕТ вас.\n"
                               "Ничего не скачивается и не ставится без вашего ответа. Обновления бесплатные.")
        self.cb_upd.toggled.connect(lambda on: ctl.set_option("updates", on))
        pr.addWidget(self.cb_upd)
        self.upd_b = QPushButton("Проверить сейчас")
        self.upd_b.setObjectName("link")
        self.upd_b.setCursor(Qt.PointingHandCursor)
        self.upd_b.setToolTip("Посмотреть сейчас, нет ли новой версии")
        self.upd_b.clicked.connect(self.check_updates)
        pr.addWidget(self.upd_b)
        # папка журналов (кнопка «Журнал» рядом с «Что происходило» открывает сам файл в блокноте): в строке
        # с версией и обновлениями - как в остальных программах линейки; наверху места уже нет (окно должно
        # влезать в 1920x1080 при 150 %)
        self.show_log_b = QPushButton("Показать журнал")
        self.show_log_b.setObjectName("link")
        self.show_log_b.setCursor(Qt.PointingHandCursor)
        self.show_log_b.setToolTip("Открою папку с журналом программы: в нём видно, что программа делала.\n"
                                   "Файл с сегодняшней датой можно прислать, если что-то пошло не так.")
        self.show_log_b.clicked.connect(ctl.show_journal)
        pr.addWidget(self.show_log_b)
        self.version = ui.label(f"Версия {__version__}", 12, QFont.DemiBold, "hint")
        pr.addWidget(self.version)
        root.addLayout(pr)

        # ---- открытые компоненты: одна строка и кнопка (перечень и тексты лицензий - файлами рядом)
        self.lic = licenses_row((ui.brand.base_dir(),), font=ui.brand.font, parent=self)
        if self.lic is not None:
            root.addWidget(self.lic)

        bot = QHBoxLayout()
        quit_b = QPushButton("Выйти из программы")
        quit_b.setObjectName("quiet")
        quit_b.clicked.connect(ctl.quit)
        bot.addWidget(quit_b)
        self.admin_b = QPushButton("Нужны права - перезапустить")
        self.admin_b.setToolTip("Windows спросит подтверждение. Программа закроется и откроется с правами -\n"
                                "настройки, калибровка и клавиша останутся как есть.")
        self.admin_b.clicked.connect(ctl.restart_as_admin)
        self.admin_b.setVisible(False)
        bot.addWidget(self.admin_b)
        bot.addStretch(1)
        self.test_b = QPushButton("Свернуть сейчас")
        self.test_b.clicked.connect(ctl.toggle_windows)
        bot.addWidget(self.test_b)
        done = QPushButton("Готово")
        done.setObjectName("primary")
        done.setDefault(True)
        done.clicked.connect(self.close)
        bot.addWidget(done)
        root.addLayout(bot)
        ui.fix_fonts(self)
        # ширина кнопки по самой длинной подписи (после fix_fonts - со шрифтом окна): «Остановить» не двигает соседей
        self.check_b.setFixedWidth(self.check_b.sizeHint().width())
        self.thr_changed(self.sens.value(), save=False)
        self.key_changed(save=False)
        self.back_text()
        self.lead_text()
        self.refresh()

    # ------------------------------------------------------------ события
    def mode_changed(self, m):
        """Сколько щелчков сворачивает. «Три» - свернуть и вернуть одной и той же серией: предупреждаем."""
        self.ctl.set_mode(m)
        self.mode_warn.setVisible(m == self.ctl.settings["back"] and self.ctl.settings["back"] > 1)
        self.back_text()
        self.lead_text()

    def back_changed(self, n):
        """Сколько щелчков возвращают окна: 1 / 2 / 3."""
        self.ctl.set_back(n)
        self.mode_warn.setVisible(self.ctl.settings["mode"] == n and n > 1)
        self.back_text()
        self.lead_text()

    def lead_text(self):
        """Первая строка окна - про главное: один щелчок свернул, ещё один вернул."""
        n = self.ctl.settings["back"]
        if n == 1:
            self.lead.setText("Щёлкните пальцами - все окна свернутся, виден рабочий стол. Щёлкнули ещё раз - "
                              "окна вернулись на место, как стояли. Щёлкайте резко: важен удар, а не громкость.")
        else:
            self.lead.setText(f"Щёлкните пальцами - все окна свернутся, виден рабочий стол. "
                              f"{settings.back_series(n)} - окна вернутся на место, как стояли.")

    def back_text(self):
        """Строка «чем вернуть окна» - по текущим настройкам (клавишу можно поменять)."""
        s = self.ctl.settings
        key = s["hotkeys"].get("toggle", "")
        how = "Ещё один щелчок" if s["back"] == 1 else settings.back_series(s["back"])
        tail = "вернутся ВСЕ окна в том же порядке"
        self.back_l.setText(f"{how} или {key} - {tail}." if key else f"{how} - {tail}.")
        self.back_l.setToolTip("Возвращаются все окна, которые свернула программа (и в прошлый раз тоже), "
                               "в прежнем порядке.\nВ значке у часов есть «Вернуть все окна, которые свернул».")

    def thr_changed(self, v, save=True):
        """Ползунок порога: рядом - то же число, что в журнале и в разделе «Что происходило»."""
        self.sens_l.setText(f"щелчок от {int(v)} из 100")
        self.thr_hint.setText(f"Ниже {settings.THR_SAFE} посторонние звуки начнут сворачивать окна сами."
                              if int(v) < settings.THR_SAFE else
                              "Левее - сработает и слабый щелчок, правее - меньше случайных.")
        if save:
            self.ctl.set_thr(v)

    def fit_clicked(self):
        """«Подобрать под меня»: ставим порог по настоящим числам и говорим, что получилось."""
        info = self.ctl.apply_suggested()
        self.sens.blockSignals(True)
        self.sens.setValue(int(info["thr"]))
        self.sens.blockSignals(False)
        self.thr_changed(info["thr"], save=False)
        self.fit_l.setText(info["text"])
        self.fit_l.setVisible(True)
        self.adjustSize()

    def theme_changed(self, value):
        """Выбрали кружок или двигают ползунок оттенка - цвет меняется сразу и сохраняется."""
        name, hue = settings.theme_parts(value)
        self.ctl.set_theme(name, hue)

    def key_text(self):
        return self.key.keySequence().toString(QKeySequence.PortableText).replace("Meta", "Win")

    def key_changed(self, *_, save=True):
        txt = self.key_text()
        prob = settings.hotkey_problem(txt)
        self.key_err.setText(prob or "")
        self.key_err.setToolTip(settings.hotkey_problem_full(txt) or "")
        self.key_err.setVisible(bool(prob))
        if save and (not txt or settings.parse_hotkey(txt) is not None):
            self.ctl.set_hotkey(txt)
            self.back_text()

    def check_updates(self):
        """Кнопка «Проверить обновления»: ответ сервера появится в «Что происходило» или окном «Вышла версия»."""
        self.upd_b.setEnabled(False)
        self.ctl.check_updates_now()
        QTimer.singleShot(4000, lambda: self.upd_b.setEnabled(True))

    def admin_changed(self, on):
        """Галочка «Запускать с правами администратора»: задание планировщика + предложение перезапуститься.

        Windows спрашивает подтверждение не сразу, поэтому проверяем результат через несколько секунд и честно
        говорим, получилось или нет."""
        self.ctl.set_admin(on)
        self.refresh_admin()
        if on:
            for ms in (3000, 8000, 20000):
                QTimer.singleShot(ms, self.check_admin_task)
        self.adjustSize()

    def check_admin_task(self):
        """Задание создалось? Если да - говорим в журнал один раз, если нет после всех попыток - тоже честно."""
        if not self.ctl.settings["admin"] or getattr(self, "_task_said", False):
            return
        if self.ctl.admin_task_ok():
            self._task_said = True
            self.ctl.log.add("права администратора: задание на запуск создано - при входе в Windows программа "
                             "будет запускаться с правами")

    def refresh_admin(self):
        """Что показать про права: кнопку перезапуска ИЛИ строку про окна «от администратора» (не то и другое
        сразу - окно и так высокое; полный текст с названием окна есть в «Что происходило»)."""
        on, now = self.ctl.admin_state()
        note = self.ctl.admin_note()
        show_b = bool(on) and not now
        self.admin_b.setVisible(show_b)
        self.admin_b.setToolTip(note or "Windows спросит подтверждение один раз.")
        self.admin_l.setVisible(bool(note) and not now and not show_b)
        if self.admin_l.isVisible():
            self.admin_l.setText(note + " Включите галочку выше.")

    def check_clicked(self):
        """«Проверить мой щелчок» / «Остановить проверку»."""
        if self.ctl.checking:
            self.ctl.stop_check()
        else:
            self.ctl.start_check()
        self.refresh()

    def learn_clicked(self):
        """«Это были мои щелчки - учесть»: дообучение по живым щелчкам + новый порог."""
        info = self.ctl.learn_check()
        if info is None:
            self.fit_l.setText("Учитывать нечего: щелчков в проверке не было.")
        else:
            self.sens.blockSignals(True)
            self.sens.setValue(int(info["thr"]))
            self.sens.blockSignals(False)
            self.thr_changed(info["thr"], save=False)
            self.fit_l.setText("Учёл ваши щелчки. " + info["text"])
        self.learn_b.setVisible(False)
        self.adjustSize()

    def refresh_log(self):
        """Раздел «Что происходило»: свежие события сверху, во время проверки - счёт и остаток секунд."""
        extra = []
        if self.ctl.checking:
            n, ok = self.ctl.check_stat
            # счётчик - строкой ВНУТРИ списка, а не в подписи: иначе окно прыгает в ширину во время проверки
            self.log_head.setText(f"Проверяю: {self.ctl.check_left()} с")
            self.check_b.setText("Остановить")
            extra = [f"щёлкните несколько раз · звуков {n}, похожих на щелчок {ok}"]
        else:
            self.log_head.setText("Что происходило")
            self.check_b.setText("Проверить мой щелчок")
            if self.ctl.check_result:
                extra = [f"проверка: {self.ctl.check_result}"]
                self.learn_b.setVisible(bool(self.ctl.check_snaps))
        lines = extra + self.ctl.log.lines(3 - len(extra))
        text = "\n".join(lines) if lines else "Пока ничего не слышал."
        if text != self.log_view.toPlainText():
            self.log_view.setPlainText(text)

    def refresh(self):
        """Состояние программы -> надписи (по таймеру окна)."""
        self.refresh_log()
        self.refresh_admin()
        hint = self.ctl.mic_hint()
        if hint != self.mic_hint.text():
            self.mic_hint.setText(hint)
            self.mic_hint.setVisible(bool(hint))
        ch = self.ctl.calib_hint()
        if ch != self.calib_l.text():
            self.calib_l.setText(ch)
            self.calib_l.setVisible(bool(ch))
        st = self.ctl.status()
        color = STATUS_COLOR[st]
        self.status.setText(f"● {self.ctl.state_text()}")
        self.test_b.setText("Вернуть все окна" if st == "hidden" else "Свернуть сейчас")
        self.status.setStyleSheet(ui.brand.tint_css(f"color: {color}; background: rgba(20, 0, 60, 150); "
                                                    "border-radius: 12px; padding: 4px 12px;"))
        self.listen_b.setText("Пауза" if self.ctl.settings["listening"] else "Слушать")
        self.meter.update()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.theme0 = settings.theme_value(self.ctl.settings)     # Esc («Отмена») вернёт этот цвет
        self.refresh()

    def eventFilter(self, obj, ev):
        """Запасная клавиша отдаётся полю ввода ТОЛЬКО пока в нём курсор; всё остальное время Ctrl+Alt+Z работает
        как всегда - раньше она пропадала на всё время, пока открыто окно (баг 16.10.2026: окна свернулись, окно
        «Щелчок» спряталось вместе с ними, а клавиша осталась незарегистрированной)."""
        if obj is self.key:
            if ev.type() == QEvent.FocusIn:
                self.ctl.unregister_hotkeys()
            elif ev.type() == QEvent.FocusOut:
                self.ctl.register_hotkeys()
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, ev):
        """Esc - как «Отмена» в Маркере и Суфлёре: вернуть прежний цвет оформления и закрыть окно."""
        if ev.key() == Qt.Key_Escape:
            self.cancel_theme()
            self.close()
            return
        super().keyPressEvent(ev)

    def cancel_theme(self):
        old = getattr(self, "theme0", None)
        if old and old != settings.theme_value(self.ctl.settings):
            name, hue = settings.theme_parts(old)
            self.ctl.set_theme(name, hue)
            self.theme.set_value(old, emit=False)

    def closeEvent(self, ev):
        super().closeEvent(ev)
        self.ctl.register_hotkeys()
