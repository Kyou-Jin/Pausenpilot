"""Erinnerungs-Fenster: erscheint mittig auf dem Bildschirm des Tools (kein Vollbild).

Ablauf: Hinweis → (Starten) → Countdown → Geschafft.
Daneben: Später (+5/+10/+15 Min, wird gezählt) und Überspringen.
"""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QPushButton, QVBoxLayout,
                               QWidget)

from . import sounds, theme, winutil
from .models import TimerConfig, fmt_duration
from .widgets import IconBubble, ProgressRing, label, paint_line_icon

SHADOW_MARGIN = 32
CARD_WIDTH = 440
PAD_X = 28
INNER_WIDTH = CARD_WIDTH - 2 * PAD_X

PAGE_PROMPT, PAGE_RUN, PAGE_DONE = 0, 1, 2
COMPACT_CARD = 340
COMPACT_PAD = 14
COMPACT_INNER = COMPACT_CARD - 2 * COMPACT_PAD


def fmt_clock(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


EYE_TIPS = [
    "Schau auf etwas, das mindestens 6 Meter entfernt ist.",
    "Blinzle ein paar Mal bewusst – das befeuchtet die Augen.",
    "Lass den Blick langsam am Horizont entlangwandern.",
]
MOVE_TIPS = [
    "Schultern kreisen lassen – fünfmal vor, fünfmal zurück.",
    "Steh auf und streck die Arme weit über den Kopf.",
    "Ein paar Schritte gehen, am besten zum Fenster.",
    "Nacken locker: Kopf langsam zur einen, dann zur anderen Seite neigen.",
    "Tief durch die Nase ein- und langsam durch den Mund ausatmen.",
]


def tips_for(icon: str) -> list[str]:
    if icon == "👁":
        return EYE_TIPS
    if icon in ("☕", "🧍", "🤸", "🚶", "🧘", "🫁"):
        return MOVE_TIPS
    return []


def waiting_text(n: int) -> str:
    return "1 weitere wartet" if n == 1 else f"{n} weitere warten"


class CheckBubble(QWidget):
    """Grüner Kreis mit Haken (Erfolg)."""

    def __init__(self, size: int, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(theme.c("success", 0.18))
        p.drawEllipse(r)
        inner = r.adjusted(r.width() * .16, r.height() * .16, -r.width() * .16, -r.height() * .16)
        p.setBrush(theme.c("success"))
        p.drawEllipse(inner)
        s = inner.width() * .62
        paint_line_icon(p, "check", QRectF(inner.center().x() - s / 2, inner.center().y() - s / 2, s, s),
                        QColor("#FFFFFF"), max(2.5, self.width() / 18))
        p.end()


class AlarmWindow(QWidget):
    started = Signal(str)
    completed = Signal(str)
    snoozed = Signal(str, int)
    skipped = Signal(str)
    run_cancelled = Signal(str)
    moved = Signal(QPoint, bool)   # neue Position (Kartenmitte bzw. -ecke im Kompaktformat), kompakt?

    def __init__(self, sound_cfg):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("Pausenpilot – Erinnerung")
        self._sound_cfg = sound_cfg       # callable → (enabled, volume)
        self.timer: TimerConfig | None = None
        self._end = 0.0
        self._last_whole = None
        self._drag: QPoint | None = None
        self._closing = False
        self._page = PAGE_PROMPT
        self._time_up = False
        self._dragged = False
        self.compact = False
        self._anchor = None
        self.quiet = False                # Telefonat läuft → kein Ton, nicht in den Vordergrund

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW_MARGIN, SHADOW_MARGIN - 8, SHADOW_MARGIN, SHADOW_MARGIN + 8)
        self.card = QFrame()
        self.card.setObjectName("alarmCard")
        self.card.setFixedWidth(CARD_WIDTH)
        self.shadow = QGraphicsDropShadowEffect(self.card)
        self.shadow.setBlurRadius(48)
        self.shadow.setOffset(0, 12)
        self.shadow.setColor(QColor(0, 0, 0, 110))
        self.card.setGraphicsEffect(self.shadow)
        outer.addWidget(self.card)

        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(PAD_X, 26, PAD_X, 22)
        cl.setSpacing(0)
        self.pages = [self._build_prompt(), self._build_running(), self._build_done()]
        for pg in self.pages:
            pg.setFixedWidth(INNER_WIDTH)
            cl.addWidget(pg)
        # Kompaktformat (erscheint an der Stelle des Kompaktfensters)
        self.cpages = [self._build_c_prompt(), self._build_c_running(), self._build_c_done()]
        for pg in self.cpages:
            pg.setFixedWidth(COMPACT_INNER)
            cl.addWidget(pg)

        self._tick = QTimer(self)
        self._tick.setInterval(50)
        self._tick.timeout.connect(self._on_tick)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(220)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.finished.connect(self._fade_finished)

        self._done_timer = QTimer(self)
        self._done_timer.setSingleShot(True)
        self._done_timer.timeout.connect(self._fade_out)
        self._set_page(PAGE_PROMPT)

    # ------------------------------------------------------------------ Aufbau
    def _build_prompt(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        top = QHBoxLayout()
        top.setSpacing(16)
        self.p_icon = IconBubble("⭐", theme.P["accent"], 60)
        top.addWidget(self.p_icon, 0, Qt.AlignTop)
        tv = QVBoxLayout()
        tv.setSpacing(3)
        tv.addStretch(1)
        self.p_kicker = label("ZEIT FÜR", "sectionTitle")
        tv.addWidget(self.p_kicker)
        self.p_title = label("", "alarmTitle", wrap=True)
        tv.addWidget(self.p_title)
        tv.addStretch(1)
        top.addLayout(tv, 1)
        v.addLayout(top)
        v.addSpacing(14)

        self.p_desc = label("", "alarmDesc", wrap=True)
        v.addWidget(self.p_desc)
        v.addSpacing(10)
        self.p_meta = label("", "alarmMeta")
        v.addWidget(self.p_meta)
        self.p_badges = QWidget()
        bl = QHBoxLayout(self.p_badges)
        bl.setContentsMargins(0, 12, 0, 0)
        bl.setSpacing(8)
        self.p_snoozes = label("", "snoozeBadge")
        self.p_snoozes.setToolTip("So oft wurde diese Erinnerung schon verschoben – wird im Kalender markiert")
        self.p_queue = label("", "queueBadge")
        bl.addWidget(self.p_snoozes)
        bl.addWidget(self.p_queue)
        bl.addStretch(1)
        v.addWidget(self.p_badges)
        v.addSpacing(20)

        self.p_start = QPushButton("Starten")
        self.p_start.setObjectName("bigPrimary")
        self.p_start.setCursor(Qt.PointingHandCursor)
        self.p_start.clicked.connect(self._on_start)
        self.p_done = QPushButton("Erledigt ✓")
        self.p_done.setObjectName("bigDone")
        self.p_done.setCursor(Qt.PointingHandCursor)
        self.p_done.setToolTip("Schon gemacht – ohne Countdown direkt als erledigt eintragen")
        self.p_done.clicked.connect(self._on_done_direct)
        srow = QHBoxLayout()
        srow.setSpacing(8)
        srow.addWidget(self.p_start, 1)
        srow.addWidget(self.p_done)
        v.addLayout(srow)
        v.addSpacing(18)

        v.addWidget(label("Später erinnern", "alarmMeta"))
        v.addSpacing(7)
        row = QHBoxLayout()
        row.setSpacing(8)
        for mins in (5, 10, 15):
            b = QPushButton(f"+{mins} Min")
            b.setObjectName("snooze")
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"In {mins} Minuten erneut erinnern – wird gezählt und im Kalender markiert")
            b.clicked.connect(lambda _=False, m=mins: self._on_snooze(m))
            row.addWidget(b)
        v.addLayout(row)
        v.addSpacing(12)

        self.p_skip = QPushButton("Diesmal überspringen")
        self.p_skip.setObjectName("link")
        self.p_skip.setCursor(Qt.PointingHandCursor)
        self.p_skip.setToolTip("Wird im Kalender als übersprungen eingetragen")
        self.p_skip.clicked.connect(self._on_skip)
        v.addWidget(self.p_skip, 0, Qt.AlignHCenter)
        return w

    def _build_running(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.r_icon = IconBubble("⭐", theme.P["accent"], 38)
        head.addWidget(self.r_icon)
        self.r_title = label("", "h2")
        head.addWidget(self.r_title, 1)
        v.addLayout(head)
        v.addSpacing(22)
        self.r_ring = ProgressRing(216, 10)
        self.r_ring.setBig(True)
        v.addWidget(self.r_ring, 0, Qt.AlignHCenter)
        v.addSpacing(18)
        self.r_desc = label("", "alarmDesc", wrap=True)
        self.r_desc.setAlignment(Qt.AlignHCenter)
        v.addWidget(self.r_desc)
        v.addSpacing(8)
        self.r_tip = label("", "alarmMeta", wrap=True)
        self.r_tip.setAlignment(Qt.AlignHCenter)
        v.addWidget(self.r_tip)
        v.addSpacing(10)
        self.r_queue = label("", "queueBadge")
        self.r_queue.hide()
        v.addWidget(self.r_queue, 0, Qt.AlignHCenter)
        v.addSpacing(18)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.r_cancel = QPushButton("Abbrechen")
        self.r_cancel.setObjectName("ghost")
        self.r_cancel.setCursor(Qt.PointingHandCursor)
        self.r_cancel.setToolTip("Zurück zur Erinnerung – es wird nichts eingetragen")
        self.r_cancel.clicked.connect(self._on_cancel_run)
        self.r_finish = QPushButton("Fertig – eintragen")
        self.r_finish.setCursor(Qt.PointingHandCursor)
        self.r_finish.setToolTip("Früher beenden und als erledigt eintragen")
        self.r_finish.clicked.connect(self._on_finish_early)
        row.addStretch(1)
        row.addWidget(self.r_cancel)
        row.addWidget(self.r_finish)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def _build_done(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 22, 0, 18)
        v.setSpacing(0)
        self.d_icon = CheckBubble(76)
        v.addWidget(self.d_icon, 0, Qt.AlignHCenter)
        v.addSpacing(18)
        self.d_title = label("Geschafft!", "alarmTitle")
        self.d_title.setAlignment(Qt.AlignHCenter)
        v.addWidget(self.d_title)
        v.addSpacing(6)
        self.d_sub = label("", "alarmDesc", wrap=True)
        self.d_sub.setAlignment(Qt.AlignHCenter)
        v.addWidget(self.d_sub)
        return w

    def _build_c_prompt(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(11)
        self.c_icon = IconBubble("⭐", theme.P["accent"], 38)
        top.addWidget(self.c_icon)
        tv = QVBoxLayout()
        tv.setSpacing(1)
        self.c_title = label("", "compactTitle")
        self.c_meta = label("", "compactSub")
        tv.addWidget(self.c_title)
        tv.addWidget(self.c_meta)
        top.addLayout(tv, 1)
        v.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.c_start = QPushButton("Starten")
        self.c_start.setObjectName("compactPrimary")
        self.c_start.setCursor(Qt.PointingHandCursor)
        self.c_start.clicked.connect(self._on_start)
        row.addWidget(self.c_start, 1)
        self.c_done = QPushButton("Erledigt")
        self.c_done.setObjectName("compactDone")
        self.c_done.setCursor(Qt.PointingHandCursor)
        self.c_done.setToolTip("Schon gemacht – ohne Countdown direkt als erledigt eintragen")
        self.c_done.clicked.connect(self._on_done_direct)
        row.addWidget(self.c_done)
        for mins in (5, 10):
            b = QPushButton(f"+{mins}")
            b.setObjectName("compactBtn")
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"In {mins} Minuten erneut erinnern – wird gezählt und im Kalender markiert")
            b.clicked.connect(lambda _=False, m=mins: self._on_snooze(m))
            row.addWidget(b)
        sk = QPushButton("✕")
        sk.setObjectName("compactBtn")
        sk.setCursor(Qt.PointingHandCursor)
        sk.setToolTip("Diesmal überspringen – wird im Kalender als übersprungen eingetragen")
        sk.clicked.connect(self._on_skip)
        row.addWidget(sk)
        v.addLayout(row)
        return w

    def _build_c_running(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(12)
        self.c_ring = ProgressRing(56, 5)
        top.addWidget(self.c_ring)
        tv = QVBoxLayout()
        tv.setSpacing(1)
        self.c_r_title = label("", "compactTitle")
        self.c_r_tip = label("", "compactSub", wrap=True)
        tv.addWidget(self.c_r_title)
        tv.addWidget(self.c_r_tip)
        self.c_r_queue = label("", "compactSub")
        self.c_r_queue.hide()
        tv.addWidget(self.c_r_queue)
        top.addLayout(tv, 1)
        v.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addStretch(1)
        cancel = QPushButton("Abbrechen")
        cancel.setObjectName("compactBtn")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setToolTip("Zurück zur Erinnerung – es wird nichts eingetragen")
        cancel.clicked.connect(self._on_cancel_run)
        self.c_cancel = cancel
        fin = QPushButton("Fertig – eintragen")
        self.c_finish = fin
        fin.setObjectName("compactPrimary")
        fin.setCursor(Qt.PointingHandCursor)
        fin.setToolTip("Früher beenden und als erledigt eintragen")
        fin.clicked.connect(self._on_finish_early)
        row.addWidget(cancel)
        row.addWidget(fin)
        v.addLayout(row)
        return w

    def _build_c_done(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(12)
        h.addWidget(CheckBubble(40))
        tv = QVBoxLayout()
        tv.setSpacing(1)
        tv.addWidget(label("Geschafft!", "compactTitle"))
        self.c_sub = label("", "compactSub", wrap=True)
        tv.addWidget(self.c_sub)
        h.addLayout(tv, 1)
        return w

    def _set_page(self, idx: int):
        self._page = idx
        for i, pg in enumerate(self.pages):
            pg.setVisible(i == idx and not self.compact)
        for i, pg in enumerate(getattr(self, "cpages", [])):
            pg.setVisible(i == idx and self.compact)
        if self.compact:
            self.card.setFixedWidth(COMPACT_CARD)
            self.card.setObjectName("compactCard")
            self.card.layout().setContentsMargins(COMPACT_PAD, 12, COMPACT_PAD, 12)
        else:
            self.card.setFixedWidth(CARD_WIDTH)
            self.card.setObjectName("alarmCard")
            self.card.layout().setContentsMargins(PAD_X, 26, PAD_X, 22)
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)

    # ------------------------------------------------------------------ Anzeige
    def show_alarm(self, timer: TimerConfig, snoozes: int, waiting: int, planned: datetime | None,
                   screen_name: str = "", anchor: QPoint | None = None, center: QPoint | None = None):
        """anchor: globale Position der Kompaktkarte → Erinnerung im Kompaktformat an dieser Stelle."""
        self._done_timer.stop()
        self._tick.stop()
        self.timer = timer
        self.compact = anchor is not None
        self._anchor = anchor
        self._center = center
        self.c_icon.set(timer.icon, timer.color)
        self.c_title.setText(timer.name)
        self.c_title.setToolTip(timer.description)
        dur = f"Dauer {fmt_duration(timer.duration_sec)} · " if timer.duration_sec > 0 else ""
        self._c_meta_base = (f"{dur}fällig {(planned or datetime.now()):%H:%M}"
                             + (f" · {snoozes}× verschoben" if snoozes else ""))
        self.c_meta.setText(self._c_meta_base)
        has_cd = timer.duration_sec > 0
        self.c_start.setText(f"Start · {fmt_duration(timer.duration_sec)}" if has_cd else "Erledigt ✓")
        self.c_done.setVisible(has_cd)
        self.p_done.setVisible(has_cd)
        self.p_icon.set(timer.icon, timer.color)
        self.r_icon.set(timer.icon, timer.color)
        self.p_title.setText(timer.name)
        self.p_desc.setText(timer.description)
        self.p_desc.setVisible(bool(timer.description))
        when = (planned or datetime.now()).strftime("%H:%M")
        if timer.duration_sec > 0:
            self.p_meta.setText(f"Dauer {fmt_duration(timer.duration_sec)}  ·  fällig {when} Uhr")
            self.p_start.setText(f"Starten  ·  {fmt_duration(timer.duration_sec)}")
            self.p_start.setToolTip("Startet den Countdown. Erst danach gilt die Erinnerung als erledigt.")
        else:
            self.p_meta.setText(f"fällig {when} Uhr")
            self.p_start.setText("Erledigt")
            self.p_start.setToolTip("Als erledigt eintragen")
        self.p_snoozes.setText(f"{snoozes}× verschoben")
        self.p_snoozes.setVisible(snoozes > 0)
        self._snoozes_shown = snoozes > 0
        self.update_waiting(waiting)
        self.shadow.setColor(QColor(0, 0, 0, 120 if theme.P.get("is_dark") else 60))
        self._set_page(PAGE_PROMPT)
        self._present(screen_name)
        self._sound("click")

    def update_waiting(self, waiting: int, names=()):
        txt = waiting_text(waiting) if waiting > 0 else ""
        # Während des Countdowns: was kommt direkt danach?
        if names:
            first = names[0]
            more = f" (+{len(names) - 1})" if len(names) > 1 else ""
            run_txt = f"⏳ Danach wartet: {first}{more}"
        else:
            run_txt = ""
        for lb in (self.r_queue, self.c_r_queue):
            if lb.text() != run_txt or lb.isVisible() != bool(run_txt):
                lb.setText(run_txt)
                lb.setToolTip("Wurde während dieses Countdowns fällig und kommt direkt im Anschluss:\n"
                              + "\n".join(names) if names else "")
                lb.setVisible(bool(run_txt))
                if self.isVisible() and self._page == PAGE_RUN:
                    self._relayout()
        if hasattr(self, "_c_meta_base"):
            self.c_meta.setText(self._c_meta_base + (f" · {txt}" if txt else ""))
        if self.p_queue.text() == txt and self.p_queue.isVisible() == (waiting > 0):
            return
        self.p_queue.setText(txt)
        self.p_queue.setVisible(waiting > 0)
        self.p_badges.setVisible(waiting > 0 or getattr(self, "_snoozes_shown", False))
        if self.isVisible() and self._page == PAGE_PROMPT:
            self._relayout()

    def _fit(self):
        self.card.layout().activate()
        self.layout().activate()
        self.resize(self.minimumSizeHint().expandedTo(self.sizeHint()))

    def _present(self, screen_name: str):
        self._fit()
        screen = None
        for s in QGuiApplication.screens():
            if s.name() == screen_name:
                screen = s
                break
        screen = screen or QGuiApplication.primaryScreen()
        self.winId()
        if self.windowHandle() and self.windowHandle().screen() is not screen:
            self.windowHandle().setScreen(screen)
            self._fit()
        if self.compact and self._anchor is not None:
            self._move_to_anchor()
        elif getattr(self, "_center", None) is not None:
            scr = QGuiApplication.screenAt(self._center) or screen
            if self.windowHandle() and self.windowHandle().screen() is not scr:
                self.windowHandle().setScreen(scr)
                self._fit()
            g = scr.availableGeometry()
            off = self.card.geometry()
            x = self._center.x() - off.center().x()
            y = self._center.y() - off.center().y()
            x = max(g.left() - off.x(), min(x, g.right() - off.right()))
            y = max(g.top() - off.y(), min(y, g.bottom() - off.bottom()))
            self.move(x, y)
        else:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2 - geo.height() // 16
            self.move(max(geo.x(), x), max(geo.y(), y))
        self._fade.stop()
        self._closing = False
        start = 0.0 if not self.isVisible() else self.windowOpacity()
        self.setWindowOpacity(start)
        self.show()
        if start < 1.0:
            self._fade.setStartValue(start)
            self._fade.setEndValue(1.0)
            self._fade.start()
        self._apply_zorder()

    def _move_to_anchor(self):
        off = self.card.geometry().topLeft()
        pt = self._anchor - off
        scr = QGuiApplication.screenAt(self._anchor) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        x = max(g.left() - off.x(), min(pt.x(), g.right() - self.card.width() - off.x()))
        y = max(g.top() - off.y(), min(pt.y(), g.bottom() - self.card.height() - off.y()))
        self.move(x, y)

    def _relayout(self):
        if self.compact and self._anchor is not None:
            self._fit()
            self._move_to_anchor()
            return
        center = self.geometry().center()
        self._fit()
        g = self.geometry()
        g.moveCenter(center)
        self.setGeometry(g)

    def is_running(self) -> bool:
        return self.isVisible() and self._page == PAGE_RUN and self.timer is not None

    def close_silently(self):
        """Schließt ohne Signal (z. B. wenn der Timer gelöscht wurde)."""
        self._tick.stop()
        self._done_timer.stop()
        self._fade.stop()
        self._closing = False
        self.timer = None
        self.hide()
        self.setWindowOpacity(1.0)

    # ------------------------------------------------------------------ Aktionen
    def _on_start(self):
        if not self.timer:
            return
        if self.timer.duration_sec <= 0:
            self._show_done()
            return
        self.started.emit(self.timer.id)
        self.r_title.setText(self.timer.name)
        self.r_desc.setText(self.timer.description or "Genieß die Pause.")
        self.r_ring.setColor(self.timer.color)
        self.c_ring.setColor(self.timer.color)
        self.c_r_title.setText(self.timer.name)
        self._end = time.monotonic() + self.timer.duration_sec
        self._start = time.monotonic()
        self._tips = tips_for(self.timer.icon)
        self._tip_idx = -1
        self.r_tip.setText(self._tips[0] if self._tips else "")
        self.r_tip.setVisible(bool(self._tips))
        self.c_r_tip.setText(self._tips[0] if self._tips else (self.timer.description or "Genieß die Pause."))
        self._last_whole = None
        self._set_time_up(False)
        self._set_page(PAGE_RUN)
        self._relayout()
        self._on_tick()
        self._tick.start()

    def _on_tick(self):
        if not self.timer:
            self._tick.stop()
            return
        remaining = self._end - time.monotonic()
        total = max(1, self.timer.duration_sec)
        self.r_ring.setValue(max(0.0, remaining) / total)
        whole = int(remaining + 0.999) if remaining > 0 else 0
        self.r_ring.setText(fmt_clock(whole), "verbleibend")
        self.c_ring.setValue(max(0.0, remaining) / total)
        self.c_ring.setText(fmt_clock(whole))
        if self._tips:
            idx = int((time.monotonic() - self._start) // 25) % len(self._tips)
            if idx != self._tip_idx:
                self._tip_idx = idx
                self.r_tip.setText("Tipp: " + self._tips[idx])
                self.c_r_tip.setText(self._tips[idx])
        if whole != self._last_whole:
            self._last_whole = whole
            if total >= 4 and whole in (3, 2, 1):
                self._sound("tick")
        if remaining <= 0:
            self._tick.stop()
            self._sound("chime")
            self._set_time_up(True)

    def _set_time_up(self, up: bool):
        """Countdown abgelaufen: erst mit Klick auf „Erledigt“ wird eingetragen."""
        self._time_up = up
        if up:
            self.r_ring.setValue(0)
            self.r_ring.setText("00:00", "Zeit um")
            self.c_ring.setValue(0)
            self.c_ring.setText("✓")
            self.r_tip.setText("Zeit ist um – hast du es gemacht? Dann bestätige mit „Erledigt“.")
            self.r_tip.setVisible(True)
            self.c_r_tip.setText("Zeit ist um – hast du es gemacht?")
            for b in (self.r_finish, self.c_finish):
                b.setText("Erledigt ✓")
                b.setToolTip("Als erledigt in den Kalender eintragen")
            self.r_finish.setObjectName("primary")
            for b in (self.r_cancel, self.c_cancel):
                b.setText("Nicht gemacht")
                b.setToolTip("Als übersprungen eintragen")
        else:
            for b in (self.r_finish, self.c_finish):
                b.setText("Fertig – eintragen")
                b.setToolTip("Früher beenden und als erledigt eintragen")
            self.r_finish.setObjectName("")
            for b in (self.r_cancel, self.c_cancel):
                b.setText("Abbrechen")
                b.setToolTip("Zurück zur Erinnerung – es wird nichts eingetragen")
        self.r_finish.style().unpolish(self.r_finish)
        self.r_finish.style().polish(self.r_finish)
        if self.isVisible():
            self._relayout()

    def _show_done(self):
        t = self.timer
        if not t:
            return
        self.d_icon.update()
        self.d_sub.setText(f"„{t.name}“ ist im Kalender eingetragen.")
        self.c_sub.setText("Im Kalender eingetragen.")
        self._set_page(PAGE_DONE)
        self._relayout()
        self.completed.emit(t.id)
        self._done_timer.start(2200)

    def set_next_hint(self, text: str):
        if self._page == PAGE_DONE and text:
            self.d_sub.setText(self.d_sub.text() + "\n" + text)
            self.c_sub.setText("Eingetragen · " + text)
            self._relayout()

    def _sound(self, name: str):
        enabled, vol = self._sound_cfg()
        if enabled and not self.quiet:
            sounds.play(name, vol)

    def set_quiet(self, on: bool):
        """Während eines Telefonats: leise und hinter dem aktiven Fenster. Endet der Anruf,
        kommt eine offene Erinnerung wieder ganz normal nach vorn (ohne Fokus zu stehlen)."""
        if on == self.quiet:
            return
        self.quiet = on
        if self.isVisible():
            self._apply_zorder()

    def _apply_zorder(self):
        hwnd = int(self.winId())
        if self.quiet:
            winutil.place_behind_foreground(hwnd)
        else:
            winutil.set_topmost(hwnd, True)
            self.raise_()

    def _on_snooze(self, minutes: int):
        if self.timer:
            tid = self.timer.id
            self._fade_out()
            self.snoozed.emit(tid, minutes)

    def _on_skip(self):
        if self.timer:
            tid = self.timer.id
            self._fade_out()
            self.skipped.emit(tid)

    def _on_done_direct(self):
        """Ohne Countdown direkt als erledigt eintragen."""
        if self.timer:
            self._show_done()

    def _on_finish_early(self):
        self._tick.stop()
        if not self._time_up:
            self._sound("chime")
        self._time_up = False
        self._show_done()

    def _on_cancel_run(self):
        if self._time_up:            # „Nicht gemacht“ nach Ablauf → übersprungen
            self._time_up = False
            self._on_skip()
            return
        self._tick.stop()
        if self.timer:
            self._set_page(PAGE_PROMPT)
            self._relayout()
            self.run_cancelled.emit(self.timer.id)

    def _fade_out(self):
        self._tick.stop()
        self._done_timer.stop()
        self.timer = None
        self._closing = True
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _fade_finished(self):
        if self._closing:
            self._closing = False
            self.hide()
            self.setWindowOpacity(1.0)

    # ------------------------------------------------------------------ Verschieben per Maus
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragged = False

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self._dragged = True
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        if self._drag is not None and self._dragged:
            if self.compact:
                pt = self.card.mapToGlobal(QPoint(0, 0))
                self._anchor = pt
            else:
                pt = self.card.mapToGlobal(self.card.rect().center())
            self.moved.emit(pt, self.compact)
        self._drag = None
        self._dragged = False
