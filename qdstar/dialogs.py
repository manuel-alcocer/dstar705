"""Settings and reflector management dialogs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QGroupBox, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from . import config, i18n
from .i18n import N_, tr
from .reflectors import normalize_to


class SettingsDialog(QDialog):
    def __init__(self, parent=None, my_note=None):
        """my_note: the note of the radio's MY call sign, None while it has not been read."""
        super().__init__(parent)
        self.setWindowTitle(tr("Settings"))
        self.host = QLineEdit(config.get("radio/host"))
        self.port = QSpinBox(minimum=1, maximum=65535, value=config.get("radio/control_port"))
        self.user = QLineEdit(config.get("radio/username"))
        self.password = QLineEdit(config.get("radio/password"))
        self.password.setEchoMode(QLineEdit.Password)
        self.auto = QCheckBox(tr("Connect on start-up"))
        self.auto.setChecked(config.get("radio/auto_connect"))
        self.server = QLineEdit(config.get("dstar/server"))
        self.server.setToolTip(tr("The same value as MENU > DV GW > Gateway Repeater (Server/IP/Domain) in the radio.\n"
                                  "The radio does not expose it over CI-V."))

        self.language = QComboBox()
        self.language.addItem(tr("System language"), "")
        for code, name in i18n.available_languages().items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(config.get("ui/language") or "")))

        self.callsign = QLineEdit(config.callsign())
        self.callsign.setPlaceholderText(tr("read from the radio (MY)"))
        self.radio_note = my_note
        self.note = QLineEdit(my_note or "")
        self.note.setMaxLength(4)
        self.note.setToolTip(tr("Shown after your call sign on the air, e.g. N0CALL /705.\n"
                                "It is written to the radio's selected MY call sign memory."))
        if my_note is None:
            self.note.setEnabled(False)
            self.note.setPlaceholderText(tr("connect the radio to change it"))
        self.int_call = QLineEdit(config.get("int/terminal_call"))
        self.int_call.setPlaceholderText(config.terminal_call("int") or tr("call sign + Z"))
        self.ext_call = QLineEdit(config.get("ext/terminal_call"))
        self.ext_call.setPlaceholderText(config.terminal_call("ext") or tr("call sign + B"))
        self.backend = QComboBox()
        self.backend.addItem(tr("Built-in (QDStar)"), "builtin")
        self.backend.addItem(tr("External ircDDBGateway"), "ircddbgateway")
        self.backend.setCurrentIndex(max(0, self.backend.findData(config.get("ext/backend"))))
        self.usb_port = QLineEdit(config.get("ext/usb_port"))
        self.usb_port.setPlaceholderText(tr("automatic"))
        self.gw_host = QLineEdit(config.get("ext/gateway_host"))
        self.gw_port = QSpinBox(minimum=1, maximum=65535, value=config.get("ext/gateway_port"))
        self.gw_password = QLineEdit(config.get("ext/gateway_password"))
        self.gw_password.setEchoMode(QLineEdit.Password)
        self.gw_password.setPlaceholderText(tr("empty: read from ~/.config/dstar/ircddbgateway"))
        self.start_cmd = QLineEdit(config.get("ext/start_cmd"))
        self.stop_cmd = QLineEdit(config.get("ext/stop_cmd"))
        self.usb_cmd = QLineEdit(config.get("ext/usb_cmd"))

        radio_box = QGroupBox(tr("Radio (WiFi)"))
        form = QFormLayout(radio_box)
        form.addRow(tr("Call sign"), self.callsign)
        form.addRow(tr("Note (/…)"), self.note)
        form.addRow(tr("Radio IP / host"), self.host)
        form.addRow(tr("Control port (UDP)"), self.port)
        form.addRow(tr("Network user"), self.user)
        form.addRow(tr("Password"), self.password)
        form.addRow("", self.auto)

        int_box = QGroupBox(tr("INT mode (internal gateway, WiFi)"))
        form = QFormLayout(int_box)
        form.addRow(tr("Terminal Mode server"), self.server)
        form.addRow("Terminal/AP Call Sign", self.int_call)

        ext_box = QGroupBox(tr("EXT mode (external gateway, USB + PC)"))
        form = QFormLayout(ext_box)
        form.addRow("Terminal/AP Call Sign", self.ext_call)
        form.addRow("Gateway", self.backend)
        form.addRow(tr("USB data port"), self.usb_port)
        form.addRow("ircDDBGateway host", self.gw_host)
        form.addRow(tr("Remote control port"), self.gw_port)
        form.addRow(tr("Remote password"), self.gw_password)
        form.addRow(tr("Command when entering EXT"), self.start_cmd)
        form.addRow(tr("Command when leaving EXT"), self.stop_cmd)
        form.addRow(tr("Command when the USB is plugged in"), self.usb_cmd)
        # Only the external ircDDBGateway uses these fields
        self.ext_form = form
        self.external_only = [self.gw_host, self.gw_port, self.gw_password, self.start_cmd, self.stop_cmd, self.usb_cmd]
        self.backend.currentIndexChanged.connect(self._backend_changed)
        self._backend_changed()

        self.check_updates = QCheckBox(tr("Check for new versions on start-up"))
        self.check_updates.setChecked(config.get("updates/check"))
        self.dprs_all = QCheckBox(tr("D-PRS tab with every report received, including relayed ones"))
        self.dprs_all.setToolTip(tr("Stations such as ED2YAV relay APRS positions and weather stations"))
        self.dprs_all.setChecked(config.get("dprs/show_all"))

        self.tray = QCheckBox(tr("Icon in the system tray"))
        self.tray.setChecked(config.get("ui/tray"))
        self.tray_notify = QCheckBox(tr("Notify when a station comes on air"))
        self.tray_notify.setToolTip(tr("Only while the QDStar window is not in front"))
        self.tray_notify.setChecked(config.get("ui/tray_notify"))
        self.close_to_tray = QCheckBox(tr("Closing the window keeps QDStar running in the tray"))
        self.close_to_tray.setToolTip(tr("Quit from the tray menu or from Radio > Quit"))
        self.close_to_tray.setChecked(config.get("ui/close_to_tray"))
        self.tray.toggled.connect(self._tray_changed)
        self._tray_changed()

        self.aprs_enabled = QCheckBox(tr("Send my D-PRS position to APRS-IS (aprs.fi) after every over"))
        self.aprs_enabled.setToolTip(tr("Only when the radio sends its position (GPS TX Mode = D-PRS).\n"
                                        "The APRS-IS passcode is computed from your call sign."))
        self.aprs_enabled.setChecked(config.get("aprs/enabled"))
        self.aprs_received = QCheckBox(tr("Also send the positions of the stations heard"))
        self.aprs_received.setToolTip(tr("Positions relayed from APRS are never sent back.\n"
                                         "The station's own gateway may already forward them."))
        self.aprs_received.setChecked(config.get("aprs/received"))
        self.aprs_server = QLineEdit(config.get("aprs/server"))
        self.aprs_server.setPlaceholderText("rotate.aprs2.net:14580")
        self.aprs_enabled.toggled.connect(self._aprs_changed)
        self._aprs_changed()

        aprs_box = QGroupBox("APRS-IS")
        form = QFormLayout(aprs_box)
        form.addRow("", self.aprs_enabled)
        form.addRow("", self.aprs_received)
        form.addRow(tr("Server"), self.aprs_server)

        ui_box = QGroupBox(tr("Interface"))
        form = QFormLayout(ui_box)
        form.addRow(tr("Language"), self.language)
        form.addRow("", self.check_updates)
        form.addRow("", self.dprs_all)

        tray_box = QGroupBox(tr("System tray"))
        form = QFormLayout(tray_box)
        form.addRow("", self.tray)
        form.addRow("", self.tray_notify)
        form.addRow("", self.close_to_tray)

        # One tab per topic: all the groups at once no longer fit on a laptop screen
        self.tabs = QTabWidget()
        pages = {}
        for key, title, boxes in (("interface", tr("Interface"), (ui_box, tray_box)),
                                  ("radio", tr("Radio"), (radio_box,)),
                                  ("modes", "INT / EXT", (int_box, ext_box)),
                                  ("aprs", "APRS-IS", (aprs_box,))):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            for box in boxes:
                page_layout.addWidget(box)
            page_layout.addStretch(1)
            pages[key] = page
            self.tabs.addTab(page, title)
        if not config.get("radio/username"):
            self.tabs.setCurrentWidget(pages["radio"])    # first run: the radio is what is missing

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

    def _tray_changed(self):
        for field in (self.tray_notify, self.close_to_tray):
            field.setEnabled(self.tray.isChecked())

    def _aprs_changed(self):
        for field in (self.aprs_received, self.aprs_server):
            field.setEnabled(self.aprs_enabled.isChecked())

    def _backend_changed(self):
        external = self.backend.currentData() == "ircddbgateway"
        for field in self.external_only:
            self.ext_form.setRowVisible(field, external)
        self.adjustSize()

    def new_note(self):
        """The MY note to write to the radio, or None when unchanged."""
        if self.radio_note is None:
            return None
        note = self.note.text().strip()
        return note if note != self.radio_note else None

    def save(self):
        config.put("radio/host", self.host.text().strip())
        config.put("radio/control_port", self.port.value())
        config.put("radio/username", self.user.text().strip())
        config.put("radio/password", self.password.text())
        config.put("radio/auto_connect", self.auto.isChecked())
        config.put("dstar/server", self.server.text().strip())
        if self.language.currentData() != (config.get("ui/language") or ""):
            config.put("ui/language", self.language.currentData())
            QMessageBox.information(self, tr("Language"), tr("The new language is used after restarting QDStar."))
        config.put("updates/check", self.check_updates.isChecked())
        config.put("dprs/show_all", self.dprs_all.isChecked())
        config.put("ui/tray", self.tray.isChecked())
        config.put("ui/tray_notify", self.tray_notify.isChecked())
        config.put("ui/close_to_tray", self.close_to_tray.isChecked())
        config.put("aprs/enabled", self.aprs_enabled.isChecked())
        config.put("aprs/received", self.aprs_received.isChecked())
        config.put("aprs/server", self.aprs_server.text().strip())
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
        self.setWindowTitle(tr("Reflectors"))
        self.default_via = default_via
        self.resize(660, 470)
        self.registry = registry
        self.editing = None

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._select)
        self.via = QComboBox()
        self.via.addItem(tr("INT (WiFi, writes the TO)"), "int")
        self.via.addItem(tr("EXT (USB + PC, linked by the gateway)"), "ext")
        self.via.currentIndexChanged.connect(self._via_changed)
        self.to = QLineEdit(placeholderText="/XLX214D")
        self.server = QLineEdit(placeholderText=tr("e.g. server1.dstar.es"))
        self.name = QLineEdit()
        self.description = QLineEdit()
        self.dashboard = QLineEdit(placeholderText="https://…/dashboard/")
        self.api = QLineEdit(placeholderText=tr("https://…/dashboard/index.php (JSON API, optional)"))
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(70)

        self.origin = QLabel(wordWrap=True)
        self.origin.setStyleSheet("color: palette(mid);")
        form = QFormLayout()
        form.addRow(self.origin)
        form.addRow(tr("Type"), self.via)
        form.addRow("TO / reflector", self.to)
        form.addRow(tr("Server"), self.server)
        form.addRow(tr("Name"), self.name)
        form.addRow(tr("Description"), self.description)
        form.addRow("Dashboard", self.dashboard)
        form.addRow("API", self.api)
        form.addRow(tr("Notes"), self.notes)

        new_btn = QPushButton(tr("New"))
        new_btn.clicked.connect(self._new)
        save_btn = QPushButton(tr("Save"))
        save_btn.clicked.connect(self._save)
        del_btn = QPushButton(tr("Delete"))
        del_btn.clicked.connect(self._delete)
        self.copy_btn = QPushButton(tr("Copy to my list"))
        self.copy_btn.setToolTip(tr("Reflectors from other sources are read only: copy one to change it"))
        self.copy_btn.clicked.connect(self._copy)
        self.save_btn, self.del_btn = save_btn, del_btn
        sources_btn = QPushButton(tr("Sources…"))
        sources_btn.setToolTip(tr("Reflector lists from QDStar, a URL, a file or a git repository"))
        sources_btn.clicked.connect(lambda: SourcesDialog(self.registry, self).exec())
        export_btn = QPushButton(tr("Export my list…"))
        export_btn.setToolTip(tr("Save your own reflectors as JSON, to share them or publish them as a source"))
        export_btn.clicked.connect(self._export)
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        for b in (new_btn, save_btn, del_btn, self.copy_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        extra = QHBoxLayout()
        extra.addWidget(sources_btn)
        extra.addWidget(export_btn)
        extra.addStretch(1)
        self.form_fields = [self.via, self.to, self.server, self.name, self.description, self.dashboard, self.api,
                            self.notes]
        registry.changed.connect(self._registry_changed)

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
        layout.addLayout(extra)
        layout.addLayout(buttons)
        self._reload()

    def _reload(self, select=None):
        self.list.clear()
        for item in self.registry.list():
            w = QListWidgetItem(f"[{item['via'].upper()}] {item['to']}  {item['name']}")
            w.setData(Qt.UserRole, item)
            if item.get("source"):
                w.setForeground(self.palette().placeholderText())
                w.setToolTip(tr("From: {origin} (read only)", origin=item["origin"]))
            self.list.addItem(w)
            if item["to"] == select:
                self.list.setCurrentItem(w)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)

    def _select(self, current, _previous=None):
        item = current.data(Qt.UserRole) if current else {}
        self.editing = item.get("to")
        self.selected = item
        from_source = bool(item.get("source"))
        self.origin.setText(tr("From: {origin} (read only). Copy it to your list to change it.", origin=item["origin"])
                            if from_source else tr("Your own reflector") if item else "")
        for field in self.form_fields:
            field.setEnabled(not from_source)
        self.save_btn.setEnabled(not from_source)
        self.del_btn.setEnabled(bool(item) and not from_source)
        self.copy_btn.setEnabled(from_source)
        self.via.setCurrentIndex(max(0, self.via.findData(item.get("via", self.default_via))))
        self._via_changed()
        self.to.setText(item.get("to", ""))
        self.server.setText(item.get("server", ""))
        self.name.setText(item.get("name", ""))
        self.description.setText(item.get("description", ""))
        self.dashboard.setText(item.get("dashboard", ""))
        self.api.setText(item.get("api", ""))
        self.notes.setPlainText(item.get("notes", ""))

    def _registry_changed(self):
        self._reload(select=self.editing)

    def _copy(self):
        item = getattr(self, "selected", None) or {}
        if item.get("source"):
            copied = self.registry.upsert(item)
            self._reload(select=copied["to"])

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Export my list"), "reflectors.json", "JSON (*.json)")
        if not path:
            return
        import json
        try:
            with open(path, "w", encoding="utf-8") as out:
                json.dump(self.registry.local(), out, indent=2, ensure_ascii=False)
        except OSError as exc:
            QMessageBox.warning(self, tr("Export my list"), str(exc))
            return
        QMessageBox.information(self, tr("Export my list"), tr("{n} reflectors saved in {path}", n=len(self.registry.local()),
                                                             path=path))

    def _via_changed(self):
        ext = self.via.currentData() == "ext"
        self.to.setPlaceholderText("REF001 C" if ext else "/XLX214D")
        editable = not (getattr(self, "selected", None) or {}).get("source")
        self.server.setEnabled(not ext and editable)
        self.api.setEnabled(not ext and editable)

    def _new(self):
        self.list.setCurrentItem(None)
        self._select(None)
        self.origin.setText(tr("Your own reflector"))
        self.server.setText(config.get("dstar/server"))
        self.to.setFocus()

    def _save(self):
        try:
            to = normalize_to(self.to.text(), self.via.currentData())
        except ValueError as exc:
            QMessageBox.warning(self, tr("Reflectors"), str(exc))
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
        if QMessageBox.question(self, tr("Reflectors"), tr("Delete {reflector}?", reflector=self.editing)) == QMessageBox.Yes:
            self.registry.delete(self.editing)
            self.editing = None
            self._reload()


class SourcesDialog(QDialog):
    """The sources of reflector lists: enable, add, edit, remove, refresh."""

    def __init__(self, registry, parent=None):
        super().__init__(parent)
        from . import sources
        self.sources = sources
        self.manager = registry.sources
        self.setWindowTitle(tr("Reflector sources"))
        self.resize(560, 320)
        intro = QLabel(tr("Reflectors from these sources are added to your own list, read only. "
                          "When a reflector is in several places, your own copy wins."), wordWrap=True)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._toggled)
        self.list.itemDoubleClicked.connect(lambda _item: self._edit())
        self.list.currentRowChanged.connect(lambda _row: self._update_buttons())
        add_btn = QPushButton(tr("Add"))
        menu = QMenu(add_btn)
        for kind, label in sources.TYPES.items():
            menu.addAction(tr(label), lambda k=kind: self._add(k))
        add_btn.setMenu(menu)
        self.edit_btn = QPushButton(tr("Edit…"), clicked=self._edit)
        self.remove_btn = QPushButton(tr("Remove"), clicked=self._remove)
        refresh_btn = QPushButton(tr("Update all"), clicked=lambda: self.manager.refresh())
        close_btn = QPushButton(tr("Close"), clicked=self.accept)
        buttons = QHBoxLayout()
        for b in (add_btn, self.edit_btn, self.remove_btn, refresh_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.list)
        layout.addLayout(buttons)
        self.manager.status_changed.connect(self._status_changed)
        self._reload()

    def _status_changed(self, _source_id):
        self._reload()

    def _status_text(self, source):
        import time
        if source["id"] in self.manager.busy:
            return tr("updating…")
        st = self.manager.status.get(source["id"])
        if not st:
            return tr("not updated yet") if source.get("enabled", True) else tr("off")
        count = st.get("count")
        text = "" if count is None else tr("1 reflector") if count == 1 else tr("{n} reflectors", n=count)
        if source["type"] != "builtin" and st.get("when"):
            text += " · " + time.strftime("%d/%m %H:%M", time.localtime(st["when"]))
        if not st["ok"]:
            text = "⚠ " + st["message"] + (f" ({text})" if text else "")
        elif st.get("message"):
            text += " · " + st["message"]
        return text

    def _reload(self):
        row = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for source in self.manager.sources():
            kind = tr(self.sources.TYPES.get(source["type"], "")) if source["type"] != "builtin" else ""
            label = self.sources.display_name(source) + (f"  [{kind}]" if kind else "")
            status = self._status_text(source)
            item = QListWidgetItem(f"{label}\n    {status}")
            item.setToolTip(f"{label}\n{status}")      # long git errors do not fit in the row
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if source.get("enabled", True) else Qt.Unchecked)
            item.setData(Qt.UserRole, source["id"])
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.list.setCurrentRow(min(max(row, 0), self.list.count() - 1))
        self._update_buttons()

    def _current(self):
        item = self.list.currentItem()
        source_id = item.data(Qt.UserRole) if item else None
        return next((s for s in self.manager.sources() if s["id"] == source_id), None)

    def _update_buttons(self):
        source = self._current()
        editable = bool(source) and source["type"] != "builtin"
        self.edit_btn.setEnabled(editable)
        self.remove_btn.setEnabled(editable)

    def _toggled(self, item):
        sources = self.manager.sources()
        for source in sources:
            if source["id"] == item.data(Qt.UserRole):
                source["enabled"] = item.checkState() == Qt.Checked
                enabled = source["enabled"]
        self.manager.set_sources(sources)
        if enabled:
            self.manager.refresh(item.data(Qt.UserRole))
        self._reload()

    def _add(self, kind):
        source = self.sources.new_source(kind)
        if SourceEditDialog(source, self).exec():
            self.manager.set_sources(self.manager.sources() + [source])
            self.manager.refresh(source["id"])
            self._reload()
            self.list.setCurrentRow(self.list.count() - 1)

    def _edit(self):
        source = self._current()
        if not source or source["type"] == "builtin":
            return
        if SourceEditDialog(source, self).exec():
            self.manager.set_sources([source if s["id"] == source["id"] else s for s in self.manager.sources()])
            self.manager.refresh(source["id"])
            self._reload()

    def _remove(self):
        source = self._current()
        if not source or source["type"] == "builtin":
            return
        if QMessageBox.question(self, tr("Reflector sources"),
                                tr("Remove {source}? Its reflectors disappear from the list.",
                                   source=self.sources.display_name(source))) == QMessageBox.Yes:
            self.manager.set_sources([s for s in self.manager.sources() if s["id"] != source["id"]])
            self._reload()


class SourceEditDialog(QDialog):
    """One source: URL, file or git repository (with an optional user and password/token)."""

    def __init__(self, source, parent=None):
        super().__init__(parent)
        from . import credentials, sources
        self.credentials, self.sources = credentials, sources
        self.source = source
        kind = source["type"]
        self.setWindowTitle(tr(sources.TYPES[kind]))
        self.setMinimumWidth(480)
        self.name = QLineEdit(source.get("name", ""), placeholderText=tr("optional"))
        self.location = QLineEdit(source.get("location", ""))
        form = QFormLayout()
        form.addRow(tr("Name"), self.name)
        if kind == "url":
            self.location.setPlaceholderText("https://example.org/reflectors.json")
            form.addRow("URL", self.location)
        elif kind == "file":
            browse = QPushButton(tr("Browse…"), clicked=self._browse)
            row = QHBoxLayout()
            row.addWidget(self.location, 1)
            row.addWidget(browse)
            form.addRow(tr("File"), row)
        else:
            self.location.setPlaceholderText("https://github.com/user/repo.git  ·  git@host:user/repo.git")
            self.branch = QLineEdit(source.get("branch", ""), placeholderText=tr("the default one"))
            self.path = QLineEdit(source.get("path", "") or "reflectors.json")
            self.username = QLineEdit(source.get("username", ""), placeholderText=tr("only for private repositories"))
            self.secret = QLineEdit(echoMode=QLineEdit.Password)
            self.had_secret = bool(credentials.load(sources.secret_key(source)))
            self.secret.setPlaceholderText(tr("unchanged") if self.had_secret else tr("only for private repositories"))
            self.clear_secret = QCheckBox(tr("Forget the saved password or token"))
            self.clear_secret.setVisible(self.had_secret)
            where = (tr("It is kept in the system keyring.") if credentials.available() else
                     tr("⚠ No system keyring available: it would be kept in QDStar's settings file."))
            form.addRow(tr("Repository"), self.location)
            form.addRow(tr("Branch"), self.branch)
            form.addRow(tr("File in the repository"), self.path)
            form.addRow(tr("User"), self.username)
            form.addRow(tr("Password or token"), self.secret)
            form.addRow("", self.clear_secret)
            note = QLabel(where + " " + tr("With SSH (git@…), your own SSH keys are used."), wordWrap=True)
            note.setStyleSheet("color: palette(mid);")
            form.addRow("", note)
        hint = QLabel(tr("The file is a JSON list of reflectors, like the one Export my list saves."), wordWrap=True)
        hint.setStyleSheet("color: palette(mid);")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("File"), self.location.text(), "JSON (*.json);;* (*)")
        if path:
            self.location.setText(path)

    def _save(self):
        if not self.location.text().strip():
            QMessageBox.warning(self, self.windowTitle(), tr("Fill in where the list is."))
            return
        self.source.update(name=self.name.text().strip(), location=self.location.text().strip())
        if self.source["type"] == "git":
            self.source.update(branch=self.branch.text().strip(), path=self.path.text().strip() or "reflectors.json",
                               username=self.username.text().strip())
            key = self.sources.secret_key(self.source)
            if self.clear_secret.isChecked():
                self.credentials.store(key, "")
            elif self.secret.text():
                if self.credentials.store(key, self.secret.text()) == "settings":
                    QMessageBox.warning(self, self.windowTitle(),
                                        tr("There is no system keyring: the password is kept in QDStar's settings file."))
        self.accept()


SYMBOL_NAMES = {
    # translated when shown
    "/-": N_("House"), "\\-": N_("House (HF)"), "/>": N_("Car"), "/[": N_("Person"), "/b": N_("Bicycle"), "/k": N_("Pick-up"),
    "/v": N_("Van"), "/u": N_("Truck"), "/s": N_("Ship"), "/Y": N_("Sailboat"), "/r": N_("Antenna"), "/R": N_("Motorhome"),
    "/j": N_("Jeep"), "/<": N_("Motorbike"), "/'": N_("Small aircraft"), "/_": N_("Weather"),
}
SSID_CHOICES = ["---", "-0"] + [f"-{n}" for n in range(1, 16)] + [f"-{chr(c)}" for c in range(65, 91)]
COMMENT_LENGTH = 43


def format_position(lat, lon):
    def part(value, positive, negative, width):
        deg = int(abs(value))
        minutes = (abs(value) - deg) * 60
        return f"{deg:0{width}d}° {minutes:06.3f}' {positive if value >= 0 else negative}"
    return f"{part(lat, 'N', 'S', 2)}, {part(lon, 'E', 'W', 3)}"


class DprsDialog(QDialog):
    """Own D-PRS position settings, read from and written to the radio over CI-V."""

    READ = ["0281", "0286", "0287", "0290", "0291", "0292", "0293", "0294", "0295", "0297"]

    def __init__(self, radio, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QLabel
        from . import civ
        self.civ = civ
        self.radio = radio
        self.setWindowTitle(tr("D-PRS position"))
        self.values = {}
        self.pending_check = {}

        self.send = QCheckBox(tr("Send my position with every over (GPS TX Mode = D-PRS)"))
        self.source = QComboBox()
        self.source.addItem(tr("The radio's internal GPS"), 1)
        self.source.addItem(tr("Manual position"), 2)
        self.source.currentIndexChanged.connect(self._source_changed)
        self.lat = QLineEdit(placeholderText="40.41680")
        self.lon = QLineEdit(placeholderText="-3.70380")
        self.alt = QLineEdit(placeholderText=tr("optional, metres"))
        self.locator = QLineEdit(placeholderText="IN80DK")
        loc_btn = QPushButton(tr("Use locator"))
        loc_btn.setToolTip(tr("Centre of the grid square: announces an area, not your exact home"))
        loc_btn.clicked.connect(self._from_locator)
        self.pretty = QLabel()
        self.symbol = QComboBox()
        self.ssid = QComboBox()
        self.ssid.addItems(SSID_CHOICES)
        self.comment = QLineEdit()
        self.comment.setMaxLength(COMMENT_LENGTH)
        self.status = QLabel(tr("Reading the radio's settings…"))
        for field in (self.lat, self.lon):
            field.textChanged.connect(self._update_pretty)

        loc_row = QHBoxLayout()
        loc_row.addWidget(self.locator, 1)
        loc_row.addWidget(loc_btn)
        form = QFormLayout()
        form.addRow("", self.send)
        form.addRow(tr("Position source"), self.source)
        form.addRow(tr("Latitude (degrees)"), self.lat)
        form.addRow(tr("Longitude (degrees, west negative)"), self.lon)
        form.addRow("", self.pretty)
        form.addRow(tr("Altitude"), self.alt)
        form.addRow(tr("Locator"), loc_row)
        form.addRow(tr("Symbol"), self.symbol)
        form.addRow("SSID", self.ssid)
        form.addRow(tr("Comment"), self.comment)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self.save_btn = buttons.button(QDialogButtonBox.Save)
        self.save_btn.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status)
        layout.addWidget(buttons)

        radio.setting_received.connect(self._on_setting)
        for number in self.READ:
            radio.read_setting(number)

    # --- reading ---------------------------------------------------------------

    def _on_setting(self, number, data):
        self.values[number] = data
        if number in self.pending_check:
            expected = self.pending_check.pop(number)
            if data != expected:
                self.status.setText("⚠ " + tr("The radio did not accept setting {number}", number=number))
            elif not self.pending_check:
                self.status.setText(tr("Saved in the radio and verified ✓"))
            return
        if all(n in self.values for n in self.READ):
            self._fill()

    def _fill(self):
        v = self.values
        self.send.setChecked(v["0287"][:1] == b"\x01")
        self.source.setCurrentIndex(1 if v["0281"][:1] == b"\x02" else 0)
        lat = self.civ.decode_latitude(v["0286"][:5])
        lon = self.civ.decode_longitude(v["0286"][5:11])
        alt = self.civ.decode_altitude(v["0286"][11:15])
        self.lat.setText("" if lat is None else f"{lat:.5f}")
        self.lon.setText("" if lon is None else f"{lon:.5f}")
        self.alt.setText("" if alt is None else f"{alt:g}")
        self.symbol.clear()
        for i, number in enumerate(("0291", "0292", "0293", "0294")):
            code = v[number][:2].decode("latin-1")
            self.symbol.addItem(tr("No. {n}: {name} ({code})", n=i + 1, name=tr(SYMBOL_NAMES.get(code, "Symbol")), code=code), i)
        self.symbol.setCurrentIndex(min(v["0290"][0], 3) if v["0290"] else 0)
        self.ssid.setCurrentIndex(min(v["0295"][0], len(SSID_CHOICES) - 1) if v["0295"] else 0)
        self.comment.setText(v["0297"].decode("latin-1").rstrip())
        self._source_changed()
        self.save_btn.setEnabled(True)
        self.status.setText(tr("Settings read from the radio"))

    # --- editing -----------------------------------------------------------------

    def _source_changed(self):
        manual = self.source.currentData() == 2
        for w in (self.lat, self.lon, self.alt, self.locator):
            w.setEnabled(manual)

    def _from_locator(self):
        try:
            lat, lon = self.civ.locator_to_latlon(self.locator.text())
        except ValueError as exc:
            QMessageBox.warning(self, tr("D-PRS position"), str(exc))
            return
        self.lat.setText(f"{lat:.5f}")
        self.lon.setText(f"{lon:.5f}")

    def _position(self):
        lat, lon = float(self.lat.text().replace(",", ".")), float(self.lon.text().replace(",", "."))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(tr("Coordinates out of range"))
        alt = float(self.alt.text().replace(",", ".")) if self.alt.text().strip() else None
        return lat, lon, alt

    def _update_pretty(self):
        try:
            lat, lon, _ = self._position()
            self.pretty.setText(format_position(lat, lon))
        except ValueError:
            self.pretty.setText("")

    def _save(self):
        writes = {"0289": b"\x00"}     # TX Format = Position (own station)
        if self.source.currentData() == 2:
            try:
                lat, lon, alt = self._position()
            except ValueError:
                QMessageBox.warning(self, tr("D-PRS position"), tr("Check the latitude, longitude and altitude."))
                return
            writes["0286"] = self.civ.encode_position(lat, lon, alt)
        writes["0281"] = bytes([self.source.currentData()])
        writes["0290"] = bytes([self.symbol.currentData() or 0])
        writes["0295"] = bytes([self.ssid.currentIndex()])
        writes["0296"] = b"\x00"
        writes["0297"] = self.comment.text().ljust(COMMENT_LENGTH)[:COMMENT_LENGTH].encode("latin-1", "replace")
        writes["0287"] = b"\x01" if self.send.isChecked() else b"\x00"
        self.pending_check = {}
        for number, data in writes.items():
            self.radio.write_setting(number, data)
            self.pending_check[number] = data
            self.radio.read_setting(number)
        self.status.setText(tr("Saving in the radio…"))
