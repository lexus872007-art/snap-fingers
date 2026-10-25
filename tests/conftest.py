import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    from shchelchok import brand
    brand.load_fonts()
    return app


TRACKED = []        # программы (Controller), созданные тестом: убираем за ними, даже если тест упал


@pytest.fixture(autouse=True)
def _no_leftovers():
    """После КАЖДОГО теста закрываем окна и глушим микрофон - даже если тест упал на assert.

    Иначе упавший тест оставляет открытое окно Qt и живой поток разбора звука, и pytest не завершается: на
    сервере висит процесс, а выглядит это как «тесты зависли», а не как упавшая проверка (нашла независимая
    приёмка 16.10.2026)."""
    yield
    while TRACKED:
        ctl = TRACKED.pop()
        try:
            ctl.listener.shutdown()
            for w in (getattr(ctl, "main", None), getattr(ctl, "calib", None), getattr(ctl, "toast", None)):
                if w is not None:
                    w.close()
        except Exception:  # noqa: BLE001
            pass
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            for w in list(app.topLevelWidgets()):
                w.close()
            app.processEvents()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture(autouse=True)
def _journal_to_tmp(tmp_path, monkeypatch):
    """Журнал программы - во временную папку теста (а не в настоящий %LOCALAPPDATA%)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from shchelchok import journal
    journal.set_path(str(tmp_path / "log.txt"))
    yield
    journal.set_path(None)


@pytest.fixture
def rng():
    return np.random.default_rng(12345)


def run_front(y):
    """float-сигнал -> кандидаты (кусками по 30 мс, как из микрофона)."""
    from eval import synth as S
    from shchelchok import detector as D
    fe = D.Frontend()
    a = S.to_int16(y)
    out = []
    for i in range(0, len(a), 480):
        out += fe.feed(a[i:i + 480].tolist())
    return out


def calibrated(rng, centroid=2900, bed_rms=0.003):
    """Шаблон по 3 синтетическим щелчкам одного «человека» (как окно калибровки)."""
    from eval import synth as S
    from shchelchok import detector as D
    bed = S.room(rng, 7, bed_rms)
    for k in range(3):
        S.place(bed, S.snap(rng, centroid=centroid * rng.uniform(0.96, 1.04), decay_ms=9), 1.5 + 1.5 * k)
    got = [c for c in run_front(bed) if not D.gates(c, strict=False) and c["snr"] >= 15]
    assert len(got) == 3
    assert D.calib_consistent(got)[0]
    return D.make_template(got)
