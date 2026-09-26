"""Main window: LED row, 4:3 reflector screen, mode + reflector selector and tabs."""

import re
import shlex
import time
from datetime import datetime

from PySide6.QtCore import QByteArray, QProcess, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtSerialPort import QSerialPortInfo
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from . import __author__, __url__, __version__, config, startup
from . import civ
from .dialogs import SYMBOL_NAMES, DprsDialog, ReflectorsDialog, SettingsDialog, format_position
from .dstar.core import LocalGateway
from .gateway import GatewayClient
from .lookup import NameLookup
from .radio import Radio
from .reflectors import Registry, StatusPoller
from .storage import Storage
from .updates import UpdateChecker
from .widgets import LedBar, ReflectorScreen, WeatherPanel, load_fonts
from .i18n import N_, tr

# (key, caption, tooltip); translated when the window is built
LEDS = [
    ("radio", N_("Icom"), N_("Network session with the IC-705")),
    ("civ", N_("CI-V"), N_("The radio answers CI-V commands")),
    ("internet", N_("Internet"), N_("Internet access (XLX directory)")),
    ("usb", N_("USB"), N_("EXT mode: the radio's USB cable is connected to the PC")),
    ("gateway", N_("Gateway"), N_("EXT mode: the gateway answers")),
    ("reflector", N_("Reflector"), N_("The selected reflector is online")),
    ("linked", N_("Linked"), N_("Linked to the reflector")),
    ("rx", N_("RX"), N_("Receiving voice")),
    ("tx", N_("TX"), N_("Transmitting")),
]
EXT_ONLY_LEDS = ("usb", "gateway")
ICOM_USB_VENDOR = 0x0C26

MODE_NAMES = {"int": "INT · WiFi", "ext": "EXT · USB/PC"}
HISTORY_COLUMNS = [N_("Time"), "", N_("Call sign"), N_("Dist."), N_("Name"), N_("Reflector"), N_("Dur."),
                   N_("Message"), N_("Location")]
DPRS_COLUMNS = [N_("Time"), N_("Station"), N_("Type"), N_("Dist."), N_("Details"), N_("Via"), N_("Reflector")]
DPRS_KIND_NAMES = {"position": N_("position"), "object": N_("object"), "item": N_("item"), "weather": N_("weather")}
GPS_POLL_MS = 60_000
LOG_MAX_BYTES = 2_000_000
WINDOW_WIDTH = 420
UPDATE_CHECK_MS = 24 * 3600 * 1000
ALL_TIME = 100 * 365 * 86400
EXT_UR = "CQCQCQ"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QDStar — IC-705 D-STAR")
        startup.progress(3, tr("Opening the database…"))
        self.storage = Storage()
        startup.progress(4, tr("Loading reflectors…"))
        self.registry = Registry()
        self.lookup = NameLookup(self.storage)
        self.lookup.resolved.connect(self._name_resolved)
        self.radio = None
        self.gateway = None
        self.log_file = self._open_log()

        self.mode = config.get("dstar/mode")
        self.to = ""
        self.r1 = ""
        self.r2 = ""
        self.my_call = ""
        self.status = {}
        self.gw_ok = None
        self.gw_links = []
        self.pending_restore = None
        self.usb_present = None
        self.radio_connected = False
        self.own_gps = {}          # radio settings 0281 (GPS select), 0286 (manual position), 0287 (TX mode)
        self.gps_fix = None        # (lat, lon) from the radio's GPS when GPS Select = ON
        self._geo_origin = None    # position the displayed distances were computed from
        self.rx_entry = None
        self.rx_info = None
        self.tx_entry = None
        self.tx_since = None

        startup.progress(5, tr("Preparing the interface…"))
        load_fonts()
        self._build_ui()
        self._build_menu()

        self.poller = StatusPoller(self.registry, lambda: self.r1)
        self.poller.status.connect(self._reflector_status)
        self.poller.internet.connect(lambda ok: self.leds["internet"].set("green" if ok else "red"))
        self.poller.start()

        # New versions: once at start-up, then daily while the app stays open
        self.updates = UpdateChecker()
        self.updates.available.connect(self._update_available)
        self.updates.up_to_date.connect(self._update_none)
        self.updates.failed.connect(self._update_failed)
        self.update_manual = False
        self.update_notified = ""
        self.update_timer = QTimer(self, interval=UPDATE_CHECK_MS)
        self.update_timer.timeout.connect(lambda: self._check_updates(manual=False))
        if config.get("updates/check"):
            QTimer.singleShot(4000, lambda: self._check_updates(manual=False))
            self.update_timer.start()
        self.registry.changed.connect(self._fill_reflectors)
        self.registry.changed.connect(self.poller.refresh_now)
        self.registry.changed.connect(self._refresh_screen_reflector)

        self.weather_timer = QTimer(self, interval=60_000)
        self.weather_timer.timeout.connect(self._load_weather)
        self.weather_timer.start()
        self.gps_timer = QTimer(self, interval=GPS_POLL_MS)
        self.gps_timer.timeout.connect(lambda: self.radio and self.radio.read_my_position())
        self.usb_timer = QTimer(self, interval=2000)
        self.usb_timer.timeout.connect(self._check_usb)

        startup.progress(6, tr("Starting the gateway…"))
        self._apply_mode(self.mode, startup=True)
        self._load_history()
        self._load_dprs()
        self._update_last_heard()
        self._backfill_names()
        if config.get("radio/auto_connect") and config.get("radio/username"):
            QTimer.singleShot(200, self.connect_radio)
        elif not config.get("radio/username"):
            QTimer.singleShot(200, self.open_settings)

    # --- UI ------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)

        self.leds = LedBar([(key, tr(caption), tr(tip)) for key, caption, tip in LEDS])
        layout.addWidget(self.leds)

        self.screen = ReflectorScreen()
        layout.addWidget(self.screen, 0)

        mode_bar = QHBoxLayout()
        mode_bar.addWidget(QLabel(tr("Mode:")))
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for key in ("int", "ext"):
            button = QPushButton(MODE_NAMES[key], checkable=True)
            button.setToolTip(tr("Terminal Mode with the internal gateway over WiFi (G3 servers)") if key == "int" else
                              tr("Terminal Mode with an external gateway over USB (built into QDStar)"))
            self.mode_group.addButton(button)
            self.mode_buttons[key] = button
            mode_bar.addWidget(button)
            button.clicked.connect(lambda _=False, k=key: self.switch_mode(k))
        self.mode_hint = QLabel()
        self.mode_hint.setStyleSheet("color: #c77;")
        mode_bar.addWidget(self.mode_hint, 1)
        # New version notice (a download link), right-aligned next to the mode buttons
        self.update_label = QLabel()
        self.update_label.setOpenExternalLinks(True)
        self.update_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.update_label.hide()
        mode_bar.addWidget(self.update_label)
        layout.addLayout(mode_bar)

        bar = QHBoxLayout()
        self.reflector_combo = QComboBox()
        self.reflector_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.reflector_combo.setMinimumContentsLength(12)
        bar.addWidget(self.reflector_combo, 1)
        self.change_btn = QPushButton(tr("Change"))
        self.change_btn.clicked.connect(self.change_reflector)
        bar.addWidget(self.change_btn)
        self.unlink_btn = QPushButton(tr("Unlink"))
        self.unlink_btn.clicked.connect(self.unlink_reflector)
        bar.addWidget(self.unlink_btn)
        manage_btn = QPushButton("…")
        manage_btn.setToolTip(tr("Manage reflectors"))
        manage_btn.setFixedWidth(32)
        manage_btn.clicked.connect(self.manage_reflectors)
        bar.addWidget(manage_btn)
        layout.addLayout(bar)

        self.tabs = QTabWidget()
        self.history = QTableWidget(0, len(HISTORY_COLUMNS))
        self.history.setHorizontalHeaderLabels([tr(c) if c else c for c in HISTORY_COLUMNS])
        self.history.verticalHeader().setVisible(False)
        self.history.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history.setAlternatingRowColors(True)
        self.history.setWordWrap(False)
        header = self.history.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        self.tabs.addTab(self.history, tr("History"))

        self.log_view = QPlainTextEdit(readOnly=True)
        self.log_view.setMaximumBlockCount(3000)
        font = self.log_view.font()
        font.setFamily("monospace")
        self.log_view.setFont(font)
        self.tabs.addTab(self.log_view, tr("Log"))

        self.dprs_table = QTableWidget(0, len(DPRS_COLUMNS))
        self.dprs_table.setHorizontalHeaderLabels([tr(c) for c in DPRS_COLUMNS])
        self.dprs_table.verticalHeader().setVisible(False)
        self.dprs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.dprs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.dprs_table.setAlternatingRowColors(True)
        self.dprs_table.setWordWrap(False)
        dprs_header = self.dprs_table.horizontalHeader()
        dprs_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        dprs_header.setStretchLastSection(True)
        self.dprs_tab_index = self.tabs.addTab(self.dprs_table, "D-PRS")
        self.weather_panel = WeatherPanel()
        self.weather_tab_index = self.tabs.addTab(self.weather_panel, tr("Weather"))
        self._show_dprs_tabs()
        layout.addWidget(self.tabs, 1)
        # The screen keeps its full 4:3 size (the window width is fixed); when the window
        # gets shorter, the tabs shrink instead, down to a few visible rows
        margins = layout.contentsMargins()
        self.screen.setFixedHeight(int((WINDOW_WIDTH - margins.left() - margins.right()) * 3 / 4))
        self.tabs.setMinimumHeight(150)

        self.setCentralWidget(central)
        # Vertical layout: the window grows in height only, the width stays fixed
        self.setFixedWidth(WINDOW_WIDTH)
        geometry = config.get("ui/geometry")
        if geometry:
            self.restoreGeometry(QByteArray(geometry))
        else:
            self.resize(WINDOW_WIDTH, 1000)

    def _build_menu(self):
        radio_menu = self.menuBar().addMenu(tr("&Radio"))
        self.connect_action = QAction(tr("Connect"), self, triggered=self.connect_radio)
        self.disconnect_action = QAction(tr("Disconnect"), self, triggered=self.disconnect_radio)
        radio_menu.addAction(self.connect_action)
        radio_menu.addAction(self.disconnect_action)
        radio_menu.addSeparator()
        radio_menu.addAction(QAction(tr("Settings…"), self, triggered=self.open_settings))
        radio_menu.addAction(QAction(tr("D-PRS position…"), self, triggered=self.open_dprs))
        self.debug_action = QAction(tr("Log RX/TX CI-V frames"), self, checkable=True)
        self.debug_action.setChecked(config.get("ui/debug_civ"))
        self.debug_action.toggled.connect(lambda on: config.put("ui/debug_civ", on))
        radio_menu.addAction(self.debug_action)
        radio_menu.addSeparator()
        radio_menu.addAction(QAction(tr("Quit"), self, triggered=self.close))
        ref_menu = self.menuBar().addMenu(tr("R&eflectors"))
        ref_menu.addAction(QAction(tr("Manage…"), self, triggered=self.manage_reflectors))
        ref_menu.addAction(QAction(tr("Refresh status"), self, triggered=self._refresh_all))
        hist_menu = self.menuBar().addMenu(tr("H&istory"))
        hist_menu.addAction(QAction(tr("Clear history…"), self, triggered=self.clear_history))
        help_menu = self.menuBar().addMenu(tr("&Help"))
        help_menu.addAction(QAction(tr("Check for updates…"), self, triggered=lambda: self._check_updates(manual=True)))
        help_menu.addAction(QAction(tr("About QDStar…"), self, triggered=self.about))

    # --- logging ---------------------------------------------------------

    def _open_log(self):
        path = config.data_dir() / "qdstar.log"
        try:
            if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
                path.replace(path.with_suffix(".log.1"))
            return open(path, "a", encoding="utf-8", buffering=1)
        except OSError:
            return None

    def log(self, message):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}"
        self.log_view.appendPlainText(line)
        if self.log_file:
            self.log_file.write(line + "\n")

    # --- INT / EXT mode ----------------------------------------------------

    def switch_mode(self, mode):
        if mode == self.mode:
            return
        if mode == "ext":
            box = QMessageBox(self)
            box.setWindowTitle(tr("EXT mode (USB + PC)"))
            box.setIcon(QMessageBox.Information)
            box.setText(tr("To work in EXT mode:"))
            box.setInformativeText(
                tr("1. Connect the radio's USB cable to the PC.\n"
                   "2. On the radio: MENU > DV GW > Gateway Select = External Gateway USB (B).\n"
                   "3. Terminal/AP Call Sign = {call}.\n"
                   "4. Turn Terminal Mode on.\n\n"
                   "QDStar will start its gateway.", call=config.terminal_call("ext") or tr("<call sign> B")))
            box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            if box.exec() != QMessageBox.Ok:
                self.mode_buttons[self.mode].setChecked(True)
                return
        else:
            box = QMessageBox(self)
            box.setWindowTitle(tr("INT mode (WiFi)"))
            box.setIcon(QMessageBox.Information)
            box.setText(tr("To work in INT mode:"))
            box.setInformativeText(
                tr("1. On the radio: MENU > DV GW > Gateway Select = Internal Gateway (WLAN).\n"
                   "2. Terminal/AP Call Sign = {call}.\n"
                   "3. Turn Terminal Mode on.\n\n"
                   "The USB cable is no longer needed and the gateway stops.",
                   call=config.terminal_call("int") or tr("<call sign> Z")))
            box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            if box.exec() != QMessageBox.Ok:
                self.mode_buttons[self.mode].setChecked(True)
                return
        self._apply_mode(mode)

    def _apply_mode(self, mode, startup=False):
        previous = self.mode
        self.mode = mode
        config.put("dstar/mode", mode)
        self.mode_buttons[mode].setChecked(True)
        for key in EXT_ONLY_LEDS:
            self.leds[key].setVisible(mode == "ext")
        self.unlink_btn.setVisible(mode == "ext")
        self.change_btn.setText(tr("Link") if mode == "ext" else tr("Change"))
        self.change_btn.setToolTip(tr("Links the reflector through the gateway") if mode == "ext" else
                                   tr("Writes the TO (UR) to the radio"))
        if mode == "ext":
            if not startup or previous == "ext":
                self._run_command(config.get("ext/start_cmd"))
            self._start_gateway()
            self.usb_timer.start()
            self._check_usb()
        else:
            self.usb_timer.stop()
            self._stop_gateway()
            if not startup and previous == "ext":
                self._run_command(config.get("ext/stop_cmd"))
        if not startup:
            self.log(tr("Mode {mode}", mode=MODE_NAMES[mode]))
        self._fill_reflectors()
        self._refresh_screen_reflector()

    def _gateway_label(self):
        return "EXT · ircDDBGateway" if self._external_gateway() else tr("EXT · built-in gateway")

    def _external_gateway(self):
        return config.get("ext/backend") == "ircddbgateway"

    def _run_command(self, command):
        # Service commands only apply to the external ircDDBGateway stack
        if not command or not self._external_gateway():
            return
        args = shlex.split(command)
        if QProcess.startDetached(args[0], args[1:]):
            self.log(tr("Ran: {command}", command=command))
        else:
            self.log(tr("Could not run: {command}", command=command))

    def _start_gateway(self):
        self._stop_gateway()
        terminal_call = config.terminal_call("ext")
        if not terminal_call:
            self.log(tr("Gateway: waiting to read your call sign (MY) from the radio"))
            return
        if self._external_gateway():
            self.gateway = GatewayClient(config.get("ext/gateway_host"), config.get("ext/gateway_port"),
                                         config.get("ext/gateway_password"), terminal_call)
        else:
            self.gateway = LocalGateway(config.callsign(), terminal_call, config.gateway_call(),
                                        config.get("ext/usb_port"))
        # Built-in gateway: relink the reflector of the last session once the radio answers over USB
        self.pending_restore = None if self._external_gateway() else (config.get("ext/last_link") or None)
        self.gateway.log.connect(self.log)
        self.gateway.status.connect(self._gateway_status)
        self.gateway.result.connect(self._gateway_result)
        self.gateway.start()
        self.gateway.refresh()

    def _stop_gateway(self):
        if self.gateway:
            self.gateway.stop()
            self.gateway = None
        self.gw_ok = None
        self.gw_links = []

    def _check_usb(self):
        present = any(p.vendorIdentifier() == ICOM_USB_VENDOR for p in QSerialPortInfo.availablePorts())
        if present != self.usb_present:
            plugged_in = present and self.usb_present is False
            self.usb_present = present
            self.log(tr("Radio USB cable detected") if present else tr("Radio USB cable NOT detected"))
            if plugged_in:
                self._run_command(config.get("ext/usb_cmd"))
        self.leds["usb"].set("green" if present else "red")
        self._update_mode_hint()

    def _gateway_status(self, ok, links):
        changed = links != self.gw_links
        self.gw_ok = ok
        self.gw_links = links
        self.leds["gateway"].set("green" if ok else "amber", blink=not ok)
        if ok and self.pending_restore and not self.ext_reflector() and self.gateway:
            reflector, self.pending_restore = self.pending_restore, None
            self.log(tr("Restoring the last link: {reflector}", reflector=reflector))
            self.gateway.link(reflector)
        if changed:
            linked = self.ext_reflector()
            self.log(tr("Gateway linked to {reflector}", reflector=linked) if linked else tr("Gateway not linked"))
            self._select_combo(linked)
            self.poller.refresh_now()
        self._refresh_screen_reflector()

    def _gateway_result(self, ok, detail):
        if ok:
            self.log(f"Gateway: {detail}")
            self._ensure_ext_ur()
        else:
            self.log(tr("Gateway error: {error}", error=detail))
            QMessageBox.warning(self, tr("Link reflector"), detail)

    def ext_reflector(self):
        """Reflector the PC gateway is linked to, e.g. 'REF001 C'."""
        for link in self.gw_links:
            if link["linked"] and not link["incoming"]:
                return link["reflector"]
        return ""

    def current_reflector(self):
        return self.ext_reflector() if self.mode == "ext" else self.to

    def radio_mode(self):
        """Terminal Mode the radio is in, judged by its R1.
        INT fills R1 with the terminal call sign; EXT leaves R1/R2 empty (as does plain DV)."""
        if self.r1 == config.terminal_call("int"):
            return "int"
        if not self.r1 or self.r1 == config.terminal_call("ext"):
            return "ext"
        return None

    def _update_mode_hint(self):
        hints = []
        radio_mode = self.radio_mode()
        if self.radio_connected and radio_mode != self.mode:
            if self.mode == "ext":
                hints.append(tr("the radio is still in INT ({r1})", r1=self.r1))
            else:
                hints.append(tr("the radio is not in INT Terminal Mode (R1 {r1})", r1=self.r1 or tr("empty")))
        if self.mode == "ext" and self.usb_present is False:
            hints.append(tr("connect the USB"))
        self.mode_hint.setText("⚠ " + tr("check") if hints else "")
        self.mode_hint.setToolTip("; ".join(hints))
        self.screen.update_state(mode_warning="; ".join(hints))

    def _ensure_ext_ur(self):
        """In EXT the radio must transmit to CQCQCQ so the gateway sends it to the linked reflector."""
        if self.mode == "ext" and self.radio and self.radio_mode() == "ext" and self.to and self.to != EXT_UR:
            self.log(tr("Radio TO {old} → {new} for the linked reflector", old=self.to, new=EXT_UR))
            self.radio.set_to(EXT_UR)

    # --- radio -----------------------------------------------------------

    def connect_radio(self):
        self.disconnect_radio(quiet=True)
        self.radio = Radio(config.get("radio/host"), config.get("radio/username"), config.get("radio/password"),
                           config.get("radio/control_port"))
        r = self.radio
        r.log.connect(self.log)
        r.link_state.connect(self._link_state)
        r.civ_alive.connect(lambda ok: self.leds["civ"].set("green" if ok else "off"))
        r.my_call.connect(self._my_call)
        r.tx_calls.connect(self._tx_calls)
        r.tx_message.connect(lambda m: self.log(tr("TX message: '{message}'", message=m)))
        r.mode.connect(self._mode)
        r.transmitting.connect(self._transmitting)
        r.rx_started.connect(self._rx_started)
        r.rx_message.connect(self._rx_message)
        r.rx_ended.connect(self._rx_ended)
        r.to_write_result.connect(self._to_written)
        r.raw.connect(lambda line: self.debug_action.isChecked() and self.log(f"CI-V {line}"))
        r.setting_received.connect(self._setting_received)
        r.dprs_received.connect(self._dprs_received)
        r.my_position.connect(self._my_position)
        r.start()

    def disconnect_radio(self, quiet=False):
        if self.radio:
            self.radio.stop()
            self.radio.deleteLater()
            self.radio = None
            if not quiet:
                self.log(tr("Disconnected by the user"))
        self._link_state("disconnected")

    def _link_state(self, state):
        led = self.leds["radio"]
        if state == "connected":
            led.set("green")
        elif state in ("connecting", "authenticated"):
            led.set("amber", blink=True)
        else:
            led.set("red" if self.radio else "off")
            self.leds["civ"].set("off")
        self.connect_action.setEnabled(state == "disconnected")
        self.disconnect_action.setEnabled(self.radio is not None)
        self.radio_connected = state == "connected"
        if self.radio_connected:
            for number in ("0281", "0286", "0287"):
                self.radio.read_setting(number)
            self.radio.read_my_position()
            self.gps_timer.start()
        else:
            self.gps_timer.stop()

    def _my_call(self, call, note):
        self.my_call = call
        base = call.split()[0] if call.split() else ""
        if base and not config.callsign():
            # First run: the station call sign is the radio's MY call sign
            config.put("station/callsign", base)
            self.log(tr("Station call sign: {call} (read from the radio)", call=base))
            if self.mode == "ext" and not self.gateway:
                self._start_gateway()
        self.log(f"MY: {call}" + (f" /{note}" if note else ""))
        self.screen.update_state(my_call=call)

    def _mode(self, mode):
        self.screen.update_state(mode=mode)
        if mode != "DV":
            self.log(tr("Warning: the radio is in {mode}, not DV", mode=mode))

    def _tx_calls(self, ur, r1, r2):
        changed = ur != self.to
        self.to, self.r1, self.r2 = ur, r1, r2
        self.log(f"TO={ur}  R1={r1}  R2={r2}")
        self._update_mode_hint()
        if changed and self.mode == "int":
            self._select_combo(ur)
            self.poller.refresh_now()
        if self.mode == "ext" and self.ext_reflector():
            self._ensure_ext_ur()
        self._refresh_screen_reflector()

    # --- reflectors ------------------------------------------------------

    def _refresh_all(self):
        self.poller.refresh_now()
        if self.gateway:
            self.gateway.refresh()

    def _fill_reflectors(self):
        current = self.reflector_combo.currentData() or self.current_reflector()
        self.reflector_combo.blockSignals(True)
        self.reflector_combo.clear()
        for item in self.registry.list(via=self.mode):
            self.reflector_combo.addItem(f"{item['to']}  {item['name']}", item["to"])
        self.reflector_combo.blockSignals(False)
        self._select_combo(current)

    def _select_combo(self, to):
        index = self.reflector_combo.findData(to)
        if index >= 0:
            self.reflector_combo.setCurrentIndex(index)

    def _refresh_screen_reflector(self):
        ref = self.current_reflector()
        item = self.registry.get(ref) if ref else None
        if item is None and ref:
            item = {"to": ref, "name": tr("(not registered)"), "description": tr("Add it in Reflectors > Manage"),
                    "server": ""}
        if self.mode == "ext":
            if item is not None:
                item = dict(item, server=self._gateway_label())
            elif self.gw_ok:
                item = {"to": "", "name": tr("Not linked"), "description": tr("Pick a reflector and press Link"),
                        "server": self._gateway_label()}
            else:
                item = {"to": "", "name": tr("PC gateway"), "description": tr("Waiting for the gateway…"),
                        "server": self._gateway_label()}
            mismatch = False
        else:
            server = config.get("dstar/server")
            mismatch = bool(item and item.get("server") and server and item["server"].lower() != server.lower())
        status = dict(self.status.get(ref, {})) if ref else {}
        if self.mode == "ext":
            status["linked"] = bool(ref) if self.gw_ok else None
            if ref and self.gw_ok and status.get("online") is None:
                status["online"] = True  # the gateway is linked, so the reflector answers
        self.screen.update_state(reflector=item, status=status, to=ref, server_mismatch=mismatch)
        self._update_reflector_leds(status)
        self._update_last_heard()

    def _reflector_status(self, to, status):
        self.status[to] = status
        if to == self.current_reflector():
            self._refresh_screen_reflector()

    def _update_reflector_leds(self, status):
        online = status.get("online")
        self.leds["reflector"].set("off" if online is None else "green" if online else "red")
        linked = status.get("linked")
        self.leds["linked"].set("off" if linked is None else "green" if linked else "amber")

    def change_reflector(self):
        to = self.reflector_combo.currentData()
        if not to:
            return
        if self.mode == "ext":
            if not self.gateway:
                return
            if to == self.ext_reflector():
                self.log(tr("The gateway is already linked to {reflector}", reflector=to))
                return
            self.log(tr("Asking the gateway to link {reflector}…", reflector=to))
            self.pending_restore = None      # the user's choice wins over the saved state
            config.put("ext/last_link", to)
            self.gateway.link(to)
            return
        if not self.radio:
            return
        if to == self.to:
            self.log(tr("{to} is already the current TO", to=to))
            return
        item = self.registry.get(to) or {}
        server = config.get("dstar/server")
        if item.get("server") and server and item["server"].lower() != server.lower():
            answer = QMessageBox.question(
                self, tr("Change reflector"),
                tr("{to} is reached through {needed}, but the radio uses {server}.\n\n"
                   "The server cannot be changed over CI-V: change it in MENU > DV GW > Gateway Repeater "
                   "and update Radio > Settings.\n\nWrite the TO anyway?", to=to, needed=item["server"], server=server))
            if answer != QMessageBox.Yes:
                return
        self.log(tr("Changing the TO to {to}…", to=to))
        self.radio.set_to(to)

    def unlink_reflector(self):
        self.pending_restore = None
        config.put("ext/last_link", "")
        if self.gateway and self.ext_reflector():
            self.log(tr("Unlinking {reflector}…", reflector=self.ext_reflector()))
            self.gateway.unlink()

    def _to_written(self, ok, detail):
        if ok and detail == EXT_UR:
            self.log(tr("Radio TO = {to}", to=EXT_UR))
        elif ok:
            self.log(tr("TO changed to {to}. Press PTT briefly to register on the reflector.", to=detail))
        else:
            self.log(tr("Error changing the TO: {error}", error=detail))
            QMessageBox.warning(self, tr("Change reflector"), detail)

    def manage_reflectors(self):
        ReflectorsDialog(self.registry, self.mode, self).exec()

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            dialog.save()
            self.log(tr("Settings saved"))
            if self.mode == "ext":
                self._start_gateway()
            self._update_mode_hint()
            self._refresh_screen_reflector()
            self._show_dprs_tabs()
            if self.radio or config.get("radio/auto_connect"):
                self.connect_radio()

    # --- activity / history ----------------------------------------------

    def _is_system_call(self, call):
        """Replies from our own gateway/repeater/terminal after a TX are not conversations.
        In EXT the radio does not report R1/R2, so any call sign with our own base counts."""
        if not call or call in (self.r1, self.r2):
            return True
        # We never hear ourselves: <call> /INFO are gateway announcements, <call> B/G acknowledgements
        base = (self.my_call or "").split()[:1]
        return bool(base) and call.split()[:1] == base

    def _rx_started(self, calls):
        if self._is_system_call(calls.caller):
            self.log(tr("System reply: {caller} → {called}", caller=calls.caller, called=calls.called))
            return
        base = calls.caller.split()[0]
        self.log(f"RX {calls.caller}" + (f" /{calls.note}" if calls.note else "") +
                 f"  UR={calls.called} R1={calls.rpt1} R2={calls.rpt2}")
        self.rx_entry = self.storage.start_entry("RX", base, calls.note, self.current_reflector(),
                                                 calls.rpt1, calls.rpt2)
        self.rx_info = {"callsign": calls.caller, "suffix": calls.note, "started": time.time(), "live": True,
                        "name": "", "location": "", "message": ""}
        self.leds["rx"].set("green")
        known = self.storage.last_position(base)
        if known:
            self._with_position(self.rx_info, known)
        self.screen.update_state(rx=self.rx_info)
        self.lookup.request(base)
        self._load_history()

    def _rx_message(self, message, caller):
        base = caller.split()[0] if caller.split() else ""
        if not base or not message:
            return
        # Messages can arrive after the over ended: fill the station's latest entry
        if self.storage.fill_recent(base, "message", message, window=120):
            self._load_history()
        if self.rx_info and self.rx_info["callsign"].split()[:1] == [base]:
            self.rx_info["message"] = message
            self.screen.update_state(rx=self.rx_info)
        self.log(tr("Message from {caller}: {message}", caller=caller, message=message))

    def _rx_ended(self):
        self.leds["rx"].set("off")
        if self.rx_info and self.rx_info.get("live"):
            self.rx_info["live"] = False
            self.rx_info["ended"] = time.time()
            self.storage.update_entry(self.rx_entry, ended=self.rx_info["ended"])
            secs = int(self.rx_info["ended"] - self.rx_info["started"])
            self.log(tr("End of RX {caller} ({seconds}s)", caller=self.rx_info["callsign"], seconds=secs))
            self.screen.update_state(rx=self.rx_info)
            self._load_history()
            self._update_last_heard()

    def _transmitting(self, tx):
        self.leds["tx"].set("red" if tx else "off")
        ref = self.current_reflector()
        base = self.my_call.split()[0] if self.my_call.split() else "?"
        if tx:
            self.tx_since = time.time()
            self.tx_entry = self.storage.start_entry("TX", base, "", ref, self.r1, self.r2)
            self.lookup.request(base)  # our own name, for the last heard list
            self.log(f"TX → {ref or self.to}")
        elif self.tx_entry:
            own = self.storage.cached_name(base) or {}
            self.storage.update_entry(self.tx_entry, ended=time.time(), name=own.get("name") or "",
                                      location=own.get("location") or "")
            self.log(tr("End of TX ({seconds}s)", seconds=int(time.time() - self.tx_since)))
            self.tx_entry = None
            # Our over counts as the reflector's last heard right away; the reflector's
            # dashboard catches up a few seconds later
            QTimer.singleShot(3000, self.poller.refresh_now)
        self.screen.update_state(tx=tx, tx_since=self.tx_since, to=ref or self.to)
        self._load_history()
        if not tx:
            self._update_last_heard()

    def _name_resolved(self, callsign, name, location):
        # The lookup may finish after the over: fill every recent entry of this station
        # (names do not change: any entry of this station still without one gets it)
        changed = self.storage.fill_recent(callsign, "name", name, window=ALL_TIME) + \
            self.storage.fill_recent(callsign, "location", location, window=ALL_TIME)
        if changed:
            self._load_history()
        if self.rx_info and self.rx_info["callsign"].split()[0] == callsign:
            self.rx_info.update(name=self.rx_info.get("name") or name,
                                location=self.rx_info.get("location") or location)
            self.screen.update_state(rx=self.rx_info)

    def _backfill_names(self):
        """Look up names for history entries saved while radioid.net was unreachable."""
        missing = {r["callsign"] for r in self.storage.recent() if not r["name"] and r["callsign"] not in ("?", "")}
        for callsign in missing:
            self.lookup.request(callsign)

    def _load_history(self):
        rows = self.storage.recent()
        self.history.setRowCount(len(rows))
        for i, r in enumerate(rows):
            started = time.localtime(r["started"])
            when = time.strftime("%H:%M:%S" if time.strftime("%Y%m%d", started) == time.strftime("%Y%m%d")
                                 else "%d/%m %H:%M", started)
            dur = f"{int(r['ended'] - r['started'])}s" if r["ended"] else "…"
            call = r["callsign"] + (f" /{r['suffix']}" if r["suffix"] else "")
            item = self.registry.get(r["reflector"]) if r["reflector"] else None
            reflector = r["reflector"] or ""
            if item and item.get("name"):
                reflector = f"{item['name']} ({reflector})"
            dist = ""
            if r.get("lat") is not None and r.get("lon") is not None:
                distance, bearing = self._geo((r["lat"], r["lon"]))
                dist = (f"{distance:.0f} km {tr(civ.compass_point(bearing))}" if distance is not None
                        else format_position(r["lat"], r["lon"]))
            values = [when, r["direction"], call, dist, r["name"] or "", reflector, dur, r["message"] or "",
                      r["location"] or ""]
            for c, v in enumerate(values):
                cell = QTableWidgetItem(v)
                if c == 1:
                    cell.setForeground(Qt.red if v == "TX" else Qt.darkGreen)
                cell.setToolTip(time.strftime("%Y-%m-%d %H:%M:%S", started) if c == 0 else v)
                self.history.setItem(i, c, cell)

    @staticmethod
    def _heard_time(text):
        """'Saturday Sat Sep 26 07:10:17 2026' (xlxd dashboard, local time) -> epoch."""
        match = re.search(r"(\w{3} \w{3} +\d+ \d\d:\d\d:\d\d \d{4})", text or "")
        if not match:
            return None
        try:
            return datetime.strptime(" ".join(match.group(1).split()), "%a %b %d %H:%M:%S %Y").timestamp()
        except ValueError:
            return None

    def _update_last_heard(self):
        """Screen 'last heard' for the selected reflector: the most recent of the reflector's
        own last heard (when it publishes one) and what this app heard there; empty otherwise."""
        ref = self.current_reflector()
        remote = []
        for h in (self.status.get(ref, {}).get("heard") or []) if ref else []:
            ts = self._heard_time(h.get("time"))
            if h.get("callsign") and ts:
                remote.append({"callsign": h["callsign"].strip(), "suffix": "", "name": h.get("name", ""),
                               "location": "", "message": "", "ts": ts, "via": h.get("via", "")})
        local = []
        for r in self.storage.last_heard(ref, 8) if ref else []:
            local.append({"callsign": r["callsign"], "suffix": r["suffix"] or "", "name": r["name"] or "",
                          "location": r["location"] or "", "message": r["message"] or "",
                          "ts": r["ended"] or r["started"], "via": "",
                          "pos": (r["lat"], r["lon"]) if r.get("lat") is not None else None})
        merged = sorted(remote + local, key=lambda e: e["ts"], reverse=True)
        # the same over can appear in both sources: keep one per call sign within a minute,
        # completing it with whatever the other source knows
        unique = []
        for e in merged:
            twin = next((u for u in unique if u["callsign"] == e["callsign"] and abs(u["ts"] - e["ts"]) < 60), None)
            if twin is None:
                unique.append(dict(e))
            else:
                for key, value in e.items():
                    if value and not twin.get(key):
                        twin[key] = value
        heard = [{"callsign": e["callsign"], "name": e["name"],
                  "time": time.strftime("%H:%M:%S", time.localtime(e["ts"]))} for e in unique[:4]]
        title = tr("LAST HEARD ON THE REFLECTOR") if remote else tr("LAST HEARD HERE ON THIS REFLECTOR")
        self.screen.update_state(heard=heard, heard_title=title)
        if self.rx_info and self.rx_info.get("live"):
            return
        if not unique:
            self.rx_info = None
            self.screen.update_state(rx=None)
            return
        last = unique[0]
        self.rx_info = {"callsign": last["callsign"], "suffix": last["suffix"], "name": last["name"],
                        "location": last["location"], "message": last["message"], "live": False,
                        "started": last["ts"], "ended": last["ts"]}
        self._with_position(self.rx_info, last.get("pos") or self.storage.last_position(last["callsign"]))
        self.screen.update_state(rx=self.rx_info)
        if not last["location"]:
            self.lookup.request(last["callsign"])

    # --- D-PRS --------------------------------------------------------------

    def open_dprs(self):
        if not (self.radio and self.radio_connected):
            QMessageBox.information(self, tr("D-PRS position"), tr("Connect to the radio first."))
            return
        DprsDialog(self.radio, self).exec()
        for number in ("0281", "0286", "0287"):
            self.radio.read_setting(number)

    def own_position(self):
        """Our position for distances: the radio's manual position, or its GPS fix."""
        source = self.own_gps.get("0281", b"")[:1]
        if source == b"\x02":
            data = self.own_gps.get("0286", b"")
            if len(data) < 11:
                return None
            lat, lon = civ.decode_latitude(data[:5]), civ.decode_longitude(data[5:11])
            return (lat, lon) if lat is not None and lon is not None else None
        if source == b"\x01":
            return self.gps_fix
        return None

    def _my_position(self, position):
        if position != self.gps_fix:
            self.gps_fix = position
            self._setting_received("0281", self.own_gps.get("0281", b""))   # refresh locator/footer

    def _geo(self, pos):
        """(distance km, bearing degrees) from our position to pos, or (None, None)."""
        own = self.own_position()
        if not own or not pos:
            return None, None
        return (civ.distance_km(own[0], own[1], pos[0], pos[1]),
                civ.bearing_deg(own[0], own[1], pos[0], pos[1]))

    def _with_position(self, info, pos):
        distance, bearing = self._geo(pos)
        info.update(pos=pos, distance=distance, bearing=bearing)
        return info

    def _setting_received(self, number, data):
        if number in ("0281", "0286", "0287"):
            self.own_gps[number] = data
            sending = self.own_gps.get("0287", b"")[:1] == b"\x01"
            own = self.own_position()
            self.screen.update_state(dprs_on=sending, locator=civ.latlon_to_locator(*own) if own else "")
            if own != self._geo_origin:
                # Distances depend on our position: redraw them once it is known or changes
                self._geo_origin = own
                self._load_history()
                self._load_dprs()
                self._update_last_heard()

    def _dprs_received(self, pos):
        base = pos.callsign.split("-")[0].strip()
        self._record_dprs(pos, base)
        if not self.rx_info or not self.rx_entry:
            return
        # A position report without a name is the position of the station transmitting it
        same_station = self.rx_info["callsign"].split()[0] == base or (pos.kind == "position" and not base)
        # Objects and items carry their own name, not the sender's call sign: take them
        # when they arrive during (or right after) the over
        recent = self.rx_info.get("live") or time.time() - self.rx_info.get("ended", 0) < 10
        if not same_station and not (pos.kind in ("object", "item") and recent):
            return
        # (the box may already show this position from an earlier over; the entry still needs it)
        already_shown = self.rx_info.get("pos") == (pos.lat, pos.lon)
        self._with_position(self.rx_info, (pos.lat, pos.lon))
        self.screen.update_state(rx=self.rx_info)
        distance, bearing = self.rx_info["distance"], self.rx_info["bearing"]
        text = format_position(pos.lat, pos.lon)
        if distance is not None:
            text += f" · {distance:.0f} km {tr(civ.compass_point(bearing))} ({bearing:.0f}°)"
        if not already_shown:
            self.log(tr("D-PRS from {caller}: {position}", caller=pos.callsign, position=text))
        if self.rx_entry:
            self.storage.update_entry(self.rx_entry, lat=pos.lat, lon=pos.lon)
            self._load_history()

    # --- updates --------------------------------------------------------------

    def _check_updates(self, manual):
        self.update_manual = manual
        self.updates.check()

    def _update_available(self, version, url, page, notes):
        self.log(tr("New version available: {version}", version=version))
        self.update_label.setText(f'<a href="{url}">⬆ ' + tr("New {version}", version=version) + "</a>")
        self.update_label.setToolTip(tr("New version {version} available", version=version) + " — " + tr("Download"))
        self.update_label.show()
        skipped = config.get("updates/skip") == version
        if self.update_manual or (not skipped and self.update_notified != version):
            self.update_notified = version
            self._offer_update(version, url, page, notes)

    def _offer_update(self, version, url, page, notes):
        box = QMessageBox(self)
        box.setWindowTitle(tr("Update available"))
        box.setIcon(QMessageBox.Information)
        box.setText(tr("QDStar {version} is available (you have {current}).", version=version, current=__version__))
        box.setInformativeText(tr("Release notes: {page}", page=page))
        if notes:
            box.setDetailedText(notes)
        download = box.addButton(tr("Download"), QMessageBox.AcceptRole)
        box.addButton(tr("Later"), QMessageBox.RejectRole)
        skip = box.addButton(tr("Skip this version"), QMessageBox.DestructiveRole)
        box.exec()
        if box.clickedButton() is download:
            QDesktopServices.openUrl(QUrl(url))
        elif box.clickedButton() is skip:
            config.put("updates/skip", version)

    def _update_none(self):
        if self.update_manual:
            QMessageBox.information(self, tr("Check for updates"),
                                    tr("You have the latest version ({version}).", version=__version__))

    def _update_failed(self, error):
        if self.update_manual:
            QMessageBox.warning(self, tr("Check for updates"), tr("Could not check for updates: {error}", error=error))

    def _record_dprs(self, pos, base):
        """D-PRS tab: every report, with the station whose over carried it when it is someone else."""
        if not config.get("dprs/show_all"):
            return
        via = ""
        if self.rx_info:
            caller = self.rx_info["callsign"].split()[0]
            recent = self.rx_info.get("live") or time.time() - self.rx_info.get("ended", 0) < 10
            if recent and base and base != caller:
                via = caller
        name = pos.callsign or (self.rx_info["callsign"].split()[0] if self.rx_info else "?")
        pos = civ.DprsPosition(name, pos.symbol, pos.lat, pos.lon, pos.altitude, pos.kind, pos.weather)
        if self.storage.add_dprs(pos, via, self.current_reflector()):
            self._load_dprs()

    @staticmethod
    def _weather_text(w):
        parts = []
        if w.get("temperature") is not None:
            parts.append(f"{w['temperature']:.1f} °C")
        if w.get("humidity") is not None:
            parts.append(f"{w['humidity']:.0f} %")
        if w.get("pressure"):
            parts.append(f"{w['pressure']:.1f} hPa")
        if w.get("wind") is not None:
            if w["wind"] == 0:
                parts.append(tr("calm"))
            else:
                wind = f"{w['wind']:.1f} m/s"
                if w.get("wind_dir") is not None:
                    wind += " " + tr(civ.compass_point(w["wind_dir"]))
                parts.append(wind)
        if w.get("rain_24h"):
            parts.append(tr("rain {mm} mm/24h", mm=f"{w['rain_24h']:.1f}"))
        return " · ".join(parts)

    def _show_dprs_tabs(self):
        shown = config.get("dprs/show_all")
        self.tabs.setTabVisible(self.dprs_tab_index, shown)
        self.tabs.setTabVisible(self.weather_tab_index, shown)

    @staticmethod
    def _ago(ts):
        minutes = int((time.time() - ts) // 60)
        if minutes < 1:
            return tr("just now")
        if minutes < 60:
            return tr("{n} min ago", n=minutes)
        return tr("{n} h ago", n=minutes // 60)

    def _load_weather(self):
        """Weather tab: the latest report of each station, nearest first."""
        import json
        stations = []
        for r in self.storage.latest_weather():
            distance, bearing = self._geo((r["lat"], r["lon"]))
            where = (f"{distance:.0f} km {tr(civ.compass_point(bearing))}" if distance is not None
                     else format_position(r["lat"], r["lon"]))
            footer = self._ago(r["received"])
            if r["via"]:
                footer = tr("via {station}", station=r["via"]) + " · " + footer
            stations.append({"name": r["name"], "where": where, "weather": json.loads(r["weather"] or "{}"),
                             "footer": footer, "calm": tr("calm"),
                             "_sort": distance if distance is not None else float("inf")})
        stations.sort(key=lambda st: st["_sort"])
        self.weather_panel.set_stations(stations, tr("No weather reports yet.\n"
                                                     "Stations such as ED2YAV relay nearby weather stations."))

    def _load_dprs(self):
        import json
        rows = self.storage.recent_dprs()
        self.dprs_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            received = time.localtime(r["received"])
            when = time.strftime("%H:%M:%S" if time.strftime("%Y%m%d", received) == time.strftime("%Y%m%d")
                                 else "%d/%m %H:%M", received)
            distance, bearing = self._geo((r["lat"], r["lon"]))
            dist = (f"{distance:.0f} km {tr(civ.compass_point(bearing))}" if distance is not None
                    else format_position(r["lat"], r["lon"]))
            if r["weather"]:
                details = self._weather_text(json.loads(r["weather"]))
            else:
                details = tr(SYMBOL_NAMES.get(r["symbol"] or "", "")) if SYMBOL_NAMES.get(r["symbol"] or "") else (r["symbol"] or "")
            values = [when, r["name"], tr(DPRS_KIND_NAMES.get(r["kind"], r["kind"])), dist, details,
                      r["via"] or "", r["reflector"] or ""]
            for c, v in enumerate(values):
                cell = QTableWidgetItem(v)
                cell.setToolTip(format_position(r["lat"], r["lon"]) if c == 3 else v)
                self.dprs_table.setItem(i, c, cell)
        self._load_weather()

    def about(self):
        QMessageBox.about(
            self, tr("About QDStar"),
            f"<b>QDStar {__version__}</b><br>"
            + tr("IC-705 D-STAR Terminal Mode controller and built-in gateway.") + "<br><br>"
            + tr("Author: {author}", author=__author__) + "<br>"
            + tr("Seville (Bellavista), Spain") + "<br>"
            f'<a href="{__url__}">{__url__}</a><br><br>'
            + tr("License GPL-3.0-or-later. Based on wfview (Icom network protocol) "
                 "and on G4KLX's DStarRepeater / ircDDBGateway."))

    def clear_history(self):
        if QMessageBox.question(self, tr("History"), tr("Delete the whole history?")) == QMessageBox.Yes:
            self.storage.clear_history()
            self._load_history()

    # --- shutdown ----------------------------------------------------------

    def closeEvent(self, event):
        config.put("ui/geometry", self.saveGeometry())
        self.poller.stop()
        self._stop_gateway()
        if self.radio:
            self.radio.stop()
        if self.log_file:
            self.log_file.close()
            self.log_file = None
        super().closeEvent(event)
