"""Значок программы (тот же рисунок, что в трее и на плашке): ui/icon.png (256) и ui/icon.ico (16-256).
Запуск на сервере 2: tools/linux_run.sh offscreen ../venv/bin/python tools/make_icon.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication([])
from shchelchok import brand  # noqa: E402
from PIL import Image  # noqa: E402

png = os.path.join(ROOT, "ui", "icon.png")
brand.app_icon_image(512).save(png)
im = Image.open(png).convert("RGBA")
im.resize((256, 256), Image.LANCZOS).save(png)
im.save(os.path.join(ROOT, "ui", "icon.ico"), sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48),
                                                     (64, 64), (128, 128), (256, 256)])
print("ok")
