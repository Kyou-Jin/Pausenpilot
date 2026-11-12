"""Tages-Zeitstrahl für die Hauptseite.

Eine Spur je Erinnerung über die aktive Zeit des Tages:
* geplante Termine als Ringe in der Farbe der Erinnerung
* erledigte mit grünem Haken, übersprungene mit rotem Kreuz
* Pausen als blaue Bänder über alle Spuren, „Jetzt“ als senkrechte Linie
* Abwesenheiten (gesperrt / nicht am PC / Standby) als graue Bänder; was hineinfiel,
  ist erledigt mit kleinem Schloss oder neutral „ausgelassen“
"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from . import schedule, theme
from .storage import ACTION_DONE, ACTION_MISSED, ACTION_SKIP, AWAY_ICONS, AWAY_LABELS
from .widgets import EMOJI_FONT

GUTTER = 34      # Platz links für das Symbol je Spur
TOP = 26         # Platz oben für „Jetzt“-Marke und Pausen-Beschriftung
AXIS = 20        # Platz unten für die Uhrzeiten
RIGHT = 14


def _fmt_dur(sec: float) -> str:
    m = max(0, int(sec)) // 60
    return f"{m} Min" if m < 60 else f"{m // 60}:{m % 60:02d} h"


class DayTimeline(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.now = datetime.now()
        self.lanes: list[dict] = []
        self.pauses: list[tuple[datetime, datetime, bool]] = []
        self.aways: list[tuple[datetime, datetime, str, bool]] = []
        self.range: tuple[datetime, datetime] | None = None
        self.active_win: tuple[datetime, datetime] | None = None
        self._sig = None
        self._hits: list[tuple[QPointF, str]] = []
        self._set_height(3)

    # ------------------------------------------------------------------ Daten
    def _lane_h(self, n: int) -> int:
        return max(9, min(22, 120 // max(1, n)))

    def _set_height(self, n: int):
        self.setFixedHeight(TOP + max(1, n) * self._lane_h(n) + AXIS + 4)

    def set_state(self, sched, entries, pauses, now: datetime, aways=()):
        """sched: Scheduler · entries: Verlauf heute · pauses: [(von, bis)] heute."""
        today = now.date()
        settings = sched.settings
        self.active_win = schedule.window_for(settings, today)
        lanes = []
        by_timer: dict[str, list] = {}
        for e in entries:
            by_timer.setdefault(e.timer_id, []).append(e)
        for t in sched.timers:
            hist = by_timer.get(t.id, [])
            if not t.enabled and not hist:
                continue
            r = sched.rt.get(t.id)
            planned = []
            current = False
            if t.enabled and r is not None:
                current = r.phase in (schedule.PHASE_ALARM, schedule.PHASE_QUEUED, schedule.PHASE_RUNNING)
                end = self.active_win[1] if self.active_win else datetime.combine(today + timedelta(days=1),
                                                                          datetime.min.time())
                d = r.due
                step = timedelta(minutes=max(1, t.interval_min))
                while d is not None and d.date() == today and d < end and len(planned) < 200:
                    if d > now or not current:
                        planned.append(d)
                    d += step
            done = [(e.ts, e.snoozes, e.via) for e in hist if e.action == ACTION_DONE]
            skipped = [e.ts for e in hist if e.action == ACTION_SKIP]
            missed = [(e.ts, e.via) for e in hist if e.action == ACTION_MISSED]
            lanes.append(dict(name=t.name, icon=t.icon, color=t.color, enabled=t.enabled,
                              planned=planned, done=done, skipped=skipped, missed=missed, current=current))
        ps = [(a, b, False) for a, b in pauses]
        if sched.paused_until is not None:
            ps.append((sched.paused_since or now, now, True))
        aw = [(a, b, r, False) for a, b, r in aways]
        if sched.away_since is not None:
            aw.append((sched.away_since, now, sched.away_reason or "idle", True))

        # sichtbarer Bereich: aktive Zeit, erweitert um Ereignisse außerhalb – auf volle Stunden gerundet
        if self.active_win:
            lo, hi = self.active_win
        else:
            lo = datetime.combine(today, datetime.min.time()) + timedelta(hours=8)
            hi = lo + timedelta(hours=10)
        pts = [x for ln in lanes for x in [*(d for d, _, _ in ln["done"]), *ln["skipped"],
                                            *(d for d, _ in ln["missed"])]]
        pts += [a for a, _, _ in ps] + [b for _, b, _ in ps]
        pts += [a for a, _, _, _ in aw if a.date() == today] + [b for _, b, _, _ in aw]
        if pts:
            lo, hi = min(lo, *pts), max(hi, *pts)
        if lo <= now <= hi + timedelta(hours=1):
            hi = max(hi, now)
        lo = lo.replace(minute=0, second=0, microsecond=0)
        if hi.minute or hi.second:
            hi = hi.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        day_end = datetime.combine(today + timedelta(days=1), datetime.min.time())
        hi = min(hi, day_end)
        self.range = (lo, hi)

        sig = (now.replace(second=0, microsecond=0), self.range, self.active_win,
               tuple((ln["name"], ln["icon"], ln["color"], tuple(ln["planned"]), tuple(ln["done"]),
                      tuple(ln["skipped"]), tuple(ln["missed"]), ln["current"]) for ln in lanes),
               tuple((a, b.replace(second=0, microsecond=0), c) for a, b, c in ps),
               tuple((a, b.replace(second=0, microsecond=0), r, c) for a, b, r, c in aw), theme.P.get("is_dark"))
        self.now = now
        if sig != self._sig:
            self._sig = sig
            if len(lanes) != len(self.lanes):
                self._set_height(len(lanes))
            self.lanes, self.pauses, self.aways = lanes, ps, aw
            self.update()

    # ------------------------------------------------------------------ Zeichnen
    def _x(self, t: datetime) -> float:
        lo, hi = self.range
        span = max(1.0, (hi - lo).total_seconds())
        w = self.width() - GUTTER - RIGHT
        return GUTTER + max(0.0, min(1.0, (t - lo).total_seconds() / span)) * w

    def paintEvent(self, _):
        if not self.range:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = bool(theme.P.get("is_dark"))
        n = max(1, len(self.lanes))
        lh = self._lane_h(n)
        top, bottom = TOP, TOP + n * lh
        lo, hi = self.range
        now = self.now
        self._hits = []
        small = QFont(self.font())
        small.setPointSizeF(8)

        # aktive Zeit als Fläche, vergangener Teil etwas kräftiger
        if self.active_win:
            wx0, wx1 = self._x(self.active_win[0]), self._x(self.active_win[1])
            band = QRectF(wx0, top - 4, wx1 - wx0, bottom - top + 8)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.c("surface2"))
            p.drawRoundedRect(band, 8, 8)
            if now > self.active_win[0]:
                px = min(self._x(now), wx1)
                p.setBrush(theme.c("accent", 0.07 if dark else 0.06))
                p.drawRoundedRect(QRectF(wx0, top - 4, px - wx0, bottom - top + 8), 8, 8)

        # Stundenraster + Achse
        hours = int((hi - lo).total_seconds() // 3600)
        width = self.width() - GUTTER - RIGHT
        every = 1 if hours and width / hours >= 44 else (2 if hours and width / hours >= 22 else 3)
        p.setFont(small)
        fm = p.fontMetrics()
        for k in range(hours + 1):
            t = lo + timedelta(hours=k)
            x = self._x(t)
            p.setPen(QPen(theme.c("border"), 1, Qt.DotLine if k % every else Qt.SolidLine))
            p.drawLine(QPointF(x, top - 4), QPointF(x, bottom + 4))
            if k % every == 0:
                txt = "24:00" if t.date() > lo.date() else t.strftime("%H:%M")
                tw = fm.horizontalAdvance(txt)
                p.setPen(theme.c("faint"))
                p.drawText(QRectF(x - tw / 2 - 2, bottom + 6, tw + 4, AXIS - 6), Qt.AlignCenter, txt)

        # Platz der „Jetzt“-Marke (Pausen-Beschriftung darf sie nicht überdecken)
        fpill = QFont(self.font())
        fpill.setPointSizeF(8)
        fpill.setWeight(QFont.DemiBold)
        pill = None
        if lo <= now <= hi:
            p.setFont(fpill)
            ptw = p.fontMetrics().horizontalAdvance(now.strftime("%H:%M")) + 12
            px = max(GUTTER, min(self.width() - RIGHT - ptw, self._x(now) - ptw / 2))
            pill = QRectF(px, 2, ptw, 18)

        # Abwesenheits-Bänder (grau, schraffiert)
        hatch = theme.c("muted", 0.22 if dark else 0.18)
        for a, b, reason, running in self.aways:
            x0, x1 = self._x(a), self._x(b)
            if x1 - x0 < 3:
                x1 = x0 + 3
            r = QRectF(x0, top - 4, x1 - x0, bottom - top + 8)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.c("muted", 0.13 if dark else 0.10))
            p.drawRoundedRect(r, 4, 4)
            p.save()
            p.setClipRect(r)
            p.setPen(QPen(hatch, 1))
            step = 7
            k = x0 - (bottom - top + 8)
            while k < x1:
                p.drawLine(QPointF(k, bottom + 4), QPointF(k + (bottom - top + 8), top - 4))
                k += step
            p.restore()
            dur = _fmt_dur((b - a).total_seconds())
            name = AWAY_LABELS.get(reason, "Abwesend")
            icon = AWAY_ICONS.get(reason, "")
            limit = pill.left() - 4 if pill is not None and pill.left() > x0 else x1
            room = min(x1, limit) - x0
            p.setFont(small)
            txt = f"{icon} {dur}"
            tw = p.fontMetrics().horizontalAdvance(txt)
            if room > tw + 8:
                p.setPen(theme.c("muted"))
                p.drawText(QRectF(x0 + (room - tw) / 2 - 2, 2, tw + 4, 18), Qt.AlignCenter, txt)
            tip = (f"{name} seit {a:%H:%M} Uhr ({dur})" if running
                   else f"{name} {a:%H:%M} – {b:%H:%M} Uhr ({dur})")
            if reason == "idle":
                tip += "\nKeine Eingabe – was hier fällig war, ist neutral als ausgelassen vermerkt."
            else:
                tip += ("\nErinnerungen mit Dauer (z. B. Augen entspannen, Aufstehen) zählen hier als "
                        "erledigt – du warst ja weg vom Bildschirm.")
            self._hits.append((QPointF((x0 + x1) / 2, 11), tip, (x1 - x0) / 2 + 4))

        # Pausen-Bänder
        for a, b, running in self.pauses:
            x0, x1 = self._x(a), self._x(b)
            if x1 - x0 < 3:
                x1 = x0 + 3
            r = QRectF(x0, top - 4, x1 - x0, bottom - top + 8)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.c("accent", (0.30 if running else 0.20) if dark else (0.22 if running else 0.14)))
            p.drawRoundedRect(r, 4, 4)
            # Beschriftung oben
            label = _fmt_dur((b - a).total_seconds())
            p.setFont(small)
            tw = p.fontMetrics().horizontalAdvance(label)
            cx = (x0 + x1) / 2
            p.setBrush(theme.c("accent"))
            limit = pill.left() - 4 if pill is not None and pill.left() > x0 else x1
            room = min(x1, limit) - x0
            with_text = room > tw + 16
            if with_text:
                bx = x0 + (room - tw - 10) / 2
            else:
                bx = min(cx, (limit if pill is not None and limit < x1 else cx) - 8) - 3.5
                if pill is not None and pill.left() - 8 <= bx <= pill.right():
                    bx = None   # kein Platz neben der Jetzt-Marke
            if bx is not None:
                p.drawRoundedRect(QRectF(bx, 7, 2.4, 8), 1, 1)
                p.drawRoundedRect(QRectF(bx + 4.4, 7, 2.4, 8), 1, 1)
            if with_text:
                p.setPen(theme.c("accent"))
                p.drawText(QRectF(bx + 10, 2, tw + 4, 18), Qt.AlignLeft | Qt.AlignVCenter, label)
            tip = (f"Pause seit {a:%H:%M} Uhr ({label})" if running
                   else f"Pause {a:%H:%M} – {b:%H:%M} Uhr ({label})")
            self._hits.append((QPointF(cx, 11), tip, (x1 - x0) / 2 + 4))

        # Spuren
        emoji = QFont(EMOJI_FONT)
        emoji.setPixelSize(max(9, min(16, lh - 5)))
        for i, ln in enumerate(self.lanes):
            cy = top + i * lh + lh / 2
            col = QColor(ln["color"])
            if not ln["enabled"]:
                col.setAlphaF(0.4)
            p.setFont(emoji)
            p.setPen(theme.c("text"))
            p.drawText(QRectF(0, cy - lh / 2, GUTTER - 8, lh), Qt.AlignRight | Qt.AlignVCenter, ln["icon"])
            if self.active_win:
                line = QColor(col)
                line.setAlphaF(0.28 if dark else 0.35)
                p.setPen(QPen(line, 1.5))
                p.drawLine(QPointF(self._x(self.active_win[0]) + 4, cy), QPointF(self._x(self.active_win[1]) - 4, cy))
            r_plan = max(2.5, min(4.2, lh * 0.2))
            r_done = max(3.5, min(6.5, lh * 0.32))
            # geplant
            for d in ln["planned"]:
                x = self._x(d)
                p.setPen(QPen(col, 1.6))
                p.setBrush(theme.c("surface"))
                p.drawEllipse(QPointF(x, cy), r_plan, r_plan)
                self._hits.append((QPointF(x, cy), f"{ln['name']} · geplant {d:%H:%M} Uhr", r_plan + 3))
            # übersprungen
            for d in ln["skipped"]:
                x = self._x(d)
                k = r_plan + 0.6
                p.setPen(QPen(theme.c("danger"), 1.8, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(x - k, cy - k), QPointF(x + k, cy + k))
                p.drawLine(QPointF(x - k, cy + k), QPointF(x + k, cy - k))
                self._hits.append((QPointF(x, cy), f"{ln['name']} · übersprungen {d:%H:%M} Uhr", r_done + 2))
            # ausgelassen (fiel in eine Abwesenheit): gestrichelter grauer Ring
            for d, via in ln["missed"]:
                x = self._x(d)
                p.setPen(QPen(theme.c("faint"), 1.3, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(x, cy), r_plan, r_plan)
                why = AWAY_LABELS.get(via, "abwesend")
                self._hits.append((QPointF(x, cy), f"{ln['name']} · {d:%H:%M} Uhr ausgelassen – {why}", r_plan + 3))
            # erledigt: Punkt in eigener Farbe + grüner Haken (automatisch während Sperre: mit Schloss)
            for d, snoozes, via in ln["done"]:
                x = self._x(d)
                auto = via in AWAY_LABELS
                p.setPen(QPen(theme.c("surface"), 1.5))
                fill = QColor(col)
                if auto:
                    fill.setAlphaF(fill.alphaF() * 0.55)
                p.setBrush(fill)
                p.drawEllipse(QPointF(x, cy), r_done, r_done)
                self._check(p, QPointF(x + r_done * 0.75, cy - r_done * 0.65), max(3.6, r_done * 0.72))
                if auto:
                    self._lock(p, QPointF(x - r_done * 0.8, cy + r_done * 0.55), max(3.2, r_done * 0.6))
                    extra = f" · automatisch ({AWAY_LABELS[via]})"
                else:
                    extra = f" · vorher {snoozes}× verschoben" if snoozes else ""
                self._hits.append((QPointF(x, cy), f"{ln['name']} · erledigt {d:%H:%M} Uhr{extra}", r_done + 3))
            # gerade fällig
            if ln["current"] and lo <= now <= hi:
                x = self._x(now)
                p.setPen(QPen(col, 2))
                p.setBrush(col)
                p.drawEllipse(QPointF(x, cy), r_done, r_done)
                self._hits.append((QPointF(x, cy), f"{ln['name']} · jetzt fällig", r_done + 3))

        # Jetzt-Linie
        if pill is not None:
            x = self._x(now)
            p.setPen(QPen(theme.c("accent"), 2))
            p.drawLine(QPointF(x, top - 6), QPointF(x, bottom + 4))
            p.setFont(fpill)
            txt = now.strftime("%H:%M")
            p.setPen(Qt.NoPen)
            p.setBrush(theme.c("accent"))
            p.drawRoundedRect(pill, 9, 9)
            p.setPen(QColor(theme.P["accent_text"]))
            p.drawText(pill, Qt.AlignCenter, txt)
        p.end()

    def _lock(self, p: QPainter, c: QPointF, r: float):
        """Kleines Schloss-Abzeichen: automatisch eingetragen, weil der PC gesperrt war."""
        p.setPen(QPen(theme.c("surface"), 1.2))
        p.setBrush(theme.c("muted"))
        p.drawEllipse(c, r, r)
        w, h = r * 0.9, r * 0.62
        body = QRectF(c.x() - w / 2, c.y() - h * 0.15, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(body, 0.8, 0.8)
        p.setPen(QPen(QColor("#FFFFFF"), max(0.9, r * 0.2)))
        p.setBrush(Qt.NoBrush)
        sw = w * 0.62
        p.drawArc(QRectF(c.x() - sw / 2, body.top() - sw * 0.75, sw, sw * 1.2), 0, 180 * 16)

    def _check(self, p: QPainter, c: QPointF, r: float):
        p.setPen(QPen(theme.c("surface"), 1.2))
        p.setBrush(theme.c("success"))
        p.drawEllipse(c, r, r)
        path = QPainterPath()
        path.moveTo(c.x() - r * 0.45, c.y() + r * 0.02)
        path.lineTo(c.x() - r * 0.1, c.y() + r * 0.38)
        path.lineTo(c.x() + r * 0.5, c.y() - r * 0.36)
        pen = QPen(QColor("#FFFFFF"), max(1.1, r * 0.32), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    # ------------------------------------------------------------------ Tooltips
    def mouseMoveEvent(self, e):
        pos = e.position()
        best, bd = None, 1e9
        for pt, tip, rad in self._hits:
            d = max(abs(pt.x() - pos.x()) - (rad if rad > 12 else 0), 0) ** 2 + (pt.y() - pos.y()) ** 2 \
                if rad > 12 else (pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2
            lim = (rad if rad <= 12 else 12) ** 2
            if d <= lim and d < bd:
                best, bd = tip, d
        if best:
            QToolTip.showText(e.globalPosition().toPoint(), best, self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, e):
        QToolTip.hideText()
