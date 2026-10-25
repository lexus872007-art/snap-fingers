#!/usr/bin/env python3
"""Главное поведение 1.3.0: ОДИН щелчок - переключатель, и щёлкать можно подряд («щёлк, щёлк, щёлк - свернул,
развернул, свернул, развернул», владелец 16.10.2026). Цена - ложные срабатывания. Сервер 2.

    ../venv/bin/python eval/fast_toggle.py [--gap 0.45] [--thr 45,40]

Те же записи CC0 и та же 30-минутная смесь (eval/out/cache.pkl). Считаем:
1. БЫСТРЫЕ ЩЕЛЧКИ: щелчки человека подряд через --gap секунд - на сколько из них программа ответила
   (переключила окна) и сколько ответов было ЛИШНИХ (один щелчок сработал дважды - этого быть не должно).
2. ЛОЖНЫЕ СРАБАТЫВАНИЯ в час на 30-минутной смеси (речь, клавиатура, музыка, хлопки, стук, мышь, прочее):
   в режиме переключателя любое ложное срабатывание - это либо «окна свернулись сами», либо «окна всплыли
   сами», поэтому считаем их вместе. Отдельно - с защитой «клавиатура и мышь ЭТОГО компьютера».
3. Для сравнения - прежнее поведение (свернуть одним щелчком, вернуть двумя подряд) на тех же записях.
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
from eval.calib_n import CAL_MAX, CAL_NEED, calib_set, snap_cands  # noqa: E402
from eval.fa_back import own_keys_guard  # noqa: E402
from shchelchok import detector as D  # noqa: E402

SR = 16000


def run_stream(cands, tpl, thr, toggle, guard=None, hidden=False, back_n=None):
    """Поток ударов -> времена срабатываний и что это было. toggle=True - один щелчок переключает;
    back_n - сколько щелчков возвращают окна (1 / 2 / 3), настройка человека."""
    n = (1 if toggle else D.RESTORE_N) if back_n is None else int(back_n)
    # допуски берём из модуля ЯВНО: значения по умолчанию в Clicker привязаны на момент импорта, и подмена
    # D.BACK_GAP без этого ничего бы не меняла (на эту грабельку я наступил 16.10.2026)
    ck = D.Clicker(mode=1, hidden=hidden, restore_n=n, back_iso=D.BACK_ISO, back_gap=D.BACK_GAP,
                   back_span=D.BACK_SPAN)
    fired = []
    for c in cands:
        now = c["t"] + D.POST_MS / 1000.0
        if ck.decide_at is not None and ck.decide_at <= now:
            at = ck.decide_at
            a = ck.poll(at)
            if a:
                fired.append((at, a))
                ck.hidden = not ck.hidden            # переключатель: состояние окон поменялось
        ck.poll(now)
        v = D.judge(c, tpl, hidden=ck.hidden, thr=thr,
                    guard_reason=guard(c["t"]) if guard is not None else None)
        ck.push(c["t"], v["ok"], D.loud_peak(c), v["kind"])
    if ck.decide_at is not None:
        at = ck.decide_at
        a = ck.poll(at)
        if a:
            fired.append((at, a))
    return fired


def fast_stream(clips, bed_files, rng, cal_peak, gap, n=6):
    """Запись: человек щёлкает n раз подряд через gap секунд (как владелец в работе)."""
    dur = 2.0 + gap * (n + 1)
    bed = E.bed_from(bed_files, dur, -55, rng) if bed_files else None
    times = []
    for k, cl in enumerate(clips[:n]):
        at = 1.2 + gap * k
        E.place_clip(bed, cl, at, cal_peak + rng.uniform(-4, 2), cl[2])
        times.append(at)
    return E.cands_of(bed), times


def pairs(groups, mix, guard, minutes, thr, gaps=(0.3, 0.5, 0.7, 0.9, 1.1, 1.3)):
    """Возврат ДВУМЯ щелчками: какие промежутки между щелчками программа принимает за пару и чего стоит
    расширить окно. Владелец 16.10.2026: «двойные щелчки я поставил, по-моему, они не работают»."""
    rows = []
    base = (D.BACK_GAP, D.BACK_SPAN)
    try:
        for gmax, span in ((1.0, 2.0), (1.4, 2.5), (1.8, 3.0)):
            D.BACK_GAP, D.BACK_SPAN = (0.12, gmax), span
            got = {}
            for g in gaps:
                hit = n = 0
                for grp in groups:
                    cs, times = grp["conds"]["A"]
                    snaps = [c for c in (next((x for x in cs if abs(x["t"] - t) < 0.03), None) for t in times)
                             if c is not None]
                    for i in range(CAL_MAX, len(snaps) - 1, 2):
                        a, b = dict(snaps[i]), dict(snaps[i + 1])
                        a["t"], b["t"] = 1.0, 1.0 + g
                        fired = run_stream([a, b], grp["tpl"], thr, False, hidden=True, back_n=2)
                        hit += 1 if fired else 0
                        n += 1
                got[g] = round(100 * hit / max(1, n), 1)
            fa = [len(run_stream(mix, grp["tpl"], thr, False, hidden=True, back_n=2)) for grp in groups]
            fag = [len(run_stream(mix, grp["tpl"], thr, False, guard=guard, hidden=True, back_n=2))
                   for grp in groups]
            row = {"окно пары, с": gmax, **{f"промежуток {g} с, %": v for g, v in got.items()},
                   "ложных возвратов в час": round(float(np.mean(fa)) * 60 / minutes, 2),
                   "в час с защитой": round(float(np.mean(fag)) * 60 / minutes, 2)}
            rows.append(row)
            print(row, flush=True)
    finally:
        D.BACK_GAP, D.BACK_SPAN = base
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "eval", "out"))
    ap.add_argument("--thr", default="45,40")
    ap.add_argument("--gap", type=float, default=0.45)
    ap.add_argument("--pairs", action="store_true")
    a = ap.parse_args()
    st = pickle.load(open(os.path.join(a.out, "cache.pkl"), "rb"))
    mix, labels = st["mix"], st["labels"]
    guard = own_keys_guard(labels)
    minutes = sum(b - t for t, b, _ in labels) / 60
    thrs = [float(v) for v in a.thr.split(",")]
    groups = []
    for g in st["pos"]:
        if not g["tpl"]:
            continue
        a_cs, a_times = g["conds"]["A"]
        cands = snap_cands(a_cs, a_times)
        cal = calib_set(cands, CAL_NEED)
        if not cal or len([c for c in cands if c is not None]) < CAL_MAX + 2:
            continue
        groups.append({"name": g["name"], "conds": g["conds"], "tpl": D.make_template(cal)})
    print(f"шаблонов: {len(groups)}, смесь: {minutes:.1f} мин", flush=True)

    if a.pairs:
        rs = [r for thr in thrs for r in pairs(groups, mix, guard, minutes, thr)]
        json.dump(rs, open(os.path.join(a.out, "pairs.json"), "w"), ensure_ascii=False, indent=1)
        return
    out = {"gap": a.gap, "rows": [], "back": []}
    # Сколько случайных ВОЗВРАТОВ в час даёт каждый выбор (один / два / три щелчка) - окна уже свёрнуты
    for thr in thrs:
        for n in (1, 2, 3):
            fa = [len(run_stream(mix, g["tpl"], thr, False, hidden=True, back_n=n)) for g in groups]
            fag = [len(run_stream(mix, g["tpl"], thr, False, guard=guard, hidden=True, back_n=n)) for g in groups]
            row = {"порог": thr, "щелчков на возврат": n,
                   "случайных возвратов в час": round(float(np.mean(fa)) * 60 / minutes, 2),
                   "макс": round(max(fa) * 60 / minutes, 1),
                   "в час с защитой": round(float(np.mean(fag)) * 60 / minutes, 2),
                   "макс с защитой": round(max(fag) * 60 / minutes, 1)}
            out["back"].append(row)
            print(row, flush=True)
    for thr in thrs:
        for toggle in (True, False):
            # 1. быстрые щелчки подряд - по готовым потокам условий A/B (щелчки стоят через 3,5 с, но нам важна
            # способность отвечать на КАЖДЫЙ щелчок, поэтому берём плотный поток: см. ниже «подряд»)
            answered = total = extra = 0
            for g in groups:
                for cond in ("A", "B"):
                    cs, times = g["conds"][cond]
                    test = [t for i, t in enumerate(times) if i >= CAL_MAX]
                    if not test:
                        continue
                    fired = run_stream(cs, g["tpl"], thr, toggle)
                    for t in test:
                        k = sum(1 for f, _ in fired if t - 0.05 <= f <= t + 1.0)
                        answered += 1 if k else 0
                        extra += max(0, k - 1)
                        total += 1
            # 2. ложные срабатывания на смеси
            fa = [len(run_stream(mix, g["tpl"], thr, toggle)) for g in groups]
            fag = [len(run_stream(mix, g["tpl"], thr, toggle, guard=guard)) for g in groups]
            row = {"порог": thr, "один щелчок переключает": toggle,
                   "ответил на щелчок, %": round(100 * answered / max(1, total), 1),
                   "лишних ответов на один щелчок": extra,
                   "ложных в час": round(float(np.mean(fa)) * 60 / minutes, 2),
                   "ложных в час, макс": round(max(fa) * 60 / minutes, 1),
                   "ложных в час с защитой": round(float(np.mean(fag)) * 60 / minutes, 2),
                   "ложных в час с защитой, макс": round(max(fag) * 60 / minutes, 1)}
            out["rows"].append(row)
            print(row, flush=True)

    # 3. щелчки ПОДРЯД через gap секунд - на каждый ли отвечает программа
    rows = []
    for thr in thrs:
        for toggle in (True, False):
            answered = total = extra = 0
            for g in groups:
                cs, times = g["conds"]["A"]
                test = [(i, t) for i, t in enumerate(times) if i >= CAL_MAX]
                if len(test) < 3:
                    continue
                # «подряд»: берём кандидатов проверочных щелчков и сдвигаем их времена в плотный ряд
                dense = []
                for k, (i, t) in enumerate(test):
                    m = [c for c in cs if abs(c["t"] - t) < 0.03]
                    if not m:
                        continue
                    c = dict(m[0])
                    c["t"] = 1.0 + a.gap * k
                    dense.append(c)
                if len(dense) < 3:
                    continue
                fired = run_stream(dense, g["tpl"], thr, toggle)
                for c in dense:
                    k = sum(1 for f, _ in fired if c["t"] - 0.05 <= f <= c["t"] + a.gap - 0.02)
                    answered += 1 if k else 0
                    extra += max(0, k - 1)
                    total += 1
            rows.append({"порог": thr, "один щелчок переключает": toggle, "щелчки через, с": a.gap,
                         "ответил, %": round(100 * answered / max(1, total), 1), "лишних": extra,
                         "щелчков": total})
            print(rows[-1], flush=True)
    out["dense"] = rows
    json.dump(out, open(os.path.join(a.out, "fast_toggle.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
