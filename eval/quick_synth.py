# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shchelchok import detector as D
from eval import synth as S

def cands(y):
    fe = D.Frontend(); out = []
    a = S.to_int16(y)
    for i in range(0, len(a), 480):
        out += fe.feed(a[i:i+480].tolist())
    return out

rng = np.random.default_rng(1)
cen = 2900
bed = S.room(rng, 8, 0.003)
for k in range(3):
    S.place(bed, S.snap(rng, centroid=cen*rng.uniform(0.95,1.05)), 2 + k*1.5)
cc = cands(bed)
cal = [c for c in cc if not D.gates(c, strict=False) and c["snr"] >= 15]
print("cal", len(cal), D.calib_consistent(cal))
tpl = D.make_template(cal)
print(tpl)
for name, fn in [("snap", lambda: S.snap(rng, centroid=cen*rng.uniform(0.9,1.1))), ("snap_q", lambda: S.snap(rng, centroid=cen*rng.uniform(0.9,1.1), peak=0.15)),
                 ("snap_other", lambda: S.snap(rng)), ("clap", lambda: S.clap(rng)), ("key", lambda: S.key(rng)), ("mouse", lambda: S.mouse(rng)), ("knock", lambda: S.knock(rng))]:
    bed = S.room(rng, 40*2.5+2, 0.003)
    for k in range(40):
        S.place(bed, fn(), 1 + k*2.5)
    cs = cands(bed)
    fired, ev = D.simulate(cs, tpl)
    sc = sorted(e["score"] for e in ev)
    w = D.band_weights(tpl["shape"])
    ok = [c for c in cs if not D.gates(c)]
    if ok:
        ds = [D.rms_diff(c["shape"], tpl["shape"], w) for c in ok]; dd = [D.rms_diff(c["dec"], tpl["dec"]) for c in ok]
        print(f"   ds med={np.median(ds):.1f} p10={np.percentile(ds,10):.1f} p90={np.percentile(ds,90):.1f}  dd med={np.median(dd):.1f} p90={np.percentile(dd,90):.1f}")
    from collections import Counter
    print(f"{name:10s} cands={len(cs)} fired={len(fired)}/40 scores med={np.median(sc) if sc else 0:.0f} max={max(sc) if sc else 0:.0f}", Counter(e["reason"] for e in ev).most_common(4))
for name, fn in [("speech", lambda: S.speech(rng, 120, 0.05)), ("music", lambda: S.music(rng, 120, 0.05))]:
    y = fn() + S.room(rng, 120, 0.003)
    cs = cands(y)
    fired, ev = D.simulate(cs, tpl)
    from collections import Counter
    print(f"{name:10s} cands={len(cs)} fired={len(fired)} /2min", Counter(e["reason"] for e in ev).most_common(4))
