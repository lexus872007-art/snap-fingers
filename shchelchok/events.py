"""Журнал событий человеческими словами: что программа услышала и почему это не сработало.

Требование владельца 16.10.2026 («добавь в щелчок журнал событий, он на третий раз перестал работать, а должен
работать как швейцарские часы»): на каждый звук, похожий на щелчок, - строка со временем, оценкой и вердиктом.
Раньше журнал писал ТОЛЬКО удачи («свернул окна: 12»), и почему щелчок не приняли, не было видно вообще.

Одно и то же описание идёт и в файл `%APPDATA%\\Щелчок\\log.txt`, и в раздел «Что происходило» в окне программы.
Сам звук не записывается и никуда не уходит - только числа и слова.
"""
from __future__ import annotations

import time
from collections import deque

from . import journal
from .detector import MAYBE, NOISE, SNAP

LOG_GAP = 25.0           # звук с оценкой не ниже «порог минус столько» получает свою строку в журнале

# Почему звук не щелчок - словами, без терминов. Слева - короткие причины из detector.score/gates и защиты.
WHY = {
    "медленно нарастает": "звук нарастает плавно, а у щелчка удар резкий",
    "долгий звук": "звук слишком долгий для щелчка",
    "звук до удара": "прямо перед этим был другой звук",
    "звук после удара": "сразу после этого был другой звук",
    "низкий звук": "звук слишком низкий для щелчка",
    "тише щелчка": "тише, чем на настройке - щёлкните ближе к микрофону",
    "не похоже на щелчок": "похоже недостаточно",
    "нужна настройка": "щелчок ещё не настроен",
    "нажали клавишу": "в этот момент печатали на клавиатуре",
    "щёлкнули мышью": "в этот момент щёлкнули мышью",
    "клавиатура или мышь": "в этот момент печатали или двигали мышью",
    "звук компьютера": "звук пришёл из колонок компьютера",
}
# Что с принятым щелчком сделало решение (detector.Clicker.push)
VERDICT = {
    "cooldown": "ещё идёт пауза после прошлого срабатывания",
    "just_restored": "только что вернул окна - сворачивать обратно пока не буду",
    "noise_before": "прямо перед щелчком был посторонний звук",
    "maybe": "для сворачивания щелчок должен быть увереннее",
}
MISS = {
    "timeout": "не дождался второго щелчка",
    "noise_after": "сразу после щелчков был посторонний звук",
    "half": "щелчков в серии не хватило",
}

# Окна, запущенные от имени администратора: Windows не даёт обычной программе ими управлять (см. winapi).
ADMIN_FIX = "чтобы и такие окна слушались, включите «Запускать с правами администратора» в окне «Щелчок»"


def word_windows(n):
    """«1 окно» / «2 окна» / «5 окон»."""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return f"{n} окно"
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return f"{n} окна"
    return f"{n} окон"


def admin_line(titles, fix=True):
    """Строка про окна «от имени администратора» - теми же словами в журнале и в окне «Что происходило»."""
    names = [str(t).strip() for t in titles if str(t).strip()]
    n = len(titles)
    if not n:
        return ""
    if n == 1:
        who = f"окно «{names[0]}»" if names else "окно"
        t = f"{who} запущено от имени администратора - свернуть/вернуть его без прав нельзя"
    else:
        who = (": " + ", ".join(f"«{x}»" for x in names[:3])) if names else ""
        t = (f"{word_windows(n)} запущены от имени администратора - свернуть/вернуть их без прав нельзя{who}")
    return f"{t} ({ADMIN_FIX})" if fix else t


def describe(ev, need=2, gap_max=1.0):
    """Событие детектора -> одна строка для человека: «41 из 100 · не щелчок: похоже недостаточно (порог 55)»."""
    need = ev.get("need") or need
    gap_max = ev.get("gap_max") or gap_max
    sc = int(round(ev.get("score") or 0))
    thr = int(round(ev.get("thr") or 0))
    head = f"{sc} из 100"
    v = ev.get("verdict")
    if ev.get("ok"):
        if v == "series":
            return f"{head} · щелчок - серия собрана"
        if v == "started":
            what = f"жду второй щелчок (до {_sec(gap_max)})" if need > 1 else "жду"
            return f"{head} · щелчок принят, {what}"
        if v in VERDICT:
            return f"{head} · щелчок, но {VERDICT[v]}"
        return f"{head} · щелчок"
    # звук сам по себе не щелчок - называем ЕГО причину, а не «идёт пауза»: пауза тут ни при чём
    why = WHY.get(ev.get("reason") or "", ev.get("reason") or "не щелчок")
    if ev.get("reason") == "не похоже на щелчок":
        why = f"похоже недостаточно (порог {thr})"
    return f"{head} · не щелчок: {why}"


def miss_text(code, gap_max=1.0):
    """Серия не сложилась -> строка для человека (владелец просил с цифрой: «ждал 1 с»)."""
    why = MISS.get(code)
    if why is None:
        return None
    return f"не сработало: {why} (ждал {_sec(gap_max)})" if code == "timeout" else f"не сработало: {why}"


def worth_line(ev):
    """Этот звук заслуживает своей строки в журнале? Щелчки и почти-щелчки - да; посторонний шум - нет (он идёт
    числом в сводке), но звук, который был похож на щелчок и чуть не дотянул, - да (иначе не видно, ПОЧЕМУ)."""
    if ev.get("kind") in (SNAP, MAYBE):
        return True
    return (ev.get("score") or 0) >= (ev.get("thr") or 0) - LOG_GAP


def _sec(v):
    """0.8 -> «0,8 с», 1.0 -> «1 с»."""
    s = f"{v:.1f}".replace(".0", "").replace(".", ",")
    return f"{s} с"


class EventLog:
    """Последние события словами: окно «Что происходило» (свежие сверху) + строки в файл журнала.

    Посторонние звуки (клавиатура, речь, шорох) идут не строкой каждый, а числом раз в SUM_EVERY секунд -
    иначе за день журнал забьётся шумом и в нём не найти щелчок."""

    SUM_EVERY = 120.0

    def __init__(self, n=120):
        self.items = deque(maxlen=n)          # [(время, строка)] - свежие в конце
        self.noise = 0
        self._next_sum = None

    def push(self, text):
        """Строка пришла в файл журнала (в том числе из сторожа микрофона) - показываем её и в окне."""
        self.items.append((time.strftime("%H:%M:%S"), str(text)))

    def add(self, text, to_file=True):
        """Строка в окно и (по желанию) в файл журнала."""
        if to_file:
            journal.write(text)               # оттуда она вернётся в окно через push (journal.set_hook)
        else:
            self.push(text)
        return text

    def lines(self, n=8):
        """Последние строки для окна - свежие сверху."""
        return [f"{t}  {s}" for t, s in list(self.items)[-n:]][::-1]

    def count_noise(self, now=None):
        """Посторонний звук - просто считаем; строку сводки отдаём, когда пришло время."""
        now = time.monotonic() if now is None else now
        self.noise += 1
        if self._next_sum is None:
            self._next_sum = now + self.SUM_EVERY
        return self.flush_noise(now)

    def flush_noise(self, now=None):
        """-> строка сводки по посторонним звукам, если пора (иначе None)."""
        now = time.monotonic() if now is None else now
        if self._next_sum is None or now < self._next_sum or not self.noise:
            return None
        n, self.noise, self._next_sum = self.noise, 0, now + self.SUM_EVERY
        return self.add(f"посторонних звуков за две минуты: {n} (не щелчки)")
