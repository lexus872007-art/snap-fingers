#!/bin/bash
# Настоящая установка по ссылке с сервера 3 под Wine (свой экран, свой префикс), затем запуск установленной программы.
B=$HOME/shchelchok_build
export WINEPREFIX=$B/wine WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
D=${1:-69}; [ -e /tmp/.X11-unix/X$D ] && { echo "экран :$D занят"; exit 1; }
T=$B/e2e_install; rm -rf $T; mkdir -p $T; cd $T
curl -s -O https://ty-biznesmen.ru/apps/shchelchok/Shchelchok-Setup.exe
# ставим НАЧИСТО: иначе install.id и запись в реестре остаются от прошлой установки и проверка показывает
# старую версию, не дождавшись новой (16.10.2026)
LA0=$(wine cmd /c echo %LOCALAPPDATA% 2>/dev/null | tr -d "\r"); U0=$(winepath -u "$LA0" 2>/dev/null)
rm -rf "$U0/Programs/Щелчок"
wine reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\TyBiznesmen-shchelchok" /f >/dev/null 2>&1
Xvfb :$D -screen 0 1400x900x24 >/dev/null 2>&1 &
XP=$!; sleep 2; export DISPLAY=:$D; xsetroot -solid "#203040"
setsid wine $T/Shchelchok-Setup.exe >/dev/null 2>&1 &
P=$!
LA=$(wine cmd /c echo %LOCALAPPDATA% 2>/dev/null | tr -d "\r"); U=$(winepath -u "$LA" 2>/dev/null)
DEST="$U/Programs/Щелчок"
for i in $(seq 1 90); do sleep 2; [ -f "$DEST/install.id" ] && break; done
sleep 3
$B/venv/bin/python -c "from PIL import ImageGrab; ImageGrab.grab(xdisplay=\":$D\").save(\"$T/install_done.png\")"
echo "PROGRAM DIR: $DEST"; ls "$DEST" | head; echo "--- uninstall.ps1"; cat "$DEST/uninstall.ps1"
echo "--- реестр"; wine reg query "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\TyBiznesmen-shchelchok" 2>/dev/null | tr -d "\r"
kill -- -$P 2>/dev/null; wineserver -k; sleep 1
setsid wine "$DEST/Shchelchok.exe" >/dev/null 2>&1 &
P=$!; sleep 30
$B/venv/bin/python -c "from PIL import ImageGrab; ImageGrab.grab(xdisplay=\":$D\").save(\"$T/installed_running.png\")"
xdotool search --onlyvisible --name "^(Щелчок|Настройка щелчка)$" >/dev/null && echo "УСТАНОВЛЕННАЯ ПРОГРАММА ЗАПУЩЕНА" || echo "ПЛАШКИ НЕТ"
kill -- -$P 2>/dev/null; wineserver -k; kill $XP
