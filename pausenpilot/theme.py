"""Farbpaletten und Stylesheet (hell / dunkel)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication

DARK = {
    "bg": "#0F1115",
    "sidebar": "#14161C",
    "surface": "#1A1D25",
    "surface2": "#222631",
    "surface3": "#2A2F3C",
    "input": "#232733",
    "border": "#2A2E3A",
    "border_strong": "#3A4050",
    "text": "#ECEEF3",
    "muted": "#A3AABB",
    "faint": "#828A9D",
    "accent": "#5B7BF5",
    "accent_hover": "#6B89FA",
    "accent_text": "#FFFFFF",
    "success": "#3DD68C",
    "warn": "#F5A524",
    "danger": "#F2645F",
    "overlay_shadow": "#000000",
    "is_dark": True,
}

LIGHT = {
    "bg": "#F4F5F8",
    "sidebar": "#ECEEF3",
    "surface": "#FFFFFF",
    "surface2": "#F3F4F8",
    "surface3": "#E8EAF0",
    "input": "#FFFFFF",
    "border": "#E1E4EB",
    "border_strong": "#CDD2DC",
    "text": "#161922",
    "muted": "#4F5666",
    "faint": "#687083",
    "accent": "#3D5BD9",
    "accent_hover": "#3450C6",
    "accent_text": "#FFFFFF",
    "success": "#137A4B",
    "warn": "#A86400",
    "danger": "#C23B36",
    "overlay_shadow": "#1A2040",
    "is_dark": False,
}

P: dict = dict(DARK)   # aktuelle Palette (wird beim Theme-Wechsel ersetzt)


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return True


def resolve(mode: str) -> dict:
    if mode == "light":
        return LIGHT
    if mode == "dark":
        return DARK
    return DARK if system_is_dark() else LIGHT


def set_palette(pal: dict) -> None:
    P.clear()
    P.update(pal)


def c(key: str, alpha: float | None = None) -> QColor:
    col = QColor(P[key])
    if alpha is not None:
        col.setAlphaF(alpha)
    return col


def rgba(hex_color: str, alpha: float) -> str:
    q = QColor(hex_color)
    return f"rgba({q.red()},{q.green()},{q.blue()},{alpha:.3f})"


FONT = '"Segoe UI Variable Text", "Segoe UI", sans-serif'


def stylesheet() -> str:
    p = P
    return f"""
* {{
    font-family: {FONT};
    font-size: 10pt;
    color: {p['text']};
    outline: none;
}}
QMainWindow, QDialog, #page, QStackedWidget, QScrollArea, #scrollBody {{
    background: {p['bg']};
}}
QToolTip {{
    background: {p['surface3']};
    color: {p['text']};
    border: 1px solid {p['border_strong']};
    border-radius: 6px;
    padding: 5px 8px;
}}
#sidebar {{
    background: {p['sidebar']};
    border-right: 1px solid {p['border']};
}}
#brand {{ font-size: 13pt; font-weight: 600; }}
#brandSub {{ color: {p['faint']}; font-size: 8.5pt; }}
#navButton {{
    text-align: left;
    padding: 9px 12px;
    border: none;
    border-radius: 8px;
    background: transparent;
    color: {p['muted']};
    font-size: 10pt;
}}
#navButton:hover {{ background: {p['surface2']}; color: {p['text']}; }}
#navButton:checked {{
    background: {rgba(p['accent'], 0.16)};
    color: {p['text']};
    font-weight: 600;
}}
#statusPill {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 10px;
}}
#statusTitle {{ color: {p['faint']}; font-size: 8.5pt; }}
#statusText {{ font-weight: 600; }}

#h1 {{ font-size: 19pt; font-weight: 600; }}
#h2 {{ font-size: 12pt; font-weight: 600; }}
#h3 {{ font-size: 10.5pt; font-weight: 600; }}
#muted {{ color: {p['muted']}; }}
#faint {{ color: {p['faint']}; font-size: 9pt; }}
#warnText {{ color: {p['warn']}; }}
#dangerText {{ color: {p['danger']}; }}

#card {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 14px;
}}
#timerCard {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 14px;
}}
#timerCard:hover {{ border-color: {p['border_strong']}; }}
#statTile {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 12px;
}}
#statValue {{ font-size: 17pt; font-weight: 600; }}
#statLabel {{ color: {p['muted']}; font-size: 9pt; }}

QPushButton {{
    background: {p['surface2']};
    border: 1px solid {p['border']};
    border-radius: 9px;
    padding: 7px 14px;
    color: {p['text']};
}}
QPushButton:hover {{ background: {p['surface3']}; border-color: {p['border_strong']}; }}
QPushButton:pressed {{ background: {p['border']}; }}
QPushButton:disabled {{ color: {p['faint']}; background: {p['surface']}; }}
QPushButton#primary {{
    background: {p['accent']};
    border: 1px solid {p['accent']};
    color: {p['accent_text']};
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {p['accent_hover']}; border-color: {p['accent_hover']}; }}
QPushButton#primary:disabled {{ background: {p['surface3']}; border-color: {p['surface3']}; color: {p['faint']}; }}
QPushButton#ghost {{
    background: transparent;
    border: 1px solid transparent;
    color: {p['muted']};
}}
QPushButton#ghost:hover {{ background: {p['surface2']}; color: {p['text']}; }}
QPushButton#danger {{
    background: transparent;
    border: 1px solid {rgba(p['danger'], 0.45)};
    color: {p['danger']};
}}
QPushButton#danger:hover {{ background: {rgba(p['danger'], 0.12)}; }}
QPushButton#chip {{
    background: {p['surface2']};
    border: 1px solid {p['border']};
    border-radius: 13px;
    padding: 4px 11px;
    font-size: 9pt;
    color: {p['muted']};
}}
QPushButton#chip:hover {{ color: {p['text']}; border-color: {p['border_strong']}; }}
QPushButton#chip:checked {{
    background: {rgba(p['accent'], 0.18)};
    border-color: {rgba(p['accent'], 0.6)};
    color: {p['text']};
}}
QPushButton#iconButton {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 4px;
    font-size: 13pt;
    color: {p['muted']};
}}
QPushButton#iconButton:hover {{ background: {p['surface2']}; color: {p['text']}; }}
QPushButton#iconButton::menu-indicator {{ image: none; width: 0; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}

QLineEdit, QSpinBox, QTimeEdit, QComboBox {{
    background: {p['input']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 7px 12px;
    selection-background-color: {p['accent']};
    selection-color: {p['accent_text']};
    min-height: 20px;
}}
QLineEdit:hover, QSpinBox:hover, QTimeEdit:hover, QComboBox:hover {{ border-color: {p['border_strong']}; }}
QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus, QComboBox:focus {{ border-color: {p['accent']}; }}
QLineEdit:disabled, QSpinBox:disabled, QTimeEdit:disabled {{
    color: {p['faint']}; background: transparent; border-color: {p['border']};
}}
QSpinBox::up-button, QSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button {{
    width: 0; border: none;
}}
QToolButton#stepBtn {{
    background: {p['input']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 0;
}}
QToolButton#stepBtn:hover {{ border-color: {p['border_strong']}; background: {p['surface2']}; }}
QToolButton#stepBtn:pressed {{ border-color: {p['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: none; border: none; width: 0; }}
QComboBox QAbstractItemView {{
    background: {p['surface2']};
    border: 1px solid {p['border_strong']};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {rgba(p['accent'], 0.25)};
    selection-color: {p['text']};
}}

QMenu {{
    background: {p['surface2']};
    border: 1px solid {p['border_strong']};
    border-radius: 10px;
    padding: 5px;
}}
QMenu::item {{
    padding: 7px 26px 7px 12px;
    border-radius: 6px;
    background: transparent;
    color: {p['text']};
}}
QMenu::item:selected {{ background: {rgba(p['accent'], 0.22)}; }}
QMenu::item:disabled {{ color: {p['faint']}; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 5px 8px; }}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p['border_strong']}; border-radius: 3px; min-height: 30px; margin: 0 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {p['faint']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ height: 0; background: transparent; }}
QScrollBar:horizontal {{ height: 0; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {p['border_strong']}; background: {p['surface2']};
}}
QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}

QSlider::groove:horizontal {{
    height: 4px; border-radius: 2px; background: {p['surface3']};
}}
QSlider::sub-page:horizontal {{ background: {p['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 16px; height: 16px; margin: -6px 0; border-radius: 8px;
    background: #FFFFFF; border: 1px solid {p['border_strong']};
}}
QSlider::sub-page:horizontal:disabled {{ background: {p['border_strong']}; }}
QMessageBox {{ background: {p['bg']}; }}
QMessageBox QLabel {{ color: {p['text']}; }}

#alarmCard {{
    background: {p['surface']};
    border: 1px solid {p['border_strong']};
    border-radius: 20px;
}}
#compactCard {{
    background: {p['surface']};
    border: 1px solid {p['border_strong']};
    border-radius: 14px;
}}
#compactTitle {{ font-size: 10.5pt; font-weight: 600; }}
#compactSub {{ color: {p['muted']}; font-size: 8.8pt; }}
QPushButton#compactBtn, QPushButton#compactPrimary {{
    padding: 4px 10px; min-height: 18px; border-radius: 8px; font-size: 9pt;
}}
QPushButton#compactPrimary {{
    background: {p['accent']}; border: 1px solid {p['accent']}; color: {p['accent_text']}; font-weight: 600;
}}
QPushButton#compactPrimary:hover {{ background: {p['accent_hover']}; border-color: {p['accent_hover']}; }}
QPushButton#compactIcon {{ padding: 0; border-radius: 7px; }}
QPushButton#compactDone {{
    padding: 4px 10px; min-height: 18px; border-radius: 8px; font-size: 9pt; font-weight: 600;
    border: 1px solid {p['success']}; color: {p['success']}; background: {p['surface2']};
}}
QPushButton#compactDone:hover {{ background: {p['surface3']}; }}
#alarmTitle {{ font-size: 17pt; font-weight: 600; }}
#alarmDesc {{ color: {p['muted']}; font-size: 10.5pt; }}
#alarmMeta {{ color: {p['faint']}; font-size: 9pt; }}
#snoozeBadge {{
    background: {rgba(p['warn'], 0.14)};
    color: {p['warn']};
    border: 1px solid {rgba(p['warn'], 0.35)};
    border-radius: 10px;
    padding: 3px 10px;
    font-size: 9pt;
    font-weight: 600;
}}
#queueBadge {{
    background: {p['surface2']};
    color: {p['muted']};
    border-radius: 10px;
    padding: 3px 10px;
    font-size: 9pt;
}}
QPushButton#bigPrimary {{
    background: {p['accent']};
    border: none;
    color: {p['accent_text']};
    font-weight: 600;
    font-size: 11pt;
    border-radius: 12px;
    padding: 11px 18px;
}}
QPushButton#bigPrimary:hover {{ background: {p['accent_hover']}; }}
QPushButton#bigDone {{
    background: {p['surface2']};
    border: 1px solid {p['success']};
    color: {p['success']};
    font-weight: 600;
    font-size: 11pt;
    border-radius: 12px;
    padding: 10px 18px;
}}
QPushButton#bigDone:hover {{ background: {p['surface3']}; }}
QPushButton#snooze {{
    background: {p['surface2']};
    border: 1px solid {p['border_strong']};
    border-radius: 10px;
    padding: 8px 0;
    font-weight: 600;
}}
QPushButton#snooze:hover {{ border-color: {rgba(p['warn'], 0.6)}; background: {rgba(p['warn'], 0.10)}; }}
QPushButton#link {{
    background: transparent; border: none; color: {p['faint']}; padding: 4px 8px;
}}
QPushButton#link:hover {{ color: {p['text']}; }}

#dayDetailItem {{
    background: {p['surface2']};
    border-radius: 10px;
}}
#pill {{
    border-radius: 9px; padding: 2px 9px; font-size: 8.5pt; font-weight: 600;
}}
#sectionTitle {{ color: {p['faint']}; font-size: 8.5pt; font-weight: 600; letter-spacing: 0.6px; }}
#divider {{ background: {p['border']}; max-height: 1px; min-height: 1px; }}
#toast {{
    background: {p['surface3']};
    border: 1px solid {p['border_strong']};
    border-radius: 10px;
}}
"""
