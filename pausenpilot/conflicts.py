"""Überschneidungen im Tagesplan finden – und einen Vorschlag, wie man sie vermeidet.

Eine Überschneidung: Während eine Erinnerung mit Dauer läuft (z. B. „Schreibtisch hoch“, 15 Min),
wird eine andere fällig – oder zwei kommen zur selben Minute. Die zweite muss dann warten.
Grundlage ist das eingestellte Raster (Startzeit + Vielfache des Intervalls in der aktiven Zeit).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .models import Settings, TimerConfig
from .models import parse_hm
from .schedule import first_occurrences_today

SAME_TIME = timedelta(seconds=60)
STEP_MIN = 5


@dataclass
class Clash:
    first: TimerConfig       # läuft gerade (bzw. kommt zuerst)
    first_at: datetime
    second: TimerConfig      # muss warten
    second_at: datetime


@dataclass
class Suggestion:
    timer: TimerConfig
    new_start: str           # "HH:MM"
    before: int              # Überschneidungen heute vorher
    after: int               # … mit dem Vorschlag


def _slots(t: TimerConfig, settings: Settings, d: date) -> list[datetime]:
    return first_occurrences_today(t, settings, d, limit=400)


def find_clashes(timers: list[TimerConfig], settings: Settings, d: date) -> list[Clash]:
    active = [t for t in timers if t.enabled]
    slots = {t.id: _slots(t, settings, d) for t in active}
    out: list[Clash] = []
    seen = set()
    for a in active:
        dur = timedelta(seconds=max(0, a.duration_sec))
        for ta in slots[a.id]:
            for b in active:
                if b.id == a.id:
                    continue
                for tb in slots[b.id]:
                    if tb > ta + max(dur, SAME_TIME):
                        break
                    inside = dur > timedelta(0) and ta <= tb < ta + dur
                    same = abs(tb - ta) < SAME_TIME
                    if not (inside or same):
                        continue
                    # gleiche Minute nur einmal zählen; zuerst kommt die mit der längeren Dauer
                    key = tuple(sorted(((a.id, ta), (b.id, tb)))) if same else (a.id, ta, b.id, tb)
                    if key in seen:
                        continue
                    seen.add(key)
                    if same and b.duration_sec > a.duration_sec:
                        out.append(Clash(b, tb, a, ta))
                    else:
                        out.append(Clash(a, ta, b, tb))
    out.sort(key=lambda c: c.first_at)
    return out


def _shifted(t: TimerConfig, minutes: int) -> TimerConfig:
    base = datetime.combine(date.today(), parse_hm(t.first_start))
    new = (base + timedelta(minutes=minutes)).strftime("%H:%M")
    c = TimerConfig(**{**t.__dict__})
    c.first_start = new
    return c


def suggest(timers: list[TimerConfig], settings: Settings, d: date) -> Suggestion | None:
    """Bester einzelner Eingriff: Startzeit einer beteiligten Erinnerung um ein paar Minuten verschieben."""
    clashes = find_clashes(timers, settings, d)
    if not clashes:
        return None
    before = len(clashes)
    involved: dict[str, int] = {}
    for c in clashes:
        # bevorzugt die „wartende“ Erinnerung verschieben – meist die kurze, häufige
        involved[c.second.id] = involved.get(c.second.id, 0) + 2
        involved[c.first.id] = involved.get(c.first.id, 0) + 1
    best = None
    for tid in sorted(involved, key=lambda k: -involved[k]):
        t = next(x for x in timers if x.id == tid)
        span = max(STEP_MIN, min(t.interval_min, 120))
        for m in range(STEP_MIN, span, STEP_MIN):
            for sign in (1, -1):
                cand = _shifted(t, sign * m)
                trial = [cand if x.id == tid else x for x in timers]
                n = len(find_clashes(trial, settings, d))
                score = (n, m)
                if best is None or score < best[0]:
                    best = (score, t, cand.first_start, n)
            if best and best[0][0] == 0:
                break
        if best and best[0][0] == 0:
            break
    if not best or best[3] >= before:
        return None
    return Suggestion(best[1], best[2], before, best[3])
