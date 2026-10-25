# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Признаки ударов в wav-файлах (для подбора порогов): python eval/probe.py <папка|файл> ..."""
import os, sys, wave
from array import array
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shchelchok import detector as D

def read(path):
    with wave.open(path) as w:
        return array("h", w.readframes(w.getnframes()))

for arg in sys.argv[1:]:
    files = [os.path.join(arg, f) for f in sorted(os.listdir(arg))] if os.path.isdir(arg) else [arg]
    for p in files:
        fe = D.Frontend()
        cs = []
        s = read(p)
        for i in range(0, len(s), 480):
            cs += fe.feed(s[i:i + 480])
        print(f"== {os.path.basename(p)} {len(s)/16000:.1f}s cands={len(cs)}")
        for c in cs[:8]:
            g = D.gates(c)
            print(f"  t={c['t']:.2f} pk={c['peak']:.0f} snr={c['snr']:.0f} rise={c['rise']} dec={c['decay']} pre={c['pre_gap']:.0f} post={c['post_gap']:.0f} cen={c['centroid']:.0f} low={c['low']:.0f} {g or 'OK'}")
