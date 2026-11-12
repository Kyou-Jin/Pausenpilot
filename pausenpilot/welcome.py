"""Willkommens-Bildschirm: erscheint beim allerersten Start (und auf Wunsch in den Einstellungen)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import APP_NAME, APP_VERSION, theme
from .widgets import IconBubble, app_icon, label

FEATURES = (
    ("⏱", "#5B7CFA", "Bis zu 20 Erinnerungen",
     "Augen entspannen, Wasser trinken, aufstehen – mit eigenem Takt und eigener Startzeit."),
    ("🎬", "#F2A93B", "Erkennt Vollbild",
     "YouTube, Spiele oder Präsentation im Vollbild? Die Erinnerung wartet, bis du fertig bist."),
    ("📞", "#3FBF7F", "Erkennt Telefonate",
     "Bei Teams-, Zoom- oder Discord-Anrufen kommt sie leise – ohne Ton, ohne sich vorzudrängeln."),
    ("🔒", "#8A93A6", "Erkennt Sperre & Abwesenheit",
     "Win+L oder weg vom PC: nichts staut sich. Die Zeit steht im Kalender – ohne Minuspunkte."),
    ("🏅", "#C9A227", "Medaillen & Kalender",
     "Jeder Tag bekommt Bronze, Silber, Gold oder Platin – und du siehst, was du wann geschafft hast."),
    ("▣", "#9B7BFF", "Kompaktmodus",
     "Klein in der Ecke: zeigt nur, was als Nächstes kommt. Schaltet sich auf Wunsch selbst ein."),
)


class Hero(QWidget):
    """Farbverlauf-Banner mit Logo und Titel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor("#4F6EF7"))
        g.setColorAt(1, QColor("#9B7BFF"))
        path = QPainterPath()
        path.addRoundedRect(r, 16, 16)
        p.fillPath(path, g)
        # dezente Kreise als Deko
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawEllipse(QRectF(r.right() - 170, -60, 220, 220))
        p.setBrush(QColor(255, 255, 255, 14))
        p.drawEllipse(QRectF(r.right() - 290, 70, 160, 160))
        # Logo
        icon = app_icon().pixmap(QSize(64, 64))
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawRoundedRect(QRectF(28, 43, 64, 64), 18, 18)
        p.drawPixmap(28 + 6, 43 + 6, 52, 52, icon)
        # Texte
        p.setPen(QColor("#FFFFFF"))
        f = QFont(self.font())
        f.setPointSizeF(21)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.drawText(QRectF(112, 38, r.width() - 130, 40), Qt.AlignLeft | Qt.AlignVCenter, f"Willkommen bei {APP_NAME}")
        f.setPointSizeF(10.5)
        f.setWeight(QFont.Normal)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 225))
        p.drawText(QRectF(112, 78, r.width() - 130, 40), Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
                   "Dein Pausen-Coach für den Schreibtisch. Läuft unauffällig im Hintergrund "
                   "und meldet sich nur, wenn es passt.")
        p.end()


class FeatureTile(QFrame):
    def __init__(self, icon: str, color: str, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(12)
        h.addWidget(IconBubble(icon, color, 40), 0, Qt.AlignTop)
        v = QVBoxLayout()
        v.setSpacing(2)
        v.addWidget(label(title, "h3"))
        t = label(text, "muted", wrap=True)
        t.setMinimumWidth(220)
        v.addWidget(t)
        v.addStretch(1)
        h.addLayout(v, 1)


class WelcomeDialog(QDialog):
    def __init__(self, parent=None, dont_show: bool = False):
        super().__init__(parent)
        self.setWindowTitle(f"Willkommen bei {APP_NAME}")
        self.setWindowIcon(app_icon())
        self.setModal(True)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 18)
        root.setSpacing(16)
        root.addWidget(Hero())

        head = label("Das erledigt Pausenpilot automatisch für dich", "h2")
        root.addWidget(head)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for i, f in enumerate(FEATURES):
            grid.addWidget(FeatureTile(*f), i // 2, i % 2)
        root.addLayout(grid)

        foot = QHBoxLayout()
        foot.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(6)
        self.dont_show = QCheckBox("Beim nächsten Start nicht mehr anzeigen")
        self.dont_show.setCursor(Qt.PointingHandCursor)
        self.dont_show.setChecked(dont_show)
        self.dont_show.setToolTip("Den Überblick findest du jederzeit wieder unter Einstellungen.")
        left.addWidget(self.dont_show)
        info = QLabel(f"Portabel – keine Installation. Alles bleibt im Ordner „Pausenpilot-Daten“ "
                      f"neben der Exe.  ·  Version {APP_VERSION}")
        info.setObjectName("faint")
        info.setWordWrap(True)
        left.addWidget(info)
        foot.addLayout(left, 1)
        go = QPushButton("Los geht's")
        go.setObjectName("primary")
        go.setCursor(Qt.PointingHandCursor)
        go.setMinimumWidth(150)
        go.setMinimumHeight(38)
        go.setDefault(True)
        go.clicked.connect(self.accept)
        foot.addWidget(go)
        root.addLayout(foot)
        self.setMinimumWidth(820)
