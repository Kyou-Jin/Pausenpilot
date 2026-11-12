"""Kompaktfenster: klein, rahmenlos, verschiebbar – zeigt nur die nächste Erinnerung.

Unten ein Mini-Zeitstrahl des Tages mit Haken/Kreuzen, Pausen und der Tagesmedaille.
Erinnerungen erscheinen im Kompaktmodus an derselben Stelle im Kompaktformat (siehe AlarmWindow).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import schedule, theme
from .main_window import PAUSE_CHOICES, fmt_due, fmt_elapsed, fmt_remaining
from .models import MEDAL_MIN_ENTRIES, MEDAL_NAMES, day_rating, next_medal
from .schedule import PHASE_ALARM, PHASE_QUEUED, PHASE_RUNNING
from .storage import ACTION_DONE, ACTION_SKIP
from .widgets import IconBubble, MedalIcon, ProgressRing, label, line_icon, paint_line_icon

MARGIN = 12          # Platz für den Schatten
COMPACT_WIDTH = 340


class MiniDay(QWidget):
    """Schmaler Tagesbalken: vergangene Zeit, Pausen, erledigt (grün) / übersprungen (rot), Jetzt."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.range = None
        self.now = datetime.now()
        self.done: list[datetime] = []
        self.skipped: list[datetime] = []
        self.pauses: list[tuple[datetime, datetime]] = []
        self._sig = None

    def set_state(self, rng, now, done, skipped, pauses):
        sig = (rng, now.replace(second=0, microsecond=0), tuple(done), tuple(skipped),
               tuple((a, b.replace(second=0, microsecond=0)) for a, b in pauses), theme.P.get("is_dark"))
        if sig == self._sig:
            return
        self._sig = sig
        self.range, self.now, self.done, self.skipped, self.pauses = rng, now, done, skipped, pauses
        self.update()

    def _x(self, t: datetime) -> float:
        lo, hi = self.range
        span = max(1.0, (hi - lo).total_seconds())
        return 4 + max(0.0, min(1.0, (t - lo).total_seconds() / span)) * (self.width() - 8)

    def paintEvent(self, _):
        if not self.range:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = bool(theme.P.get("is_dark"))
        cy = self.height() / 2
        track = QRectF(4, cy - 3, self.width() - 8, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.c("surface3") if dark else theme.c("border"))
        p.drawRoundedRect(track, 3, 3)
        lo, hi = self.range
        if self.now > lo:
            p.setBrush(theme.c("accent", 0.35 if dark else 0.28))
            p.drawRoundedRect(QRectF(4, cy - 3, self._x(self.now) - 4, 6), 3, 3)
        for a, b in self.pauses:
            p.setBrush(theme.c("accent", 0.75))
            x0, x1 = self._x(a), self._x(b)
            p.drawRoundedRect(QRectF(x0, cy - 3, max(2.5, x1 - x0), 6), 2, 2)
        for t in self.skipped:
            x = self._x(t)
            p.setPen(QPen(theme.c("danger"), 1.6, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x - 3, cy - 3), QPointF(x + 3, cy + 3))
            p.drawLine(QPointF(x - 3, cy + 3), QPointF(x + 3, cy - 3))
        p.setPen(QPen(theme.c("surface"), 1.2))
        p.setBrush(theme.c("success"))
        for t in self.done:
            p.drawEllipse(QPointF(self._x(t), cy), 3.6, 3.6)
        if lo <= self.now <= hi:
            x = self._x(self.now)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.c("accent"))
            p.drawRoundedRect(QRectF(x - 1, 0, 2, self.height()), 1, 1)
        p.end()


class PauseBubble(QPushButton):
    """Großes Pause-Symbol links – während der Pause ein echter Knopf: zeigt beim Drüberfahren ▶
    und beendet die Pause per Klick."""

    def __init__(self, size: int = 38, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Pause beenden – die Erinnerungen laufen weiter")
        self.setAttribute(Qt.WA_Hover)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hover = self.underMouse()
        down = self.isDown()
        dark = bool(theme.P.get("is_dark"))
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        if hover:
            p.setBrush(theme.c("accent_hover" if down else "accent"))
        else:
            p.setBrush(theme.c("accent", 0.2 if dark else 0.14))
        p.drawRoundedRect(r, 10, 10)
        col = QColor(theme.P["accent_text"]) if hover else theme.c("accent")
        s = self.width() * 0.47
        ir = QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s)
        paint_line_icon(p, "play" if hover else "pause", ir, col, 2)
        p.end()


class CompactWindow(QWidget):
    expand_requested = Signal()
    pause_requested = Signal(int)
    resume_requested = Signal()
    moved = Signal(QPoint)
    quit_requested = Signal()
    hide_requested = Signal()
    queued_done = Signal(str)      # wartende Erinnerung (z. B. wegen Vollbild) direkt erledigt

    def __init__(self, on_top: bool = True):
        super().__init__(None, self._flags(on_top))
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("Pausenpilot – kompakt")
        self._drag: QPoint | None = None
        self._dragged = False
        self._paused = False
        self._layout_paused = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(MARGIN, MARGIN - 4, MARGIN, MARGIN + 4)
        self.card = QFrame()
        self.card.setObjectName("compactCard")
        self.card.setFixedWidth(COMPACT_WIDTH)
        self.shadow = QGraphicsDropShadowEffect(self.card)
        self.shadow.setBlurRadius(22)
        self.shadow.setOffset(0, 4)
        self.shadow.setColor(QColor(0, 0, 0, 90))
        self.card.setGraphicsEffect(self.shadow)
        outer.addWidget(self.card)

        v = QVBoxLayout(self.card)
        v.setContentsMargins(14, 12, 12, 10)
        v.setSpacing(0)
        row = QHBoxLayout()
        row.setSpacing(11)
        self.bubble = IconBubble("⭐", theme.P["accent"], 38)
        row.addWidget(self.bubble)
        self.pause_bubble = PauseBubble(38)
        self.pause_bubble.clicked.connect(self._resume_clicked)
        self.pause_bubble.hide()
        row.addWidget(self.pause_bubble)
        tv = QVBoxLayout()
        tv.setSpacing(1)
        self.title = label("", "compactTitle")
        self.sub = label("", "compactSub")
        for lb in (self.title, self.sub):
            lb.setMinimumWidth(1)
            lb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        tv.addWidget(self.title)
        tv.addWidget(self.sub)
        row.addLayout(tv, 1)
        self.ring = ProgressRing(44, 4)
        row.addWidget(self.ring)
        self.done_btn = QPushButton("✓")
        self.done_btn.setObjectName("compactCheck")
        self.done_btn.setFixedSize(44, 44)
        self.done_btn.setCursor(Qt.PointingHandCursor)
        self.done_btn.clicked.connect(self._done_clicked)
        self.done_btn.hide()
        self._queued_tid = None
        row.addWidget(self.done_btn)
        self.end_pause = QPushButton("Beenden")
        self.end_pause.setObjectName("compactPrimary")
        self.end_pause.setCursor(Qt.PointingHandCursor)
        self.end_pause.setToolTip("Pause beenden – die Erinnerungen laufen weiter")
        self.end_pause.clicked.connect(self._resume_clicked)
        self.end_pause.hide()
        row.addWidget(self.end_pause)
        btns = QVBoxLayout()
        btns.setSpacing(4)
        self.pause_btn = self._icon_btn("pause", "Pause starten (bis du sie beendest)")
        self.pause_btn.clicked.connect(self._pause_clicked)
        self.expand_btn = self._icon_btn("expand", "Großes Fenster öffnen")
        self.expand_btn.clicked.connect(self.expand_requested.emit)
        btns.addWidget(self.pause_btn)
        btns.addWidget(self.expand_btn)
        row.addLayout(btns)
        v.addLayout(row)
        v.addSpacing(9)
        self.mini = MiniDay()
        v.addWidget(self.mini)
        v.addSpacing(3)
        foot = QHBoxLayout()
        foot.setSpacing(6)
        self.f_start = label("", "faint")
        self.f_end = label("", "faint")
        self.medal = MedalIcon(16)
        self.medal.hide()
        self.f_medal = QLabel()
        self.f_medal.setObjectName("compactSub")
        self.f_medal.setTextFormat(Qt.RichText)
        foot.addWidget(self.f_start)
        foot.addStretch(1)
        foot.addWidget(self.medal)
        foot.addWidget(self.f_medal)
        foot.addStretch(1)
        foot.addWidget(self.f_end)
        v.addLayout(foot)
        self.setToolTip("Doppelklick: großes Fenster · Ziehen: verschieben · Rechtsklick: Menü")

    def _pause_clicked(self):
        self._last_button = time.monotonic()
        self.pause_requested.emit(0)

    def _done_clicked(self):
        self._last_button = time.monotonic()
        if self._queued_tid:
            self.queued_done.emit(self._queued_tid)

    def _set_done_btn(self, tid, tip: str = ""):
        """Knopf „✓ Erledigt“ statt Ring, solange eine Erinnerung nur wartet (z. B. Vollbild)."""
        self._queued_tid = tid
        self.done_btn.setToolTip(tip)
        show = tid is not None
        if self.done_btn.isHidden() == show or self.ring.isHidden() != (show or self._paused):
            self.done_btn.setVisible(show)
            self.ring.setVisible(not show and not self._paused)
            self._fit()

    def _resume_clicked(self):
        self._last_button = time.monotonic()
        self.resume_requested.emit()

    @staticmethod
    def _flags(on_top: bool):
        f = Qt.Tool | Qt.FramelessWindowHint
        return f | Qt.WindowStaysOnTopHint if on_top else f

    def set_on_top(self, on: bool):
        if bool(self.windowFlags() & Qt.WindowStaysOnTopHint) == on:
            return
        vis = self.isVisible()
        self.setWindowFlags(self._flags(on))
        if vis:
            self.show()

    def _icon_btn(self, icon: str, tip: str) -> QPushButton:
        b = QPushButton()
        b.setObjectName("compactIcon")
        b.setFixedSize(28, 26)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(tip)
        b.setProperty("lineIcon", icon)
        b.setIcon(line_icon(icon, theme.P["muted"], 15))
        return b

    def apply_theme(self):
        for b in (self.pause_btn, self.expand_btn):
            b.setIcon(line_icon(b.property("lineIcon"), theme.P["muted"], 15))
        self.pause_bubble.update()
        self.shadow.setColor(QColor(0, 0, 0, 100 if theme.P.get("is_dark") else 45))

    # ------------------------------------------------------------------ Inhalt
    def update_status(self, sched, now: datetime, entries, pauses, summary, away: bool, held: bool = False):
        paused = sched.paused_until is not None
        if paused != self._layout_paused:
            self._paused = self._layout_paused = paused
            self.bubble.setVisible(not paused)
            self.pause_bubble.setVisible(paused)
            self.ring.setVisible(not paused)
            self.end_pause.setVisible(paused)
            self.pause_btn.setVisible(not paused)
            self._fit()

        if paused:
            self._set_done_btn(None)
            since = sched.paused_since or now
            rest = "" if sched.pause_open else f" · bis {sched.paused_until:%H:%M}"
            self._set_texts(f"Pause seit {since:%H:%M}",
                            f"{fmt_elapsed((now - since).total_seconds())}{rest} · Erinnerungen ruhen")
        else:
            self._show_next(sched, now, away, held)

        # Mini-Zeitstrahl + Medaille
        w = schedule.window_for(sched.settings, now.date())
        if w:
            lo, hi = w
        else:
            lo = datetime.combine(now.date(), datetime.min.time()) + timedelta(hours=8)
            hi = lo + timedelta(hours=10)
        done = [e.ts for e in entries if e.action == ACTION_DONE]
        skipped = [e.ts for e in entries if e.action == ACTION_SKIP]
        ps = list(pauses) + ([(sched.paused_since or now, now)] if paused else [])
        self.mini.set_state((lo, hi), now, done, skipped, ps)
        self.f_start.setText(lo.strftime("%H:%M"))
        self.f_end.setText("24:00" if hi.date() > lo.date() else hi.strftime("%H:%M"))
        key, pct = day_rating(summary.done, summary.skips)
        self.medal.set(key)
        P = theme.P
        total = summary.done + summary.skips
        if total < MEDAL_MIN_ENTRIES:
            txt = f'<span style="color:{P["faint"]}">{summary.done} erledigt</span>'
        else:
            name = MEDAL_NAMES.get(key, "") if key not in (None, "thumb") else ""
            col = P["danger"] if key == "thumb" else P["text"]
            txt = f'<span style="color:{col}">{name + " · " if name else ""}{pct} %</span>'
            nxt = next_medal(summary.done, summary.skips)
            if nxt and nxt[1]:
                txt += f'<span style="color:{P["faint"]}"> · noch {nxt[1]} bis {MEDAL_NAMES[nxt[0]]}</span>'
        self.f_medal.setText(txt)

    def _show_next(self, sched, now: datetime, away: bool, held: bool = False):
        items = []
        for t in sched.timers:
            r = sched.rt.get(t.id)
            if t.enabled and r is not None and r.due is not None:
                items.append((r.due, t, r))
        items.sort(key=lambda x: x[0])
        if not items:
            self._set_done_btn(None)
            self.bubble.set("⭐", theme.P["faint"])
            self._set_texts("Keine anstehende Erinnerung", "Zeiten oder Erinnerungen prüfen")
            self.ring.setValue(0)
            self.ring.setText("–")
            return
        due, t, r = items[0]
        waiting = [x for x in sched.queue if x != sched.active]
        if waiting and sched.active is None:
            # Erinnerung wartet (Vollbild/Präsentation) – trotzdem schon abhakbar
            t = sched.timer(waiting[0]) or t
            self.bubble.set(t.icon, t.color)
            more = f" · +{len(waiting) - 1} weitere" if len(waiting) > 1 else ""
            why = "Wartet (Vollbild)" if held else "kommt gleich"
            self._set_texts(t.name, why + more)
            self._set_done_btn(t.id, f"„{t.name}“ schon gemacht? Klick trägt sie als erledigt ein."
                               + (" Sie kommt, sobald das Vollbild endet." if held else ""))
            return
        self._set_done_btn(None)
        self.bubble.set(t.icon, t.color)
        self.ring.setIcon("")
        self.ring.setColor(t.color)
        if r.phase in (PHASE_ALARM, PHASE_RUNNING, PHASE_QUEUED):
            self.ring.setValue(1)
            self.ring.setText("jetzt")
            self._set_texts(t.name, "Läuft gerade" if r.phase == PHASE_RUNNING else "Ist jetzt dran")
            return
        remaining = (due - now).total_seconds()
        total = max(60, t.interval_min * 60)
        self.ring.setValue(1 - remaining / total if remaining < total else 0)
        today = due.date() == now.date()
        self.ring.setText(fmt_remaining(remaining) if today and remaining < 3600 * 10 else due.strftime("%H:%M"))
        sub = f"{fmt_due(due, now)} Uhr" if not today else f"um {due:%H:%M} Uhr"
        if away:
            sub = "Du bist gerade nicht am PC"
            self.ring.setIcon("moon")
            self.ring.setValue(0)
        elif not schedule.is_active_now(sched.settings, now):
            sub = f"Außerhalb der aktiven Zeit · {fmt_due(due, now)} Uhr"
        self._set_texts(t.name, sub)

    @staticmethod
    def _elide(lb, text: str):
        w = lb.width() if lb.width() > 20 else 180
        short = lb.fontMetrics().elidedText(text, Qt.ElideRight, w)
        if lb.text() != short:
            lb.setText(short)
        lb.setToolTip(text if short != text else "")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        for lb, attr in ((self.title, "_full_title"), (self.sub, "_full_sub")):
            if hasattr(self, attr):
                self._elide(lb, getattr(self, attr))

    def _set_texts(self, title: str, sub: str):
        self._full_title, self._full_sub = title, sub
        self._elide(self.title, title)
        self._elide(self.sub, sub)

    def _fit(self):
        self.card.layout().activate()
        self.layout().activate()
        self.resize(self.minimumSizeHint().expandedTo(self.sizeHint()))

    # ------------------------------------------------------------------ Position
    def place(self, pos_str: str, ref_screen=None):
        self._fit()
        pt = None
        try:
            x, y = (int(v) for v in pos_str.split(","))
            pt = QPoint(x, y)
        except (ValueError, AttributeError):
            pass
        screens = QGuiApplication.screens()
        if pt is None or not any(s.availableGeometry().intersects(self.frameGeometry().translated(
                pt - self.frameGeometry().topLeft())) for s in screens):
            scr = ref_screen or QGuiApplication.primaryScreen()
            g = scr.availableGeometry()
            pt = QPoint(g.right() - self.width() - 8, g.bottom() - self.height() - 8)
        self.move(self._clamp(pt))

    def _clamp(self, pt: QPoint) -> QPoint:
        scr = QGuiApplication.screenAt(pt + QPoint(self.width() // 2, self.height() // 2)) or \
            QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        x = max(g.left() - MARGIN, min(pt.x(), g.right() - self.width() + MARGIN))
        y = max(g.top() - MARGIN, min(pt.y(), g.bottom() - self.height() + MARGIN))
        return QPoint(x, y)

    def card_rect_global(self):
        """Bildschirm-Rechteck der sichtbaren Karte (für die Erinnerung an derselben Stelle)."""
        tl = self.card.mapToGlobal(QPoint(0, 0))
        return tl, self.card.size()

    # ------------------------------------------------------------------ Maus
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragged = False

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self._dragged = True
            self.move(self._clamp(e.globalPosition().toPoint() - self._drag))

    def mouseReleaseEvent(self, e):
        if self._drag is not None and self._dragged:
            self.moved.emit(self.pos())
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        # Kein großes Fenster, wenn der Doppelklick nur „zweiter Klick“ auf einen Knopf war,
        # der gerade verschwunden ist (z. B. „Beenden“ nach dem Ende der Pause)
        recent = time.monotonic() - getattr(self, "_last_button", 0.0) < \
            max(0.6, QApplication.doubleClickInterval() / 1000 + 0.15)
        if e.button() == Qt.LeftButton and not recent:
            self.expand_requested.emit()

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.addAction("Großes Fenster öffnen", self.expand_requested.emit)
        if self._paused:
            m.addAction("Pause beenden", self.resume_requested.emit)
        else:
            sub = m.addMenu("Pause starten")
            for mins, txt in PAUSE_CHOICES:
                sub.addAction(txt, lambda m_=mins: self.pause_requested.emit(m_))
        m.addSeparator()
        m.addAction("Ausblenden (läuft im Infobereich weiter)", self.hide_requested.emit)
        m.addAction("Beenden", self.quit_requested.emit)
        m.exec(e.globalPos())
