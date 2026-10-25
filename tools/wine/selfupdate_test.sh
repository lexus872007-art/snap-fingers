#!/bin/bash
# САМООБНОВЛЕНИЕ целиком, под Wine и с настоящего сервера (владелец 17.10.2026).
# Ставим СТАРУЮ выложенную версию (её архив лежит на сервере 3), запускаем и ждём: программа сама посмотрит
# latest.json, увидит новую версию, покажет окно «Вышла версия X», скачает установщик, проверит sha256,
# запустит установку поверх и закроется. Проверяем, что версия в папке стала новой, а настройки целы.
#   tools/wine/selfupdate_test.sh [экран] [старая версия]
B=$HOME/shchelchok_build
export WINEPREFIX=$B/wine WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
D=${1:-71}; OLD=${2:-1.4.1}
[ -e /tmp/.X11-unix/X$D ] && { echo "экран :$D занят"; exit 1; }
T=$B/selfupdate_test; rm -rf $T; mkdir -p $T; cd $T
# «старая версия»: если рядом есть своя сборка с этим номером - берём её (так проверяется НОВЫЙ код против
# настоящего сервера), иначе качаем ту, что выложена
if [ -f "$B/release/Shchelchok-$OLD.zip" ]; then
  echo "== берём старую версию $OLD из своей сборки"
  cp "$B/release/Shchelchok-$OLD.zip" old.zip
else
  echo "== берём старую версию $OLD с сервера"
  curl -s -o old.zip https://ty-biznesmen.ru/apps/shchelchok/Shchelchok-$OLD.zip || { echo "нет архива $OLD"; exit 1; }
fi
LA=$(wine cmd /c echo %LOCALAPPDATA% 2>/dev/null | tr -d "\r"); U=$(winepath -u "$LA" 2>/dev/null)
AD=$(wine cmd /c echo %APPDATA% 2>/dev/null | tr -d "\r"); UA=$(winepath -u "$AD" 2>/dev/null)
DEST="$U/Programs/Щелчок"; CFG="$UA/Щелчок"
rm -rf "$DEST" "$CFG"; mkdir -p "$DEST" "$CFG"
python3 -c "import zipfile,sys; zipfile.ZipFile('old.zip').extractall(sys.argv[1])" "$DEST"
echo -n "$OLD" > "$DEST/version.txt"
wine reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\TyBiznesmen-shchelchok" \
  /v DisplayVersion /t REG_SZ /d "$OLD" /f >/dev/null 2>&1
# настройки человека: своя калибровка, свой цвет, своя клавиша - после самообновления обязаны остаться
cat > "$CFG/settings.json" <<'JSON'
{
 "listening": true, "mode": 2, "sens": 7, "thr": 52, "mic": "Микрофон (Гарнитура)",
 "templates": {"Микрофон (Гарнитура)": {"shape": [-14.3, -12.0, -11.0, -9.5, -8.6, -6.0, -4.9, 1.6, 6.5, 9.4, 9.9, 8.5, 7.5, 3.9],
   "dec": [-3.1, -7.2, -15.8, -27.0, -33.5, -35.0], "peak_min": -14.0, "snr_min": 38.0, "centroid": 3010.0,
   "spread": 2.1, "n": 3, "peak_mean": -12.0, "peak_max": -10.0}},
 "mute": true, "unmute": false, "toast": false, "ignore_output": false, "ignore_typing": true,
 "hotkeys": {"toggle": "Ctrl+Alt+Y"}, "autostart": true, "first_run": false, "theme": "graphite", "hue": 120,
 "updates": true, "update_auto": false, "update_last": 0, "update_failed": false, "update_later": "", "update_asked": 0
}
JSON
# сравнивать весь файл нельзя: программа сама пишет туда свои отметки (когда смотрели сервер) - сверяем
# ИМЕННО настройки человека
python3 - "$CFG/settings.json" > $T/settings_before.json <<'PY2'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
keys = ("theme", "hue", "mode", "thr", "sens", "mic", "templates", "hotkeys", "mute", "unmute", "toast",
        "ignore_output", "ignore_typing", "autostart", "first_run", "updates", "update_auto")
print(json.dumps({k: d.get(k) for k in keys}, ensure_ascii=False, sort_keys=True))
PY2
Xvfb :$D -screen 0 1400x900x24 >/dev/null 2>&1 &
XP=$!; sleep 2; export DISPLAY=:$D; xsetroot -solid "#203040"
echo "== запускаем старую версию (первая проверка - через 2 минуты после старта)"
setsid wine "$DEST/Shchelchok.exe" --no-tray >/dev/null 2>&1 &
P=$!
SHOT() { $B/venv/bin/python -c "from PIL import ImageGrab; ImageGrab.grab(xdisplay=\":$D\").save(\"$T/$1.png\")"; }
for i in $(seq 1 100); do                 # ждём окно «Вышла новая версия» (не дольше ~5 минут)
  sleep 4
  xdotool search --onlyvisible --name "новая версия" >/dev/null 2>&1 && { echo "ОКНО «ВЫШЛА НОВАЯ ВЕРСИЯ» ПОЯВИЛОСЬ (через $((i*4)) c)"; break; }
done
SHOT offer
echo "--- журнал программы:"; grep -i "обновлен" "$CFG/log.txt" 2>/dev/null | tail -5
echo "== нажимаем «Обновить»"
xdotool search --onlyvisible --name "новая версия" windowactivate --sync key --clearmodifiers Return 2>/dev/null
sleep 6; SHOT downloading
for i in $(seq 1 90); do                  # ждём, пока установщик положит новую версию
  sleep 4
  [ "$(cat "$DEST/version.txt" 2>/dev/null)" != "$OLD" ] && break
done
sleep 5; SHOT installed
echo "--- version.txt: $(cat "$DEST/version.txt" 2>/dev/null)"
echo "--- реестр:"; wine reg query "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\TyBiznesmen-shchelchok" 2>/dev/null | tr -d "\r" | grep -E "DisplayVersion|DisplayName"
echo "--- настройки человека не тронуты:"
python3 - "$CFG/settings.json" "$T/settings_before.json" <<'PY2'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
was = json.load(open(sys.argv[2], encoding="utf-8"))
now = {k: d.get(k) for k in was}
if now == was:
    print("ДА - все настройки человека на месте (цвет, клавиша, порог, калибровка)")
else:
    print("НЕТ, изменилось:", {k: (was[k], now[k]) for k in was if was[k] != now[k]})
PY2
echo "--- журнал (хвост):"; tail -12 "$CFG/log.txt" 2>/dev/null
echo "--- журнал установки:"; tail -5 "$WINEPREFIX/drive_c/users/$USER/Temp/shchelchok-install.log" 2>/dev/null
kill -- -$P 2>/dev/null; wineserver -k; kill $XP
echo "снимки: $T/offer.png $T/downloading.png $T/installed.png"
