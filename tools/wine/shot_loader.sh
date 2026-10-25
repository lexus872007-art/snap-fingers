#!/bin/bash
# Снимки окна установщика (--demo) под Wine при 100/125/150 % на своём экране (не :99/:100).
B=$HOME/shchelchok_build
export WINEPREFIX=$B/wine WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
D=${1:-76}; OUT=$B/shots_loader; rm -rf $OUT; mkdir -p $OUT
[ -e /tmp/.X11-unix/X$D ] && { echo "экран :$D занят"; exit 1; }
Xvfb :$D -screen 0 1600x1000x24 >/dev/null 2>&1 &
XP=$!; sleep 2; export DISPLAY=:$D
xsetroot -solid "#203040"
for dpi in 96 120 144; do
  wine reg add "HKCU\\Control Panel\\Desktop" /v LogPixels /t REG_DWORD /d $dpi /f >/dev/null 2>&1
  sleep 1; wineserver -k; sleep 1
  for st in progress update first wait done error; do
    setsid wine $B/release/Shchelchok-Setup.exe --demo $st >/dev/null 2>&1 &
    P=$!; sleep 14
    $B/venv/bin/python -c "from PIL import ImageGrab; im=ImageGrab.grab(xdisplay=\":$D\"); bb=im.convert(\"RGB\").point(lambda v: 255 if v>70 else 0).convert(\"L\").getbbox(); (im.crop(bb) if bb else im).save(\"$OUT/ldr_${st}_${dpi}.png\")"
    kill -- -$P 2>/dev/null; wineserver -k; sleep 1
  done
done
wine reg add "HKCU\\Control Panel\\Desktop" /v LogPixels /t REG_DWORD /d 96 /f >/dev/null 2>&1
wineserver -k; kill $XP; ls $OUT
