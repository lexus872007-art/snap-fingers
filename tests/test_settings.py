# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Настройки и клавиша: значения по умолчанию, испорченный файл, Ctrl+Alt+Z свободна, клавиши соседей."""
import json

from shchelchok import settings


def test_defaults_single_snap_and_safe():
    d = settings.load("/nonexistent/s.json")
    assert d["mode"] == 1 and d["sens"] == 5 and d["listening"] is True
    # ОДИН щелчок - переключатель: свернул / вернул (решение владельца 16.10.2026)
    assert d["back"] == 1 and d["thr"] == 45
    assert d["autostart"] is False and d["ignore_output"] and d["ignore_typing"]
    assert d["hotkeys"]["toggle"] == "Ctrl+Alt+Z"


def test_default_key_not_taken_by_line():
    assert settings.parse_hotkey("Ctrl+Alt+Z") is not None
    assert settings.line_owner("Ctrl+Alt+Z") is None
    for k in ("Ctrl+Alt+Space", "Ctrl+Alt+G", "Ctrl+Alt+D", "Ctrl+Alt+F", "Ctrl+Alt+H", "Ctrl+Alt+S", "Ctrl+Alt+W",
              "Ctrl+Alt+P", "Ctrl+Alt+O", "Ctrl+Alt+Up", "Ctrl+Alt+Down", "Ctrl+Alt+PgUp", "Ctrl+Alt+PgDown",
              "Ctrl+Alt+Home"):
        assert settings.line_owner(k), k
        assert settings.parse_hotkey(k) != settings.parse_hotkey("Ctrl+Alt+Z")


def test_hotkey_problem_texts():
    assert settings.hotkey_problem("Ctrl+Alt+Z") is None
    assert "Суфлёр" in settings.hotkey_problem("Ctrl+Alt+P")
    assert "Local Voice" in settings.hotkey_problem("Ctrl+Alt+Space")
    assert "Ctrl, Alt или Win" in settings.hotkey_problem("Z")
    assert settings.hotkey_problem("") is None


def test_corrupted_values_normalized(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"mode": 7, "sens": "abc", "mic": 5, "templates": {"x": {"shape": [1]}, "y": 3},
                             "toast": None, "hotkeys": {"toggle": "Ctrl+Alt+Q", "чужое": "x"}}), encoding="utf-8")
    d = settings.load(str(p))
    assert d["mode"] == 1 and d["sens"] == 5 and d["mic"] == "" and d["templates"] == {}
    assert d["toast"] is True and d["hotkeys"] == {"toggle": "Ctrl+Alt+Q"}


def test_broken_json(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{не json", encoding="utf-8")
    assert settings.load(str(p))["mode"] == 1


def test_roundtrip_with_template(tmp_path):
    p = str(tmp_path / "s.json")
    d = settings.load(p)
    from shchelchok.detector import NBANDS
    tpl = {"shape": [0.0] * NBANDS, "dec": [-1.0] * 6, "peak_min": -12.0, "snr_min": 30.0, "centroid": 3000.0,
           "spread": 2.0, "n": 3}
    d["templates"]["Гарнитура"] = tpl
    d["mode"] = 2
    settings.save(d, p)
    e = settings.load(p)
    assert e["templates"]["Гарнитура"] == tpl and e["mode"] == 2


def test_theme_setting_normalized(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"theme": "радуга", "hue": 999}), encoding="utf-8")
    d = settings.load(str(p))
    assert d["theme"] == "violet" and 0 <= d["hue"] <= 359


def test_template_found_when_windows_truncates_mic_name():
    """Общий режим Windows обрезает имя микрофона до 31 знака («Набор микрофонов (Realtek(R) Au») - настройка
    щелчка обязана найтись и по полному имени, и по обрезанному, и в другом регистре (баг 16.10.2026)."""
    tp = {"Набор микрофонов (Realtek(R) Au": {}}
    assert settings.match_template_key(tp, "Набор микрофонов (Realtek(R) Audio)") == \
        "Набор микрофонов (Realtek(R) Au"
    assert settings.match_template_key(tp, "набор  микрофонов (realtek(r) au") == \
        "Набор микрофонов (Realtek(R) Au"
    assert settings.match_template_key(tp, "Микрофон (USB гарнитура)") is None
    assert settings.match_template_key(tp, "") is None
    assert settings.match_template_key({}, "Набор микрофонов") is None
