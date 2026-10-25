# -*- mode: python ; coding: utf-8 -*-
# Сборка «Щелчок» (onedir): pyinstaller --noconfirm Shchelchok.spec
# Из Qt берём только нужное: QtCore/QtGui/QtWidgets/QtNetwork, платформа windows, картинки png/ico.
# Звук - sounddevice (PortAudio из пакета).
import os

datas = [('ui/fonts/Manrope-SemiBold.ttf', 'ui/fonts'), ('ui/fonts/Manrope-Bold.ttf', 'ui/fonts'),
         ('ui/fonts/Manrope-ExtraBold.ttf', 'ui/fonts'), ('ui/icon.ico', 'ui'), ('ui/icon.png', 'ui'),
         ('licenses', 'licenses')]      # перечень открытых компонентов и тексты лицензий - рядом с программой

binaries = []          # PortAudio для sounddevice собирает hook-sounddevice (pyinstaller-hooks-contrib)
a = Analysis(['start.py'], pathex=['.'], binaries=binaries, datas=datas,
             hiddenimports=['PySide6.QtNetwork', 'sounddevice', '_cffi_backend'],
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             # ssl/_ssl НЕ исключать: без них самообновление не достучится до сервера по https (приёмка 17.10.2026)
             excludes=['tkinter', 'numpy', 'PIL', 'pytest', 'PySide6.QtQml', 'PySide6.QtQuick',
                       'PySide6.QtOpenGL', 'PySide6.QtPdf', 'PySide6.QtSvg', 'PySide6.QtDBus', 'PySide6.QtConcurrent',
                       'PySide6.QtSql', 'PySide6.QtXml', 'PySide6.QtTest', 'PySide6.QtPrintSupport', 'openpyxl',
                       'cryptography', 'msoffcrypto', 'docx', 'lxml', 'pypdfium2', 'bottle', 'clr', 'clr_loader', 'mss'],
             noarchive=False, optimize=0)

# libcrypto/libssl/_ssl в DROP НЕ класть: это и есть https для самообновления (приёмка 17.10.2026)
DROP = ('opengl32sw.dll', 'Qt6Pdf', 'Qt6Qml', 'Qt6Quick', 'Qt6Svg', 'Qt6OpenGL', 'Qt6VirtualKeyboard', 'qtvirtualkeyboard',
        'qpdf', 'qsvg', 'qtga', 'qtiff', 'qwbmp', 'qwebp', 'qgif', 'qicns', 'qdirect2d', 'qminimal', 'qoffscreen',
        'qnetworklistmanager', 'qtuiotouchplugin', 'qopensslbackend', 'qschannelbackend', 'qcertonlybackend',
        'libportaudio32bit', 'libportaudio64bit-asio', 'libportaudioarm64', 'libportaudio.dylib')
def keep(entry):
    name = entry[0].replace('\\', '/')
    base = os.path.basename(name)
    if 'translations/' in name and not base.startswith('qtbase_ru'):
        return False
    if base.startswith('Qt6Network') or base.startswith('QtNetwork'):
        return True
    return not any(base.startswith(d) or d in base for d in DROP)
a.binaries = [b for b in a.binaries if keep(b)]
a.datas = [d for d in a.datas if keep(d)]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Shchelchok', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=False, disable_windowed_traceback=False, argv_emulation=False,
          target_arch=None, codesign_identity=None, entitlements_file=None, icon=['ui/icon.ico'])
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, upx_exclude=[], name='Shchelchok')
