#!/usr/bin/env python3
# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Что даёт настройка 1.3.0: калибровка по 5-7 щелчкам вместо 3, НЕСКОЛЬКО образцов вместо среднего и порог
числом (его человек двигает сам). Те же записи CC0 и та же 30-минутная смесь, что в README. Сервер 2.

    ../venv/bin/python eval/calib_n.py [--out eval/out] [--thr 60,50,45,42,40,38,35]

Берёт готовые потоки из eval/out/cache.pkl. Для каждого «человека»:
  - щелчки в тихой комнате (условие A) по порядку: первые K - калибровка (K = 3, как было, и 6, как стало),
    остальные (с 7-го) - проверка; проверочный набор ОДИН И ТОТ ЖЕ для всех K, иначе цифры несравнимы;
  - шаблон: «среднее» (как в 1.2.0) и «среднее + образцы» (как в 1.3.0, сравнение с лучшим из них);
  - порог: фиксированный из списка и «подобранный под человека» (`tuning.suggest_threshold` по оценкам его же
    щелчков, честно - каждый оценён шаблоном из остальных).
Считаем: узнавание одиночного щелчка (A тихо, B офис, C разговор рядом) и ложные срабатывания на 30-минутной
смеси - без защиты и с защитой «клавиатура и мышь ЭТОГО компьютера» (как у владельца за ноутбуком).
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from collections import Counter

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eval import evaluate as E  # noqa: E402
from eval.fa_back import own_keys_guard  # noqa: E402
from shchelchok import detector as D, tuning as T  # noqa: E402

CAL_MAX = 6          # столько первых щелчков человека отдаём под калибровку (проверка - с 7-го)
CAL_NEED = 5         # столько щелчков просит окно «Настройка щелчка» в 1.3.0 (было 3)


def snap_cands(cs, times):
    """По одному кандидату на каждый щелчок (в порядке щелчков); None - щелчок не услышан вовсе."""
    out = []
    for t in times:
        m = [c for c in cs if abs(c["t"] - t) < 0.03]
        out.append(m[0] if m else None)
    return out


def calib_set(cands, k):
    """Калибровка как в окне: берём первые k услышанных щелчков, непохожие выбрасываем (pick_calib)."""
    got = [c for c in cands[:k] if c is not None and not D.gates(c, strict=False) and c["snr"] >= 15]
    if len(got) < 3:
        return []
    kept, _ = D.pick_calib(got, need=k)
    return kept


def flat(tpl):
    """Шаблон без образцов - ровно то, что было в 1.2.0."""
    t = dict(tpl)
    t.pop("samples", None)
    return t


def detect(group, tpl, thr, guard=None):
    """Узнавание на проверочных щелчках (с 7-го) по условиям A/B/C. -> {cond: (узнано, всего)}."""
    res = {}
    for cond, (cs, times) in group["conds"].items():
        test = [(i, t) for i, t in enumerate(times) if i >= CAL_MAX]
        if not test:
            res[cond] = (0, 0)
            continue
        fired, _ = D.simulate(cs, tpl, thr=thr, mode=1, guard=guard)
        hit = sum(1 for _, t in test if any(t - 0.05 <= f <= t + 1.0 for f in fired))
        res[cond] = (hit, len(test))
    return res


def grid(groups, mix, guard, thrs):
    """Плата за совпадение с ОДНИМ образцом (SAMPLE_PENALTY) и ширина допуска (SAMPLE_SIG): что из этого даёт
    узнавание без лишних ложных срабатываний. Сравниваем с «средним» шаблоном при том же пороге."""
    rows = []
    base_sig, base_pen = D.SAMPLE_SIG, D.SAMPLE_PENALTY
    try:
        for sig, pen in [(None, None)] + [(s, p) for s in (1.41, 1.8) for p in (0.0, 1.0, 2.0, 3.0, 4.0)]:
            for thr in thrs:
                tpls = []
                for g in groups:
                    t = D.make_template(g["cal"][CAL_NEED])
                    tpls.append(flat(t) if sig is None else t)
                if sig is not None:
                    D.SAMPLE_SIG, D.SAMPLE_PENALTY = sig, pen
                det = Counter()
                fa, fag = [], []
                for i, g in enumerate(groups):
                    for cond, (hit, n) in detect(g, tpls[i], thr).items():
                        det[cond + "h"] += hit
                        det[cond + "n"] += n
                    fa.append(len(D.simulate(mix, tpls[i], thr=thr, mode=1)[0]))
                    fag.append(len(D.simulate(mix, tpls[i], thr=thr, mode=1, guard=guard)[0]))
                rows.append({"образцы": "нет" if sig is None else f"sig {sig} плата {pen}", "порог": thr,
                             "A": round(100 * det["Ah"] / max(1, det["An"]), 1),
                             "B": round(100 * det["Bh"] / max(1, det["Bn"]), 1),
                             "C": round(100 * det["Ch"] / max(1, det["Cn"]), 1),
                             "ложные": round(float(np.mean(fa)), 2),
                             "с защитой": round(float(np.mean(fag)), 2)})
                print(rows[-1], flush=True)
    finally:
        D.SAMPLE_SIG, D.SAMPLE_PENALTY = base_sig, base_pen
    return rows


def bimodal(groups, mix, guard, thr=45.0):
    """Главный вопрос про образцы: настройка 1.3.0 просит щёлкать ПО-РАЗНОМУ (сильнее и тише, ближе и дальше),
    и щелчки в ней получаются непохожими друг на друга. Среднее по таким щелчкам не похоже ни на один из них.

    Проверяем в чистом виде: шаблон из щелчков ДВУХ разных «людей» (крайний случай «щёлкаю по-разному»), проверка
    на остальных щелчках обоих. Сравниваем «среднее» и «среднее + образцы» при том же пороге."""
    rows = []
    for mode in ("среднее", "среднее+образцы"):
        det = Counter()
        fa, fag = [], []
        for i in range(0, len(groups) - 1, 2):
            g1, g2 = groups[i], groups[i + 1]
            cal = g1["cal"][3] + g2["cal"][3]
            t = D.make_template(cal)
            tpl = t if mode == "среднее+образцы" else flat(t)
            for g in (g1, g2):
                for cond, (hit, n) in detect(g, tpl, thr).items():
                    det[cond + "h"] += hit
                    det[cond + "n"] += n
            fa.append(len(D.simulate(mix, tpl, thr=thr, mode=1)[0]))
            fag.append(len(D.simulate(mix, tpl, thr=thr, mode=1, guard=guard)[0]))
        rows.append({"шаблон": mode, "порог": thr,
                     "A тихо": round(100 * det["Ah"] / max(1, det["An"]), 1),
                     "B офис": round(100 * det["Bh"] / max(1, det["Bn"]), 1),
                     "C разговор": round(100 * det["Ch"] / max(1, det["Cn"]), 1),
                     "ложные/30 мин": round(float(np.mean(fa)), 2),
                     "с защитой": round(float(np.mean(fag)), 2)})
        print(rows[-1], flush=True)
    return rows


def drop(groups):
    """На сколько очков живой щелчок получает МЕНЬШЕ, чем щелчок настройки (от этого зависит, какой порог
    предлагать: по щелчкам настройки он выходит слишком строгим)."""
    rows = []
    for g in groups:
        cal = g["cal"][CAL_NEED]
        tpl = D.make_template(cal)
        loo = T.loo_scores(cal, thr=45)
        for cond, (cs, times) in g["conds"].items():
            live = []
            for i, t in enumerate(times):
                if i < CAL_MAX:
                    continue
                m = [c for c in cs if abs(c["t"] - t) < 0.03]
                if m:
                    live.append(D.score(m[0], tpl, thr=45)[0])
            if live and loo:
                rows.append({"name": g["name"], "cond": cond, "cal": float(np.median(loo)),
                             "live": float(np.median(live)), "drop": float(np.median(loo) - np.median(live))})
    for cond in ("A", "B", "C"):
        d = [r["drop"] for r in rows if r["cond"] == cond]
        print(f"условие {cond}: живой щелчок ниже щелчка настройки на {np.median(d):.1f} очка "
              f"(медиана; четверти {np.percentile(d, 25):.1f} / {np.percentile(d, 75):.1f})", flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "eval", "out"))
    ap.add_argument("--thr", default="60,50,45,42,40,38,35")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--drop", action="store_true")
    ap.add_argument("--bimodal", action="store_true")
    a = ap.parse_args()
    st = pickle.load(open(os.path.join(a.out, "cache.pkl"), "rb"))
    mix, labels = st["mix"], st["labels"]
    guard = own_keys_guard(labels)
    thrs = [float(v) for v in a.thr.split(",")]
    groups = []
    for g in st["pos"]:
        if not g["tpl"]:
            continue
        a_cs, a_times = g["conds"]["A"]
        cands = snap_cands(a_cs, a_times)
        if len([c for c in cands if c is not None]) < CAL_MAX + 2:
            continue                                  # на такого «человека» не хватает щелчков для сравнения
        cal = {k: calib_set(cands, k) for k in (3, CAL_NEED)}
        if not all(cal.values()):
            continue
        groups.append({"name": g["name"], "conds": g["conds"], "cal": cal})
    print(f"«людей» с запасом щелчков: {len(groups)}", flush=True)
    if a.grid or a.drop or a.bimodal:
        out = {"groups": len(groups)}
        if a.bimodal:
            out["bimodal"] = [r for t in [float(v) for v in a.thr.split(",")] for r in bimodal(groups, mix, guard, t)]
        if a.drop:
            out["drop"] = drop(groups)
        if a.grid:
            out["grid"] = grid(groups, mix, guard, [60.0, 45.0, 40.0])
        json.dump(out, open(os.path.join(a.out, "calib_grid.json"), "w"), ensure_ascii=False, indent=1)
        return

    rows = []
    auto = {}
    for k in (3, CAL_NEED):
        for mode in ("среднее", "среднее+образцы"):
            tpls = []
            for g in groups:
                t = D.make_template(g["cal"][k])
                tpls.append(t if mode == "среднее+образцы" else flat(t))
            # порог «под человека» - по оценкам его же щелчков (шаблон из остальных)
            if mode == "среднее+образцы":
                picked = []
                for g, t in zip(groups, tpls):
                    loo = T.loo_scores(g["cal"][k], thr=45)
                    picked.append(T.suggest_threshold([], noise=[], cur=45, cal=loo)["thr"])
                auto[k] = picked
            for thr in thrs + (["auto"] if mode == "среднее+образцы" else []):
                det = Counter()
                fa, fag = [], []
                for i, g in enumerate(groups):
                    tv = auto[k][i] if thr == "auto" else thr
                    for cond, (hit, n) in detect(g, tpls[i], tv).items():
                        det[cond + "h"] += hit
                        det[cond + "n"] += n
                    fa.append(len(D.simulate(mix, tpls[i], thr=tv, mode=1)[0]))
                    fag.append(len(D.simulate(mix, tpls[i], thr=tv, mode=1, guard=guard)[0]))
                row = {"щелчков на настройке": k, "шаблон": mode,
                       "порог": (f"свой ({int(np.median(auto[k]))} в среднем)" if thr == "auto" else int(thr)),
                       "A тихо": round(100 * det["Ah"] / max(1, det["An"]), 1),
                       "B офис": round(100 * det["Bh"] / max(1, det["Bn"]), 1),
                       "C разговор": round(100 * det["Ch"] / max(1, det["Cn"]), 1),
                       "ложные/30 мин": round(float(np.mean(fa)), 2), "макс": int(max(fa)),
                       "с защитой клав./мыши": round(float(np.mean(fag)), 2), "макс с защитой": int(max(fag))}
                rows.append(row)
                print(row, flush=True)
    out = {"rows": rows, "auto_thresholds": auto, "groups": len(groups), "cal_max": CAL_MAX,
           "mix_minutes": round(sum(b - t for t, b, _ in labels) / 60, 1)}
    json.dump(out, open(os.path.join(a.out, "calib_n.json"), "w"), ensure_ascii=False, indent=1)
    print("подобранные пороги (медиана / мин / макс):",
          {k: (int(np.median(v)), int(min(v)), int(max(v))) for k, v in auto.items()})


if __name__ == "__main__":
    main()
