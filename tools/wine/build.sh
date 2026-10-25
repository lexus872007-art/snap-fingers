#!/bin/bash
# Сборка Windows-версии под Wine (сервер 2): программа (onedir) -> zip, установщик (onefile).
#   tools/wine/build.sh 1.0.2      -> ~/shchelchok_build/release/{Shchelchok-<версия>.zip, Shchelchok-Setup.exe, latest.json}
set -e
B=$HOME/shchelchok_build
# Версия - из shchelchok/__init__.py (её же показывает окно); другой номер в аргументе - ошибка
VV=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' $B/src/shchelchok/__init__.py)
V=${1:-$VV}
[ "$V" = "$VV" ] || { echo "версия $V не равна shchelchok/__init__.py ($VV)"; exit 1; }
export WINEPREFIX=$B/wine WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
PY="C:\\Python312\\python.exe"
cd $B/src && tools/linux_run.sh offscreen ../venv/bin/python tools/make_icon.py
rm -rf $B/win && mkdir -p $B/win && rsync -a --exclude tests --exclude __pycache__ --exclude qa_out --exclude screens $B/src/ $B/win/
cd $B/win
wine $PY -m PyInstaller --noconfirm --clean Shchelchok.spec > $B/build_app.log 2>&1 || { echo "APP FAIL"; tail -30 $B/build_app.log; exit 1; }
# Перечень открытых компонентов и полные тексты лицензий лежат в licenses/ и попадают в сборку через
# Shchelchok.spec (datas). Собирает их python3 ~/office_tools/_brand/tools/make_licenses.py.
test -s licenses/"Сторонние компоненты.txt" || { echo "НЕТ licenses/Сторонние компоненты.txt"; exit 1; }
cd loader && wine $PY -m PyInstaller --noconfirm --clean --distpath ../dist --workpath ../build_loader Setup.spec > $B/build_loader.log 2>&1 || { echo "LDR FAIL"; tail -30 $B/build_loader.log; exit 1; }
cd $B/win/dist
mkdir -p $B/release && rm -f $B/release/*
(cd Shchelchok && python3 -c "
import os, zipfile, sys
z = zipfile.ZipFile(sys.argv[1], 'w', zipfile.ZIP_DEFLATED, compresslevel=9)
for root, _, files in os.walk('.'):
    for f in files:
        p = os.path.join(root, f); z.write(p, os.path.relpath(p, '.'))
z.close()" $B/release/Shchelchok-$V.zip)
cp Shchelchok-Setup.exe $B/release/
python3 - "$B/release" "$V" "$B/src/release_notes.txt" <<'PY'
import hashlib, json, os, sys
d, v, notes_file = sys.argv[1], sys.argv[2], sys.argv[3]
z = f"Shchelchok-{v}.zip"
p = os.path.join(d, z)
h = hashlib.sha256(open(p, "rb").read()).hexdigest()
setup = os.path.join(d, "Shchelchok-Setup.exe")
sh = hashlib.sha256(open(setup, "rb").read()).hexdigest()
# «что нового» - из release_notes.txt (первая строка): текст берёт САМА ПРОГРАММА при самообновлении,
# поэтому он лежит в latest.json, а не зашит в код (владелец 17.10.2026)
notes = ""
try:
    for line in open(notes_file, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            notes = line
            break
except OSError:
    pass
json.dump({"version": v, "zip": z, "sha256": h, "size": os.path.getsize(p), "exe": "Shchelchok.exe",
           "title": "Щелчок", "setup": "Shchelchok-Setup.exe", "setup_sha256": sh,
           "setup_size": os.path.getsize(setup), "notes": notes},
          open(os.path.join(d, "latest.json"), "w", encoding="utf-8"), ensure_ascii=False)
PY
du -sh $B/win/dist/Shchelchok; ls -la $B/release; cat $B/release/latest.json; echo BUILD_DONE
