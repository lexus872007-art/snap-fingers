# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Журнал событий человеческими словами (владелец 16.10.2026: «добавь в щелчок журнал событий... должен работать
как швейцарские часы»): на каждый звук - оценка и ПРИЧИНА, почему не сработало; посторонний шум - числом."""
import os

import numpy as np

from conftest import calibrated, run_front
from eval import synth as S
from shchelchok import detector as D
from shchelchok import events, journal


def ev(score=80.0, thr=60.0, ok=True, kind=D.SNAP, reason="", verdict="series"):
    return {"score": score, "thr": thr, "ok": ok, "kind": kind, "reason": reason, "verdict": verdict}


def test_every_refusal_has_a_reason_in_human_words():
    """Каждая причина отказа - понятной строкой, без терминов (список из задачи владельца)."""
    cases = [
        (ev(ok=True, verdict="cooldown"), "ещё идёт пауза после прошлого срабатывания"),
        (ev(ok=False, kind=D.MAYBE, reason="нажали клавишу", verdict="maybe"), "в этот момент печатали"),
        (ev(ok=False, kind=D.MAYBE, reason="щёлкнули мышью", verdict="maybe"), "щёлкнули мышью"),
        (ev(ok=False, kind=D.MAYBE, reason="звук компьютера", verdict="maybe"), "из колонок компьютера"),
        (ev(score=41, thr=55, ok=False, kind=D.MAYBE, reason="не похоже на щелчок"), "41 из 100"),
        (ev(ok=False, kind=D.NOISE, reason="долгий звук"), "слишком долгий"),
        (ev(ok=False, kind=D.NOISE, reason="низкий звук"), "слишком низкий"),
        (ev(ok=False, kind=D.NOISE, reason="нужна настройка"), "не настроен"),
        (ev(ok=True, verdict="started"), "жду второй щелчок"),
        (ev(ok=True, verdict="noise_before"), "посторонний звук"),
        (ev(ok=True, verdict="just_restored"), "только что вернул окна"),
    ]
    for e, part in cases:
        line = events.describe(e)
        assert part in line, (line, part)
        assert "snap" not in line and "maybe" not in line and "noise" not in line, line


def test_score_and_threshold_are_in_the_line():
    assert events.describe(ev(score=41, thr=55, ok=False, kind=D.MAYBE, reason="не похоже на щелчок")) == \
        "41 из 100 · не щелчок: похоже недостаточно (порог 55)"
    assert events.describe(ev(score=88.4)) == "88 из 100 · щелчок - серия собрана"


def test_series_wait_says_how_long():
    assert "до 1 с" in events.describe(ev(verdict="started"), need=2, gap_max=1.0)
    assert "до 0,8 с" in events.describe(ev(verdict="started"), need=2, gap_max=0.8)


def test_wait_line_keeps_the_number_even_if_windows_came_back():
    """Пока строка дойдёт до журнала, окна могут уже вернуться - «жду второй щелчок» не должно превратиться
    в непонятное «жду»: сколько щелчков ждали, записано в самом событии."""
    e = ev(verdict="started")
    e["need"], e["gap_max"] = 2, 1.0
    assert "жду второй щелчок (до 1 с)" in events.describe(e, need=1, gap_max=0.8)


def test_miss_reasons_are_human():
    assert events.MISS["timeout"] == "не дождался второго щелчка"
    assert "посторонний звук" in events.MISS["noise_after"]
    assert events.miss_text("timeout", 1.0) == "не сработало: не дождался второго щелчка (ждал 1 с)"
    assert events.miss_text("timeout", 0.8) == "не сработало: не дождался второго щелчка (ждал 0,8 с)"
    assert events.miss_text("noise_after") == "не сработало: сразу после щелчков был посторонний звук"
    assert events.miss_text("чего-то новенького") is None


def test_noise_goes_to_summary_not_a_line_each(tmp_path):
    """Клавиатура и речь дают десятки ударов в минуту: в журнале они числом раз в две минуты, иначе в нём не
    найти щелчок (а файл ограничен по размеру)."""
    log = events.EventLog()
    assert events.worth_line(ev(ok=True)) is True
    assert events.worth_line(ev(score=50, thr=60, ok=False, kind=D.MAYBE)) is True
    assert events.worth_line(ev(score=12, thr=60, ok=False, kind=D.NOISE)) is False
    for i in range(40):
        assert log.count_noise(now=100.0 + i) is None
    line = log.count_noise(now=100.0 + log.SUM_EVERY + 1)
    assert line == "посторонних звуков за две минуты: 41 (не щелчки)"
    assert log.noise == 0


def test_window_list_newest_first_and_file_gets_the_same(tmp_path):
    journal.set_path(str(tmp_path / "log.txt"))
    log = events.EventLog()
    journal.set_hook(log.push)
    try:
        log.add("первая")
        log.add("вторая")
        assert [s.split("  ", 1)[1] for s in log.lines(5)] == ["вторая", "первая"]
        assert any("вторая" in s for s in journal.tail(5))
    finally:
        journal.set_hook(None)


def test_journal_is_limited_by_the_folder_not_by_cutting_the_file(tmp_path, monkeypatch):
    """Журнал «пишется бесконечно» (владелец 17.10.2026): файл дня никто не режет пополам.

    Прежнее правило (200 КБ на файл, половину отрезаем) ушло вместе с переездом в общий `app_log`:
    теперь ограничение - общий объём папки журналов, и про удаление старых дней остаётся строка."""
    from shchelchok import app_log
    journal.set_path(None)
    folder = app_log.logs_dir(journal.LOG.title)
    big = "x" * 300_000
    journal.write(big)
    journal.write("новая строка")
    day = open(journal.path(), encoding="utf-8").read()
    assert big in day and "новая строка" in day, "файл дня не обрезан"
    # папка разрослась - убираем самые старые дни и ГОВОРИМ об этом строкой
    for i in range(3):
        with open(os.path.join(folder, f"{journal.LOG.app}-2026-09-0{i + 1}.log"), "w", encoding="utf-8") as f:
            f.write("x" * 200_000)
    gone = app_log.trim(folder, journal.LOG.app, max_bytes=250_000)
    assert gone, "самые старые дни убраны"


def test_real_stream_lines_tell_the_story(rng):
    """Настоящий поток: два щелчка подряд при свёрнутых окнах -> в журнале видно «жду второй», «серия собрана»."""
    tpl = calibrated(rng)
    det = D.Detector(template=tpl, sens=5)
    det.set_windows(True)
    bed = S.room(np.random.default_rng(5), 4, 0.003)
    S.place(bed, S.snap(np.random.default_rng(6), centroid=2900, decay_ms=9), 1.0)
    S.place(bed, S.snap(np.random.default_rng(7), centroid=2900, decay_ms=9), 1.4)
    lines, fired = [], []
    a = S.to_int16(bed)
    for i in range(0, len(a), 480):
        evs, fr = det.feed(a[i:i + 480].tolist())
        fired += fr
        for e in evs:
            lines.append(events.describe(e, need=2, gap_max=det.clicker.gaps[1]))
    assert any("жду второй щелчок" in s for s in lines), lines
    assert any("серия собрана" in s for s in lines), lines
    assert [a for _, a in fired] == ["restore"]
