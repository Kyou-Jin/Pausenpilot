"""Einstiegspunkt und Steuerung (Controller)."""
from __future__ import annotations

import getpass
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QLockFile, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QMenu, QMessageBox, QSystemTrayIcon,
                               QWidget)

from . import APP_NAME, schedule, theme, winutil
from .alarm import AlarmWindow
from .calendar_page import CalendarPage
from .compact import CompactWindow
from .editor import DELETE_RESULT, TimerEditor
from .main_window import PAUSE_CHOICES, MainWindow, TimersPage, fmt_due, fmt_remaining
from .models import MAX_TIMERS, TimerConfig
from .schedule import PHASE_WAITING, Scheduler
from .settings_page import SettingsPage
from .storage import (ACTION_DONE, ACTION_MISSED, ACTION_SKIP, ACTION_SNOOZE, AWAY_IDLE, ConfigStore, History,
                      resolve_data_dir)
from .widgets import app_icon

SERVER_NAME = f"Pausenpilot-{getpass.getuser()}"
NBSP = chr(0xA0)   # geschütztes Leerzeichen, damit „in 5 Min“ nicht umbricht


class Controller(QObject):
    def __init__(self, app: QApplication, start_hidden: bool):
        super().__init__()
        self.app = app
        self.data_dir = resolve_data_dir()
        self.store = ConfigStore(self.data_dir)
        self.history = History(self.data_dir / "history.db")
        timers, self.settings, first_run = self.store.load()
        self.timers: list[TimerConfig] = timers
        now = datetime.now()
        self.sched = Scheduler(self.timers, self.settings)
        self.sched.restore(self.store.load_state(), now)
        if self.sched.ended_pause:
            self.history.add_pause(*self.sched.ended_pause)
            self.sched.ended_pause = None
        if first_run:
            self.save_config()

        # Autostart-Eintrag mit Einstellung abgleichen (z. B. wenn die .exe verschoben wurde)
        if self.settings.autostart and not winutil.autostart_points_here():
            winutil.set_autostart(True)

        self._today = date.today()
        self._summary = self.history.day_summary(self._today)
        self._streak = self.history.streak(self._today)
        self._entries = self.history.day_entries(self._today)
        self._pauses = self.history.day_pauses(self._today)
        self._aways = self.history.day_aways(self._today)
        self._away = False
        self._last_tooltip = ""

        self.apply_theme(self.settings.theme)

        # UI
        self.timers_page = TimersPage()
        self.calendar_page = CalendarPage(self.history)
        self.settings_page = SettingsPage(self.settings, str(self.data_dir))
        self.window = MainWindow(self.timers_page, self.calendar_page, self.settings_page)
        self._restore_geometry()
        self.timers_page.rebuild(self.timers, self)
        self.timers_page.new_timer.connect(self.new_timer)
        self.timers_page.pause_requested.connect(self.pause)
        self.timers_page.resume_requested.connect(self.resume)
        self.timers_page.compact_requested.connect(self.enter_compact)
        self.timers_page.replan_requested.connect(self.replan)
        self.timers_page.conflict_fix_requested.connect(self.apply_conflict_fix)
        self.settings_page.changed.connect(self.settings_changed)
        self.settings_page.theme_changed.connect(self.apply_theme_live)
        self.settings_page.autostart_changed.connect(self.set_autostart)
        self.settings_page.export_requested.connect(self.export_csv)
        self.settings_page.wipe_requested.connect(self.wipe_history)
        self.settings_page.welcome_requested.connect(self.show_welcome)
        self.window.closed_to_tray.connect(self._closed_to_tray)
        self.window.screen_changed.connect(self._screen_changed)

        self.alarm = AlarmWindow(lambda: (self.settings.sound, self.settings.sound_volume))
        self.alarm.started.connect(self._alarm_started)
        self.alarm.completed.connect(self._alarm_completed)
        self.alarm.snoozed.connect(self._alarm_snoozed)
        self.alarm.skipped.connect(self._alarm_skipped)
        self.alarm.run_cancelled.connect(self._alarm_cancelled)
        self.alarm.queued_done.connect(self._queued_done)
        self.alarm.moved.connect(self._alarm_moved)

        self.compact = CompactWindow(self.settings.compact_on_top)
        self.compact.apply_theme()
        self.compact.expand_requested.connect(lambda: self.show_window(0))
        self.compact.pause_requested.connect(self.pause)
        self.compact.resume_requested.connect(self.resume)
        self.compact.queued_done.connect(self._queued_done)
        self.compact.moved.connect(self._compact_moved)
        self.compact.hide_requested.connect(self.hide_compact)
        self.compact.quit_requested.connect(self.quit)
        self.compact_mode = False
        self._last_main_use = time.monotonic()
        app.installEventFilter(self)

        self._build_tray()

        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._system_scheme_changed)
        except Exception:
            pass

        self.clock = QTimer(self)
        self.clock.setInterval(1000)
        self.clock.timeout.connect(self.tick)
        self.clock.start()
        self.save_timer = QTimer(self)
        self.save_timer.setInterval(60_000)
        self.save_timer.timeout.connect(self.save_state)
        self.save_timer.start()

        app.aboutToQuit.connect(self.shutdown)
        self.tick()
        if self.settings.compact_active and not first_run:
            self.enter_compact()
        elif not start_hidden or first_run:
            self.show_window()
        if not self.settings.welcome_shown:
            QTimer.singleShot(500, self.show_welcome)

    def show_welcome(self):
        """Willkommens-Bildschirm mit den wichtigsten Funktionen (beim ersten Start automatisch)."""
        from .welcome import WelcomeDialog
        parent = self.window if self.window.isVisible() else None
        dlg = WelcomeDialog(parent, self.settings.welcome_shown)
        dlg.winId()
        winutil.set_dark_titlebar(int(dlg.winId()), bool(theme.P.get("is_dark")))
        if parent is None:
            dlg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dlg.exec()
        # Erscheint bei jedem Start, bis „Beim nächsten Start nicht mehr anzeigen“ gesetzt ist
        if dlg.dont_show.isChecked() != self.settings.welcome_shown:
            self.settings.welcome_shown = dlg.dont_show.isChecked()
            self.save_config()

    # ------------------------------------------------------------------ Theme
    def apply_theme(self, mode: str):
        theme.set_palette(theme.resolve(mode))
        self.app.setStyleSheet(theme.stylesheet())

    def apply_theme_live(self, mode: str):
        self.apply_theme(mode)
        self._dark_titlebars()
        self.window.refresh_icons()
        self.timers_page._shown_paused = None
        self.timers_page.rebuild(self.timers, self)
        self.calendar_page.apply_theme()
        self.compact.apply_theme()
        for w in self.app.allWidgets():
            w.update()
        self.tick()

    def _system_scheme_changed(self, *_):
        if self.settings.theme == "system":
            self.apply_theme_live("system")

    def _dark_titlebars(self):
        dark = bool(theme.P.get("is_dark"))
        for w in self.app.topLevelWidgets():
            if w.isWindow() and w.testAttribute(Qt.WA_WState_Created):
                winutil.set_dark_titlebar(int(w.winId()), dark)

    # ------------------------------------------------------------------ Fenster
    def show_window(self, page: int | None = None):
        if self.compact_mode:
            self.compact_mode = False
            self.compact.hide()
            self.settings.compact_active = False
            self.save_config()
        self._last_main_use = time.monotonic()
        if page is not None:
            self.window.show_page(page)
        if self.window.isMinimized():
            self.window.showNormal()
        self.window.show()
        winutil.set_dark_titlebar(int(self.window.winId()), bool(theme.P.get("is_dark")))
        self.window.raise_()
        self.window.activateWindow()

    def toggle_window(self):
        if self.compact_mode:
            self.show_window()
            return
        if self.window.isVisible() and not self.window.isMinimized():
            self.window.hide()
        else:
            self.show_window()

    def _restore_geometry(self):
        geo = self.settings.window_geometry
        if geo:
            try:
                self.window.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
            except Exception:
                pass

    def _closed_to_tray(self):
        """Klick auf das X: nachfragen, ob wirklich beenden oder lieber Kompaktmodus."""
        if getattr(self, "_close_box_open", False):
            return
        self._close_box_open = True
        try:
            box = QMessageBox(self.window)
            box.setWindowTitle(APP_NAME)
            box.setIcon(QMessageBox.Question)
            box.setText("Pausenpilot wirklich schließen?")
            box.setInformativeText("Nach dem Beenden kommen keine Erinnerungen mehr, bis du das Programm "
                                   "wieder startest.\n\nIm Kompaktmodus läuft alles weiter – nur in einem "
                                   "kleinen Fenster.")
            compact = box.addButton("Kompaktmodus", QMessageBox.AcceptRole)
            quit_btn = box.addButton("Beenden", QMessageBox.DestructiveRole)
            cancel = box.addButton("Abbrechen", QMessageBox.RejectRole)
            for b in (compact, quit_btn, cancel):
                b.setCursor(Qt.PointingHandCursor)
            box.setDefaultButton(compact)
            box.setEscapeButton(cancel)
            box.exec()
            clicked = box.clickedButton()
        finally:
            self._close_box_open = False
        if clicked is compact:
            self.enter_compact()
        elif clicked is quit_btn:
            self.settings.window_geometry = bytes(self.window.saveGeometry().toBase64()).decode("ascii")
            self.save_config()
            self.quit()

    # ------------------------------------------------------------------ Kompaktmodus
    def enter_compact(self):
        if self.window.isVisible():
            self.settings.window_geometry = bytes(self.window.saveGeometry().toBase64()).decode("ascii")
        ref = self.window.screen() if self.window.isVisible() else None
        self.window.hide()
        self.compact_mode = True
        self.settings.compact_active = True
        now = datetime.now()
        self.compact.update_status(self.sched, now, self._entries, self._pauses, self._summary, self._away)
        if not (self.alarm.isVisible() and self.sched.active):
            self.compact.place(self.settings.compact_pos, ref)
            self.compact.show()
            winutil.set_dark_titlebar(int(self.compact.winId()), bool(theme.P.get("is_dark")))
        self.save_config()

    def hide_compact(self):
        self.compact_mode = False
        self.settings.compact_active = False
        self.compact.hide()
        self.save_config()
        if QSystemTrayIcon.supportsMessages() and not self.settings.close_hint_shown:
            self.tray.showMessage(APP_NAME, "Läuft im Hintergrund weiter. Über das Symbol im Infobereich "
                                            "kommst du zurück.", app_icon(), 5000)
            self.settings.close_hint_shown = True

    def _compact_moved(self, pt):
        self.settings.compact_pos = f"{pt.x()},{pt.y()}"
        self.save_config()

    def eventFilter(self, obj, ev):
        # Benutzung des großen Fensters merken (für den automatischen Kompaktmodus)
        if ev.type() in (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.KeyPress, QEvent.Wheel):
            w = None
            if isinstance(obj, QWidget):
                try:
                    w = obj.window()
                except RuntimeError:
                    w = None
            if w is self.window or (w is not None and w.parent() is self.window):
                self._last_main_use = time.monotonic()
        return False

    def _auto_compact_check(self):
        s = self.settings
        if not s.compact_auto or self.compact_mode or not self.window.isVisible() or self.window.isMinimized():
            return
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            self._last_main_use = time.monotonic()
            return
        if time.monotonic() - self._last_main_use >= s.compact_minutes * 60:
            self.enter_compact()

    def _screen_changed(self, name: str, moved: bool):
        if not name:
            return
        if moved:
            # Hauptfenster auf einen anderen Bildschirm gezogen → Erinnerungen folgen ihm dorthin
            self.settings.alarm_screen = name
            self.settings.alarm_pos = ""
        elif not self.settings.alarm_pos:
            self.settings.alarm_screen = name

    def _alarm_moved(self, pt, compact: bool):
        """Erinnerung wurde verschoben – Bildschirm und Stelle für die nächsten Male merken."""
        if compact:
            win = pt - self.compact.card.pos()
            self.settings.compact_pos = f"{win.x()},{win.y()}"
            self.compact.move(win)
            self._compact_anchor = pt
        else:
            self.settings.alarm_pos = f"{pt.x()},{pt.y()}"
            scr = QGuiApplication.screenAt(pt)
            if scr:
                self.settings.alarm_screen = scr.name()
        self.save_config()

    def _saved_alarm_center(self):
        try:
            x, y = (int(v) for v in self.settings.alarm_pos.split(","))
        except ValueError:
            return None
        pt = QPoint(x, y)
        return pt if QGuiApplication.screenAt(pt) else None   # Bildschirm nicht mehr da → Standard

    # ------------------------------------------------------------------ Tray
    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(APP_NAME)
        m = QMenu()
        self.tray_next = m.addAction("–")
        self.tray_next.setEnabled(False)
        self._tray_sep = m.addSeparator()
        self._tray_queue_actions = []
        m.aboutToShow.connect(self._fill_tray_queue)
        m.addAction("Öffnen", lambda: self.show_window(0))
        m.addAction("Kalender", lambda: self.show_window(1))
        m.addAction("Kompaktansicht", self.enter_compact)
        m.addSeparator()
        self.tray_pause = m.addMenu("Pause starten")
        for mins, txt in PAUSE_CHOICES:
            self.tray_pause.addAction(txt, lambda m_=mins: self.pause(m_))
        self.tray_resume = m.addAction("Pause beenden", self.resume)
        m.addSeparator()
        m.addAction("Beenden", self.quit)
        self.tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self._tray_paused_icon = None

    def _fill_tray_queue(self):
        """Wartende Erinnerungen (z. B. wegen Vollbild) direkt im Menü abhaken."""
        for a in self._tray_queue_actions:
            self.tray_menu.removeAction(a)
        self._tray_queue_actions = []
        for tid in self.sched.queue:
            t = self.sched.timer(tid)
            if t and tid != self.sched.active:
                a = QAction(f"✓ Erledigt: {t.name}", self.tray_menu)
                a.triggered.connect(lambda _=False, x=tid: self._queued_done(x))
                self.tray_menu.insertAction(self._tray_sep, a)
                self._tray_queue_actions.append(a)

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.toggle_window()

    def _update_tray(self, now: datetime):
        paused = self.sched.paused_until is not None
        if paused != self._tray_paused_icon:
            self.tray.setIcon(app_icon(paused))
            self._tray_paused_icon = paused
        self.tray_pause.menuAction().setVisible(not paused)
        self.tray_resume.setVisible(paused)
        nxt = self.sched.next_overall()
        if paused:
            short, long = self._pause_status(now)
            tip = f"{APP_NAME} – {short}"
            self.tray_next.setText(short)
            self.window.set_next("Pause läuft", long)
        elif self.sched.active:
            t = self.sched.timer(self.sched.active)
            name = t.name if t else "–"
            tip = f"{APP_NAME} – jetzt: {name}"
            self.tray_next.setText(f"Jetzt: {name}")
            self.window.set_next(name, "jetzt")
        elif nxt:
            t, due = nxt
            secs = (due - now).total_seconds()
            soon = secs < 3600 and due.date() == now.date()
            rel = (f"in {fmt_remaining(secs)}" if soon else f"{fmt_due(due, now)} Uhr").replace(" ", NBSP)
            tip = f"{APP_NAME} – {t.name} {rel}"
            self.tray_next.setText(f"Nächste: {t.name} – {rel}")
            self.window.set_next(t.name, f"{fmt_due(due, now)} Uhr  ·  {rel}" if soon else rel, t.icon, t.color)
        else:
            tip = f"{APP_NAME} – keine anstehenden Erinnerungen"
            self.tray_next.setText("Keine anstehenden Erinnerungen")
            self.window.set_next("–", "keine anstehende Erinnerung")
        call = getattr(self, "_call", None)
        if call and not paused:
            tip += f"\n{call}-Anruf läuft – Erinnerungen kommen leise"
        if tip != self._last_tooltip:
            self.tray.setToolTip(tip)
            self._last_tooltip = tip

    # ------------------------------------------------------------------ Takt
    def tick(self):
        now = datetime.now()
        idle = winutil.idle_seconds()
        call = self._call_state()
        if call:
            idle = 0.0            # im Telefonat sitzt man am PC, auch ohne Maus/Tastatur
        self.alarm.set_quiet(bool(call))
        self._set_compact_quiet(bool(call))
        hold = self.settings.hold_fullscreen and bool(self.sched.queue or self._due_now(now)) \
            and winutil.user_busy()
        self._held = hold
        locked = winutil.screen_locked()
        events = self.sched.tick(now, idle, hold, locked)
        changed = False
        for ev in events:
            if ev[0] == "alarm":
                self._show_alarm(ev[1])
                changed = True
            elif ev[0] == "expired":
                _, tid, snoozes, planned = ev
                if self.alarm.timer and self.alarm.timer.id == tid:
                    self.alarm.close_silently()
                t = self.sched.timer(tid)
                if t:
                    self.history.add(t, ACTION_SKIP, snoozes=snoozes, planned=planned)
                self._refresh_stats()
                changed = True
            elif ev[0] == "pause_ended":
                self._log_pause((ev[1], ev[2]))
                changed = True
            elif ev[0] == "away_ended":
                self._log_away(*ev[1:])
                changed = True
            elif ev[0] == "returned":
                changed = True
        self._away = self.sched.away_since is not None
        if self.alarm.isVisible() and self.sched.active:
            self._push_waiting()
        if now.date() != self._today:
            self._today = now.date()
            self._refresh_stats()
            self.calendar_page.refresh()
        if self.compact_mode:
            if not (self.alarm.isVisible() and self.alarm.timer is not None) and not self.compact.isVisible():
                self.compact.show()
            if self.compact.isVisible():
                self.compact.update_status(self.sched, now, self._entries, self._pauses, self._summary, self._away,
                                           self._held)
        else:
            self._auto_compact_check()
        if self.window.isVisible():
            self.timers_page.update_status(self.sched, now, self._away, self._summary, self._streak,
                                           self._entries, self._pauses, self._aways)
        self._update_tray(now)
        if changed:
            self.save_state()

    def _call_state(self) -> str | None:
        """Laufendes Telefonat (Teams, Zoom …)? Registry-Abfrage höchstens alle 3 Sekunden."""
        if not self.settings.quiet_in_calls:
            self._call = None
            return None
        t = time.monotonic()
        if t - getattr(self, "_call_checked", -99.0) >= 3.0:
            self._call_checked = t
            self._call = winutil.call_app()
        return getattr(self, "_call", None)

    def _set_compact_quiet(self, on: bool):
        """Im Telefonat auch das Kompaktfenster aus dem „immer oben“-Bereich nehmen."""
        was = getattr(self, "_compact_quiet", False)
        self._compact_quiet = on
        if not self.compact.isVisible() or not self.settings.compact_on_top:
            return
        if on:      # jedes Mal: ein erneutes show() würde es sonst wieder nach oben holen
            winutil.set_topmost(int(self.compact.winId()), False)
        elif was:
            winutil.set_topmost(int(self.compact.winId()), True)

    def _due_now(self, now: datetime) -> bool:
        """Ist gerade etwas fällig? (nur dann wird der Vollbild-Status abgefragt)"""
        if self.sched.active:
            return False
        return any(t.enabled and (r := self.sched.rt.get(t.id)) and r.due and r.due <= now
                   for t in self.sched.timers)

    def _show_alarm(self, tid: str):
        t = self.sched.timer(tid)
        if not t:
            self.sched.active = None
            return
        rt = self.sched.rt[tid]
        screen = self.window.screen().name() if self.window.isVisible() and self.window.screen() else \
            self.settings.alarm_screen
        anchor = None
        if self.compact_mode:
            if self.compact.isVisible():
                anchor = self.compact.card.mapToGlobal(self.compact.card.rect().topLeft())
                self._compact_anchor = anchor
                self.compact.hide()
            else:
                anchor = getattr(self, "_compact_anchor", None)
            if anchor is None:
                self.compact.place(self.settings.compact_pos)
                anchor = self.compact.pos() + self.compact.card.pos()
        center = None if anchor is not None else self._saved_alarm_center()
        self.alarm.show_alarm(t, rt.snoozes, len(self.sched.queue), rt.planned, screen, anchor, center)
        winutil.set_dark_titlebar(int(self.alarm.winId()), bool(theme.P.get("is_dark")))

    def _refresh_stats(self):
        self._summary = self.history.day_summary(self._today)
        self._streak = self.history.streak(self._today)
        self._entries = self.history.day_entries(self._today)
        self._pauses = self.history.day_pauses(self._today)
        self._aways = self.history.day_aways(self._today)
        if self.calendar_page.isVisible():
            self.calendar_page.refresh()

    # ------------------------------------------------------------------ Alarm-Aktionen
    def _alarm_started(self, tid: str):
        self.sched.start(tid)
        self.tick()

    def _alarm_cancelled(self, tid: str):
        self.sched.cancel_run(tid)
        self.tick()

    def _alarm_completed(self, tid: str):
        t = self.sched.timer(tid)
        now = datetime.now()
        snoozes, planned = self.sched.complete(tid, now)
        if t:
            self.history.add(t, ACTION_DONE, snoozes=snoozes, minutes=round(t.duration_sec / 60), planned=planned)
            due = self.sched.rt.get(tid).due if self.sched.rt.get(tid) else None
            if due:
                self.alarm.set_next_hint(f"Nächstes Mal: {fmt_due(due, now)} Uhr")
        self._after_action()

    def _push_waiting(self):
        items = [(tid, t.name) for tid in self.sched.queue if (t := self.sched.timer(tid))]
        self.alarm.update_waiting(len(self.sched.queue), [n for _, n in items], [i for i, _ in items])

    def _queued_done(self, tid: str):
        """Wartende Erinnerung während eines laufenden Countdowns nebenbei abgehakt."""
        t = self.sched.timer(tid)
        res = self.sched.complete_queued(tid, datetime.now())
        if t and res:
            snoozes, planned = res
            self.history.add(t, ACTION_DONE, snoozes=snoozes, minutes=round(t.duration_sec / 60),
                             planned=planned)
            self.alarm._sound("click")
        self._push_waiting()
        self._after_action()
        if self.compact.isVisible():
            self.compact.update_status(self.sched, datetime.now(), self._entries, self._pauses, self._summary,
                                       self._away, getattr(self, "_held", False))

    def _alarm_snoozed(self, tid: str, minutes: int):
        t = self.sched.timer(tid)
        planned = self.sched.rt[tid].planned if tid in self.sched.rt else None
        n = self.sched.snooze(tid, minutes, datetime.now())
        if t:
            self.history.add(t, ACTION_SNOOZE, snoozes=n, minutes=minutes, planned=planned)
        self._after_action()

    def _alarm_skipped(self, tid: str):
        t = self.sched.timer(tid)
        snoozes, planned = self.sched.skip(tid, datetime.now())
        if t:
            self.history.add(t, ACTION_SKIP, snoozes=snoozes, planned=planned)
        self._after_action()

    def _after_action(self):
        self._refresh_stats()
        self.save_state()

    # ------------------------------------------------------------------ Timer verwalten
    def new_timer(self):
        if len(self.timers) >= MAX_TIMERS:
            self.message(f"Es sind maximal {MAX_TIMERS} Erinnerungen möglich.")
            return
        dlg = TimerEditor(None, self.settings, self.window)
        self._prep_dialog(dlg)
        if dlg.exec():
            t = dlg.result_timer
            self.timers.append(t)
            self._config_changed({t.id})

    def edit_timer(self, tid: str):
        t = self.sched.timer(tid)
        if not t:
            return
        dlg = TimerEditor(t, self.settings, self.window)
        self._prep_dialog(dlg)
        res = dlg.exec()
        if res == DELETE_RESULT:
            self.delete_timer(tid)
            return
        if res == QDialog.Accepted:
            nt = dlg.result_timer
            sched_changed = (nt.interval_min != t.interval_min or nt.first_start != t.first_start
                             or nt.enabled != t.enabled)
            idx = next(i for i, x in enumerate(self.timers) if x.id == tid)
            self.timers[idx] = nt
            self._config_changed({tid} if sched_changed else set())

    def _prep_dialog(self, dlg):
        # Nur das Hauptfenster sperren – das Erinnerungsfenster muss bedienbar bleiben
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setWindowIcon(app_icon())
        winutil.set_dark_titlebar(int(dlg.winId()), bool(theme.P.get("is_dark")))

    def toggle_timer(self, tid: str, on: bool):
        for t in self.timers:
            if t.id == tid:
                t.enabled = on
        self._config_changed({tid})

    def delete_timer(self, tid: str):
        t = self.sched.timer(tid)
        if not t:
            return
        box = QMessageBox(self.window)
        box.setWindowTitle("Erinnerung löschen")
        box.setText(f"„{t.name}“ wirklich löschen?")
        box.setInformativeText("Der bisherige Verlauf im Kalender bleibt erhalten.")
        yes = box.addButton("Löschen", QMessageBox.DestructiveRole)
        box.addButton("Abbrechen", QMessageBox.RejectRole)
        yes.setObjectName("danger")
        self._prep_dialog(box)
        box.exec()
        if box.clickedButton() is yes:
            self.timers = [x for x in self.timers if x.id != tid]
            self._config_changed(set())

    def trigger_timer(self, tid: str):
        if self.sched.trigger_now(tid, datetime.now()):
            self.save_state()
        self.tick()

    def _config_changed(self, changed: set[str]):
        closed = self.sched.apply_config(self.timers, self.settings, datetime.now(), changed)
        if self.alarm.timer and self.alarm.timer.id in closed:
            self.alarm.close_silently()
        self.timers_page.rebuild(self.timers, self)
        self.save_config()
        self.save_state()
        self.tick()

    def apply_conflict_fix(self, tid: str, new_start: str):
        """Vorschlag aus „Überschneidungen heute“: Startzeit einer Erinnerung verschieben."""
        import dataclasses
        for i, t in enumerate(self.timers):
            if t.id == tid:
                self.timers[i] = dataclasses.replace(t, first_start=new_start)
                self._config_changed({tid})
                self.timers_page.hint.setText(f"„{t.name}“ startet jetzt ab {new_start} Uhr.")
                return

    def replan(self):
        """Knopf „Zeitplan aktualisieren“: Raster aus Startzeit/Intervall/aktiver Zeit ab jetzt anwenden."""
        n = self.sched.realign(datetime.now())
        self.save_state()
        self.tick()
        hint = self.timers_page.hint
        hint.setText(f"Zeitplan aktualisiert · {n} {'Erinnerung' if n == 1 else 'Erinnerungen'} neu ausgerichtet."
                     if n else "Zeitplan aktualisiert · alles war schon passend.")
        QTimer.singleShot(6000, lambda: (self.timers_page.__setattr__("_replan_state", None), self.tick()))

    # ------------------------------------------------------------------ Einstellungen
    def settings_changed(self):
        self.compact.set_on_top(self.settings.compact_on_top)
        self.sched.apply_config(self.timers, self.settings, datetime.now(), set())
        self.save_config()
        self.save_state()
        self.tick()

    def set_autostart(self, on: bool):
        if not winutil.set_autostart(on):
            self.message("Der Autostart konnte nicht geändert werden.", warn=True)
            self.settings_page.set_autostart_silent(winutil.autostart_registered())
            self.save_config()

    def export_csv(self):
        default = str(Path.home() / "Desktop" / f"Pausenpilot-Verlauf-{date.today():%Y-%m-%d}.csv")
        dlg = QFileDialog(self.window, "Verlauf exportieren", default, "CSV (*.csv)")
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setDefaultSuffix("csv")
        self._prep_dialog(dlg)
        path = dlg.selectedFiles()[0] if dlg.exec() and dlg.selectedFiles() else ""
        if path:
            try:
                n = self.history.export_csv(Path(path))
                self.message(f"{n} Einträge exportiert nach\n{path}")
            except OSError as e:
                self.message(f"Export fehlgeschlagen:\n{e}", warn=True)

    def wipe_history(self):
        n, pn, first = self.history.count()
        if not n and not pn:
            self.message("Da ist nichts zum Löschen. Der Kalender ist schon leer – beeindruckend konsequent.")
            return
        since = date.fromisoformat(first).strftime("%d.%m.%Y") if first else "–"
        steps = [
            ("Gesamten Verlauf löschen?",
             f"Das entfernt {n} {'Eintrag' if n == 1 else 'Einträge'} und {pn} "
             f"{'Pause' if pn == 1 else 'Pausen'} seit dem {since} – samt aller Haken und Medaillen.\n\n"
             "Deine Erinnerungen und Einstellungen bleiben erhalten.",
             "Ja, löschen", "Abbrechen"),
            ("Wirklich? Alles?",
             "Jeder grüne Haken, jede Medaille, jede einzelne Pause – weg. Für immer.\n\n"
             "Rückgängig machen geht nicht. Auch nicht mit Strg+Z, falls du das gerade überlegt hast.",
             "Ja, wirklich", "Lieber nicht"),
            ("Letzte Chance.",
             "Ganz ehrlich: Wer seine eigene Statistik löscht, hat meistens gerade keine besonders gute.\n\n"
             "Aber gut – du bist erwachsen. Meistens.",
             "Weg damit", "Okay, ich behalte sie"),
        ]
        for i, (title, text, yes_txt, no_txt) in enumerate(steps, 1):
            box = QMessageBox(self.window)
            box.setWindowTitle(f"Verlauf löschen ({i}/3)")
            box.setIcon(QMessageBox.Warning)
            box.setText(title)
            box.setInformativeText(text)
            yes = box.addButton(yes_txt, QMessageBox.DestructiveRole)
            yes.setObjectName("danger")
            no = box.addButton(no_txt, QMessageBox.RejectRole)
            box.setDefaultButton(no)
            box.setEscapeButton(no)
            self._prep_dialog(box)
            box.exec()
            if box.clickedButton() is not yes:
                return
        self.history.clear()
        self._refresh_stats()
        self.calendar_page.refresh()
        self.tick()
        self.message("Erledigt. Der Kalender ist leer – frischer Start.\n\nDiesmal klappt's bestimmt.")

    def message(self, text: str, warn: bool = False):
        box = QMessageBox(self.window)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Warning if warn else QMessageBox.Information)
        box.setText(text)
        box.addButton("OK", QMessageBox.AcceptRole)
        self._prep_dialog(box)
        box.exec()

    # ------------------------------------------------------------------ Pause
    def pause(self, minutes: int):
        """minutes: 0 = offene Pause (bis „Pause beenden“), -1 = bis morgen, sonst Minuten."""
        now = datetime.now()
        if minutes == 0:
            until = None
        elif minutes < 0:
            until = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
        else:
            until = now + timedelta(minutes=minutes)
        closed = self.sched.pause(until, now)
        if closed:
            tid, snoozes, planned = closed
            if self.alarm.timer and self.alarm.timer.id == tid and not self.alarm.is_running():
                self.alarm.close_silently()
            t = self.sched.timer(tid)
            if t:
                self.history.add(t, ACTION_SKIP, snoozes=snoozes, planned=planned)
            self._refresh_stats()
        self.save_state()
        self.tick()

    def resume(self):
        span = self.sched.resume(datetime.now())
        self._log_pause(span)
        self.save_state()
        self.tick()

    def _log_away(self, start, end, reason, missed):
        """Abwesenheit in den Verlauf: als eigener Zeitraum, dazu die Termine, die hineinfielen.
        Gesperrt/Standby: Erinnerungen mit Dauer (Augen entspannen, Aufstehen …) gelten als erledigt –
        man war ja weg vom Bildschirm. Alles andere wird neutral als „ausgelassen“ vermerkt."""
        logged = self.history.add_away(start, end, reason)
        for tid, ts in missed:
            t = self.sched.timer(tid)
            if not t or not (start - timedelta(minutes=1) <= ts <= end):
                continue
            if reason != AWAY_IDLE and t.duration_sec > 0:
                self.history.add(t, ACTION_DONE, minutes=round(t.duration_sec / 60), planned=ts, ts=ts, via=reason)
            else:
                self.history.add(t, ACTION_MISSED, planned=ts, ts=ts, via=reason)
        if logged or missed:
            self._refresh_stats()

    def _log_pause(self, span):
        if span and self.history.add_pause(*span):
            self._pauses = self.history.day_pauses(self._today)
            self.calendar_page.refresh()

    def _pause_status(self, now: datetime) -> tuple[str, str]:
        """(kurz, lang) – Text für Tray, Kopfzeile und Banner während einer Pause."""
        since = self.sched.paused_since or now
        dur = fmt_remaining((now - since).total_seconds())
        if self.sched.pause_open:
            return f"Pause seit {since:%H:%M} Uhr", f"seit {since:%H:%M} Uhr · {dur}"
        return (f"Pausiert bis {fmt_due(self.sched.paused_until, now)}",
                f"bis {fmt_due(self.sched.paused_until, now)} Uhr · noch "
                f"{fmt_remaining((self.sched.paused_until - now).total_seconds())}")

    # ------------------------------------------------------------------ Speichern
    def save_config(self):
        try:
            self.store.save(self.timers, self.settings)
        except OSError as e:
            self.tray.showMessage(APP_NAME, f"Speichern fehlgeschlagen: {e}", QSystemTrayIcon.Warning, 5000)

    def save_state(self):
        self.store.save_state(self.sched.snapshot())

    def quit(self):
        self.window._quitting = True
        self.app.quit()

    def shutdown(self):
        self.settings_page.flush()
        if self.window.isVisible():
            self.settings.window_geometry = bytes(self.window.saveGeometry().toBase64()).decode("ascii")
        self.save_config()
        self.save_state()
        self.tray.hide()
        self.compact.hide()
        self.history.close()


def main():
    args = sys.argv[1:]
    start_hidden = "--tray" in args
    winutil.set_app_user_model_id("Pausenpilot.App")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())

    # Nur eine Instanz (Sperrdatei). Eine zweite Instanz holt das Fenster der ersten nach vorn.
    lock = QLockFile(str(Path(tempfile.gettempdir()) / f"{SERVER_NAME}.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        if not start_hidden:
            sock = QLocalSocket()
            sock.connectToServer(SERVER_NAME)
            if sock.waitForConnected(1000):
                sock.write(b"show")
                sock.flush()
                sock.waitForBytesWritten(500)
                sock.disconnectFromServer()
        return 0
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.listen(SERVER_NAME)

    ctrl = Controller(app, start_hidden)

    def on_conn():
        c = server.nextPendingConnection()
        if c:
            ctrl.show_window()
            c.disconnected.connect(c.deleteLater)
    server.newConnection.connect(on_conn)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        ctrl.show_window()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
