# QDStar

Desktop controller and built-in D-STAR gateway for the Icom **IC-705** in
**Terminal Mode**, for Windows and Linux (x86-64 and ARM64 mini PCs).

- It talks to the radio over **WiFi** with the Icom network protocol
  (control + CI-V streams, no audio). This replaces wfview for D-STAR work.
- It includes its own **gateway** for Terminal Mode over USB, so
  DStarRepeater, ircDDBGateway and other services are not needed. It links
  reflectors over **DPlus** (REF), **DCS** (DCS, XLX) and **DExtra** (XRF).

## Features

- Status LEDs: radio session, CI-V, Internet, USB, gateway, reflector, linked, RX, TX.
- A 4:3 "screen" showing the selected reflector with its state and nodes,
  the station on air or the last one heard (name and location from
  radioid.net), and the reflector's last heard list.
- Conversation history (SQLite) and application log.
- **D-PRS tab** with every position, object, item and weather report received,
  including the ones relayed by stations such as ED2YAV, with distance,
  direction and the relaying station; and a **Weather tab** with a card per
  weather station (temperature, humidity, pressure, wind, rain). Both can be
  turned off in the settings.
- Update notice: on start-up (and daily) QDStar checks GitHub for a new release
  and offers the right download for your system. You can turn it off in the settings.
- **D-PRS positions**: shows the position and distance of the station on air,
  and manages your own D-PRS beacon from *Radio > Posición D-PRS…*. You can
  turn it on or off, choose the internal GPS or a manual position (or a
  locator, to announce only an area), and set the symbol, SSID and comment.
- Two working modes:
  - **INT**: Terminal Mode with the radio's internal gateway (WLAN) and a G3
    server such as `server1.dstar.es`. Changing reflector writes the TO (UR)
    over CI-V.
  - **EXT**: Terminal Mode with an external gateway over USB, provided by
    QDStar itself. Reflectors are linked with the *Enlazar* button.

## Download

Get the latest build from the **Releases** page:

| System | File |
|---|---|
| Windows 10/11 x64 | `QDStar-x.y.z-windows-x64-setup.exe` (installer) or `…-portable.zip` |
| Linux x86-64 | `qdstar_x.y.z_amd64.deb`, `QDStar-x.y.z-x86_64.AppImage` or `.tar.gz` |
| Linux ARM64 (Raspberry Pi OS bookworm, Debian 12+, Ubuntu 22.04+) | `qdstar_x.y.z_arm64.deb`, `QDStar-x.y.z-aarch64.AppImage` or `.tar.gz` |

On Linux your user needs access to the radio's USB serial ports:
`sudo usermod -aG dialout $USER` (Debian, Ubuntu, Raspberry Pi OS) or
`uucp` (Arch). Log out and back in afterwards.

## Radio setup

1. **WLAN**: connect the radio to your network and give it a fixed IP.
   In *Remote Settings*, set **Network Control** to ON and create a
   **Network User** (user + password).
2. On first run QDStar asks for the radio's IP, user and password. It reads
   your call sign from the radio (MY call sign).
3. **INT mode**: set *DV GW > Gateway Select* to **Internal Gateway (WLAN)**,
   the *Gateway Repeater* to your G3 server, and the *Terminal/AP Call Sign*
   to `<call> Z`. Then turn Terminal Mode on.
4. **EXT mode**: connect the USB cable, set *Gateway Select* to
   **External Gateway USB (B)** and the *Terminal/AP Call Sign* to `<call> B`.
   Then turn Terminal Mode on.
5. EXT mode uses DPlus (REF reflectors), which needs your call sign
   registered in the D-STAR trust network (regist.dstargateway.org).

Close the app before switching the radio off: it ends the network session
cleanly. A session left open can keep the radio's network server busy until
the radio is power cycled.

## Running from source

```sh
pip install PySide6 certifi
python -m qdstar
```

## Default reflectors

On first run the app loads the reflector list shipped in
[`qdstar/default_reflectors.json`](qdstar/default_reflectors.json).
After that the list lives in your data folder, and you can edit it from
*Reflectores > Gestionar*.

**Want more reflectors in the default list? Open a pull request** that adds
entries to `default_reflectors.json`:

```json
{
  "via": "ext",
  "to": "REF001 C",
  "server": "",
  "name": "Short name",
  "description": "One line shown on the screen",
  "notes": "",
  "dashboard": "http://ref001.dstargateway.org/",
  "api": ""
}
```

- `via`: `int` (Terminal Mode through a G3 server) or `ext` (linked by the gateway).
- `to`: the TO the radio sends in INT (`/XLX214D`), or the reflector and module in EXT (`REF001 C`, `DCS214 D`, `XLX048 A`, `XRF988 D`).
- `server`: INT only. It is the "Gateway Repeater" server that leads to this TO.
- `api`: optional. It is the base URL of an xlxd dashboard JSON API (`?api=users|heard`), used for nodes and last heard.

## Translations

The code is written in English. Every visible text goes through `tr()`, and
each language has one plain-text file in [`qdstar/translations/`](qdstar/translations/)
(`es.po` for Spanish):

```
msgid "Linked to {reflector}"
msgstr "Enlazado a {reflector}"
```

By default QDStar uses the system language and falls back to English. You can
change it in *Radio > Settings > Language*. **New languages are welcome as pull
requests:**

1. Copy `qdstar/translations/es.po` to `<code>.po` (for example `fr.po`), or
   create it with `python tools/i18n_check.py --template > qdstar/translations/fr.po`.
2. Set `Language-Name` in the header and translate every `msgstr`, keeping the
   `{placeholders}` as they are.
3. Run `python tools/i18n_check.py` to check that nothing is missing.

## Building

GitHub Actions builds every push. A version tag (`x.y.z`) publishes a release
with the Windows installer and zip, plus the .deb, AppImage and tar.gz for
Linux amd64 and arm64. To build locally:

```sh
pip install PySide6 certifi pyinstaller
python tests/smoke_test.py
pyinstaller packaging/qdstar.spec
```

## Author

Manuel Alcocer Jiménez, EA7KLX.

## License

GPL-3.0-or-later.

- The Icom network protocol is reimplemented from
  [wfview](https://gitlab.com/eliggett/wfview) (GPLv3), itself based on kappanhang.
- The Terminal Mode, DPlus, DCS and DExtra code is ported from G4KLX's
  DStarRepeater and ircDDBGateway (GPLv2+).
- Bundled DejaVu fonts: see `qdstar/fonts/LICENSE-DejaVu`.
- Reflector host lists come from Pi-Star (pistar.uk) and the XLX directory.
