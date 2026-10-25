"""Микрофон: общий режим, запасной микрофон, переподключение (замолк, сменился, пропал, умер поток разбора),
события с временем, часы потока после переподключения (баг 16.10.2026 - «щелчок работает только когда запускаешь»).
"""
import time

import numpy as np

from conftest import calibrated
from eval import synth as S
from shchelchok import audio, journal


class FakeStream:
    def __init__(self, sd, **kw):
        self.sd, self.kw = sd, kw
        self.active = False
        if sd.fail_devices is not None and kw.get("device") in sd.fail_devices:
            raise OSError("нет устройства")
        sd.opened.append(kw.get("device"))

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        pass


class FakeSD:
    def __init__(self, devices=None, fail=None):
        self.devices = devices or [{"name": "Микрофон (Realtek)", "max_input_channels": 2, "hostapi": 0},
                                   {"name": "Динамики", "max_input_channels": 0, "hostapi": 0},
                                   {"name": "Гарнитура", "max_input_channels": 1, "hostapi": 0}]
        self.fail_devices = fail
        self.opened = []
        self.reinit = 0

    def query_devices(self, d=None, kind=None):
        if kind == "input":
            return self.devices[0]
        if d is not None:
            return self.devices[d]
        return self.devices

    def query_hostapis(self):
        return [{"name": "MME"}]

    def RawInputStream(self, **kw):
        return FakeStream(self, **kw)

    def _terminate(self):
        self.reinit += 1

    def _initialize(self):
        pass


def test_list_mics_only_inputs():
    assert audio.list_mics(FakeSD()) == ["Микрофон (Realtek)", "Гарнитура"]


def test_shared_mode_16k_int16():
    sd = FakeSD()
    li = audio.Listener(sd_module=sd)
    assert li.start("") is None and li.state == "on"
    kw = li.stream.kw
    assert kw["samplerate"] == 16000 and kw["dtype"] == "int16" and kw["channels"] == 1
    assert "extra_settings" not in kw          # без монопольного режима WASAPI - микрофон остаётся общим
    li.shutdown()


def test_chosen_mic_missing_falls_back_to_default():
    sd = FakeSD()
    li = audio.Listener(sd_module=sd)
    assert li.start("USB-микрофон, которого нет") is None
    assert sd.opened == [None] and li.device_name == "Микрофон (Realtek)"
    li.shutdown()


def test_chosen_mic_used():
    sd = FakeSD()
    li = audio.Listener(sd_module=sd)
    li.start("Гарнитура")
    assert sd.opened == [2] and li.device_name == "Гарнитура"
    li.shutdown()


def test_no_mic_then_retry_every_3s():
    sd = FakeSD(fail={None, 0, 2})
    li = audio.Listener(sd_module=sd)
    assert li.start("") is not None and li.state == "nomic"
    t0 = time.monotonic()
    assert not li.watchdog(now=t0 + 1)                  # рано
    sd.fail_devices = None                              # микрофон подключили
    assert li.watchdog(now=t0 + 3.5)
    assert li.state == "on" and sd.reinit == 1          # список устройств обновлён перед открытием
    li.shutdown()


def test_stalled_stream_reconnects():
    sd = FakeSD()
    li = audio.Listener(sd_module=sd)
    li.start("")
    now = time.monotonic()
    li.last_data = now - 5                               # поток молчит 5 с (вынули USB)
    assert li.watchdog(now=now)
    assert sd.reinit == 1 and li.state == "on" and li.reconnects == 1
    li.shutdown()


def test_default_mic_changed_reconnects():
    sd = FakeSD()
    li = audio.Listener(sd_module=sd)
    li.start("")
    now = time.monotonic()
    li.last_data = now
    assert not li.watchdog("{id-ноутбук}", now=now)
    assert li.watchdog("{id-гарнитура}", now=now)      # Windows сменила микрофон по умолчанию
    assert sd.reinit == 1
    li.shutdown()


def test_chosen_mic_ignores_default_change():
    sd = FakeSD()
    li = audio.Listener(sd_module=sd)
    li.start("Гарнитура")
    now = time.monotonic()
    li.last_data = now
    li.watchdog("{a}", now=now)
    assert not li.watchdog("{b}", now=now)
    li.shutdown()


def test_paused_listener_never_reconnects():
    sd = FakeSD()
    li = audio.Listener(sd_module=sd)
    li.stop()
    assert not li.watchdog("{x}", now=time.monotonic() + 100) and sd.opened == []
    li.shutdown()


def test_events_and_fire_with_monotonic_times():
    rng = np.random.default_rng(3)
    tpl = calibrated(np.random.default_rng(1))
    li = audio.Listener(sd_module=FakeSD())
    li.det.template = tpl
    y = S.room(rng, 4, 0.003)
    S.place(y, S.snap(rng, centroid=2900, decay_ms=9), 1.0)
    a = S.to_int16(y)
    base = 1000.0
    for i in range(0, len(a), 480):
        li.feed_samples(a[i:i + 480].tolist(), mono=base + (i + 480) / 16000)
    out = li.drain()
    ev = [e for k, e in out if k == "event"]
    assert len(ev) == 1 and abs(ev[0]["mono"] - (base + 1.0)) < 0.02
    assert any(k == "fire" for k, _ in out)
    li.shutdown()


def test_guard_blocks_with_reason():
    rng = np.random.default_rng(3)
    tpl = calibrated(np.random.default_rng(1))
    seen = []

    def guard(mono):
        seen.append(mono)
        return "клавиатура или мышь"
    li = audio.Listener(guard=guard, sd_module=FakeSD())
    li.det.template = tpl
    y = S.room(rng, 4, 0.003)
    S.place(y, S.snap(rng, centroid=2900, decay_ms=9), 1.0)
    a = S.to_int16(y)
    for i in range(0, len(a), 480):
        li.feed_samples(a[i:i + 480].tolist(), mono=50.0 + (i + 480) / 16000)
    out = li.drain()
    assert not any(k == "fire" for k, _ in out)
    ev = [e for k, e in out if k == "event"]
    assert ev[0]["reason"] == "клавиатура или мышь" and abs(seen[0] - 51.0) < 0.02
    li.shutdown()


# ---------------------------------------------------------------- сторож: программа не имеет права оглохнуть
def quiet_then_snap(li, rng, base, seconds=1.0, n=1):
    """Подать звук: тишина, затем n щелчков. -> срабатывания."""
    y = S.room(rng, seconds + 1.5, 0.003)
    for k in range(n):
        S.place(y, S.snap(rng, centroid=2900, decay_ms=9), seconds + 0.4 * k)
    a = S.to_int16(y)
    for i in range(0, len(a), 480):
        li.feed_samples(a[i:i + 480].tolist(), mono=base + (i + 480) / 16000)
    return [f for k, f in li.drain() if k == "fire"]


def listener_with_template(sd=None, guard=None):
    li = audio.Listener(guard=guard, sd_module=sd or FakeSD())
    li.det.template = calibrated(np.random.default_rng(1))
    li.start("")
    return li


def test_stream_clock_continues_after_reconnect():
    """Часы потока при переподключении не обнуляются: иначе пауза после срабатывания окажется «в будущем»."""
    rng = np.random.default_rng(3)
    li = listener_with_template()
    quiet_then_snap(li, rng, 1000.0, seconds=3.0)
    t_before, block = li.det.front.t, li.det.clicker.block_until
    now = time.monotonic()
    li.last_data = now - 5
    assert li.watchdog(now=now) and li.reconnects == 1
    assert li.det.front.t >= t_before                       # время потока идёт дальше
    assert block == li.det.clicker.block_until              # саму паузу не выбрасываем - она в том же времени
    # глухота после переподключения - не больше обычной паузы 1,5 с (раньше была равна времени работы программы)
    assert li.det.clicker.block_until - li.det.front.t <= li.det.clicker.cooldown
    li.shutdown()


def test_snap_still_fires_after_reconnect():
    """ГЛАВНЫЙ баг владельца 16.10.2026: «щелчок работает только когда запускаешь». Программа поработала, микрофон
    переподключился - щелчки обязаны срабатывать дальше (раньше глохла на столько секунд, сколько проработала)."""
    rng = np.random.default_rng(3)
    li = listener_with_template()
    assert quiet_then_snap(li, rng, 1000.0, seconds=20.0) == ["hide"]
    li.det.clicker.hidden = False
    now = time.monotonic()
    li.last_data = now - 5
    li.watchdog(now=now)
    assert quiet_then_snap(li, rng, 2000.0, seconds=1.0) == ["hide"], "после переподключения программа оглохла"
    li.shutdown()


def test_guard_gets_right_time_after_reconnect():
    """Защита «клавиатура/мышь/звук компьютера» сравнивает удар с часами компьютера: после переподключения время
    удара не должно уехать в прошлое (иначе защита молча перестаёт работать)."""
    rng = np.random.default_rng(3)
    seen = []
    li = listener_with_template(guard=lambda m: seen.append(m))
    quiet_then_snap(li, rng, 1000.0, seconds=20.0)
    now = time.monotonic()
    li.last_data = now - 5
    li.watchdog(now=now)
    seen.clear()
    quiet_then_snap(li, rng, 5000.0, seconds=1.0)
    assert seen and abs(seen[0] - 5001.0) < 0.05, f"защита получила время удара {seen}"
    li.shutdown()


def test_dead_parse_thread_revived_and_written_to_journal():
    """Поток разбора звука умер - сторож поднимает новый и пишет об этом в журнал (молча глохнуть нельзя)."""
    from shchelchok import journal
    sd = FakeSD()
    li = audio.Listener(sd_module=sd)
    li.start("")
    li._stop.set()                                  # «умер»
    li._worker.join(timeout=2)
    assert not li.worker_alive()
    li._stop.clear()
    li.watchdog(now=time.monotonic())
    assert li.worker_alive() and li.revivals == 1
    assert any("поток разбора" in s for s in journal.tail(40))
    li.shutdown()


def test_reconnect_written_to_journal():
    sd = FakeSD()
    li = audio.Listener(sd_module=sd)
    li.start("")
    now = time.monotonic()
    li.last_data = now - 5
    li.watchdog(now=now)
    lines = journal.tail(40)
    assert any("микрофон переподключён" in s and "нет звука" in s for s in lines), lines
    li.shutdown()


def test_broken_stream_counts_as_dead():
    """sounddevice умеет бросать исключение на обращении к active - это тоже «поток умер»."""
    sd = FakeSD()
    li = audio.Listener(sd_module=sd)
    li.start("")
    now = time.monotonic()
    li.last_data = now
    class Boom:
        @property
        def active(self):
            raise OSError("PortAudio")
        def stop(self):
            pass
        def close(self):
            pass
    li.stream = Boom()
    assert not li.stream_active()
    assert li.watchdog(now=now) and li.state == "on"
    li.shutdown()


def test_half_series_not_carried_over_the_gap():
    """В звуке был разрыв: недосчитанный щелчок не должен склеиваться с щелчком после переподключения."""
    sd = FakeSD()
    li = audio.Listener(sd_module=sd)
    li.start("")
    li.det.clicker.push(1.0, True, 0.0)
    assert li.det.clicker.hits
    now = time.monotonic()
    li.last_data = now - 5
    li.watchdog(now=now)
    assert li.det.clicker.hits == [] and li.det.clicker.decide_at is None
    li.shutdown()
