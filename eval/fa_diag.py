import os, sys, pickle
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval import tune as T, evaluate as E
from shchelchok import detector as D
from collections import Counter, defaultdict
st = pickle.load(open(os.path.join(os.path.dirname(__file__), "out", "cache.pkl"), "rb"))
pos = [g for g in st["pos"] if g["tpl"]]; mix = st["mix"]; labels = st["labels"]
iso = T.iso_flags(mix)
gate = np.array([D.gates(c) is None for c in mix])
cls = [E.label_at(labels, c["t"]) for c in mix]
print("ударов по классам", Counter(cls))
print("прошли запреты", Counter(c for c, g in zip(cls, gate) if g))
print("прошли запреты+тишина", Counter(c for c, g, i in zip(cls, gate, iso) if g and i))
# лучший шаблонный score для каждого удара в смеси (среди шаблонов) - и для щелчков
so, ss, do, dsg = 3.0, 4.5, 3.0, 8.0
negs = defaultdict(list)
for g in pos:
    f = T.feats(mix, g["tpl"])
    s, okg = T.scores(f, g["tpl"], so, ss, do, dsg)
    for i in np.where(okg & iso)[0]:
        negs[cls[i]].append(s[i])
for k, v in negs.items():
    v = np.array(v); print(k, len(v), "p50", np.percentile(v, 50).round(), "p90", np.percentile(v, 90).round(), ">=60:", (v >= 60).sum())
pp = []
for g in pos:
    cs, times = g["conds"]["A"]
    f = T.feats(cs, g["tpl"]); s, okg = T.scores(f, g["tpl"], so, ss, do, dsg)
    ct = np.array([c["t"] for c in cs])
    for t in times:
        idx = np.where(np.abs(ct - t) < 0.03)[0]
        if len(idx): pp.append(s[idx[0]] if okg[idx[0]] else -1)
pp = np.array(pp); print("щелчки A", len(pp), "gate fail", (pp < 0).sum(), "p10", np.percentile(pp[pp>=0], 10).round(), "p50", np.percentile(pp[pp>=0], 50).round())
# признаки прошедших запреты негативов и щелчков
def summ(lst, name):
    a = np.array([[c["rise"], c["decay"], c["centroid"], c["low"], c["pre_gap"], c["post_gap"], c["snr"]] for c in lst])
    print(name, len(a), "rise/decay/cen/low/pre/post/snr p50:", np.median(a, 0).round(1), "p10", np.percentile(a, 10, 0).round(1), "p90", np.percentile(a, 90, 0).round(1))
for k in set(cls):
    lst = [c for c, cl, g, i in zip(mix, cls, gate, iso) if cl == k and g and i]
    if lst: summ(lst, k)
sn = []
for g in pos:
    cs, times = g["conds"]["A"]
    for t in times:
        sn += [c for c in cs if abs(c["t"] - t) < 0.03]
summ(sn, "ЩЕЛЧКИ")
