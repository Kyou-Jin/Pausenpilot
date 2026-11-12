"""Erstellt Screenshots aller Ansichten (für die Qualitätsprüfung).

Aufruf: python tools/screenshots.py <ausgabeordner> [dark|light]
Nutzt einen temporären Datenordner mit Beispielverlauf.
"""
import os
import random
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "shots"
mode = sys.argv[2] if len(sys.argv) > 2 else "dark"
out.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp(prefix="pp_shots_"))
os.environ["PAUSENPILOT_DATA"] = str(tmp)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pausenpilot import app as appmod  # noqa: E402
from pausenpilot.models import default_timers, Settings, TimerConfig  # noqa: E402
from pausenpilot.storage import ConfigStore, History, ACTION_DONE, ACTION_SNOOZE, ACTION_SKIP  # noqa: E402

# Beispieldaten
timers = default_timers() + [TimerConfig(name="Aufstehen & ausschütteln", description="15 Minuten stehen, Schultern lockern.",
                                         interval_min=120, duration_sec=900, first_start="09:30",
                                         color="#9B7BFF", icon="🧍")]
st = Settings()
st.theme = mode
st.close_hint_shown = True
st.welcome_shown = True
ConfigStore(tmp).save(timers, st)
h = History(tmp / "history.db")
rnd = random.Random(3)
today = date.today()
for back in range(0, 40):
    d = today - timedelta(days=back)
    if d.weekday() >= 5:
        continue
    skip_p = rnd.choice([0.0, 0.0, 0.05, 0.12, 0.18, 0.25, 0.6])
    for t in timers:
        for k in range(rnd.randint(1, 4 if t.interval_min < 60 else 2)):
            ts = datetime.combine(d, datetime.min.time()) + timedelta(hours=8 + rnd.randint(0, 9), minutes=rnd.randint(0, 59))
            if back == 0 and ts > datetime.now():
                continue
            r = rnd.random()
            if r < 0.12:
                h.add(t, ACTION_SNOOZE, snoozes=1, minutes=5, ts=ts)
                h.add(t, ACTION_DONE, snoozes=1, ts=ts + timedelta(minutes=6), planned=ts)
            elif r < 0.12 + skip_p:
                h.add(t, ACTION_SKIP, ts=ts, planned=ts)
            else:
                h.add(t, ACTION_DONE, ts=ts, planned=ts)
    if back == 0:
        ps = datetime.combine(d, datetime.min.time()) + timedelta(hours=10, minutes=15)
        if ps + timedelta(minutes=20) < datetime.now():
            h.add_pause(ps, ps + timedelta(minutes=20))
        # Mittag: PC gesperrt – Augen entspannen zählt automatisch, Wasser ist ausgelassen
        la = datetime.combine(d, datetime.min.time()) + timedelta(hours=12, minutes=5)
        if la + timedelta(minutes=50) < datetime.now():
            h.add_away(la, la + timedelta(minutes=50), "lock")
            for k in range(2):
                h.add(timers[0], ACTION_DONE, ts=la + timedelta(minutes=15 + 20 * k),
                      planned=la + timedelta(minutes=15 + 20 * k), via="lock")
            h.add(timers[1], "missed", ts=la + timedelta(minutes=25), planned=la + timedelta(minutes=25), via="lock")
    if back > 0:
        ps = datetime.combine(d, datetime.min.time()) + timedelta(hours=12, minutes=rnd.randint(0, 30))
        h.add_pause(ps, ps + timedelta(minutes=rnd.choice([25, 40, 45, 60, 75])))
        if rnd.random() < 0.15:
            ps = datetime.combine(d, datetime.min.time()) + timedelta(hours=15)
            h.add_pause(ps, ps + timedelta(hours=2, minutes=10))
h.close()

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
ctrl = appmod.Controller(qapp, start_hidden=False)
ctrl.window.resize(1100, 740)
ctrl.window.move(80, 60)
steps = []


def shot(widget, name):
    widget.grab().save(str(out / f"{name}.png"))
    print("saved", name)


def s_timers():
    ctrl.show_window(0)


def s_timers_shot():
    shot(ctrl.window, f"01_timers_{mode}")


def s_cal():
    ctrl.show_window(1)
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    ctrl.calendar_page.select_day(d)


def s_cal_shot():
    shot(ctrl.window, f"02_calendar_{mode}")


def s_set():
    ctrl.show_window(2)


def s_set_shot():
    shot(ctrl.window, f"03_settings_{mode}")


def s_editor():
    from pausenpilot.editor import TimerEditor
    dlg = TimerEditor(ctrl.timers[0], ctrl.settings, ctrl.window)
    dlg.show()
    qapp.processEvents()
    QTimer.singleShot(300, lambda: (shot(dlg, f"04_editor_{mode}"), dlg.close()))


def s_welcome():
    from pausenpilot.welcome import WelcomeDialog
    dlg = WelcomeDialog(ctrl.window)
    dlg.show()
    qapp.processEvents()
    QTimer.singleShot(400, lambda: (shot(dlg, f"00_welcome_{mode}"), dlg.close()))


def s_alarm():
    t = ctrl.timers[2]
    ctrl.sched.rt[t.id].snoozes = 2
    ctrl.sched.active = t.id
    ctrl.sched.queue = [ctrl.timers[1].id]
    ctrl._show_alarm(t.id)


def s_alarm_shot():
    shot(ctrl.alarm, f"05_alarm_{mode}")


def s_run():
    ctrl.alarm._on_start()


def s_run_shot():
    shot(ctrl.alarm, f"06_countdown_{mode}")


def s_done():
    ctrl.alarm._show_done()


def s_done_shot():
    shot(ctrl.alarm, f"07_done_{mode}")


def s_alarm0():
    ctrl.alarm.close_silently()
    t = ctrl.timers[1]
    ctrl.sched.active = t.id
    ctrl.sched.queue = []
    ctrl.sched.rt[t.id].snoozes = 0
    ctrl._show_alarm(t.id)


def s_alarm0_shot():
    shot(ctrl.alarm, f"08_alarm_nocountdown_{mode}")


def s_paused():
    ctrl.pause(0)
    ctrl.sched.paused_since = datetime.now() - timedelta(minutes=47)
    ctrl.show_window(0)
    ctrl.tick()


def s_paused_shot():
    shot(ctrl.window, f"09_paused_{mode}")


seq = [s_timers, s_timers_shot, s_cal, s_cal_shot, s_set, s_set_shot, s_editor, None, s_welcome, None, s_alarm, None, s_alarm_shot,
       s_run, s_run_shot, s_done, s_done_shot, s_alarm0, None, s_alarm0_shot, s_paused, s_paused_shot]


def run(i=0):
    if i >= len(seq):
        ctrl.quit()
        return
    if seq[i]:
        seq[i]()
    QTimer.singleShot(700, lambda: run(i + 1))


QTimer.singleShot(800, run)
qapp.exec()
