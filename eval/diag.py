"""Разбор пропусков: условие A (тихая комната), по каждому щелчку - признаки и оценка."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval import evaluate as E
from shchelchok import detector as D
from collections import Counter
data = sys.argv[1]
rng = np.random.default_rng(7)
wav = os.path.join(data, "wav")
import json
titles = json.load(open(os.path.join(data, "titles.json")))
amb = [os.path.join(wav, "ambience", f) for f in os.listdir(os.path.join(wav, "ambience"))]
files = [os.path.join(wav, "snap", f) for f in sorted(os.listdir(os.path.join(wav, "snap")))
         if not any(b in titles.get(f[:-4], {}).get("title", "").lower() for b in E.BAD_TITLE)]
stats = Counter()
rows = []
for f in files:
    clips = E.snap_events(f)
    if len(clips) < 4:
        continue
    cal_peak = -12
    tpl, why = E.calibrate(clips[:3], amb, rng, cal_peak)
    if not tpl:
        continue
    bed = E.bed_from(amb, 2 + 3.5 * len(clips), -55, rng)
    times = []
    for k, cl in enumerate(clips[3:]):
        at = 1.5 + 3.5 * k
        E.place_clip(bed, cl, at, cal_peak, cl[2]); times.append(at)
    cs = E.cands_of(bed)
    w = D.band_weights(tpl["shape"])
    for t in times:
        near = [c for c in cs if t - 0.02 <= c["t"] <= t + 0.45]
        main = [c for c in near if abs(c["t"] - t) < 0.02]
        if not main:
            stats["нет удара"] += 1; continue
        c = main[0]
        s, r = D.score(c, tpl)
        ds = D.rms_diff(c["shape"], tpl["shape"], w); dd = D.rms_diff(c["dec"], tpl["dec"])
        extra = len(near) - 1
        stats[(r or "ok") + (" +хвост" if extra else "")] += 1
        rows.append((os.path.basename(f)[:-4], round(s), r, round(ds, 1), round(dd, 1), c["rise"], c["decay"], round(c["pre_gap"]), round(c["post_gap"]), round(c["centroid"]), round(c["low"]), extra, tpl["spread"]))
print(stats)
for r in rows:
    if r[2] or r[11]:
        print(r)
