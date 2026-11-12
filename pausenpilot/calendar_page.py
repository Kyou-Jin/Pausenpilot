"""Kalender-Ansicht: Monatsübersicht + Tagesdetails des Verlaufs."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen  # noqa: F401
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import theme
from .models import (MEDAL_MIN_ENTRIES, MEDAL_NAMES, MEDALS, MONTHS, WEEKDAYS, WEEKDAYS_SHORT, day_rating,
                     next_medal)
from .storage import (ACTION_DONE, ACTION_MISSED, ACTION_SKIP, ACTION_SNOOZE, AWAY_ICONS, AWAY_LABELS,
                      DaySummary, History)
from .widgets import EMOJI_FONT, IconBubble, LineIcon, MedalIcon, label, line_icon, paint_medal


def fmt_pause(sec: int, short: bool = False) -> str:
    m = max(0, int(sec)) // 60
    if m < 60:
        return f"{m}m" if short else f"{m} Min"
    return f"{m // 60}:{m % 60:02d}" + ("" if short else " h")


class MonthMedals(QWidget):
    """Zeile „Medaillen im Monat“: je Medaille Symbol + Anzahl."""
    ORDER = ["platinum", "gold", "silver", "bronze", "thumb"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.counts: dict[str, int] = {}
        self.setFixedHeight(24)
        self.setMinimumWidth(260)

    def set_counts(self, counts: dict[str, int]):
        self.counts = counts
        parts = [f"{MEDAL_NAMES[k]}: {counts[k]}" for k in self.ORDER if counts.get(k)]
        self.setToolTip("Medaillen in diesem Monat – " + (", ".join(parts) if parts else "noch keine") +
                        "\nAb 70 % Bronze · 80 % Silber · 90 % Gold · 100 % Platin · unter 50 % Daumen runter")
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font())
        f.setPointSizeF(9)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        fm = p.fontMetrics()
        x = 0.0
        shown = [k for k in self.ORDER if self.counts.get(k)]
        if not shown:
            p.setPen(theme.c("faint"))
            p.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, "Noch keine Medaillen in diesem Monat")
            p.end()
            return
        for k in shown:
            paint_medal(p, QRectF(x, 2, 20, 20), k)
            x += 22
            txt = f"{self.counts[k]}×"
            p.setPen(theme.c("danger") if k == "thumb" else theme.c("muted"))
            p.drawText(QRectF(x, 0, fm.horizontalAdvance(txt) + 2, 24), Qt.AlignLeft | Qt.AlignVCenter, txt)
            x += fm.horizontalAdvance(txt) + 12
        p.end()


class DayCell(QWidget):
    clicked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.day: date | None = None
        self.in_month = True
        self.summary = DaySummary()
        self.is_today = False
        self.selected = False
        self.hover = False
        self.setMinimumSize(64, 74)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    def set_data(self, d: date, in_month: bool, summ: DaySummary, today: bool, selected: bool,
                 pause_sec: int = 0):
        self.day, self.in_month, self.summary, self.is_today, self.selected = d, in_month, summ, today, selected
        self.pause_sec = pause_sec
        tips = []
        key, pct = day_rating(summ.done, summ.skips)
        if key:
            tips.append(f"{MEDAL_NAMES[key]} ({pct} %)")
        elif pct is not None and summ.done + summ.skips >= MEDAL_MIN_ENTRIES:
            tips.append(f"{pct} % geschafft")
        if pause_sec >= 60:
            tips.append(f"{fmt_pause(pause_sec)} Pause")
        if summ.done:
            tips.append(f"{summ.done} erledigt")
        if summ.snoozes:
            tips.append(f"{summ.snoozes}× verschoben")
        if summ.skips:
            tips.append(f"{summ.skips}× übersprungen")
        self.setToolTip(f"{d:%d.%m.%Y}: " + (", ".join(tips) if tips else "keine Einträge"))
        self.update()

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.day:
            self.clicked.emit(self.day)

    def paintEvent(self, _):
        if not self.day:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        s = self.summary
        # Hintergrund
        if self.selected:
            p.setPen(QPen(theme.c("accent"), 1.5))
            p.setBrush(theme.c("accent", 0.14))
        elif self.hover:
            p.setPen(QPen(theme.c("border_strong"), 1))
            p.setBrush(theme.c("surface2"))
        else:
            p.setPen(QPen(theme.c("border"), 1))
            p.setBrush(theme.c("surface") if self.in_month else theme.c("bg"))
        p.drawRoundedRect(r, 10, 10)
        if self.is_today and not self.selected:
            p.setPen(QPen(theme.c("accent"), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 10, 10)

        # Tageszahl (Hauptelement)
        f = QFont(self.font())
        f.setPointSizeF(11)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(theme.c("text") if self.in_month else theme.c("faint"))
        if self.is_today:
            p.setPen(theme.c("accent"))
        p.drawText(r.adjusted(10, 7, -6, -6), Qt.AlignLeft | Qt.AlignTop, str(self.day.day))
        if not self.in_month:
            p.setOpacity(0.5)

        # Medaille oben rechts
        key, pct = day_rating(s.done, s.skips)
        if key:
            ms = 19.0
            paint_medal(p, QRectF(r.right() - ms - 4, r.top() + 5, ms, ms), key)

        # Markierungen unten: ✓ erledigt + Pause (untere Zeile) · verschoben / übersprungen (darüber)
        h = 17.0
        f3 = QFont(self.font())
        f3.setPointSizeF(7.8)
        f3.setWeight(QFont.DemiBold)
        p.setFont(f3)
        fm = p.fontMetrics()
        dark = theme.P.get("is_dark")
        psec = getattr(self, "pause_sec", 0)
        rows = [[(s.done, "success", "✓ ")] + ([(psec, "accent", "pause")] if psec >= 60 else []),
                [(s.snoozes, "warn", "×"), (s.skips, "danger", "✕ ")]]
        y = r.bottom() - h - 5
        for row in rows:
            items = [(n, k, pre) for n, k, pre in row if n]
            if not items:
                continue
            x = r.left() + 6
            for n, key, pre in items:
                if pre == "pause":
                    txt = fmt_pause(n, short=True)
                    w = fm.horizontalAdvance(txt) + 22
                    if x + w > r.right() - 3:
                        txt, w = "", 18.0
                    if x + w > r.right() - 3:
                        break
                    pill = QRectF(x, y, w, h)
                    p.setPen(Qt.NoPen)
                    p.setBrush(theme.c("accent", 0.18 if dark else 0.12))
                    p.drawRoundedRect(pill, h / 2, h / 2)
                    p.setBrush(theme.c("accent"))
                    bx, by = pill.left() + (6.5 if txt else 5.6), pill.top() + 5
                    p.drawRoundedRect(QRectF(bx, by, 2.2, 7), 1, 1)
                    p.drawRoundedRect(QRectF(bx + 4, by, 2.2, 7), 1, 1)
                    if txt:
                        p.setPen(theme.c("accent"))
                        p.drawText(pill.adjusted(14, 0, -4, 0), Qt.AlignCenter, txt)
                    x += w + 3
                    continue
                txt = f"{n}{pre}" if pre == "×" else f"{pre}{n}"
                w = fm.horizontalAdvance(txt) + 10
                if x + w > r.right() - 3:      # zu schmal → ohne Symbol
                    txt = str(n)
                    w = fm.horizontalAdvance(txt) + 10
                pill = QRectF(x, y, w, h)
                p.setPen(Qt.NoPen)
                p.setBrush(theme.c(key, 0.16 if dark else 0.12))
                p.drawRoundedRect(pill, h / 2, h / 2)
                p.setPen(theme.c(key))
                p.drawText(pill, Qt.AlignCenter, txt)
                x += w + 3
            y -= h + 3
        p.end()


class CalendarPage(QWidget):
    def __init__(self, history: History, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.history = history
        today = date.today()
        self.year, self.month = today.year, today.month
        self.selected = today

        root = QHBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(22)

        # ---- linke Seite: Monat
        left = QVBoxLayout()
        left.setSpacing(0)
        head = QHBoxLayout()
        tv = QVBoxLayout()
        tv.setSpacing(2)
        tv.addWidget(label("Kalender", "h1"))
        tv.addWidget(label("Was du wann erledigt, verschoben, übersprungen – und pausiert hast.", "muted"))
        head.addLayout(tv, 1)
        left.addLayout(head)
        left.addSpacing(20)

        nav = QHBoxLayout()
        mv = QVBoxLayout()
        mv.setSpacing(1)
        self.month_label = label("", "h2")
        self.month_stats = label("", "faint")
        mv.addWidget(self.month_label)
        mv.addWidget(self.month_stats)
        self.month_medals = MonthMedals()
        mv.addWidget(self.month_medals)
        nav.addLayout(mv)
        nav.addStretch(1)
        prev = QPushButton()
        prev.setIcon(line_icon("left", theme.P["text"], 16))
        prev.setToolTip("Vorheriger Monat")
        prev.setFixedSize(36, 34)
        prev.clicked.connect(lambda: self._shift(-1))
        nxt = QPushButton()
        nxt.setIcon(line_icon("right", theme.P["text"], 16))
        nxt.setToolTip("Nächster Monat")
        nxt.setFixedSize(36, 34)
        self._arrows = (prev, nxt)
        nxt.clicked.connect(lambda: self._shift(1))
        today_btn = QPushButton("Heute")
        today_btn.clicked.connect(self.go_today)
        nav.addWidget(prev)
        nav.addWidget(nxt)
        nav.addSpacing(6)
        nav.addWidget(today_btn)
        left.addLayout(nav)
        left.addSpacing(12)

        grid = QGridLayout()
        grid.setSpacing(6)
        for i, wd in enumerate(WEEKDAYS_SHORT):
            lb = label(wd, "faint")
            lb.setAlignment(Qt.AlignCenter)
            grid.addWidget(lb, 0, i)
        self.cells: list[DayCell] = []
        for row in range(6):
            for col in range(7):
                c = DayCell()
                c.clicked.connect(self.select_day)
                grid.addWidget(c, row + 1, col)
                self.cells.append(c)
        for row in range(1, 7):
            grid.setRowStretch(row, 1)
        left.addLayout(grid, 1)
        left.addSpacing(12)

        legend = QHBoxLayout()
        legend.setSpacing(16)
        for txt, key in (("✓ erledigt", "success"), ("2× verschoben", "warn"), ("✕ übersprungen", "danger"),
                         ("❚❚ Pause", "accent")):
            lb = QLabel(txt)
            lb.setStyleSheet(f"color: {theme.P[key]}; font-size: 9pt;")
            lb.setProperty("legendKey", key)
            legend.addWidget(lb)
        self.legend_labels = [legend.itemAt(i).widget() for i in range(legend.count())]
        legend.addStretch(1)
        left.addLayout(legend)
        root.addLayout(left, 3)

        # ---- rechte Seite: Tagesdetails
        self.detail = QFrame()
        self.detail.setObjectName("card")
        self.detail.setMinimumWidth(360)
        self.detail.setMaximumWidth(400)
        dv = QVBoxLayout(self.detail)
        dv.setContentsMargins(20, 20, 20, 16)
        dv.setSpacing(0)
        self.d_weekday = label("", "faint")
        self.d_date = label("", "h2")
        dv.addWidget(self.d_weekday)
        dv.addWidget(self.d_date)
        dv.addSpacing(10)
        mrow = QHBoxLayout()
        mrow.setSpacing(8)
        self.d_medal = MedalIcon(26)
        mrow.addWidget(self.d_medal)
        self.d_medal_text = QLabel()
        self.d_medal_text.setTextFormat(Qt.RichText)
        self.d_medal_text.setObjectName("muted")
        self.d_medal_text.setWordWrap(True)
        mrow.addWidget(self.d_medal_text, 1)
        dv.addLayout(mrow)
        dv.addSpacing(12)
        stats = QHBoxLayout()
        stats.setSpacing(8)
        self.s_done = self._stat_chip("success")
        self.s_snooze = self._stat_chip("warn")
        self.s_skip = self._stat_chip("danger")
        for w in (self.s_done, self.s_snooze, self.s_skip):
            stats.addWidget(w[0], 1)
        dv.addLayout(stats)
        self.d_pause = QLabel()
        self.d_pause.setObjectName("dayDetailItem")
        self.d_pause.setTextFormat(Qt.RichText)
        self.d_pause.setContentsMargins(10, 8, 10, 8)
        dv.addSpacing(8)
        dv.addWidget(self.d_pause)
        dv.addSpacing(14)
        self.list_area = QScrollArea()
        self.list_area.setWidgetResizable(True)
        self.list_area.setFrameShape(QFrame.NoFrame)
        self.list_area.setStyleSheet("background: transparent;")
        self.list_body = QWidget()
        self.list_body.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.list_body)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(6)
        self.list_area.setWidget(self.list_body)
        dv.addWidget(self.list_area, 1)
        root.addWidget(self.detail, 2)

        self.refresh()

    def _stat_chip(self, key: str):
        f = QFrame()
        f.setObjectName("statTile")
        v = QVBoxLayout(f)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(0)
        val = QLabel("0")
        val.setObjectName("statValue")
        val.setProperty("colorKey", key)
        cap = label("", "statLabel")
        v.addWidget(val)
        v.addWidget(cap)
        return f, val, cap

    def apply_theme(self):
        for lb in self.legend_labels:
            key = lb.property("legendKey")
            if key:
                lb.setStyleSheet(f"color: {theme.P[key]}; font-size: 9pt;")
        self._arrows[0].setIcon(line_icon("left", theme.P["text"], 16))
        self._arrows[1].setIcon(line_icon("right", theme.P["text"], 16))
        self.refresh()

    # ------------------------------------------------------------------ Logik
    def _shift(self, delta: int):
        m = self.month + delta
        y = self.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        self.year, self.month = y, m
        self.refresh()

    def go_today(self):
        t = date.today()
        self.year, self.month = t.year, t.month
        self.selected = t
        self.refresh()

    def select_day(self, d: date):
        self.selected = d
        if (d.year, d.month) != (self.year, self.month):
            self.year, self.month = d.year, d.month
        self.refresh()

    def refresh(self):
        today = date.today()
        self.month_label.setText(f"{MONTHS[self.month - 1]} {self.year}")
        first = date(self.year, self.month, 1)
        start = first - timedelta(days=first.weekday())
        end = start + timedelta(days=41)
        summ = self.history.range_summary(start, end)
        pauses = self.history.range_pause_seconds(start, end)
        for i, cell in enumerate(self.cells):
            d = start + timedelta(days=i)
            cell.set_data(d, d.month == self.month, summ.get(d, DaySummary()), d == today, d == self.selected,
                          pauses.get(d, 0))
        # Monatsstatistik
        last = date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])
        mdone = sum(s.done for d, s in summ.items() if first <= d <= last)
        msn = sum(s.snoozes for d, s in summ.items() if first <= d <= last)
        msk = sum(s.skips for d, s in summ.items() if first <= d <= last)
        counts: dict[str, int] = {}
        for d, s in summ.items():
            if first <= d <= last:
                k, _ = day_rating(s.done, s.skips)
                if k:
                    counts[k] = counts.get(k, 0) + 1
        self.month_medals.set_counts(counts)
        mp = sum(s for d, s in pauses.items() if first <= d <= last)
        self.month_stats.setText(f"Monat: {mdone} erledigt · {msn}× verschoben · {msk}× übersprungen")
        self.legend_labels[-1].setText(f"❚❚ Pause · {fmt_pause(mp)} im Monat" if mp >= 60 else "❚❚ Pause")
        self._refresh_detail()

    def _refresh_detail(self):
        d = self.selected
        today = date.today()
        prefix = "HEUTE · " if d == today else ("GESTERN · " if d == today - timedelta(days=1) else "")
        self.d_weekday.setText(prefix + WEEKDAYS[d.weekday()].upper())
        self.d_date.setText(f"{d.day}. {MONTHS[d.month - 1]} {d.year}")
        entries = self.history.day_entries(d)
        done = sum(1 for e in entries if e.action == ACTION_DONE)
        sn = sum(1 for e in entries if e.action == ACTION_SNOOZE)
        sk = sum(1 for e in entries if e.action == ACTION_SKIP)
        for (frame, val, cap), n, txt, key in ((self.s_done, done, "erledigt", "success"),
                                                (self.s_snooze, sn, "verschoben", "warn"),
                                                (self.s_skip, sk, "übersprungen", "danger")):
            val.setText(str(n))
            val.setStyleSheet(f"color: {theme.P[key] if n else theme.P['faint']};")
            cap.setText(txt)
        key, pct = day_rating(done, sk)
        self.d_medal.set(key)
        P = theme.P
        total = done + sk
        if total < MEDAL_MIN_ENTRIES:
            mt = (f'<span style="color:{P["faint"]}">Keine Wertung – erst ab {MEDAL_MIN_ENTRIES} fälligen '
                  f'Erinnerungen</span>' if d <= today else "")
        else:
            name = MEDAL_NAMES.get(key, "") if key != "thumb" else ""
            col = P["danger"] if key == "thumb" else P["text"]
            head = f'<b style="color:{col}">{name + " · " if name else ""}{pct} % geschafft</b>'
            mt = f'{head}<br><span style="color:{P["faint"]}">{done} von {total} erledigt'
            nxt = next_medal(done, sk) if d == today else None
            if nxt and nxt[1]:
                mt += f' · noch {nxt[1]} bis {MEDAL_NAMES[nxt[0]]}'
            mt += "</span>"
        self.d_medal_text.setText(mt)
        self.d_medal_text.setVisible(bool(mt))
        pauses = self.history.day_pauses(d)
        psec = sum(int((b - a).total_seconds()) for a, b in pauses)
        self.d_pause.setVisible(psec >= 60)
        n = len(pauses)
        self.d_pause.setText(f'<span style="color:{theme.P["accent"]}; font-weight:600">❚❚ {fmt_pause(psec)} '
                             f'Pause</span><span style="color:{theme.P["muted"]}"> · '
                             f'{n} {"Pause" if n == 1 else "Pausen"} an diesem Tag</span>')

        while self.list_layout.count():
            it = self.list_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        aways = self.history.day_aways(d)
        items = [(e.ts, e) for e in entries] + [(a, (a, b)) for a, b in pauses] \
            + [(a, (a, b, r)) for a, b, r in aways]
        items.sort(key=lambda x: x[0], reverse=True)
        if not items:
            empty = label("Für diesen Tag gibt es keine Einträge." if d <= today
                          else "Dieser Tag liegt noch in der Zukunft.", "muted", wrap=True)
            empty.setAlignment(Qt.AlignCenter)
            self.list_layout.addSpacing(30)
            self.list_layout.addWidget(empty)
        else:
            for _, it in items:
                self.list_layout.addWidget(self._pause_widget(*it) if isinstance(it, tuple)
                                           else self._entry_widget(it))
        self.list_layout.addStretch(1)

    def _pause_widget(self, start, end, reason: str = "") -> QWidget:
        """Pause – oder mit reason eine Abwesenheit (gesperrt / nicht am PC / Standby)."""
        f = QFrame()
        f.setObjectName("dayDetailItem")
        h = QHBoxLayout(f)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(10)
        bub = QFrame()
        bub.setFixedSize(30, 30)
        ckey = "muted" if reason else "accent"
        c = theme.c(ckey, 0.2 if theme.P.get("is_dark") else 0.14)
        bub.setStyleSheet(f"background: rgba({c.red()},{c.green()},{c.blue()},{c.alpha()}); border-radius: 15px;")
        bl = QHBoxLayout(bub)
        bl.setContentsMargins(0, 0, 0, 0)
        if reason:
            ic = QLabel(AWAY_ICONS.get(reason, ""))
            ic.setAlignment(Qt.AlignCenter)
            bl.addWidget(ic, 0, Qt.AlignCenter)
        else:
            bl.addWidget(LineIcon("pause", "accent", 16), 0, Qt.AlignCenter)
        h.addWidget(bub)
        v = QVBoxLayout()
        v.setSpacing(0)
        v.addWidget(label(AWAY_LABELS.get(reason, "Pause") if reason else "Pause", "h3"))
        sub = QLabel()
        sub.setObjectName("faint")
        sub.setTextFormat(Qt.RichText)
        dur = fmt_pause(int((end - start).total_seconds()))
        if reason:
            sub.setWordWrap(True)
            sub.setText(f'<span style="color:{theme.P["muted"]}; font-weight:600">{dur}</span>'
                        f' · {start:%H:%M} – {end:%H:%M} Uhr')
        else:
            sub.setText(f'<span style="color:{theme.P["accent"]}; font-weight:600">❚❚ {dur}</span>'
                        f' · {start:%H:%M} – {end:%H:%M} Uhr')
        v.addWidget(sub)
        h.addLayout(v, 1)
        t = label(start.strftime("%H:%M"), "h3")
        t.setAlignment(Qt.AlignRight | Qt.AlignTop)
        t.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        h.addWidget(t, 0, Qt.AlignTop)
        return f

    def _entry_widget(self, e) -> QWidget:
        f = QFrame()
        f.setObjectName("dayDetailItem")
        h = QHBoxLayout(f)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(10)
        h.addWidget(IconBubble(e.icon or "⭐", e.color or theme.P["accent"], 30))
        v = QVBoxLayout()
        v.setSpacing(0)
        name = label(e.name, "h3", wrap=True)
        v.addWidget(name)
        key = {ACTION_DONE: "success", ACTION_SNOOZE: "warn", ACTION_SKIP: "danger"}.get(e.action, "faint")
        via = AWAY_LABELS.get(e.via, "")
        if e.action == ACTION_MISSED:
            status, extra = "– ausgelassen", [via or "abwesend"]
        elif e.action == ACTION_DONE and via:
            status, extra = "✓ erledigt", [f"{AWAY_ICONS.get(e.via, '')} {via}"]
        elif e.action == ACTION_DONE:
            status, extra = "✓ erledigt", []
            if e.snoozes:
                extra.append(f"{e.snoozes}× verschoben")
            if e.planned and abs((e.ts - e.planned).total_seconds()) >= 60:
                extra.append(f"geplant {e.planned:%H:%M}")
        elif e.action == ACTION_SNOOZE:
            status, extra = "» verschoben", [f"um {e.minutes} Min"]
        else:
            status, extra = "✕ übersprungen", [f"{e.snoozes}× verschoben"] if e.snoozes else []
        sub = QLabel()
        sub.setWordWrap(True)
        sub.setObjectName("faint")
        sub.setTextFormat(Qt.RichText)
        rest = "".join(f" · {x}" for x in extra)
        sub.setText(f'<span style="color:{theme.P[key]}; font-weight:600">{status}</span>{rest}')
        v.addWidget(sub)
        h.addLayout(v, 1)
        t = label(e.ts.strftime("%H:%M"), "h3")
        t.setAlignment(Qt.AlignRight | Qt.AlignTop)
        t.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        h.addWidget(t, 0, Qt.AlignTop)
        return f
