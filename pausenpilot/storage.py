"""Speicherung: Konfiguration (JSON), Laufzeitstatus (JSON) und Verlauf (SQLite).

Portabel: Daten liegen im Ordner "Pausenpilot-Daten" neben der .exe.
Ist dieser Ort nicht beschreibbar, wird %APPDATA%\\Pausenpilot verwendet.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import Settings, TimerConfig, default_timers, MAX_TIMERS

DATA_FOLDER_NAME = "Pausenpilot-Daten"


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".schreibtest"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def resolve_data_dir() -> Path:
    override = os.environ.get("PAUSENPILOT_DATA")
    if override:
        d = Path(override)
        d.mkdir(parents=True, exist_ok=True)
        return d
    d = app_base_dir() / DATA_FOLDER_NAME
    if _writable(d):
        return d
    d = Path(os.environ.get("APPDATA", str(Path.home()))) / "Pausenpilot"
    d.mkdir(parents=True, exist_ok=True)
    return d


def atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        # Beschädigte Datei sichern, damit nichts stillschweigend verloren geht
        try:
            path.replace(path.with_suffix(path.suffix + f".defekt-{datetime.now():%Y%m%d%H%M%S}"))
        except OSError:
            pass
        return None


class ConfigStore:
    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.config_path = data_dir / "config.json"
        self.state_path = data_dir / "state.json"

    def load(self) -> tuple[list[TimerConfig], Settings, bool]:
        """Gibt (timer, settings, first_run) zurück."""
        raw = read_json(self.config_path)
        if not isinstance(raw, dict):
            return default_timers(), Settings(), True
        timers = []
        raw_timers = raw.get("timers")
        for t in (raw_timers if isinstance(raw_timers, list) else [])[:MAX_TIMERS]:
            if isinstance(t, dict):
                try:
                    timers.append(TimerConfig.from_dict(t))
                except (TypeError, ValueError):
                    pass
        try:
            settings = Settings.from_dict(raw.get("settings", {}) or {})
        except (TypeError, ValueError):
            settings = Settings()
        return timers, settings, False

    def save(self, timers: list[TimerConfig], settings: Settings) -> None:
        atomic_write_json(self.config_path, {
            "version": 1,
            "timers": [t.to_dict() for t in timers],
            "settings": settings.to_dict(),
        })

    def load_state(self) -> dict:
        raw = read_json(self.state_path)
        return raw if isinstance(raw, dict) else {}

    def save_state(self, state: dict) -> None:
        try:
            atomic_write_json(self.state_path, state)
        except OSError:
            pass


# --------------------------------------------------------------------------- Verlauf

ACTION_DONE = "done"
ACTION_SNOOZE = "snooze"
ACTION_SKIP = "skip"
ACTION_MISSED = "missed"     # fiel in eine Abwesenheit – zählt weder als erledigt noch als übersprungen

AWAY_LOCK, AWAY_IDLE, AWAY_SLEEP = "lock", "idle", "sleep"
AWAY_LABELS = {AWAY_LOCK: "PC gesperrt", AWAY_IDLE: "Nicht am PC", AWAY_SLEEP: "Standby"}
AWAY_ICONS = {AWAY_LOCK: "🔒", AWAY_IDLE: "🚶", AWAY_SLEEP: "🌙"}


@dataclass
class HistoryEntry:
    ts: datetime
    timer_id: str
    name: str
    icon: str
    color: str
    action: str
    snoozes: int
    minutes: int          # bei snooze: verschobene Minuten; bei done: Dauer in Sekunden/60 gerundet
    planned: datetime | None
    via: str = ""         # "lock"/"sleep"/"idle": automatisch eingetragen während einer Abwesenheit


@dataclass
class DaySummary:
    done: int = 0
    snoozes: int = 0
    skips: int = 0

    @property
    def total(self) -> int:
        return self.done + self.snoozes + self.skips


class History:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                day TEXT NOT NULL,
                timer_id TEXT NOT NULL,
                name TEXT NOT NULL,
                icon TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                snoozes INTEGER NOT NULL DEFAULT 0,
                minutes INTEGER NOT NULL DEFAULT 0,
                planned TEXT
            )""")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_events_day ON events(day)")
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS pauses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                start TEXT NOT NULL,
                end TEXT NOT NULL,
                seconds INTEGER NOT NULL
            )""")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_pauses_day ON pauses(day)")
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS aways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                start TEXT NOT NULL,
                end TEXT NOT NULL,
                seconds INTEGER NOT NULL,
                reason TEXT NOT NULL
            )""")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_aways_day ON aways(day)")
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(events)")}
        if "via" not in cols:
            self._db.execute("ALTER TABLE events ADD COLUMN via TEXT NOT NULL DEFAULT ''")
        self._db.commit()

    # ---- Abwesenheiten (gesperrt / nicht am PC / Standby) -------------------
    def add_away(self, start: datetime, end: datetime, reason: str) -> bool:
        """Abwesenheit eintragen (ab 1 Minute, über Mitternacht je Tag ein Eintrag)."""
        start, end = start.replace(microsecond=0), end.replace(microsecond=0)
        if (end - start).total_seconds() < self.MIN_PAUSE_SECONDS:
            return False
        with self._lock:
            s = start
            while s < end:
                e = min(end, datetime.combine(s.date() + timedelta(days=1), datetime.min.time()))
                self._db.execute("INSERT INTO aways(day, start, end, seconds, reason) VALUES (?,?,?,?,?)",
                                 (s.date().isoformat(), s.isoformat(timespec="seconds"),
                                  e.isoformat(timespec="seconds"), int((e - s).total_seconds()), reason))
                s = e
            self._db.commit()
        return True

    def day_aways(self, d: date) -> list[tuple[datetime, datetime, str]]:
        with self._lock:
            rows = self._db.execute("SELECT start, end, reason FROM aways WHERE day=? ORDER BY start",
                                    (d.isoformat(),)).fetchall()
        return [(datetime.fromisoformat(a), datetime.fromisoformat(b), r) for a, b, r in rows]

    # ---- Pausen ------------------------------------------------------------
    MIN_PAUSE_SECONDS = 60   # versehentliche Klicks nicht eintragen

    def add_pause(self, start: datetime, end: datetime) -> bool:
        """Pause eintragen. Über Mitternacht wird je Tag ein eigener Eintrag angelegt."""
        start, end = start.replace(microsecond=0), end.replace(microsecond=0)
        if (end - start).total_seconds() < self.MIN_PAUSE_SECONDS:
            return False
        parts = []
        s = start
        while s < end:
            midnight = datetime.combine(s.date() + timedelta(days=1), datetime.min.time())
            e = min(end, midnight)
            parts.append((s, e))
            s = e
        with self._lock:
            for s, e in parts:
                self._db.execute("INSERT INTO pauses(day, start, end, seconds) VALUES (?,?,?,?)",
                                 (s.date().isoformat(), s.isoformat(timespec="seconds"),
                                  e.isoformat(timespec="seconds"), int((e - s).total_seconds())))
            self._db.commit()
        return True

    def day_pauses(self, d: date) -> list[tuple[datetime, datetime]]:
        with self._lock:
            rows = self._db.execute("SELECT start, end FROM pauses WHERE day=? ORDER BY start",
                                    (d.isoformat(),)).fetchall()
        return [(datetime.fromisoformat(a), datetime.fromisoformat(b)) for a, b in rows]

    def range_pause_seconds(self, start: date, end: date) -> dict[date, int]:
        with self._lock:
            rows = self._db.execute("SELECT day, SUM(seconds) FROM pauses WHERE day BETWEEN ? AND ? GROUP BY day",
                                    (start.isoformat(), end.isoformat())).fetchall()
        return {date.fromisoformat(d): int(s or 0) for d, s in rows}

    def add(self, timer: TimerConfig, action: str, snoozes: int = 0, minutes: int = 0,
            planned: datetime | None = None, ts: datetime | None = None, via: str = "") -> None:
        ts = ts or datetime.now()
        with self._lock:
            self._db.execute(
                "INSERT INTO events(ts, day, timer_id, name, icon, color, action, snoozes, minutes, planned, via)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ts.isoformat(timespec="seconds"), ts.date().isoformat(), timer.id, timer.name, timer.icon,
                 timer.color, action, int(snoozes), int(minutes),
                 planned.isoformat(timespec="seconds") if planned else None, via))
            self._db.commit()

    def day_entries(self, d: date) -> list[HistoryEntry]:
        with self._lock:
            rows = self._db.execute(
                "SELECT ts, timer_id, name, icon, color, action, snoozes, minutes, planned, via FROM events"
                " WHERE day=? ORDER BY ts", (d.isoformat(),)).fetchall()
        return [HistoryEntry(datetime.fromisoformat(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7],
                             datetime.fromisoformat(r[8]) if r[8] else None, r[9] or "") for r in rows]

    def range_summary(self, start: date, end: date) -> dict[date, DaySummary]:
        """Zusammenfassung je Tag für [start, end] (inklusive)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT day, action, COUNT(*) FROM events WHERE day BETWEEN ? AND ? GROUP BY day, action",
                (start.isoformat(), end.isoformat())).fetchall()
        out: dict[date, DaySummary] = {}
        for day, action, n in rows:
            s = out.setdefault(date.fromisoformat(day), DaySummary())
            if action == ACTION_DONE:
                s.done += n
            elif action == ACTION_SNOOZE:
                s.snoozes += n
            elif action == ACTION_SKIP:
                s.skips += n
        return out

    def day_summary(self, d: date) -> DaySummary:
        return self.range_summary(d, d).get(d, DaySummary())

    def streak(self, today: date) -> int:
        """Anzahl Tage in Folge (bis heute bzw. gestern) mit mindestens einer erledigten Erinnerung."""
        start = today - timedelta(days=400)
        summ = self.range_summary(start, today)
        d = today if summ.get(today, DaySummary()).done else today - timedelta(days=1)
        n = 0
        while summ.get(d, DaySummary()).done:
            n += 1
            d -= timedelta(days=1)
        return n

    def export_csv(self, path: Path) -> int:
        import csv
        with self._lock:
            rows = self._db.execute(
                "SELECT ts, name, action, snoozes, minutes, planned, via FROM events").fetchall()
            prows = self._db.execute("SELECT start, end, seconds FROM pauses").fetchall()
            arows = self._db.execute("SELECT start, end, seconds, reason FROM aways").fetchall()
        labels = {ACTION_DONE: "erledigt", ACTION_SNOOZE: "verschoben", ACTION_SKIP: "übersprungen",
                  ACTION_MISSED: "ausgelassen"}

        def lab(action, via):
            base = labels.get(action, action)
            return f"{base} ({AWAY_LABELS[via]})" if via in AWAY_LABELS else base
        out = [(ts, [ts.replace("T", " "), name, lab(action, via), snoozes,
                     minutes if action == ACTION_SNOOZE else "", (planned or "").replace("T", " "), ""])
               for ts, name, action, snoozes, minutes, planned, via in rows]
        out += [(s, [s.replace("T", " "), "Pause", "Pause", "", round(sec / 60), "", e.replace("T", " ")])
                for s, e, sec in prows]
        out += [(s, [s.replace("T", " "), AWAY_LABELS.get(r, r), AWAY_LABELS.get(r, r), "", round(sec / 60), "",
                     e.replace("T", " ")]) for s, e, sec, r in arows]
        out.sort(key=lambda x: x[0])
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Zeitpunkt", "Erinnerung", "Aktion", "Vorher verschoben", "Minuten", "Geplant für",
                        "Bis"])
            for _, r in out:
                w.writerow(r)
        return len(out)

    def count(self) -> tuple[int, int, str | None]:
        """(Einträge, Pausen, erster Tag) – für die Sicherheitsabfrage beim Löschen."""
        with self._lock:
            n = self._db.execute("SELECT COUNT(*), MIN(day) FROM events").fetchone()
            pn = self._db.execute("SELECT COUNT(*), MIN(day) FROM pauses").fetchone()
        first = min([d for d in (n[1], pn[1]) if d], default=None)
        return int(n[0]), int(pn[0]), first

    def clear(self) -> None:
        """Gesamten Verlauf löschen (Erinnerungen + Pausen) und die Datei verkleinern."""
        with self._lock:
            self._db.execute("DELETE FROM events")
            self._db.execute("DELETE FROM pauses")
            self._db.execute("DELETE FROM aways")
            self._db.commit()
            self._db.execute("VACUUM")

    def close(self) -> None:
        with self._lock:
            self._db.close()
