"""Windows-spezifische Helfer: Leerlaufzeit, Autostart, dunkle Titelleiste."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Pausenpilot"


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float:
    """Sekunden seit der letzten Maus-/Tastatureingabe (0 bei Fehlern / Nicht-Windows)."""
    if sys.platform != "win32":
        return 0.0
    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return ((now - lii.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return 0.0


def user_busy() -> bool:
    """True bei Vollbild-Anwendung, Präsentationsmodus oder gesperrtem Bildschirm
    (SHQueryUserNotificationState)."""
    if sys.platform != "win32":
        return False
    try:
        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
        # 1 = nicht anwesend/gesperrt, 2 = Vollbild-App, 3 = Direct3D-Vollbild, 4 = Präsentation
        return state.value in (1, 2, 3, 4)
    except Exception:
        return False


def screen_locked() -> bool:
    """True, wenn der Bildschirm gesperrt ist (Win+L, Sperrbildschirm, UAC-/Anmeldedesktop).
    Ist die Arbeitsfläche „Default“ nicht die aktive Eingabe-Arbeitsfläche, ist gesperrt."""
    if sys.platform != "win32":
        return False
    try:
        u = ctypes.windll.user32
        u.OpenInputDesktop.restype = ctypes.c_void_p
        u.GetUserObjectInformationW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                                ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]
        u.CloseDesktop.argtypes = [ctypes.c_void_p]
        h = u.OpenInputDesktop(0, False, 0x0100)       # DESKTOP_SWITCHDESKTOP
        if not h:
            return True                                 # Eingabe-Desktop gehört nicht uns → gesperrt
        try:
            buf = ctypes.create_unicode_buffer(256)
            need = ctypes.c_uint(0)
            if u.GetUserObjectInformationW(h, 2, buf, ctypes.sizeof(buf), ctypes.byref(need)):  # UOI_NAME
                return buf.value.lower() != "default"
            return False
        finally:
            u.CloseDesktop(h)
    except Exception:
        return False


CAPABILITY_KEY =r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
# Teil des Registry-Schlüssels (klein geschrieben) → Anzeigename
CALL_APPS = (
    ("msteams", "Teams"), ("microsoft.teams", "Teams"), ("#teams.exe", "Teams"), ("ms-teams", "Teams"),
    ("zoom", "Zoom"), ("webex", "Webex"), ("ciscocollab", "Webex"), ("skype", "Skype"),
    ("discord", "Discord"), ("#slack.exe", "Slack"), ("com.squirrel.slack", "Slack"),
)


def _call_name(key: str) -> str | None:
    k = key.lower()
    for part, name in CALL_APPS:
        if part in k:
            return name
    return None


def call_app() -> str | None:
    """Name der Telefonie-App (Teams, Zoom …), die gerade Mikrofon oder Kamera benutzt – sonst None.
    Windows führt das unter HKCU …\\CapabilityAccessManager: LastUsedTimeStop == 0 heißt „gerade in Benutzung“."""
    if sys.platform != "win32":
        return None
    import winreg

    def scan(path: str) -> str | None:
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return None
        with k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    return None
                i += 1
                if sub == "NonPackaged":
                    hit = scan(path + "\\" + sub)
                    if hit:
                        return hit
                    continue
                name = _call_name(sub)
                if not name:
                    continue
                try:
                    with winreg.OpenKey(k, sub) as sk:
                        start = winreg.QueryValueEx(sk, "LastUsedTimeStart")[0]
                        stop = winreg.QueryValueEx(sk, "LastUsedTimeStop")[0]
                except OSError:
                    continue
                if start and stop == 0:
                    return name

    for cap in ("microphone", "webcam"):
        hit = scan(CAPABILITY_KEY + "\\" + cap)
        if hit:
            return hit
    return None


# ------------------------------------------------------------------ Fenster-Reihenfolge
_HWND_TOPMOST, _HWND_NOTOPMOST = -1, -2
_SWP_FLAGS = 0x0001 | 0x0002 | 0x0010   # NOSIZE | NOMOVE | NOACTIVATE
_GWL_EXSTYLE, _WS_EX_TOPMOST, _GW_HWNDNEXT = -20, 0x0008, 2


def _set_pos(hwnd: int, after: int) -> None:
    u = ctypes.windll.user32
    u.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(after), 0, 0, 0, 0, _SWP_FLAGS)


def _is_topmost(hwnd: int) -> bool:
    u = ctypes.windll.user32
    u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    return bool(u.GetWindowLongW(ctypes.c_void_p(hwnd), _GWL_EXSTYLE) & _WS_EX_TOPMOST)


def set_topmost(hwnd: int, on: bool) -> None:
    """Fenster in den „immer oben“-Bereich holen bzw. daraus entfernen – ohne es zu aktivieren."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        _set_pos(hwnd, _HWND_TOPMOST if on else _HWND_NOTOPMOST)
    except Exception:
        pass


def place_behind_foreground(hwnd: int) -> None:
    """Fenster direkt hinter das aktive Programm legen (z. B. Teams oder die geteilte Präsentation):
    sichtbar, wo Platz ist, aber nie darüber – und ohne Fokus zu stehlen."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        u = ctypes.windll.user32
        u.GetForegroundWindow.restype = ctypes.c_void_p
        u.GetWindow.restype = ctypes.c_void_p
        u.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        u.IsWindowVisible.argtypes = [ctypes.c_void_p]
        u.IsIconic.argtypes = [ctypes.c_void_p]
        _set_pos(hwnd, _HWND_NOTOPMOST)
        ref = u.GetForegroundWindow() or 0
        if ref == hwnd:
            ref = 0
        if ref and _is_topmost(ref):
            # Aktives Fenster ist selbst „immer oben“ → hinter das oberste normale Fenster legen
            h, ref = u.GetWindow(ctypes.c_void_p(ref), 0) or 0, 0   # GW_HWNDFIRST
            for _ in range(500):
                if not h:
                    break
                if h != hwnd and u.IsWindowVisible(ctypes.c_void_p(h)) and not u.IsIconic(ctypes.c_void_p(h)) \
                        and not _is_topmost(h):
                    ref = h
                    break
                h = u.GetWindow(ctypes.c_void_p(h), _GW_HWNDNEXT) or 0
        if ref:
            _set_pos(hwnd, ref)
    except Exception:
        pass


def autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" --tray'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    if pyw.exists():
        exe = pyw
    script = Path(__file__).resolve().parent.parent / "run.py"
    return f'"{exe}" "{script}" --tray'


def set_autostart(enabled: bool) -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def autostart_registered() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, RUN_VALUE)
            return bool(val)
    except OSError:
        return False


def autostart_points_here() -> bool:
    """True, wenn der Autostart-Eintrag auf diese .exe zeigt (z. B. nach Verschieben veraltet)."""
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, RUN_VALUE)
            return str(val).strip().lower() == autostart_command().strip().lower()
    except OSError:
        return False


def set_dark_titlebar(hwnd: int, dark: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (neu / alt)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd), attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


def set_app_user_model_id(app_id: str) -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass
