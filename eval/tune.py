#!/usr/bin/env python3
"""Подбор допусков детектора на реальных записях (CC0): разброс щелчков одного человека (SIG_BAND, SIG_DEC) и
порог, жёсткие запреты. Честно: 2 половины «людей» - допуски учатся на одной половине, проверяются на другой.
Цель: максимум распознавания одиночного щелчка при ложных <= цели на 30 мин смеси.

    ../venv/bin/python eval/tune.py ~/shchelchok_build/data [--rebuild]
"""
from __future__ import annotations

import argparse
import itertools
import os
import pickle
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eval import evaluate as E  # noqa: E402
from shchelchok import detector as D  # noqa: E402

GUARDED = {"keyboard", "mouse"}       # клавиатура и мышь ЭТОГО компьютера - отсекает защита программы


def iso_flags(cands):
    """Одиночный режим: у удара нет соседей не тише его на REL_DB за 0,5 с до и 0,35 с после."""
    t = np.array([c["t"] for c in cands])
    out = np.ones(len(cands), bool)
    for i in range(len(cands)):
        lo, hi = np.searchsorted(t, t[i] - 0.5), np.searchsorted(t, t[i] + 0.35, side="right")
        for j in range(lo, hi):
            pj = D.loud_peak(cands[j])
            if j != i and pj is not None and pj >= cands[i]["peak"] - D.REL_DB:
                out[i] = False
                break
    return out


def arr(cands):
    """Признаки ударов массивами."""
    g = lambda k: np.array([c[k] for c in cands], float)   # noqa: E731
    return {"shape": np.array([c["shape"] for c in cands]), "dec": np.array([c["dec"] for c in cands]),
            "peak": g("peak"), "rise": g("rise"), "decay": g("decay"), "pre": g("pre_gap"), "post": g("post_gap"),
            "cen": g("centroid"), "low": g("low"), "snr": g("snr"), "t": g("t")}


def gate_mask(a, decay_max=90, pre_min=10, post_min=12, rise_max=6, cen_min=1000, low_max=6):
    return ((a["rise"] <= rise_max) & (a["decay"] <= decay_max) & (a["pre"] >= pre_min) & (a["post"] >= post_min)
            & (a["cen"] >= cen_min) & (a["low"] <= low_max))


def dist(a, tpl, sb, sd, adec, sens=5):
    t = np.array(tpl["shape"])
    w = np.array(D.band_weights(tpl["shape"]))
    ds = ((((a["shape"] - t) / sb) ** 2) * w).sum(1) / w.sum()
    dd = (((a["dec"] - np.array(tpl["dec"])) / sd) ** 2).mean(1)
    ref = tpl.get("peak_mean", tpl["peak_min"])
    low = D.LVL_LOW + 1.5 * (sens - 5)
    d = a["peak"] - ref
    ex = np.where(d < -low, -d - low, np.where(d > D.LVL_HIGH, d - D.LVL_HIGH, 0.0))
    return ds + adec * dd + (ex / D.LVL_SIG) ** 2


def learn_sigma(groups):
    """Разброс своих щелчков около своего шаблона (по условию A), устойчиво (медиана модулей)."""
    db, dd = [], []
    for g in groups:
        cs, times = g["conds"]["A"]
        for t in times:
            m = [c for c in cs if abs(c["t"] - t) < 0.03 and D.gates(c, strict=False) is None]
            if m:
                db.append(np.array(m[0]["shape"]) - np.array(g["tpl"]["shape"]))
                dd.append(np.array(m[0]["dec"]) - np.array(g["tpl"]["dec"]))
    sb = np.maximum(1.5, 1.4826 * np.median(np.abs(np.array(db)), 0))
    sd = np.maximum(1.5, 1.4826 * np.median(np.abs(np.array(dd)), 0))
    return sb, sd


def greedy(times, mask, cooldown=1.5):
    n, last = 0, -1e9
    for t in times[mask]:
        if t - last >= cooldown:
            n += 1
            last = t
    return n


def build(data, rng):
    import json
    wav = os.path.join(data, "wav")
    classes = {c: [os.path.join(wav, c, f) for f in sorted(os.listdir(os.path.join(wav, c)))] for c in os.listdir(wav)}
    titles = json.load(open(os.path.join(data, "titles.json")))
    beds = E.beds_of(data, classes)
    groups = []
    for f in classes["snap"]:
        t = titles.get(os.path.basename(f)[:-4], {}).get("title", "").lower()
        if any(b in t for b in E.BAD_TITLE):
            continue
        clips = E.snap_events(f)
        if len(clips) >= 4:
            groups.append((os.path.basename(f)[:-4], clips[:16]))
    pos = E.prepare_positive(groups, beds, rng)
    y, labels = E.build_mix({c: classes.get(c, []) for c, _ in E.MIX_PLAN}, beds, 30, rng)
    mix = E.cands_of(y)
    return {"pos": pos, "mix": mix, "labels": labels}


def evaluate_fold(test, sb, sd, mix_a, mix_iso, mix_cls, params):
    adec, dmax, gk = params
    gm = gate_mask(mix_a, **gk)
    fa, fa_g = [], []
    guarded = np.array([c in GUARDED for c in mix_cls])
    for g in test:
        ok = gm & mix_iso & (dist(mix_a, g["tpl"], sb, sd, adec) <= dmax)
        fa.append(greedy(mix_a["t"], ok))
        fa_g.append(greedy(mix_a["t"], ok & ~guarded))
    det = {}
    for cond in ("A", "B", "C"):
        h = n = 0
        for g in test:
            cs, times = g["conds"][cond]
            a = g["_arr"][cond]
            ok = gate_mask(a, **gk) & g["_iso"][cond] & (dist(a, g["tpl"], sb, sd, adec) <= dmax)
            for t in times:
                idx = np.where(np.abs(a["t"] - t) < 0.03)[0]
                h += bool(len(idx) and ok[idx].any())
                n += 1
        det[cond] = h / max(1, n)
    return fa, fa_g, det


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    cache = os.path.join(ROOT, "eval", "out", "cache.pkl")
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    if a.rebuild or not os.path.exists(cache):
        pickle.dump(build(a.data, np.random.default_rng(7)), open(cache, "wb"))
    st = pickle.load(open(cache, "rb"))
    pos = [g for g in st["pos"] if g["tpl"]]
    for g in pos:
        g["_arr"] = {c: arr(cs) for c, (cs, _) in g["conds"].items()}
        g["_iso"] = {c: iso_flags(cs) for c, (cs, _) in g["conds"].items()}
    mix = st["mix"]
    mix_a = arr(mix)
    mix_iso = iso_flags(mix)
    mix_cls = [E.label_at(st["labels"], t) for t in mix_a["t"]]
    folds = [pos[0::2], pos[1::2]]
    sig = [learn_sigma(folds[1]), learn_sigma(folds[0])]      # учимся на другой половине
    sb_all, sd_all = learn_sigma(pos)
    print("SIG_BAND", np.round(sb_all, 1).tolist())
    print("SIG_DEC", np.round(sd_all, 1).tolist())
    grid = []
    for adec, dmax in itertools.product([0.25, 0.5, 1.0], [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0]):
        for dm, pm, po, cm in itertools.product([40, 60, 90], [10, 15, 20], [12, 16, 20], [1000, 1500]):
            grid.append((adec, dmax, {"decay_max": dm, "pre_min": pm, "post_min": po, "cen_min": cm}))
    res = []
    for params in grid:
        fa, fa_g, det = [], [], {"A": 0, "B": 0, "C": 0}
        for k in (0, 1):
            f, fg, d = evaluate_fold(folds[k], sig[k][0], sig[k][1], mix_a, mix_iso, mix_cls, params)
            fa += f
            fa_g += fg
            for c in det:
                det[c] += d[c] / 2
        res.append((params, float(np.mean(fa)), int(max(fa)), float(np.mean(fa_g)), int(max(fa_g)), det))
    pickle.dump(res, open(os.path.join(ROOT, "eval", "out", "tune.pkl"), "wb"))
    key = lambda r: -(r[5]["A"] + r[5]["B"])   # noqa: E731
    for title, cond in (("ложные <= 0,5 в среднем, без защиты", lambda r: r[1] <= 0.5 and r[2] <= 2),
                        ("ложные <= 1 в среднем, без защиты", lambda r: r[1] <= 1.0),
                        ("с защитой клавиатуры/мыши: ложные <= 0,5", lambda r: r[3] <= 0.5 and r[4] <= 2),
                        ("с защитой: ложные <= 1", lambda r: r[3] <= 1.0)):
        print("==", title)
        for r in sorted([r for r in res if cond(r)], key=key)[:6]:
            p = r[0]
            print(f"  adec={p[0]} dmax={p[1]} {p[2]} | ложные {r[1]:.2f}/{r[2]}, с защитой {r[3]:.2f}/{r[4]} | "
                  f"A {r[5]['A']:.3f} B {r[5]['B']:.3f} C {r[5]['C']:.3f}")


if __name__ == "__main__":
    main()
