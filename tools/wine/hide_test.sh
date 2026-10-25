#!/bin/bash
# Свернуть и вернуть настоящие окна под Wine: пять «Блокнотов» + Shchelchok.exe --selftest --hide-test --premin 1
# (одно окно «пользователь свернул сам» - после возврата оно обязано остаться свёрнутым, баг 15.10.2026).
# Третий аргумент - сколько окон развернуть на весь экран перед проверкой (по умолчанию 2): они обязаны
# вернуться развёрнутыми, а остальные - с теми же координатами и размером (владелец 17.10.2026).
# Второй аргумент - сколько окон считать «от имени администратора» (--admin-sim): уровни целостности Windows
# Wine не изображает, поэтому в программе их эмулирует тот же запрет, что ставит Windows (наши команды этим
# окнам молча не выполняются). Проверяем настоящие окна: порядок наложения, скорость, честный журнал.
B=$HOME/shchelchok_build
export WINEPREFIX=$B/wine WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
D=${1:-88}; A=${2:-0}; M=${3:-2}; [ -e /tmp/.X11-unix/X$D ] && { echo "экран :$D занят"; exit 1; }
OUT=$B/hide_test; rm -rf $OUT; mkdir -p $OUT
Xvfb :$D -screen 0 1400x900x24 >/dev/null 2>&1 &
XP=$!; sleep 2; export DISPLAY=:$D; xsetroot -solid "#203040"
setsid wine notepad >/dev/null 2>&1 & N1=$!
sleep 4
setsid wine notepad >/dev/null 2>&1 & N2=$!
sleep 3
setsid wine notepad >/dev/null 2>&1 & N3=$!
sleep 3
setsid wine notepad >/dev/null 2>&1 & N4=$!
sleep 3
setsid wine notepad >/dev/null 2>&1 & N5=$!
sleep 4
$B/venv/bin/python -c "from PIL import ImageGrab; ImageGrab.grab(xdisplay=\":$D\").save(\"$OUT/before.png\")"
setsid wine $B/win/dist/Shchelchok/Shchelchok.exe --selftest 'Z:'"${OUT//\//\\}" --hide-test --premin 1 \
  --admin-sim $A --maximize $M --no-tray >/dev/null 2>&1 & P=$!
for i in $(seq 1 80); do sleep 0.5; [ -f $OUT/hidden.flag ] && break; done
$B/venv/bin/python -c "from PIL import ImageGrab; ImageGrab.grab(xdisplay=\":$D\").save(\"$OUT/hidden.png\")"
for i in $(seq 1 80); do sleep 1; [ -f $OUT/selftest.json ] && break; done
sleep 1
$B/venv/bin/python -c "from PIL import ImageGrab; ImageGrab.grab(xdisplay=\":$D\").save(\"$OUT/after.png\")"
cat $OUT/selftest.json
for p in $P $N1 $N2 $N3 $N4 $N5; do kill -- -$p 2>/dev/null; done
wineserver -k; kill $XP
