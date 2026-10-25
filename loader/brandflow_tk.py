# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Фирменный перелив для окон tkinter (установщики линейки) - та же формула, что brand-flow.js и плашка Local Voice.

Цвет точки = LUT[(0.8·x + 0.45·y + фаза) mod 1] + два световых пятна exp(-((x-cx)² + 2.5·(y-cy)²)·9)·(28 + 60·energy).
Без numpy и PIL (установщик - маленький файл):
- полосы зависят только от u = 0.8·x/W + 0.45·y/H, поэтому они рисуются ОДИН раз широкой картинкой (ширина окна +
  один период по x = W/0.8) и при анимации картинка просто сдвигается влево: сдвиг на d точек = фаза + 0.8·d/W.
  Смещение каждой строки - срез одной длинной строки байтов (быстро, на чистом Python);
- пятно - полупрозрачная белая картинка (PNG с альфой, функция раскладывается: exp(-9dx²)·exp(-22.5dy²)),
  двигается по тем же синусоидам. Прибавка +A к каналу заменена смешиванием с белым (α = A·g/125) - на глаз то же.
Анимация 18 кадров/с через after(); окно свёрнуто - кадры не рисуются. static=True - один неподвижный кадр формулы.

    flow = Flow(canvas, w, h)      # создать ДО текста и полосок - перелив ляжет под них
    flow.work(True)                # идёт установка: speed 0.35, пятна ярче (energy 0.45)
"""
import base64
import math
import struct
import time
import zlib

PALETTE = [(49, 10, 110), (91, 33, 182), (139, 92, 246), (192, 132, 252), (109, 40, 217), (67, 20, 150)]
N = 512


def lut():
    pal = PALETTE + [PALETTE[0]]
    n = len(pal) - 1
    out = []
    for i in range(N):
        p = i / (N - 1) * n
        j = min(int(p), n - 1)
        f = p - j
        out.append(bytes(int(pal[j][c] + (pal[j + 1][c] - pal[j][c]) * f) for c in range(3)))
    return out


def png(width, height, rows, alpha):
    """PNG из строк байтов (RGB или RGBA) - tkinter.PhotoImage(data=...) читает его без PIL."""
    raw = b"".join(b"\x00" + r for r in rows)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 1)) +
                            chunk(b"IEND", b""))


def stripes(w, h, phase=0.0):
    """Строки картинки полос шириной w + w/0.8 (запас на сдвиг) - точная формула, фаза phase."""
    period = w / 0.8                                  # на столько точек по x u меняется на 1
    ww = w + int(math.ceil(period)) + 2
    dy = 0.45 / 0.8 * w / h                           # сдвиг строки на 1 вниз = столько точек по x
    total = ww + int(math.ceil(dy * h)) + 2
    L = lut()
    line = b"".join(L[int((((0.8 * i / w) + phase) % 1.0) * (N - 1))] for i in range(total))
    rows = []
    for y in range(h):
        o = int(round(y * dy)) * 3
        rows.append(line[o:o + ww * 3])
    return ww, rows, period


def spot(w, h, amp):
    """Пятно: белое с альфой amp·exp(-((dx)² + 2.5·dy²)·9)/125; dx, dy - доли окна; размер покрывает альфу >= 1/255."""
    sx, sy = int(w * 0.7), int(h * 0.45)             # полуразмеры
    gx = [math.exp(-9 * ((i - sx) / w) ** 2) for i in range(2 * sx + 1)]
    k = 255 * amp / 125.0
    rows = []
    for j in range(2 * sy + 1):
        gy = k * math.exp(-22.5 * ((j - sy) / h) ** 2)
        row = bytearray(b"\xff" * (4 * len(gx)))
        row[3::4] = bytes(min(255, int(gy * g)) for g in gx)
        rows.append(bytes(row))
    return 2 * sx + 1, 2 * sy + 1, rows


class Flow:
    IDLE, WORK = (0.08, 0.0), (0.35, 0.45)

    def __init__(self, canvas, w, h, fps=18, static=False):
        import tkinter as tk
        self.c, self.w, self.h, self.static = canvas, w, h, static
        self.dt = int(1000 / fps)
        ww, rows, self.period = stripes(w, h)
        self.img = tk.PhotoImage(data=png(ww, len(rows), rows, False))
        self.spots = {}
        for name, (_, en) in (("idle", self.IDLE), ("work", self.WORK)):
            sw, sh, srows = spot(w, h, 28 + 60 * en)
            self.spots[name] = tk.PhotoImage(data=png(sw, sh, srows, True))
        self.item = canvas.create_image(0, 0, image=self.img, anchor="nw")
        self.s_items = [canvas.create_image(0, 0, image=self.spots["idle"], anchor="center") for _ in range(2)]
        self.speed, self.target, self.mode = self.IDLE[0], self.IDLE[0], "idle"
        self.phase, self.t0, self.last = 0.0, time.monotonic(), None
        self.frames, self.busy = 0, 0.0
        self.draw(1.2 if static else 0.0)
        if not static:
            canvas.after(self.dt, self.tick)

    def work(self, on):
        self.target = (self.WORK if on else self.IDLE)[0]
        self.mode = "work" if on else "idle"
        for it in self.s_items:
            self.c.itemconfigure(it, image=self.spots[self.mode])
        if self.static:
            self.draw(1.2)

    def draw(self, t):
        off = (self.phase % 1.0) * self.period          # фаза +f = картинка левее на f·период: полосы вверх-влево
        self.c.coords(self.item, -off, 0)
        for k, (fx, fy) in enumerate(((0.9, 0.6), (0.6, 0.9))):
            cx = 0.5 + 0.45 * math.sin(t * fx + k * 2.1)
            cy = 0.5 + 0.45 * math.cos(t * fy + k * 1.3)
            self.c.coords(self.s_items[k], cx * self.w, cy * self.h)

    def tick(self):
        try:
            now = time.monotonic()
            dt = min(0.1, now - self.last) if self.last else 0.0
            self.last = now
            self.speed += (self.target - self.speed) * min(1.0, dt * 3)
            self.phase += dt * self.speed
            if self.c.winfo_viewable():                  # свёрнуто - не рисуем
                t0 = time.perf_counter()
                self.draw(now - self.t0)
                self.c.update_idletasks()
                self.busy += time.perf_counter() - t0
                self.frames += 1
            self.c.after(self.dt, self.tick)
        except Exception:  # noqa: BLE001 - окно закрыто
            pass
