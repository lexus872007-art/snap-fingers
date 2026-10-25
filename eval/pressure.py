#!/usr/bin/env python3
"""Что происходит, когда владелец щёлкает МНОГО РАЗ ПОДРЯД (окна свёрнуты, он хочет их вернуть) и при этом
работает за ноутбуком - печатает и водит мышью. Жалоба владельца 16.10.2026: «он на третий раз перестал
работать», журнал с ноутбука: один возврат занял 37 с, потом не сработал совсем.

    ../venv/bin/python eval/pressure.py ~/shchelchok_build/data [--sens 5] [--out eval/out] [--rebuild]

Те же записи CC0 и те же 41 шаблон, что в остальной таблице README (eval/out/cache.pkl).

Что считаем:
1. «Щёлкает подряд»: 8 щелчков человека с промежутками 0,35-0,70 с (так щёлкает тот, у кого не вышло с первого
   раза) на фоне A (тихо) и B (офис). Хорошо - окна вернулись с первой пары, то есть в первые ~1,2 с.
   Считаем: доля потоков, где возврат случился вообще; через сколько секунд после ПЕРВОГО щелчка (медиана, 90 %).
2. То же, но владелец печатает: защита «не реагировать, пока печатаю» (при свёрнутых окнах окно узкое,
   -0,10 / +0,06 с от нажатия клавиши; в 1.1.0 оно было -0,3 / +0,2 с - `--typing 0.3,0.2`).
   Печать - 3 клавиши в секунду сплошь («пишу письмо») и вспышками по 2 с через 2 с («работаю с мышью»).
3. Сколько времени защита вообще оставляет программе: доля секунд, когда щелчок был бы отвергнут.
4. Ложные возвраты на ТОЙ ЖЕ 30-минутной смеси (речь/клавиатура/музыка/хлопки/стук/мышь/прочее).
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eval import evaluate as E  # noqa: E402
from shchelchok import detector as D  # noqa: E402

N_SNAPS = 8                 # столько раз подряд щёлкает человек, которому нужно вернуть окна
GAP = (0.35, 0.70)          # промежутки между его щелчками (по записям: медиана 0,45 с)
FIRST = 1.5                 # первый щелчок в потоке, с
TYPE_RATE = 3.0             # клавиш в секунду, когда печатает


def typing_times(dur, mode, rng):
    """Моменты нажатий клавиш/мыши на ЭТОМ компьютере (их видит InputWatch)."""
    if mode == "none":
        return []
    out, t = [], 0.0
    while t < dur:
        if mode == "solid":
            t += rng.exponential(1.0 / TYPE_RATE)
            out.append(t)
        else:                                  # вспышками: 2 с печатает, 2 с не печатает
            if (int(t) // 2) % 2 == 0:
                t += rng.exponential(1.0 / TYPE_RATE)
                out.append(t)
            else:
                t += 0.05
    return [t for t in out if t < dur]


def typing_guard(times, before=0.1, after=0.06):
    """Защита «клавиатура или мышь этого компьютера» - как winapi.InputWatch.near."""
    arr = np.array(times) if len(times) else np.zeros(0)

    def g(t):
        if len(arr) and np.any((t - before <= arr) & (arr <= t + after)):
            return "клавиатура или мышь"
        return None
    return g


def deaf_share(times, dur, before=0.3, after=0.2):
    """Доля времени, когда защита отвергает любой щелчок (объединение окон вокруг нажатий)."""
    if not times:
        return 0.0
    iv = sorted((max(0.0, t - before), min(dur, t + after)) for t in times)
    tot, cur_a, cur_b = 0.0, iv[0][0], iv[0][1]
    for a, b in iv[1:]:
        if a <= cur_b:
            cur_b = max(cur_b, b)
        else:
            tot += cur_b - cur_a
            cur_a, cur_b = a, b
    tot += cur_b - cur_a
    return tot / dur


def build(data, groups, rng):
    """Потоки «щёлкает 8 раз подряд» для каждого шаблона, фон A и B."""
    wav = os.path.join(data, "wav")
    classes = {c: [os.path.join(wav, c, f) for f in sorted(os.listdir(os.path.join(wav, c)))]
               for c in os.listdir(wav)}
    beds = E.beds_of(data, classes)
    streams = {}
    for name, tpl in groups:
        path = os.path.join(wav, "snap", name + ".wav")
        if not os.path.exists(path):
            continue
        clips = E.snap_events(path)
        test = clips[3:]                                   # первые 3 - калибровка, как везде
        if len(test) < 2:
            continue
        ref = tpl.get("peak_mean", tpl["peak_min"])
        streams[name] = {}
        for cond in ("A", "B"):
            dur = FIRST + N_SNAPS * GAP[1] + 3
            bed = (E.bed_from(beds["quiet"], dur, -55, rng) if cond == "A"
                   else E.bed_from(beds["office"], dur, -42, rng))
            t, times = FIRST, []
            for k in range(N_SNAPS):
                cl = test[k % len(test)]
                E.place_clip(bed, cl, t, ref + rng.uniform(-4, 2), cl[2])
                times.append(t)
                t += rng.uniform(*GAP)
            streams[name][cond] = (E.cands_of(bed), times, dur)
        print("подряд", name, flush=True)
    return streams


def score(streams, groups, sens, mode, rng, tw=(0.1, 0.06)):
    """-> (доля потоков с возвратом, задержки от первого щелчка, доля «глухого» времени)."""
    got, delays, deaf = [0, 0], [], []
    for name, tpl in groups:
        for cond, (cs, times, dur) in streams.get(name, {}).items():
            ks = typing_times(dur, mode, rng)
            deaf.append(deaf_share(ks, dur, *tw))
            fired, _ = D.simulate(cs, tpl, sens=sens, hidden=True, guard=typing_guard(ks, *tw) if ks else None)
            got[1] += 1
            if fired:
                got[0] += 1
                delays.append(fired[0] - times[0])
    return got, delays, deaf


def row(label, got, delays, deaf):
    d = np.array(delays) if delays else np.zeros(0)
    return {"что": label, "вернулось, % потоков": round(100 * got[0] / max(1, got[1]), 1),
            "потоков": got[1],
            "задержка медиана, с": round(float(np.median(d)), 2) if len(d) else None,
            "задержка 90 %, с": round(float(np.percentile(d, 90)), 2) if len(d) else None,
            "задержка макс, с": round(float(d.max()), 2) if len(d) else None,
            "глухо от защиты, % времени": round(100 * float(np.mean(deaf)), 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--sens", type=int, default=5)
    ap.add_argument("--out", default=os.path.join(ROOT, "eval", "out"))
    ap.add_argument("--seed", type=int, default=23)
    ap.add_argument("--tag", default="now")
    ap.add_argument("--typing", default="0.1,0.06", help="окно защиты «печатаю» (1.1.0 было 0.3,0.2)")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    tw = tuple(float(v) for v in a.typing.split(","))
    st = pickle.load(open(os.path.join(a.out, "cache.pkl"), "rb"))
    groups = [(g["name"], g["tpl"]) for g in st["pos"] if g["tpl"]]
    mix = st["mix"]
    cache = os.path.join(a.out, "pressure_cache.pkl")
    if a.rebuild or not os.path.exists(cache):
        pickle.dump(build(a.data, groups, np.random.default_rng(a.seed)), open(cache, "wb"))
    streams = pickle.load(open(cache, "rb"))
    rows = []
    for label, mode in (("щёлкает подряд, не печатает", "none"),
                        ("щёлкает подряд, печатает вспышками", "bursts"),
                        ("щёлкает подряд, печатает сплошь", "solid")):
        got, delays, deaf = score(streams, groups, a.sens, mode, np.random.default_rng(a.seed + 1), tw)
        rows.append(row(label, got, delays, deaf))
        print(rows[-1], flush=True)
    # ложные возвраты на 30-минутной смеси (та же, что в README)
    fa = [len(D.simulate(mix, tpl, sens=a.sens, hidden=True)[0]) for _, tpl in groups]
    one = [len(D.simulate(mix, tpl, sens=a.sens, hidden=True, single_restores=True)[0]) for _, tpl in groups]
    out = {"tag": a.tag, "sens": a.sens, "snaps_in_row": N_SNAPS, "gap": GAP, "templates": len(groups),
           "typing_window": tw, "rows": rows, "false_restores_30min": {"среднее": round(float(np.mean(fa)), 2), "макс": int(max(fa))},
           "false_restores_30min_single_on": {"среднее": round(float(np.mean(one)), 2), "макс": int(max(one))},
           "restore_n": D.RESTORE_N}
    p = os.path.join(a.out, f"pressure_{a.tag}.json")
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=1, default=str)
    print("ложные возвраты на 30 мин:", out["false_restores_30min"], "с галочкой:",
          out["false_restores_30min_single_on"])
    print("записано", p)


if __name__ == "__main__":
    main()
