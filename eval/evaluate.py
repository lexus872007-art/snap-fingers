#!/usr/bin/env python3
# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Проверка детектора щелчка на реальных записях (CC0, freesound.org) и синтетике. Сервер 2, numpy - только здесь.

    ../venv/bin/python eval/evaluate.py ~/shchelchok_build/data [--minutes 30] [--sens 5] [--out eval/out]

Распознавание (на «человека» = запись, где >= 4 щелчков):
  калибровка - первые 3 щелчка в тихой комнате (как в окне «Настройка щелчка»), шаблон; затем остальные щелчки
  этой записи по одному каждые 3-4 с на фоне: A - тихая комната, B - шум офиса/кафе, C - разговор в стороне;
  громкость щелчка - как при калибровке, от -6 до +3 дБ. Считается срабатывание одиночного режима.
  Щелчок в записи = любой сильный отдельный удар (на 25 дБ громче фона, 15 дБ тишины перед ним) - без отбора по
  форме, чтобы не подыгрывать детектору.
Ложные срабатывания: 30 мин смеси реальных записей (речь, клавиатура, музыка, мышь, хлопки, стук, прочее) поверх
  фона комнаты; каждый шаблон из распознавания прогоняется по смеси (одиночный, двойной режимы), без защиты от
  клавиатуры и звука компьютера (это дополнительные слои в программе).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import wave
from collections import Counter, defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eval import synth as S  # noqa: E402
from shchelchok import detector as D  # noqa: E402

SR = 16000
BAD_TITLE = ("crack", "knuckle", "reverse", "flanger", "lofi", "layered", "beat", "bpm", "mixdown", "pastry",
             "percussion", "perc_", "magic", "fail", "reverb", "stairway", "clap", "flip", "sfx", "kid ")


def read(path):
    with wave.open(path) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0
    return a


def cands_of(y):
    fe = D.Frontend()
    a = S.to_int16(y)
    out = []
    for i in range(0, len(a), 480):
        out += fe.feed(a[i:i + 480].tolist())
    return out


def db_rms(x):
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)


def norm_rms(x, target_db):
    return x * 10 ** ((target_db - db_rms(x)) / 20)


def norm_peak(x, target_db, q=99.95):
    p = np.percentile(np.abs(x), q) + 1e-9
    return x * (10 ** (target_db / 20) / p)


def bed_from(files, seconds, rms_db, rng):
    """Фон из реальных записей подряд (случайные куски), громкость - rms_db."""
    n = int(seconds * SR)
    out = np.zeros(n)
    i = 0
    while i < n:
        x = read(rng.choice(files))
        if len(x) < SR:
            continue
        st = rng.integers(0, max(1, len(x) - SR))
        seg = x[st:st + min(len(x) - st, n - i)]
        seg = norm_rms(seg, rms_db) if db_rms(seg) > -90 else seg
        k = min(len(seg), n - i)
        fade = min(800, k // 4)
        seg = seg[:k].copy()
        if fade:
            seg[:fade] *= np.linspace(0, 1, fade)
            seg[-fade:] *= np.linspace(1, 0, fade)
        out[i:i + k] += seg
        i += k
    return out


# ---------------------------------------------------------------- щелчки из записей
def snap_events(path, with_times=False):
    """Сильные отдельные удары в записи щелчков -> вырезки [-0,15 с; +0,45 с] (без соседнего удара).
    with_times=True -> (вырезки, времена ВСЕХ таких ударов в записи) - промежутки серий, eval/series.py."""
    x = read(path)
    cs = cands_of(x)
    # щелчок пальцами - высокий звук (по физике щелчка основная энергия 1,5-4 кГц): удары ниже 1,2 кГц в таких
    # записях - шлепки ладони, стук, шорох; форму (нарастание/затухание/сходство) НЕ проверяем
    ev = [c for c in cs if c["snr"] >= 25 and c["pre_gap"] >= 15 and c["peak"] >= -45 and c["centroid"] >= 1200]
    clips = []
    for i, c in enumerate(ev):
        on = int(c["t"] * SR)
        nxt = int(ev[i + 1]["t"] * SR) if i + 1 < len(ev) else len(x)
        a, b = max(0, on - int(0.15 * SR)), min(len(x), on + int(0.45 * SR), nxt - int(0.05 * SR))
        if b - on < int(0.12 * SR):
            continue
        clip = x[a:b].copy()
        f = min(160, (on - a) // 2)
        if f:
            clip[:f] *= np.linspace(0, 1, f)
        clip[-160:] *= np.linspace(1, 0, min(160, len(clip)))
        clips.append((clip, on - a, c["peak"]))
    return (clips, [c["t"] for c in ev]) if with_times else clips


def place_clip(bed, clip, at_s, peak_db, src_peak_db):
    g = 10 ** ((peak_db - src_peak_db) / 20)
    S.place(bed, clip[0], at_s - clip[1] / SR, g)


def calibrate(clips, bed_files, rng, cal_peak):
    """Как окно «Настройка щелчка»: 3 щелчка в тихой комнате -> шаблон (или None)."""
    bed = bed_from(bed_files, 3 + 1.4 * len(clips), -55, rng) if bed_files else S.room(rng, 3 + 1.4 * len(clips), 0.0018)
    for k, cl in enumerate(clips):
        place_clip(bed, cl, 1.5 + 1.4 * k, cal_peak, cl[2])
    got = []
    for c in cands_of(bed):
        if not D.gates(c, strict=False) and c["snr"] >= 15:
            got.append(c)
    if len(got) < 3:
        return None, f"услышал {len(got)} из 3"
    ok, why = D.calib_consistent(got[:3])
    return (D.make_template(got[:3]), "") if ok else (None, why)


def prepare_positive(groups, beds, rng, conds=("A", "B", "C")):
    """Потоки для проверки распознавания (шаблон не меняется - потоки считаются один раз)."""
    out = []
    for name, clips in groups:
        cal_peak = rng.uniform(-18, -8)
        tpl, why, test = None, "", []
        for start in range(0, min(3, len(clips) - 3)):              # не вышло - «Заново» (до 3 попыток)
            tpl, why = calibrate(clips[start:start + 3], beds["quiet"], rng, cal_peak)
            if tpl:
                test = clips[:start] + clips[start + 3:]
                break
        g = {"name": name, "tpl": tpl, "why": why, "conds": {}, "double": None}
        out.append(g)
        if not tpl:
            continue
        for cond in conds:
            n = len(test)
            dur = 2 + 3.5 * n
            if cond == "A":
                bed = bed_from(beds["quiet"], dur, -55, rng)
            elif cond == "B":
                bed = bed_from(beds["office"], dur, -42, rng)
            else:
                bed = bed_from(beds["quiet"], dur, -55, rng) + bed_from(beds["speech"], dur, -36, rng)
            times = []
            for k, cl in enumerate(test):
                at = 1.5 + 3.5 * k + rng.uniform(-0.3, 0.3)
                place_clip(bed, cl, at, cal_peak + rng.uniform(-6, 3), cl[2])
                times.append(at)
            g["conds"][cond] = (cands_of(bed), times)
        if len(test) >= 2:
            bed = bed_from(beds["quiet"], 2 + 3.5 * len(test), -55, rng)
            times = []
            for k in range(0, len(test) - 1, 2):
                at = 1.5 + 3.5 * k
                gap = rng.uniform(0.25, 0.6)
                place_clip(bed, test[k], at, cal_peak + rng.uniform(-4, 2), test[k][2])
                place_clip(bed, test[k + 1], at + gap, cal_peak + rng.uniform(-4, 2), test[k + 1][2])
                times.append(at)
            g["double"] = (cands_of(bed), times)
    return out


def score_positive(prep, sens):
    res = {c: [0, 0] for c in ("A", "B", "C")}
    res2 = [0, 0]
    reasons = Counter()
    cal_fail = Counter(g["why"] for g in prep if not g["tpl"])
    per_group = []
    for g in prep:
        if not g["tpl"]:
            per_group.append((g["name"], None, g["why"]))
            continue
        row = {}
        for cond, (cs, times) in g["conds"].items():
            fired, ev = D.simulate(cs, g["tpl"], sens=sens, mode=1)
            hit = sum(1 for t in times if any(t - 0.05 <= f <= t + 1.0 for f in fired))
            for e in ev:
                if any(abs(e["t"] - t) < 0.03 for t in times):
                    reasons[(cond, e["reason"] or "ok")] += 1
            res[cond][0] += hit
            res[cond][1] += len(times)
            row[cond] = (hit, len(times))
        if g["double"]:
            cs, times = g["double"]
            fired, _ = D.simulate(cs, g["tpl"], sens=sens, mode=2)
            res2[0] += sum(1 for t in times if any(t <= f <= t + 1.8 for f in fired))
            res2[1] += len(times)
        per_group.append((g["name"], row, ""))
    return res, res2, cal_fail, per_group, reasons


def beds_of(data, classes):
    import csv
    import glob
    query = {}
    for src in glob.glob(os.path.join(data, "sources*.csv")):
        for r in csv.DictReader(open(src, encoding="utf-8")):
            query[r["id"]] = r["query"]
    amb = classes.get("ambience", [])
    quiet = [f for f in amb if query.get(os.path.basename(f)[:-4]) in ("room tone", "computer fan")] or amb
    office = [f for f in amb if f not in quiet] or amb
    return {"quiet": quiet, "office": office, "speech": classes.get("speech", [])}


# ---------------------------------------------------------------- смесь без щелчков
MIX_PLAN = [("speech", 0.30), ("keyboard", 0.20), ("music", 0.20), ("mouse", 0.07), ("clap", 0.09),
            ("knock", 0.07), ("other", 0.07)]


def build_mix(classes, beds, minutes, rng):
    total = minutes * 60
    y = bed_from(beds["quiet"], total, -52, rng)
    labels = []
    t = 0.0
    order = []
    for cls, frac in MIX_PLAN:
        if classes.get(cls):
            order += [cls] * int(round(frac * 100))
    while t < total - 2:
        cls = rng.choice(order)
        x = read(rng.choice(classes[cls]))
        if len(x) < SR // 4 or db_rms(x) < -80:
            continue
        seg_len = min(len(x), int(rng.uniform(8, 40) * SR))
        st = rng.integers(0, max(1, len(x) - seg_len))
        seg = x[st:st + seg_len].copy()
        if cls == "speech":
            seg = norm_rms(seg, rng.uniform(-32, -22))
        elif cls == "music":
            seg = norm_rms(seg, rng.uniform(-34, -24))
        elif cls == "keyboard":
            seg = norm_peak(seg, rng.uniform(-12, -4))
        elif cls == "mouse":
            seg = norm_peak(seg, rng.uniform(-20, -8))
        else:
            seg = norm_peak(seg, rng.uniform(-14, -3))
        k = min(len(seg), int((total - t) * SR))
        i = int(t * SR)
        y[i:i + k] += seg[:k]
        labels.append((t, t + k / SR, cls))
        t += k / SR + rng.uniform(0.3, 3.0)
    return y, labels


def label_at(labels, t):
    for a, b, c in labels:
        if a - 0.05 <= t <= b + 0.3:
            return c
    return "фон"


def synth_groups(rng, n=20, per=10):
    groups = []
    for g in range(n):
        cen = rng.uniform(1900, 4200)
        dec = rng.uniform(4, 16)
        clips = []
        for k in range(per):
            y = np.concatenate([np.zeros(int(0.15 * SR)), S.snap(rng, centroid=cen * rng.uniform(0.92, 1.08),
                                                                 decay_ms=dec * rng.uniform(0.8, 1.25)),
                                np.zeros(int(0.37 * SR))])
            clips.append((y, int(0.15 * SR), 20 * np.log10(np.abs(y).max())))
        groups.append((f"синт-{g + 1}", clips))
    return groups


def synth_mix(rng, minutes):
    total = minutes * 60
    y = S.room(rng, total, 0.0025)
    t = 1.0
    labels = []
    while t < total - 15:
        kind = rng.choice(["speech", "music", "keys", "claps", "knocks", "mouse"], p=[.3, .2, .2, .1, .1, .1])
        if kind in ("speech", "music"):
            d = rng.uniform(8, 30)
            seg = (S.speech if kind == "speech" else S.music)(rng, d, 10 ** (rng.uniform(-32, -22) / 20))
            S.place(y, seg, t)
        else:
            d = rng.uniform(5, 15)
            fn = {"keys": S.key, "claps": S.clap, "knocks": S.knock, "mouse": S.mouse}[kind]
            tt = t
            while tt < t + d:
                S.place(y, fn(rng, peak=10 ** (rng.uniform(-14, -3) / 20)), tt)
                tt += rng.uniform(0.15, 0.6) if kind == "keys" else rng.uniform(0.8, 4)
        labels.append((t, t + d, kind))
        t += d + rng.uniform(0.3, 2)
    return y, labels


def main():
    import pickle
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--sens", type=int, default=5)
    ap.add_argument("--out", default=os.path.join(ROOT, "eval", "out"))
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    cache = os.path.join(a.out, "cache.pkl")
    if not os.path.exists(cache):
        from eval import tune
        pickle.dump(tune.build(a.data, np.random.default_rng(a.seed)), open(cache, "wb"))
    st = pickle.load(open(cache, "rb"))
    prep, mix_c, labels = st["pos"], st["mix"], st["labels"]
    templates = [(g["name"], g["tpl"]) for g in prep if g["tpl"]]
    res, res2, cal_fail, per_group, reasons = score_positive(prep, a.sens)
    fa1, fa2, by_cls, fa_items = [], [], Counter(), []
    for name, tpl in templates:
        f1, ev = D.simulate(mix_c, tpl, sens=a.sens, mode=1)
        f2, _ = D.simulate(mix_c, tpl, sens=a.sens, mode=2)
        fa1.append(len(f1))
        fa2.append(len(f2))
        for t in f1:
            cls = label_at(labels, t - 0.43)
            by_cls[cls] += 1
            fa_items.append((name, round(t, 2), cls))
    sens_rows = []
    for sv in (2, 3, 5, 7, 9, 10):
        r, r2, _, _, _ = score_positive(prep, sv)
        f = [len(D.simulate(mix_c, tpl, sens=sv, mode=1)[0]) for _, tpl in templates]
        f2 = [len(D.simulate(mix_c, tpl, sens=sv, mode=2)[0]) for _, tpl in templates]
        sens_rows.append((sv, {k: round(100 * v[0] / max(1, v[1]), 1) for k, v in r.items()},
                          round(float(np.mean(f)), 2), int(max(f)),
                          round(100 * r2[0] / max(1, r2[1]), 1), round(float(np.mean(f2)), 2), int(max(f2))))
        print("чувствительность", sens_rows[-1], flush=True)
    # синтетика
    srng = np.random.default_rng(a.seed + 1)
    wav = os.path.join(a.data, "wav")
    classes = {c: [os.path.join(wav, c, f) for f in sorted(os.listdir(os.path.join(wav, c)))] for c in os.listdir(wav)}
    beds = beds_of(a.data, classes)
    sprep = prepare_positive(synth_groups(srng), beds, srng)
    sres, sres2, scal, _, _ = score_positive(sprep, a.sens)
    sy, _ = synth_mix(srng, 30)
    sc = cands_of(sy)
    sfa = [len(D.simulate(sc, g["tpl"], sens=a.sens, mode=1)[0]) for g in sprep if g["tpl"]]
    mix_min = sum(b - t for t, b, _ in labels) / 60
    out = {"groups": len(prep), "templates": len(templates), "cal_fail": dict(cal_fail), "detect": res,
           "detect_double": res2, "reasons": {f"{k[0]}:{k[1]}": v for k, v in reasons.most_common()},
           "mix_cands": len(mix_c), "mix_sound_minutes": round(mix_min, 1), "fa_single": fa1, "fa_double": fa2,
           "fa_by_class": dict(by_cls), "fa_items": fa_items, "sens_rows": sens_rows,
           "mix_labels": dict(Counter(c for _, _, c in labels)),
           "synth": {"detect": sres, "detect_double": sres2, "cal_fail": dict(scal), "fa_single": sfa},
           "per_group": per_group,
           "params": {"SIG_BAND": D.SIG_BAND, "SIG_DEC": D.SIG_DEC, "A_DEC": D.A_DEC, "D_SCALE": D.D_SCALE,
                      "THR_BASE": D.THR_BASE, "REL_DB": D.REL_DB}}
    json.dump(out, open(os.path.join(a.out, "results.json"), "w"), ensure_ascii=False, indent=1, default=str)
    pct = lambda h: f"{100 * h[0] / max(1, h[1]):.1f} % ({h[0]}/{h[1]})"   # noqa: E731
    print(f"«людей» {len(prep)}, шаблонов {len(templates)}, калибровка не вышла {dict(cal_fail)}")
    for c in res:
        print("распознавание", c, pct(res[c]))
    print("двойной", pct(res2))
    print(f"ложные (одиночный) на 30 мин: среднее {np.mean(fa1):.2f}, макс {max(fa1)}, шаблонов {len(fa1)}; "
          f"двойной: среднее {np.mean(fa2):.2f}, макс {max(fa2)}")
    print("ложные по классам", dict(by_cls))
    print("причины", reasons.most_common(12))
    print("чувствительность", sens_rows)
    print("синтетика", {k: pct(v) for k, v in sres.items()}, "двойной", pct(sres2), "ложные", sfa, "кал", dict(scal))


if __name__ == "__main__":
    main()
