"""Datenmodell: Timer und Einstellungen (reine Python-Klassen, kein Qt)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import time

MAX_TIMERS = 20

COLORS = [
    "#6C8CFF",  # Blau
    "#36C2B4",  # Türkis
    "#3DD68C",  # Grün
    "#F5A524",  # Bernstein
    "#FF7A59",  # Koralle
    "#EF5DA8",  # Pink
    "#9B7BFF",  # Violett
    "#5EC8F2",  # Himmelblau
]

ICONS = ["👁", "💧", "☕", "🧍", "🤸", "🚶", "🧘", "🍎", "🌿", "🫁", "💊", "⭐"]

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]


def parse_hm(s: str) -> time:
    try:
        h, m = s.strip().split(":")
        return time(max(0, min(23, int(h))), max(0, min(59, int(m))))
    except Exception:
        return time(8, 0)


def fmt_hm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class TimerConfig:
    id: str = field(default_factory=new_id)
    name: str = "Neue Erinnerung"
    description: str = ""
    interval_min: int = 60
    duration_sec: int = 60
    first_start: str = "08:00"
    enabled: bool = True
    color: str = COLORS[0]
    icon: str = "⭐"

    @classmethod
    def from_dict(cls, d: dict) -> "TimerConfig":
        t = cls()
        for k in asdict(t):
            if k in d:
                setattr(t, k, d[k])
        t.interval_min = max(1, min(24 * 60, int(t.interval_min)))
        t.duration_sec = max(0, min(3 * 3600, int(t.duration_sec)))
        t.first_start = t.first_start if isinstance(t.first_start, str) else "08:00"
        t.first_start = fmt_hm(parse_hm(t.first_start))
        t.name = str(t.name)[:60] or "Erinnerung"
        t.description = str(t.description)[:200]
        t.enabled = bool(t.enabled)
        return t

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DayWindow:
    enabled: bool = True
    start: str = "08:00"
    end: str = "18:00"

    @classmethod
    def from_dict(cls, d: dict) -> "DayWindow":
        w = cls()
        w.enabled = bool(d.get("enabled", True))
        w.start = fmt_hm(parse_hm(str(d.get("start", "08:00"))))
        w.end = fmt_hm(parse_hm(str(d.get("end", "18:00"))))
        return w


def default_days() -> list[DayWindow]:
    days = [DayWindow(True, "08:00", "18:00") for _ in range(5)]
    days += [DayWindow(False, "10:00", "16:00") for _ in range(2)]
    return days


@dataclass
class Settings:
    days: list[DayWindow] = field(default_factory=default_days)
    autostart: bool = False
    sound: bool = True
    sound_volume: int = 60          # 0..100
    idle_detect: bool = True
    idle_minutes: int = 5
    hold_fullscreen: bool = True    # bei Vollbild/Präsentation zurückhalten
    quiet_in_calls: bool = True     # bei Teams-/Zoom-Anruf: leise und nicht in den Vordergrund
    theme: str = "system"           # system | dark | light
    alarm_screen: str = ""          # Name des Bildschirms, auf dem das Tool zuletzt lief
    close_hint_shown: bool = False
    welcome_shown: bool = False     # Willkommens-Bildschirm schon gezeigt
    window_geometry: str = ""
    compact_auto: bool = True       # nach Inaktivität automatisch in den Kompaktmodus
    compact_minutes: int = 3
    compact_on_top: bool = True     # Kompaktfenster immer im Vordergrund
    compact_pos: str = ""           # "x,y" des Kompaktfensters
    compact_active: bool = False    # war beim Beenden im Kompaktmodus
    alarm_pos: str = ""             # "x,y" – Mitte der Erinnerung, wenn sie verschoben wurde

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        s = cls()
        days = d.get("days")
        if isinstance(days, list) and len(days) == 7:
            s.days = [DayWindow.from_dict(x if isinstance(x, dict) else {}) for x in days]
        s.autostart = bool(d.get("autostart", s.autostart))
        s.sound = bool(d.get("sound", s.sound))
        s.sound_volume = max(0, min(100, int(d.get("sound_volume", s.sound_volume))))
        s.idle_detect = bool(d.get("idle_detect", s.idle_detect))
        s.idle_minutes = max(1, min(120, int(d.get("idle_minutes", s.idle_minutes))))
        s.hold_fullscreen = bool(d.get("hold_fullscreen", s.hold_fullscreen))
        s.quiet_in_calls = bool(d.get("quiet_in_calls", s.quiet_in_calls))
        s.theme = d.get("theme", s.theme) if d.get("theme") in ("system", "dark", "light") else "system"
        s.alarm_screen = str(d.get("alarm_screen", ""))
        s.close_hint_shown = bool(d.get("close_hint_shown", False))
        s.welcome_shown = bool(d.get("welcome_shown", False))
        s.window_geometry = str(d.get("window_geometry", ""))
        s.compact_auto = bool(d.get("compact_auto", s.compact_auto))
        s.compact_minutes = max(1, min(120, int(d.get("compact_minutes", s.compact_minutes))))
        s.compact_on_top = bool(d.get("compact_on_top", s.compact_on_top))
        s.compact_pos = str(d.get("compact_pos", ""))
        s.compact_active = bool(d.get("compact_active", False))
        s.alarm_pos = str(d.get("alarm_pos", ""))
        return s

    def to_dict(self) -> dict:
        d = asdict(self)
        d["days"] = [asdict(w) for w in self.days]
        return d


def default_timers() -> list[TimerConfig]:
    return [
        TimerConfig(name="Augen entspannen", description="20 Sekunden in die Ferne schauen – am besten aus dem Fenster.",
                    interval_min=20, duration_sec=20, first_start="08:00", color=COLORS[0], icon="👁"),
        TimerConfig(name="Glas Wasser trinken", description="Einmal aufstehen und ein Glas Wasser trinken.",
                    interval_min=60, duration_sec=0, first_start="08:10", color=COLORS[7], icon="💧"),
        TimerConfig(name="Kurze Pause", description="Weg vom Bildschirm, kurz bewegen und durchatmen.",
                    interval_min=60, duration_sec=5 * 60, first_start="08:50", color=COLORS[3], icon="☕"),
    ]


def fmt_duration(sec: int) -> str:
    if sec <= 0:
        return "ohne Countdown"
    m, s = divmod(int(sec), 60)
    if m and s:
        return f"{m} Min {s} Sek"
    if m:
        return f"{m} Min"
    return f"{s} Sek"


def fmt_interval(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h} Std {m} Min"
    if h:
        return "1 Stunde" if h == 1 else f"{h} Stunden"
    return f"{m} Min"


# --------------------------------------------------------------------------- Tageswertung
# Anteil erledigt an allen fälligen Erinnerungen des Tages (erledigt + übersprungen).
# Verschieben zählt nicht extra – die Erinnerung wird am Ende erledigt oder übersprungen.
MEDAL_MIN_ENTRIES = 3          # darunter gibt es noch keine Wertung
MEDALS = [                     # (Schlüssel, Name, ab Prozent) – absteigend
    ("platinum", "Platin", 100),
    ("gold", "Gold", 90),
    ("silver", "Silber", 80),
    ("bronze", "Bronze", 70),
]
THUMB_BELOW = 50
MEDAL_NAMES = {k: n for k, n, _ in MEDALS} | {"thumb": "Daumen runter"}


def day_rating(done: int, skips: int) -> tuple[str | None, int | None]:
    """(Schlüssel, Prozent). Schlüssel: platinum/gold/silver/bronze/thumb oder None (keine Medaille)."""
    total = done + skips
    if total < MEDAL_MIN_ENTRIES:
        return None, (round(100 * done / total) if total else None)
    pct = 100 * done / total
    shown = int(pct) if pct < 100 else 100          # abrunden: 89,6 % ist noch kein Gold
    for key, _, need in MEDALS:
        if pct >= need:
            return key, shown
    if pct < THUMB_BELOW:
        return "thumb", shown
    return None, shown


def next_medal(done: int, skips: int) -> tuple[str, int] | None:
    """Nächstbessere Medaille und wie viele weitere Erledigungen (ohne Auslassen) dafür nötig sind."""
    key, _ = day_rating(done, skips)
    order = [k for k, _, _ in reversed(MEDALS)]
    targets = order if key in (None, "thumb") else order[order.index(key) + 1:]
    for tk in targets:
        need = next(n for k, _, n in MEDALS if k == tk)
        if skips and need >= 100:
            continue                      # Platin ist nach einem Auslassen nicht mehr erreichbar
        k = 0
        while k < 500:
            d, total = done + k, done + k + skips
            if total >= MEDAL_MIN_ENTRIES and 100 * d / total >= need:
                return tk, k
            k += 1
    return None
