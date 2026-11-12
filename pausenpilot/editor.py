"""Dialog zum Anlegen / Bearbeiten eines Timers."""
from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QTime, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QTimeEdit, QToolButton, QVBoxLayout, QWidget)

from . import schedule, theme
from .models import COLORS, ICONS, Settings, TimerConfig, fmt_hm, parse_hm
from .widgets import EMOJI_FONT, IconBubble, ToggleSwitch, label, line_icon


DELETE_RESULT = 2


class SnapSpin(QSpinBox):
    """Zahlenfeld zum Eintippen; Pfeile/Mausrad/Tastatur springen auf volle Schritte (z. B. 5er)."""

    def __init__(self, lo: int, hi: int, step: int, suffix: str, parent=None):
        super().__init__(parent)
        self.setRange(lo, hi)
        self.setSingleStep(step)
        self.setSuffix(suffix)
        self.setAccelerated(True)
        self.setKeyboardTracking(True)

    def stepBy(self, n: int):
        v, s = self.value(), self.singleStep()
        nv = (v // s + n) * s if n > 0 else (-(-v // s) + n) * s
        self.setValue(max(self.minimum(), min(self.maximum(), nv)))
        self.selectAll()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        QTimer.singleShot(0, self.selectAll)   # Klick ins Feld markiert die Zahl → direkt überschreiben


class Stepper(QWidget):
    """Zahlenfeld mit kleinen ▲/▼-Knöpfen rechts daneben."""

    def __init__(self, spin: SnapSpin, tip: str = "", parent=None):
        super().__init__(parent)
        self.spin = spin
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(spin, 1)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        step = spin.singleStep()
        unit = spin.suffix().strip()
        self.buttons = []
        for name, d in (("up", 1), ("down", -1)):
            b = QToolButton()
            b.setObjectName("stepBtn")
            b.setFixedSize(26, 19)
            b.setCursor(Qt.PointingHandCursor)
            b.setAutoRepeat(True)
            b.setAutoRepeatDelay(400)
            b.setAutoRepeatInterval(90)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip(f"{'+' if d > 0 else '−'}{step} {unit}")
            b.clicked.connect(lambda _=False, d_=d: self.spin.stepBy(d_))
            col.addWidget(b)
            self.buttons.append((b, name))
        h.addLayout(col)
        if tip:
            spin.setToolTip(tip)
        self.refresh_icons()

    def refresh_icons(self):
        for b, name in self.buttons:
            b.setIcon(line_icon(name, theme.P["muted"], 14))


class Swatch(QAbstractButton):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.color = color
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(30, 30)
        self.setToolTip("Farbe wählen")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.isChecked():
            p.setPen(Qt.NoPen)
            ring = QColor(self.color)
            ring.setAlphaF(0.35)
            p.setBrush(ring)
            p.drawEllipse(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.color))
        m = 6 if self.isChecked() else 5
        p.drawEllipse(self.rect().adjusted(m, m, -m, -m))
        if self.underMouse() and not self.isChecked():
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawEllipse(self.rect().adjusted(m, m, -m, -m))
        p.end()


class EmojiButton(QAbstractButton):
    def __init__(self, emoji: str, parent=None):
        super().__init__(parent)
        self.emoji = emoji
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(36, 36)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        if self.isChecked():
            p.setPen(theme.c("accent"))
            p.setBrush(theme.c("accent", 0.18))
            p.drawRoundedRect(r, 9, 9)
        elif self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(theme.c("surface3"))
            p.drawRoundedRect(r, 9, 9)
        f = QFont(EMOJI_FONT)
        f.setPixelSize(18)
        p.setFont(f)
        p.setPen(theme.c("text"))
        p.drawText(self.rect(), Qt.AlignCenter, self.emoji)
        p.end()


class TimerEditor(QDialog):
    def __init__(self, timer: TimerConfig | None, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Erinnerung bearbeiten" if timer else "Neue Erinnerung")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._settings = settings
        self.is_new = timer is None
        self.timer = TimerConfig.from_dict(timer.to_dict()) if timer else TimerConfig(
            name="", interval_min=30, duration_sec=60, first_start="08:00")

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 22)
        root.setSpacing(0)

        # Kopf mit Vorschau
        head = QHBoxLayout()
        self.preview = IconBubble(self.timer.icon, self.timer.color, 52)
        head.addWidget(self.preview)
        head.addSpacing(14)
        ht = QVBoxLayout()
        ht.setSpacing(2)
        ht.addWidget(label("Neue Erinnerung" if self.is_new else "Erinnerung bearbeiten", "h2"))
        ht.addWidget(label("Wofür möchtest du erinnert werden?", "muted"))
        head.addLayout(ht, 1)
        root.addLayout(head)
        root.addSpacing(20)

        # Name
        root.addWidget(label("ZWECK", "sectionTitle"))
        root.addSpacing(6)
        self.name = QLineEdit(self.timer.name)
        self.name.setPlaceholderText("z. B. Augen entspannen, Wasser trinken, aufstehen …")
        self.name.setMaxLength(60)
        root.addWidget(self.name)
        root.addSpacing(12)
        root.addWidget(label("BESCHREIBUNG (OPTIONAL)", "sectionTitle"))
        root.addSpacing(6)
        self.desc = QLineEdit(self.timer.description)
        self.desc.setPlaceholderText("Optional: Was genau ist zu tun?")
        self.desc.setMaxLength(200)
        root.addWidget(self.desc)
        root.addSpacing(18)

        # Symbol + Farbe
        root.addWidget(label("SYMBOL & FARBE", "sectionTitle"))
        root.addSpacing(6)
        icons = QHBoxLayout()
        icons.setSpacing(4)
        self.icon_group = QButtonGroup(self)
        for e in ICONS:
            b = EmojiButton(e)
            b.setChecked(e == self.timer.icon)
            self.icon_group.addButton(b)
            icons.addWidget(b)
        icons.addStretch(1)
        self.icon_group.buttonClicked.connect(self._icon_changed)
        root.addLayout(icons)
        root.addSpacing(6)
        colors = QHBoxLayout()
        colors.setSpacing(4)
        self.color_group = QButtonGroup(self)
        for col in COLORS:
            s = Swatch(col)
            s.setChecked(col.lower() == self.timer.color.lower())
            self.color_group.addButton(s)
            colors.addWidget(s)
        colors.addStretch(1)
        self.color_group.buttonClicked.connect(self._color_changed)
        root.addLayout(colors)
        root.addSpacing(18)

        # Zeitplan
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        grid.addWidget(label("INTERVALL", "sectionTitle"), 0, 0)
        grid.addWidget(label("DAUER DER AKTIVITÄT", "sectionTitle"), 0, 1)
        grid.addWidget(label("ERSTER START", "sectionTitle"), 0, 2)

        self.interval = SnapSpin(1, 24 * 60, 5, " Min")
        self.interval.setValue(self.timer.interval_min)
        grid.addWidget(Stepper(self.interval, "Abstand zwischen zwei Erinnerungen in Minuten – eintippen "
                                              "oder mit den Pfeilen in 5-Minuten-Schritten"), 1, 0)

        dur = QHBoxLayout()
        dur.setSpacing(8)
        self.dur_min = SnapSpin(0, 180, 5, " Min")
        self.dur_sec = SnapSpin(0, 59, 5, " Sek")
        m, s = divmod(self.timer.duration_sec, 60)
        self.dur_min.setValue(m)
        self.dur_sec.setValue(s)
        dur.addWidget(Stepper(self.dur_min, "Minuten – eintippen oder mit den Pfeilen in 5er-Schritten"), 1)
        dur.addWidget(Stepper(self.dur_sec, "Sekunden – eintippen oder mit den Pfeilen in 5er-Schritten"), 1)
        dw = QWidget()
        dw.setLayout(dur)
        dur.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(dw, 1, 1)

        self.first = QTimeEdit(QTime.fromString(self.timer.first_start, "HH:mm"))
        self.first.setDisplayFormat("HH:mm")
        self.first.setToolTip("Uhrzeit der ersten Erinnerung am Tag – so starten nicht alle Timer gleichzeitig")
        grid.addWidget(self.first, 1, 2)

        # Schnellwahl
        chips_i = QHBoxLayout()
        chips_i.setSpacing(4)
        for mins, txt in ((20, "20 Min"), (30, "30 Min"), (60, "1 Std"), (120, "2 Std")):
            b = QPushButton(txt)
            b.setObjectName("chip")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=mins: self.interval.setValue(v))
            chips_i.addWidget(b)
        chips_i.addStretch(1)
        grid.addLayout(chips_i, 2, 0)
        chips_d = QHBoxLayout()
        chips_d.setSpacing(4)
        for sec, txt in ((0, "keine"), (20, "20 Sek"), (300, "5 Min"), (900, "15 Min")):
            b = QPushButton(txt)
            b.setObjectName("chip")
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip("Ohne Countdown – nur bestätigen" if sec == 0 else "")
            b.clicked.connect(lambda _=False, v=sec: self._set_dur(v))
            chips_d.addWidget(b)
        chips_d.addStretch(1)
        grid.addLayout(chips_d, 2, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 4)
        grid.setColumnStretch(2, 2)
        root.addLayout(grid)
        root.addSpacing(14)

        # Vorschau des Tagesplans
        self.plan = label("", "faint", wrap=True)
        root.addWidget(self.plan)
        root.addSpacing(14)

        en = QHBoxLayout()
        self.enabled = ToggleSwitch(checked=self.timer.enabled)
        en.addWidget(self.enabled)
        en.addSpacing(8)
        en.addWidget(label("Aktiv"))
        en.addStretch(1)
        root.addLayout(en)
        root.addSpacing(20)

        self.error = label("", "dangerText")
        self.error.hide()
        root.addWidget(self.error)

        btns = QHBoxLayout()
        if not self.is_new:
            delete = QPushButton("Löschen …")
            delete.setObjectName("danger")
            delete.setCursor(Qt.PointingHandCursor)
            delete.clicked.connect(lambda: self.done(DELETE_RESULT))
            btns.addWidget(delete)
        btns.addStretch(1)
        cancel = QPushButton("Abbrechen")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton("Erinnerung anlegen" if self.is_new else "Speichern")
        self.save_btn.setObjectName("primary")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(self.save_btn)
        root.addLayout(btns)

        for w in (self.name, self.desc, self.interval, self.dur_min, self.dur_sec, self.first):
            w.setFixedHeight(40)
        for w in (self.interval, self.dur_min, self.dur_sec):
            w.valueChanged.connect(self._update_plan)
        self.first.timeChanged.connect(self._update_plan)
        self.name.textChanged.connect(self._validate)
        self._update_plan()
        self._validate()
        self.name.setFocus()

    def _set_dur(self, sec: int):
        self.dur_min.setValue(sec // 60)
        self.dur_sec.setValue(sec % 60)

    def _icon_changed(self, b):
        self.timer.icon = b.emoji
        self.preview.set(self.timer.icon, self.timer.color)

    def _color_changed(self, b):
        self.timer.color = b.color
        self.preview.set(self.timer.icon, self.timer.color)

    def _collect(self) -> TimerConfig:
        t = TimerConfig.from_dict(self.timer.to_dict())
        t.name = self.name.text().strip()
        t.description = self.desc.text().strip()
        t.interval_min = self.interval.value()
        t.duration_sec = self.dur_min.value() * 60 + self.dur_sec.value()
        t.first_start = self.first.time().toString("HH:mm")
        t.enabled = self.enabled.isChecked()
        return t

    def _validate(self):
        ok = bool(self.name.text().strip())
        self.save_btn.setEnabled(ok)

    def _update_plan(self):
        t = self._collect()
        warn = []
        if t.duration_sec >= t.interval_min * 60:
            warn.append("Die Dauer ist länger als das Intervall.")
        # Nächster aktiver Tag für die Vorschau
        d = date.today()
        shown = None
        for i in range(8):
            dd = date.fromordinal(d.toordinal() + i)
            occ = schedule.first_occurrences_today(t, self._settings, dd, 5)
            if occ:
                shown = (dd, occ)
                break
        if shown:
            dd, occ = shown
            day = "Heute" if dd == d else ("Morgen" if dd.toordinal() == d.toordinal() + 1 else dd.strftime("%d.%m."))
            times = ", ".join(o.strftime("%H:%M") for o in occ)
            txt = f"{day}: {times} …"
            w = schedule.window_for(self._settings, dd)
            if w and parse_hm(t.first_start) < w[0].time():
                txt += f"   (aktiver Zeitraum beginnt erst {w[0]:%H:%M})"
        else:
            txt = "Mit diesen Einstellungen fällt keine Erinnerung in einen aktiven Zeitraum."
            warn.append("Prüfe die aktiven Zeiten in den Einstellungen.")
        if warn:
            txt += "\n⚠ " + " ".join(warn)
        self.plan.setText(txt)

    def _save(self):
        t = self._collect()
        if not t.name:
            self.error.setText("Bitte gib einen Zweck an.")
            self.error.show()
            return
        self.result_timer = t
        self.accept()
