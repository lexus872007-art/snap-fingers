"""Статические начертания Manrope (600/700/800) из переменного ui/fonts/Manrope.ttf (OFL).
Переменный шрифт под старым движком шрифтов Windows (и под Wine) рисуется самым тонким начертанием - поэтому в
программу кладём обычные файлы: Manrope-SemiBold/Bold/ExtraBold.ttf, семейство «Manrope».
    ../venv/bin/python tools/make_fonts.py      (нужен fonttools)"""
import os

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "ui", "fonts", "Manrope.ttf")
for weight, style in ((600, "SemiBold"), (700, "Bold"), (800, "ExtraBold")):
    f = instancer.instantiateVariableFont(TTFont(SRC), {"wght": weight})
    name = f["name"]
    for rec in list(name.names):
        if rec.nameID in (1, 2, 3, 4, 6, 16, 17):
            name.removeNames(nameID=rec.nameID)
    full = f"Manrope {style}"
    for nid, val in ((1, "Manrope"), (2, "Bold" if weight == 700 else "Regular"), (3, f"Manrope-{style};static"),
                     (4, full), (6, f"Manrope-{style}"), (16, "Manrope"), (17, style)):
        name.setName(val, nid, 3, 1, 0x409)
        name.setName(val, nid, 1, 0, 0)
    f["OS/2"].usWeightClass = weight
    sel = f["OS/2"].fsSelection & ~0b1100001          # снять italic/bold/regular
    f["OS/2"].fsSelection = sel | (0b100000 if weight == 700 else 0b1000000)
    f["head"].macStyle = 1 if weight == 700 else 0
    out = os.path.join(ROOT, "ui", "fonts", f"Manrope-{style}.ttf")
    f.save(out)
    print(out, os.path.getsize(out))
