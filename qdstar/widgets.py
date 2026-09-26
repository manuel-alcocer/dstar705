"""Custom widgets: status LEDs and the 4:3 reflector screen."""

import time
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QGuiApplication, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .civ import compass_point
from .i18n import tr

FONTS_DIR = Path(__file__).with_name("fonts")
_fonts_loaded = False


def load_fonts():
    """Bundle the screen font, so the display looks the same on every OS.
    Without a windowing system (offscreen) Qt has no fonts at all: use it for the whole UI too."""
    global _fonts_loaded
    if _fonts_loaded:
        return
    _fonts_loaded = True
    for ttf in sorted(FONTS_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(ttf))
    if QGuiApplication.platformName() == "offscreen":
        QGuiApplication.setFont(QFont("DejaVu Sans", 9))


LED_COLORS = {
    "off": QColor("#3a3a3a"),
    "green": QColor("#2ee66b"),
    "amber": QColor("#ffb020"),
    "red": QColor("#ff3b30"),
    "blue": QColor("#3fa9ff"),
}


class Led(QWidget):
    """Round LED with a short caption underneath."""

    def __init__(self, caption, tooltip="", parent=None):
        super().__init__(parent)
        self.color = "off"
        self.blink = False
        self._blink_on = True
        self.dot = _LedDot(self)
        self.label = QLabel(caption)
        self.label.setAlignment(Qt.AlignCenter)
        font = self.label.font()
        font.setPointSizeF(font.pointSizeF() * 0.8)
        self.label.setFont(font)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        layout.addWidget(self.dot, 0, Qt.AlignHCenter)
        layout.addWidget(self.label)
        self.setToolTip(tooltip)
        self.timer = QTimer(self, interval=450)
        self.timer.timeout.connect(self._toggle)

    def set(self, color, blink=False):
        self.color = color
        self.blink = blink
        if blink and not self.timer.isActive():
            self.timer.start()
        elif not blink:
            self.timer.stop()
            self._blink_on = True
        self.dot.update()

    def _toggle(self):
        self._blink_on = not self._blink_on
        self.dot.update()

    def current_color(self):
        if self.blink and not self._blink_on:
            return LED_COLORS["off"]
        return LED_COLORS[self.color]


class _LedDot(QWidget):
    def __init__(self, led):
        super().__init__(led)
        self.led = led
        self.setFixedSize(18, 18)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = self.led.current_color()
        rect = QRectF(2, 2, 14, 14)
        grad = QRadialGradient(rect.center().x() - 2, rect.center().y() - 2, 9)
        grad.setColorAt(0, color.lighter(170) if self.led.color != "off" else color.lighter(130))
        grad.setColorAt(1, color)
        p.setBrush(grad)
        p.setPen(QPen(QColor("#111"), 1))
        p.drawEllipse(rect)
        if self.led.color != "off" and self.led.current_color() != LED_COLORS["off"]:
            glow = QColor(color)
            glow.setAlpha(70)
            p.setPen(QPen(glow, 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(0.5, 0.5, 17, 17))


class LedBar(QWidget):
    def __init__(self, leds, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self.leds = {}
        for key, caption, tip in leds:
            led = Led(caption, tip)
            self.leds[key] = led
            layout.addWidget(led, 1)

    def __getitem__(self, key):
        return self.leds[key]


# --- screen -----------------------------------------------------------------

AMBER = QColor("#ffb347")
GREEN = QColor("#5cff8d")
DIM = QColor("#cfc8b8")      # secondary text: light, still distinct from WHITE
WHITE = QColor("#f2efe6")
RED = QColor("#ff4d4d")
CYAN = QColor("#63d8ff")
BG = QColor("#050505")

W, H = 640, 480  # virtual canvas
BOX_X = 466      # left edge of the distance/direction box


def _ago(ts):
    secs = int(time.time() - ts)
    if secs < 60:
        return tr("{n}s ago", n=secs)
    if secs < 3600:
        return tr("{n} min ago", n=secs // 60)
    if secs < 86400:
        return tr("{n} h ago", n=secs // 3600)
    return tr("{n} d ago", n=secs // 86400)


class ReflectorScreen(QWidget):
    """Black 4:3 display with reflector data and current activity."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumSize(320, 240)
        self.state = {}
        load_fonts()
        mono = QFont("DejaVu Sans Mono")
        mono.setStyleHint(QFont.Monospace)
        self.mono = mono
        self.tick = QTimer(self, interval=1000)
        self.tick.timeout.connect(self.update)
        self.tick.start()

    def update_state(self, **values):
        self.state.update(values)
        self.update()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return int(width * 3 / 4)

    def sizeHint(self):
        return QSize(480, 360)

    # drawing helpers
    def _font(self, size, bold=False):
        f = QFont(self.mono)
        f.setPixelSize(size)
        f.setBold(bold)
        return f

    def _text(self, p, x, y, text, size, color, bold=False, align=Qt.AlignLeft, width=None):
        font = self._font(size, bold)
        p.setFont(font)
        p.setPen(color)
        fm = QFontMetrics(font)
        width = width or (W - 2 * 24)
        text = fm.elidedText(str(text), Qt.ElideRight, width)
        if align == Qt.AlignRight:
            x = x - fm.horizontalAdvance(text)
        elif align == Qt.AlignHCenter:
            x = x - fm.horizontalAdvance(text) / 2
        p.drawText(int(x), int(y), text)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        # Keep 4:3 inside whatever space we got
        if w * 3 > h * 4:
            sw, sh = h * 4 / 3, h
        else:
            sw, sh = w, w * 3 / 4
        ox, oy = (w - sw) / 2, (h - sh) / 2
        p.fillRect(self.rect(), QColor("#1b1b1b"))
        p.translate(ox, oy)
        p.scale(sw / W, sh / H)
        p.setBrush(BG)
        p.setPen(QPen(QColor("#2a2a2a"), 3))
        p.drawRoundedRect(QRectF(1.5, 1.5, W - 3, H - 3), 14, 14)
        self._draw(p)

    def _draw(self, p):
        s = self.state
        L, R = 24, W - 24
        ref = s.get("reflector") or {}
        st = s.get("status") or {}

        # --- reflector block
        self._text(p, L, 34, tr("REFLECTOR"), 14, DIM, True)
        self._text(p, R, 34, ref.get("server", "") or tr("server ?"), 14, DIM, align=Qt.AlignRight)
        self._text(p, L, 72, ref.get("name") or "—", 32, AMBER, True, width=400)
        self._text(p, R, 72, ref.get("to") or s.get("to", ""), 26, CYAN, True, align=Qt.AlignRight)
        if s.get("mode_warning"):
            self._text(p, L, 98, "⚠ " + s["mode_warning"], 15, RED, True)
        else:
            self._text(p, L, 98, ref.get("description", ""), 15, WHITE)

        online = st.get("online")
        parts = []
        parts.append(("● " + tr("ONLINE"), GREEN) if online else ("● " + tr("NO DATA"), DIM) if online is None else
                     ("● " + tr("DOWN"), RED))
        if st.get("users") is not None:
            parts.append((tr("{n} nodes", n=st["users"]), WHITE))
        if st.get("linked") is True:
            parts.append((tr("linked"), GREEN))
        elif st.get("linked") is False:
            parts.append((tr("not linked"), AMBER))
        if s.get("server_mismatch"):
            parts.append((tr("different server!"), RED))
        x = L
        for text, color in parts:
            self._text(p, x, 124, text, 16, color, True)
            x += QFontMetrics(self._font(16, True)).horizontalAdvance(text) + 22

        p.setPen(QPen(QColor("#333"), 2))
        p.drawLine(L, 140, R, 140)

        # --- activity block
        rx = s.get("rx")
        if s.get("tx"):
            self._text(p, L, 176, "TX", 22, RED, True)
            self._text(p, L + 50, 176, tr("transmitting"), 18, RED)
            self._text(p, L, 232, s.get("my_call", ""), 52, RED, True)
            self._text(p, L, 262, f"→ {s.get('to', '')}", 18, WHITE)
            self._elapsed(p, s.get("tx_since"), RED)
        elif rx:
            live = rx.get("live")
            self._text(p, L, 176, "RX" if live else tr("LAST"), 22, GREEN if live else DIM, True)
            if not live and rx.get("ended"):
                self._text(p, L + 110, 176, _ago(rx["ended"]), 18, DIM)
            call = rx.get("callsign", "")
            if rx.get("suffix"):
                call += f" /{rx['suffix']}"
            self._text(p, L, 232, call, 52, GREEN if live else AMBER, True)
            self._text(p, L, 264, rx.get("name") or "", 22, WHITE, width=BOX_X - L - 10)
            self._text(p, L, 290, rx.get("location") or "", 16, DIM, width=BOX_X - L - 10)
            self._position_box(p, rx)
            if rx.get("message"):
                self._text(p, L, 314, f"« {rx['message']} »", 17, CYAN)
            if live:
                self._elapsed(p, rx.get("started"), GREEN)
        else:
            self._text(p, W / 2, 240, tr("no activity"), 24, DIM, align=Qt.AlignHCenter)

        p.setPen(QPen(QColor("#333"), 2))
        p.drawLine(L, 330, R, 330)

        # --- last heard on the reflector (from its API, when available)
        self._text(p, L, 354, s.get("heard_title", tr("LAST HEARD ON THE REFLECTOR")), 16, DIM, True)
        heard = s.get("heard") or []
        if not heard:
            self._text(p, L, 384, tr("(no records for this reflector)"), 18, DIM)
        # Three rows in a readable size (the screen scales with the narrow window)
        for i, h in enumerate(heard[:3]):
            y = 384 + i * 27
            self._text(p, L, y, h.get("callsign", ""), 21, AMBER, True, width=150)
            self._text(p, L + 150, y, h.get("name", ""), 21, WHITE, width=R - L - 260)
            self._text(p, R, y, h.get("time", ""), 19, DIM, align=Qt.AlignRight)

        # --- footer
        footer = f"MY {s.get('my_call', '—')}"
        if s.get("locator"):
            footer += f" · {s['locator']}"
        if s.get("mode"):
            footer += f" · {s['mode']}"
        if s.get("dprs_on") is not None:
            footer += " · D-PRS " + ("ON" if s["dprs_on"] else "OFF")
        self._text(p, L, H - 12, footer, 16, DIM, width=R - L - 110)
        self._text(p, R, H - 12, time.strftime("%H:%M:%S"), 16, DIM, align=Qt.AlignRight)

    def _position_box(self, p, rx):
        """Fixed box: distance and direction to the station (D-PRS), or a placeholder."""
        box = QRectF(BOX_X, 244, W - 24 - BOX_X, 64)
        has_distance = rx.get("distance") is not None
        p.setPen(QPen(CYAN if has_distance else QColor("#333"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(box, 8, 8)
        cx = box.center().x()
        if has_distance:
            self._text(p, cx, 272, f"{rx['distance']:.0f} km", 24, CYAN, True, align=Qt.AlignHCenter, width=box.width())
            bearing = rx.get("bearing") or 0
            self._text(p, cx, 297, f"{tr(compass_point(bearing))} · {bearing:.0f}°", 16, WHITE, True,
                       align=Qt.AlignHCenter, width=box.width())
        elif rx.get("pos"):
            lat, lon = rx["pos"]
            self._text(p, cx, 272, f"{abs(lat):.2f}°{'N' if lat >= 0 else 'S'}", 16, CYAN, True, align=Qt.AlignHCenter)
            self._text(p, cx, 294, f"{abs(lon):.2f}°{'E' if lon >= 0 else 'W'}", 16, CYAN, True, align=Qt.AlignHCenter)
        else:
            self._text(p, cx, 272, "— km", 22, DIM, True, align=Qt.AlignHCenter, width=box.width())
            self._text(p, cx, 296, tr("no position"), 13, DIM, align=Qt.AlignHCenter, width=box.width())

    def _elapsed(self, p, since, color):
        if since:
            secs = int(time.time() - since)
            self._text(p, W - 24, 176, f"{secs // 60:02d}:{secs % 60:02d}", 22, color, True, align=Qt.AlignRight)
