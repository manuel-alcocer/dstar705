# DStar705

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
- Two working modes:
  - **INT**: Terminal Mode with the radio's internal gateway (WLAN) and a G3
    server such as `server1.dstar.es`. Changing reflector writes the TO (UR)
    over CI-V.
  - **EXT**: Terminal Mode with an external gateway over USB, provided by
    DStar705 itself. Reflectors are linked with the *Enlazar* button.

## Download

Get the latest build from the **Releases** page:

| System | File |
|---|---|
| Windows 10/11 x64 | `DStar705-x.y.z-windows-x64-setup.exe` (installer) or `…-portable.zip` |
| Linux x86-64 | `dstar705_x.y.z_amd64.deb`, `DStar705-x.y.z-x86_64.AppImage` or `.tar.gz` |
| Linux ARM64 (Raspberry Pi OS bookworm, Debian 12+, Ubuntu 22.04+) | `dstar705_x.y.z_arm64.deb`, `DStar705-x.y.z-aarch64.AppImage` or `.tar.gz` |

On Linux your user needs access to the radio's USB serial ports:
`sudo usermod -aG dialout $USER` (Debian, Ubuntu, Raspberry Pi OS) or
`uucp` (Arch). Log out and back in afterwards.

## Radio setup

1. **WLAN**: connect the radio to your network and give it a fixed IP.
   In *Remote Settings*, set **Network Control** to ON and create a
   **Network User** (user + password).
2. On first run DStar705 asks for the radio's IP, user and password. It reads
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
pip install PySide6
python -m dstar705
```

## Default reflectors

On first run the app loads the reflector list shipped in
[`dstar705/default_reflectors.json`](dstar705/default_reflectors.json).
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

## Building

GitHub Actions builds every push. A version tag (`x.y.z`) publishes a release
with the Windows installer and zip, plus the .deb, AppImage and tar.gz for
Linux amd64 and arm64. To build locally:

```sh
pip install PySide6 pyinstaller
python tests/smoke_test.py
pyinstaller packaging/dstar705.spec
```

## Author

Manuel Alcocer Jiménez, EA7KLX.

## License

GPL-3.0-or-later.

- The Icom network protocol is reimplemented from
  [wfview](https://gitlab.com/eliggett/wfview) (GPLv3), itself based on kappanhang.
- The Terminal Mode, DPlus, DCS and DExtra code is ported from G4KLX's
  DStarRepeater and ircDDBGateway (GPLv2+).
- Bundled DejaVu fonts: see `dstar705/fonts/LICENSE-DejaVu`.
- Reflector host lists come from Pi-Star (pistar.uk) and the XLX directory.
