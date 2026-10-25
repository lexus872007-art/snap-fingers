# -*- mode: python ; coding: utf-8 -*-
# Установщик одним файлом: pyinstaller --noconfirm loader\Setup.spec  ->  dist\Shchelchok-Setup.exe
import os
ROOT = os.path.dirname(SPECPATH)
a = Analysis([os.path.join(SPECPATH, 'loader.py')], pathex=[SPECPATH], binaries=[],
             datas=[(os.path.join(ROOT, 'ui', 'icon.ico'), '.')], hiddenimports=['brandflow_tk'],
             excludes=['numpy', 'PySide6', 'shiboken6', 'PIL', 'mss'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='Shchelchok-Setup', debug=False, strip=False, upx=False,
          console=False, icon=[os.path.join(ROOT, 'ui', 'icon.ico')])
