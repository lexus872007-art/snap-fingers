#!/usr/bin/env python3
"""ВЯЛЫЙ ЩЕЛЧОК: почему у владельца «срабатывает через раз» и что с этим можно сделать. Сервер 2.

    ../venv/bin/python eval/weak_snap.py [--thr 42] [--quiet 0,6,12,18]

Факт из его журнала 1.3.0 (13,7 мин, 84 звука): узнано 57 щелчков (оценки 44-87), отклонено 27, и 14 из них -
в коридоре 36-41, то есть «не дотянули чуть-чуть». Его настройка снята ТРЕМЯ громкими щелчками (в файле
настроек `n=3`, образцов нет, peak_mean -8,2 дБ), а живые щелчки в работе тише и мягче - он сам это понял:
«нужно быстрые щелчки делать, не вялые».

Здесь проверяем на записях CC0 ровно эту картину: шаблон по 3 громким щелчкам, а проверочные щелчки ТИШЕ
шаблона на 0/6/12/18 дБ. И смотрим, что возвращает вялые щелчки, не пуская при этом посторонние звуки:
  * LVL_LOW - на сколько дБ щелчок может быть тише шаблона без штрафа;
  * rise_max - насколько резким обязан быть удар (жёсткий запрет «медленно нарастает»);
  * dec_floor - не сравнивать точки затухания, которые у тихого щелчка уже утонули в шуме.
Ложные срабатывания считаются на той же 30-минутной смеси, с защитой «клавиатура и мышь этого ПК» и без неё.
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
from eval.calib_n import CAL_MAX, calib_set, snap_cands  # noqa: E402
from eval.fa_back import own_keys_guard  # noqa: E402
from shchelchok import detector as D  # noqa: E402


def quieter(c, db):
    """Тот же удар, но тише на db децибел (громкость и профиль затухания сдвигаются, форма спектра - нет)."""
    out = dict(c)
    out["peak"] = c["peak"] - db
    out["snr"] = c["snr"] - db
    floor = max(-35.0, out["noise"] - out["peak"])
    out["dec"] = [max(floor, v) for v in c["dec"]]      # тихий щелчок быстрее утыкается в шум комнаты
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "eval", "out"))
    ap.add_argument("--thr", type=float, default=42.0)
    ap.add_argument("--quiet", default="0,6,12,18")
    a = ap.parse_args()
    st = pickle.load(open(os.path.join(a.out, "cache.pkl"), "rb"))
    mix, labels = st["mix"], st["labels"]
    guard = own_keys_guard(labels)
    minutes = sum(b - t for t, b, _ in labels) / 60
    quiets = [float(v) for v in a.quiet.split(",")]

    groups = []
    for g in st["pos"]:
        if not g["tpl"]:
            continue
        cs, times = g["conds"]["A"]
        cands = snap_cands(cs, times)
        cal = calib_set(cands, 3)                      # как у владельца: шаблон по ТРЁМ щелчкам
        test = [c for i, c in enumerate(cands) if i >= 3 and c is not None]
        if not cal or len(test) < 3:
            continue
        groups.append({"name": g["name"], "tpl": D.make_template(cal), "test": test,
                       "office": [c for i, c in enumerate(snap_cands(*g["conds"]["B"])) if i >= 3 and c is not None]})
    print(f"шаблонов: {len(groups)} (каждый по 3 громким щелчкам, как у владельца)", flush=True)

    base = (D.LVL_LOW, D.SIG_DEC, D.DEC_FLOOR_SKIP if hasattr(D, "DEC_FLOOR_SKIP") else None)
    rows = []
    for lvl_low in (8.0, 12.0, 16.0, 20.0):
        for skip in (False, True):
            D.LVL_LOW = lvl_low
            if hasattr(D, "DEC_FLOOR_SKIP"):
                D.DEC_FLOOR_SKIP = skip
            elif skip:
                continue
            det = {}
            for db in quiets:
                hit = n = 0
                for g in groups:
                    for c in g["test"] + g["office"]:
                        s, reason = D.score(quieter(c, db), g["tpl"], thr=a.thr)
                        hit += 1 if not reason else 0
                        n += 1
                det[db] = round(100 * hit / max(1, n), 1)
            fa, fag = [], []
            for g in groups:
                f, _ = D.simulate(mix, g["tpl"], thr=a.thr, mode=1)
                fa.append(len(f))
                f2, _ = D.simulate(mix, g["tpl"], thr=a.thr, mode=1, guard=guard)
                fag.append(len(f2))
            row = {"тише шаблона без штрафа, дБ": lvl_low, "не сравнивать утонувшее затухание": skip,
                   **{f"узнан, тише на {int(k)} дБ, %": v for k, v in det.items()},
                   "ложных в час": round(float(np.mean(fa)) * 60 / minutes, 2),
                   "в час с защитой": round(float(np.mean(fag)) * 60 / minutes, 2)}
            rows.append(row)
            print(row, flush=True)
    D.LVL_LOW, D.SIG_DEC = base[0], base[1]
    if hasattr(D, "DEC_FLOOR_SKIP") and base[2] is not None:
        D.DEC_FLOOR_SKIP = base[2]
    json.dump(rows, open(os.path.join(a.out, "weak_snap.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
