"""Цвет оформления линейки «ТЫ - бизнесмен» - КОПИЯ ~/office_tools/_brand (править там, раздавать: python3 _brand/sync.py).

Меняется ТОЛЬКО цвет: формула перелива (направление полос, скорость, 2 пятна) не трогается.
Каждый цвет темы = цвет фиолетовой палитры, повёрнутый по оттенку в OKLCH (светлота L сохраняется - контраст белого
текста на стекле не падает; насыщенность C сохраняется, если цвет помещается в sRGB, иначе снижается до границы).
«Фиолетовый» - исходная палитра бит-в-бит. «Графит» - тот же поворот, насыщенность x0.12.

Значение темы (строка в настройках программы): 'violet' | 'blue' | 'teal' | 'green' | 'red' | 'orange' | 'pink' |
'graphite' | 'custom:<0..360>' (свой оттенок, градусы OKLCH). Неизвестное значение = 'violet'.

    palette(theme)          - 6 цветов перелива (как PALETTE)
    tint(rgb, theme)        - любой «фиолетовый» цвет оформления в цвет темы (жёлтый, зелёный, красный - без изменений)
    swatch(theme)           - цвет кружка в выборе темы
Без зависимостей (math) - работает в tkinter, Qt и тестах. Та же математика - в brand-flow.js (тест сверяет).
"""
import math

PALETTE = [(49, 10, 110), (91, 33, 182), (139, 92, 246), (192, 132, 252), (109, 40, 217), (67, 20, 150)]
DEFAULT = "violet"
# (ключ, подпись, оттенок OKLCH, множитель насыщенности); None у фиолетового - исходная палитра без пересчёта
PRESETS = [
    ("violet", "Фиолетовый", None, 1.0),
    ("blue", "Синий", 262.0, 1.0),
    ("teal", "Бирюзовый", 195.0, 1.0),
    ("green", "Зелёный", 150.0, 1.0),
    ("red", "Красный", 25.0, 1.0),
    ("orange", "Оранжевый", 50.0, 1.0),
    ("pink", "Розовый", 350.0, 1.0),
    ("graphite", "Графит", 262.0, 0.12),
]
CUSTOM_LABEL = "Свой"
CUSTOM_DEFAULT_HUE = 210
LABEL = "Цвет оформления"
# цвета, которые НЕ перекрашиваются (акцент, статусы); контраст на стекле каждой темы проверяет тест
ACCENT = (255, 214, 10)
OK = (126, 240, 176)
ERR = (255, 107, 134)
GLASS = (26, 7, 62)            # тёмное стекло brand-flow.css (--bf-glass-dark, непрозрачность .62)


def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _cbrt(x):
    return math.copysign(abs(x) ** (1.0 / 3.0), x)


def to_oklch(rgb):
    r, g, b = (_lin(float(v)) for v in rgb[:3])
    l = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    bb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360.0


def _lab_rgb(L, a, b):
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def from_oklch(L, C, h):
    """OKLCH -> sRGB 0..255; вне охвата sRGB - насыщенность уменьшается (бинарный поиск), L и оттенок те же."""
    hr = math.radians(h)
    ca, sa = math.cos(hr), math.sin(hr)

    def inside(c):
        return all(-1e-4 <= v <= 1.0001 for v in _lab_rgb(L, c * ca, c * sa))
    if not inside(C):
        lo, hi = 0.0, C
        for _ in range(24):
            mid = (lo + hi) / 2
            if inside(mid):
                lo = mid
            else:
                hi = mid
        C = lo
    return tuple(int(round(min(1.0, max(0.0, _gam(min(1.0, max(0.0, v))))) * 255)) for v in _lab_rgb(L, C * ca, C * sa))


BASE_HUE = to_oklch(PALETTE[2])[2]          # оттенок опорного цвета (139, 92, 246) ~ 293°


def parse(theme):
    """-> (ключ, оттенок или None, множитель насыщенности). Мусор -> фиолетовый."""
    t = str(theme or DEFAULT).strip().lower()
    for key, _name, hue, cm in PRESETS:
        if t == key:
            return key, hue, cm
    if t.startswith("custom:"):
        try:
            h = float(t.split(":", 1)[1]) % 360.0
            return "custom", h, 1.0
        except ValueError:
            pass
    return DEFAULT, None, 1.0


def normalize(theme):
    key, hue, _ = parse(theme)
    return f"custom:{int(round(hue)) % 360}" if key == "custom" else key


def is_tintable(rgb):
    """Цвет «фирменный фиолетовый» (его перекрашиваем): оттенок 255..335°, заметная насыщенность."""
    _L, C, h = to_oklch(rgb)
    return C >= 0.03 and 255.0 <= h <= 335.0


def tint(rgb, theme):
    """Фиолетовый цвет оформления -> цвет темы (альфа, если есть, сохраняется). Прочие цвета - как есть."""
    key, hue, cm = parse(theme)
    rgb = tuple(int(v) for v in rgb)
    if hue is None or not is_tintable(rgb[:3]):
        return rgb
    L, C, h = to_oklch(rgb[:3])
    out = from_oklch(L, C * cm, (h - BASE_HUE + hue) % 360.0)
    return out + rgb[3:]


def palette(theme=DEFAULT):
    return [tint(c, theme) for c in PALETTE]


def swatch(theme):
    return tint(PALETTE[2], theme)


def presets():
    """[(значение, подпись, цвет кружка)] - для окна настроек."""
    return [(k, n, swatch(k)) for k, n, _h, _c in PRESETS]


# ---------------------------------------------------------------- контраст (WCAG)
def luminance(rgb):
    r, g, b = (_lin(float(v)) for v in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def over(fg, alpha, bg):
    return tuple(fg[i] * alpha + bg[i] * (1 - alpha) for i in range(3))


def glass_worst(theme, alpha=0.62, glass=GLASS):
    """Самый светлый фон под стеклом: стекло темы поверх белого (пятна перелива на светлой полосе)."""
    return over(tint(glass, theme), alpha, (255, 255, 255))


# ---------------------------------------------------------------- текст стилей (QSS, CSS, HTML)
import re as _re  # noqa: E402

_NUM = r"\s*(\d{1,3})\s*"
_RX = _re.compile(r"rgba?\(" + _NUM + "," + _NUM + "," + _NUM + r"(,\s*[0-9.]+%?\s*)?\)"
                  r"|#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def tint_text(text, theme):
    """Все фиолетовые цвета в тексте стиля (rgb(), rgba(), #rrggbb, #rgb) -> цвета темы; формат записи тот же."""
    if parse(theme)[1] is None:
        return text

    def rep(m):
        if m.group(5):
            hx = m.group(5)
            short = len(hx) == 3
            if short:
                hx = "".join(c * 2 for c in hx)
            rgb = tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))
            out = tint(rgb, theme)
            if out == rgb:
                return m.group(0)
            return "#%02X%02X%02X" % out if m.group(5).isupper() else "#%02x%02x%02x" % out
        rgb = tuple(int(m.group(i)) for i in (1, 2, 3))
        if max(rgb) > 255:
            return m.group(0)
        r, g, b = tint(rgb, theme)
        if (r, g, b) == rgb:
            return m.group(0)
        return f"rgba({r}, {g}, {b}{m.group(4)})" if m.group(4) else f"rgb({r}, {g}, {b})"
    return _RX.sub(rep, text)
