# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Звук самого компьютера: удар в выводе в момент «щелчка» -> не щелчок; ровная музыка не мешает."""
from shchelchok.syscom import output_hit


def hist(f, t0=0.0, t1=3.0):
    out, t = [], t0
    while t < t1:
        out.append((t, f(t)))
        t += 0.01
    return out


def test_silence_no_hit():
    assert not output_hit(hist(lambda t: 0.0), 2.0)


def test_steady_music_no_hit():
    assert not output_hit(hist(lambda t: 0.3), 2.0)


def test_drum_hit_in_output():
    h = hist(lambda t: 0.9 if 1.95 <= t <= 1.98 else 0.1)
    assert output_hit(h, 2.0)


def test_hit_far_away_ignored():
    h = hist(lambda t: 0.9 if 1.0 <= t <= 1.03 else 0.05)
    assert not output_hit(h, 2.5)


def test_quiet_output_ignored():
    h = hist(lambda t: 0.02 if 1.95 <= t <= 1.98 else 0.001)
    assert not output_hit(h, 2.0)
