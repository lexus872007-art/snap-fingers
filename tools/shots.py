#!/usr/bin/env python3
"""Снимки состояний программы на своём виртуальном экране (сервер 2). Linux-версия Qt или Windows-сборка под Wine.

    python3 tools/shots.py linux  <папка> [--display 64] [--scale 1.5]  [--states idle,draw,...]
    python3 tools/shots.py wine   <папка> [--display 65] [--dpi 144] [--exe путь\\Shchelchok.exe]

Правило сервера 2 (12.10): свой номер экрана (не :99/:100 - там Flow), убиваем ТОЛЬКО свои процессы по PID.
"""
import argparse
import os
import signal
import subprocess
import sys
import time

B = os.path.expanduser("~/shchelchok_build")
SRC = os.path.join(B, "src")
STATES = ["main", "hidden", "check", "main_green", "main_red", "main_graphite", "calibtest_teal", "paused", "nomic", "needcal", "keywarn", "calib0", "calib2", "calibtest", "calibbad", "toast_hide", "toast_restore", "toast_busy"]
BUSY = {"99", "100"}


def grab(display, path, crop_dark=False):
    from PIL import ImageGrab
    im = ImageGrab.grab(xdisplay=f":{display}")
    im.save(path)
    return im


def start_xvfb(display, size="1600x1000x24", extra=()):
    if display in BUSY or os.path.exists(f"/tmp/.X11-unix/X{display}"):
        sys.exit(f"экран :{display} занят - возьмите другой")
    p = subprocess.Popen(["Xvfb", f":{display}", "-screen", "0", size, *extra],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    return p


def kill_own(p):
    """Только свой процесс и его группа (запущен через setsid)."""
    if p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["linux", "wine"])
    ap.add_argument("out")
    ap.add_argument("--display", default=None)
    ap.add_argument("--scale", default="1")
    ap.add_argument("--dpi", default="96")
    ap.add_argument("--exe", default=None)
    ap.add_argument("--states", default=",".join(STATES))
    ap.add_argument("--wait", type=float, default=None)
    a = ap.parse_args()
    disp = a.display or ("64" if a.mode == "linux" else "65")
    os.makedirs(a.out, exist_ok=True)
    x = start_xvfb(disp)
    env = dict(os.environ, DISPLAY=f":{disp}")
    tmp = os.path.join(B, "tmp_shots")
    os.makedirs(tmp, exist_ok=True)
    try:
        if a.mode == "wine":
            env.update(WINEPREFIX=os.path.join(B, "wine"), WINEDEBUG="-all", WINEDLLOVERRIDES="mscoree,mshtml=")
            subprocess.run(["wine", "reg", "add", r"HKCU\Control Panel\Desktop", "/v", "LogPixels", "/t", "REG_DWORD",
                            "/d", a.dpi, "/f"], env=env, capture_output=True)
            subprocess.run(["wineserver", "-k"], env=env, capture_output=True)
            time.sleep(1)
        for st in a.states.split(","):
            sfile = os.path.join(tmp, "settings.json")
            if os.path.exists(sfile):
                os.remove(sfile)
            if a.mode == "linux":
                cmd = [os.path.join(SRC, "tools", "linux_run.sh"), f":{disp}", "../venv/bin/python", "start.py"]
                env2 = dict(env, QT_SCALE_FACTOR=a.scale)
                setf, shots = sfile, os.path.join(tmp, "shots")
            else:
                cmd = ["wine", a.exe]
                env2 = env
                setf = "Z:" + sfile.replace("/", "\\")
                shots = "Z:" + os.path.join(tmp, "shots").replace("/", "\\")
            demo, _, theme = st.partition("_")
            if theme not in ("green", "red", "graphite", "teal", "blue", "orange", "pink"):
                demo, theme = st, ""
            cmd += ["--demo", demo, "--settings", setf, "--no-tray", "--quit-after", "40"]
            if theme:
                cmd += ["--theme", theme]
            p = subprocess.Popen(cmd, env=env2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            wait = a.wait or (6 if a.mode == "linux" else 14)
            time.sleep(wait)
            grab(disp, os.path.join(a.out, f"{st}.png"))
            kill_own(p)
            if a.mode == "wine":
                subprocess.run(["wineserver", "-k"], env=env, capture_output=True)
            time.sleep(0.5)
            print("снимок", st, flush=True)
    finally:
        if a.mode == "wine":
            subprocess.run(["wine", "reg", "add", r"HKCU\Control Panel\Desktop", "/v", "LogPixels", "/t",
                            "REG_DWORD", "/d", "96", "/f"], env=env, capture_output=True)
            subprocess.run(["wineserver", "-k"], env=env, capture_output=True)
        x.terminate()
        x.wait(5)


if __name__ == "__main__":
    main()
