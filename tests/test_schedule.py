"""Tests der Zeitplanung (ohne Qt). Ausführen: python -m pytest tests  oder  python tests/test_schedule.py"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pausenpilot.models import DayWindow, Settings, TimerConfig  # noqa: E402
from pausenpilot import schedule as S  # noqa: E402

# 2026-11-09 ist ein Montag
MON = datetime(2026, 11, 9)


def settings(**kw):
    s = Settings()
    s.idle_detect = kw.get("idle", False)
    return s


def T(interval=20, first="08:00", dur=20, enabled=True):
    return TimerConfig(name="t", interval_min=interval, first_start=first, duration_sec=dur, enabled=enabled)


def at(h, m=0, s=0, day=MON):
    return day.replace(hour=h, minute=m, second=s)


def test_first_slot_before_window():
    assert S.next_slot(T(), settings(), at(6)) == at(8)


def test_grid_alignment():
    assert S.next_slot(T(20, "08:00"), settings(), at(10, 7)) == at(10, 20)
    assert S.next_slot(T(60, "08:10"), settings(), at(10, 10)) == at(10, 10)


def test_first_start_before_window_start():
    st = settings()
    st.days[0] = DayWindow(True, "09:00", "17:00")
    assert S.next_slot(T(20, "07:50"), st, at(6)) == at(9, 10)


def test_after_window_goes_next_day_first_start():
    assert S.next_slot(T(60, "08:30"), settings(), at(18, 5)) == at(8, 30, day=MON + timedelta(days=1))


def test_weekend_skipped():
    fri = MON + timedelta(days=4)
    assert S.next_slot(T(60, "08:00"), settings(), at(19, day=fri)) == at(8, day=MON + timedelta(days=7))


def test_after_completion_rebases():
    assert S.after_completion(T(20), settings(), at(10, 3, 30)) == at(10, 23, 30)


def test_after_completion_crosses_window_end():
    assert S.after_completion(T(60, "08:10"), settings(), at(17, 30)) == at(8, 10, day=MON + timedelta(days=1))


def test_no_window_returns_none():
    st = settings()
    for d in st.days:
        d.enabled = False
    assert S.next_slot(T(), st, at(8)) is None


def test_midnight_end():
    st = settings()
    st.days[0] = DayWindow(True, "20:00", "00:00")
    assert S.next_slot(T(30, "20:00"), st, at(23, 40)) is None or True  # kein Crash
    assert S.next_slot(T(30, "20:00"), st, at(23, 10)) == at(23, 30)


def tick(sc, now, idle=0.0):
    sc.last_tick = now - timedelta(seconds=1)  # simuliert sekündlichen Takt
    return sc.tick(now, idle)


def make(timers, now, **kw):
    sc = S.Scheduler(timers, settings(**kw))
    sc.restore({}, now)
    return sc


def test_alarm_and_queue_and_complete():
    a, b = T(20, "08:00"), T(60, "08:00")
    sc = make([a, b], at(7, 59, 59))
    ev = sc.tick(at(8))
    assert ev == [("alarm", a.id)] or ev == [("alarm", b.id)]
    first = ev[0][1]
    assert len(sc.queue) == 1
    snoozes, planned = sc.complete(first, at(8, 1))
    assert planned == at(8)
    assert sc.tick(at(8, 1, 1)) == []  # kurze Atempause
    ev = sc.tick(at(8, 1, 4))
    assert ev and ev[0][0] == "alarm" and ev[0][1] != first


def test_snooze_counts_and_reschedules():
    a = T(20)
    sc = make([a], at(7, 59))
    sc.tick(at(8))
    assert sc.snooze(a.id, 5, at(8, 0, 10)) == 1
    assert sc.rt[a.id].due == at(8, 5, 10)
    assert tick(sc, at(8, 5, 10)) == [("alarm", a.id)]
    assert sc.snooze(a.id, 5, at(8, 5, 20)) == 2
    tick(sc, at(8, 10, 20))
    snoozes, planned = sc.complete(a.id, at(8, 11))
    assert snoozes == 2 and planned == at(8)
    assert sc.rt[a.id].snoozes == 0


def test_idle_reschedules_missed():
    a = T(20)
    sc = make([a], at(7, 59), idle=True)
    sc.settings.idle_minutes = 5
    sc.tick(at(7, 59, 30), idle_seconds=0)
    ev = tick(sc, at(8, 10), 600)
    assert ("away",) in ev and not any(e[0] == "alarm" for e in ev)
    ev = tick(sc, at(8, 10, 1), 0)
    assert ev[0][0] == "returned"
    assert sc.rt[a.id].due == at(8, 30, 1)


def test_locked_screen_means_away_immediately():
    for idle_detect in (True, False):
        a = T(20)
        sc = make([a], at(7, 59), idle=idle_detect)
        sc.tick(at(7, 59, 30))
        # gesperrt nach 30 s ohne Eingabe – weit unter der Leerlauf-Grenze
        sc.last_tick = at(7, 59, 59)
        ev = sc.tick(at(8, 0), 30, locked=True)
        assert ("away",) in ev and not any(e[0] == "alarm" for e in ev), ev
        sc.last_tick = at(8, 4, 59)
        assert not any(e[0] == "alarm" for e in sc.tick(at(8, 5), 330, locked=True))
        # entsperrt → zurück, Erinnerung startet ab jetzt neu
        sc.last_tick = at(8, 5, 59)
        ev = sc.tick(at(8, 6), 1, locked=False)
        assert any(e[0] == "returned" for e in ev) or not idle_detect, ev
        assert sc.away_since is None
        assert sc.rt[a.id].due == at(8, 26), sc.rt[a.id].due


def test_away_ended_reports_span_and_missed_slots():
    eye, water = T(20, "08:00"), T(60, "08:00", dur=0)
    sc = make([eye, water], at(9, 59), idle=True)
    sc.settings.idle_minutes = 5
    sc.tick(at(9, 59, 30))
    sc.rt[eye.id].due, sc.rt[water.id].due = at(10, 0), at(11, 0)
    sc.last_tick = at(9, 59, 59)
    sc.tick(at(10, 0) - timedelta(seconds=1), 10, locked=True)
    assert sc.away_reason == "lock"
    sc.last_tick = at(11, 4, 59)
    sc.tick(at(11, 5), 3900, locked=True)
    sc.last_tick = at(11, 5, 59)
    ev = sc.tick(at(11, 6), 1, locked=False)
    ended = [e for e in ev if e[0] == "away_ended"]
    assert len(ended) == 1, ev
    _, since, until, reason, missed = ended[0]
    assert reason == "lock" and until == at(11, 6) and since <= at(10, 0)
    assert sorted(d for tid, d in missed if tid == eye.id) == [at(10), at(10, 20), at(10, 40), at(11)]
    assert [d for tid, d in missed if tid == water.id] == [at(11)]
    assert sc.away_since is None and sc.away_missed == []


def test_idle_away_reason_and_sleep_gap_event():
    a = T(20)
    sc = make([a], at(9, 59), idle=True)
    sc.settings.idle_minutes = 5
    sc.tick(at(9, 59, 30))
    sc.last_tick = at(10, 9, 59)
    sc.tick(at(10, 10), 600)
    assert sc.away_reason == "idle"
    sc.last_tick = at(10, 10, 59)
    ev = sc.tick(at(10, 11), 0)
    assert [e[3] for e in ev if e[0] == "away_ended"] == ["idle"]
    # Standby ohne vorherige Abwesenheit
    sc.last_tick = at(10, 30)
    ev = sc.tick(at(11, 30), 0)
    sl = [e for e in ev if e[0] == "away_ended"]
    assert sl and sl[0][3] == "sleep" and sl[0][1] == at(10, 30) and sl[0][4], ev


def test_sleep_gap_reschedules():
    a = T(20)
    sc = make([a], at(7, 50))
    ev = sc.tick(at(9, 0))
    assert ev[0][0] == "returned"
    assert sc.rt[a.id].due == at(9, 20)
    assert not any(e[0] == "alarm" for e in ev)


def test_pause_and_resume():
    a = T(20)
    sc = make([a], at(7, 59))
    sc.pause(at(9), at(7, 59, 1))
    for m in range(0, 60):
        assert not any(e[0] == "alarm" for e in sc.tick(at(8, m)))
    sc.resume(at(8, 59, 30))
    assert sc.rt[a.id].due == at(9, 19, 30)


def test_disable_closes_alarm():
    a = T(20)
    sc = make([a], at(7, 59))
    sc.tick(at(8))
    a2 = TimerConfig.from_dict({**a.to_dict(), "enabled": False})
    closed = sc.apply_config([a2], sc.settings, at(8, 0, 5), {a.id})
    assert closed == [a.id] and sc.active is None


def test_delete_closes_alarm():
    a = T(20)
    sc = make([a], at(7, 59))
    sc.tick(at(8))
    closed = sc.apply_config([], sc.settings, at(8, 0, 5), set())
    assert closed == [a.id] and sc.active is None


def test_restore_keeps_future_due():
    a = T(20)
    sc = make([a], at(9))
    sc.snooze(a.id, 5, at(9))   # due 09:05
    snap = sc.snapshot()
    sc2 = S.Scheduler([a], settings())
    sc2.restore(snap, at(9, 2))
    assert sc2.rt[a.id].due == at(9, 5)


def test_restore_past_due_uses_grid():
    a = T(20)
    sc2 = S.Scheduler([a], settings())
    sc2.restore({"timers": {a.id: {"due": at(9).isoformat()}}}, at(11, 7))
    assert sc2.rt[a.id].due == at(11, 20)


def test_trigger_now():
    a = T(60)
    sc = make([a], at(9, 1))
    sc.trigger_now(a.id, at(9, 2))
    assert sc.tick(at(9, 2, 1)) == [("alarm", a.id)]


def test_settings_change_moves_out_of_window_due():
    a = T(60, "08:00")
    sc = make([a], at(16, 30))
    assert sc.rt[a.id].due == at(17)
    st = settings()
    st.days[0] = DayWindow(True, "08:00", "16:45")
    sc.apply_config([a], st, at(16, 31), set())
    assert sc.rt[a.id].due == at(8, day=MON + timedelta(days=1))


def test_enable_weekend_pulls_due_forward():
    sat = MON + timedelta(days=5)
    a = T(60, "08:00")
    sc = make([a], at(10, day=sat))
    assert sc.rt[a.id].due == at(8, day=MON + timedelta(days=7))
    st = settings()
    st.days[5] = DayWindow(True, "08:00", "18:00")
    sc.apply_config([a], st, at(10, day=sat), set())
    assert sc.rt[a.id].due == at(10, day=sat)


def test_transient_bad_window_recovers():
    a = T(60, "08:00")
    sc = make([a], at(14))
    bad = settings()
    bad.days[0] = DayWindow(True, "08:00", "01:00")
    sc.apply_config([a], bad, at(14), set())
    good = settings()
    good.days[0] = DayWindow(True, "08:00", "19:00")
    sc.apply_config([a], good, at(14, 0, 2), set())
    assert sc.rt[a.id].due.date() == MON.date()


def test_snooze_outside_window_goes_to_next_slot():
    a = T(60, "08:00")
    sc = make([a], at(16, 59, 59))
    tick(sc, at(17))
    sc.snooze(a.id, 15, at(17, 50))   # 18:05 – außerhalb
    ev = tick(sc, at(18, 5))
    assert not any(e[0] == "alarm" for e in ev)
    assert sc.rt[a.id].due == at(8, day=MON + timedelta(days=1)) and sc.rt[a.id].snoozes == 0


def test_away_while_prompt_open_reschedules_queue():
    a, b = T(20, "08:00"), T(20, "08:10")
    sc = make([a, b], at(7, 59), idle=True)
    tick(sc, at(8))
    for m in range(1, 100):
        tick(sc, at(8 + m // 60, m % 60), m * 60)
    ev = tick(sc, at(9, 40), 0)
    assert any(e[0] == "returned" for e in ev)
    assert b.id not in sc.queue and sc.rt[b.id].due > at(9, 40)


def test_pause_closes_open_prompt_as_skip():
    a = T(20)
    sc = make([a], at(7, 59))
    tick(sc, at(8))
    sc.snooze(a.id, 5, at(8, 0, 5))
    tick(sc, at(8, 5, 6))
    closed = sc.pause(at(9), at(8, 6))
    assert closed[0] == a.id and closed[1] == 1 and sc.active is None


def test_overnight_prompt_expires():
    a = T(60, "17:00")
    sc = make([a], at(16, 59, 59))
    tick(sc, at(17))
    ev = sc.tick(at(8, 0, 0, day=MON + timedelta(days=1)))
    assert any(e[0] == "expired" for e in ev) and sc.active is None


def test_completion_near_window_end_survives_unrelated_change():
    a, b = T(45, "08:00"), T(60, "08:30")
    sc = make([a, b], at(17, 14, 59))
    tick(sc, at(17, 15))
    sc.complete(a.id, at(17, 20))
    tomorrow = at(8, day=MON + timedelta(days=1))
    assert sc.rt[a.id].due == tomorrow
    # unabhängige Änderung (anderer Timer, gleiche Zeiten)
    b2 = TimerConfig.from_dict({**b.to_dict(), "name": "neu"})
    sc.apply_config([a, b2], sc.settings, at(17, 21), {b.id})
    assert sc.rt[a.id].due == tomorrow
    # Neustart
    sc2 = S.Scheduler([a, b2], settings())
    sc2.restore(sc.snapshot(), at(17, 22))
    assert sc2.rt[a.id].due == tomorrow


def test_snooze_outside_window_reports_expired():
    a = T(60, "08:00")
    sc = make([a], at(16, 59, 59))
    tick(sc, at(17))
    sc.snooze(a.id, 15, at(17, 50))
    ev = tick(sc, at(18, 5))
    assert ("expired", a.id, 1, at(17)) in ev


def test_hold_keeps_alarm_queued_until_released():
    a = T(20)
    sc = make([a], at(7, 59, 59))
    sc.last_tick = at(8) - timedelta(seconds=1)
    assert not any(e[0] == "alarm" for e in sc.tick(at(8), 0, True))
    assert a.id in sc.queue
    sc.last_tick = at(8, 5) - timedelta(seconds=1)
    assert sc.tick(at(8, 5), 0, False) == [("alarm", a.id)]


def test_trigger_blocked_while_paused():
    a = T(60)
    sc = make([a], at(9))
    sc.pause(at(10), at(9))
    assert sc.trigger_now(a.id, at(9, 1)) is False


def test_open_pause_runs_until_resume_and_reports_span():
    a = T(20)
    sc = make([a], at(11, 59))
    sc.pause(None, at(12, 3))
    assert sc.pause_open and sc.paused_until == at(0, day=MON + timedelta(days=1))
    for m in range(4, 60):
        assert not any(e[0] == "alarm" for e in tick(sc, at(12, m)))
    span = sc.resume(at(13, 8))
    assert span == (at(12, 3), at(13, 8)) and not sc.pause_open and sc.paused_until is None
    assert sc.rt[a.id].due == at(13, 28)


def test_timed_pause_end_event_carries_span():
    a = T(20)
    sc = make([a], at(9))
    sc.pause(at(9, 30), at(9, 0, 10))
    tick(sc, at(9, 29, 59))
    ev = tick(sc, at(9, 30))
    assert ("pause_ended", at(9, 0, 10), at(9, 30)) in ev


def test_pause_survives_restart_with_start_time():
    a = T(20)
    sc = make([a], at(12))
    sc.pause(None, at(12))
    sc2 = S.Scheduler([a], settings())
    sc2.restore(sc.snapshot(), at(12, 30))
    assert sc2.pause_open and sc2.paused_since == at(12)
    assert sc2.resume(at(13)) == (at(12), at(13))


def test_pause_expired_while_closed_is_reported_up_to_last_save():
    a = T(20)
    state = {"paused_until": at(0, day=MON + timedelta(days=1)).isoformat(),
             "paused_since": at(12).isoformat(), "pause_open": True, "saved": at(17, 5).isoformat()}
    sc = S.Scheduler([a], settings())
    sc.restore(state, at(8, day=MON + timedelta(days=1)))
    assert sc.paused_until is None and sc.ended_pause == (at(12), at(17, 5))


def test_history_pauses(tmp=None):
    import tempfile
    from pausenpilot.storage import History
    d = Path(tempfile.mkdtemp())
    h = History(d / "h.db")
    assert not h.add_pause(at(12), at(12, 0, 30))           # zu kurz
    assert h.add_pause(at(12), at(13, 5))
    assert h.add_pause(at(23, 30), at(0, 30, day=MON + timedelta(days=1)))
    assert h.range_pause_seconds(MON.date(), MON.date()) == {MON.date(): 65 * 60 + 30 * 60}
    assert h.day_pauses((MON + timedelta(days=1)).date()) == [
        (at(0, day=MON + timedelta(days=1)), at(0, 30, day=MON + timedelta(days=1)))]
    n = h.export_csv(d / "x.csv")
    assert n == 3
    h.add(T(), "done", ts=at(9))
    assert h.count() == (1, 3, MON.date().isoformat())
    h.clear()
    assert h.count() == (0, 0, None) and h.day_pauses(MON.date()) == []
    h.close()


def test_day_rating_thresholds():
    from pausenpilot.models import day_rating, next_medal
    assert day_rating(2, 0) == (None, 100)            # zu wenige Einträge
    assert day_rating(3, 0) == ("platinum", 100)
    assert day_rating(9, 1) == ("gold", 90)
    assert day_rating(17, 2) == ("silver", 89)        # 89,5 % ist noch kein Gold
    assert day_rating(8, 2) == ("silver", 80)
    assert day_rating(7, 3) == ("bronze", 70)
    assert day_rating(6, 4) == (None, 60)
    assert day_rating(5, 5) == (None, 50)
    assert day_rating(4, 5) == ("thumb", 44)
    assert next_medal(17, 2) == ("gold", 1)
    assert next_medal(9, 1) is None                   # Platin nach Auslassen unerreichbar


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, repr(e))
    print("fehler:", fails)
    sys.exit(1 if fails else 0)
