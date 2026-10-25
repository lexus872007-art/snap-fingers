#!/bin/bash
# Весь путь жеста в НАСТОЯЩЕЙ Windows-сборке под Wine: три «Блокнота» -> синтетический щелчок сворачивает окна ->
# микрофон «отваливается» и переподключается (баг 16.10) -> ДВА щелчка возвращают ВСЕ окна.
#   tools/wine/gesture_test.sh [экран]   -> ~/shchelchok_build/gesture/{before,hidden,after}.png + gesture.json
B=$HOME/shchelchok_build
export WINEPREFIX=$B/wine WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
D=${1:-87}; [ -e /tmp/.X11-unix/X$D ] && { echo "экран :$D занят"; exit 1; }
OUT=$B/gesture; rm -rf $OUT; mkdir -p $OUT
Xvfb :$D -screen 0 1400x900x24 >/dev/null 2>&1 &
XP=$!; sleep 2; export DISPLAY=:$D; xsetroot -solid "#203040"
setsid wine notepad >/dev/null 2>&1 & N1=$!
sleep 4
setsid wine notepad >/dev/null 2>&1 & N2=$!
sleep 4
setsid wine notepad >/dev/null 2>&1 & N3=$!
sleep 5
$B/venv/bin/python -c "from PIL import ImageGrab; ImageGrab.grab(xdisplay=\":$D\").save(\"$OUT/before.png\")"
setsid wine $B/win/dist/Shchelchok/Shchelchok.exe --selftest 'Z:'"${OUT//\//\\}" --gesture-test --no-tray \
  --settings 'Z:'"${OUT//\//\\}"'\s.json' >/dev/null 2>&1 & P=$!
for i in $(seq 1 90); do sleep 1; [ -f $OUT/hidden.flag ] && break; done
sleep 1
$B/venv/bin/python -c "from PIL import ImageGrab; ImageGrab.grab(xdisplay=\":$D\").save(\"$OUT/hidden.png\")"
for i in $(seq 1 60); do sleep 2; [ -f $OUT/gesture.json ] && break; done
sleep 2
$B/venv/bin/python -c "from PIL import ImageGrab; ImageGrab.grab(xdisplay=\":$D\").save(\"$OUT/after.png\")"
echo "--- gesture.json"; cat $OUT/gesture.json
for p in $P $N1 $N2 $N3; do kill -- -$p 2>/dev/null; done
wineserver -k; kill $XP
