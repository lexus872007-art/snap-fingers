# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Окно «Настройка щелчка»: человек щёлкает 5 раз (можно до 7) -> шаблон ИМЕННО его щелчка на ЭТОМ микрофоне
(форма спектра, затухание, громкость) и порог под него. Потом - проверка: каждый следующий звук получает оценку.
Пока окно открыто, окна не сворачиваются.

Почему пять, а не три (жалоба владельца 16.10.2026 - его щелчки получали 27-70 при пороге 45): шаблон по трём
щелчкам сидит на этих трёх, а живой щелчок каждый раз чуть другой. Поэтому: просим щёлкать с разной силой и с
разного расстояния, храним ВСЕ образцы (сравнение идёт с лучшим из них), один непохожий просто выбрасываем, а в
конце честно считаем, насколько хорошо получилось узнавать (`tuning.quality`), и подбираем порог.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLayout, QHBoxLayout, QPushButton, QVBoxLayout

from . import detector, tuning, ui
from .widgets import Dots, LevelMeter, ScoreBar

NEED = 5                 # столько щелчков просим (из них один непохожий можно отбросить - останется четыре)
STEP_HINT = ["Щёлкните как обычно.",
             "Теперь чуть тише - как будто торопитесь.",
             "Теперь резче и звонче.",
             "Теперь чуть дальше от компьютера.",
             "И ещё раз, как обычно."]


class CalibWindow(ui.FlowWindow):
    def __init__(self, ctl):
        super().__init__(ctl, "Настройка щелчка")
        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SetMinimumSize)   # окно не меньше содержимого при любом масштабе
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)
        root.addWidget(ui.label("Настройка щелчка", 22, QFont.ExtraBold))
        self.lead = ui.label("", 15, QFont.DemiBold, wrap=True)
        root.addWidget(self.lead)
        g, lay = ui.glass()
        self.dots = Dots(NEED)
        self.dots.setMinimumWidth(500)
        lay.addWidget(self.dots)
        self.msg = ui.label("", 15, QFont.ExtraBold, "key", wrap=True)
        self.msg.setAlignment(Qt.AlignHCenter)
        lay.addWidget(self.msg)
        self.mic_l = ui.label("", 12, QFont.DemiBold, "hint", wrap=True)
        lay.addWidget(self.mic_l)
        self.meter = LevelMeter(ctl)
        lay.addWidget(self.meter)
        self.scores = ScoreBar(ctl)
        lay.addWidget(self.scores)
        root.addWidget(g)
        self.result = ui.label("", 13, QFont.Bold, "key", wrap=True)
        root.addWidget(self.result)
        self.advice = ui.label("", 12, QFont.Bold, "err", wrap=True)
        root.addWidget(self.advice)
        root.addWidget(ui.label("Щёлкайте так же, как потом в работе: той же рукой и на том же расстоянии от "
                                "компьютера. Чем больше разных щелчков услышит программа сейчас, тем лучше узнает "
                                "ваш щелчок потом. Звук не записывается - программа запоминает только «отпечаток» "
                                "щелчка.", 12, QFont.DemiBold, "hint", wrap=True))
        bot = QHBoxLayout()
        bot.addStretch(1)
        self.again = QPushButton("Переснять")
        self.again.clicked.connect(self.reset)
        bot.addWidget(self.again)
        self.done_b = QPushButton("Готово")
        self.done_b.setObjectName("primary")
        self.done_b.clicked.connect(self.close)
        bot.addWidget(self.done_b)
        root.addLayout(bot)
        ui.fix_fonts(self)
        self.reset()

    # ------------------------------------------------------------ шаги
    def reset(self):
        self.cands = []
        self.dropped = 0
        self.stage = "collect"           # collect -> test
        self.dots.set_done(0)
        self.scores.hide()
        self.result.setText("")
        self.result.setVisible(False)
        self.advice.setText("")
        self.advice.setVisible(False)
        self.lead.setText(f"Щёлкните пальцами {NEED} раз, между щелчками - секунда. Щёлкайте по-разному: "
                          f"сильнее и тише, ближе и дальше - так, как получается в жизни.\n"
                          f"Щёлкайте РЕЗКО: важен удар, а не громкость. Это только настройка - в работе "
                          f"хватит одного щелчка.")
        self.msg.setText(f"Жду щелчок 1 из {NEED}… {STEP_HINT[0]}")
        self.done_b.setEnabled(self.ctl.template() is not None)
        self.mic_l.setText(f"Микрофон: {self.ctl.mic_name()}"
                           + (f"\n{self.ctl.mic_hint()}" if self.ctl.mic_hint() else ""))

    def on_candidate(self, c):
        """Удар из микрофона (все признаки) - от контроллера."""
        if self.stage == "test":
            return
        reason = detector.gates(c, strict=False)
        if not reason and c["snr"] < 15:
            reason = "тихо"
        if reason:
            if c["snr"] >= 12:
                hint = {"тихо": "Тихо - щёлкните ближе к компьютеру",
                        "долгий звук": "Это был не щелчок (долгий звук) - ещё раз",
                        "низкий звук": "Похоже на стук или хлопок - щёлкните пальцами",
                        "звук до удара": "Мешает шум рядом - ещё раз, в тишине",
                        "звук после удара": "Мешает шум рядом - ещё раз, в тишине",
                        "медленно нарастает": "Это был не щелчок - ещё раз"}.get(reason, "Ещё раз")
                self.msg.setText(hint)
            return
        self.cands.append(c)
        k = len(self.cands)
        self.dots.set_done(k)
        if k < NEED:
            self.msg.setText(f"Есть! Жду щелчок {k + 1} из {NEED}… {STEP_HINT[min(k, len(STEP_HINT) - 1)]}")
            return
        kept, dropped = detector.pick_calib(self.cands, need=NEED)
        if not kept:
            self.cands = []
            self.dots.set_done(0)
            self.msg.setText("Щелчки получились очень разными - давайте ещё раз, одинаково")
            return
        self.dropped = len(dropped)
        self.finish(kept)

    def finish(self, kept):
        """Шаблон из отобранных щелчков + порог под этого человека + честная оценка, что получилось."""
        ctl = self.ctl
        ctl.set_template(detector.make_template(kept))
        scores = tuning.loo_scores(kept, thr=ctl.threshold())
        info = tuning.suggest_threshold(scores, ctl.scores.noise(), cur=ctl.threshold())
        ctl.set_thr(info["thr"])
        q = tuning.quality(scores, info["thr"])
        self.stage = "test"
        ctl.recent.clear()
        ctl.log.add(f"настройка щелчка: образцов {len(kept)}"
                    + (" (один непохожий отбросил)" if self.dropped == 1 else
                       f" (непохожих отбросил: {self.dropped})" if self.dropped else "")
                    + f", порог {info['thr']}, узнаваемость примерно {q} из 100")
        self.scores.show()
        self.lead.setText("Готово! Проверьте: щёлкните ещё раз - точка на шкале должна уйти вправо, за жёлтую "
                          "черту. В работе один щелчок сворачивает окна, ещё один - возвращает.")
        self.msg.setText("Щелчок запомнил")
        self.result.setText(tuning.calib_text(scores, info["thr"]) + f" Образцов: {len(kept)}.")
        self.result.setVisible(True)
        adv = tuning.calib_advice(scores, info["thr"], loud=min(c["snr"] for c in kept),
                                  noise_max=info["noise_max"])
        self.advice.setText(adv)
        self.advice.setVisible(bool(adv))
        self.again.setText("Переснять" if not adv else "Переснять настройку")
        self.done_b.setEnabled(True)
        self.adjustSize()

    def refresh(self):
        self.meter.update()
        self.scores.update()
        if self.stage == "test":
            t = self.ctl.last_text()
            if t:
                self.msg.setText(t)

    def closeEvent(self, ev):
        super().closeEvent(ev)
        self.ctl.calibration_closed()
