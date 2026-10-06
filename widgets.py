"""
Custom-painted components for the Cayde 420 theme.

QSS can't express texture, glow, or physical controls, so anything with depth
gets painted here with QPainter.

Nothing in this file depends on the backend — these are pure view components.
"""

import math
import random

from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPixmap, QRadialGradient, QLinearGradient,
    QPainterPath, QFont,
)
from PySide6.QtWidgets import QWidget, QLabel, QFrame, QHBoxLayout, QVBoxLayout, QGraphicsDropShadowEffect

from styles import COLORS


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _c(key: str, alpha: int = 255) -> QColor:
    col = QColor(COLORS[key])
    col.setAlpha(alpha)
    return col


def apply_glow(widget: QWidget, color_key: str = "ember", radius: int = 18, alpha: int = 140):
    """Attach an outer glow. Qt implements this as a drop shadow with no offset."""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(radius)
    eff.setOffset(0, 0)
    eff.setColor(_c(color_key, alpha))
    widget.setGraphicsEffect(eff)
    return eff


# ─── Cracked / weathered backdrop ─────────────────────────────────────────────

class CrackedBackdrop(QWidget):
    """
    Full-window background: gunmetal field, vignette, and a network of panel
    seams with visor-orange light behind them. Rendered once into a cached
    pixmap and only regenerated on resize.
    """

    def __init__(self, parent=None, seed: int = 7, density: int = 16):
        super().__init__(parent)
        self._cache: QPixmap | None = None
        self._seed = seed
        self._density = density
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.lower()

    def resizeEvent(self, event):
        self._cache = None
        super().resizeEvent(event)

    def paintEvent(self, event):
        if self._cache is None or self._cache.size() != self.size():
            self._cache = self._render()
        QPainter(self).drawPixmap(0, 0, self._cache)

    # ── generation ──

    def _render(self) -> QPixmap:
        w, h = max(self.width(), 1), max(self.height(), 1)
        pm = QPixmap(w, h)
        pm.fill(_c("bg"))

        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)

        self._paint_field(p, w, h)
        self._paint_cracks(p, w, h)
        self._paint_vignette(p, w, h)

        p.end()
        return pm

    def _paint_field(self, p: QPainter, w: int, h: int):
        """Mottled gunmetal base with a couple of pools of visor light."""
        g = QLinearGradient(0, 0, w * 0.4, h)
        g.setColorAt(0.0, _c("bg_raised"))
        g.setColorAt(0.55, _c("bg"))
        g.setColorAt(1.0, _c("bg_deep"))
        p.fillRect(0, 0, w, h, QBrush(g))

        rng = random.Random(self._seed + 991)
        p.setPen(Qt.NoPen)
        for _ in range(5):
            cx, cy = rng.uniform(0, w), rng.uniform(0, h)
            rad = rng.uniform(min(w, h) * 0.25, min(w, h) * 0.6)
            rg = QRadialGradient(cx, cy, rad)
            rg.setColorAt(0.0, _c("bg_raised", 120))
            rg.setColorAt(1.0, _c("bg_raised", 0))
            p.setBrush(QBrush(rg))
            p.drawEllipse(QPointF(cx, cy), rad, rad)

    def _paint_cracks(self, p: QPainter, w: int, h: int):
        rng = random.Random(self._seed)
        for _ in range(self._density):
            x, y = rng.uniform(0, w), rng.uniform(0, h)
            ang = rng.uniform(0, math.tau)
            self._crack(p, rng, x, y, ang, length=rng.uniform(60, 190), width=rng.uniform(1.6, 3.0), depth=0)

    def _crack(self, p: QPainter, rng, x, y, ang, length, width, depth):
        """One branching fissure, drawn glow-first then hot core."""
        if depth > 3 or length < 9 or width < 0.35:
            return

        path = QPainterPath(QPointF(x, y))
        cx, cy, ca = x, y, ang
        steps = max(int(length / 11), 2)
        seg = length / steps
        for _ in range(steps):
            # slight wander only — seams are gaps between panels, not roots
            ca += rng.uniform(-0.16, 0.16)
            cx += math.cos(ca) * seg
            cy += math.sin(ca) * seg
            path.lineTo(cx, cy)

        # pass 1 — wide ember bleed
        p.setPen(QPen(_c("ember", 12), width * 5.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        # pass 2 — the seam itself, barely lit
        p.setPen(QPen(_c("ember", 46), width * 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        # pass 3 — a hairline of hot core, only on the widest seams
        if width > 2.0:
            p.setPen(QPen(_c("a_bright", 34), max(width * 0.35, 0.5), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)

        # branch
        for _ in range(rng.randint(1, 2)):
            if rng.random() < 0.72:
                self._crack(
                    p, rng, cx, cy,
                    ca + rng.choice([-1, 1]) * rng.uniform(0.45, 1.15),
                    length * rng.uniform(0.4, 0.62),
                    width * 0.6,
                    depth + 1,
                )

    def _paint_vignette(self, p: QPainter, w: int, h: int):
        rg = QRadialGradient(w / 2, h / 2, max(w, h) * 0.78)
        rg.setColorAt(0.0, QColor(0, 0, 0, 0))
        rg.setColorAt(0.62, QColor(0, 0, 0, 26))
        rg.setColorAt(1.0, QColor(0, 0, 0, 104))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(rg))
        p.drawRect(0, 0, w, h)


# ─── Scanlines ────────────────────────────────────────────────────────────────

class ScanlineOverlay(QWidget):
    """Horizontal CRT scanlines. Sits above everything, eats no mouse events."""

    def __init__(self, parent=None, spacing: int = 3, alpha: int = 26):
        super().__init__(parent)
        self._spacing = spacing
        self._alpha = alpha
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QPen(QColor(0, 0, 0, self._alpha), 1))
        for y in range(0, self.height(), self._spacing):
            p.drawLine(0, y, self.width(), y)


# ─── LED indicator ────────────────────────────────────────────────────────────

class LEDDot(QWidget):
    """
    A small glowing lamp. `state` is one of: green | amber | red | off.
    Live states breathe; off is flat.
    """

    _MAP = {
        "green": ("led_green", "led_green_dim"),
        "amber": ("led_amber", "led_amber_dim"),
        "red":   ("led_red",   "led_red_dim"),
        "off":   ("a_dim",     "bg_inset"),
    }

    def __init__(self, state: str = "off", diameter: int = 10, parent=None):
        super().__init__(parent)
        self._state = state
        self._d = diameter
        self._pulse = 1.0
        self.setFixedSize(diameter + 8, diameter + 8)

        self._anim = QPropertyAnimation(self, b"pulse", self)
        self._anim.setDuration(1600)
        self._anim.setStartValue(0.55)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)
        self._anim.setLoopCount(-1)
        self._sync_anim()

    # Qt can only animate registered properties — hence this declaration.
    def _get_pulse(self) -> float:
        return self._pulse

    def _set_pulse(self, v: float):
        self._pulse = v
        self.update()

    pulse = Property(float, _get_pulse, _set_pulse)

    def set_state(self, state: str):
        if state == self._state:
            return
        self._state = state
        self._sync_anim()
        self.update()

    def _sync_anim(self):
        if self._state == "off":
            self._anim.stop()
            self._pulse = 1.0
        elif self._anim.state() != QPropertyAnimation.Running:
            self._anim.start()

    def paintEvent(self, event):
        hot_key, dim_key = self._MAP.get(self._state, self._MAP["off"])
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        cx, cy = self.width() / 2, self.height() / 2
        r = self._d / 2

        if self._state != "off":
            halo = QRadialGradient(cx, cy, r * 3.1)
            halo.setColorAt(0.0, _c(hot_key, int(120 * self._pulse)))
            halo.setColorAt(1.0, _c(hot_key, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(halo))
            p.drawEllipse(QPointF(cx, cy), r * 3.1, r * 3.1)

        body = QRadialGradient(cx - r * 0.3, cy - r * 0.3, r * 1.9)
        body.setColorAt(0.0, _c(hot_key, int(255 * self._pulse)))
        body.setColorAt(1.0, _c(dim_key))
        p.setBrush(QBrush(body))
        p.setPen(QPen(_c(dim_key), 1))
        p.drawEllipse(QPointF(cx, cy), r, r)


# ─── Rotary knob (decorative) ─────────────────────────────────────────────────

class Knob(QWidget):
    """
    A physical-looking rotary control. Decorative by default; pass a callback
    to `on_change` to make it drive something.
    """

    def __init__(self, label: str = "", value: float = 0.5, diameter: int = 26,
                 on_change=None, parent=None):
        super().__init__(parent)
        self._value = max(0.0, min(1.0, value))
        self._label = label
        self._d = diameter
        self._on_change = on_change
        self._dragging = False
        self.setFixedSize(diameter + 10, diameter + (20 if label else 10))
        self.setCursor(Qt.PointingHandCursor if on_change else Qt.ArrowCursor)

    def value(self) -> float:
        return self._value

    def set_value(self, v: float):
        self._value = max(0.0, min(1.0, v))
        self.update()
        if self._on_change:
            self._on_change(self._value)

    def mousePressEvent(self, e):
        if self._on_change:
            self._dragging = True

    def mouseReleaseEvent(self, e):
        self._dragging = False

    def mouseMoveEvent(self, e):
        if self._dragging:
            # vertical drag = value; 120px of travel covers the full range
            delta = -e.position().y() / 120.0
            self.set_value(self._value + delta * 0.08)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        cx = self.width() / 2
        cy = self._d / 2 + 4
        r = self._d / 2

        # bezel
        bez = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
        bez.setColorAt(0.0, _c("border_warm"))
        bez.setColorAt(1.0, _c("bg_deep"))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(bez))
        p.drawEllipse(QPointF(cx, cy), r, r)

        # face
        face = QRadialGradient(cx - r * 0.35, cy - r * 0.35, r * 1.7)
        face.setColorAt(0.0, _c("bg_raised"))
        face.setColorAt(1.0, _c("bg_deep"))
        p.setBrush(QBrush(face))
        p.drawEllipse(QPointF(cx, cy), r * 0.78, r * 0.78)

        # pointer — sweeps 270° with a gap at the bottom
        ang = math.radians(135 + self._value * 270)
        p.setPen(QPen(_c("a_hot"), 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(
            QPointF(cx + math.cos(ang) * r * 0.28, cy + math.sin(ang) * r * 0.28),
            QPointF(cx + math.cos(ang) * r * 0.68, cy + math.sin(ang) * r * 0.68),
        )

        # tick marks
        p.setPen(QPen(_c("a_dim"), 1))
        for i in range(9):
            a = math.radians(135 + (i / 8) * 270)
            p.drawLine(
                QPointF(cx + math.cos(a) * r * 0.88, cy + math.sin(a) * r * 0.88),
                QPointF(cx + math.cos(a) * r * 1.0,  cy + math.sin(a) * r * 1.0),
            )

        if self._label:
            f = QFont("Consolas", 6)
            p.setFont(f)
            p.setPen(QPen(_c("a_dim")))
            p.drawText(QRectF(0, self._d + 5, self.width(), 12),
                       Qt.AlignHCenter | Qt.AlignTop, self._label)


# ─── Signal meter (the little bar readout) ────────────────────────────────────

class BarMeter(QWidget):
    """Segmented level readout — used for tok/s. `level` is 0.0–1.0.

    The ramp runs bone → visor orange, so a hot meter reads as load rather
    than as an error. Status LEDs are the only place green is allowed.
    """

    def __init__(self, segments: int = 12, parent=None):
        super().__init__(parent)
        self._segments = segments
        self._level = 0.0
        self.setFixedSize(segments * 5, 16)

    def set_level(self, level: float):
        self._level = max(0.0, min(1.0, level))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        lit = int(self._level * self._segments)
        hot_at = self._segments * 0.7
        for i in range(self._segments):
            x = i * 5
            if i < lit:
                col = _c("a_bright") if i < hot_at else _c("ember")
            else:
                col = _c("a_dim", 90)
            p.fillRect(x, 3, 3, self.height() - 6, col)


# ─── Original mascot ──────────────────────────────────────────────────────────

class MascotGlyph(QWidget):
    """
    An angular exo-visor glyph for the welcome screen — a bone plate silhouette
    with one lit horizontal visor. Drawn from scratch out of straight lines;
    deliberately not a likeness of any existing character.
    """

    def __init__(self, size: int = 92, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._s = size

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        s = self._s
        u = s / 100.0  # unit scale so the drawing is resolution independent

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_c("a_mid"), 2.0 * u, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

        # cranium — a flattened hexagon, wider at the temples
        skull = QPainterPath(QPointF(50 * u, 14 * u))
        skull.lineTo(74 * u, 26 * u)
        skull.lineTo(78 * u, 46 * u)
        skull.lineTo(66 * u, 64 * u)
        skull.lineTo(50 * u, 72 * u)
        skull.lineTo(34 * u, 64 * u)
        skull.lineTo(22 * u, 46 * u)
        skull.lineTo(26 * u, 26 * u)
        skull.closeSubpath()
        p.drawPath(skull)

        # cheek seams
        p.setPen(QPen(_c("border_warm"), 1.4 * u, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(30 * u, 40 * u), QPointF(40 * u, 58 * u))
        p.drawLine(QPointF(70 * u, 40 * u), QPointF(60 * u, 58 * u))

        # visor — the one lit element
        visor = QPainterPath(QPointF(28 * u, 40 * u))
        visor.lineTo(72 * u, 40 * u)
        visor.lineTo(68 * u, 51 * u)
        visor.lineTo(32 * u, 51 * u)
        visor.closeSubpath()
        p.setPen(QPen(_c("ember"), 1.6 * u, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(QBrush(_c("ember", 46)))
        p.drawPath(visor)

        # brow ridge over the visor
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_c("a_bright"), 1.8 * u, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(25 * u, 36 * u), QPointF(75 * u, 36 * u))

        # mandible and neck
        p.setPen(QPen(_c("a_mid"), 2.0 * u, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(44 * u, 66 * u), QPointF(44 * u, 84 * u))
        p.drawLine(QPointF(56 * u, 66 * u), QPointF(56 * u, 84 * u))
        p.drawLine(QPointF(38 * u, 86 * u), QPointF(62 * u, 86 * u))


# ─── Bottom hardware console ──────────────────────────────────────────────────

class HardwareStrip(QFrame):
    """
    Decorative instrument cluster for the bottom-right of the status bar:
    a row of labelled LEDs, a few knobs, and a small readout plate.

    Purely cosmetic — it sells the "physical device" feel without pretending to
    control anything.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hardwareStrip")
        self.setFixedHeight(34)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 2, 10, 2)
        lay.setSpacing(11)

        self._leds: list[LEDDot] = []
        for caption in ("PWR", "I/O", "GPU"):
            lay.addWidget(self._lamp(caption))

        for caption in ("VOL", "CTR", "TMP"):
            lay.addWidget(Knob(caption, value=0.6, diameter=20))

        # readout plate
        plate = QLabel("RDY")
        plate.setAlignment(Qt.AlignCenter)
        plate.setFixedSize(34, 20)
        plate.setStyleSheet(
            f"background-color: {COLORS['bg_deep']};"
            f" color: {COLORS['ember']};"
            f" border: 1px solid {COLORS['border_warm']};"
            f" border-radius: 2px;"
            f" font-size: 10px; font-weight: 700;"
        )
        self.plate = plate
        lay.addWidget(plate)

    def _lamp(self, caption: str) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.setAlignment(Qt.AlignCenter)

        led = LEDDot("off", diameter=8)
        self._leds.append(led)
        v.addWidget(led, alignment=Qt.AlignHCenter)

        lbl = QLabel(caption)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color: {COLORS['a_dim']}; font-size: 7px; letter-spacing: 1px;")
        v.addWidget(lbl)
        return box

    def set_lamps(self, power: str, io: str, gpu: str):
        """Set the three lamp states: green | amber | red | off."""
        for led, state in zip(self._leds, (power, io, gpu)):
            led.set_state(state)

    def set_plate(self, text: str):
        self.plate.setText(text[:4])
