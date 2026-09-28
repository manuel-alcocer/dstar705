"""System tray icon: station on air and status without the window in front."""

from PySide6.QtCore import QObject, QRectF, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .i18n import tr

ICON_SIZE = 64
STATE_COLORS = {"rx": "#2ecc40", "tx": "#ff2d2d"}


def available():
    return QSystemTrayIcon.isSystemTrayAvailable()


def _state_icon(base, state):
    """The application icon with a coloured dot in the corner while receiving or transmitting."""
    color = STATE_COLORS.get(state)
    if not color:
        return base
    pixmap = base.pixmap(ICON_SIZE, ICON_SIZE)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor("#000000"))
    painter.setBrush(QColor(color))
    dot = ICON_SIZE * 0.42
    painter.drawEllipse(QRectF(ICON_SIZE - dot - 1, ICON_SIZE - dot - 1, dot, dot))
    painter.end()
    return QIcon(pixmap)


class Tray(QObject):
    toggle_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_icon = QApplication.windowIcon()
        self.icons = {state: _state_icon(self.base_icon, state) for state in ("", "rx", "tx")}
        self.state = ""
        self.tray = QSystemTrayIcon(self.icons[""], self)
        self.tray.setToolTip("QDStar")
        self.tray.activated.connect(self._activated)
        self.tray.messageClicked.connect(self.toggle_requested)
        self.menu = QMenu()
        self.toggle_action = QAction(tr("Show QDStar"), self.menu, triggered=lambda: self.toggle_requested.emit())
        self.menu.addAction(self.toggle_action)
        self.menu.addSeparator()
        self.menu.addAction(QAction(tr("Quit"), self.menu, triggered=lambda: self.quit_requested.emit()))
        self.tray.setContextMenu(self.menu)

    def show(self):
        self.tray.show()

    def hide(self):
        self.tray.hide()

    def set_window_visible(self, visible):
        self.toggle_action.setText(tr("Hide QDStar") if visible else tr("Show QDStar"))

    def set_state(self, state):
        """'' (idle), 'rx' or 'tx'."""
        if state != self.state:
            self.state = state
            self.tray.setIcon(self.icons.get(state, self.icons[""]))

    def set_tooltip(self, text):
        self.tray.setToolTip(text)

    def notify(self, title, text):
        if self.tray.isVisible() and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, text, self.base_icon, 5000)

    def _activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:      # a double click also starts with a Trigger
            self.toggle_requested.emit()
