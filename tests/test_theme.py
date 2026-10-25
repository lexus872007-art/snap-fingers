# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Цвет оформления: общий код линейки (brand_theme, OKLCH) - меняется только оттенок палитры; перелив (формула,
направление, пятна) тот же; акценты целы; «Свой» - любой оттенок ползунком и он переживает перезапуск."""
from shchelchok import brand, settings
from shchelchok import brand_theme as bt


def teardown_function():
    brand.set_theme("violet")


def hue_of(c):
    return bt.to_oklch(c)[2]


def test_default_is_base_palette():
    brand.set_theme("violet")
    assert brand.PALETTE == brand.BASE_PALETTE == list(bt.PALETTE)


def test_presets_rotate_hue_keep_lightness():
    for tid, _name, hue in brand.THEMES:
        if hue is None:
            continue
        brand.set_theme(tid)
        for a, b in zip(brand.BASE_PALETTE, brand.PALETTE):
            la, _ca, _ha = bt.to_oklch(a)
            lb, _cb, _hb = bt.to_oklch(b)
            assert abs(la - lb) < 0.02, tid          # светлота та же - белый текст читается
        h = hue_of(brand.PALETTE[2])
        assert min(abs(h - hue), 360 - abs(h - hue)) < 3, tid


def test_graphite_low_saturation():
    brand.set_theme("graphite")
    assert all(bt.to_oklch(c)[1] < 0.04 for c in brand.PALETTE)


def test_custom_hue_and_unknown():
    assert brand.set_theme("custom", 100) == "custom"
    assert min(abs(hue_of(brand.PALETTE[2]) - 100), 360 - abs(hue_of(brand.PALETTE[2]) - 100)) < 3
    assert brand.theme_value() == "custom:100" and brand.theme_hue() == 100
    assert brand.set_theme("нет такой") == "violet"
    assert brand.set_theme("custom", None) == "custom"      # без оттенка - оттенок по умолчанию, не поломка


def test_accents_untouched():
    brand.set_theme("green")
    assert brand.tint_rgb(255, 214, 10) == (255, 214, 10)        # жёлтый
    assert brand.tint_rgb(255, 255, 255) == (255, 255, 255)
    css = brand.tint_css("a { color: #FFD60A; background: rgba(20,0,60,110); border: #4C1D95; }")
    assert "#FFD60A" in css and "#4C1D95" not in css and "rgba(20,0,60,110)" not in css


def test_flow_same_formula(qapp):
    """Перелив тот же: у темы те же полосы (позиции переходов) и та же светлота (OKLCH) по диагонали - меняется
    только оттенок."""
    from PySide6.QtGui import QColor
    brand.set_theme("violet")
    a = brand.flow_image(200, 100, 1.3)
    brand.set_theme("teal")
    b = brand.flow_image(200, 100, 1.3)
    lum = lambda img, x: bt.to_oklch(QColor(img.pixel(x, x // 2)).getRgb()[:3])[0]   # noqa: E731
    assert max(abs(lum(a, x) - lum(b, x)) for x in range(0, 200, 10)) < 0.04
    assert QColor(a.pixel(100, 50)).hue() != QColor(b.pixel(100, 50)).hue()


# ---------------------------------------------------------------- «Свой»: настройки <-> общий выбор цвета
def test_theme_value_round_trip():
    d = dict(settings.DEFAULTS)
    assert settings.theme_value(d) == "violet"
    d.update(theme="custom", hue=200)
    assert settings.theme_value(d) == "custom:200"
    assert settings.theme_parts("custom:200") == ("custom", 200)
    assert settings.theme_parts("blue") == ("blue", None)
    assert settings.theme_parts("мусор") == ("violet", None)
    assert settings.theme_parts("custom:725")[1] == 5            # оттенок по кругу, как в общем brand_theme
    assert settings.theme_parts("custom:абв")[1] == settings.DEFAULTS["hue"]


def test_custom_hue_survives_restart(tmp_path):
    p = str(tmp_path / "s.json")
    d = settings.load(p)
    d["theme"], d["hue"] = "custom", 200
    settings.save(d, p)
    again = settings.load(p)
    assert again["theme"] == "custom" and again["hue"] == 200
    assert settings.theme_value(again) == "custom:200"
    brand.set_theme(*[x for x in settings.theme_parts(settings.theme_value(again))])
    assert brand.theme_value() == "custom:200"
