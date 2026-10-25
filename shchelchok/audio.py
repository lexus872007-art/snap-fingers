# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Микрофон -> детектор щелчка в отдельном потоке. Звук никуда не пишется: блоки по 30 мс сразу разбираются и
забываются (в памяти только последние ~0,5 с для разбора удара).

- общий режим Windows (MME через sounddevice): микрофон НЕ забирается - Local Voice, Zoom и Teams продолжают
  работать с ним одновременно;
- переподключение: микрофон отключили/сменили (вынули гарнитуру, Windows сменила «по умолчанию»), поток
  замолчал > 2,5 с или упал - обновляем список устройств (sd._terminate()/_initialize(), как в Local Voice) и
  открываем заново; не вышло - пробуем каждые 3 с, на экране «Не слышу микрофон»;
- умер поток разбора (его не должно быть, но если) - сторож поднимает новый;
- КАЖДОЕ переподключение попадает в журнал (journal.py): молча глохнуть программа не имеет права.

Часы потока (главный баг 16.10.2026). Решение о щелчках Clicker принимает по времени ПОТОКА (сколько звука
разобрано), а не по часам компьютера. Раньше при переподключении микрофона фронтенд начинал время с нуля, а в
Clicker оставались старые отметки (пауза после срабатывания) - и программа глохла ровно на столько секунд, сколько
проработала до переподключения (через час работы - на час). Теперь часы потока не обнуляются
(front.reset(keep_clock=True)), недосчитанная серия сбрасывается (clicker.drop_pending()), а момент удара для
защиты «клавиатура/звук компьютера» считается от времени потока, а не от отдельного счётчика сэмплов.
"""
from __future__ import annotations

import queue
import threading
import time
from array import array
from collections import deque

from . import detector, journal

SR = detector.SR
BLOCK = 480                     # 30 мс
SKIP_INPUTS = ("stereo mix", "стерео микшер", "переназнач", "mapper", "primary sound capture", "первичный драйвер")


def _sd():
    import sounddevice as sd
    return sd


def list_mics(sd=None):
    """Имена микрофонов (по одному на устройство, из MME - общий режим). [] - звука нет."""
    try:
        sd = sd or _sd()
        devs = sd.query_devices()
        apis = sd.query_hostapis()
    except Exception:  # noqa: BLE001
        return []
    mme = next((i for i, a in enumerate(apis) if "MME" in a.get("name", "")), None)
    out = []
    for d in devs:
        if d.get("max_input_channels", 0) <= 0:
            continue
        if mme is not None and d.get("hostapi") != mme:
            continue
        name = d.get("name", "").strip()
        low = name.lower()
        if not name or name in out or any(s in low for s in SKIP_INPUTS):
            continue
        out.append(name)
    return out


def find_device(sd, name):
    if not name:
        return None
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0 and d.get("name", "").strip() == name:
                return i
    except Exception:  # noqa: BLE001
        pass
    return -1                      # такого микрофона сейчас нет


class Listener:
    """Поток разбора звука. Наружу (в окно, по таймеру): drain() -> события, срабатывания; level_db; state.

    state: "off" - выключен, "on" - слушаю, "nomic" - микрофона нет/не открылся (жду и пробую снова)."""

    STALL_S = 2.5
    RETRY_S = 3.0

    def __init__(self, guard=None, sd_module=None):
        self.det = detector.Detector(guard=None)
        self.guard = guard                       # guard(time.monotonic()) -> причина или None
        self.det.guard = self._guard
        self._sd = sd_module
        self.stream = None
        self.device = ""
        self.device_name = ""
        self.state = "off"
        self.error = None
        self.q = queue.Queue(maxsize=200)
        self.out = deque(maxlen=500)
        self.lock = threading.Lock()
        self.last_data = 0.0
        self.last_try = 0.0
        self.capture_id = None
        self.reconnects = 0
        self.revivals = 0                        # сколько раз сторож поднимал поток разбора
        self.errors = 0                          # сбоев разбора звука (в журнал)
        self.last_reconnect = None               # (время, причина) - для журнала и окна
        self._map = (0.0, 0.0)                   # (monotonic, время потока) конца последнего блока
        self._stop = threading.Event()
        self._worker = None
        self._start_worker()

    # ------------------------------------------------------------ поток разбора
    def _start_worker(self):
        self._worker = threading.Thread(target=self._work, name="snap-detector", daemon=True)
        self._worker.start()

    def worker_alive(self):
        return self._worker is not None and self._worker.is_alive()

    # ------------------------------------------------------------ поток микрофона
    @property
    def sd(self):
        if self._sd is None:
            self._sd = _sd()
        return self._sd

    def start(self, device=""):
        """Открыть микрофон (общий режим). None - получилось, иначе текст ошибки для человека."""
        self.close_stream()
        self.device = device or ""
        self.state = "nomic"
        self.last_try = time.monotonic()
        try:
            sd = self.sd
        except Exception as e:  # noqa: BLE001
            self.error = "Микрофон недоступен на этом компьютере"
            journal.write(f"микрофон: звук недоступен ({type(e).__name__})")
            return self.error
        dev = find_device(sd, self.device)
        tries = ([dev] if dev not in (None, -1) else []) + [None]     # выбранного нет - микрофон Windows
        last = None
        for d in tries:
            try:
                st = sd.RawInputStream(samplerate=SR, blocksize=BLOCK, channels=1, dtype="int16", device=d,
                                       callback=self._cb)
                st.start()
                self.stream = st
                self.device_name = self._name(sd, d)
                self.state = "on"
                self.error = None
                self.last_data = time.monotonic()
                journal.write(f"микрофон открыт: «{self.device_name or 'как в Windows'}»")
                return None
            except Exception as e:  # noqa: BLE001
                last = e
                continue
        self.error = "Не получилось включить микрофон. Проверьте, что он подключён и разрешён в Windows"
        journal.write(f"микрофон не открылся ({type(last).__name__}: {last})" if tries else "микрофонов нет")
        return self.error

    @staticmethod
    def _name(sd, d):
        """Имя микрофона, который реально открыт (для «как в Windows» - тот, что сейчас по умолчанию)."""
        try:
            info = sd.query_devices(d) if d is not None else sd.query_devices(kind="input")
            return str(info.get("name", "")).strip()
        except Exception:  # noqa: BLE001
            return ""

    def _cb(self, indata, frames, t, status):
        now = time.monotonic()
        self.last_data = now
        try:
            self.q.put_nowait((bytes(indata), now))
        except queue.Full:
            pass

    def close_stream(self):
        s, self.stream = self.stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:  # noqa: BLE001
                pass

    def stop(self):
        self.close_stream()
        self.state = "off"

    def shutdown(self):
        self.stop()
        self._stop.set()

    def refresh_devices(self):
        """Обновить список устройств PortAudio (новая гарнитура видна только после этого)."""
        try:
            sd = self.sd
            sd._terminate()
            sd._initialize()
        except Exception:  # noqa: BLE001
            pass

    def stream_active(self):
        """Поток микрофона ещё жив? (у sounddevice обращение к active умеет бросать - это тоже «умер»)."""
        if self.stream is None:
            return True
        try:
            return bool(self.stream.active)
        except Exception:  # noqa: BLE001
            return False

    def watchdog(self, capture_id=None, now=None):
        """Раз в секунду из окна: поток замолк/упал, умер поток разбора или сменился микрофон Windows ->
        поднять заново и записать в журнал. -> True, если переподключались."""
        if self.state == "off":
            return False
        now = time.monotonic() if now is None else now
        if not self.worker_alive():                    # поток разбора умер - поднимаем (без него программа глухая)
            self.revivals += 1
            self._start_worker()
            journal.write(f"сторож: поток разбора звука умер - поднял заново (раз {self.revivals})")
        changed = capture_id is not None and self.capture_id is not None and capture_id != self.capture_id \
            and not self.device
        if capture_id is not None:
            self.capture_id = capture_id
        silent = self.state == "on" and now - self.last_data > self.STALL_S
        dead = self.state == "on" and (silent or not self.stream_active())
        retry = self.state == "nomic" and now - self.last_try >= self.RETRY_S
        if not (changed or dead or retry):
            return False
        why = ("микрофон Windows сменился" if changed else
               f"нет звука {now - self.last_data:.0f} с" if silent else
               "поток микрофона упал" if dead else "микрофона не было - пробую снова")
        self.close_stream()
        self.refresh_devices()
        self.reconnects += 1
        self.last_reconnect = (now, why)
        # часы потока НЕ обнуляем: иначе пауза после срабатывания в Clicker окажется «в будущем» и программа
        # перестанет отвечать на щелчки на столько секунд, сколько проработала до этого (баг 16.10.2026)
        self.det.front.reset(keep_clock=True)
        self.det.clicker.drop_pending()
        self.start(self.device)
        journal.write(f"микрофон переподключён ({why}): {'слушаю' if self.state == 'on' else 'не вышло'} "
                      f"(раз {self.reconnects}, время потока {self.det.front.t:.0f} с)")
        if self.state == "on":
            self.last_data = now
        else:
            self.last_try = now
        return True

    # ------------------------------------------------------------ разбор
    def _guard(self, t_stream):
        """Время потока -> время компьютера (monotonic) по последнему блоку: защита «клавиатура/мышь/звук
        компьютера» сравнивает удар с нажатиями клавиш, а они в часах компьютера."""
        if self.guard is None:
            return None
        return self.guard(self.mono_of(t_stream))

    def mono_of(self, t_stream):
        mono, end = self._map
        return mono - (end - t_stream)

    def feed_samples(self, samples, mono=None):
        """Разобрать блок (из потока микрофона или из теста)."""
        mono = time.monotonic() if mono is None else mono
        # время потока считает ТОЛЬКО фронтенд (один счётчик вместо двух - иначе после переподключения
        # защита получала время удара на минуты в прошлом)
        self._map = (mono, self.det.front.t + len(samples) / SR)
        events, fired = self.det.feed(samples)
        self._map = (mono, self.det.front.t)
        miss = self.det.clicker.take_miss()
        with self.lock:
            for e in events:
                e["mono"] = self.mono_of(e["t"])
                self.out.append(("event", e))
            if miss is not None:
                self.out.append(("miss", miss))          # серия не сложилась - строка в журнал
            for _, action in fired:
                self.out.append(("fire", action))        # "hide" - свернуть, "restore" - вернуть
        return events, fired

    def _work(self):
        while not self._stop.is_set():
            try:
                data, mono = self.q.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                self.feed_samples(array("h", data), mono)
            except Exception as e:  # noqa: BLE001
                self.errors += 1
                if self.errors in (1, 10, 100, 1000):      # в журнал, но не строкой на каждый блок
                    journal.write(f"разбор звука: сбой {type(e).__name__}: {e} (всего {self.errors})")

    def drain(self):
        with self.lock:
            out = list(self.out)
            self.out.clear()
        return out

    @property
    def level_db(self):
        return self.det.front.level_db
