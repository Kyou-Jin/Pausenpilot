"""Eigene Widgets: Schalter, Fortschrittsring, Icon-Blase, App-Icon."""
from __future__ import annotations

from PySide6.QtCore import (Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
                            Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QImage)
from PySide6.QtWidgets import QAbstractButton, QLabel, QSizePolicy, QWidget, QFrame

from . import theme

EMOJI_FONT = "Segoe UI Emoji"


class ToggleSwitch(QAbstractButton):
    """Animierter An/Aus-Schalter im modernen Stil."""

    def __init__(self, parent=None, checked: bool = False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setCheckedSilent(self, on: bool):
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._pos = 1.0 if on else 0.0
        self.update()

    def get_knob(self):
        return self._pos

    def set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def sizeHint(self):
        return QSize(42, 24)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        off = theme.c("surface3")
        on = theme.c("accent")
        t = self._pos
        track = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            track.setAlphaF(0.45)
        p.setPen(QPen(theme.c("border_strong") if t < 0.5 else track, 1))
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * t
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))
        p.end()


class ProgressRing(QWidget):
    """Kreisförmiger Fortschritt mit Text in der Mitte."""

    def __init__(self, size: int = 56, thickness: float = 5.0, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._color = QColor(theme.P["accent"])
        self._text = ""
        self._sub = ""
        self._thick = thickness
        self._big = False
        self._icon = ""
        self.setFixedSize(size, size)

    def setIcon(self, name: str):
        """Statt Text ein Linien-Icon in der Mitte zeichnen (z. B. 'pause'); '' = Text."""
        if name != self._icon:
            self._icon = name
            self.update()

    def setBig(self, big: bool):
        self._big = big

    def setColor(self, col: str | QColor):
        self._color = QColor(col)
        self.update()

    def setValue(self, v: float):
        v = max(0.0, min(1.0, v))
        if abs(v - self._value) > 0.0005:
            self._value = v
            self.update()

    def setText(self, text: str, sub: str = ""):
        if text != self._text or sub != self._sub:
            self._text, self._sub = text, sub
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = self._thick / 2 + 1
        r = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        track = QColor(self._color)
        track.setAlphaF(0.22 if theme.P.get("is_dark") else 0.28)
        pen = QPen(track, self._thick)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(r, 0, 360 * 16)
        if self._value >= 0.004:
            pen.setColor(self._color)
            p.setPen(pen)
            p.drawArc(r, 90 * 16, -int(self._value * 360 * 16))
        if self._icon:
            s = min(r.width(), r.height()) * 0.36
            paint_line_icon(p, self._icon, QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s),
                            theme.c("muted"), 1.6)
            p.end()
            return
        p.setPen(theme.c("text"))
        f = QFont(self.font())
        if self._big:
            f.setPointSizeF(30)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            tr = QRectF(r)
            if self._sub:
                tr.translate(0, -8)
            p.drawText(tr, Qt.AlignCenter, self._text)
            if self._sub:
                f2 = QFont(self.font())
                f2.setPointSizeF(9.5)
                p.setFont(f2)
                p.setPen(theme.c("muted"))
                p.drawText(QRectF(r.left(), r.center().y() + 22, r.width(), 20), Qt.AlignHCenter | Qt.AlignTop,
                           self._sub)
        else:
            f.setPointSizeF(8.5 if len(self._text) <= 5 else 7.5)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            p.drawText(r, Qt.AlignCenter, self._text)
        p.end()


class IconBubble(QWidget):
    """Emoji in einem farbigen, abgerundeten Quadrat."""

    def __init__(self, icon: str, color: str, size: int = 44, parent=None):
        super().__init__(parent)
        self._icon, self._color = icon, color
        self._dim = False
        self.setFixedSize(size, size)

    def set(self, icon: str, color: str):
        self._icon, self._color = icon, color
        self.update()

    def setDim(self, dim: bool):
        self._dim = dim
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        col = QColor(self._color)
        col.setAlphaF(0.10 if self._dim else 0.20)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        r = QRectF(0, 0, self.width(), self.height())
        p.drawRoundedRect(r, self.width() * 0.3, self.width() * 0.3)
        if self._dim:
            p.setOpacity(0.45)
        f = QFont(EMOJI_FONT)
        f.setPixelSize(int(self.height() * 0.56))
        p.setFont(f)
        p.setPen(theme.c("text"))
        p.drawText(r, Qt.AlignCenter, self._icon)
        p.end()


class Dot(QWidget):
    def __init__(self, color: str, size: int = 8, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._color))
        p.drawEllipse(self.rect())
        p.end()


def label(text: str = "", obj: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    if wrap:
        lb.setWordWrap(True)
    return lb


def divider() -> QFrame:
    f = QFrame()
    f.setObjectName("divider")
    f.setFrameShape(QFrame.NoFrame)
    return f


# --------------------------------------------------------------------------- Linien-Icons

def paint_line_icon(p: QPainter, name: str, r: QRectF, color: QColor, width: float):
    pen = QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    cx, cy = r.center().x(), r.center().y()
    if name == "clock":
        p.drawEllipse(r.adjusted(w * .08, h * .08, -w * .08, -h * .08))
        p.drawLine(QPointF(cx, cy), QPointF(cx, y + h * .28))
        p.drawLine(QPointF(cx, cy), QPointF(x + w * .68, y + h * .6))
    elif name == "calendar":
        box = QRectF(x + w * .1, y + h * .18, w * .8, h * .72)
        p.drawRoundedRect(box, w * .12, w * .12)
        p.drawLine(QPointF(box.left(), y + h * .42), QPointF(box.right(), y + h * .42))
        p.drawLine(QPointF(x + w * .34, y + h * .08), QPointF(x + w * .34, y + h * .28))
        p.drawLine(QPointF(x + w * .66, y + h * .08), QPointF(x + w * .66, y + h * .28))
    elif name == "refresh":
        arc = r.adjusted(w * .14, h * .14, -w * .14, -h * .14)
        p.drawArc(arc, 60 * 16, 270 * 16)
        # Pfeilspitze am Ende des Bogens (oben rechts)
        import math
        a = math.radians(60)
        ex = arc.center().x() + arc.width() / 2 * math.cos(a)
        ey = arc.center().y() - arc.height() / 2 * math.sin(a)
        s = w * .2
        p.drawLine(QPointF(ex, ey), QPointF(ex - s * 1.05, ey - s * .15))
        p.drawLine(QPointF(ex, ey), QPointF(ex + s * .2, ey - s * 1.0))
    elif name == "sliders":
        for i, kx in enumerate((.32, .68, .45)):
            yy = y + h * (.22 + .28 * i)
            p.drawLine(QPointF(x + w * .1, yy), QPointF(x + w * .9, yy))
            rr = w * .09
            p.setBrush(color)
            p.drawEllipse(QPointF(x + w * kx, yy), rr, rr)
            p.setBrush(Qt.NoBrush)
    elif name == "pause":
        bw = w * .14
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(cx - bw * 1.7, y + h * .2, bw * 1.2, h * .6), bw * .5, bw * .5)
        p.drawRoundedRect(QRectF(cx + bw * .5, y + h * .2, bw * 1.2, h * .6), bw * .5, bw * .5)
    elif name == "play":
        path = QPainterPath()
        path.moveTo(x + w * .32, y + h * .2)
        path.lineTo(x + w * .78, cy)
        path.lineTo(x + w * .32, y + h * .8)
        path.closeSubpath()
        p.setBrush(color)
        p.drawPath(path)
    elif name == "plus":
        p.drawLine(QPointF(cx, y + h * .2), QPointF(cx, y + h * .8))
        p.drawLine(QPointF(x + w * .2, cy), QPointF(x + w * .8, cy))
    elif name == "more":
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        rr = w * .085
        for k in (-1, 0, 1):
            p.drawEllipse(QPointF(cx, cy + k * h * .26), rr, rr)
    elif name in ("down", "up"):
        d = 1 if name == "down" else -1
        p.drawLine(QPointF(x + w * .25, cy - d * h * .12), QPointF(cx, cy + d * h * .12))
        p.drawLine(QPointF(cx, cy + d * h * .12), QPointF(x + w * .75, cy - d * h * .12))
    elif name in ("expand", "compact"):
        # zwei diagonale Pfeile: nach außen (expand) bzw. nach innen (compact)
        a, b = (.18, .44) if name == "expand" else (.44, .18)
        for sx, sy in ((-1, -1), (1, 1)):
            tip = QPointF(cx + sx * w * (.5 - a), cy + sy * h * (.5 - a))
            base = QPointF(cx + sx * w * (.5 - b), cy + sy * h * (.5 - b))
            p.drawLine(base, tip)
            k = w * .16 * (1 if name == "expand" else -1)
            p.drawLine(tip, QPointF(tip.x() - sx * k, tip.y()))
            p.drawLine(tip, QPointF(tip.x(), tip.y() - sy * k))
    elif name == "stop":
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(r.adjusted(w * .24, h * .24, -w * .24, -h * .24), w * .08, w * .08)
    elif name in ("left", "right"):
        d = -1 if name == "left" else 1
        p.drawLine(QPointF(cx - d * w * .12, y + h * .25), QPointF(cx + d * w * .14, cy))
        p.drawLine(QPointF(cx + d * w * .14, cy), QPointF(cx - d * w * .12, y + h * .75))
    elif name == "check":
        p.drawLine(QPointF(x + w * .2, y + h * .52), QPointF(x + w * .42, y + h * .74))
        p.drawLine(QPointF(x + w * .42, y + h * .74), QPointF(x + w * .82, y + h * .3))
    elif name == "moon":
        path = QPainterPath()
        path.addEllipse(r.adjusted(w * .12, h * .12, -w * .12, -h * .12))
        cut = QPainterPath()
        cut.addEllipse(QRectF(x + w * .36, y + h * .02, w * .64, h * .64))
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPath(path.subtracted(cut))


def line_icon(name: str, color: str | QColor, size: int = 18, width: float | None = None) -> QIcon:
    ic = QIcon()
    for scale in (1, 2):
        px = QPixmap(size * scale, size * scale)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        paint_line_icon(p, name, QRectF(0, 0, size * scale, size * scale), QColor(color),
                        (width or max(1.4, size / 11)) * scale)
        p.end()
        px.setDevicePixelRatio(scale)
        ic.addPixmap(px)
    return ic


class LineIcon(QWidget):
    def __init__(self, name: str, color_key: str = "muted", size: int = 18, parent=None):
        super().__init__(parent)
        self.name, self.color_key = name, color_key
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_line_icon(p, self.name, QRectF(self.rect()), theme.c(self.color_key), max(1.4, self.width() / 11))
        p.end()


# --------------------------------------------------------------------------- App-Icon

def paint_app_icon(size: int, paused: bool = False) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)
    r = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    if paused:
        g.setColorAt(0, QColor("#8A90A0"))
        g.setColorAt(1, QColor("#5C6273"))
    else:
        g.setColorAt(0, QColor("#7C9BFF"))
        g.setColorAt(1, QColor("#4F5FE8"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(r, s * 0.24, s * 0.24)
    # Ring
    c = r.center()
    rad = s * 0.27
    pen = QPen(QColor(255, 255, 255, 235), max(1.5, s * 0.075))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    ring = QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad)
    p.drawArc(ring, 90 * 16, -290 * 16)
    if paused:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 235))
        bw, bh = s * 0.07, s * 0.2
        p.drawRoundedRect(QRectF(c.x() - bw * 1.6, c.y() - bh / 2, bw, bh), bw / 2, bw / 2)
        p.drawRoundedRect(QRectF(c.x() + bw * 0.6, c.y() - bh / 2, bw, bh), bw / 2, bw / 2)
    else:
        # Zeiger
        path = QPainterPath()
        path.moveTo(c)
        path.lineTo(QPointF(c.x(), c.y() - rad * 0.62))
        path.moveTo(c)
        path.lineTo(QPointF(c.x() + rad * 0.48, c.y() + rad * 0.12))
        pen2 = QPen(QColor(255, 255, 255, 245), max(1.5, s * 0.07))
        pen2.setCapStyle(Qt.RoundCap)
        p.setPen(pen2)
        p.drawPath(path)
        # Punkt am Ende des Rings
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FFD27A"))
        dd = s * 0.11
        p.drawEllipse(QRectF(c.x() - dd / 2, c.y() - rad - dd / 2, dd, dd))
    p.end()
    return img


def app_icon(paused: bool = False) -> QIcon:
    ic = QIcon()
    for sz in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        ic.addPixmap(QPixmap.fromImage(paint_app_icon(sz, paused)))
    return ic


# --------------------------------------------------------------------------- Medaillen
MEDAL_COLORS = {                 # (hell, dunkel, Band)
    "bronze": ("#E8A26A", "#A35A28", "#C2410C"),
    "silver": ("#F1F4F8", "#8D97A6", "#475569"),
    "gold": ("#FFE27A", "#C9951C", "#B91C1C"),
    "platinum": ("#E9FBFF", "#7FB6D6", "#6D28D9"),
}


def paint_medal(p: QPainter, r: QRectF, key: str):
    """Medaille (Bronze/Silber/Gold/Platin) oder Daumen runter in das Rechteck r zeichnen."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    s = min(r.width(), r.height())
    x0, y0 = r.center().x() - s / 2, r.center().y() - s / 2
    if key == "thumb":
        f = QFont(EMOJI_FONT)
        f.setPixelSize(max(8, int(s * 0.82)))
        p.setFont(f)
        p.setPen(QColor("#000000"))
        p.drawText(QRectF(x0, y0, s, s), Qt.AlignCenter, "👎")
        p.restore()
        return
    light, dark, band = (QColor(c) for c in MEDAL_COLORS.get(key, MEDAL_COLORS["gold"]))
    # Band (zwei Schrägen)
    p.setPen(Qt.NoPen)
    cx = r.center().x()
    for d in (-1, 1):   # links / rechts gespiegelt
        path = QPainterPath()
        path.moveTo(cx + d * s * 0.34, y0)
        path.lineTo(cx + d * s * 0.12, y0)
        path.lineTo(cx - d * s * 0.10, y0 + s * 0.52)
        path.lineTo(cx + d * s * 0.12, y0 + s * 0.52)
        path.closeSubpath()
        p.setBrush(band if d < 0 else band.darker(118))
        p.drawPath(path)
    # Scheibe
    cr = s * 0.33
    c = QPointF(r.center().x(), y0 + s - cr - s * 0.02)
    g = QLinearGradient(c.x() - cr, c.y() - cr, c.x() + cr, c.y() + cr)
    g.setColorAt(0, light)
    g.setColorAt(1, dark)
    p.setBrush(QBrush(g))
    p.setPen(QPen(dark.darker(125), max(1.0, s * 0.045)))
    p.drawEllipse(c, cr, cr)
    # Stern
    star = QPainterPath()
    import math
    ro, ri = cr * 0.55, cr * 0.24
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = ro if i % 2 == 0 else ri
        pt = QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a))
        star.moveTo(pt) if i == 0 else star.lineTo(pt)
    star.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 215) if key != "silver" else QColor(255, 255, 255, 240))
    p.drawPath(star)
    p.restore()


class MedalIcon(QWidget):
    def __init__(self, size: int = 22, parent=None):
        super().__init__(parent)
        self.key: str | None = None
        self.setFixedSize(size, size)

    def set(self, key: str | None):
        if key != self.key:
            self.key = key
            self.setVisible(key is not None)
            self.update()

    def paintEvent(self, _):
        if self.key:
            p = QPainter(self)
            paint_medal(p, QRectF(self.rect()), self.key)
            p.end()
