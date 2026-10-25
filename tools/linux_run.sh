#!/bin/bash
# Запуск программы/тестов на сервере 2 под Linux (Qt нужны libEGL/xcb - лежат в ~/shchelchok_build/syslibs).
# Использование: tools/linux_run.sh <дисплей|offscreen> <команда...>
B=$HOME/shchelchok_build
export LD_LIBRARY_PATH=$B/syslibs/root/usr/lib/x86_64-linux-gnu
D=$1; shift
if [ "$D" = offscreen ]; then export QT_QPA_PLATFORM=offscreen; else export DISPLAY=$D QT_QPA_PLATFORM=xcb; fi
cd $B/src && exec "$@"
