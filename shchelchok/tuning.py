"""Настройка под человека: насколько хорошо узнаётся ЕГО щелчок, какой порог ему подходит, что ему сказать.

Без Qt и без numpy - проверяется тестами на числах.

Зачем (жалоба владельца 16.10.2026 по журналу с его ноутбука): его щелчки получали оценки 27-70 при пороге 45,
то есть половина промахивалась на 1-5 очков - «идеального щелчка нету». Три вывода:
1. Шаблон, снятый по ТРЁМ щелчкам, сидит слишком близко к этим трём: 5-7 щелчков разной силы дают шаблон,
   похожий на все живые щелчки человека, а не на три удачных.
2. Порог должен быть ЕГО: по оценкам его же щелчков (честно - каждый оценён шаблоном из ОСТАЛЬНЫХ, `loo_scores`)
   и по тому, насколько похожи на щелчок посторонние звуки в его комнате.
3. Человеку надо сказать числом, что получилось: «ваш щелчок узнаётся примерно на 85 из 100».
"""
from __future__ import annotations

import math
import time

from . import detector

MARGIN = 2.0             # запас ниже самого тихого из своих щелчков
NOISE_GAP = 3.0          # на столько очков выше самого похожего на щелчок постороннего звука
KEEP_FRAC = 0.85         # столько своих щелчков порог обязан пропускать
THR_SUGGEST_MAX = 60.0   # выше не советуем сами: там живые щелчки начинают промахиваться
SD_MIN = 4.0             # разброс оценок меньше этого не бывает (три похожих щелчка дают ложную точность)
NOISE_WINDOW = 900.0     # посторонние звуки за столько секунд считаем «обстановкой в комнате»
# Щелчок при настройке звучит лучше, чем в работе: настройка идёт в тишине, а работают при шуме. Измерено на
# записях CC0 (eval/calib_n.py --drop, 12 «людей»): в тихой комнате живой щелчок получает на 1 очко меньше, чем
# щелчок настройки, в шуме офиса и при разговоре рядом - на 24 очка меньше. Поэтому порог, посчитанный ПО
# ЩЕЛЧКАМ НАСТРОЙКИ, опускаем на CAL_DROP: иначе он выходит слишком строгим и человек промахивается половину
# раз (ровно это и было у владельца: настройка в тишине, работа при шуме, порог 45 и оценки 27-70).
# Берём 20 - ближе к шумному случаю, он и есть жизнь; окончательно порог подстраивается по ЖИВЫМ щелчкам
# («Проверить мой щелчок» -> «Это были мои щелчки - учесть»), там поправка не нужна вовсе.
CAL_DROP = 20.0
SNAP_NEAR = 2.0          # звук в пределах столько секунд от узнанного щелчка - часть того же жеста, не шум


def loo_scores(cands, thr=None):
    """Оценка каждого щелчка настройки шаблоном из ОСТАЛЬНЫХ щелчков.

    Так оценку получит НОВЫЙ щелчок: сравнивать щелчок с шаблоном, в котором он сам и сидит, - обманывать себя
    (оценки выходят на 10-20 очков выше, чем в жизни)."""
    out = []
    n = len(cands)
    if n < 3:
        return out
    for i in range(n):
        rest = cands[:i] + cands[i + 1:]
        tpl = detector.make_template(rest)
        if tpl is None:
            continue
        s, _ = detector.score(cands[i], tpl, thr=thr if thr is not None else detector.THR_DEFAULT)
        out.append(round(s, 1))
    return out


def _mean_sd(values):
    n = len(values)
    m = sum(values) / n
    if n < 2:
        return m, SD_MIN
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    return m, max(SD_MIN, math.sqrt(var))


def quality(scores, thr):
    """«Ваш щелчок узнаётся примерно на N из 100»: сколько раз из ста щелчок перейдёт порог.

    Считаем по оценкам своих же щелчков (их разброс и есть ответ): доля выше порога по нормальной модели -
    на 5-7 щелчках простая доля «сколько из 7 прошло» даёт только 0, 14, 29… и обманывает."""
    if not scores:
        return 0
    m, sd = _mean_sd(list(scores))
    z = (m - float(thr)) / (sd * math.sqrt(2))
    p = 0.5 * (1.0 + math.erf(z))
    return int(round(100 * max(0.02, min(0.99, p))))


def suggest_threshold(own, noise=(), cur=None, cal=()):
    """Порог под этого человека. -> dict(thr, hits, total, noise_max, quality, floor).

    own - оценки ЖИВЫХ щелчков (как есть), cal - оценки щелчков с настройки (им делается поправка CAL_DROP).
    Правило: порог ниже самого тихого из своих щелчков (с запасом MARGIN), но не ниже самого похожего на щелчок
    постороннего звука (с запасом NOISE_GAP) и не ниже THR_MIN - иначе окна начнут сворачиваться сами."""
    own = sorted([float(v) for v in own] + [float(v) - CAL_DROP for v in cal])
    noise_max = max([float(v) for v in noise], default=0.0)
    floor = max(detector.THR_MIN, noise_max + NOISE_GAP)
    if not own:
        thr = float(cur if cur is not None else detector.THR_DEFAULT)
        thr = max(floor, min(detector.THR_MAX, thr))
    else:
        # порог, который пропускает KEEP_FRAC своих щелчков (а не все: один тихий не должен тянуть порог на дно)
        i = max(0, min(len(own) - 1, int(math.floor(len(own) * (1.0 - KEEP_FRAC)))))
        thr = min(own[i] - MARGIN, THR_SUGGEST_MAX)
        thr = max(floor, min(detector.THR_MAX, thr))
    thr = int(round(thr))
    return {"thr": thr, "hits": sum(1 for v in own if v >= thr), "total": len(own),
            "noise_max": int(round(noise_max)), "quality": quality(own, thr), "floor": int(round(floor))}


def quality_word(q):
    """Оценка настройки словами (ничего не выдумываем - только пересказ числа)."""
    if q >= 85:
        return "это хорошо"
    if q >= 70:
        return "это нормально"
    if q >= 50:
        return "так себе"
    return "это мало"


def calib_text(scores, thr, noise_max=0.0):
    """Итог настройки человеку: «Ваш щелчок узнаётся примерно на 85 из 100 - это хорошо»."""
    q = quality(scores, thr)
    t = f"Ваш щелчок узнаётся примерно на {q} из 100 - {quality_word(q)}."
    if scores:
        lo, hi = int(round(min(scores))), int(round(max(scores)))
        t += f" Оценки ваших щелчков: от {lo} до {hi}, порог {int(round(thr))}."
    return t


def calib_advice(scores, thr, loud=None, noise_max=0.0):
    """Если настройка вышла плохой - что сделать человеку (конкретно, а не «попробуйте ещё»). -> строка или ''."""
    q = quality(scores, thr)
    if q >= 70:
        return ""
    tips = []
    if loud is not None and loud < 20:
        tips.append("щёлкайте ближе к микрофону - щелчок приходит тихим")
    if noise_max >= thr - 5:
        tips.append("в комнате шумно: посторонние звуки похожи на щелчок, лучше переснять в тишине")
    if scores and max(scores) - min(scores) > 25:
        tips.append("щёлкайте одинаково: сейчас щелчки получились очень разными")
    tips.append("щёлкайте резче - щелчок должен быть звонким, а не глухим")
    return "Лучше переснять настройку: " + "; ".join(tips[:2]) + "."


def _word_snaps(n):
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return f"{n} щелчка"
    return f"{n} щелчков"


def suggest_text(info, cur, noise_count=0):
    """Что сказать человеку про предложенный порог - настоящими числами, без обещаний.

    «Предлагаю порог 40: из ваших 12 щелчков прошло бы 11. Посторонних звуков было 64, самый похожий получил 31.»"""
    thr, total, hits = info["thr"], info["total"], info["hits"]
    if total:
        t = f"Предлагаю порог {thr}: из ваших {_word_snaps(total)} прошло бы {hits}."
    else:
        t = f"Предлагаю порог {thr}."
    if noise_count:
        t += (f" Посторонних звуков было {noise_count}, самый похожий получил {info['noise_max']}."
              if info["noise_max"] else f" Посторонних звуков было {noise_count}, ни один не был похож на щелчок.")
    if int(round(float(cur))) == thr:
        t += " Это и стоит сейчас."
    return t


def check_text(scores, thr, suggested=None):
    """Итог режима «Проверить мой щелчок» словами: «ваши щелчки: от 27 до 70, порог сейчас 45, предлагаю 40»."""
    if not scores:
        return f"щелчков не услышал, порог сейчас {int(round(thr))}"
    lo, hi = int(round(min(scores))), int(round(max(scores)))
    t = f"ваши щелчки: от {lo} до {hi}, порог сейчас {int(round(thr))}"
    if suggested is not None and int(suggested) != int(round(thr)):
        t += f", предлагаю {int(suggested)}"
    return t


class ScoreHistory:
    """Оценки последних звуков: свои щелчки и посторонние - раздельно (для кнопки «Подобрать под меня»).

    «Свой щелчок» - звук, который программа приняла за щелчок, или тот, что человек подтвердил кнопкой «Это были
    мои щелчки». «Посторонний» - звук, рядом с которым (SNAP_NEAR секунд) узнанного щелчка не было: иначе в шум
    попадут собственные промахи того же жеста, и порог сам себя задерёт вверх."""

    def __init__(self, n=400, clock=time.monotonic):
        self.items = []          # [(время, оценка, щелчок?)]
        self.n = n
        self.clock = clock

    def add(self, score, is_snap, now=None):
        now = self.clock() if now is None else now
        self.items.append((now, float(score), bool(is_snap)))
        if len(self.items) > self.n:
            del self.items[:len(self.items) - self.n]

    def own(self, window=NOISE_WINDOW, now=None):
        now = self.clock() if now is None else now
        return [s for t, s, ok in self.items if ok and now - t <= window]

    def noise(self, window=NOISE_WINDOW, now=None):
        """Посторонние звуки за окно - без тех, что стоят рядом с узнанным щелчком (это свои промахи)."""
        now = self.clock() if now is None else now
        snaps = [t for t, _, ok in self.items if ok]
        out = []
        for t, s, ok in self.items:
            if ok or now - t > window:
                continue
            if any(abs(t - st) <= SNAP_NEAR for st in snaps):
                continue
            out.append(s)
        return out

    def noise_count(self, window=NOISE_WINDOW, now=None):
        return len(self.noise(window, now))
