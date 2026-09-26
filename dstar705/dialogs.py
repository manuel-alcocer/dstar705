"""Settings and reflector management dialogs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QGroupBox, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from . import config
from .reflectors import normalize_to


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajustes")
        self.host = QLineEdit(config.get("radio/host"))
        self.port = QSpinBox(minimum=1, maximum=65535, value=config.get("radio/control_port"))
        self.user = QLineEdit(config.get("radio/username"))
        self.password = QLineEdit(config.get("radio/password"))
        self.password.setEchoMode(QLineEdit.Password)
        self.auto = QCheckBox("Conectar al arrancar")
        self.auto.setChecked(config.get("radio/auto_connect"))
        self.server = QLineEdit(config.get("dstar/server"))
        self.server.setToolTip("El mismo valor que MENU > DV GW > Gateway Repeater (Server/IP/Domain) en la radio.\n"
                               "La radio no lo expone por CI-V.")

        self.callsign = QLineEdit(config.callsign())
        self.callsign.setPlaceholderText("se lee de la radio (MY)")
        self.int_call = QLineEdit(config.get("int/terminal_call"))
        self.int_call.setPlaceholderText(config.terminal_call("int") or "indicativo + Z")
        self.ext_call = QLineEdit(config.get("ext/terminal_call"))
        self.ext_call.setPlaceholderText(config.terminal_call("ext") or "indicativo + B")
        self.backend = QComboBox()
        self.backend.addItem("Integrado (DStar705)", "builtin")
        self.backend.addItem("ircDDBGateway externo", "ircddbgateway")
        self.backend.setCurrentIndex(max(0, self.backend.findData(config.get("ext/backend"))))
        self.usb_port = QLineEdit(config.get("ext/usb_port"))
        self.usb_port.setPlaceholderText("automático")
        self.gw_host = QLineEdit(config.get("ext/gateway_host"))
        self.gw_port = QSpinBox(minimum=1, maximum=65535, value=config.get("ext/gateway_port"))
        self.gw_password = QLineEdit(config.get("ext/gateway_password"))
        self.gw_password.setEchoMode(QLineEdit.Password)
        self.gw_password.setPlaceholderText("vacío: leer de ~/.config/dstar/ircddbgateway")
        self.start_cmd = QLineEdit(config.get("ext/start_cmd"))
        self.stop_cmd = QLineEdit(config.get("ext/stop_cmd"))
        self.usb_cmd = QLineEdit(config.get("ext/usb_cmd"))

        radio_box = QGroupBox("Radio (WiFi)")
        form = QFormLayout(radio_box)
        form.addRow("Indicativo", self.callsign)
        form.addRow("IP / host de la radio", self.host)
        form.addRow("Puerto de control (UDP)", self.port)
        form.addRow("Usuario de red", self.user)
        form.addRow("Contraseña", self.password)
        form.addRow("", self.auto)

        int_box = QGroupBox("Modo INT (gateway interno, WiFi)")
        form = QFormLayout(int_box)
        form.addRow("Servidor Terminal Mode", self.server)
        form.addRow("Terminal/AP Call Sign", self.int_call)

        ext_box = QGroupBox("Modo EXT (gateway externo, USB + PC)")
        form = QFormLayout(ext_box)
        form.addRow("Terminal/AP Call Sign", self.ext_call)
        form.addRow("Gateway", self.backend)
        form.addRow("Puerto USB de datos", self.usb_port)
        form.addRow("ircDDBGateway host", self.gw_host)
        form.addRow("Puerto de control remoto", self.gw_port)
        form.addRow("Contraseña remota", self.gw_password)
        form.addRow("Comando al entrar en EXT", self.start_cmd)
        form.addRow("Comando al salir de EXT", self.stop_cmd)
        form.addRow("Comando al conectar el USB", self.usb_cmd)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(radio_box)
        layout.addWidget(int_box)
        layout.addWidget(ext_box)
        layout.addWidget(buttons)

    def save(self):
        config.put("radio/host", self.host.text().strip())
        config.put("radio/control_port", self.port.value())
        config.put("radio/username", self.user.text().strip())
        config.put("radio/password", self.password.text())
        config.put("radio/auto_connect", self.auto.isChecked())
        config.put("dstar/server", self.server.text().strip())
        config.put("station/callsign", self.callsign.text().upper().strip())
        config.put("int/terminal_call", self.int_call.text().upper().strip())
        config.put("ext/terminal_call", self.ext_call.text().upper().strip())
        config.put("ext/backend", self.backend.currentData())
        config.put("ext/usb_port", self.usb_port.text().strip())
        config.put("ext/gateway_host", self.gw_host.text().strip())
        config.put("ext/gateway_port", self.gw_port.value())
        config.put("ext/gateway_password", self.gw_password.text())
        config.put("ext/start_cmd", self.start_cmd.text().strip())
        config.put("ext/stop_cmd", self.stop_cmd.text().strip())
        config.put("ext/usb_cmd", self.usb_cmd.text().strip())


class ReflectorsDialog(QDialog):
    """List + edit form for the reflector registry."""

    def __init__(self, registry, default_via="int", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reflectores")
        self.default_via = default_via
        self.resize(560, 460)
        self.registry = registry
        self.editing = None

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._select)
        self.via = QComboBox()
        self.via.addItem("INT (WiFi, se escribe el TO)", "int")
        self.via.addItem("EXT (USB + PC, enlaza ircDDBGateway)", "ext")
        self.via.currentIndexChanged.connect(self._via_changed)
        self.to = QLineEdit(placeholderText="/XLX214D")
        self.server = QLineEdit(placeholderText="ej. server1.dstar.es")
        self.name = QLineEdit()
        self.description = QLineEdit()
        self.dashboard = QLineEdit(placeholderText="https://…/dashboard/")
        self.api = QLineEdit(placeholderText="https://…/dashboard/index.php (API JSON, opcional)")
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(70)

        form = QFormLayout()
        form.addRow("Tipo", self.via)
        form.addRow("TO / reflector", self.to)
        form.addRow("Servidor", self.server)
        form.addRow("Nombre", self.name)
        form.addRow("Descripción", self.description)
        form.addRow("Dashboard", self.dashboard)
        form.addRow("API", self.api)
        form.addRow("Notas", self.notes)

        new_btn = QPushButton("Nuevo")
        new_btn.clicked.connect(self._new)
        save_btn = QPushButton("Guardar")
        save_btn.clicked.connect(self._save)
        del_btn = QPushButton("Borrar")
        del_btn.clicked.connect(self._delete)
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        for b in (new_btn, save_btn, del_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(form)
        right_layout.addStretch(1)

        top = QHBoxLayout()
        top.addWidget(self.list, 2)
        top.addWidget(right, 3)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(buttons)
        self._reload()

    def _reload(self, select=None):
        self.list.clear()
        for item in self.registry.list():
            w = QListWidgetItem(f"[{item['via'].upper()}] {item['to']}  {item['name']}")
            w.setData(Qt.UserRole, item)
            self.list.addItem(w)
            if item["to"] == select:
                self.list.setCurrentItem(w)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)

    def _select(self, current, _previous=None):
        item = current.data(Qt.UserRole) if current else {}
        self.editing = item.get("to")
        self.via.setCurrentIndex(max(0, self.via.findData(item.get("via", self.default_via))))
        self._via_changed()
        self.to.setText(item.get("to", ""))
        self.server.setText(item.get("server", ""))
        self.name.setText(item.get("name", ""))
        self.description.setText(item.get("description", ""))
        self.dashboard.setText(item.get("dashboard", ""))
        self.api.setText(item.get("api", ""))
        self.notes.setPlainText(item.get("notes", ""))

    def _via_changed(self):
        ext = self.via.currentData() == "ext"
        self.to.setPlaceholderText("REF001 C" if ext else "/XLX214D")
        self.server.setEnabled(not ext)
        self.api.setEnabled(not ext)

    def _new(self):
        self.list.setCurrentItem(None)
        self._select(None)
        self.server.setText(config.get("dstar/server"))
        self.to.setFocus()

    def _save(self):
        try:
            to = normalize_to(self.to.text(), self.via.currentData())
        except ValueError as exc:
            QMessageBox.warning(self, "Reflectores", str(exc))
            return
        item = self.registry.upsert({
            "via": self.via.currentData(), "to": to, "server": self.server.text(), "name": self.name.text(),
            "description": self.description.text(), "dashboard": self.dashboard.text(),
            "api": self.api.text(), "notes": self.notes.toPlainText(),
        }, old_to=self.editing)
        self._reload(select=item["to"])

    def _delete(self):
        if not self.editing:
            return
        if QMessageBox.question(self, "Reflectores", f"¿Borrar {self.editing}?") == QMessageBox.Yes:
            self.registry.delete(self.editing)
            self.editing = None
            self._reload()
