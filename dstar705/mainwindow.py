"""Main window: LED row, 4:3 reflector screen, mode + reflector selector and tabs."""

import re
import shlex
import time
from datetime import datetime

from PySide6.QtCore import QByteArray, QProcess, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtSerialPort import QSerialPortInfo
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from . import __author__, __url__, __version__, config
from .dialogs import ReflectorsDialog, SettingsDialog
from .dstar.core import LocalGateway
from .gateway import GatewayClient
from .lookup import NameLookup
from .radio import Radio
from .reflectors import Registry, StatusPoller
from .storage import Storage
from .widgets import LedBar, ReflectorScreen, load_fonts

LEDS = [
    ("radio", "Icom", "Sesión de red con la IC-705"),
    ("civ", "CI-V", "La radio responde a comandos CI-V"),
    ("internet", "Internet", "Acceso a internet (directorio XLX)"),
    ("usb", "USB", "Modo EXT: cable USB de la radio conectado al PC"),
    ("gateway", "Gateway", "Modo EXT: ircDDBGateway responde"),
    ("reflector", "Reflector", "El reflector seleccionado está en línea"),
    ("linked", "Enlazado", "Enlazado con el reflector"),
    ("rx", "RX", "Recibiendo voz"),
    ("tx", "TX", "Transmitiendo"),
]
EXT_ONLY_LEDS = ("usb", "gateway")
ICOM_USB_VENDOR = 0x0C26

MODE_NAMES = {"int": "INT · WiFi", "ext": "EXT · USB/PC"}
HISTORY_COLUMNS = ["Hora", "", "Indicativo", "Nombre", "Reflector", "Dur.", "Mensaje", "Ubicación"]
LOG_MAX_BYTES = 2_000_000
EXT_UR = "CQCQCQ"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DStar705 — IC-705 D-STAR")
        self.storage = Storage()
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
        self.usb_present = None
        self.radio_connected = False
        self.rx_entry = None
        self.rx_info = None
        self.tx_entry = None
        self.tx_since = None

        load_fonts()
        self._build_ui()
        self._build_menu()

        self.poller = StatusPoller(self.registry, lambda: self.r1)
        self.poller.status.connect(self._reflector_status)
        self.poller.internet.connect(lambda ok: self.leds["internet"].set("green" if ok else "red"))
        self.poller.start()
        self.registry.changed.connect(self._fill_reflectors)
        self.registry.changed.connect(self.poller.refresh_now)
        self.registry.changed.connect(self._refresh_screen_reflector)

        self.usb_timer = QTimer(self, interval=2000)
        self.usb_timer.timeout.connect(self._check_usb)

        self._apply_mode(self.mode, startup=True)
        self._load_history()
        self._update_last_heard()
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

        self.leds = LedBar(LEDS)
        layout.addWidget(self.leds)

        self.screen = ReflectorScreen()
        layout.addWidget(self.screen, 0)

        mode_bar = QHBoxLayout()
        mode_bar.addWidget(QLabel("Modo:"))
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for key in ("int", "ext"):
            button = QPushButton(MODE_NAMES[key], checkable=True)
            button.setToolTip("Terminal Mode con gateway interno por WiFi (servidores G3)" if key == "int" else
                              "Terminal Mode con gateway externo por USB (DStarRepeater + ircDDBGateway en el PC)")
            self.mode_group.addButton(button)
            self.mode_buttons[key] = button
            mode_bar.addWidget(button)
            button.clicked.connect(lambda _=False, k=key: self.switch_mode(k))
        self.mode_hint = QLabel()
        self.mode_hint.setStyleSheet("color: #c77;")
        mode_bar.addWidget(self.mode_hint, 1)
        layout.addLayout(mode_bar)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Reflector:"))
        self.reflector_combo = QComboBox()
        self.reflector_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.reflector_combo.setMinimumContentsLength(12)
        bar.addWidget(self.reflector_combo, 1)
        self.change_btn = QPushButton("Cambiar")
        self.change_btn.clicked.connect(self.change_reflector)
        bar.addWidget(self.change_btn)
        self.unlink_btn = QPushButton("Desenlazar")
        self.unlink_btn.clicked.connect(self.unlink_reflector)
        bar.addWidget(self.unlink_btn)
        manage_btn = QPushButton("…")
        manage_btn.setToolTip("Gestionar reflectores")
        manage_btn.setFixedWidth(32)
        manage_btn.clicked.connect(self.manage_reflectors)
        bar.addWidget(manage_btn)
        layout.addLayout(bar)

        self.tabs = QTabWidget()
        self.history = QTableWidget(0, len(HISTORY_COLUMNS))
        self.history.setHorizontalHeaderLabels(HISTORY_COLUMNS)
        self.history.verticalHeader().setVisible(False)
        self.history.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history.setAlternatingRowColors(True)
        self.history.setWordWrap(False)
        header = self.history.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        self.tabs.addTab(self.history, "Histórico")

        self.log_view = QPlainTextEdit(readOnly=True)
        self.log_view.setMaximumBlockCount(3000)
        font = self.log_view.font()
        font.setFamily("monospace")
        self.log_view.setFont(font)
        self.tabs.addTab(self.log_view, "Log")
        layout.addWidget(self.tabs, 1)

        self.setCentralWidget(central)
        geometry = config.get("ui/geometry")
        if geometry:
            self.restoreGeometry(QByteArray(geometry))
        else:
            self.resize(560, 1000)

    def _build_menu(self):
        radio_menu = self.menuBar().addMenu("&Radio")
        self.connect_action = QAction("Conectar", self, triggered=self.connect_radio)
        self.disconnect_action = QAction("Desconectar", self, triggered=self.disconnect_radio)
        radio_menu.addAction(self.connect_action)
        radio_menu.addAction(self.disconnect_action)
        radio_menu.addSeparator()
        radio_menu.addAction(QAction("Ajustes…", self, triggered=self.open_settings))
        self.debug_action = QAction("Registrar CI-V de RX/TX en el log", self, checkable=True)
        self.debug_action.setChecked(config.get("ui/debug_civ"))
        self.debug_action.toggled.connect(lambda on: config.put("ui/debug_civ", on))
        radio_menu.addAction(self.debug_action)
        radio_menu.addSeparator()
        radio_menu.addAction(QAction("Salir", self, triggered=self.close))
        ref_menu = self.menuBar().addMenu("R&eflectores")
        ref_menu.addAction(QAction("Gestionar…", self, triggered=self.manage_reflectors))
        ref_menu.addAction(QAction("Actualizar estado", self, triggered=self._refresh_all))
        hist_menu = self.menuBar().addMenu("&Histórico")
        hist_menu.addAction(QAction("Vaciar histórico…", self, triggered=self.clear_history))
        help_menu = self.menuBar().addMenu("A&yuda")
        help_menu.addAction(QAction("Acerca de DStar705…", self, triggered=self.about))

    # --- logging ---------------------------------------------------------

    def _open_log(self):
        path = config.data_dir() / "dstar705.log"
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
            box.setWindowTitle("Modo EXT (USB + PC)")
            box.setIcon(QMessageBox.Information)
            box.setText("Para trabajar en modo EXT:")
            box.setInformativeText(
                "1. Conecta el cable USB de la radio al PC.\n"
                "2. En la radio: MENU > DV GW > Gateway Select = External Gateway USB (B).\n"
                f"3. Terminal/AP Call Sign = {config.terminal_call('ext') or '<indicativo> B'}.\n"
                "4. Activa Terminal Mode.\n\n"
                "La aplicación arrancará el gateway del PC (ircDDBGateway).")
            box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            if box.exec() != QMessageBox.Ok:
                self.mode_buttons[self.mode].setChecked(True)
                return
        else:
            box = QMessageBox(self)
            box.setWindowTitle("Modo INT (WiFi)")
            box.setIcon(QMessageBox.Information)
            box.setText("Para trabajar en modo INT:")
            box.setInformativeText(
                "1. En la radio: MENU > DV GW > Gateway Select = Internal Gateway (WLAN).\n"
                f"2. Terminal/AP Call Sign = {config.terminal_call('int') or '<indicativo> Z'}.\n"
                "3. Activa Terminal Mode.\n\n"
                "El cable USB ya no hace falta y se detendrá el gateway del PC.")
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
        self.change_btn.setText("Enlazar" if mode == "ext" else "Cambiar")
        self.change_btn.setToolTip("Enlaza el reflector con ircDDBGateway" if mode == "ext" else
                                   "Escribe el TO (UR) en la radio")
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
            self.log(f"Modo {MODE_NAMES[mode]}")
        self._fill_reflectors()
        self._refresh_screen_reflector()

    def _gateway_label(self):
        return "EXT · ircDDBGateway" if self._external_gateway() else "EXT · gateway integrado"

    def _external_gateway(self):
        return config.get("ext/backend") == "ircddbgateway"

    def _run_command(self, command):
        # Service commands only apply to the external ircDDBGateway stack
        if not command or not self._external_gateway():
            return
        args = shlex.split(command)
        if QProcess.startDetached(args[0], args[1:]):
            self.log(f"Ejecutado: {command}")
        else:
            self.log(f"No se pudo ejecutar: {command}")

    def _start_gateway(self):
        self._stop_gateway()
        terminal_call = config.terminal_call("ext")
        if not terminal_call:
            self.log("Gateway: esperando a leer tu indicativo (MY) de la radio")
            return
        if self._external_gateway():
            self.gateway = GatewayClient(config.get("ext/gateway_host"), config.get("ext/gateway_port"),
                                         config.get("ext/gateway_password"), terminal_call)
        else:
            self.gateway = LocalGateway(config.callsign(), terminal_call, config.gateway_call(),
                                        config.get("ext/usb_port"))
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
            self.log("Cable USB de la radio detectado" if present else "Cable USB de la radio NO detectado")
            if plugged_in:
                self._run_command(config.get("ext/usb_cmd"))
        self.leds["usb"].set("green" if present else "red")
        self._update_mode_hint()

    def _gateway_status(self, ok, links):
        changed = links != self.gw_links
        self.gw_ok = ok
        self.gw_links = links
        self.leds["gateway"].set("green" if ok else "amber", blink=not ok)
        if changed:
            linked = self.ext_reflector()
            self.log(f"Gateway enlazado a {linked}" if linked else "Gateway sin enlace")
            self._select_combo(linked)
            self.poller.refresh_now()
        self._refresh_screen_reflector()

    def _gateway_result(self, ok, detail):
        if ok:
            self.log(f"Gateway: {detail}")
            self._ensure_ext_ur()
        else:
            self.log(f"Error del gateway: {detail}")
            QMessageBox.warning(self, "Enlazar reflector", detail)

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
                hints.append(f"la radio sigue en INT ({self.r1})")
            else:
                hints.append(f"la radio no está en Terminal Mode INT (R1 {self.r1 or 'vacío'})")
        if self.mode == "ext" and self.usb_present is False:
            hints.append("conecta el USB")
        self.mode_hint.setText("⚠ revisar" if hints else "")
        self.mode_hint.setToolTip("; ".join(hints))
        self.screen.update_state(mode_warning="; ".join(hints))

    def _ensure_ext_ur(self):
        """In EXT the radio must transmit to CQCQCQ so the gateway sends it to the linked reflector."""
        if self.mode == "ext" and self.radio and self.radio_mode() == "ext" and self.to and self.to != EXT_UR:
            self.log(f"TO de la radio {self.to} → {EXT_UR} para el reflector enlazado")
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
        r.tx_message.connect(lambda m: self.log(f"Mensaje TX: '{m}'"))
        r.mode.connect(self._mode)
        r.transmitting.connect(self._transmitting)
        r.rx_started.connect(self._rx_started)
        r.rx_message.connect(self._rx_message)
        r.rx_ended.connect(self._rx_ended)
        r.to_write_result.connect(self._to_written)
        r.raw.connect(lambda line: self.debug_action.isChecked() and self.log(f"CI-V {line}"))
        r.start()

    def disconnect_radio(self, quiet=False):
        if self.radio:
            self.radio.stop()
            self.radio.deleteLater()
            self.radio = None
            if not quiet:
                self.log("Desconectado por el usuario")
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

    def _my_call(self, call, note):
        self.my_call = call
        base = call.split()[0] if call.split() else ""
        if base and not config.callsign():
            # First run: the station call sign is the radio's MY call sign
            config.put("station/callsign", base)
            self.log(f"Indicativo de la estación: {base} (leído de la radio)")
            if self.mode == "ext" and not self.gateway:
                self._start_gateway()
        self.log(f"MY: {call}" + (f" /{note}" if note else ""))
        self.screen.update_state(my_call=call)

    def _mode(self, mode):
        self.screen.update_state(mode=mode)
        if mode != "DV":
            self.log(f"Aviso: la radio está en {mode}, no en DV")

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
            item = {"to": ref, "name": "(no registrado)", "description": "Añádelo en Reflectores > Gestionar",
                    "server": ""}
        if self.mode == "ext":
            if item is not None:
                item = dict(item, server=self._gateway_label())
            elif self.gw_ok:
                item = {"to": "", "name": "Sin enlace", "description": "Elige un reflector y pulsa Enlazar",
                        "server": self._gateway_label()}
            else:
                item = {"to": "", "name": "Gateway PC", "description": "Esperando a ircDDBGateway…",
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
                self.log(f"El gateway ya está enlazado a {to}")
                return
            self.log(f"Pidiendo al gateway enlazar {to}…")
            self.gateway.link(to)
            return
        if not self.radio:
            return
        if to == self.to:
            self.log(f"{to} ya es el TO actual")
            return
        item = self.registry.get(to) or {}
        server = config.get("dstar/server")
        if item.get("server") and server and item["server"].lower() != server.lower():
            answer = QMessageBox.question(
                self, "Cambiar reflector",
                f"{to} se alcanza a través de {item['server']}, pero la radio usa {server}.\n\n"
                "El servidor no se puede cambiar por CI-V: hazlo en MENU > DV GW > Gateway Repeater "
                "y actualiza Radio > Ajustes.\n\n¿Escribir el TO de todas formas?")
            if answer != QMessageBox.Yes:
                return
        self.log(f"Cambiando TO a {to}…")
        self.radio.set_to(to)

    def unlink_reflector(self):
        if self.gateway and self.ext_reflector():
            self.log(f"Desenlazando {self.ext_reflector()}…")
            self.gateway.unlink()

    def _to_written(self, ok, detail):
        if ok and detail == EXT_UR:
            self.log(f"TO de la radio = {EXT_UR}")
        elif ok:
            self.log(f"TO cambiado a {detail}. Pulsa PTT un instante para registrarte en el reflector.")
        else:
            self.log(f"Error al cambiar el TO: {detail}")
            QMessageBox.warning(self, "Cambiar reflector", detail)

    def manage_reflectors(self):
        ReflectorsDialog(self.registry, self.mode, self).exec()

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            dialog.save()
            self.log("Ajustes guardados")
            if self.mode == "ext":
                self._start_gateway()
            self._update_mode_hint()
            self._refresh_screen_reflector()
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
            self.log(f"Respuesta del sistema: {calls.caller} → {calls.called}")
            return
        base = calls.caller.split()[0]
        self.log(f"RX {calls.caller}" + (f" /{calls.note}" if calls.note else "") +
                 f"  UR={calls.called} R1={calls.rpt1} R2={calls.rpt2}")
        self.rx_entry = self.storage.start_entry("RX", base, calls.note, self.current_reflector(),
                                                 calls.rpt1, calls.rpt2)
        self.rx_info = {"callsign": calls.caller, "suffix": calls.note, "started": time.time(), "live": True,
                        "name": "", "location": "", "message": ""}
        self.leds["rx"].set("green")
        self.screen.update_state(rx=self.rx_info)
        self.lookup.request(base)
        self._load_history()

    def _rx_message(self, message, caller):
        if self.rx_info and caller.split()[:1] == self.rx_info["callsign"].split()[:1]:
            self.rx_info["message"] = message
            self.storage.update_entry(self.rx_entry, message=message)
            self.screen.update_state(rx=self.rx_info)
            self.log(f"Mensaje de {caller}: {message}")
            self._load_history()

    def _rx_ended(self):
        self.leds["rx"].set("off")
        if self.rx_info and self.rx_info.get("live"):
            self.rx_info["live"] = False
            self.rx_info["ended"] = time.time()
            self.storage.update_entry(self.rx_entry, ended=self.rx_info["ended"])
            secs = int(self.rx_info["ended"] - self.rx_info["started"])
            self.log(f"Fin RX {self.rx_info['callsign']} ({secs}s)")
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
            self.log(f"Fin TX ({int(time.time() - self.tx_since)}s)")
            self.tx_entry = None
            # Our over counts as the reflector's last heard right away; the reflector's
            # dashboard catches up a few seconds later
            QTimer.singleShot(3000, self.poller.refresh_now)
        self.screen.update_state(tx=tx, tx_since=self.tx_since, to=ref or self.to)
        self._load_history()
        if not tx:
            self._update_last_heard()

    def _name_resolved(self, callsign, name, location):
        if self.rx_info and self.rx_info["callsign"].split()[0] == callsign:
            self.rx_info.update(name=self.rx_info.get("name") or name, location=location)
            self.screen.update_state(rx=self.rx_info)
            if self.rx_entry and self.rx_info.get("live"):
                self.storage.update_entry(self.rx_entry, name=name, location=location)
                self._load_history()

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
            values = [when, r["direction"], call, r["name"] or "", reflector, dur, r["message"] or "",
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
                          "ts": r["ended"] or r["started"], "via": ""})
        merged = sorted(remote + local, key=lambda e: e["ts"], reverse=True)
        # the same over can appear in both sources: keep one per call sign within a minute
        unique = []
        for e in merged:
            if not any(u["callsign"] == e["callsign"] and abs(u["ts"] - e["ts"]) < 60 for u in unique):
                unique.append(e)
        heard = [{"callsign": e["callsign"], "name": e["name"],
                  "time": time.strftime("%H:%M:%S", time.localtime(e["ts"]))} for e in unique[:4]]
        title = ("ÚLTIMOS EN EL REFLECTOR" if remote else "ÚLTIMOS OÍDOS AQUÍ EN ESTE REFLECTOR")
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
        self.screen.update_state(rx=self.rx_info)
        if not last["location"]:
            self.lookup.request(last["callsign"])

    def about(self):
        QMessageBox.about(
            self, "Acerca de DStar705",
            f"<b>DStar705 {__version__}</b><br>"
            "Control del IC-705 en D-STAR Terminal Mode y gateway integrado.<br><br>"
            f"Autor: {__author__}<br>"
            f'<a href="{__url__}">{__url__}</a><br><br>'
            "Licencia GPL-3.0-or-later. Basado en wfview (protocolo de red de Icom) "
            "y en DStarRepeater / ircDDBGateway de G4KLX.")

    def clear_history(self):
        if QMessageBox.question(self, "Histórico", "¿Borrar todo el histórico?") == QMessageBox.Yes:
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
