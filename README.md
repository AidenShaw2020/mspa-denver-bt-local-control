# MSpa Denver Bluetooth Local Control

![MSpa Local](custom_components/mspa_local/brand/logo.png)

**MSpa Local** is an experimental Home Assistant custom integration for reading and controlling an MSpa Denver over Bluetooth Mesh through an active ESPHome Bluetooth proxy.

Normal device communication stays on your local network. An MSpa owner account is used during configuration to import the Mesh keys; manual key entry is also available. This project is independent of MSpa and ESPHome.

## Status

Version **0.2.0** is a test release. Water temperature and full device state have been read and authenticated on a real Denver through an ESP32-WROOM-32 ESPHome proxy. A direct protocol test successfully changed the target temperature to 39 °C, verified it, and restored 38 °C. Other actuator writes have synthetic protocol coverage but have not all been exercised on hardware.

The package has not yet been installed and tested inside a running Home Assistant instance. Its automated tests use Home Assistant API stubs and an encrypted simulated BLE peripheral. Other MSpa models and firmware versions are unverified.

## Requirements

- A powered MSpa Denver with Bluetooth control supported by MSpa Link.
- Home Assistant with its Bluetooth integration and an ESPHome integration connected to an **active** Bluetooth proxy near the spa. The tested board is ESP32-WROOM-32.
- The owning MSpa account, or the correct NetKey and AppKey for the spa's Mesh network. A shared account may expose a different network or omit the required nodes.
- The spa configured to use **Celsius**. Fahrenheit control is not yet supported.

Use a current Home Assistant release with Bluetooth connection support. The included local icon and detail logos require **Home Assistant 2026.3 or later**. Full runtime compatibility has not yet been established by installation testing. Proxy firmware is supplied separately; this repository does not flash or configure the ESP32.

## Installation

1. Download `mspa-denver-bt-local-control-0.2.0.zip` from [Releases](https://github.com/AidenShaw2020/mspa-denver-bt-local-control/releases).
2. Extract it and copy `custom_components/mspa_local` to `/config/custom_components/mspa_local` on Home Assistant. When updating, replace the existing integration folder.
3. Add your ESPHome Bluetooth proxy to Home Assistant using the **ESPHome** integration. Enter its API encryption key there. MSpa Local uses Home Assistant's shared Bluetooth manager and does not require the proxy's IP address or API key.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration → MSpa Local**.
6. Choose account import, enter the owner account, and select the region. Use **ROW** for Europe; **US** and **CH** are also available.
7. Select the spa and review its profile. Leave NetKey and AppKey blank to keep the imported values.
8. Initially keep the polling interval and state timeout at **60 seconds**. Use the default controller address `7FFD` only if it is unused in this Mesh network.

Keep the spa powered and the proxy nearby. Close MSpa Link during the initial connection test because it may occupy the Bluetooth connection. The first complete state read can take about a minute.

For manual setup, provide both 32-character hexadecimal keys and the spa's hexadecimal Mesh unicast address. The default spa address `0102` is an example from the tested Denver, not a universal device address.

Owners of the earlier diagnostic 0.1.0 package must import keys again in **Options** after updating: that package stored only NetKey, while control also requires AppKey.

## Entities

The core controls follow the names and functions of [DTekNO's cloud integration](https://github.com/DTekNO/mspa-homeassistant).

| Entity | Function |
|---|---|
| Heater Control | Climate entity with current and target temperature, Heat/Off, 20–40 °C, 0.5 °C target increments |
| Heater, Filter, Bubble, Jet, Ozone, UVC | Six device switches |
| Bubble Level | Level 1–3 |
| Water Temperature | Device-reported water temperature |
| Fault, Filter status | Device fault and filter warning status |
| Heater timer | Native device timer flag |
| Heater timer remaining | Device-reported `heat_time` value in hours |
| Firmware version | Metadata imported at configuration time |
| Raw Mesh diagnostics | Device-reported attributes, including lock, filter current, filter life and timer fields |
| Bluetooth status, Bluetooth signal, IV Index | Local connection diagnostics |
| Network/Application key authentication | Authentication diagnostics |
| Refresh Bluetooth state | Button to request a fresh state |

Functions absent from the hardware cannot be added by this integration. A switch whose attribute is missing is unavailable; firmware may reject unsupported functions.

**There are no power or energy estimates, predictive heating algorithms, readiness forecasts, ambient learning, or autonomous predictive schedules.** The investigated BLE protocol does not provide measured electricity consumption. Device-reported `heat_rest_time` and `device_heat_perhour` remain raw diagnostics and are not used to calculate a ready time. Native timer reporting does not implement a predictive scheduler.

MSpa Local uses the `mspa_local` domain and separate unique IDs. Update dashboard and automation references when migrating from cloud entities. During initial testing, disable cloud automations that change the same settings to avoid competing commands.

## Configuration and command behavior

**Options** allows changing the profile name, model, Mesh addresses and keys, polling interval (30–600 seconds), state timeout (10–180 seconds), or importing the keys again. English and Czech configuration translations are included.

The integration maintains a GATT connection through Home Assistant, requests full state periodically, and reconnects on a later update after disconnection. Writes are confirmed by authenticated state readback. An acknowledgement alone is not treated as success. A failed or unconfirmed write returns a service error and marks entities unavailable until a successful update.

Writes are not automatically retried after an uncertain result. Turning off the filter first turns off the heater, matching the cloud integration's dependency. Turning bubbles on first selects the reported valid level, or level 1 if needed. Startup and reconnection only read state; they do not restore actuator settings or turn heating on automatically.

This version supports the verified **IV Index 0** without Mesh Key Refresh or IV Update. It stops access in unsupported transition states. Fahrenheit temperature commands are blocked rather than converted using an unverified interpretation.

## Credentials and Mesh sequence storage

The integration does not retain your login password or cloud session token. Mesh keys and device metadata are stored in Home Assistant's configuration, so treat configuration files and backups as sensitive. The exported integration diagnostics redact keys and identifiers. Release archives contain no account exports, device keys, proxy credentials, or APK files.

Each outgoing Mesh sequence number is saved **before transmission** to:

```text
.storage/mspa_local.sequence.<network-id>.<source>
```

Do not delete these files or restore an older counter for the same network and controller address. Reusing a sequence can trigger Mesh replay protection. Keep the counter with the configuration. Another Home Assistant instance or controller in the same Mesh network must use a different, genuinely unused unicast source address and its own persistent counter. Do not run two instances with the same network and source address.

The default Home Assistant source is `7FFD`. The development hardware tests used a separate `7FFE` source. This does not reserve either address in your network automatically.

## Troubleshooting

- **No Mesh nodes / invalid profile:** use the owner account and correct region; a shared account may not contain the spa's keys. Reimport keys in Options.
- **Unavailable / timeout:** check proxy availability, active connections, proximity, spa power, and whether the mobile app is connected. Start with a 60-second state timeout.
- **Authentication succeeds but no full state:** verify the spa address and AppKey, not just NetKey. Beacon authentication alone does not prove control access.
- **Unsupported IV/key transition:** this release cannot migrate that state; do not reset the sequence file as a workaround.
- **Temperature unavailable:** check that the spa uses Celsius.

Download integration diagnostics from Home Assistant when reporting an issue. Review attachments before posting and never upload configuration files, account exports, or Mesh keys.

## Development and validation

Use Python 3.13 and install the test dependencies:

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python scripts/build_release.py
```

The suite covers published Mesh cryptographic vectors, fragmented state reads, authenticated half-degree target writes, command rejection, sequence persistence, disconnect handling, platform entities, profile parsing and configuration. All fixtures use public test vectors or synthetic data. Home Assistant is stubbed, so these tests do not establish full runtime compatibility.

The builder validates Python and JSON files and writes an installation archive plus its SHA-256 checksum to `dist/`. It packages only integration files and distribution documentation.

Integration branding lives in `custom_components/mspa_local/brand/`, including light/dark detail logos and high-resolution PNG variants. The editable icon source is [assets/icon.svg](assets/icon.svg). These are original project graphics, supplied under the project license. Home Assistant loads them locally without a separate brands repository submission.

## License and attribution

This project is distributed under **Apache License 2.0**; see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Cloud authentication is adapted from **DTekNO/mspa-homeassistant**, also Apache-2.0, at commit [`bdaa2420e34dee1c7449873d79eb7b17691a3426`](https://github.com/DTekNO/mspa-homeassistant/tree/bdaa2420e34dee1c7449873d79eb7b17691a3426), specifically [`custom_components/mspa/mspa_api.py`](https://github.com/DTekNO/mspa-homeassistant/blob/bdaa2420e34dee1c7449873d79eb7b17691a3426/custom_components/mspa/mspa_api.py). The modified implementation uses asynchronous requests solely for configuration-time Mesh profile import. Runtime reads and controls use the independently implemented local Mesh transport.

Published Mesh test vectors were checked against [Nordic Semiconductor's Android nRF Mesh Library](https://github.com/NordicSemiconductor/Android-nRF-Mesh-Library), licensed under BSD-3-Clause; its notice and license are retained in [LICENSES/Nordic-BSD-3-Clause.txt](LICENSES/Nordic-BSD-3-Clause.txt). The MSpa vendor messages were investigated using MSpa Link 1.2.13. No APK, decompiled application code or application assets are redistributed here.

Technical references: [Home Assistant Bluetooth API](https://developers.home-assistant.io/docs/core/bluetooth/api/), [Bleak Retry Connector](https://github.com/Bluetooth-Devices/bleak-retry-connector).
