"""Настройка под человека: несколько образцов щелчка, порог числом, «Подобрать под меня», дообучение.

Жалоба владельца 16.10.2026 по его журналу: щелчки получали 27-70 при пороге 45, половина промахивалась на 1-5
очков. По риску - отдельная проверка.
"""
import numpy as np
import pytest

from conftest import run_front
from eval import synth as S
from shchelchok import detector as D, settings as St, tuning as T

# Настоящие оценки щелчков ВЛАДЕЛЬЦА из журнала 1.2.0 (16-16.10.2026, 4,5 часа, порог 45):
# 75 узнанных щелчков и 33 промаха, которые стояли рядом с узнанными, то есть тоже его щелчки.
OWNER_SNAPS = [46, 46, 46, 46, 46, 46, 46, 47, 47, 47, 47, 47, 48, 48, 48, 48, 49, 49, 50, 51, 51, 51, 52, 52,
               52, 53, 53, 53, 54, 54, 54, 54, 54, 54, 54, 55, 55, 56, 56, 56, 56, 56, 56, 57, 58, 58, 59, 59,
               59, 59, 60, 60, 60, 61, 61, 62, 62, 62, 63, 64, 64, 64, 65, 66, 66, 67, 69, 69, 70, 70, 74, 75,
               76, 80, 82,
               23, 23, 24, 24, 26, 26, 27, 27, 28, 29, 30, 31, 32, 35, 36, 36, 36, 38, 38, 39, 40, 40, 41, 41,
               41, 42, 42, 42, 42, 42, 43, 44, 44]
# Посторонние звуки из того же журнала, которые НЕ стояли рядом с щелчком (шум его комнаты)
OWNER_NOISE = [20, 24, 24, 25, 27, 29, 29, 30, 31, 43]


def cands(rng, n=5, centroid=2900, spread=0.04, peak=None):
    """n синтетических щелчков одного «человека» - как в окне настройки."""
    bed = S.room(rng, 2 + 1.5 * n, 0.003)
    for k in range(n):
        S.place(bed, S.snap(rng, centroid=centroid * rng.uniform(1 - spread, 1 + spread), decay_ms=9),
                1.5 + 1.5 * k, 1.0 if peak is None else peak[k])
    out = [c for c in run_front(bed) if not D.gates(c, strict=False) and c["snr"] >= 15]
    assert len(out) == n
    return out


# ---------------------------------------------------------------- несколько образцов вместо одного
def test_template_keeps_every_sample(rng):
    cs = cands(rng, 5)
    tpl = D.make_template(cs)
    assert len(tpl["samples"]) == 5
    s = tpl["samples"][0]
    assert len(s["shape"]) == D.NBANDS and len(s["dec"]) == len(D.DEC_POINTS) and "peak" in s


def test_score_takes_the_best_sample_not_only_the_average(rng):
    """Щелчок пальцами не повторяется один в один, а настройка 1.3.0 ПРОСИТ щёлкать по-разному (тише, резче,
    дальше). Среднее по таким щелчкам не похоже ни на один из них - поэтому сравниваем и с самими образцами.
    Крайний случай «щёлкаю по-разному»: половина образцов звонкая, половина глухая."""
    low = cands(np.random.default_rng(21), 3, centroid=2200)
    high = cands(np.random.default_rng(22), 3, centroid=4200)
    tpl = D.make_template(low[:2] + high[:2])
    flat = dict(tpl)
    flat.pop("samples")
    probes = [low[2], high[2]]
    with_s = [D.score(c, tpl, thr=45)[0] for c in probes]
    without = [D.score(c, flat, thr=45)[0] for c in probes]
    assert all(a > b for a, b in zip(with_s, without)), (with_s, without)
    assert max(without) < 45 <= max(with_s), "без образцов такой щелчок не узнаётся вообще"


def test_sample_match_costs_a_penalty(rng):
    """Поблажка не бесплатная: совпадение с ОДНИМ образцом слабее совпадения со средним на SAMPLE_PENALTY -
    иначе среди образцов всегда найдётся похожий и на посторонний звук (подобрано прогоном eval/calib_n.py)."""
    cs = cands(rng, 5)
    tpl = D.make_template(cs)
    assert D.SAMPLE_PENALTY >= 1.0
    d_mean = sum(D.distance(cs[0], tpl)[:1]) + D.A_DEC * D.distance(cs[0], tpl)[1] + D.distance(cs[0], tpl)[2]
    d_smp = D.sample_distance(cs[0], D.sample_of(cs[0]), tpl)[0]
    assert d_smp == pytest.approx(D.SAMPLE_PENALTY, abs=0.01), "до самого себя расстояние = только плата"
    assert D.total_distance(cs[0], tpl)[0] <= min(d_mean, d_smp) + 1e-6


def test_samples_do_not_make_everything_a_snap(rng):
    """Поблажка не бесплатная: проверяем, что чужой звук (стук) образцами не «вытягивается» в щелчок."""
    cs = cands(rng, 5, spread=0.14)
    tpl = D.make_template(cs)
    bed = S.room(rng, 3, 0.003)
    S.place(bed, S.knock(rng), 1.2)
    for c in run_front(bed):
        assert D.score(c, tpl, thr=45)[1], "стук остался не щелчком"


def test_relearn_adds_live_snaps_to_samples(rng):
    cs = cands(rng, 5)
    tpl = D.make_template(cs[:3])
    new, kept = D.relearn(tpl, cs[3:])
    assert len(kept) == 5 and len(new["samples"]) == 5
    assert new["n"] == 5


def test_relearn_keeps_at_most_ten_samples(rng):
    cs = cands(rng, 7)
    tpl = D.make_template(cs)
    for _ in range(3):
        tpl, kept = D.relearn(tpl, cs)
    assert len(tpl["samples"]) <= D.MAX_SAMPLES


# ---------------------------------------------------------------- отбор щелчков настройки
def test_pick_calib_drops_one_odd_snap(rng):
    """На пяти щелчках всегда найдётся один «не такой» - его выбрасываем, а не начинаем настройку заново."""
    cs = cands(rng, 5)
    odd = cands(np.random.default_rng(99), 1, centroid=1500)[0]
    kept, dropped = D.pick_calib(cs + [odd], need=5)
    assert len(kept) == 5 and dropped == [odd]


def test_pick_calib_gives_up_when_all_snaps_are_different(rng):
    cs = [cands(np.random.default_rng(s), 1, centroid=c)[0]
          for s, c in ((1, 1400), (2, 2600), (3, 4800), (4, 7000), (5, 2000))]
    kept, dropped = D.pick_calib(cs, need=5)
    assert kept == [] and len(dropped) == 5


def test_pick_calib_keeps_all_when_snaps_are_alike(rng):
    cs = cands(rng, 5, spread=0.02)
    kept, dropped = D.pick_calib(cs, need=5)
    assert len(kept) == 5 and dropped == []


# ---------------------------------------------------------------- честная оценка настройки
def test_loo_scores_are_honest(rng):
    """Оценка щелчка шаблоном, в котором он сам и сидит, завышена - считаем по шаблону из ОСТАЛЬНЫХ."""
    cs = cands(rng, 5, spread=0.1)
    tpl = D.make_template(cs)
    loo = T.loo_scores(cs, thr=45)
    own = [D.score(c, tpl, thr=45)[0] for c in cs]
    assert len(loo) == 5
    assert sum(loo) / 5 <= sum(own) / 5 + 0.01, "честная оценка не может быть выше «самооценки»"


def test_quality_is_a_number_out_of_100():
    assert T.quality([60, 62, 58, 64, 59], 45) >= 90
    assert T.quality([46, 44, 48, 42, 47], 45) == pytest.approx(50, abs=20)
    assert T.quality([30, 32, 28], 45) <= 15
    assert T.quality([], 45) == 0


def test_quality_grows_when_threshold_drops():
    sc = [40, 44, 48, 52, 56]
    assert T.quality(sc, 40) > T.quality(sc, 45) > T.quality(sc, 55)


def test_quality_word_matches_number():
    assert T.quality_word(86) == "это хорошо" and T.quality_word(41) == "это мало"


def test_calib_text_says_number_and_range():
    t = T.calib_text([52, 60, 70, 78, 64], 45)
    assert "из 100" in t and "от 52 до 78" in t and "порог 45" in t


def test_calib_advice_appears_only_when_bad():
    assert T.calib_advice([60, 64, 70], 45) == ""
    bad = T.calib_advice([28, 36, 49], 45, loud=16, noise_max=10)
    assert bad.startswith("Лучше переснять настройку") and "ближе к микрофону" in bad


# ---------------------------------------------------------------- порог под человека
def test_suggest_threshold_on_owner_real_numbers():
    """Главная цифра задачи: по настоящим оценкам владельца программа предлагает порог около 40, и это
    действительно прибавляет узнавание (владелец: «порог 40 - и вот уже 4 срабатывания лучше»)."""
    info = T.suggest_threshold(OWNER_SNAPS, OWNER_NOISE, cur=45)
    assert 38 <= info["thr"] <= 46, info
    at45 = sum(1 for v in OWNER_SNAPS if v >= 45)
    at40 = sum(1 for v in OWNER_SNAPS if v >= 40)
    assert at45 == 75 and at40 == 88, "на его же числах порог 40 даёт на 13 узнанных щелчков больше"


def test_suggest_threshold_does_not_go_under_the_room_noise():
    """Порог не опускаем ниже самого похожего на щелчок постороннего звука - иначе окна поедут сами."""
    info = T.suggest_threshold([30, 32, 34, 36, 38], noise=[42, 20, 31], cur=45)
    assert info["thr"] >= 45 and info["noise_max"] == 42


def test_suggest_threshold_stays_in_safe_range():
    low = T.suggest_threshold([5, 6, 7, 8], noise=[], cur=45)
    high = T.suggest_threshold([95, 96, 97, 98], noise=[], cur=45)
    assert low["thr"] == int(D.THR_MIN) and high["thr"] <= T.THR_SUGGEST_MAX


def test_suggest_threshold_counts_how_many_pass():
    info = T.suggest_threshold([40, 42, 50, 60, 70], noise=[], cur=45)
    assert info["total"] == 5 and info["hits"] == sum(1 for v in [40, 42, 50, 60, 70] if v >= info["thr"])


def test_suggest_text_has_real_numbers():
    info = T.suggest_threshold(OWNER_SNAPS[:12], OWNER_NOISE, cur=45)
    t = T.suggest_text(info, 45, noise_count=64)
    assert str(info["thr"]) in t and "из ваших 12 щелчков" in t and "64" in t
    assert str(info["noise_max"]) in t


def test_check_text_says_range_and_suggestion():
    t = T.check_text([27, 44, 55, 70], 45, suggested=40)
    assert t == "ваши щелчки: от 27 до 70, порог сейчас 45, предлагаю 40"
    assert T.check_text([], 45) == "щелчков не услышал, порог сейчас 45"


# ---------------------------------------------------------------- оценки звуков: своё и постороннее
def test_score_history_separates_own_snaps_from_noise():
    h = T.ScoreHistory(clock=lambda: 100.0)
    h.add(60, True, now=10.0)                 # щелчок
    h.add(41, False, now=10.6)                # промах того же жеста - это НЕ посторонний звук
    h.add(31, False, now=50.0)                # посторонний
    assert h.own(now=100.0) == [60.0]
    assert h.noise(now=100.0) == [31.0]


def test_score_history_forgets_old_sounds():
    h = T.ScoreHistory()
    h.add(60, True, now=0.0)
    h.add(30, False, now=0.0)
    assert h.own(now=T.NOISE_WINDOW + 10) == [] and h.noise(now=T.NOISE_WINDOW + 10) == []


# ---------------------------------------------------------------- порог как настройка
def test_threshold_and_sensitivity_are_the_same_knob():
    assert D.threshold(8) == 45 and D.sens_of_thr(45) == 8
    assert D.sens_of_thr(D.threshold(3)) == 3
    assert D.sens_of_thr(5) == 10 and D.sens_of_thr(100) == 1      # за краями - в пределах 1-10


def test_detector_uses_threshold_not_only_sensitivity(rng):
    """Порог - число с шагом 1 очко: звук с оценкой между 40 и 45 при пороге 40 щелчок, при 45 - нет."""
    cs = cands(rng, 5)
    tpl = D.make_template(cs[:4])
    probe = cs[4]
    s = D.score(probe, tpl, thr=45)[0]
    assert D.score(probe, tpl, thr=s - 1)[1] == ""
    assert D.score(probe, tpl, thr=s + 1)[1] == "не похоже на щелчок"
    j = D.judge(probe, tpl, thr=s + 1)
    assert j["thr"] == s + 1 and j["kind"] in (D.MAYBE, D.NOISE)


def test_settings_migrate_sensitivity_to_threshold(tmp_path):
    """Обновление не меняет, как программа слушает: у владельца чувствительность 8 - значит порог 45."""
    import json
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"sens": 8, "mode": 1}), encoding="utf-8")
    d = St.load(str(p))
    assert d["thr"] == 45 and d["sens"] == 8
    p.write_text(json.dumps({"sens": 5}), encoding="utf-8")
    assert St.load(str(p))["thr"] == 60, "кто не трогал чувствительность - слушает как раньше"
    p.write_text(json.dumps({"sens": 8, "thr": 40}), encoding="utf-8")
    assert St.load(str(p))["thr"] == 40, "свой порог важнее старой чувствительности"


def test_settings_threshold_is_clamped(tmp_path):
    import json
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"thr": 500}), encoding="utf-8")
    assert St.load(str(p))["thr"] == St.THR_MAX
    p.write_text(json.dumps({"thr": "ой"}), encoding="utf-8")
    assert St.load(str(p))["thr"] == St.DEFAULTS["thr"]


def test_settings_keeps_samples_and_drops_broken_ones(tmp_path, rng):
    import json
    cs = cands(rng, 4)
    tpl = D.make_template(cs)
    tpl["samples"].append({"shape": [1, 2], "dec": [], "peak": 0})       # испорченный образец
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"templates": {"mic": tpl}}), encoding="utf-8")
    d = St.load(str(p))
    assert len(d["templates"]["mic"]["samples"]) == 4
