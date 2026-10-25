"""Синтетические звуки для тестов и проверки детектора (numpy, 16 кГц, float -1..1).

Похоже на настоящие по главным признакам (так их и различает детектор):
- щелчок пальцами: удар < 1 мс, затухание 5-20 мс, энергия в 1,5-5 кГц (резонансы), чуть низкого «шлепка»;
- хлопок: шире полоса и ниже (0,6-2,5 кГц), затухание 25-60 мс + отзвук комнаты;
- клавиша: нажатие + отпускание через 60-160 мс, высокий щелчок + низкий стук корпуса;
- мышь: два коротких щелчка (нажать/отпустить) через 60-120 мс;
- стук по столу: 120-500 Гц, затухание 60-150 мс;
- речь: слоги 120-300 мс (основной тон 90-250 Гц, форманты), шипящие, паузы;
- музыка: аккорды + ударные (бочка, малый барабан, хай-хэт) в ритме.
"""
from __future__ import annotations

import numpy as np

SR = 16000


def _bp_noise(rng, n, lo, hi):
    """Белый шум в полосе lo-hi Гц (через БПФ)."""
    x = rng.standard_normal(n)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    X[(f < lo) | (f > hi)] = 0
    y = np.fft.irfft(X, n)
    return y / (np.abs(y).max() + 1e-9)


def _res(rng, n, freqs, decay_s, amps=None):
    t = np.arange(n) / SR
    out = np.zeros(n)
    for i, fr in enumerate(freqs):
        a = 1.0 if amps is None else amps[i]
        out += a * np.sin(2 * np.pi * fr * t + rng.uniform(0, 6.28)) * np.exp(-t / decay_s)
    return out


def snap(rng, centroid=None, decay_ms=None, peak=0.5):
    """Щелчок пальцами: ~60 мс."""
    n = int(0.08 * SR)
    t = np.arange(n) / SR
    c = centroid or rng.uniform(2200, 3600)
    d = (decay_ms or rng.uniform(5, 14)) / 1000
    burst = _bp_noise(rng, n, c * 0.55, min(7800, c * 1.9)) * np.exp(-t / d)
    ring = _res(rng, n, [c * rng.uniform(0.85, 1.15), c * rng.uniform(1.3, 1.6)], d * 0.8, [0.5, 0.3])
    thump = _res(rng, n, [rng.uniform(250, 450)], 0.006, [0.06])
    y = burst + ring + thump
    att = int(rng.uniform(0.0002, 0.0008) * SR) + 1
    y[:att] *= np.linspace(0, 1, att)
    return y / np.abs(y).max() * peak


def clap(rng, peak=0.6):
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    d = rng.uniform(0.012, 0.03)
    y = _bp_noise(rng, n, rng.uniform(400, 700), rng.uniform(2200, 3200)) * np.exp(-t / d)
    y += 0.25 * _bp_noise(rng, n, 300, 4000) * np.exp(-t / rng.uniform(0.05, 0.09))      # отзвук
    att = int(rng.uniform(0.001, 0.003) * SR)
    y[:att] *= np.linspace(0, 1, att)
    return y / np.abs(y).max() * peak


def key(rng, peak=0.4):
    """Нажатие+отпускание клавиши."""
    gap = rng.uniform(0.06, 0.16)
    n = int((gap + 0.06) * SR)
    y = np.zeros(n)
    for k, (at, a) in enumerate(((0.0, 1.0), (gap, rng.uniform(0.4, 0.9)))):
        m = int(0.04 * SR)
        t = np.arange(m) / SR
        c = rng.uniform(2500, 6000)
        s = _bp_noise(rng, m, c * 0.5, min(7800, c * 1.5)) * np.exp(-t / rng.uniform(0.002, 0.006))
        s += _res(rng, m, [rng.uniform(150, 400)], 0.01, [rng.uniform(0.3, 1.0)])
        i = int(at * SR)
        y[i:i + m] += a * s
    return y / np.abs(y).max() * peak


def mouse(rng, peak=0.3):
    gap = rng.uniform(0.06, 0.12)
    n = int((gap + 0.03) * SR)
    y = np.zeros(n)
    for at in (0.0, gap):
        m = int(0.02 * SR)
        t = np.arange(m) / SR
        s = _bp_noise(rng, m, 1500, 6000) * np.exp(-t / 0.002)
        i = int(at * SR)
        y[i:i + m] += s
    return y / np.abs(y).max() * peak


def knock(rng, peak=0.6):
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    y = _res(rng, n, [rng.uniform(120, 250), rng.uniform(300, 500)], rng.uniform(0.04, 0.1), [1, 0.5])
    y += 0.3 * _bp_noise(rng, n, 500, 3000) * np.exp(-t / 0.003)
    return y / np.abs(y).max() * peak


def speech(rng, seconds, rms=0.05):
    """Речь-подобный сигнал: слоги с формантами и шипящими, паузы между словами/фразами."""
    n = int(seconds * SR)
    y = np.zeros(n)
    i = 0
    f0 = rng.uniform(95, 220)
    while i < n:
        syl = int(rng.uniform(0.12, 0.3) * SR)
        if i + syl >= n:
            break
        t = np.arange(syl) / SR
        f = f0 * (1 + 0.1 * np.sin(2 * np.pi * rng.uniform(1, 4) * t))
        ph = 2 * np.pi * np.cumsum(f) / SR
        v = np.zeros(syl)
        for h in range(1, 30):
            fh = f0 * h
            if fh > 7500:
                break
            amp = sum(np.exp(-((fh - F) / bw) ** 2) for F, bw in ((rng.uniform(300, 800), 120),
                                                                  (rng.uniform(900, 2200), 200),
                                                                  (rng.uniform(2400, 3200), 300)))
            v += (amp + 0.02) * np.sin(h * ph)
        env = np.sin(np.pi * np.arange(syl) / syl) ** 0.6
        seg = v * env
        if rng.random() < 0.35:                  # шипящая/взрывная
            m = int(rng.uniform(0.03, 0.12) * SR)
            fr = _bp_noise(rng, m, rng.uniform(2500, 4000), 7800) * np.hanning(m) * rng.uniform(0.2, 0.6)
            seg = np.concatenate([fr * np.abs(seg).max(), seg])
        seg = seg[:n - i]
        y[i:i + len(seg)] += seg
        i += len(seg)
        r = rng.random()
        i += int((0.02 if r < 0.6 else rng.uniform(0.15, 0.4) if r < 0.9 else rng.uniform(0.5, 1.2)) * SR)
    return y / (np.sqrt(np.mean(y ** 2)) + 1e-9) * rms


def music(rng, seconds, rms=0.05):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    y = np.zeros(n)
    bpm = rng.uniform(80, 140)
    beat = 60 / bpm
    root = rng.choice([110, 130.8, 146.8, 164.8, 196])
    for k, start in enumerate(np.arange(0, seconds, beat * 4)):
        i0, i1 = int(start * SR), min(n, int((start + beat * 4) * SR))
        tt = t[i0:i1] - start
        for mul in (1, 1.25, 1.5, 2):
            y[i0:i1] += 0.2 * np.sin(2 * np.pi * root * mul * (1 + 0.003 * k) * tt) * np.exp(-tt / 2)
    for b in np.arange(0, seconds, beat / 2):
        i = int(b * SR)
        m = min(int(0.2 * SR), n - i)
        if m <= 0:
            break
        tt = np.arange(m) / SR
        beat_i = int(round(b / (beat / 2)))
        if beat_i % 4 == 0:
            y[i:i + m] += 0.8 * np.sin(2 * np.pi * 60 * tt) * np.exp(-tt / 0.08)
        elif beat_i % 4 == 2:
            y[i:i + m] += 0.5 * _bp_noise(rng, m, 300, 5000) * np.exp(-tt / 0.06)
        y[i:i + m] += 0.15 * _bp_noise(rng, m, 5000, 7900) * np.exp(-tt / 0.02)
    return y / (np.sqrt(np.mean(y ** 2)) + 1e-9) * rms


def room(rng, seconds, rms=0.002):
    """Тихая комната/вентилятор: розоватый шум."""
    n = int(seconds * SR)
    x = rng.standard_normal(n)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    X /= np.maximum(f, 50) ** 0.5
    y = np.fft.irfft(X, n)
    return y / (np.sqrt(np.mean(y ** 2)) + 1e-9) * rms


def place(base, clip, at_s, gain=1.0):
    i = int(at_s * SR)
    m = min(len(clip), len(base) - i)
    if m > 0:
        base[i:i + m] += clip[:m] * gain
    return base


def to_int16(y):
    return np.clip(np.round(y * 32767), -32768, 32767).astype(np.int16)
