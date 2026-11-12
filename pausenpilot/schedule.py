"""Zeitplanung – reine Logik ohne Qt (testbar).

Regeln
------
* Ein Timer feuert nur innerhalb des aktiven Zeitfensters des jeweiligen Wochentags.
* Tagesraster: erste Startzeit + k * Intervall. Beim Programmstart / nach Änderungen
  wird der nächste Rasterpunkt gewählt.
* Nach "erledigt" oder "übersprungen" läuft das Intervall ab diesem Moment neu.
  Fällt der neue Zeitpunkt aus dem Fenster, beginnt der nächste aktive Tag wieder
  mit der ersten Startzeit.
* "Später" verschiebt um n Minuten ab jetzt.
* Abwesenheit (Leerlauf, Standby, Pause): Erinnerungen, die in diese Zeit fielen,
  werden nicht nachgeholt, sondern ab der Rückkehr neu geplant.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .models import Settings, TimerConfig, parse_hm

SEARCH_DAYS = 8


def window_for(settings: Settings, d: date) -> tuple[datetime, datetime] | None:
    w = settings.days[d.weekday()]
    if not w.enabled:
        return None
    start = datetime.combine(d, parse_hm(w.start))
    end = datetime.combine(d, parse_hm(w.end))
    if w.end == "00:00":
        end = datetime.combine(d + timedelta(days=1), parse_hm("00:00"))
    if end <= start:
        return None
    return start, end


def in_window(settings: Settings, t: datetime) -> bool:
    w = window_for(settings, t.date())
    return bool(w and w[0] <= t < w[1])


def is_active_now(settings: Settings, now: datetime) -> bool:
    return in_window(settings, now)


def next_slot(timer: TimerConfig, settings: Settings, after: datetime) -> datetime | None:
    """Nächster Rasterpunkt >= after, der in einem aktiven Fenster liegt."""
    after = after.replace(microsecond=0)
    step = timedelta(minutes=max(1, timer.interval_min))
    for i in range(SEARCH_DAYS):
        d = after.date() + timedelta(days=i)
        w = window_for(settings, d)
        if not w:
            continue
        ws, we = w
        t0 = datetime.combine(d, parse_hm(timer.first_start))
        lo = max(after, ws)
        if lo >= we:
            continue
        if lo <= t0:
            t = t0
        else:
            k = math.ceil((lo - t0) / step)
            t = t0 + k * step
        if ws <= t < we:
            return t
    return None


def after_completion(timer: TimerConfig, settings: Settings, at: datetime) -> datetime | None:
    """Nächster Termin, wenn das Intervall ab `at` neu beginnt."""
    at = at.replace(microsecond=0)
    c = at + timedelta(minutes=max(1, timer.interval_min))
    if c.date() == at.date() and in_window(settings, c):
        return c
    # Neuer Tag oder außerhalb des Fensters → nächster Tag beginnt mit der ersten Startzeit
    nxt = next_slot(timer, settings, c)
    return nxt


def first_occurrences_today(timer: TimerConfig, settings: Settings, d: date, limit: int = 4) -> list[datetime]:
    w = window_for(settings, d)
    if not w:
        return []
    out = []
    t = datetime.combine(d, parse_hm(timer.first_start)) - timedelta(seconds=1)
    while len(out) < limit:
        n = next_slot(timer, settings, t + timedelta(seconds=1))
        if not n or n.date() != d:
            break
        out.append(n)
        t = n
    return out


# --------------------------------------------------------------------------- Laufzeit-Kern

PHASE_WAITING = "waiting"
PHASE_QUEUED = "queued"
PHASE_ALARM = "alarm"
PHASE_RUNNING = "running"


@dataclass
class TimerRuntime:
    due: datetime | None = None
    planned: datetime | None = None   # ursprünglich geplanter Zeitpunkt (vor dem Verschieben)
    snoozes: int = 0
    phase: str = PHASE_WAITING


@dataclass
class Scheduler:
    """Zustandsmaschine aller Timer. Wird sekündlich mit `tick(now, idle)` getaktet."""
    timers: list[TimerConfig]
    settings: Settings
    rt: dict[str, TimerRuntime] = field(default_factory=dict)
    queue: list[str] = field(default_factory=list)
    active: str | None = None
    paused_until: datetime | None = None
    paused_since: datetime | None = None
    pause_open: bool = False             # Pause ohne festes Ende (läuft bis „Pause beenden“, spätestens Mitternacht)
    ended_pause: tuple | None = None     # (von, bis) einer Pause, die endete, während das Tool zu war
    away_since: datetime | None = None
    away_reason: str = ""                # "lock" (gesperrt) | "idle" (keine Eingabe) – solange away_since gesetzt
    away_missed: list = field(default_factory=list)   # [(tid, Termin)] – während der Abwesenheit fällig gewesen
    last_tick: datetime | None = None
    hold_until: datetime | None = None   # kurze Atempause zwischen zwei Erinnerungen

    SLEEP_GAP = timedelta(seconds=90)
    HOLD = timedelta(seconds=3)

    # ---- Aufbau ---------------------------------------------------------
    def restore(self, state: dict, now: datetime) -> None:
        saved = state.get("timers", {}) if isinstance(state, dict) else {}
        for t in self.timers:
            r = TimerRuntime()
            s = saved.get(t.id, {}) if isinstance(saved, dict) else {}
            due = _parse_dt(s.get("due"))
            planned = _parse_dt(s.get("planned")) or due
            try:
                snoozes = int(s.get("snoozes", 0)) if planned and planned.date() == now.date() else 0
            except (TypeError, ValueError):
                snoozes = 0
            ok = (due and due > now and t.enabled and _consistent(t, self.settings, due, now)
                  and (snoozes > 0 or in_window(self.settings, due)))
            fresh = next_slot(t, self.settings, now) if t.enabled else None
            if ok:
                r.due = due
                r.planned = planned
                r.snoozes = snoozes
            else:
                r.due = fresh
                r.planned = r.due
            self.rt[t.id] = r
        st = state if isinstance(state, dict) else {}
        pu = _parse_dt(st.get("paused_until"))
        ps = _parse_dt(st.get("paused_since"))
        if ps and ps > now:
            ps = None
        if pu and pu > now:
            self.paused_until = pu
            self.paused_since = ps or now
            self.pause_open = bool(st.get("pause_open"))
        elif pu and ps:
            # Pause ist abgelaufen, während das Tool geschlossen war – Ende höchstens zum letzten Speichern
            saved = _parse_dt(st.get("saved"))
            end = min(pu, saved) if saved and saved > ps else pu
            self.ended_pause = (ps, end)
        self.last_tick = now
        self._days_snapshot = _days_key(self.settings)

    def snapshot(self) -> dict:
        return {
            "saved": datetime.now().isoformat(timespec="seconds"),
            "paused_until": self.paused_until.isoformat(timespec="seconds") if self.paused_until else None,
            "paused_since": self.paused_since.isoformat(timespec="seconds") if self.paused_since else None,
            "pause_open": self.pause_open,
            "timers": {
                tid: {
                    "due": r.due.isoformat(timespec="seconds") if r.due else None,
                    "planned": r.planned.isoformat(timespec="seconds") if r.planned else None,
                    "snoozes": r.snoozes,
                } for tid, r in self.rt.items()
            },
        }

    def timer(self, tid: str) -> TimerConfig | None:
        for t in self.timers:
            if t.id == tid:
                return t
        return None

    # ---- Takt -----------------------------------------------------------
    def tick(self, now: datetime, idle_seconds: float = 0.0, hold: bool = False,
             locked: bool = False) -> list[tuple]:
        """Gibt Ereignisse zurück:
        ("alarm", tid) | ("returned", since) | ("pause_ended",) | ("away",)
        | ("away_ended", von, bis, grund, [(tid, Termin)])  – grund: "lock" | "idle" | "sleep"
        | ("expired", tid, snoozes, planned)  – offene Erinnerung ist veraltet und wurde geschlossen
        """
        events: list[tuple] = []
        # Standby / Ruhezustand erkannt (Uhr ist gesprungen – auch rückwärts, z. B. Zeitumstellung)
        if self.last_tick and (now - self.last_tick > self.SLEEP_GAP or self.last_tick - now > self.SLEEP_GAP):
            slept_from = self.last_tick
            missed = self._missed_slots(now) if not self.paused_until else []
            events += self._reschedule_missed(now)
            events.append(("returned", slept_from))
            if self.away_since is not None:
                # schon abwesend (z. B. gesperrt) → gehört zu dieser Abwesenheit
                self.away_missed += missed
            elif not self.paused_until and now > slept_from:
                events.append(("away_ended", slept_from, now, "sleep", missed))
        self.last_tick = now

        # Pause
        if self.paused_until:
            if now >= self.paused_until:
                span = (self.paused_since or self.paused_until, self.paused_until)
                self._clear_pause()
                events += self._reschedule_missed(now)
                events.append(("pause_ended", span[0], span[1]))
            else:
                return events

        # Abwesenheit (nicht während ein Countdown läuft – dann ist man ja gerade in der Pause)
        running = self.active is not None and self.rt.get(self.active) and \
            self.rt[self.active].phase == PHASE_RUNNING
        if locked:
            # Gesperrter Bildschirm = nicht am PC, sofort (unabhängig von der Leerlauf-Einstellung)
            if self.away_since is None and not running:
                self.away_since = now - timedelta(seconds=min(idle_seconds, 60))
                self.away_reason = "lock"
                self.away_missed = []
                events.append(("away",))
            elif self.away_since is not None:
                self.away_reason = "lock"      # erst inaktiv, dann gesperrt → zählt als gesperrt
        elif self.settings.idle_detect:
            limit = self.settings.idle_minutes * 60
            if self.away_since is None and idle_seconds >= limit and not running:
                self.away_since = now - timedelta(seconds=idle_seconds)
                self.away_reason = "idle"
                self.away_missed = []
                events.append(("away",))
            elif self.away_since is not None and idle_seconds < 3:
                events += self._end_away(now)
        elif self.away_since is not None:
            events += self._end_away(now)

        if self.away_since is not None:
            return events

        # Fällige Timer einreihen
        for t in self.timers:
            r = self.rt.get(t.id)
            if not r or not t.enabled or r.due is None:
                continue
            if r.phase == PHASE_WAITING and r.due <= now:
                if r.snoozes > 0 and not in_window(self.settings, now):
                    # Verschobene Erinnerung landet außerhalb der aktiven Zeit → als übersprungen
                    # melden und den nächsten regulären Termin nehmen
                    events.append(("expired", t.id, r.snoozes, r.planned))
                    r.snoozes = 0
                    r.due = next_slot(t, self.settings, now)
                    r.planned = r.due
                    continue
                r.phase = PHASE_QUEUED
                self.queue.append(t.id)
        # hold=True: Vollbild/Präsentation läuft → Erinnerungen warten in der Schlange
        if self.active is None and self.queue and not hold and not (self.hold_until and now < self.hold_until):
            self.queue.sort(key=lambda tid: self.rt[tid].due or now)
            tid = self.queue.pop(0)
            self.active = tid
            self.rt[tid].phase = PHASE_ALARM
            events.append(("alarm", tid))
        return events

    def _end_away(self, now: datetime) -> list[tuple]:
        since, reason = self.away_since, self.away_reason or "idle"
        missed = self.away_missed + self._missed_slots(now)
        self.away_since, self.away_reason, self.away_missed = None, "", []
        events = self._reschedule_missed(now)
        events.append(("returned", since))
        events.append(("away_ended", since, now, reason, missed))
        return events

    def _missed_slots(self, now: datetime) -> list[tuple[str, datetime]]:
        """Termine (je Erinnerung im Raster), die bis jetzt fällig waren, aber nicht angezeigt wurden."""
        out = []
        for t in self.timers:
            r = self.rt.get(t.id)
            if not r or not t.enabled or r.due is None or t.id == self.active:
                continue
            d, step, n = r.due, timedelta(minutes=max(1, t.interval_min)), 0
            while d <= now and n < 300:
                if in_window(self.settings, d) or (n == 0 and r.snoozes):
                    out.append((t.id, d))
                d += step
                n += 1
        return out

    def _reschedule_missed(self, now: datetime) -> list[tuple]:
        """Erinnerungen, die in eine Abwesenheit fielen, ab jetzt neu planen.
        Eine offene (nicht gestartete) Erinnerung von einem früheren Tag wird geschlossen."""
        events: list[tuple] = []
        if self.active and self.active in self.rt:
            r = self.rt[self.active]
            if r.phase == PHASE_ALARM and r.planned and r.planned.date() < now.date():
                t = self.timer(self.active)
                tid = self.active
                events.append(("expired", tid, r.snoozes, r.planned))
                r.phase = PHASE_WAITING
                r.snoozes = 0
                r.due = next_slot(t, self.settings, now) if t else None
                r.planned = r.due
                self._release(tid)
        for t in self.timers:
            r = self.rt.get(t.id)
            if not r or not t.enabled:
                continue
            if t.id == self.active:
                continue
            if r.due is not None and r.due <= now:
                if t.id in self.queue:
                    self.queue.remove(t.id)
                r.phase = PHASE_WAITING
                r.snoozes = 0
                r.due = after_completion(t, self.settings, now)
                r.planned = r.due
        return events

    # ---- Aktionen ---------------------------------------------------------
    def start(self, tid: str) -> None:
        r = self.rt.get(tid)
        if r and self.active == tid:
            r.phase = PHASE_RUNNING

    def cancel_run(self, tid: str) -> None:
        r = self.rt.get(tid)
        if r and self.active == tid:
            r.phase = PHASE_ALARM

    def complete(self, tid: str, now: datetime) -> tuple[int, datetime | None]:
        """Erledigt. Gibt (Anzahl Verschiebungen, geplanter Zeitpunkt) zurück."""
        return self._finish(tid, now)

    def skip(self, tid: str, now: datetime) -> tuple[int, datetime | None]:
        return self._finish(tid, now)

    def _finish(self, tid: str, now: datetime) -> tuple[int, datetime | None]:
        t = self.timer(tid)
        r = self.rt.get(tid)
        if not t or not r:
            self._release(tid)
            return 0, None
        snoozes, planned = r.snoozes, r.planned
        r.snoozes = 0
        r.phase = PHASE_WAITING
        r.due = after_completion(t, self.settings, now) if t.enabled else None
        r.planned = r.due
        self._release(tid)
        self.hold_until = now + self.HOLD
        return snoozes, planned

    def snooze(self, tid: str, minutes: int, now: datetime) -> int:
        r = self.rt.get(tid)
        if not r:
            self._release(tid)
            return 0
        r.snoozes += 1
        r.phase = PHASE_WAITING
        r.due = now.replace(microsecond=0) + timedelta(minutes=minutes)
        self._release(tid)
        self.hold_until = now + self.HOLD
        return r.snoozes

    def trigger_now(self, tid: str, now: datetime) -> bool:
        """Erinnerung sofort auslösen (manuell). Nicht während einer Pause."""
        r = self.rt.get(tid)
        t = self.timer(tid)
        if not r or not t or r.phase != PHASE_WAITING or self.paused_until:
            return False
        r.due = now.replace(microsecond=0)
        r.planned = r.due
        self.hold_until = None
        return True

    def _release(self, tid: str) -> None:
        if self.active == tid:
            self.active = None
        if tid in self.queue:
            self.queue.remove(tid)

    def pause(self, until: datetime | None, now: datetime) -> tuple | None:
        """Alle Erinnerungen pausieren. until=None: offene Pause bis „Pause beenden“ (spätestens Mitternacht).
        Ein laufender Countdown darf zu Ende laufen.
        Eine offene, nicht gestartete Erinnerung wird geschlossen und als übersprungen gemeldet:
        Rückgabe (tid, snoozes, planned) oder None."""
        self.pause_open = until is None
        if until is None:
            until = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
        closed = None
        if self.active and self.active in self.rt and self.rt[self.active].phase == PHASE_ALARM:
            tid = self.active
            closed = (tid,) + self._finish(tid, now)
        for tid in list(self.queue):
            self.rt[tid].phase = PHASE_WAITING
        self.queue.clear()
        self.paused_until = until
        self.paused_since = self.paused_since or now
        return closed

    def resume(self, now: datetime) -> tuple | None:
        """Pause beenden. Gibt (von, bis) der beendeten Pause zurück."""
        if self.paused_until:
            span = (self.paused_since or now, now)
            self._clear_pause()
            self._reschedule_missed(now)
            return span
        return None

    def _clear_pause(self) -> None:
        self.paused_until = None
        self.paused_since = None
        self.pause_open = False

    # ---- Konfigurationsänderungen ----------------------------------------
    def apply_config(self, timers: list[TimerConfig], settings: Settings, now: datetime,
                     changed_schedule: set[str] | None = None) -> list[str]:
        """Neue Konfiguration übernehmen. Gibt IDs zurück, deren laufender Alarm geschlossen werden muss."""
        changed_schedule = changed_schedule or set()
        closed: list[str] = []
        old_days = getattr(self, "_days_snapshot", None) or _days_key(self.settings)
        new_days = _days_key(settings)
        changed_days = {i for i in range(7) if old_days[i] != new_days[i]}
        old_ids = set(self.rt)
        self.timers = timers
        self.settings = settings
        ids = {t.id for t in timers}
        for tid in old_ids - ids:
            self.rt.pop(tid, None)
            if self.active == tid:
                closed.append(tid)
            self._release(tid)
        for t in timers:
            r = self.rt.get(t.id)
            if r is None:
                r = self.rt[t.id] = TimerRuntime()
                changed_schedule.add(t.id)
            if not t.enabled:
                if self.active == t.id:
                    closed.append(t.id)
                self._release(t.id)
                r.phase = PHASE_WAITING
                r.due = None
                r.snoozes = 0
                continue
            if r.phase in (PHASE_ALARM, PHASE_RUNNING) and self.active == t.id:
                continue
            if t.id in changed_schedule or r.due is None:
                if t.id in self.queue:
                    self.queue.remove(t.id)
                r.phase = PHASE_WAITING
                r.snoozes = 0
                r.due = next_slot(t, settings, now)
                r.planned = r.due
            elif r.phase == PHASE_WAITING and r.snoozes == 0:
                if r.due and not in_window(settings, r.due):
                    r.due = next_slot(t, settings, max(now, r.due))
                    r.planned = r.due
                # Nur wenn sich der aktive Zeitraum eines Wochentags geändert hat: früheren Termin übernehmen
                if changed_days:
                    fresh = next_slot(t, settings, now)
                    if fresh and fresh.weekday() in changed_days and (r.due is None or fresh < r.due):
                        r.due = fresh
                        r.planned = fresh
        self._days_snapshot = _days_key(settings)
        return closed

    def next_overall(self) -> tuple[TimerConfig, datetime] | None:
        best = None
        for t in self.timers:
            r = self.rt.get(t.id)
            if t.enabled and r and r.due and r.phase == PHASE_WAITING:
                if best is None or r.due < best[1]:
                    best = (t, r.due)
        return best


def _days_key(settings: Settings) -> list[tuple]:
    return [(d.enabled, d.start, d.end) for d in settings.days]


def _parse_dt(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def _consistent(t: TimerConfig, settings: Settings, due: datetime, now: datetime) -> bool:
    """Gespeicherter Termin ist noch plausibel (nicht weiter als ein Intervall + 8 Tage entfernt)."""
    return due <= now + timedelta(days=SEARCH_DAYS, minutes=t.interval_min)
