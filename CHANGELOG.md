# Changelog

## 0.2.3 — 2026-10-10

- Document author-confirmed operation on a real MSpa Denver in Home Assistant.
- Document successful shared ESP32 operation with the MSpa Denver RF LED control project.
- Record occasional Bluetooth dropouts with automatic recovery within about one minute in the tested setup.
- Correct early Git commit attribution from the unrelated noreply account to AidenShaw2020, using the author's GitHub privacy email.
- No changes to device commands, entities or reconnect behavior.

## 0.2.2 — 2026-10-08

- Make HACS custom repository installation the documented installation method.
- Add HACS metadata with a Home Assistant 2026.3 minimum for local brand images.
- Include license notices inside the integration directory for HACS installations.
- Validate the HACS repository layout when building distribution archives.
- No changes to device commands or entity behavior.

## 0.2.1 — 2026-10-08

- Credit AidenShaw2020 as the project author while keeping personal contact details out of the distribution.
- Use the test requirements file for GitHub Actions dependency caching; Linux validation passes.
- No changes to device commands or entity behavior.

## 0.2.0 — 2026-10-08

First public experimental distribution.

- Local Bluetooth Mesh reads and controls through Home Assistant's Bluetooth manager and an active ESPHome proxy.
- Owner account login with automatic NetKey/AppKey import, device selection, manual profile entry and editable options.
- Climate, six switches, bubble level, temperature, native timer reporting and diagnostics.
- Persistent outgoing sequence allocation and authenticated state confirmation for writes.
- English documentation, English/Czech configuration translations, upstream attribution and license notices.
- Original local integration icon and light/dark detail logos for Home Assistant 2026.3+.
- Portable tests with encrypted synthetic peripherals and published cryptographic vectors.

No electricity consumption estimates or predictive scheduling are included.
Real Denver state reads and direct target-temperature writes are verified; full Home Assistant runtime installation and other actuator hardware tests remain pending.
