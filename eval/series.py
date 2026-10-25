#!/usr/bin/env python3
"""Метрики ВОЗВРАТА окон серией щелчков (detector.RESTORE_N: с 16.10.2026 - ДВА щелчка, до этого три) на тех же
записях (CC0), что и остальная таблица README. Сервер 2.

    ../venv/bin/python eval/series.py ~/shchelchok_build/data [--sens 5] [--out eval/out] [--rebuild]

1. Промежутки между щелчками в настоящих записях (сколько времени у людей между щелчками серии) - по ним выбрано
   окно серии возврата: соседние щелчки detector.BACK_GAP, вся серия не длиннее detector.BACK_SPAN.
2. Распознавание серии: шаблоны те же (из cache.pkl, 41 «человек»), серии из RESTORE_N щелчков этого же «человека»
   с промежутками 0,25-0,6 с, по одной серии каждые 4 с; A - тихая комната, B - шум офиса. Режим «окна свёрнуты»,
   галочка «одиночный тоже возвращает» выключена.
3. Ложные: ТА ЖЕ 30-минутная смесь (речь/клавиатура/музыка/хлопки/стук/мышь/прочее) - сколько раз окна вернулись бы
   сами; для сравнения - то же с включённой галочкой (там работает одиночный щелчок).
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
from shchelchok import detector as D  # noqa: E402

GAP = (0.25, 0.6)          # так щёлкают серию (медиана промежутков в записях - см. пункт 1)
EVERY = 4.0                # одна серия каждые 4 с
MAX_SERIES = 5


def file_series_data(path):
    """Вырезки щелчков и промежутки между щелчками в одной записи."""
    clips, times = E.snap_events(path, with_times=True)
    d = [b - a for a, b in zip(times, times[1:])]
    gaps = [v for v in d if v < 2.5]
    n = D.RESTORE_N
    spans = [times[i + n - 1] - times[i] for i in range(len(times) - n + 1)
             if all(d[i + j] < 2.5 for j in range(n - 1))]
    return clips, gaps, spans


def build(data, groups, rng):
    """groups: [(имя записи, шаблон)] -> потоки кандидатов с сериями + промежутки из записей."""
    wav = os.path.join(data, "wav")
    classes = {c: [os.path.join(wav, c, f) for f in sorted(os.listdir(os.path.join(wav, c)))]
               for c in os.listdir(wav)}
    beds = E.beds_of(data, classes)
    gaps_all, spans_all, streams = [], [], {}
    for name, tpl in groups:
        path = os.path.join(wav, "snap", name + ".wav")
        if not os.path.exists(path):
            continue
        clips, gaps, spans = file_series_data(path)
        gaps_all += gaps
        spans_all += spans
        test = clips[3:]                                  # первые 3 - калибровка (как в остальной таблице)
        per = D.RESTORE_N                                 # щелчков в серии (сколько нужно для возврата)
        n_ser = min(MAX_SERIES, len(test) // per)
        if n_ser < 1:
            continue
        ref = tpl.get("peak_mean", tpl["peak_min"])
        streams[name] = {}
        for cond in ("A", "B"):
            dur = 2 + EVERY * n_ser
            bed = (E.bed_from(beds["quiet"], dur, -55, rng) if cond == "A"
                   else E.bed_from(beds["office"], dur, -42, rng))
            times = []
            for k in range(n_ser):
                at = 1.5 + EVERY * k
                t = at
                for j in range(per):
                    cl = test[per * k + j]
                    E.place_clip(bed, cl, t, ref + rng.uniform(-4, 2), cl[2])
                    t += rng.uniform(*GAP)
                times.append(at)
            streams[name][cond] = (E.cands_of(bed), times)
        print("серии", name, n_ser, flush=True)
    return {"streams": streams, "gaps": gaps_all, "spans": spans_all}


def score(streams, groups, mix, sens):
    """-> (распознано A, распознано B, ложные по шаблонам, ложные с галочкой)."""
    res = {"A": [0, 0], "B": [0, 0]}
    for name, tpl in groups:
        for cond, (cs, times) in streams.get(name, {}).items():
            fired, _ = D.simulate(cs, tpl, sens=sens, hidden=True)
            res[cond][0] += sum(1 for t in times if any(t <= f <= t + 2.6 for f in fired))
            res[cond][1] += len(times)
    fa = [len(D.simulate(mix, tpl, sens=sens, hidden=True)[0]) for _, tpl in groups]
    fa1 = [len(D.simulate(mix, tpl, sens=sens, hidden=True, single_restores=True)[0]) for _, tpl in groups]
    return res, fa, fa1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--sens", type=int, default=5)
    ap.add_argument("--out", default=os.path.join(ROOT, "eval", "out"))
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    st = pickle.load(open(os.path.join(a.out, "cache.pkl"), "rb"))
    groups = [(g["name"], g["tpl"]) for g in st["pos"] if g["tpl"]]
    mix = st["mix"]
    cache = os.path.join(a.out, "series_cache.pkl")
    if a.rebuild or not os.path.exists(cache):
        pickle.dump(build(a.data, groups, np.random.default_rng(a.seed)), open(cache, "wb"))
    ser = pickle.load(open(cache, "rb"))
    streams = ser["streams"]
    gaps, spans = np.array(ser["gaps"]), np.array(ser["spans"])
    win = D.series_window()
    lo_g, hi_g = D.BACK_GAP                      # окно промежутка берём из кода, а не руками
    inside = float(np.mean((gaps >= lo_g) & (gaps <= hi_g))) if len(gaps) else 0.0
    span_ok = {s: float(np.mean(spans <= s)) for s in (1.2, 1.4, 1.5, 1.6, 2.0)} if len(spans) else {}
    rows = []
    for sv in (2, 3, 5, 7, 9):
        res, fa, fa1 = score(streams, groups, mix, sv)
        rows.append((sv, round(100 * res["A"][0] / max(1, res["A"][1]), 1),
                     round(100 * res["B"][0] / max(1, res["B"][1]), 1),
                     round(float(np.mean(fa)), 2), int(max(fa)), res["A"][1],
                     round(float(np.mean(fa1)), 2), int(max(fa1))))
        print("серия, чувствительность", rows[-1], flush=True)
    out = {"window": win, "gaps_n": int(len(gaps)), "gap_pct": {str(p): round(float(np.percentile(gaps, p)), 2)
                                                                for p in (10, 25, 50, 75, 90)} if len(gaps) else {},
           "gaps_inside_window": round(inside, 3), "spans_n": int(len(spans)),
           "span_within": {str(k): round(v, 3) for k, v in span_ok.items()},
           "templates": len(groups), "rows": rows, "gap_used": GAP}
    json.dump(out, open(os.path.join(a.out, "series.json"), "w"), ensure_ascii=False, indent=1, default=str)
    print("окно серии", win, "промежутки в записях", out["gap_pct"], "в окне", f"{100 * inside:.0f} %")
    print(f"серии из {D.RESTORE_N} в записях укладываются:", out["span_within"], "всего серий", len(spans))


if __name__ == "__main__":
    main()
