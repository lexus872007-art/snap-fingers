# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Детектор: признаки удара, шаблон, оценка, отличие щелчка от хлопка/клавиш/стука/речи/музыки (синтетика)."""
import math

import numpy as np
import pytest

from conftest import calibrated, run_front
from eval import synth as S
from shchelchok import detector as D


def test_fft_matches_sine():
    n = 128
    x = [math.sin(2 * math.pi * 16 * i / n) for i in range(n)]
    sp = D.fft(x)
    mags = [abs(c) for c in sp[:n // 2]]
    assert mags.index(max(mags)) == 16


def test_snap_features(rng):
    bed = S.room(rng, 3, 0.002)
    S.place(bed, S.snap(rng, centroid=3000, decay_ms=8), 1.0)
    cs = run_front(bed)
    assert len(cs) == 1
    c = cs[0]
    assert abs(c["t"] - 1.0) < 0.01
    assert c["rise"] <= 3 and c["decay"] < 40
    assert 1800 < c["centroid"] < 4500
    assert c["low"] < 0 and c["pre_gap"] > 20 and c["post_gap"] > 20
    assert D.gates(c) is None


def test_clap_knock_long_rejected_by_gates(rng):
    for fn, why in ((S.knock, "низкий звук"),):
        bed = S.room(rng, 3, 0.002)
        S.place(bed, fn(rng), 1.0)
        c = run_front(bed)[0]
        assert D.gates(c) is not None


def test_speech_never_passes(rng):
    y = S.speech(rng, 60, 0.05) + S.room(rng, 60, 0.002)
    tpl = calibrated(np.random.default_rng(1))
    fired, ev = D.simulate(run_front(y), tpl)
    assert fired == []


def test_music_never_passes(rng):
    y = S.music(rng, 60, 0.05) + S.room(rng, 60, 0.002)
    tpl = calibrated(np.random.default_rng(1))
    fired, _ = D.simulate(run_front(y), tpl)
    assert fired == []


@pytest.mark.parametrize("kind", ["clap", "key", "mouse", "knock"])
def test_other_impulses_not_snaps(rng, kind):
    tpl = calibrated(np.random.default_rng(1))
    fn = getattr(S, kind)
    bed = S.room(rng, 2 + 2.5 * 30, 0.003)
    for k in range(30):
        S.place(bed, fn(rng), 1 + 2.5 * k)
    fired, _ = D.simulate(run_front(bed), tpl)
    assert len(fired) <= 1, kind


def test_own_snaps_detected(rng):
    tpl = calibrated(np.random.default_rng(1), centroid=2900)
    bed = S.room(rng, 2 + 3 * 30, 0.003)
    for k in range(30):
        S.place(bed, S.snap(rng, centroid=2900 * rng.uniform(0.92, 1.08), decay_ms=9 * rng.uniform(0.8, 1.2),
                            peak=rng.uniform(0.2, 0.6)), 1 + 3 * k)
    fired, _ = D.simulate(run_front(bed), tpl)
    assert len(fired) >= 27


def test_template_scores_own_higher_than_foreign(rng):
    tpl = calibrated(np.random.default_rng(1), centroid=2600)
    own, other = [], []
    for k in range(10):
        for cen, lst in ((2600, own), (5200, other)):
            bed = S.room(rng, 1.5, 0.002)
            S.place(bed, S.snap(rng, centroid=cen, decay_ms=9), 0.6)
            c = run_front(bed)[0]
            lst.append(D.score(c, tpl)[0])
    assert np.median(own) > np.median(other) + 20


def test_calibration_inconsistent(rng):
    bed = S.room(rng, 7, 0.003)
    for k, cen in enumerate((2000, 4800, 3000)):
        S.place(bed, S.snap(rng, centroid=cen, decay_ms=6 if k != 1 else 16), 1.5 + 1.5 * k)
    got = [c for c in run_front(bed) if not D.gates(c, strict=False)]
    ok, why = D.calib_consistent(got)
    assert not ok and why == "щелчки разные"


def test_calibration_too_quiet(rng):
    bed = S.room(rng, 7, 0.01)
    for k in range(3):
        S.place(bed, S.snap(rng, centroid=3000, decay_ms=9, peak=0.06), 1.5 + 1.5 * k)
    got = [c for c in run_front(bed) if not D.gates(c, strict=False)]
    ok, why = D.calib_consistent(got)
    assert not ok


def test_threshold_and_sensitivity(rng):
    assert D.threshold(1) > D.threshold(5) > D.threshold(10)
    tpl = calibrated(np.random.default_rng(1))
    bed = S.room(rng, 2, 0.002)
    S.place(bed, S.snap(rng, centroid=2900, decay_ms=9, peak=0.02), 1.0)     # намного тише калибровки
    c = run_front(bed)[0]
    assert D.score(c, tpl, sens=10)[0] >= D.score(c, tpl, sens=1)[0]


def test_no_template_no_trigger(rng):
    bed = S.room(rng, 3, 0.002)
    S.place(bed, S.snap(rng), 1.0)
    fired, ev = D.simulate(run_front(bed), None)
    assert fired == [] and ev[0]["reason"] == "нужна настройка"


def test_ring_buffer_bounded(rng):
    fe = D.Frontend()
    a = S.to_int16(S.room(rng, 20, 0.003))
    for i in range(0, len(a), 480):
        fe.feed(a[i:i + 480].tolist())
    assert len(fe.raw) <= 2 * 600 * D.FR and len(fe.env) <= 1200     # звук не копится - только ~0,5 с


def test_detector_stream_equals_simulate(rng):
    tpl = calibrated(np.random.default_rng(1))
    bed = S.room(rng, 20, 0.003)
    for k in range(5):
        S.place(bed, S.snap(rng, centroid=2900, decay_ms=9), 1 + 3.5 * k)
    S.place(bed, S.key(rng), 18.5)
    det = D.Detector(template=tpl)
    a = S.to_int16(bed)
    fired = []
    for i in range(0, len(a), 480):
        fired += det.feed(a[i:i + 480].tolist())[1]
    sim, _ = D.simulate(run_front(bed), tpl)
    assert len(fired) == len(sim) == 5
    assert all(a == "hide" for _, a in fired)
    for (x, _), y in zip(fired, sim):
        assert abs(x - y) < 0.05


def _stream(bed, tpl, hidden, back_n=2):
    det = D.Detector(template=tpl)
    det.set_windows(hidden, back_n)
    a = S.to_int16(bed)
    out = []
    for i in range(0, len(a), 480):
        out += det.feed(a[i:i + 480].tolist())[1]
    return out


def series_bed(rng, gap):
    bed = S.room(rng, 8, 0.003)
    for k in range(3):
        S.place(bed, S.snap(rng, centroid=2900, decay_ms=9), 2.0 + gap * k)
    return bed


@pytest.mark.parametrize("gap", [0.25, 0.4, 0.6])
def test_stream_two_snaps_restore_when_hidden(rng, gap):
    """Жест владельца (16.10.2026): окна свёрнуты, ДВА щелчка подряд в звуке - окна возвращаются."""
    tpl = calibrated(np.random.default_rng(1))
    bed = S.room(rng, 8, 0.003)
    for k in range(2):
        S.place(bed, S.snap(rng, centroid=2900, decay_ms=9), 2.0 + gap * k)
    assert [a for _, a in _stream(bed, tpl, hidden=True)] == ["restore"]


@pytest.mark.parametrize("gap", [0.25, 0.4, 0.6])
def test_stream_three_snaps_restore_when_hidden(rng, gap):
    """Весь путь (звук -> признаки -> оценка -> решение): щёлкнули ТРИ раза (не вышло с первого) - окна всё
    равно возвращаются ровно один раз, лишний щелчок серию не отменяет."""
    tpl = calibrated(np.random.default_rng(1))
    assert [a for _, a in _stream(series_bed(rng, gap), tpl, hidden=True)] == ["restore"]


def test_stream_series_when_windows_shown(rng):
    """Окна на месте: быстрая серия (щелчки через 0,25 с) не сворачивает ничего - второй щелчок отменяет решение;
    серия пореже - сворачивает по первому щелчку (как обычный одиночный), остальные щелчки попадают в паузу."""
    tpl = calibrated(np.random.default_rng(1))
    assert [a for _, a in _stream(series_bed(rng, 0.25), tpl, hidden=False)] == []
    assert [a for _, a in _stream(series_bed(rng, 0.4), tpl, hidden=False)] == ["hide"]


def test_stream_single_snap_does_not_restore(rng):
    tpl = calibrated(np.random.default_rng(1))
    bed = S.room(rng, 8, 0.003)
    S.place(bed, S.snap(rng, centroid=2900, decay_ms=9), 2.0)
    assert _stream(bed, tpl, hidden=True) == []
    assert [a for _, a in _stream(bed, tpl, hidden=True, back_n=1)] == ["restore"]
    assert [a for _, a in _stream(bed, tpl, hidden=False)] == ["hide"]
