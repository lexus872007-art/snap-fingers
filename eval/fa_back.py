#!/usr/bin/env python3
"""Откуда берутся ложные ВОЗВРАТЫ окон: по классам звука (речь, клавиатура, музыка…) и сколько из них отсечёт
защита «клавиатура и мышь ЭТОГО компьютера». Сервер 2.

    ../venv/bin/python eval/fa_back.py [--out eval/out] [--sens 5]

Та же 30-минутная смесь, что в README (eval/out/cache.pkl), 41 шаблон, состояние «окна свёрнуты».
Защита моделируется как в программе при свёрнутых окнах: удар отвергается, если в этот момент (-0,10 / +0,06 с)
на компьютере нажали клавишу или кнопку мыши. «Своя клавиатура» - считаем, что вся клавиатура и мышь в смеси
набиралась на этом же компьютере (так защита работает у владельца за ноутбуком).
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
from shchelchok import detector as D  # noqa: E402

GUARD = (0.10, 0.06)       # окно защиты при свёрнутых окнах (app.GUARD_BACK)


def own_keys_guard(labels):
    """Защита «клавиатура и мышь этого компьютера»: внутри кусков смеси класса keyboard/mouse нажатия СВОИ."""
    iv = [(a, b) for a, b, c in labels if c in ("keyboard", "mouse")]

    def g(t):
        return "нажали клавишу" if any(a - GUARD[0] <= t <= b + GUARD[1] for a, b in iv) else None
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "eval", "out"))
    ap.add_argument("--sens", type=int, default=5)
    ap.add_argument("--bonus", type=int, default=None, help="поблажка порога на возврат (по умолчанию из кода)")
    a = ap.parse_args()
    if a.bonus is not None:
        D.RESTORE_SENS_BONUS = a.bonus
    st = pickle.load(open(os.path.join(a.out, "cache.pkl"), "rb"))
    groups = [(g["name"], g["tpl"]) for g in st["pos"] if g["tpl"]]
    mix, labels = st["mix"], st["labels"]
    by_cls = Counter()
    fa, fa_guard = [], []
    guard = own_keys_guard(labels)
    for _, tpl in groups:
        f, _ = D.simulate(mix, tpl, sens=a.sens, hidden=True)
        fa.append(len(f))
        for t in f:
            by_cls[E.label_at(labels, t - 0.3)] += 1
        fg, _ = D.simulate(mix, tpl, sens=a.sens, hidden=True, guard=guard)
        fa_guard.append(len(fg))
    out = {"ложные возвраты на 30 мин": {"среднее": round(float(np.mean(fa)), 2), "макс": int(max(fa))},
           "по классам звука (сумма по 41 шаблону)": dict(by_cls.most_common()),
           "со защитой «своя клавиатура и мышь»": {"среднее": round(float(np.mean(fa_guard)), 2),
                                                   "макс": int(max(fa_guard))},
           "минут звука в смеси": round(sum(b - t for t, b, _ in labels) / 60, 1)}
    json.dump(out, open(os.path.join(a.out, "fa_back.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
