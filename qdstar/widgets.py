"""Custom widgets: status LEDs and the 4:3 reflector screen."""

import math
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
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
VIOLET = QColor("#c9a2ff")   # an over from the history, not what is on air now
BG = QColor("#050505")

W, H = 640, 480  # virtual canvas
BOX_X = 466      # left edge of the distance/direction box
SMALL_TEXT = 19  # texts up to this size use the proportional font


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
    """Black 4:3 display with reflector data and current activity.
    With state['review'] set, the activity block shows that over from the history instead;
    a click on the screen asks to go back to live (live_requested)."""

    live_requested = Signal()

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
        if "review" in values:
            self.setCursor(Qt.PointingHandCursor if values["review"] else Qt.ArrowCursor)
            self.setToolTip(tr("Click (or press Esc) to go back to live") if values["review"] else "")
        self.update()

    def mousePressEvent(self, event):
        if self.state.get("review") and event.button() == Qt.LeftButton:
            self.live_requested.emit()
        super().mousePressEvent(event)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return int(width * 3 / 4)

    def sizeHint(self):
        return QSize(480, 360)

    # drawing helpers
    def _font(self, size, bold=False, sans=None):
        """Small secondary texts use the proportional DejaVu Sans, which reads better when small."""
        if sans is None:
            sans = size <= SMALL_TEXT
        f = QFont("DejaVu Sans") if sans else QFont(self.mono)
        f.setPixelSize(max(1, int(round(size))))
        f.setBold(bold)
        return f

    def _advance(self, text, size, bold=False):
        """Width of a text in canvas units."""
        return QFontMetrics(self._font(size, bold)).horizontalAdvance(text)

    def _text(self, p, x, y, text, size, color, bold=False, align=Qt.AlignLeft, width=None):
        # Text is drawn at its real on-screen size (not scaled with the canvas), so the
        # font can be hinted to the pixel grid and stays sharp in a narrow window.
        k = p.transform().m11()
        font = self._font(size * k, bold, sans=size <= SMALL_TEXT)
        fm = QFontMetrics(font)
        text = fm.elidedText(str(text), Qt.ElideRight, int((width or (W - 2 * 24)) * k))
        pt = p.transform().map(QPointF(x, y))
        px = pt.x()
        if align == Qt.AlignRight:
            px -= fm.horizontalAdvance(text)
        elif align == Qt.AlignHCenter:
            px -= fm.horizontalAdvance(text) / 2
        p.save()
        p.resetTransform()
        p.setFont(font)
        p.setPen(color)
        p.drawText(QPointF(round(px), round(pt.y())), text)
        p.restore()

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
            x += self._advance(text, 16, True) + 22

        p.setPen(QPen(QColor("#333"), 2))
        p.drawLine(L, 140, R, 140)

        # --- activity block
        rx = s.get("rx")
        if s.get("review"):
            self._review(p, s["review"], s)
        elif s.get("tx"):
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
            self._position_box(p, rx, s)
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

    def _review(self, p, entry, s):
        """An over picked in the history: same layout as a received over, framed in violet,
        with its date, duration and reflector, and a LIVE button to go back."""
        L, R = 24, W - 24
        p.setPen(QPen(VIOLET, 2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(L - 12, 148, R - L + 24, 176), 10, 10)
        self._text(p, L, 176, tr("HISTORY"), 20, VIOLET, True)
        details = [time.strftime("%d/%m %H:%M:%S", time.localtime(entry["started"]))]
        if entry.get("ended"):
            secs = int(entry["ended"] - entry["started"])
            details.append(f"{secs // 60}:{secs % 60:02d}" if secs >= 60 else f"{secs}s")
        if entry.get("reflector"):
            details.append(entry["reflector"])
        live = "▶ " + tr("LIVE")
        pill_w = self._advance(live, 16, True) + 20
        x = L + self._advance(tr("HISTORY"), 20, True) + 14
        self._text(p, x, 176, " · ".join(details), 16, DIM, width=R - pill_w - 14 - x)
        pill = QRectF(R - pill_w, 158, pill_w, 26)
        p.setPen(QPen(GREEN, 1.5))
        p.drawRoundedRect(pill, 13, 13)
        self._text(p, pill.center().x(), 177, live, 16, GREEN, True, align=Qt.AlignHCenter, width=pill_w)
        call = entry.get("callsign", "")
        if entry.get("suffix"):
            call += f" /{entry['suffix']}"
        self._text(p, L, 232, call, 52, RED if entry.get("direction") == "TX" else AMBER, True)
        self._text(p, L, 264, entry.get("name") or "", 22, WHITE, width=BOX_X - L - 10)
        self._text(p, L, 290, entry.get("location") or "", 16, DIM, width=BOX_X - L - 10)
        self._position_box(p, entry, s)
        if entry.get("message"):
            self._text(p, L, 314, f"« {entry['message']} »", 17, CYAN)

    def _position_box(self, p, rx, s):
        """Fixed box: distance and direction to the station (D-PRS), or a placeholder.
        Our own over shows a circle with a cross (here) instead of a direction."""
        box = QRectF(BOX_X, 244, W - 24 - BOX_X, 64)
        mine = (s.get("my_call") or "").split()[:1]
        own = bool(mine) and (rx.get("callsign") or "").split()[:1] == mine
        has_distance = rx.get("distance") is not None and not own
        p.setPen(QPen(CYAN if has_distance or own else QColor("#333"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(box, 8, 8)
        cx = box.center().x()
        icon = QPointF(box.left() + 30, box.center().y())
        text_x = box.left() + 58 + (box.width() - 58) / 2   # centre of the part right of the icon
        text_w = box.width() - 58
        if own:
            self._here_icon(p, icon, 20)
            self._text(p, text_x, 272, "MY", 22, CYAN, True, align=Qt.AlignHCenter, width=text_w)
            if s.get("locator"):
                self._text(p, text_x, 296, s["locator"], 14, WHITE, True, align=Qt.AlignHCenter, width=text_w)
        elif has_distance:
            bearing = rx.get("bearing") or 0
            self._direction_icon(p, icon, 20, bearing)
            # 1000 km and more do not fit next to the arrow at the full size: shrink to fit
            distance = f"{rx['distance']:.0f} km"
            size = 22
            while size > 14 and self._advance(distance, size, True) > text_w - 4:
                size -= 1
            self._text(p, text_x, 272, distance, size, CYAN, True, align=Qt.AlignHCenter, width=text_w)
            self._text(p, text_x, 297, f"{tr(compass_point(bearing))} · {bearing:.0f}°", 14, WHITE, True,
                       align=Qt.AlignHCenter, width=text_w)
        elif rx.get("pos"):
            lat, lon = rx["pos"]
            self._text(p, cx, 272, f"{abs(lat):.2f}°{'N' if lat >= 0 else 'S'}", 16, CYAN, True, align=Qt.AlignHCenter)
            self._text(p, cx, 294, f"{abs(lon):.2f}°{'E' if lon >= 0 else 'W'}", 16, CYAN, True, align=Qt.AlignHCenter)
        else:
            self._text(p, cx, 272, "— km", 22, DIM, True, align=Qt.AlignHCenter, width=box.width())
            self._text(p, cx, 296, tr("no position"), 13, DIM, align=Qt.AlignHCenter, width=box.width())

    @staticmethod
    def _here_icon(p, c, r):
        """Circle with a cross in the centre: the station on air is us."""
        p.setPen(QPen(CYAN, 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, r, r)
        arm = r * 0.55
        p.drawLine(QPointF(c.x() - arm, c.y()), QPointF(c.x() + arm, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - arm), QPointF(c.x(), c.y() + arm))

    @staticmethod
    def _direction_icon(p, c, r, bearing):
        """Unit vector from our position towards the station: north up, bearing clockwise."""
        p.setPen(QPen(QColor("#555"), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, r, r)
        p.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() - r + 5))   # north tick
        a = math.radians(bearing)
        dx, dy = math.sin(a), -math.cos(a)
        tip = QPointF(c.x() + dx * (r - 3), c.y() + dy * (r - 3))
        tail = QPointF(c.x() - dx * (r - 8), c.y() - dy * (r - 8))
        p.setPen(QPen(CYAN, 2.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(tail, tip)
        # Arrow head: two short strokes back from the tip
        for side in (-1, 1):
            h = a + math.pi + side * math.radians(28)
            p.drawLine(tip, QPointF(tip.x() + math.sin(h) * 8, tip.y() - math.cos(h) * 8))

    def _elapsed(self, p, since, color):
        if since:
            secs = int(time.time() - since)
            self._text(p, W - 24, 176, f"{secs // 60:02d}:{secs % 60:02d}", 22, color, True, align=Qt.AlignRight)


# --- view title bar -------------------------------------------------------------

class DockTitleBar(QWidget):
    """Title bar of a view (dock widget) with its own detach/attach and close buttons.

    Qt's own title bar starts a mouse drag on every press, and Wayland only lets popups grab
    the mouse ("This plugin supports grabbing the mouse only for popup windows"): the first
    click was lost. This bar keeps the mouse to itself, so nothing is dragged; a detached view
    is a normal window that the window manager moves and resizes."""

    def __init__(self, dock):
        super().__init__(dock)
        from PySide6.QtWidgets import QStyle, QToolButton
        self.dock = dock
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 1, 2, 1)
        layout.setSpacing(2)
        self.title = QLabel(dock.windowTitle())
        layout.addWidget(self.title, 1)
        style = self.style()
        self.float_button = QToolButton(autoRaise=True)
        self.float_button.setIcon(style.standardIcon(QStyle.SP_TitleBarNormalButton))
        self.float_button.clicked.connect(self.toggle_floating)
        close = QToolButton(autoRaise=True, toolTip=tr("Close (View menu to show it again)"))
        close.setIcon(style.standardIcon(QStyle.SP_TitleBarCloseButton))
        close.clicked.connect(dock.close)
        self.extras = QHBoxLayout()           # view-specific controls, e.g. the History's "Hide mine"
        self.extras.setContentsMargins(0, 0, 6, 0)
        layout.addLayout(self.extras)
        for button in (self.float_button, close):
            button.setIconSize(QSize(12, 12))
            layout.addWidget(button)
        dock.topLevelChanged.connect(self._update)
        self._update(dock.isFloating())

    def toggle_floating(self):
        self.dock.setFloating(not self.dock.isFloating())

    def _update(self, floating):
        self.float_button.setToolTip(tr("Attach to the main window") if floating else tr("Detach into its own window"))

    def mouseDoubleClickEvent(self, event):
        self.toggle_floating()
        event.accept()

    def mousePressEvent(self, event):
        event.accept()      # no drag (see the class docstring)

    def mouseMoveEvent(self, event):
        event.accept()


# --- weather cards ------------------------------------------------------------

class WeatherCard(QWidget):
    """One weather station: temperature, humidity, pressure, wind and rain, in the screen's style."""

    HEIGHT = 112

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(self.HEIGHT)
        self.setMaximumHeight(self.HEIGHT)
        self.data = {}
        load_fonts()

    def set_data(self, **data):
        self.data = data
        self.update()

    def _font(self, size, bold=False):
        # Same rule as the screen: proportional font for small texts
        f = QFont("DejaVu Sans") if size <= SMALL_TEXT - 3 else QFont("DejaVu Sans Mono")
        f.setPixelSize(size)
        f.setBold(bold)
        return f

    def _text(self, p, x, y, text, size, color, bold=False, align=Qt.AlignLeft):
        font = self._font(size, bold)
        p.setFont(font)
        p.setPen(color)
        fm = QFontMetrics(font)
        if align == Qt.AlignRight:
            x -= fm.horizontalAdvance(text)
        elif align == Qt.AlignHCenter:
            x -= fm.horizontalAdvance(text) / 2
        p.drawText(int(x), int(y), text)

    def paintEvent(self, _):
        from math import cos, radians, sin
        d, w = self.data, self.data.get("weather") or {}
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        p.setBrush(BG)
        p.setPen(QPen(QColor("#2a2a2a"), 2))
        p.drawRoundedRect(rect, 10, 10)
        L, R = 12, self.width() - 12
        self._text(p, L, 22, d.get("name", ""), 15, AMBER, True)
        self._text(p, R, 22, d.get("where", ""), 13, CYAN, True, align=Qt.AlignRight)

        temperature = w.get("temperature")
        self._text(p, L, 70, "—" if temperature is None else f"{temperature:.1f}°", 36, WHITE, True)
        if temperature is not None:
            self._text(p, L + QFontMetrics(self._font(36, True)).horizontalAdvance(f"{temperature:.1f}°") + 2,
                       58, "C", 16, WHITE, True)

        col = max(L + 150, self.width() // 2 - 10)
        rows = []
        if w.get("humidity") is not None:
            rows.append(("💧", f"{w['humidity']:.0f} %"))
        if w.get("pressure"):
            rows.append(("⏲", f"{w['pressure']:.1f} hPa"))
        rain = w.get("rain_24h")
        if rain is not None:
            rows.append(("☔", f"{rain:.1f} mm/24h"))
        for i, (icon, value) in enumerate(rows[:3]):
            self._text(p, col, 46 + i * 20, f"{icon} {value}", 13, WHITE)

        # Wind: arrow pointing where the wind blows to (it comes from wind_dir)
        wind = w.get("wind")
        wx, wy = R - 26, 64
        if wind:
            angle = radians((w.get("wind_dir") or 0) + 180)
            dx, dy = sin(angle), -cos(angle)
            p.setPen(QPen(CYAN, 3))
            p.drawLine(int(wx - dx * 14), int(wy - dy * 14), int(wx + dx * 14), int(wy + dy * 14))
            tip_left = radians((w.get("wind_dir") or 0) + 180 - 150)
            tip_right = radians((w.get("wind_dir") or 0) + 180 + 150)
            for a in (tip_left, tip_right):
                p.drawLine(int(wx + dx * 14), int(wy + dy * 14),
                           int(wx + dx * 14 + sin(a) * 8), int(wy + dy * 14 - cos(a) * 8))
            self._text(p, wx, wy + 32, f"{wind:.1f} m/s", 12, CYAN, True, align=Qt.AlignHCenter)
        elif wind is not None:
            self._text(p, R, wy + 6, d.get("calm", ""), 13, CYAN, True, align=Qt.AlignRight)

        self._text(p, L, self.height() - 10, d.get("footer", ""), 12, DIM)


class WeatherPanel(QWidget):
    """Scrollable list of WeatherCard, nearest station first."""

    def __init__(self, parent=None):
        from PySide6.QtWidgets import QScrollArea
        super().__init__(parent)
        self.inner = QWidget()
        self.cards_layout = QVBoxLayout(self.inner)
        self.cards_layout.setContentsMargins(4, 4, 4, 4)
        self.cards_layout.setSpacing(6)
        self.cards_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.inner)
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.empty)
        layout.addWidget(scroll, 1)
        self.cards = []

    def set_stations(self, stations, empty_text):
        """stations: list of dicts for WeatherCard.set_data."""
        while len(self.cards) < len(stations):
            card = WeatherCard()
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
            self.cards.append(card)
        for card, data in zip(self.cards, stations):
            card.set_data(**data)
            card.show()
        for card in self.cards[len(stations):]:
            card.hide()
        self.empty.setText(empty_text if not stations else "")
        self.empty.setVisible(not stations)


def led_pixmap(color_name, size=14):
    """A small LED like the status ones, for buttons (e.g. the active mode)."""
    from PySide6.QtGui import QPixmap
    ratio = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    color = LED_COLORS[color_name]
    rect = QRectF(1.5, 1.5, size - 3, size - 3)
    grad = QRadialGradient(rect.center().x() - 2, rect.center().y() - 2, size / 2)
    grad.setColorAt(0, color.lighter(170) if color_name != "off" else color.lighter(130))
    grad.setColorAt(1, color)
    p.setBrush(grad)
    p.setPen(QPen(QColor("#111"), 1))
    p.drawEllipse(rect)
    p.end()
    return pixmap


def mode_led_icon():
    """Icon that shows a green LED when its checkable button is on, and an unlit one when off."""
    from PySide6.QtGui import QIcon
    icon = QIcon()
    icon.addPixmap(led_pixmap("green"), QIcon.Normal, QIcon.On)
    icon.addPixmap(led_pixmap("off"), QIcon.Normal, QIcon.Off)
    return icon
