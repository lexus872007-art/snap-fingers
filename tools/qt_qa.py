#!/usr/bin/env python3
"""Проверка ровности всех окон «Щелчка» (правило владельца: «всё ровно, текст не уезжает, ничего не наезжает»)
при масштабах Windows 100/125/150/200 %: окно «Щелчок» (слушаю, пауза, нет микрофона, нужна настройка,
предупреждение о клавише), «Настройка щелчка» (начало, 2 из 3, проверка, «разные щелчки»), уведомления.
Снимки - ui/qa_out/<масштаб>/.

Проверяет: текст влезает без обрезки, элементы внутри окна и не наезжают друг на друга, шрифт не мельче 12 точек,
окна влезают в экран 1920x1080 при 150 % (1280x690 точек без панели задач), фон - фирменный перелив (не белый),
перелив движется.

    tools/linux_run.sh offscreen ../venv/bin/python tools/qt_qa.py        # код 1 - есть ошибки (ui/qa_out/qt_qa.md)
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "ui", "qa_out")
SCALES = ["1", "1.25", "1.5", "2"]
MIN_FONT = 12



def release_notes_text():
    """Настоящее «что нового» этого выпуска - первая значащая строка release_notes.txt.

    Проверять окно выдуманной короткой строкой нельзя: 18.10.2026 так и вышло - на стенде текст выпуска
    (378 знаков) не поместился в окно, а проверка вида молчала, потому что подставляла 55 знаков."""
    import os as _os
    p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "release_notes.txt")
    try:
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:400]
    except OSError:
        pass
    return "что нового - написано на сайте"

def overlap(a, b, tol=0.5):
    return not (a[2] <= b[0] + tol or b[2] <= a[0] + tol or a[3] <= b[1] + tol or b[3] <= a[1] + tol)


def inside(r, w, h, m=0.0):
    return r[0] >= m - 0.01 and r[1] >= m - 0.01 and r[2] <= w - m + 0.01 and r[3] <= h - m + 0.01


def coords(q):
    return (q.left(), q.top(), q.left() + q.width(), q.top() + q.height())


def child(scale):
    import tempfile
    # виртуальный экран 3840x2160 (при 200 % - 1920x1080 точек), иначе окна упираются в крошечный экран 800x600
    cfg = os.path.join(tempfile.mkdtemp(), "screen.json")
    with open(cfg, "w") as f:
        json.dump({"screens": [{"name": "qa", "x": 0, "y": 0, "width": 3840, "height": 2160, "logicalDpi": 96,
                                "logicalBaseDpi": 96, "dpr": 1}]}, f)
    os.environ["QT_QPA_PLATFORM"] = f"offscreen:configfile={cfg}"
    os.environ["QT_SCALE_FACTOR"] = scale
    import types
    from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage
    from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QComboBox, QKeySequenceEdit, QLabel,
                                   QPushButton, QSlider, QWidget)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    import start
    from shchelchok import brand, toast as toastmod
    from shchelchok.app import Controller
    tmp = tempfile.mkdtemp()
    pct = int(float(scale) * 100)
    out = os.path.join(OUT, f"{pct}")
    os.makedirs(out, exist_ok=True)
    errors = []

    def err(where, msg):
        errors.append(f"{where} @{pct}%: {msg}")

    def new_ctl():
        args = types.SimpleNamespace(autostart=False, hidden=False, no_tray=True, demo="x", selftest=None,
                                     settings=os.path.join(tmp, "s.json"), quit_after=0, hide_test=False)
        return Controller(app, args)

    def snap(w, name):
        app.processEvents()
        w.grab().save(os.path.join(out, name + ".png"))

    def is_brand(w, name, violet=True):
        """Фон - фирменный перелив, а не белый лист. У «Своего» цвета оттенок любой - проверяем только, что фон
        цветной и тёмный (белый фон владелец не принимает)."""
        img = w.grab().toImage().convertToFormat(QImage.Format_RGB32)
        n = r = g = b = 0
        for y in range(2, img.height() - 2, 3):
            for x in range(2, img.width() - 2, 3):
                c = QColor(img.pixel(x, y))
                r, g, b, n = r + c.red(), g + c.green(), b + c.blue(), n + 1
        r, g, b = r / n, g / n, b / n
        ok = (b > g + 15 and r > g) if violet else (max(r, g, b) - min(r, g, b) > 20)
        if not (ok and (r + g + b) / 3 < 200):
            err(name, f"фон не фирменный (средний цвет {r:.0f},{g:.0f},{b:.0f})")

    def check_widgets(d, where, violet=True):
        sz = d.size()
        if sz.width() > 1280 or sz.height() > 690:
            err(where, f"окно {sz.width()}x{sz.height()} не влезает в 1920x1080 при 150 %")
        leaves = []
        for c in d.findChildren(QWidget):
            if not c.isVisible() or c.parent() is None:
                continue
            anc, bad = c.parent(), False
            while anc is not None:
                if isinstance(anc, (QKeySequenceEdit, QComboBox)):
                    bad = True
                anc = anc.parent()
            if bad or not isinstance(c, (QLabel, QAbstractButton, QKeySequenceEdit, QComboBox, QSlider)) and \
                    c.metaObject().className() not in ("LevelMeter", "ScoreBar", "Dots", "_Dots", "_Swatch"):
                continue
            g = c.geometry()
            par = c.parentWidget()
            txt = getattr(c, "text", lambda: "")() if not isinstance(c, QComboBox) else c.currentText()
            txt = txt or c.metaObject().className()
            if not inside(coords(g), par.width(), par.height(), 0):
                err(where, f"«{txt}» вылезает за край")
            fsz = c.font().pixelSize()
            if isinstance(c, (QLabel, QAbstractButton)) and 0 < fsz < MIN_FONT:
                err(where, f"мелкий шрифт {fsz} у «{txt}»")
            if isinstance(c, QLabel) and not c.wordWrap() and c.text():
                need = c.fontMetrics().horizontalAdvance(c.text())
                if need > c.contentsRect().width() + 1:
                    err(where, f"«{c.text()}» обрезан ({need:.0f} > {c.contentsRect().width()})")
            if isinstance(c, QLabel) and c.wordWrap() and c.text():
                if c.heightForWidth(c.width()) > c.height() + 1:
                    err(where, f"«{c.text()[:40]}…» не влезает по высоте")
            if isinstance(c, (QPushButton, QCheckBox)) and c.sizeHint().width() > c.width() + 1:
                err(where, f"«{c.text()}» не влезает в кнопку")
            if isinstance(c, QComboBox) and c.fontMetrics().horizontalAdvance(c.currentText()) + 30 > c.width():
                err(where, f"выбор «{c.currentText()}» обрезан")
            tl = c.mapTo(d, c.rect().topLeft())
            leaves.append((c, txt, (tl.x(), tl.y(), tl.x() + c.width(), tl.y() + c.height())))
        for i in range(len(leaves)):
            for j in range(i + 1, len(leaves)):
                if overlap(leaves[i][2], leaves[j][2], tol=1):
                    err(where, f"«{leaves[i][1]}» наезжает на «{leaves[j][1]}»")
        is_brand(d, where, violet)

    # ---------------- окно «Щелчок»
    for st in ("main", "hidden", "mode2", "custom200", "custom40", "paused", "nomic", "needcal", "keywarn",
               "admin", "fit", "checkdone"):
        ctl = new_ctl()
        start.run_demo(ctl, st)
        w = ctl.main
        w.adjustSize()
        app.processEvents()
        if st == "keywarn" and not w.key_err.isVisible():
            err("окно/keywarn", "предупреждение о чужой клавише не показано")
        if st == "mode2" and not w.mode_warn.isVisible():
            err("окно/mode2", "предупреждение «свернуть и вернуть одной серией» не показано")
        if st == "hidden" and "вернуть" not in w.status.text().lower():
            err("окно/hidden", f"состояние «окна свёрнуты» не видно: «{w.status.text()}»")
        if st == "main" and w.mode_warn.isVisible():
            err("окно/main", "предупреждение о серии показано при одном щелчке")
        if st == "main" and "ещё раз" not in w.lead.text():
            err("окно/main", f"главное не сказано первой строкой: «{w.lead.text()}»")
        if st == "main" and "из 100" not in w.sens_l.text():
            err("окно/main", f"порог рядом с ползунком не числом: «{w.sens_l.text()}»")
        if st == "admin" and not (w.admin_l.isVisible() or w.admin_b.isVisible()):
            err("окно/admin", "про окно «от администратора» и перезапуск с правами ничего не видно")
        if st == "fit" and not w.fit_l.isVisible():
            err("окно/fit", "«Подобрать под меня» не сказал числа")
        if st == "checkdone" and not w.learn_b.isVisible():
            err("окно/checkdone", "кнопки «Это были мои щелчки - учесть» нет")
        if st.startswith("custom"):                 # «Свой» цвет: ползунок оттенка виден и подписан числом
            if not w.theme.hue_box.isVisible():
                err(f"окно/{st}", "ползунок оттенка не виден при «Своём» цвете")
            if w.theme.hue_num.text().rstrip("°") != str(w.theme.hue.value()):
                err(f"окно/{st}", f"число оттенка не совпадает с ползунком ({w.theme.hue_num.text()})")
        if st == "main" and w.theme.hue_box.isVisible():
            err("окно/main", "ползунок оттенка показан у пресета - он там ничего не меняет")
        check_widgets(w, f"окно/{st}", violet=not st.startswith("custom"))
        snap(w, f"main_{st}")
        if st == "main":
            w.t_fixed = 1.3
            a = w.grab().toImage()
            w.t_fixed = 3.3
            if a == w.grab().toImage():
                err("окно", "перелив не движется")
            w.t_fixed = 1.3
        w.close()
        ctl.listener.shutdown()

    # ---------------- «Настройка щелчка»
    for st in ("calib0", "calib2", "calibtest", "calibdone", "calibbad"):
        ctl = new_ctl()
        start.run_demo(ctl, st)
        w = ctl.calib
        w.adjustSize()
        app.processEvents()
        if st == "calib0" and "одного щелчка" not in w.lead.text().lower():
            err("настройка/calib0", "не написано, что 5 щелчков - только настройка")
        if st == "calib0" and "резко" not in w.lead.text().lower():
            err("настройка/calib0", "не сказано главное: щёлкать надо резко")
        if st in ("calibtest", "calibdone") and "из 100" not in w.result.text():
            err(f"настройка/{st}", "итог настройки не числом")
        check_widgets(w, f"настройка/{st}")
        snap(w, f"calib_{st}")
        w.close()
        ctl.listener.shutdown()

    # ---------------- окно «Вышла новая версия»
    for st, auto in (("update", False),):
        ctl = new_ctl()
        start.run_demo(ctl, "main")
        ctl.open_update({"version": "9.9.9", "notes": release_notes_text()}, auto=auto)
        w = ctl.update_win
        w.t_fixed = 1.3
        w.adjustSize()
        app.processEvents()
        if not (w.go_b.isVisible() and w.later_b.isVisible()):
            err("обновление", "кнопок «Обновить» и «Позже» не видно")
        check_widgets(w, "обновление")
        snap(w, "update")
        w.close()
        ctl.main.close()
        ctl.listener.shutdown()

    # ---------------- уведомления
    ctl = new_ctl()
    t = ctl.toast
    cases = [("admin", "Окно от администратора",
              "1 окно не слушается без прав - включите «Запускать с правами администратора» в окне «Щелчок»."),
             ("hide", "Свернул", "7 окон. Щёлкните ещё раз или Ctrl+Alt+Z - верну все окна."),
             ("restore_admin", "Вернул", "окна на месте, кроме 1 окна от администратора."),
             ("hide_single", "Свернул", "7 окон. Щёлкните ещё раз или Ctrl+Alt+Z - верну."),
             ("restore", "Вернул", "все окна на месте (12 окон)."), ("nothing", "Вернул", "Возвращать нечего."),
             ("busy", "Клавиша занята", "Ctrl+Alt+PgDown - занято другой программой. Поменяйте в окне «Щелчок»."),
             ("mic", "Новый микрофон", "«Микрофон (Realtek High Definition Audio)» - настройте щелчок (3 щелчка)."),
             ("nomic", "Не слышу микрофон",
              "Не получилось включить микрофон. Проверьте, что он подключён и разрешён в Windows")]
    fmt = QFontMetricsF(brand.font(16, QFont.ExtraBold))
    fmx = QFontMetricsF(brand.font(13, QFont.DemiBold))
    for name, title, text in cases:
        t.show_message(title, text, ms=60000)
        L = t.lay
        if fmt.horizontalAdvance(title) > L["title"].width():
            err(f"уведомление/{name}", "заголовок не влезает")
        for ln in L["lines"]:
            if fmx.horizontalAdvance(ln) > L["text"].width() + 0.5:
                err(f"уведомление/{name}", f"строка не влезает «{ln}»")
        if len(toastmod.wrap(text, fmx, L["text"].width())) > len(L["lines"]):
            err(f"уведомление/{name}", "текст обрезан (больше 4 строк)")
        for rn, r in (("заголовок", coords(L["title"])), ("текст", coords(L["text"])), ("закрыть", coords(L["close"]))):
            if not inside(r, t.width(), t.height(), 4):
                err(f"уведомление/{name}", f"«{rn}» вылезает {r}")
        if overlap(coords(L["text"]), coords(L["close"])):
            err(f"уведомление/{name}", "текст наезжает на крестик")
        is_brand(t, f"уведомление/{name}")
        snap(t, f"toast_{name}")
        t.hide()
    # значок
    from shchelchok.brand import app_icon_image
    app_icon_image(64).save(os.path.join(out, "icon64.png"))
    app_icon_image(64, paused=True).save(os.path.join(out, "icon64_paused.png"))
    ctl.listener.shutdown()
    print(json.dumps(errors, ensure_ascii=False))


def main():
    if "--child" in sys.argv:
        child(sys.argv[sys.argv.index("--child") + 1])
        return 0
    os.makedirs(OUT, exist_ok=True)
    allerr = []
    for s in SCALES:
        r = subprocess.run([sys.executable, __file__, "--child", s], capture_output=True, text=True)
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith("[")]
        if r.returncode != 0 or not lines:
            allerr.append(f"масштаб {s}: проверка упала\n{r.stderr[-2000:]}")
            continue
        allerr += json.loads(lines[-1])
    with open(os.path.join(OUT, "qt_qa.md"), "w", encoding="utf-8") as f:
        f.write("# Проверка ровности окон\n\n" + ("\n".join(f"- {e}" for e in allerr) if allerr else "Ошибок нет.") + "\n")
    print(f"ошибок: {len(allerr)}")
    for e in allerr:
        print(" -", e)
    return 1 if allerr else 0


if __name__ == "__main__":
    sys.exit(main())
