#!/usr/bin/env python3
# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Подбор допусков ВОЗВРАТА окон: что даёт каждая поблажка по отдельности - сколько возвратов узнано и сколько
окон всплывёт само (ложные возвраты на той же 30-минутной смеси). Сервер 2.

    ../venv/bin/python eval/grid_back.py ~/shchelchok_build/data [--sens 5] [--only имя,имя]

Берёт готовые потоки из eval/out/cache.pkl (41 шаблон, 30-минутная смесь) и eval/out/pressure_cache.pkl
(«щёлкает 8 раз подряд», фон тихий и офисный). Печатает таблицу: узнано без печати / с печатью вспышками /
печатает сплошь / ложные возвраты на 30 мин (среднее и максимум по 41 шаблону).
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
from eval import pressure as P  # noqa: E402
from shchelchok import detector as D  # noqa: E402

# Поблажки на возврат: по одной и вместе. iso - (тишина до, тишина после), gap - промежуток между щелчками.
CONFIGS = {
    "1.1.0 (как было)": dict(bonus=0, maybe=False, iso=(0.5, 0.3), gap=(0.15, 0.8), span=1.5, chain=False),
    "только не глушить свои": dict(bonus=0, maybe=False, iso=(0.5, 0.3), gap=(0.15, 0.8), span=1.5),
    "+ порог мягче на 1": dict(bonus=1, maybe=False, iso=(0.5, 0.3), gap=(0.15, 0.8), span=1.5),
    "+ порог мягче на 2": dict(bonus=2, maybe=False, iso=(0.5, 0.3), gap=(0.15, 0.8), span=1.5),
    "+ промежуток до 1 с": dict(bonus=0, maybe=False, iso=(0.5, 0.3), gap=(0.12, 1.0), span=2.0),
    "+ почти-щелчок в паре": dict(bonus=0, maybe=True, iso=(0.5, 0.3), gap=(0.15, 0.8), span=1.5),
    "+ тишина до 0,25 с": dict(bonus=0, maybe=False, iso=(0.25, 0.3), gap=(0.15, 0.8), span=1.5),
    "+ тишина до 0,15 с": dict(bonus=0, maybe=False, iso=(0.15, 0.3), gap=(0.15, 0.8), span=1.5),
    "+ тишина после 0,15 с": dict(bonus=0, maybe=False, iso=(0.5, 0.15), gap=(0.15, 0.8), span=1.5),
    "всё вместе (1.2.0 перв.)": dict(bonus=2, maybe=True, iso=(0.15, 0.15), gap=(0.12, 1.0), span=2.0),
    # сочетания (поблажки умножают ложные, поэтому выбираем парой-тройкой, а не всё сразу)
    "A свои+почти": dict(bonus=0, maybe=True, iso=(0.5, 0.3), gap=(0.15, 0.8), span=1.5),
    "B A+порог 1": dict(bonus=1, maybe=True, iso=(0.5, 0.3), gap=(0.15, 0.8), span=1.5),
    "C A+порог 2": dict(bonus=2, maybe=True, iso=(0.5, 0.3), gap=(0.15, 0.8), span=1.5),
    "D A+тишина 0,25": dict(bonus=0, maybe=True, iso=(0.25, 0.3), gap=(0.15, 0.8), span=1.5),
    "E D+промежуток 1 с": dict(bonus=0, maybe=True, iso=(0.25, 0.3), gap=(0.12, 1.0), span=2.0),
    "F E+порог 1": dict(bonus=1, maybe=True, iso=(0.25, 0.3), gap=(0.12, 1.0), span=2.0),
    "G E+порог 2": dict(bonus=2, maybe=True, iso=(0.25, 0.3), gap=(0.12, 1.0), span=2.0),
    "H порог 2+тишина 0,25": dict(bonus=2, maybe=False, iso=(0.25, 0.3), gap=(0.12, 1.0), span=2.0),
}


def run_config(cfg, streams, groups, mix, sens, seed, typing_window):
    """-> (узнано по режимам печати, ложные возвраты по шаблонам)."""
    old_bonus, old_maybe = D.RESTORE_SENS_BONUS, D.MAYBE_GAP
    D.RESTORE_SENS_BONUS = cfg["bonus"]
    D.MAYBE_GAP = old_maybe if cfg["maybe"] else -1.0        # -1 - почти-щелчков нет вовсе
    prof = dict(back_iso=cfg["iso"], back_gap=cfg["gap"], back_span=cfg["span"])
    chain = cfg.get("chain", True)
    try:
        res = {}
        for label, mode in (("тихо", "none"), ("вспышки", "bursts"), ("сплошь", "solid")):
            rng = np.random.default_rng(seed + 1)
            got = [0, 0]
            for name, tpl in groups:
                for cond, (cs, times, dur) in streams.get(name, {}).items():
                    ks = P.typing_times(dur, mode, rng)
                    g = P.typing_guard(ks, *typing_window) if ks else None
                    fired, _ = sim(cs, tpl, sens, prof, chain, guard=g)
                    got[1] += 1
                    got[0] += 1 if fired else 0
            res[label] = round(100 * got[0] / max(1, got[1]), 1)
        fa = [len(sim(mix, tpl, sens, prof, chain)[0]) for _, tpl in groups]
        return res, fa
    finally:
        D.RESTORE_SENS_BONUS, D.MAYBE_GAP = old_bonus, old_maybe


def sim(cands, tpl, sens, prof, chain, guard=None):
    """То же, что detector.simulate(hidden=True), но с нашими допусками и с выключаемой защитой «свои щелчки
    не считаются шумом» (chain=False - как в 1.1.0)."""
    ck = D.Clicker(mode=1, hidden=True, **prof)
    if not chain:
        ck._loud_between = lambda a, b, peak: any(  # noqa: SLF001
            a < t <= b and p >= peak - D.REL_DB for t, p, _ in ck.recent)
    fired, events = [], []
    for c in cands:
        now = c["t"] + D.POST_MS / 1000.0
        if ck.decide_at is not None and ck.decide_at <= now:
            at = ck.decide_at
            if ck.poll(at):
                fired.append(at)
        ck.poll(now)
        v = D.judge(c, tpl, sens, hidden=True, guard_reason=guard(c["t"]) if guard else None)
        ck.push(c["t"], v["ok"], D.loud_peak(c), v["kind"])
        events.append(v)
    return fired, events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--sens", type=int, default=5)
    ap.add_argument("--out", default=os.path.join(ROOT, "eval", "out"))
    ap.add_argument("--seed", type=int, default=23)
    ap.add_argument("--only", default="")
    ap.add_argument("--typing", default="0.1,0.06", help="окно защиты «печатаю» при свёрнутых окнах, с")
    a = ap.parse_args()
    st = pickle.load(open(os.path.join(a.out, "cache.pkl"), "rb"))
    groups = [(g["name"], g["tpl"]) for g in st["pos"] if g["tpl"]]
    mix = st["mix"]
    streams = pickle.load(open(os.path.join(a.out, "pressure_cache.pkl"), "rb"))
    tw = tuple(float(v) for v in a.typing.split(","))
    only = [s.strip() for s in a.only.split(",") if s.strip()]
    rows = []
    for name, cfg in CONFIGS.items():
        if only and name not in only:
            continue
        res, fa = run_config(cfg, streams, groups, mix, a.sens, a.seed, tw)
        rows.append({"что": name, **res, "ложные/30 мин": round(float(np.mean(fa)), 2), "макс": int(max(fa))})
        print(rows[-1], flush=True)
    json.dump(rows, open(os.path.join(a.out, "grid_back.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
