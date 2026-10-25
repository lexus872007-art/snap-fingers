#!/bin/bash
# Обновление ПОВЕРХ старой версии под Wine: делаем вид, что стоит 1.0.0 (version.txt + запись в реестре) и что у
# пользователя своя настройка (калибровка, цвет, клавиша, режим), запускаем Setup.exe с сервера 3 и проверяем:
#   - на экране «Было: <старая> → Стало: <новая>», вопросов нет;
#   - settings.json (калибровка!) не изменился - сравниваем побайтово;
#   - version.txt и DisplayVersion стали новыми.
# Запуск:  tools/wine/update_test.sh [экран] [какая версия якобы стоит]
B=$HOME/shchelchok_build
export WINEPREFIX=$B/wine WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
D=${1:-92}; OLD=${2:-1.0.1}          # экран и версия, которая якобы стоит
[ -e /tmp/.X11-unix/X$D ] && { echo "экран :$D занят"; exit 1; }
T=$B/update_test; rm -rf $T; mkdir -p $T; cd $T
curl -s -O https://ty-biznesmen.ru/apps/shchelchok/Shchelchok-Setup.exe
Xvfb :$D -screen 0 1400x900x24 >/dev/null 2>&1 &
XP=$!; sleep 2; export DISPLAY=:$D; xsetroot -solid "#203040"
LA=$(wine cmd /c echo %LOCALAPPDATA% 2>/dev/null | tr -d "\r"); U=$(winepath -u "$LA" 2>/dev/null)
AD=$(wine cmd /c echo %APPDATA% 2>/dev/null | tr -d "\r"); UA=$(winepath -u "$AD" 2>/dev/null)
DEST="$U/Programs/Щелчок"; CFG="$UA/Щелчок"
mkdir -p "$DEST" "$CFG"
echo -n "$OLD" > "$DEST/version.txt"
wine reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\TyBiznesmen-shchelchok" \
  /v DisplayVersion /t REG_SZ /d "$OLD" /f >/dev/null 2>&1
cat > "$CFG/settings.json" <<'JSON'
{
 "listening": true, "mode": 2, "sens": 7, "mic": "Микрофон (Гарнитура)",
 "templates": {"Микрофон (Гарнитура)": {"shape": [-14.3, -12.0, -11.0, -9.5, -8.6, -6.0, -4.9, 1.6, 6.5, 9.4, 9.9, 8.5, 7.5, 3.9],
   "dec": [-3.1, -7.2, -15.8, -27.0, -33.5, -35.0], "peak_min": -14.0, "snr_min": 38.0, "centroid": 3010.0,
   "spread": 2.1, "n": 3, "peak_mean": -12.0, "peak_max": -10.0}},
 "single_restores": true, "mute": true, "unmute": false, "toast": false, "ignore_output": false,
 "ignore_typing": true, "hotkeys": {"toggle": "Ctrl+Alt+Y"}, "autostart": true, "first_run": false,
 "theme": "graphite", "hue": 120
}
JSON
md5sum "$CFG/settings.json" > $T/settings.md5
setsid wine $T/Shchelchok-Setup.exe >/dev/null 2>&1 &
P=$!
for s in 5 7 9 11; do          # поймать экран со строкой «Было: 1.0.0 → Стало: 1.0.1» (скачивание ~7 с)
  sleep 2
  $B/venv/bin/python -c "from PIL import ImageGrab; ImageGrab.grab(xdisplay=\":$D\").save(\"$T/update_$s.png\")"
done
for i in $(seq 1 90); do sleep 2; grep -qv "^$OLD$" "$DEST/version.txt" 2>/dev/null && break; done
sleep 4
$B/venv/bin/python -c "from PIL import ImageGrab; ImageGrab.grab(xdisplay=\":$D\").save(\"$T/update_done.png\")"
echo "--- version.txt: $(cat "$DEST/version.txt")"
echo "--- реестр:"; wine reg query "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\TyBiznesmen-shchelchok" 2>/dev/null | tr -d "\r" | grep -E "DisplayVersion|DisplayName"
echo "--- настройки не тронуты:"; md5sum -c $T/settings.md5 && cat "$CFG/settings.json" | head -3
echo "--- в журнале установки:"
grep -iE "установлена сейчас|установлено" "$WINEPREFIX/drive_c/users/$USER/Temp/shchelchok-install.log" 2>/dev/null | tail -3
kill -- -$P 2>/dev/null; wineserver -k; kill $XP
