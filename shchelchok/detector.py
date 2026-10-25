"""Распознавание щелчка пальцами по звуку микрофона. Без Qt, без numpy, без звуковой карты - проверяется на wav.

Звук никуда не пишется: в памяти только последние ~0,5 с (кольцевой буфер) для разбора удара.

Два шага:
1. Frontend - кандидаты «резкий удар»: сигнал после фильтра верхних частот (от ~1 кГц) по кадрам 1 мс; фон -
   нижняя треть громкостей 10-мс кадров за 2 с (плавающий фон, медианного типа - не дёргается от ударов); кандидат,
   если кадр громче фона на onset_db и на jump_db громче, чем 5-20 мс назад. Через 130 мс у кандидата считаем
   признаки: нарастание (мс до пика), затухание (мс до -20 дБ от пика), тишина до (60 мс) и после (50-110 мс от
   пика), спектр 16 мс от начала удара (14 полос 200-8000 Гц, форма в дБ), центроид, доля низких частот,
   профиль затухания (6 точек).
2. Template / score - сходство с ШАБЛОНОМ щелчка этого человека на этом микрофоне (калибровка: 3 щелчка).
   Оценка 0-100: форма спектра + профиль затухания + громкость; жёсткие запреты (долгий звук, звук вокруг,
   медленное нарастание, низкий звук) - оценка не выше 20, с причиной.

Clicker - решение: свернуть - одиночный (по умолчанию) / двойной / тройной щелчок; вернуть - ДВА щелчка подряд
(решение владельца 16.10.2026, до этого было три); «тишина вокруг» (300 мс после и 500 мс до серии нет других
ударов), пауза 1,5 с после срабатывания. Щёлкают дальше (3, 4, 5 раз подряд) - серией считаются последние щелчки,
а не «всё отменить»: владелец, у которого не вышло с первого раза, щёлкает ещё, и это обязано сработать.

ВОЗВРАТ ОКОН МЯГЧЕ, ЧЕМ СВОРАЧИВАНИЕ (16.10.2026, жалоба «на третий раз перестал работать»). Когда окна уже
свёрнуты, цена ошибки мала - окна просто вернутся, поэтому на возврат: порог оценки мягче на RESTORE_SENS_BONUS,
«тишина вокруг» короче, промежуток между щелчками шире, и ПОЧТИ-щелчок (оценка ниже порога не больше чем на
MAYBE_GAP) годится вторым в пару, если первый - уверенный щелчок. Главное: НЕУЗНАННЫЙ щелчок больше не глушит
следующий. Было (1.1.0): неузнанный звук в 0,5 с перед щелчком запрещал начинать серию, а свои же щелчки как раз и
попадали в эти 0,5 с - один промах, и сколько ни щёлкай, возврат не срабатывал НИКОГДА (доказано прогоном:
12 щелчков подряд, второй мимо - ни одного возврата). Теперь «тишине вокруг» мешает только посторонний шум
(kind "noise"), а свои щелчки и почти-щелчки - нет.
"""
from __future__ import annotations

import cmath
import math
from array import array
from collections import deque

SR = 16000
FR = SR // 1000                 # сэмплов в кадре 1 мс
FLOOR_DB = -100.0
PRE_MS, POST_MS = 60, 130       # окно разбора удара
FFT_N = 256                     # 16 мс
# 14 полос: 100-500 Гц одной полосой (стук, «бух»), дальше 13 полос 0,5-7,9 кГц логарифмически
BAND_EDGES = [100.0] + [500 * (7900 / 500) ** (i / 13) for i in range(14)]
NBANDS = len(BAND_EDGES) - 1
DEC_POINTS = (2, 4, 8, 16, 32, 64)


def db(v):
    return 20 * math.log10(v) if v > 1e-5 else FLOOR_DB


# ---------------------------------------------------------------- фильтр и БПФ
class Biquad:
    """Фильтр верхних частот 2-го порядка (Баттерворт)."""

    def __init__(self, fc, sr=SR):
        w = 2 * math.pi * fc / sr
        cw, sw = math.cos(w), math.sin(w)
        alpha = sw / (2 * 0.7071)
        a0 = 1 + alpha
        self.b0 = (1 + cw) / 2 / a0
        self.b1 = -(1 + cw) / a0
        self.b2 = self.b0
        self.a1 = -2 * cw / a0
        self.a2 = (1 - alpha) / a0
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0


def fft(x):
    """Радикс-2 БПФ (длина - степень двойки), чистый Python - только для кандидатов (редко)."""
    n = len(x)
    a = [complex(v) for v in x]
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    size = 2
    while size <= n:
        w = cmath.exp(-2j * math.pi / size)
        half = size // 2
        for s in range(0, n, size):
            wk = 1 + 0j
            for k in range(s, s + half):
                t = a[k + half] * wk
                a[k + half] = a[k] - t
                a[k] = a[k] + t
                wk *= w
        size *= 2
    return a


FRAME_N = 128                   # кадр спектра 8 мс; спектр = среднее 3 кадров с шагом 4 мс (меньше разброс)
_HANN = [0.5 - 0.5 * math.cos(2 * math.pi * i / (FRAME_N - 1)) for i in range(FRAME_N)]


def power_spectrum(seg):
    """Спектр мощности: среднее 3 кадров по 8 мс с шагом 4 мс (меньше случайный разброс)."""
    seg = list(seg[:FFT_N]) + [0.0] * max(0, FFT_N - len(seg))
    pw = [0.0] * (FRAME_N // 2)
    for st in (0, FRAME_N // 2, FRAME_N):
        fr = seg[st:st + FRAME_N]
        m = sum(fr) / FRAME_N
        sp = fft([(v - m) * w for v, w in zip(fr, _HANN)])
        for i in range(FRAME_N // 2):
            pw[i] += abs(sp[i]) ** 2
    return pw


def spectrum_features(seg, sr=SR, noise_seg=None):
    """Сегмент (FFT_N сэмплов, -1..1) -> (полосы дБ, форма полос (минус среднее), центроид Гц, низкие-к-средним дБ).
    noise_seg - звук перед ударом: его спектр вычитается (шум офиса, вентилятор не портят «отпечаток» щелчка)."""
    hz = sr / FRAME_N
    pw = power_spectrum(seg)
    if noise_seg is not None and len(noise_seg) >= FFT_N:
        pn = power_spectrum(noise_seg)
        pw = [max(p - n, 0.05 * p) for p, n in zip(pw, pn)]
    bands = []
    for lo, hi in zip(BAND_EDGES[:-1], BAND_EDGES[1:]):
        i0 = int(round(lo / hz))
        i1 = max(i0 + 1, int(round(hi / hz)))
        bands.append(10 * math.log10(sum(pw[i0:i1]) / (i1 - i0) + 1e-12))
    mean = sum(bands) / len(bands)
    shape = [b - mean for b in bands]
    tot = sum(pw[2:]) + 1e-12
    centroid = sum(i * hz * p for i, p in enumerate(pw) if i >= 2) / tot
    low = sum(pw[2:int(800 / hz)]) + 1e-12
    mid = sum(pw[int(1500 / hz):int(6000 / hz)]) + 1e-12
    return bands, shape, centroid, 10 * math.log10(low / mid)


# ---------------------------------------------------------------- шаг 1: удары
class Frontend:
    """Поток сэмплов -> кандидаты-удары с признаками. feed() возвращает список новых кандидатов (dict)."""

    def __init__(self, sr=SR, hp_hz=1000.0, onset_db=12.0, jump_db=9.0, abs_min_db=-62.0):
        if sr != SR:
            raise ValueError("нужно 16 кГц")
        self.hp = Biquad(hp_hz)
        self.onset_db, self.jump_db, self.abs_min_db = onset_db, jump_db, abs_min_db
        self.reset()

    def reset(self, keep_clock=False):
        """keep_clock=True - часы потока (nframes) НЕ обнуляются: микрофон переподключился, а время идёт дальше.
        Иначе Clicker (пауза после срабатывания, «тишина вокруг») остаётся в старом времени и глохнет на столько
        секунд, сколько программа успела проработать до переподключения (баг 16.10.2026)."""
        n = self.nframes if keep_clock else 0
        self.raw = array("f")             # сырые сэмплы (последние ~0,5 с)
        self.raw0 = n * FR                # номер сэмпла raw[0] от начала потока
        self.env = array("f")             # пик кадра 1 мс после фильтра, дБ
        self.env0 = n                     # номер кадра env[0]
        self.nframes = n
        self._fpk = 0.0
        self._fn = 0
        self._sq = 0.0
        self._sqn = 0
        self.noise_hist = deque(maxlen=200)   # 10-мс громкости за 2 с
        self.noise_db = None
        self.pending = []
        self.last_onset = -10 ** 9
        self.level_db = FLOOR_DB          # для шкалы в окне (пик последних кадров, полная полоса)
        self._lvl = 0.0

    @property
    def t(self):
        return self.nframes / 1000.0

    def feed(self, samples, scale=1 / 32768.0):
        """samples - int16 (array/список) или float -1..1 (scale=1)."""
        out = []
        hp = self.hp
        b0, b1, b2, a1, a2 = hp.b0, hp.b1, hp.b2, hp.a1, hp.a2
        x1, x2, y1, y2 = hp.x1, hp.x2, hp.y1, hp.y2
        fpk, fn, sq, sqn, lvl = self._fpk, self._fn, self._sq, self._sqn, self._lvl
        raw = self.raw
        for v in samples:
            x = v * scale
            raw.append(x)
            y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1, y2, y1 = x1, x, y1, y
            ay = y if y >= 0 else -y
            if ay > fpk:
                fpk = ay
            ax = x if x >= 0 else -x
            if ax > lvl:
                lvl = ax
            sq += y * y
            fn += 1
            if fn == FR:
                self.env.append(db(fpk))
                self.nframes += 1
                sqn += 1
                if sqn == 10:
                    self.noise_hist.append(10 * math.log10(sq / (10 * FR) + 1e-12))
                    sq, sqn = 0.0, 0
                    if len(self.noise_hist) >= 20 and self.nframes % 50 == 0 or self.noise_db is None:
                        h = sorted(self.noise_hist)
                        self.noise_db = h[len(h) // 3] + 6.0     # пик кадра ~ на 6 дБ выше RMS
                fpk, fn = 0.0, 0
                self.level_db = 0.97 * self.level_db + 0.03 * db(lvl) if self.level_db > FLOOR_DB else db(lvl)
                lvl = 0.0
                self._frame(out)
        hp.x1, hp.x2, hp.y1, hp.y2 = x1, x2, y1, y2
        self._fpk, self._fn, self._sq, self._sqn, self._lvl = fpk, fn, sq, sqn, lvl
        self._trim()
        return out

    def e(self, f):
        i = f - self.env0
        return self.env[i] if 0 <= i < len(self.env) else FLOOR_DB

    def _frame(self, out):
        f = self.nframes - 1
        if len(self.noise_hist) < 20:          # первые 0,2 с - слушаем фон, ударов не ищем
            return self._flush(f, out)
        n = self.noise_db
        v = self.e(f)
        if f - self.last_onset > 40 and v >= self.abs_min_db and v >= n + self.onset_db:
            before = max((self.e(g) for g in range(f - 20, f - 4)), default=FLOOR_DB)
            if v - before >= self.jump_db:
                self.last_onset = f
                self.pending.append((f, n))
        self._flush(f, out)

    def _flush(self, f, out):
        while self.pending and f >= self.pending[0][0] + POST_MS:
            k, noise = self.pending.pop(0)
            out.append(self.analyze(k, noise))

    def _trim(self):
        keep = 600                         # кадров (0,6 с)
        if len(self.env) > 2 * keep:
            cut = len(self.env) - keep
            del self.env[:cut]
            self.env0 += cut
        keep_s = keep * FR
        if len(self.raw) > 2 * keep_s:
            cut = len(self.raw) - keep_s
            del self.raw[:cut]
            self.raw0 += cut

    def analyze(self, k, noise):
        e = self.e
        p = max(range(k, k + 12), key=e)
        peak = e(p)
        j = p
        while j > k - 6 and e(j - 1) >= peak - 20:
            j -= 1
        rise = p - j
        decay = 110
        for m in range(p + 1, p + 111):
            if (e(m) + e(m + 1) + e(m + 2)) / 3 <= peak - 20:
                decay = m - p
                break
        pre = max((e(g) for g in range(k - PRE_MS, k - 4)), default=FLOOR_DB)
        post_vals = sorted(e(g) for g in range(p + 50, p + 111))
        post = post_vals[int(len(post_vals) * 0.9)] if post_vals else FLOOR_DB
        floor = max(-35.0, noise - peak)
        dec = [max(floor, e(p + d) - peak) for d in DEC_POINTS]
        s0 = k * FR - 2 * FR - self.raw0
        seg = self.raw[max(0, s0):max(0, s0) + FFT_N]
        bands, shape, centroid, low = spectrum_features(seg)
        return {"t": k / 1000.0, "peak": round(peak, 2), "noise": round(noise, 2), "snr": round(peak - noise, 2),
                "rise": rise, "decay": decay, "pre_gap": round(peak - pre, 2), "post_gap": round(peak - post, 2),
                "dec": [round(v, 2) for v in dec], "shape": [round(v, 2) for v in shape],
                "centroid": round(centroid, 1), "low": round(low, 2)}


# ---------------------------------------------------------------- шаг 2: шаблон и оценка
GATE_CAP = 20.0


def gates(c, strict=True):
    """Жёсткие запреты (не щелчок при любом шаблоне) -> причина или None.

    Признаки берём с запасом по умолчанию: у ОБРАЗЦА щелчка из шаблона часть признаков может не храниться
    (старый файл настроек, правка руками) - такой образец уже проходил запреты на калибровке."""
    if c.get("rise", 0) > 6:
        return "медленно нарастает"
    if c.get("decay", 0) > (90 if strict else 120):
        return "долгий звук"
    if c.get("pre_gap", 99.0) < (10 if strict else 8):
        return "звук до удара"
    if c.get("post_gap", 99.0) < (12 if strict else 9):
        return "звук после удара"
    if c.get("centroid", 2500.0) < 1000:
        return "низкий звук"
    if c.get("low", 0.0) > 6:
        return "низкий звук"
    return None


def rms_diff(a, b, w=None):
    if w is None:
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)) / max(1, len(a)))
    return math.sqrt(sum(k * (x - y) ** 2 for x, y, k in zip(a, b, w)) / max(1e-9, sum(w)))


def band_weights(shape):
    """Полосы, где у щелчка есть энергия, важнее (в тихих полосах - шум)."""
    top = max(shape)
    return [1.0 if v >= top - 20 else 0.4 for v in shape]


MAX_SAMPLES = 10        # столько образцов щелчка храним в шаблоне (больше - только медленнее, точнее не делает)


def sample_of(c):
    """Образец щелчка для шаблона: то, с чем потом сравниваем (форма, затухание, громкость) и чем считается
    сам шаблон, если образцы потом пересчитать (`relearn`)."""
    out = {"shape": [round(v, 2) for v in c["shape"]], "dec": [round(v, 2) for v in c["dec"]],
           "peak": round(c["peak"], 2), "snr": round(c.get("snr", 15.0), 2),
           "centroid": round(c.get("centroid", 2500.0), 1)}
    for k in ("rise", "decay", "pre_gap", "post_gap", "low"):     # запреты (gates) - чтобы образец можно было
        if k in c:                                                # оценить так же, как живой звук
            out[k] = round(c[k], 2)
    return out


def make_template(cands):
    """Шаблон из щелчков калибровки (3-7): среднее + САМИ ОБРАЗЦЫ. -> dict или None (мало).

    Щелчок пальцами не повторяется один в один, поэтому кроме среднего («отпечатка») храним каждый образец и
    при оценке берём ЛУЧШЕЕ совпадение (`total_distance`): у человека получается то звонкий, то глухой щелчок, и
    среднее по ним не похоже ни на один из них."""
    if len(cands) < 2:
        return None
    n = len(cands)
    shape = [sum(c["shape"][i] for c in cands) / n for i in range(len(cands[0]["shape"]))]
    dec = [sum(c["dec"][i] for c in cands) / n for i in range(len(DEC_POINTS))]
    spread = sum(rms_diff(c["shape"], shape, band_weights(shape)) for c in cands) / n
    snr = [c.get("snr", 15.0) for c in cands]
    cen = [c.get("centroid", 2500.0) for c in cands]
    return {"shape": [round(v, 2) for v in shape], "dec": [round(v, 2) for v in dec],
            "peak_min": round(min(c["peak"] for c in cands), 2), "snr_min": round(min(snr), 2),
            "peak_mean": round(sum(c["peak"] for c in cands) / n, 2), "peak_max": round(max(c["peak"] for c in cands), 2),
            "centroid": round(sum(cen) / n, 1), "spread": round(spread, 2), "n": n,
            "samples": [sample_of(c) for c in cands[-MAX_SAMPLES:]]}


def relearn(tpl, cands, keep=MAX_SAMPLES):
    """Дообучение по живым щелчкам: добавить их к образцам шаблона и пересчитать. -> (шаблон, отобранные образцы).

    Так настройка делается в НАСТОЯЩЕЙ обстановке (владелец 16.10.2026: кнопка «Это были мои щелчки - учесть»
    в режиме проверки), а не только в идеальной тишине при первом запуске."""
    old = [s for s in (tpl or {}).get("samples") or () if isinstance(s, dict) and "shape" in s]
    all_s = (old + [sample_of(c) for c in cands])[-keep:]
    kept, _ = pick_calib(all_s, need=3, keep_min=3)
    kept = kept or all_s
    return make_template(kept), kept


def pick_calib(cands, need=5, keep_min=4, limit=6.5):
    """Из собранных на настройке щелчков - те, что похожи друг на друга. -> (отобранные, выброшенные).

    На 5-7 щелчках всегда найдётся один «не такой» (стук по столу, щелчок другой рукой). Раньше это значило
    «начинаем всё заново» (владелец переснимал настройку), теперь один-два непохожих просто выбрасываются, пока
    остальных хватает (keep_min). Если непохожи почти все - возвращаем пусто, и окно просит переснять."""
    kept = list(cands)
    dropped = []
    while len(kept) >= 2:
        t = make_template(kept)
        w = band_weights(t["shape"])
        diffs = [rms_diff(c["shape"], t["shape"], w) for c in kept]
        worst = max(range(len(kept)), key=lambda i: diffs[i])
        if diffs[worst] <= limit:
            return kept, dropped
        if len(kept) - 1 < max(keep_min, min(need, 3)):
            return [], dropped + kept
        dropped.append(kept.pop(worst))
    return [], dropped + kept


def calib_consistent(cands):
    """Три щелчка калибровки похожи друг на друга? -> (ok, причина)."""
    if len(cands) < 3:
        return False, "мало щелчков"
    for c in cands:
        g = gates(c, strict=False)
        if g:
            return False, g
    t = make_template(cands)
    worst = max(rms_diff(c["shape"], t["shape"], band_weights(t["shape"])) for c in cands)
    if worst > 6.5:
        return False, "щелчки разные"
    if min(c["snr"] for c in cands) < 15:
        return False, "тихо"
    return True, ""


# Допуски сходства с шаблоном. SIG_* - насколько щелчки ОДНОГО человека на одном микрофоне отличаются от его
# шаблона (по каждой полосе спектра и точке затухания; разброс посчитан на реальных записях, eval/tune.py).
# Расстояние D = средний квадрат отклонений в этих долях (полосы с энергией щелчка важнее) + A_DEC * то же для
# затухания + штраф громкости. Оценка = 100·exp(-D / D_SCALE); порог оценки - по чувствительности.
SIG_BAND = [5.1, 5.2, 4.9, 4.3, 4.3, 4.4, 5.6, 6.2, 5.6, 4.7, 4.6, 4.7, 4.9, 6.3]
SIG_DEC = [5.5, 5.0, 5.8, 4.8, 2.4, 1.7]
A_DEC = 0.25
D_SCALE = 3.9                        # D = 2,0 -> оценка 60 (порог при чувствительности 5)
# Тише шаблона на LVL_LOW дБ / громче на LVL_HIGH - без штрафа. LVL_LOW поднят с 8 до 16 дБ 16.10.2026:
# настройка у человека снята ГРОМКИМИ щелчками, а в работе щелчок выходит вялым и тихим («из восьми раз
# подряд поднялся-спустился три раза… нужно быстрые щелчки делать, не вялые»). На записях CC0 (шаблон по трём
# громким щелчкам, eval/weak_snap.py) щелчок тише шаблона на 18 дБ узнавался в 33,5 % случаев, стал в 74,5 %,
# а ложных срабатываний на 30-минутной смеси это не добавило вовсе (24,24 против 23,91 в час с защитой).
LVL_LOW, LVL_HIGH, LVL_SIG = 16.0, 10.0, 4.0
THR_BASE, THR_STEP = 60.0, 5.0       # порог оценки при чувствительности 5 и шаг на деление
REL_DB = 12.0                        # «тишина вокруг»: мешают удары не тише щелчка на 12 дБ (эхо - тише)


SAMPLE_SIG = 1.41       # один образец от другого отличается в sqrt(2) раз сильнее, чем от среднего по ним
# Совпадение с ОДНИМ образцом слабее, чем со средним по всем: образцов несколько, и какой-нибудь из них всегда
# окажется ближе - в том числе к постороннему звуку. Поэтому к расстоянию до образца добавляется плата
# SAMPLE_PENALTY. Её размер подобран прогоном на тех же записях (eval/calib_n.py --grid): при 2,0 узнавание
# выше, чем у «среднего», а ложных срабатываний на 30-минутной смеси столько же - то есть поблажка бесплатная.
SAMPLE_PENALTY = 2.0


def _lvl_penalty(peak, ref, sens):
    low = LVL_LOW + 1.5 * (sens - 5)              # мягче - тише щелчки тоже свои
    d = peak - ref
    ex = (-d - low) if d < -low else (d - LVL_HIGH) if d > LVL_HIGH else 0.0
    return (ex / LVL_SIG) ** 2


DEC_FLOOR = -34.5        # ниже этого точка затухания - уже не звук, а шум комнаты: сравнивать её нечего
DEC_FLOOR_SKIP = True


def _dec_diff(a, b):
    """Расхождение профилей затухания. Точки, где ЛЮБОЙ из двух уже утонул в шуме, не сравниваем: у тихого
    («вялого») щелчка хвост тонет раньше, и сравнение шума с шумом зря портит оценку."""
    tot = n = 0.0
    for x, y, sg in zip(a, b, SIG_DEC):
        if DEC_FLOOR_SKIP and (x <= DEC_FLOOR or y <= DEC_FLOOR):
            continue
        tot += ((x - y) / sg) ** 2
        n += 1
    if n < 2:                      # сравнивать почти нечего - считаем как раньше, по всем точкам
        return sum(((x - y) / sg) ** 2 for x, y, sg in zip(a, b, SIG_DEC)) / len(SIG_DEC)
    return tot / n


def distance(c, tpl, sens=5):
    """-> (D спектра, D затухания, штраф громкости) до СРЕДНЕГО шаблона - для оценки и для подбора допусков."""
    w = band_weights(tpl["shape"])
    ds = sum(k * ((x - y) / sg) ** 2 for x, y, k, sg in zip(c["shape"], tpl["shape"], w, SIG_BAND)) / sum(w)
    dd = _dec_diff(c["dec"], tpl["dec"])
    return ds, dd, _lvl_penalty(c["peak"], tpl.get("peak_mean", tpl["peak_min"]), sens)


def sample_distance(c, smp, tpl, sens=5):
    """Расстояние до ОДНОГО образца щелчка. Допуски шире в SAMPLE_SIG раз: разброс между двумя живыми щелчками
    больше, чем между щелчком и средним по нескольким."""
    w = band_weights(tpl["shape"])
    sg = [v * SAMPLE_SIG for v in SIG_BAND]
    ds = sum(k * ((x - y) / g) ** 2 for x, y, k, g in zip(c["shape"], smp["shape"], w, sg)) / sum(w)
    dd = _dec_diff(c["dec"], smp["dec"]) / (SAMPLE_SIG ** 2)
    lv = _lvl_penalty(c["peak"], smp.get("peak", tpl.get("peak_mean", tpl["peak_min"])), sens)
    return ds + A_DEC * dd + lv + SAMPLE_PENALTY, lv


def total_distance(c, tpl, sens=5):
    """-> (D, штраф громкости) по ЛУЧШЕМУ из совпадений: среднее шаблона и каждый образец отдельно."""
    ds, dd, lv = distance(c, tpl, sens)
    best, best_lv = ds + A_DEC * dd + lv, lv
    for smp in tpl.get("samples") or ():
        try:
            d, l = sample_distance(c, smp, tpl, sens)
        except (KeyError, TypeError, ValueError):
            continue
        if d < best:
            best, best_lv = d, l
    return best, best_lv


def score(c, tpl, sens=5, thr=None):
    """Оценка звука 0-100 и причина отказа ('' - похож).

    thr - порог оценки «это щелчок» (его человек двигает в окне: «щелчок принимается от 45 из 100»). Если не
    задан, берётся из чувствительности 1-10, как было. Допуск по громкости идёт от того же порога
    (`sens_of_thr`) - одна ручка вместо двух."""
    reason = gates(c) or ""
    if tpl is None:
        return 0.0, "нужна настройка"
    t = threshold(sens) if thr is None else max(0.0, min(100.0, float(thr)))
    sv = sens if thr is None else sens_of_thr(t)
    d, lv = total_distance(c, tpl, sv)
    s = 100.0 * math.exp(-d / D_SCALE)
    if not reason and lv > 1.0 and c["peak"] < tpl.get("peak_mean", tpl["peak_min"]):
        reason = "тише щелчка"
    if reason and reason != "тише щелчка":
        s = min(s, GATE_CAP)
    if not reason and s < t:
        reason = "не похоже на щелчок"
    return round(s, 1), reason


# Порог оценки «это щелчок» человек двигает сам (владелец 16.10.2026: «давай порог поставим не 45, а 40, и вот
# уже будет 4 срабатывания лучше; давай этот порог можно будет регулировать - мало ли, ребёнок какой захочет, у
# него щелчок не такой сильный»). Шаг - 1 очко, а не 5, как было у чувствительности.
THR_MIN, THR_MAX = 25.0, 75.0
THR_SAFE = 35.0                      # ниже этого в окне честно написано, что пойдут посторонние звуки
THR_DEFAULT = 45.0                   # то же, что было у чувствительности 8 (её поставил себе владелец)


def threshold(sens):
    """Порог оценки для чувствительности 1-10 (5 - по умолчанию)."""
    sens = max(1, min(10, int(sens)))
    return max(5.0, min(95.0, THR_BASE - THR_STEP * (sens - 5)))


def sens_of_thr(thr):
    """Порог оценки -> та же «чувствительность» 1-10 (для допуска по громкости). Обратна threshold()."""
    return max(1.0, min(10.0, 5.0 + (THR_BASE - float(thr)) / THR_STEP))


# Когда окна свёрнуты, ошибиться не страшно (окна просто вернутся) - слушаем мягче. Каждая поблажка взвешена
# прогоном на тех же записях (eval/grid_back.py: сколько возвратов узнано против ложных возвратов на 30-минутной
# смеси). Взято то, что даёт много узнавания за мало ложных: «свои щелчки не глушат следующие» + почти-щелчок
# вторым в паре + тишины до серии 0,25 с вместо 0,5 + промежуток до 1 с. Поблажку по самому порогу (+1, +2 к
# чувствительности) НЕ берём: она прибавляла 1-3 ложных возврата за те же 1-3 % узнавания.
RESTORE_SENS_BONUS = 0       # к чувствительности на возврат (мягкость даёт MAYBE_GAP, а не сдвиг порога)
MAYBE_GAP = 12.0             # «почти щелчок»: оценка ниже порога не больше чем на столько


def sens_for(sens, hidden=False):
    """Чувствительность для текущего состояния: окна свёрнуты - мягче (возврат важнее ложного возврата)."""
    return max(1, min(10, int(sens) + (RESTORE_SENS_BONUS if hidden else 0)))


SNAP, MAYBE, NOISE = "snap", "maybe", "noise"


def judge(c, tpl, sens=5, hidden=False, guard_reason=None, thr=None):
    """Полный вердикт по одному звуку - для решения, для журнала и для окна «Что происходило».

    -> {"score", "thr", "ok", "kind", "reason"}:
      kind SNAP  - щелчок (считается в серию);
      kind MAYBE - почти щелчок (шум вокруг им не считается; при свёрнутых окнах годится вторым в пару);
      kind NOISE - посторонний звук (он и мешает «тишине вокруг»).
    guard_reason - запрет извне (клавиша/мышь этого компьютера, звук из колонок): оценку не портим, чтобы в окне
    и в журнале была видна настоящая похожесть, а не 20 из 100."""
    sv = sens_for(sens, hidden)
    thr = threshold(sv) if thr is None else max(0.0, min(100.0, float(thr)))
    s, reason = score(c, tpl, sv, thr=thr)
    if not reason and guard_reason:
        reason = guard_reason                 # сам звук похож на щелчок, запретило окружение
    kind = NOISE
    if not reason:
        kind = SNAP
    elif tpl is not None and not gates(c) and s >= thr - MAYBE_GAP:
        kind = MAYBE
    return {"score": s, "thr": thr, "ok": not reason, "kind": kind, "reason": reason}


# ---------------------------------------------------------------- шаг 3: решение
RESTORE_N = 2                        # вернуть окна - ДВА щелчка подряд (выбор, с 16.10.2026 не по умолчанию)
# ГЛАВНОЕ ПОВЕДЕНИЕ с 16.10.2026 (владелец: «щёлкнул один раз - свернулось, щёлкнул второй раз - развернулось…
# щёлк, щёлк, щёлк - он летает и не должен даже тормозить»): ОДИН щелчок - переключатель. Для этого решение
# должно приниматься быстро, а щелчки, идущие подряд каждые 0,3-0,5 с, не должны мешать друг другу:
#   - пауза после срабатывания - только чтобы один удар не сосчитался дважды (FAST_COOLDOWN);
#   - «тишина вокруг» короче и считает помехой ТОЛЬКО посторонний звук (свои щелчки - не помеха);
#   - запрета «не сворачивать после возврата» нет вовсе: переключатель симметричен, лишний щелчок просто
#     вернёт как было.
FAST_COOLDOWN = 0.35                 # столько после САМОГО щелчка: ближе - это его эхо в комнате, а не второй
FAST_ISO = (0.25, 0.12)              # тишина до серии / после щелчка, с - решение через 0,25 с после удара
# «Окна свернулись сами» - дорогая ошибка, «окна сами вернулись» - дешёвая (следующий щелчок всё исправит).
# Поэтому на СВОРАЧИВАНИЕ в режиме переключателя тишина вокруг проверяется строже и считает помехой любой
# заметный удар, включая похожий на щелчок: иначе серия клавиш сворачивает окна сама (прогон eval/fast_toggle.py:
# 39 -> 12 ложных в час на 30-минутной смеси сплошного шума). Человеку это не мешает: он щёлкает раз в 0,4-0,5 с.
FAST_ISO_HIDE = (0.35, 0.12)
SERIES_SPAN = 1.5                    # вся серия - не длиннее этого (с); по записям щелчков, eval/series.py
# Допуски на ВОЗВРАТ (окна уже свёрнуты): тишины вокруг нужно меньше, промежуток шире, серия длиннее.
BACK_ISO = (0.25, 0.3)               # тишина до серии / после последнего щелчка, с
# Промежуток между соседними щелчками серии возврата. До 16.10.2026 было до 1,0 с - и пара с промежутком
# больше секунды НЕ СОБИРАЛАСЬ ВООБЩЕ (владелец: «двойные щелчки я поставил, по-моему, они не работают»;
# в его журнале 17 строк «не дождался второго щелчка»). По записям CC0 90 % промежутков укладываются в 1,37 с,
# поэтому окно 1,4 с: пары с промежутком 1,1-1,3 с узнаются (было 0 %, стало 80,5 %), цена - случайных
# возвратов на 30-минутной записи сплошного шума 10,52 -> 12,54 в час (eval/fast_toggle.py --pairs).
BACK_GAP = (0.12, 1.4)               # промежуток между соседними щелчками, с
BACK_SPAN = 3.0                      # вся серия, с (три щелчка по 1,4 с умещаются)
NO_HIDE_AFTER_RESTORE = 3.5          # вернули окна - столько секунд лишние щелчки их не сворачивают обратно
# (в журнале владельца 16.10.2026 возврат 20:21:28, а через 3 с окна свернулись снова - это были его же щелчки,
# которыми он добивался возврата)
# Но владелец хочет щёлкать ПОДРЯД: «щёлк - свернул, щёлк-щёлк - развернул, щёлк - свернул» (16.10.2026), и
# глухие 3,5 с ему мешают. Поэтому запрет держится, только пока щелчки идут один за другим (это эхо того же
# жеста): в журнале владельца его лишние щелчки после возврата шли с промежутком около секунды. Тишина
# NO_HIDE_QUIET - жест закончился, следующий щелчок сворачивает сразу (но не раньше паузы cooldown).
NO_HIDE_QUIET = 1.5


class Clicker:
    """Кандидаты с оценками -> срабатывания «свернуть» (hide) и «вернуть» (restore).

    Окна на месте - СВЕРНУТЬ:
      mode 1: одиночный щелчок; срабатывает, если за 0,5 с до и 0,3 с после нет других ударов не тише щелчка на
              REL_DB (серия клавиш, музыка, речь, хлопки в ладоши подряд отсекаются; эхо комнаты - нет);
      mode 2/3: 2 или 3 щелчка, промежутки 0,15-0,8 с, после последнего 0,3 с тишины.
    Окна свёрнуты нами (hidden=True) - ВЕРНУТЬ:
      серия из RESTORE_N (двух) щелчков; одиночный щелчок по умолчанию НЕ возвращает (случайный шум не вернёт окна,
      пока начальник рядом), галочка single_restores - возвращает и одиночный.
    Серия: промежутки между соседними щелчками gap, вся серия не длиннее span. Щелчков подряд больше, чем нужно
    (человек щёлкает ещё раз, когда не вышло) - серия не отменяется: считаются ПОСЛЕДНИЕ нужные щелчки.
    После срабатывания - пауза cooldown (1,5 с), удары в ней не считаются.
    """

    def __init__(self, mode=1, cooldown=1.5, iso_before=0.5, iso_after=0.3, gap=(0.15, 0.8), span=SERIES_SPAN,
                 restore_n=RESTORE_N, hidden=False, single_restores=False, back_iso=BACK_ISO, back_gap=BACK_GAP,
                 back_span=BACK_SPAN, no_hide_after_restore=NO_HIDE_AFTER_RESTORE, no_hide_quiet=NO_HIDE_QUIET):
        self.mode, self.cooldown, self.iso_before, self.iso_after, self.gap = mode, cooldown, iso_before, iso_after, gap
        self.span = span
        self.restore_n = 1 if single_restores else max(1, min(3, int(restore_n)))
        self.back_iso, self.back_gap, self.back_span = back_iso, back_gap, back_span
        self.no_hide_after_restore = no_hide_after_restore
        self.no_hide_quiet = no_hide_quiet
        self.hidden = hidden                  # окна свёрнуты нами - следующая серия возвращает
        self.reset()

    # Сколько щелчков возвращают окна - настройка человека (владелец 16.10.2026): один (по умолчанию - быстро),
    # два или три подряд (страховка: случайный стук не вернёт окна, пока человек отошёл).
    @property
    def single_restores(self):
        """Прежнее имя той же настройки: возврат одним щелчком."""
        return self.restore_n == 1

    @single_restores.setter
    def single_restores(self, on):
        if on:
            self.restore_n = 1
        elif self.restore_n == 1:
            self.restore_n = RESTORE_N

    def reset(self):
        self.hits = []              # [(t, пик, kind)] - приняты щелчки, ждут решения
        self.recent = deque(maxlen=64)   # [(t, пик, kind)] - заметные удары за последнее время
        self.block_until = -10.0
        self.no_hide_until = -10.0
        self.echo_t = -10.0         # когда в последний раз звучал щелчок «того же жеста» (эхо после возврата)
        self.decide_at = None
        self.miss = None            # что не сложилось (для журнала): ("timeout"|"noise_after"|"half", время)

    def drop_pending(self):
        """В звуке был разрыв (микрофон переподключился): недосчитанную серию и удары вокруг забываем, а паузу
        после срабатывания (block_until) - нет, она в том же времени потока."""
        self.hits = []
        self.recent.clear()
        self.decide_at = None

    def hold_hide(self, now, seconds=None):
        """Окна только что вернули (щелчками, клавишей, значком у часов) - столько секунд не сворачиваем их
        обратно: это лишние щелчки того же жеста (журнал владельца 16.10.2026). В режиме переключателя запрета
        нет - там лишний щелчок просто вернёт окна как было, и это понятно человеку."""
        if self.toggle and seconds is None:
            return
        self.no_hide_until = now + (self.no_hide_after_restore if seconds is None else seconds)
        self.echo_t = now

    def take_miss(self):
        """Забрать и обнулить «что не сложилось» - программа пишет это в журнал."""
        m, self.miss = self.miss, None
        return m

    @property
    def toggle(self):
        """Один щелчок - переключатель (свернул / вернул). Главное поведение с 16.10.2026."""
        return self.restore_n == 1 and self.mode == 1

    @property
    def cd(self):
        """Пауза после срабатывания: в режиме переключателя - только чтобы один удар не сработал дважды."""
        return FAST_COOLDOWN if self.toggle else self.cooldown

    def targets(self):
        """-> (сколько щелчков срабатывает, что делаем) для текущего состояния окон."""
        if self.toggle:
            return {1}, "restore" if self.hidden else "hide"
        if self.hidden:
            return {self.restore_n}, "restore"
        return {self.mode}, "hide"

    @property
    def iso(self):
        """«Тишина вокруг» (до серии, после последнего щелчка) для текущего состояния окон."""
        if self.toggle:
            return FAST_ISO if self.hidden else FAST_ISO_HIDE
        return self.back_iso if self.hidden else (self.iso_before, self.iso_after)

    @property
    def gaps(self):
        return self.back_gap if self.hidden else self.gap

    @property
    def series_span(self):
        return self.back_span if self.hidden else self.span

    def _loud_between(self, a, b, peak):
        """Посторонний шум в промежутке. Когда окна СВЁРНУТЫ, свои щелчки и почти-щелчки шумом не считаются:
        иначе щелчки подряд глушат друг друга - один неузнанный щелчок глушил все следующие (баг 16.10.2026), а
        при быстрых «щёлк, щёлк, щёлк» не срабатывал бы ни один после первого (владелец 16.10.2026). Когда окна
        на месте, помехой считается любой заметный удар: свернуть окна по ошибке дороже, чем вернуть."""
        own_ok = self.hidden
        for t, p, kind in self.recent:
            if a < t <= b and p >= peak - REL_DB and (kind == NOISE or not own_ok):
                return True
        return False

    def push(self, t, ok, peak=0.0, kind=None):
        """Удар во время t. ok - похож на щелчок; peak - пик, дБ (None - тихий, «тишине» не мешает);
        kind - SNAP / MAYBE / NOISE (по умолчанию из ok). -> короткий код, что с этим звуком сделали:
        "cooldown" (идёт пауза после срабатывания), "just_restored" (только что вернули окна), "noise",
        "maybe" (почти щелчок - в серию не берём), "noise_before" (перед щелчком был посторонний звук),
        "started" (первый щелчок серии - жду следующий), "series" (серия собрана, решение через миг)."""
        kind = kind or (SNAP if ok else NOISE)
        if peak is not None:
            self.recent.append((t, peak, kind))
        # жест ещё идёт? щелчки после возврата сыплются один за другим (эхо) - это видно и в те 1,5 с паузы,
        # когда решение не принимается, поэтому считаем эхо ДО выхода по паузе
        echo = (kind in (SNAP, MAYBE) and t < self.no_hide_until
                and t - self.echo_t <= self.no_hide_quiet)
        if echo:
            self.echo_t = t
        if t < self.block_until:
            return "cooldown"
        if kind == NOISE:
            return "noise"          # отмену собранной серии решает poll() по self.recent
        need, action = self.targets()
        if kind != SNAP and max(need) == 1:
            # сработать может только уверенный щелчок: почти-щелчок в одиночку ничего не даёт и серию не ждёт
            # (иначе в журнале появлялось «не сработало: не дождался второго щелчка», хотя второго и не нужно)
            return "maybe"
        if action == "hide":
            if kind != SNAP:
                return "maybe"      # сворачивание не меняем: только уверенные щелчки (цифры 1.1.0 сохраняются)
            if t < self.no_hide_until:
                if echo:
                    return "just_restored"   # щелчки идут подряд - это тот же жест, окна не прячем
                self.no_hide_until = -10.0   # была тишина - человек щёлкнул ЗАНОВО, сворачиваем
        peak = 0.0 if peak is None else peak
        nmax = max(need)
        gap, span = self.gaps, self.series_span
        if self.hits:
            d = t - self.hits[-1][0]
            if d < gap[0] or d > gap[1] or \
                    self._loud_between(self.hits[-1][0], t - 1e-6, self.hits[-1][1]):
                self.hits = []                    # серия прервалась - этот щелчок начинает новую
                self.decide_at = None
            else:
                # щёлкают дальше: держим последние nmax щелчков (серия из 4-5 щелчков - тоже серия, а не отмена)
                self.hits = self.hits[-(nmax - 1):] if nmax > 1 else []
                while self.hits and t - self.hits[0][0] > span:
                    self.hits.pop(0)
        if not self.hits and self._loud_between(t - self.iso[0], t - 1e-6, peak):
            self.decide_at = None
            return "noise_before"   # перед первым щелчком серии был посторонний звук - не наш жест
        self.hits.append((t, peak, kind))
        if len(self.hits) in need and any(k == SNAP for *_, k in self.hits):
            # решение - когда разобраны все удары в окне «тишина после» (каждый удар разбирается POST_MS).
            # На ВОЗВРАТЕ решение не отодвигаем: срабатываем по первой собранной паре, иначе пока человек
            # щёлкает дальше, возврат ждёт, когда он перестанет. Сворачивание не трогаем (цифры 1.1.0).
            at = t + self.iso[1] + POST_MS / 1000.0
            self.decide_at = at if self.decide_at is None or not self.hidden else min(self.decide_at, at)
            return "series"
        return "started"

    def poll(self, now):
        """Пора сработать? now - текущее время потока (с). -> "hide" / "restore" / None."""
        if self.decide_at is not None and now >= self.decide_at:
            t, p, _ = self.hits[-1] if self.hits else (now, 0.0, NOISE)
            need, action = self.targets()
            fire = len(self.hits) in need and any(k == SNAP for *_, k in self.hits)
            self.decide_at = None
            self.hits = []
            if not fire:
                self.miss = ("half", now)
                return None
            if self._loud_between(t + 1e-6, t + self.iso[1] + 0.05, p):
                self.miss = ("noise_after", now)
                return None
            # в режиме переключателя пауза считается от САМОГО щелчка, а не от решения: человек
            # щёлкает каждые 0,4-0,5 с, и каждый щелчок обязан сработать
            self.block_until = (t if self.toggle else now) + self.cd
            if action == "restore" and not self.toggle:
                # в режиме переключателя запрета нет: лишний щелчок просто вернёт окна как было
                self.no_hide_until = now + self.no_hide_after_restore
                self.echo_t = t                  # эхо жеста считаем от ПОСЛЕДНЕГО щелчка серии
            return action
        if self.hits and self.decide_at is None and now - self.hits[-1][0] > self.gaps[1] + POST_MS / 1000.0:
            self.hits = []
            if max(self.targets()[0]) > 1:        # ждать второго щелчка имеет смысл, только если он нужен
                self.miss = ("timeout", now)
        return None


def simulate(cands, tpl, sens=5, mode=1, cooldown=1.5, guard=None, end=None, hidden=False, single_restores=False,
             thr=None, restore_n=RESTORE_N):
    """То же решение, что Detector, по готовому списку кандидатов (проверка на длинных записях: шаг 1 - один раз,
    шаблонов - много). -> (времена срабатываний, события). hidden=True - окна свёрнуты (серия возвращает)."""
    ck = Clicker(mode=mode, cooldown=cooldown, hidden=hidden, single_restores=single_restores,
                 restore_n=restore_n)
    fired, events = [], []
    for c in cands:
        now = c["t"] + POST_MS / 1000.0
        if ck.decide_at is not None and ck.decide_at <= now:
            at = ck.decide_at
            if ck.poll(at):
                fired.append(at)
        ck.poll(now)
        v = judge(c, tpl, sens, hidden=hidden, guard_reason=guard(c["t"]) if guard is not None else None, thr=thr)
        ck.push(c["t"], v["ok"], loud_peak(c), v["kind"])
        events.append({"t": c["t"], "score": v["score"], "reason": v["reason"], "kind": v["kind"]})
    if ck.decide_at is not None:
        at = ck.decide_at
        if ck.poll(at):
            fired.append(at)
    return fired, events


def series_window(gap=BACK_GAP, span=BACK_SPAN, n=RESTORE_N):
    """Окно серии из n щелчков: (минимум, максимум) секунд от первого до последнего - для текстов и README."""
    return round((n - 1) * gap[0], 2), round(min(span, (n - 1) * gap[1]), 2)


def loud_peak(c):
    """Пик удара для «тишины вокруг» или None, если удар еле слышен (на 12 дБ выше фона и меньше)."""
    return c["peak"] if c["snr"] >= 12 else None


class Detector:
    """Всё вместе для потока: feed(samples) -> список событий {"t", "score", "thr", "reason", "kind", "verdict",
    "cand"} и срабатывания [(время, действие)], где действие - "hide" (свернуть) или "restore" (вернуть).

    guard(t) -> причина или None - внешние запреты (клавиатура/мышь этого компьютера, звук из динамиков)."""

    def __init__(self, template=None, sens=5, mode=1, cooldown=1.5, guard=None, thr=None):
        self.front = Frontend()
        self.template = template
        self.sens = sens
        self.thr = THR_DEFAULT if thr is None else float(thr)
        self.clicker = Clicker(mode=mode, cooldown=cooldown)
        self.guard = guard

    def set_mode(self, mode):
        self.clicker.mode = mode
        self.clicker.reset()

    def set_windows(self, hidden, back_n=None):
        """Состояние окон из программы: свёрнуты нами или нет (от этого зависит, что делает серия щелчков), и
        сколько щелчков возвращают окна (1 - по умолчанию, 2 или 3 - страховка)."""
        self.clicker.hidden = bool(hidden)
        if back_n is None:
            return
        if isinstance(back_n, bool):          # прежний вызов: признак «возвращает одиночный щелчок»
            self.clicker.single_restores = back_n
        else:
            self.clicker.restore_n = max(1, min(3, int(back_n)))

    def feed(self, samples, scale=1 / 32768.0):
        events, fired = [], []
        hidden = self.clicker.hidden
        need, _ = self.clicker.targets()
        for c in self.front.feed(samples, scale):
            g = self.guard(c["t"]) if self.guard is not None else None
            ev = judge(c, self.template, self.sens, hidden=hidden, guard_reason=g, thr=self.thr)
            # сколько щелчков нужно СЕЙЧАС - в самом событии: пока строка дойдёт до журнала, окна могут уже
            # вернуться, и «жду второй щелчок» превратилось бы в непонятное «жду»
            ev["need"], ev["gap_max"] = max(need), self.clicker.gaps[1]
            ev["verdict"] = self.clicker.push(c["t"], ev["ok"], loud_peak(c), ev["kind"])
            ev["t"] = c["t"]
            ev["cand"] = c
            ev["hidden"] = hidden
            events.append(ev)
        action = self.clicker.poll(self.front.t)
        if action:
            fired.append((self.front.t, action))
        return events, fired
