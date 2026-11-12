"""Hauptfenster: Seitenleiste + Seiten (Erinnerungen, Kalender, Einstellungen)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QByteArray, QSize, Qt, Signal
from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from . import APP_NAME, APP_VERSION, conflicts, schedule, theme
from .models import (MAX_TIMERS, MEDAL_MIN_ENTRIES, MEDAL_NAMES, MONTHS, WEEKDAYS, WEEKDAYS_SHORT, TimerConfig,
                     day_rating, fmt_duration, fmt_interval, next_medal)
from .schedule import PHASE_ALARM, PHASE_QUEUED, PHASE_RUNNING
from .timeline import DayTimeline
from .widgets import IconBubble, LineIcon, MedalIcon, ProgressRing, ToggleSwitch, app_icon, label, line_icon


def fmt_due(due: datetime | None, now: datetime) -> str:
    if due is None:
        return "kein Termin in den nächsten Tagen"
    if due.date() == now.date():
        return f"heute {due:%H:%M}"
    if due.date() == now.date() + timedelta(days=1):
        return f"morgen {due:%H:%M}"
    return f"{WEEKDAYS_SHORT[due.weekday()]} {due:%d.%m.} {due:%H:%M}"


def fmt_remaining(sec: float) -> str:
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec} s"
    if sec < 3600:
        return f"{(sec + 59) // 60} Min"
    h, rem = divmod(sec, 3600)
    return f"{h}:{rem // 60:02d} h"


def fmt_elapsed(sec: float) -> str:
    """Laufende Dauer: 0:42 → „42 Min“, 1:05 → „1:05 h“."""
    m = max(0, int(sec)) // 60
    return f"{m} Min" if m < 60 else f"{m // 60}:{m % 60:02d} h"


# Minuten; 0 = offen (bis „Pause beenden“), -1 = bis morgen
PAUSE_CHOICES = ((0, "Bis ich sie beende"), (30, "30 Minuten"), (60, "1 Stunde"), (120, "2 Stunden"),
                 (-1, "Bis morgen"))


class TimerCard(QFrame):
    edit = Signal(str)
    toggled = Signal(str, bool)
    delete = Signal(str)
    trigger = Signal(str)

    def __init__(self, timer: TimerConfig, parent=None):
        super().__init__(parent)
        self.setObjectName("timerCard")
        self.setCursor(Qt.PointingHandCursor)
        self.timer = timer
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 14, 12, 14)
        h.setSpacing(14)
        self.bubble = IconBubble(timer.icon, timer.color, 46)
        h.addWidget(self.bubble)
        v = QVBoxLayout()
        v.setSpacing(2)
        self.title = label(timer.name, "h3")
        self.meta = label("", "faint")
        self.next = label("", "muted")
        v.addWidget(self.title)
        v.addWidget(self.meta)
        v.addWidget(self.next)
        h.addLayout(v, 1)
        self.ring = ProgressRing(58, 5)
        self.ring.setColor(timer.color)
        self.ring.setToolTip("Zeit bis zur nächsten Erinnerung")
        h.addWidget(self.ring)
        h.addSpacing(6)
        self.switch = ToggleSwitch(checked=timer.enabled)
        self.switch.setToolTip("Erinnerung aktiv / pausiert")
        self.switch.toggled.connect(lambda on: self.toggled.emit(self.timer.id, on))
        h.addWidget(self.switch)
        more = QPushButton()
        more.setObjectName("iconButton")
        more.setIcon(line_icon("more", theme.P["muted"], 18))
        more.setFixedSize(34, 34)
        more.setCursor(Qt.PointingHandCursor)
        more.setToolTip("Weitere Aktionen")
        menu = QMenu(more)
        a_edit = menu.addAction("Bearbeiten")
        a_edit.triggered.connect(lambda: self.edit.emit(self.timer.id))
        self.a_now = menu.addAction("Jetzt erinnern")
        self.a_now.triggered.connect(lambda: self.trigger.emit(self.timer.id))
        menu.addSeparator()
        a_del = menu.addAction("Löschen …")
        a_del.triggered.connect(lambda: self.delete.emit(self.timer.id))
        more.clicked.connect(lambda: menu.exec(more.mapToGlobal(more.rect().bottomLeft())))
        h.addWidget(more)
        self.set_timer(timer)

    def set_timer(self, t: TimerConfig):
        self.timer = t
        self.bubble.set(t.icon, t.color)
        self.bubble.setDim(not t.enabled)
        self.ring.setColor(t.color if t.enabled else theme.P["faint"])
        self.title.setText(t.name)
        dur = f"Dauer {fmt_duration(t.duration_sec)}" if t.duration_sec > 0 else "ohne Countdown"
        self.meta.setText(f"alle {fmt_interval(t.interval_min)}  ·  {dur}  ·  ab {t.first_start} Uhr")
        self.switch.setCheckedSilent(t.enabled)
        self.title.setEnabled(t.enabled)

    def update_status(self, rt, now: datetime, paused: bool, away: bool):
        t = self.timer
        self.a_now.setEnabled(t.enabled and rt is not None and rt.phase == schedule.PHASE_WAITING and not paused)
        self.ring.setIcon("")
        self.ring.setColor(t.color if t.enabled and not paused else theme.P["faint"])
        if not t.enabled or rt is None:
            self.ring.setValue(0)
            self.ring.setText("aus")
            self.next.setText("Ausgeschaltet – mit dem Schalter wieder aktivieren")
            return
        if paused and rt.phase not in (PHASE_RUNNING,):
            self.ring.setValue(0)
            self.ring.setIcon("pause")
            self.next.setText("Ruht während der Pause")
            return
        if rt.phase in (PHASE_ALARM, PHASE_RUNNING):
            self.ring.setValue(1)
            self.ring.setText("jetzt")
            self.next.setText("Läuft gerade" if rt.phase == PHASE_RUNNING else "Erinnerung wird angezeigt")
            return
        if rt.phase == PHASE_QUEUED:
            self.ring.setValue(1)
            self.ring.setText("gleich")
            self.next.setText("Wartet, bis die aktuelle Erinnerung erledigt ist")
            return
        if rt.due is None:
            self.ring.setValue(0)
            self.ring.setText("–")
            self.next.setText("Kein Termin im aktiven Zeitraum – Zeiten prüfen")
            return
        remaining = (rt.due - now).total_seconds()
        total = t.interval_min * 60
        self.ring.setValue(1 - remaining / total if remaining < total else 0)
        txt = "Nächste Erinnerung " + fmt_due(rt.due, now) + " Uhr"
        if rt.snoozes:
            txt += f"  ·  {rt.snoozes}× verschoben"
        if away:
            self.ring.setValue(0)
            self.ring.setIcon("moon")
            txt = "Du bist gerade nicht am PC – Erinnerungen warten"
        elif rt.due.date() == now.date() or remaining < 3600:
            self.ring.setText(fmt_remaining(remaining))
        else:
            self.ring.setText(rt.due.strftime("%H:%M"))
        self.next.setText(txt)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.edit.emit(self.timer.id)
        super().mouseReleaseEvent(e)


class StatTile(QFrame):
    def __init__(self, caption: str, key: str, parent=None):
        super().__init__(parent)
        self.setObjectName("statTile")
        self.key = key
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(0)
        self.value = QLabel("0")
        self.value.setObjectName("statValue")
        v.addWidget(self.value)
        v.addWidget(label(caption, "statLabel"))

    def set(self, n: int, highlight: bool = True):
        self.value.setText(str(n))
        col = theme.P[self.key] if (n and highlight) else theme.P["text"]
        self.value.setStyleSheet(f"color: {col};")


class TimersPage(QWidget):
    new_timer = Signal()
    pause_requested = Signal(int)      # Minuten; -1 = bis morgen
    resume_requested = Signal()
    compact_requested = Signal()
    replan_requested = Signal()
    conflict_fix_requested = Signal(str, str)   # Timer-ID, neue Startzeit "HH:MM"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("scrollBody")
        scroll.setWidget(body)
        outer.addWidget(scroll)

        root = QVBoxLayout(body)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(0)

        head = QHBoxLayout()
        tv = QVBoxLayout()
        tv.setSpacing(2)
        self.greeting = label("", "h1")
        tv.addWidget(self.greeting)
        self.subtitle = label("", "muted")
        tv.addWidget(self.subtitle)
        head.addLayout(tv, 1)
        self.compact_btn = QPushButton("  Kompakt")
        self.compact_btn.setIcon(line_icon("compact", theme.P["muted"], 16))
        self.compact_btn.setCursor(Qt.PointingHandCursor)
        self.compact_btn.setToolTip("Kompaktmodus – kleines Fenster, das nur die nächste Erinnerung zeigt")
        self.compact_btn.clicked.connect(self.compact_requested.emit)
        head.addWidget(self.compact_btn, 0, Qt.AlignTop)
        head.addSpacing(8)
        self.pause_btn = QPushButton("  Pause starten")
        self.pause_btn.setIcon(line_icon("pause", theme.P["muted"], 16))
        self.pause_btn.setCursor(Qt.PointingHandCursor)
        self.pause_btn.clicked.connect(self._pause_clicked)
        head.addWidget(self.pause_btn, 0, Qt.AlignTop)
        head.addSpacing(4)
        self.pause_more = QPushButton()
        self.pause_more.setIcon(line_icon("down", theme.P["muted"], 16))
        self.pause_more.setCursor(Qt.PointingHandCursor)
        self.pause_more.setToolTip("Pause mit festem Ende")
        self.pause_more.setFixedSize(38, self.pause_btn.sizeHint().height())
        self.pause_menu = QMenu(self.pause_more)
        for mins, txt in PAUSE_CHOICES[1:]:
            a = self.pause_menu.addAction(txt)
            a.triggered.connect(lambda _=False, m=mins: self.pause_requested.emit(m))
        self.pause_more.clicked.connect(
            lambda: self.pause_menu.exec(self.pause_more.mapToGlobal(self.pause_more.rect().bottomLeft())))
        head.addWidget(self.pause_more, 0, Qt.AlignTop)
        head.addSpacing(8)
        self.add_btn = QPushButton("  Neue Erinnerung")
        self.add_btn.setIcon(line_icon("plus", "#FFFFFF", 16, 2.0))
        self.add_btn.setObjectName("primary")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self.new_timer.emit)
        head.addWidget(self.add_btn, 0, Qt.AlignTop)
        root.addLayout(head)
        root.addSpacing(18)

        # Tages-Zeitstrahl
        tl_card = QFrame()
        tl_card.setObjectName("card")
        tv2 = QVBoxLayout(tl_card)
        tv2.setContentsMargins(16, 12, 16, 10)
        tv2.setSpacing(6)
        tl_head = QHBoxLayout()
        tl_head.addWidget(label("DEIN TAG", "sectionTitle"))
        tl_head.addSpacing(14)
        self.medal = MedalIcon(22)
        self.medal.hide()
        tl_head.addWidget(self.medal)
        self.medal_text = QLabel()
        self.medal_text.setTextFormat(Qt.RichText)
        self.medal_text.setObjectName("muted")
        tl_head.addWidget(self.medal_text)
        tl_head.addStretch(1)
        self.tl_legend = QLabel()
        self.tl_legend.setObjectName("faint")
        self.tl_legend.setTextFormat(Qt.RichText)
        tl_head.addWidget(self.tl_legend)
        tv2.addLayout(tl_head)
        self.timeline = DayTimeline()
        tv2.addWidget(self.timeline)
        root.addWidget(tl_card)
        root.addSpacing(12)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.t_done = StatTile("heute erledigt", "success")
        self.t_snooze = StatTile("heute verschoben", "warn")
        self.t_skip = StatTile("heute übersprungen", "danger")
        self.t_streak = StatTile("Tage in Folge aktiv", "accent")
        for t in (self.t_done, self.t_snooze, self.t_skip, self.t_streak):
            stats.addWidget(t, 1)
        root.addLayout(stats)
        root.addSpacing(16)

        self.banner_wrap = QWidget()
        bw = QVBoxLayout(self.banner_wrap)
        bw.setContentsMargins(0, 0, 0, 16)
        self.banner = QFrame()
        self.banner.setObjectName("card")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.setSpacing(12)
        self.banner_icon = LineIcon("pause", "accent", 18)
        bl.addWidget(self.banner_icon)
        self.banner_text = label("", "muted", wrap=True)
        bl.addWidget(self.banner_text, 1)
        bw.addWidget(self.banner)
        self.banner_wrap.hide()
        root.addWidget(self.banner_wrap)

        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(10)
        root.addLayout(self.list_layout)
        root.addSpacing(14)
        self.empty = label("Noch keine Erinnerungen. Lege mit „Neue Erinnerung“ die erste an.", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.hide()
        root.addWidget(self.empty)
        # Überschneidungen im heutigen Plan
        self.clash_card = QFrame()
        self.clash_card.setObjectName("card")
        cv = QVBoxLayout(self.clash_card)
        cv.setContentsMargins(18, 14, 18, 14)
        cv.setSpacing(6)
        self.clash_head = QLabel()
        self.clash_head.setTextFormat(Qt.RichText)
        cv.addWidget(self.clash_head)
        self.clash_list = QLabel()
        self.clash_list.setObjectName("muted")
        self.clash_list.setTextFormat(Qt.RichText)
        self.clash_list.setWordWrap(True)
        cv.addWidget(self.clash_list)
        crow = QHBoxLayout()
        crow.setSpacing(12)
        self.clash_tip = QLabel()
        self.clash_tip.setTextFormat(Qt.RichText)
        self.clash_tip.setWordWrap(True)
        crow.addWidget(self.clash_tip, 1)
        self.clash_btn = QPushButton("Vorschlag übernehmen")
        self.clash_btn.setCursor(Qt.PointingHandCursor)
        self.clash_btn.clicked.connect(self._apply_clash_fix)
        crow.addWidget(self.clash_btn, 0, Qt.AlignVCenter)
        cv.addLayout(crow)
        self.clash_card.hide()
        root.addWidget(self.clash_card)
        root.addSpacing(10)
        self._clash_key = None
        self._clash_data = ([], None)
        self._clash_shown = None
        self._suggestion = None

        self.hint = label("Tipp: Unterschiedliche Startzeiten verhindern, dass alle Erinnerungen "
                          "gleichzeitig kommen.", "faint", wrap=True)
        foot = QHBoxLayout()
        foot.setSpacing(12)
        foot.addWidget(self.hint, 1)
        self.replan_btn = QPushButton("  Zeitplan aktualisieren")
        self.replan_btn.setObjectName("primary")
        self.replan_btn.setCursor(Qt.PointingHandCursor)
        self.replan_btn.setIconSize(QSize(16, 16))
        self.replan_btn.setEnabled(False)
        self.replan_btn.setToolTip(
            "Hast du Startzeiten, Intervalle oder aktive Zeiten geändert, richtet dieser Knopf alle\n"
            "Erinnerungen neu danach aus – schon für heute, ab jetzt.\n"
            "Offene und bewusst verschobene Erinnerungen bleiben, wie sie sind.")
        self.replan_btn.clicked.connect(self.replan_requested.emit)
        foot.addWidget(self.replan_btn, 0, Qt.AlignBottom)
        root.addLayout(foot)
        root.addStretch(1)
        self._replan_state = None
        self._set_replan(False)
        self.cards: dict[str, TimerCard] = {}
        self._paused = False

    def _set_replan(self, on: bool):
        key = (on, theme.P.get("is_dark"))
        if key == self._replan_state:
            return
        self._replan_state = key
        self.replan_btn.setEnabled(on)
        self.replan_btn.setIcon(line_icon("refresh", theme.P["accent_text"] if on else theme.P["faint"], 16))
        self.hint.setText("Zeiten geändert – mit „Zeitplan aktualisieren“ gilt das neue Raster schon für heute."
                          if on else "Tipp: Unterschiedliche Startzeiten verhindern, dass alle Erinnerungen "
                                     "gleichzeitig kommen.")

    def _apply_clash_fix(self):
        if self._suggestion:
            self.conflict_fix_requested.emit(self._suggestion.timer.id, self._suggestion.new_start)

    def _update_clashes(self, sched, now: datetime):
        """Karte „Überschneidungen heute“ – Berechnung nur, wenn sich Erinnerungen/Zeiten ändern."""
        today = now.date()
        key = (today, tuple((t.id, t.enabled, t.first_start, t.interval_min, t.duration_sec, t.name, t.icon)
                            for t in sched.timers),
               tuple((d.enabled, d.start, d.end) for d in sched.settings.days))
        if key != self._clash_key:
            self._clash_key = key
            self._clash_data = (conflicts.find_clashes(sched.timers, sched.settings, today),
                                conflicts.suggest(sched.timers, sched.settings, today))
        clashes, sug = self._clash_data
        upcoming = [c for c in clashes
                    if c.first_at + timedelta(seconds=max(60, c.first.duration_sec)) > now]
        shown = (tuple((c.first.id, c.first_at, c.second.id, c.second_at) for c in upcoming[:3]), len(upcoming),
                 (sug.timer.id, sug.new_start, sug.after) if sug else None, theme.P.get("is_dark"))
        if shown == self._clash_shown:
            return
        self._clash_shown = shown
        self._suggestion = sug
        if not upcoming:
            self.clash_card.hide()
            return
        P = theme.P
        n = len(upcoming)
        self.clash_head.setText(
            f'<span style="color:{P["warn"]}; font-weight:600">⚠ {n} '
            f'{"Überschneidung" if n == 1 else "Überschneidungen"} heute</span>'
            f'<span style="color:{P["faint"]}"> · eine Erinnerung wird fällig, während eine andere läuft – '
            f'sie kommt dann direkt danach</span>')
        lines = []
        for c in upcoming[:3]:
            dur = c.first.duration_sec
            what = (f"{c.first.icon} {c.first.name} ({fmt_duration(dur)})" if dur >= 60
                    else f"{c.first.icon} {c.first.name}")
            same = abs((c.second_at - c.first_at).total_seconds()) < 60
            lines.append(f"<b>{c.first_at:%H:%M}</b> {what} – "
                         + (f"gleichzeitig {c.second.icon} {c.second.name}" if same
                            else f"um {c.second_at:%H:%M} wartet {c.second.icon} {c.second.name}"))
        if n > 3:
            lines.append(f'<span style="color:{P["faint"]}">… und {n - 3} weitere</span>')
        self.clash_list.setText("<br>".join(lines))
        if sug:
            res = "keine Überschneidungen mehr" if sug.after == 0 else f"nur noch {sug.after} statt {sug.before}"
            self.clash_tip.setText(
                f'<span style="color:{P["text"]}">💡 Tipp: Startzeit von <b>„{sug.timer.name}“</b> von '
                f'{sug.timer.first_start} auf <b>{sug.new_start}</b> setzen</span>'
                f'<span style="color:{P["muted"]}"> → {res} (ganzer Tag).</span>')
            self.clash_btn.show()
        else:
            self.clash_tip.setText(f'<span style="color:{P["muted"]}">💡 Tipp: Startzeiten um ein paar Minuten '
                                   f'versetzen oder Intervalle anpassen.</span>')
            self.clash_btn.hide()
        self.clash_card.show()

    def _pause_clicked(self):
        if self._paused:
            self.resume_requested.emit()
        else:
            self.pause_requested.emit(0)

    def _update_medal(self, summary):
        key, pct = day_rating(summary.done, summary.skips)
        sig = (key, pct, summary.done, summary.skips, theme.P.get("is_dark"))
        if sig == getattr(self, "_medal_sig", None):
            return
        self._medal_sig = sig
        self.medal.set(key)
        P = theme.P
        total = summary.done + summary.skips
        nxt = next_medal(summary.done, summary.skips)
        hint = ""
        if nxt:
            k, n = nxt
            hint = f" · noch {n} erledigt bis {MEDAL_NAMES[k]}" if n else ""
        if total < MEDAL_MIN_ENTRIES:
            txt = (f'<span style="color:{P["faint"]}">Wertung ab {MEDAL_MIN_ENTRIES} fälligen Erinnerungen '
                   f'({total} bisher)</span>')
        elif key == "thumb":
            txt = (f'<b style="color:{P["danger"]}">{pct} %</b> geschafft ({summary.done} von {total})'
                   f'<span style="color:{P["faint"]}">{hint}</span>')
        elif key:
            txt = (f'<b style="color:{P["text"]}">{MEDAL_NAMES[key]}</b> · {pct} % geschafft '
                   f'({summary.done} von {total})<span style="color:{P["faint"]}">{hint}</span>')
        else:
            txt = (f'{pct} % geschafft ({summary.done} von {total})'
                   f'<span style="color:{P["faint"]}">{hint}</span>')
        self.medal_text.setText(txt)
        self.medal_text.setToolTip("Anteil erledigter an allen fälligen Erinnerungen heute (erledigt + "
                                   "übersprungen).\nAb 70 % Bronze · 80 % Silber · 90 % Gold · 100 % Platin · "
                                   "unter 50 % Daumen runter")
        self.medal.setToolTip(self.medal_text.toolTip())

    def rebuild(self, timers: list[TimerConfig], ctrl):
        for card in self.cards.values():
            card.setParent(None)
            card.deleteLater()
        self.cards.clear()
        for t in timers:
            card = TimerCard(t)
            card.edit.connect(ctrl.edit_timer)
            card.toggled.connect(ctrl.toggle_timer)
            card.delete.connect(ctrl.delete_timer)
            card.trigger.connect(ctrl.trigger_timer)
            self.list_layout.addWidget(card)
            self.cards[t.id] = card
        n = len(timers)
        self.add_btn.setEnabled(n < MAX_TIMERS)
        self.add_btn.setToolTip("" if n < MAX_TIMERS else f"Maximal {MAX_TIMERS} Erinnerungen möglich")
        self.empty.setVisible(n == 0)

    def update_status(self, sched, now: datetime, away: bool, summary, streak: int,
                      entries=(), pauses=(), aways=()):
        paused = sched.paused_until is not None
        self._paused = paused
        self.greeting.setText(f"{WEEKDAYS[now.weekday()]}, {now.day}. {MONTHS[now.month - 1]}")
        w =schedule.window_for(sched.settings, now.date())
        when = (f"Heute aktiv {w[0]:%H:%M} – {'24:00' if w[1].date() > now.date() else w[1].strftime('%H:%M')}"
                if w else "Heute keine aktiven Zeiten")
        self.subtitle.setText(when)
        self.timeline.set_state(sched, entries, pauses, now, aways)
        self._set_replan(bool(getattr(sched, "plan_dirty", False)) and sched.paused_until is None)
        self._update_clashes(sched, now)
        self._update_medal(summary)
        if getattr(self, "_legend_dark", None) != theme.P.get("is_dark"):
            self._legend_dark = theme.P.get("is_dark")
            P = theme.P
            self.tl_legend.setText(
                f'<span style="color:{P["muted"]}">○ geplant</span>&nbsp;&nbsp;&nbsp;'
                f'<span style="color:{P["success"]}">✓ erledigt</span>&nbsp;&nbsp;&nbsp;'
                f'<span style="color:{P["danger"]}">✕ übersprungen</span>&nbsp;&nbsp;&nbsp;'
                f'<span style="color:{P["accent"]}">❚❚ Pause</span>&nbsp;&nbsp;&nbsp;'
                f'<span style="color:{P["muted"]}">🔒 gesperrt</span>')
            self.tl_legend.setToolTip("Grau schraffiert: PC gesperrt, im Standby oder nicht am PC.\n"
                                      "Erinnerungen mit Dauer zählen bei Sperre/Standby als erledigt (mit Schloss),\n"
                                      "alles andere wird neutral als „ausgelassen“ vermerkt – kein Minus für die Medaille.")
        self.t_done.set(summary.done)
        self.t_snooze.set(summary.snoozes)
        self.t_skip.set(summary.skips)
        self.t_streak.set(streak)
        if paused != getattr(self, "_shown_paused", None):
            self._shown_paused = paused
            self.pause_btn.setObjectName("primary" if paused else "")
            self.pause_btn.setIcon(line_icon("stop" if paused else "pause",
                                             "#FFFFFF" if paused else theme.P["muted"], 16))
            self.pause_btn.setToolTip("Pause beenden – die Erinnerungen laufen ab jetzt weiter" if paused else
                                      "Pause starten – alle Erinnerungen ruhen, bis du sie beendest. "
                                      "Die Pause wird im Kalender eingetragen.")
            self.pause_more.setVisible(not paused)
            self.pause_more.setIcon(line_icon("down", theme.P["muted"], 16))
            self.compact_btn.setIcon(line_icon("compact", theme.P["muted"], 16))
            self.pause_btn.style().unpolish(self.pause_btn)
            self.pause_btn.style().polish(self.pause_btn)
        if paused:
            since = sched.paused_since or now
            self.pause_btn.setText(f"  Pause beenden  ·  {fmt_elapsed((now - since).total_seconds())}")
        else:
            self.pause_btn.setText("  Pause starten")

        banner = None
        if paused:
            since = sched.paused_since or now
            if sched.pause_open:
                banner = ("pause", f"Pause seit {since:%H:%M} Uhr – alle Erinnerungen ruhen, bis du "
                                   f"„Pause beenden“ drückst. Die Pause wird im Kalender eingetragen.")
            else:
                banner = ("pause", f"Pause seit {since:%H:%M} Uhr – alle Erinnerungen ruhen bis "
                                   f"{fmt_due(sched.paused_until, now)} Uhr. Die Pause wird im Kalender "
                                   f"eingetragen.")
        elif not schedule.is_active_now(sched.settings, now):
            nxt = sched.next_overall()
            when = f"{fmt_due(nxt[1], now)} Uhr" if nxt else "–"
            banner = ("moon", f"Gerade außerhalb deiner aktiven Zeiten. Nächste Erinnerung: {when}.")
        elif away:
            banner = ("moon", "Du scheinst nicht am PC zu sein – Erinnerungen warten, bis du zurück bist.")
        if banner:
            self.banner_icon.name = banner[0]
            self.banner_icon.update()
            self.banner_text.setText(banner[1])
            self.banner_wrap.show()
        else:
            self.banner_wrap.hide()

        for t in sched.timers:
            card = self.cards.get(t.id)
            if card:
                card.update_status(sched.rt.get(t.id), now, paused, away)


class MainWindow(QMainWindow):
    closed_to_tray = Signal()
    screen_changed = Signal(str, bool)

    def __init__(self, timers_page: TimersPage, calendar_page, settings_page):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1060, 720)
        self.setMinimumSize(880, 600)
        self._quitting = False

        central = QWidget()
        self.setCentralWidget(central)
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 20, 14, 16)
        sv.setSpacing(4)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(QSize(34, 34)))
        brand.addWidget(logo)
        bt = QVBoxLayout()
        bt.setSpacing(0)
        bt.addWidget(label(APP_NAME, "brand"))
        bt.addWidget(label("Erinnerungen am Arbeitsplatz", "brandSub"))
        brand.addLayout(bt, 1)
        sv.addLayout(brand)
        sv.addSpacing(22)

        self.stack = QStackedWidget()
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self._nav_icons = ["clock", "calendar", "sliders"]
        for i, (txt, page) in enumerate((("Erinnerungen", timers_page),
                                         ("Kalender", calendar_page),
                                         ("Einstellungen", settings_page))):
            b = QPushButton("  " + txt)
            b.setObjectName("navButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIconSize(QSize(18, 18))
            self.nav.addButton(b, i)
            sv.addWidget(b)
            self.stack.addWidget(page)
        self.nav.button(0).setChecked(True)
        self.nav.idClicked.connect(self.show_page)
        self.refresh_icons()
        sv.addStretch(1)

        pill = QFrame()
        pill.setObjectName("statusPill")
        pl = QVBoxLayout(pill)
        pl.setContentsMargins(12, 10, 12, 10)
        pl.setSpacing(2)
        pl.addWidget(label("NÄCHSTE ERINNERUNG", "statusTitle"))
        nrow = QHBoxLayout()
        nrow.setSpacing(10)
        self.next_icon = IconBubble("⭐", theme.P["accent"], 30)
        self.next_icon.hide()
        nrow.addWidget(self.next_icon, 0, Qt.AlignTop)
        ncol = QVBoxLayout()
        ncol.setSpacing(1)
        self.next_name = label("–", "statusText", wrap=True)
        self.next_time = label("", "faint", wrap=True)
        ncol.addWidget(self.next_name)
        ncol.addWidget(self.next_time)
        nrow.addLayout(ncol, 1)
        pl.addLayout(nrow)
        sv.addWidget(pill)
        sv.addSpacing(8)
        ver = label(f"Version {APP_VERSION}", "faint")
        ver.setAlignment(Qt.AlignCenter)
        ver.setToolTip(f"{APP_NAME} {APP_VERSION}")
        sv.addWidget(ver)

        h.addWidget(side)
        h.addWidget(self.stack, 1)

    def refresh_icons(self):
        for i, name in enumerate(self._nav_icons):
            b = self.nav.button(i)
            b.setIcon(line_icon(name, theme.P["accent"] if b.isChecked() else theme.P["muted"], 18))

    def show_page(self, idx: int):
        self.stack.setCurrentIndex(idx)
        btn = self.nav.button(idx)
        if btn:
            btn.setChecked(True)
        self.refresh_icons()
        page = self.stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    def set_next(self, text: str, when: str, icon: str = "", color: str = ""):
        self.next_name.setText(text)
        self.next_time.setText(when)
        if icon:
            self.next_icon.set(icon, color or theme.P["accent"])
        self.next_icon.setVisible(bool(icon))

    def closeEvent(self, e):
        if self._quitting:
            e.accept()
            return
        # Nicht direkt schließen – die App fragt nach (Beenden / Kompaktmodus / Abbrechen)
        e.ignore()
        self.closed_to_tray.emit()

    def _check_screen(self):
        if not self.screen():
            return
        name = self.screen().name()
        prev = getattr(self, "_last_screen", None)
        if name != prev:
            self._last_screen = name
            # moved=True nur, wenn das Fenster wirklich auf einen anderen Bildschirm gezogen wurde
            self.screen_changed.emit(name, prev is not None)

    def moveEvent(self, e):
        super().moveEvent(e)
        if self.isVisible():
            self._check_screen()

    def showEvent(self, e):
        super().showEvent(e)
        self._check_screen()
