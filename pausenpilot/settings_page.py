"""Einstellungen: aktive Zeiten, Autostart, Töne, Abwesenheit, Design, Daten."""
from __future__ import annotations

from PySide6.QtCore import QTime, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSlider, QSpinBox, QTimeEdit, QVBoxLayout, QWidget)

from . import APP_NAME, APP_VERSION, sounds
from .models import DayWindow, Settings, WEEKDAYS
from .widgets import ToggleSwitch, label, divider


class SettingsPage(QWidget):
    changed = Signal()            # irgendeine Einstellung wurde geändert
    theme_changed = Signal(str)
    autostart_changed = Signal(bool)
    export_requested = Signal()
    wipe_requested = Signal()
    welcome_requested = Signal()

    def __init__(self, settings: Settings, data_dir: str, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.settings = settings
        self._loading = True
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(700)
        self._debounce.timeout.connect(self._commit_days)

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
        root.addWidget(label("Einstellungen", "h1"))
        root.addWidget(label("Änderungen werden sofort gespeichert.", "muted"))
        root.addSpacing(22)

        # ---- Aktive Zeiten
        card, v = self._card("Aktive Zeiten",
                             "Nur in diesen Zeiträumen wird erinnert. Außerhalb ruht das Tool.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.day_rows = []
        for i, name in enumerate(WEEKDAYS):
            w = settings.days[i]
            sw = ToggleSwitch(checked=w.enabled)
            lb = label(name)
            lb.setMinimumWidth(96)
            st = QTimeEdit(QTime.fromString(w.start, "HH:mm"))
            st.setDisplayFormat("HH:mm")
            en = QTimeEdit(QTime.fromString(w.end, "HH:mm"))
            en.setDisplayFormat("HH:mm")
            en.setToolTip("00:00 = bis Mitternacht")
            for te in (st, en):
                te.setFixedSize(92, 38)
                te.setAlignment(Qt.AlignCenter)
            bis = label("bis", "muted")
            info = label("", "faint")
            grid.addWidget(sw, i, 0)
            grid.addWidget(lb, i, 1)
            grid.addWidget(st, i, 2)
            grid.addWidget(bis, i, 3)
            grid.addWidget(en, i, 4)
            grid.addWidget(info, i, 5)
            sw.toggled.connect(self._days_changed)
            st.timeChanged.connect(self._days_changed)
            en.timeChanged.connect(self._days_changed)
            self.day_rows.append((sw, st, en, bis, info))
        grid.setColumnStretch(5, 1)
        v.addLayout(grid)
        v.addSpacing(10)
        copy_row = QHBoxLayout()
        copy = QPushButton("Montag auf alle Werktage übertragen")
        copy.setCursor(Qt.PointingHandCursor)
        copy.clicked.connect(self._copy_monday)
        copy_row.addWidget(copy)
        copy_row.addStretch(1)
        v.addLayout(copy_row)
        root.addWidget(card)
        root.addSpacing(16)

        # ---- Verhalten
        card, v = self._card("Verhalten", None)
        self.autostart = self._toggle_row(v, "Mit Windows starten",
                                          "Startet unauffällig im Infobereich (Tray), sobald du dich anmeldest.",
                                          settings.autostart)
        self.autostart.toggled.connect(self._autostart_toggled)
        v.addWidget(divider())
        self.idle = self._toggle_row(v, "Abwesenheit erkennen",
                                     "Bist du nicht am PC, wird nicht erinnert. Verpasste Erinnerungen "
                                     "starten nach deiner Rückkehr neu.", settings.idle_detect)
        idle_row = QHBoxLayout()
        idle_row.addSpacing(54)
        idle_row.addWidget(label("Als abwesend gelten nach", "muted"))
        self.idle_min = QSpinBox()
        self.idle_min.setRange(1, 120)
        self.idle_min.setSuffix(" Min")
        self.idle_min.setValue(settings.idle_minutes)
        self.idle_min.setFixedSize(92, 38)
        idle_row.addWidget(self.idle_min)
        idle_row.addWidget(label("ohne Maus/Tastatur", "muted"))
        idle_row.addStretch(1)
        v.addLayout(idle_row)
        v.addSpacing(6)
        v.addWidget(divider())
        self.hold_fs = self._toggle_row(v, "Bei Vollbild und Präsentationen zurückhalten",
                                        "Läuft ein Video, Spiel oder eine Präsentation im Vollbild, wartet die "
                                        "Erinnerung, bis du fertig bist.", settings.hold_fullscreen)
        self.hold_fs.toggled.connect(self._save)
        v.addWidget(divider())
        self.quiet_calls = self._toggle_row(v, "Bei Telefonaten leise erinnern",
                                            "Läuft ein Anruf in Teams, Zoom, Webex, Skype, Discord oder Slack, "
                                            "kommt die Erinnerung ohne Ton und bleibt hinter dem aktiven Fenster – "
                                            "eine geteilte Präsentation wird nicht überdeckt.",
                                            settings.quiet_in_calls)
        self.quiet_calls.toggled.connect(self._save)
        self.idle.toggled.connect(self._save)
        self.idle.toggled.connect(self.idle_min.setEnabled)
        self.idle_min.setEnabled(settings.idle_detect)
        self.idle_min.valueChanged.connect(self._save)
        root.addWidget(card)
        root.addSpacing(16)

        # ---- Fenster / Kompaktmodus
        card, v = self._card("Kompaktmodus", "Ein kleines Fenster, das nur die nächste Erinnerung zeigt – "
                                             "umschalten über den Knopf oben auf der Hauptseite.")
        self.compact_auto = self._toggle_row(v, "Automatisch in den Kompaktmodus wechseln",
                                             "Wenn du das große Fenster eine Weile nicht benutzt, wird es "
                                             "zum kleinen Kompaktfenster.", settings.compact_auto)
        c_row = QHBoxLayout()
        c_row.addSpacing(54)
        c_row.addWidget(label("Wechseln nach", "muted"))
        self.compact_min = QSpinBox()
        self.compact_min.setRange(1, 120)
        self.compact_min.setSuffix(" Min")
        self.compact_min.setValue(settings.compact_minutes)
        self.compact_min.setFixedSize(92, 38)
        c_row.addWidget(self.compact_min)
        c_row.addWidget(label("ohne Benutzung des Fensters", "muted"))
        c_row.addStretch(1)
        v.addLayout(c_row)
        v.addSpacing(6)
        v.addWidget(divider())
        self.compact_top = self._toggle_row(v, "Kompaktfenster immer im Vordergrund",
                                            "Bleibt über anderen Programmen sichtbar.", settings.compact_on_top)
        self.compact_auto.toggled.connect(self._save)
        self.compact_auto.toggled.connect(self.compact_min.setEnabled)
        self.compact_min.setEnabled(settings.compact_auto)
        self.compact_min.valueChanged.connect(self._save)
        self.compact_top.toggled.connect(self._save)
        root.addWidget(card)
        root.addSpacing(16)

        # ---- Ton & Design
        card, v = self._card("Ton & Darstellung", None)
        self.sound = self._toggle_row(v, "Töne", "Dezenter Klick bei einer Erinnerung, leises 3-2-1 am Ende "
                                                 "eines Countdowns.", settings.sound)
        vol_row = QHBoxLayout()
        vol_row.addSpacing(54)
        vol_row.addWidget(label("Lautstärke", "muted"))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(5, 100)
        self.volume.setValue(settings.sound_volume)
        self.volume.setFixedWidth(200)
        vol_row.addWidget(self.volume)
        test = QPushButton("Probehören")
        test.setObjectName("ghost")
        test.clicked.connect(lambda: sounds.play("click", self.volume.value()))
        vol_row.addWidget(test)
        vol_row.addStretch(1)
        v.addLayout(vol_row)
        self.sound.toggled.connect(self._save)
        self.sound.toggled.connect(self.volume.setEnabled)
        self.volume.setEnabled(settings.sound)
        self.volume.sliderReleased.connect(self._volume_released)
        self.volume.valueChanged.connect(self._save)
        v.addSpacing(6)
        v.addWidget(divider())
        v.addSpacing(10)
        th = QHBoxLayout()
        tv = QVBoxLayout()
        tv.setSpacing(1)
        tv.addWidget(label("Design", "h3"))
        tv.addWidget(label("Hell, dunkel oder wie Windows.", "faint"))
        th.addLayout(tv, 1)
        self.theme_box = QComboBox()
        self.theme_box.addItem("Wie Windows", "system")
        self.theme_box.addItem("Dunkel", "dark")
        self.theme_box.addItem("Hell", "light")
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(settings.theme)))
        self.theme_box.setFixedWidth(160)
        self.theme_box.currentIndexChanged.connect(self._theme_changed)
        th.addWidget(self.theme_box)
        v.addLayout(th)
        root.addWidget(card)
        root.addSpacing(16)

        # ---- Daten
        card, v = self._card("Daten", "Alles bleibt lokal auf diesem PC – portabel neben der .exe.")
        path = label(data_dir, "faint", wrap=True)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(path)
        v.addSpacing(10)
        row = QHBoxLayout()
        open_btn = QPushButton("Ordner öffnen")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(data_dir)))
        exp = QPushButton("Verlauf als CSV exportieren …")
        exp.clicked.connect(self.export_requested.emit)
        row.addWidget(open_btn)
        row.addWidget(exp)
        row.addStretch(1)
        wipe = QPushButton("Verlauf komplett löschen …")
        wipe.setObjectName("danger")
        wipe.setToolTip("Löscht den gesamten Kalender: alle erledigten, verschobenen und übersprungenen "
                        "Erinnerungen, alle Pausen und Medaillen. Deine Erinnerungen und Einstellungen bleiben.")
        wipe.clicked.connect(self.wipe_requested.emit)
        row.addWidget(wipe)
        v.addLayout(row)
        root.addWidget(card)
        root.addSpacing(18)
        vrow = QHBoxLayout()
        vrow.addWidget(label(f"{APP_NAME} {APP_VERSION}", "faint"))
        tour = QPushButton("Was kann Pausenpilot? – Überblick zeigen")
        tour.setObjectName("link")
        tour.setCursor(Qt.PointingHandCursor)
        tour.clicked.connect(self.welcome_requested.emit)
        vrow.addWidget(tour)
        vrow.addStretch(1)
        root.addLayout(vrow)
        root.addStretch(1)

        self._refresh_day_rows()
        self._loading = False

    # ------------------------------------------------------------------ Bausteine
    def _card(self, title: str, sub: str | None):
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(6)
        v.addWidget(label(title, "h2"))
        if sub:
            v.addWidget(label(sub, "muted", wrap=True))
        v.addSpacing(8)
        return card, v

    def _toggle_row(self, v: QVBoxLayout, title: str, sub: str, checked: bool) -> ToggleSwitch:
        row = QHBoxLayout()
        row.setSpacing(12)
        sw = ToggleSwitch(checked=checked)
        row.addWidget(sw, 0, Qt.AlignTop)
        tv = QVBoxLayout()
        tv.setSpacing(1)
        tv.addWidget(label(title, "h3"))
        tv.addWidget(label(sub, "faint", wrap=True))
        row.addLayout(tv, 1)
        v.addLayout(row)
        v.addSpacing(8)
        return sw

    # ------------------------------------------------------------------ Ereignisse
    def _refresh_day_rows(self):
        for sw, st, en, bis, info in self.day_rows:
            on = sw.isChecked()
            for w in (st, en, bis):
                w.setEnabled(on)
            if not on:
                info.setText("keine Erinnerungen")
                info.setObjectName("faint")
            else:
                s, e = st.time(), en.time()
                if e == QTime(0, 0):
                    mins = (24 * 60) - (s.hour() * 60 + s.minute())
                else:
                    mins = (e.hour() * 60 + e.minute()) - (s.hour() * 60 + s.minute())
                if mins <= 0:
                    info.setText("⚠ Ende liegt vor dem Start")
                    info.setObjectName("warnText")
                else:
                    h, m = divmod(mins, 60)
                    info.setText(f"{h} Std {m:02d} Min" if m else f"{h} Std")
                    info.setObjectName("faint")
            info.style().unpolish(info)
            info.style().polish(info)

    def _days_changed(self, *_):
        self._refresh_day_rows()
        if self._loading:
            return
        # Kurz warten, damit halb eingetippte Uhrzeiten nicht sofort übernommen werden
        self._debounce.start()

    def flush(self):
        """Noch nicht übernommene Zeitänderungen sofort speichern (z. B. beim Beenden)."""
        if self._debounce.isActive():
            self._debounce.stop()
            self._commit_days()

    def _commit_days(self):
        self.settings.days = [DayWindow(sw.isChecked(), st.time().toString("HH:mm"), en.time().toString("HH:mm"))
                              for sw, st, en, _b, _i in self.day_rows]
        self.changed.emit()

    def _copy_monday(self):
        sw0, st0, en0, _b, _i = self.day_rows[0]
        self._loading = True
        for sw, st, en, _b2, _i2 in self.day_rows[1:5]:
            sw.setChecked(sw0.isChecked())
            st.setTime(st0.time())
            en.setTime(en0.time())
        self._loading = False
        self._days_changed()

    def _autostart_toggled(self, on: bool):
        if self._loading:
            return
        self.settings.autostart = on
        self.autostart_changed.emit(on)
        self.changed.emit()

    def set_autostart_silent(self, on: bool):
        self.autostart.setCheckedSilent(on)
        self.settings.autostart = on

    def _volume_released(self):
        sounds.play("click", self.volume.value())

    def _theme_changed(self, _):
        if self._loading:
            return
        self.settings.theme = self.theme_box.currentData()
        self.theme_changed.emit(self.settings.theme)
        self.changed.emit()

    def _save(self, *_):
        if self._loading:
            return
        self.settings.idle_detect = self.idle.isChecked()
        self.settings.idle_minutes = self.idle_min.value()
        self.settings.hold_fullscreen = self.hold_fs.isChecked()
        self.settings.quiet_in_calls = self.quiet_calls.isChecked()
        self.settings.sound = self.sound.isChecked()
        self.settings.sound_volume = self.volume.value()
        self.settings.compact_auto = self.compact_auto.isChecked()
        self.settings.compact_minutes = self.compact_min.value()
        self.settings.compact_on_top = self.compact_top.isChecked()
        self.changed.emit()
