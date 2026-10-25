"""Звук Windows через Core Audio (ctypes, COM вручную - без лишних библиотек). На Linux - заглушки.

- OutputMeter: поток опрашивает громкость того, что ИГРАЕТ компьютер (IAudioMeterInformation::GetPeakValue
  устройства вывода по умолчанию, каждые 10 мс). Удар в звуке компьютера (музыка, видео, звонок) в тот же момент,
  что и «щелчок» в микрофоне, - значит, это не щелчок, а звук из динамиков. Звук не записывается - только число
  громкости.
- Там же раз в 2 с - какой микрофон сейчас «по умолчанию» (подключили гарнитуру - надо переподключиться).
- mute_get / mute_set: выключить и вернуть звук компьютера (IAudioEndpointVolume).
"""
from __future__ import annotations

import sys
import threading
import time
from collections import deque

WIN = sys.platform == "win32"

if WIN:
    import ctypes
    from ctypes import wintypes as wt

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wt.DWORD), ("d2", wt.WORD), ("d3", wt.WORD), ("d4", ctypes.c_ubyte * 8)]

        def __init__(self, s):
            super().__init__()
            s = s.strip("{}").replace("-", "")
            self.d1, self.d2, self.d3 = int(s[0:8], 16), int(s[8:12], 16), int(s[12:16], 16)
            for i in range(8):
                self.d4[i] = int(s[16 + 2 * i:18 + 2 * i], 16)

    CLSID_ENUM = GUID("BCDE0395-E52F-467C-8E3D-C4579291692E")
    IID_ENUM = GUID("A95664D2-9614-4F35-A746-DE8DB63617E6")
    IID_METER = GUID("C02216F6-8C67-4B5B-9D00-D008E73E0064")
    IID_VOLUME = GUID("5CDF2C82-841E-4546-9722-0CF74078229A")
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wt.DWORD]
    ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_void_p)]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    HR = ctypes.c_long

    def _call(obj, idx, *types_and_args):
        """Вызов метода COM по номеру в таблице: _call(p, 4, (c_int, 0), (POINTER(c_void_p), byref(x)))."""
        vt = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        proto = ctypes.WINFUNCTYPE(HR, ctypes.c_void_p, *[t for t, _ in types_and_args])
        return proto(vt[idx])(obj, *[a for _, a in types_and_args])

    def _release(obj):
        if obj:
            try:
                _call(obj, 2)
            except Exception:  # noqa: BLE001
                pass

    def _enumerator():
        p = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(CLSID_ENUM), None, 0x17, ctypes.byref(IID_ENUM), ctypes.byref(p))
        return p if hr == 0 and p else None

    def _default(enum, flow):
        """flow 0 - вывод, 1 - микрофон; роль eConsole."""
        dev = ctypes.c_void_p()
        hr = _call(enum, 4, (ctypes.c_int, flow), (ctypes.c_int, 0), (ctypes.POINTER(ctypes.c_void_p), ctypes.byref(dev)))
        return dev if hr == 0 and dev else None

    def _dev_id(dev):
        s = ctypes.c_wchar_p()
        if _call(dev, 5, (ctypes.POINTER(ctypes.c_wchar_p), ctypes.byref(s))) == 0 and s:
            v = s.value
            ole32.CoTaskMemFree(s)
            return v
        return None

    def _activate(dev, iid):
        out = ctypes.c_void_p()
        hr = _call(dev, 3, (ctypes.c_void_p, ctypes.byref(iid)), (wt.DWORD, 0x17), (ctypes.c_void_p, None),
                   (ctypes.POINTER(ctypes.c_void_p), ctypes.byref(out)))
        return out if hr == 0 and out else None


class OutputMeter:
    """Поток: громкость звука компьютера каждые 10 мс (последние 3 с) и микрофон по умолчанию.

    hit(t) -> True, если около момента t (time.monotonic) в звуке компьютера был удар/всплеск."""

    def __init__(self):
        self.hist = deque(maxlen=300)          # (время, пик 0..1)
        self.capture_id = None                 # микрофон Windows по умолчанию (меняется - переподключаемся)
        self.ok = False                        # счётчик громкости работает
        self._stop = threading.Event()
        self._th = None

    def start(self):
        if not WIN or self._th is not None:
            return
        self._th = threading.Thread(target=self._run, name="output-meter", daemon=True)
        self._th.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        try:
            ole32.CoInitializeEx(None, 0)
        except Exception:  # noqa: BLE001
            return
        enum = meter = None
        next_refresh = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_refresh:
                next_refresh = now + 2.0
                try:
                    if enum is None:
                        enum = _enumerator()
                    if enum is not None:
                        _release(meter)
                        meter = None
                        dev = _default(enum, 0)
                        if dev is not None:
                            meter = _activate(dev, IID_METER)
                            _release(dev)
                        cap = _default(enum, 1)
                        self.capture_id = _dev_id(cap) if cap is not None else None
                        _release(cap)
                except Exception:  # noqa: BLE001
                    meter = None
            if meter is not None:
                v = ctypes.c_float()
                try:
                    if _call(meter, 3, (ctypes.POINTER(ctypes.c_float), ctypes.byref(v))) == 0:
                        self.hist.append((now, float(v.value)))
                        self.ok = True
                except Exception:  # noqa: BLE001
                    meter = None
            self._stop.wait(0.01)
        _release(meter)
        _release(enum)

    def hit(self, t, before=0.15, after=0.15, min_peak=0.03, jump=2.0):
        """Был ли около t всплеск в звуке компьютера: пик в окне >= min_peak и в jump раз выше обычного
        (медиана за 1 с до окна). Ровная музыка без ударов не мешает, удар барабана/щелчок в видео - мешает."""
        return output_hit(list(self.hist), t, before, after, min_peak, jump)


def output_hit(hist, t, before=0.15, after=0.15, min_peak=0.03, jump=2.0):
    win = [v for (ts, v) in hist if t - before <= ts <= t + after]
    if not win:
        return False
    peak = max(win)
    if peak < min_peak:
        return False
    base = sorted(v for (ts, v) in hist if t - before - 1.0 <= ts < t - before)
    med = base[len(base) // 2] if base else 0.0
    return peak >= jump * med + 0.01


def mute_get():
    """Выключен ли звук компьютера: True/False, None - не узнать."""
    if not WIN:
        return None
    return _volume(lambda vol: _get_mute(vol))


def mute_set(on):
    if not WIN:
        return False
    return bool(_volume(lambda vol: _call(vol, 14, (wt.BOOL, bool(on)), (ctypes.c_void_p, None)) == 0))


def _get_mute(vol):
    b = wt.BOOL()
    if _call(vol, 15, (ctypes.POINTER(wt.BOOL), ctypes.byref(b))) == 0:
        return bool(b.value)
    return None


def _volume(fn):
    try:
        ole32.CoInitializeEx(None, 2)      # в главном потоке Qt COM уже есть - вызов безвреден
    except Exception:  # noqa: BLE001
        pass
    enum = dev = vol = None
    try:
        enum = _enumerator()
        if enum is None:
            return None
        dev = _default(enum, 0)
        if dev is None:
            return None
        vol = _activate(dev, IID_VOLUME)
        if vol is None:
            return None
        return fn(vol)
    except Exception:  # noqa: BLE001
        return None
    finally:
        _release(vol)
        _release(dev)
        _release(enum)
