# TomTuT Mitsubishi Outlander PHEV EU

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1.0%2B-blue)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Home Assistant custom integration for **Mitsubishi Connect EU** (GOA platform) — monitor and control your Mitsubishi PHEV or EV directly from Home Assistant.

> 📖 **Full setup guide, configuration tips & dashboard:**
> **[https://www.tomtut.de/tomtut-tomtut-mitsubishi-outlander-phev-eu/](https://www.tomtut.de/tomtut-tomtut-mitsubishi-outlander-phev-eu/)**

> **Disclaimer:** This is an unofficial community project. It is not affiliated with, endorsed by, or supported by Mitsubishi Motors or any of its subsidiaries. Use at your own risk.

---

## Features

- **Battery & Charging** — State of charge, EV range, fuel range, total range, charging status, remaining charge time
- **Remote Commands** — Start/stop charging, start/stop climate remotely
- **Climate Control** — Target temperature sensor, AC on/off switch
- **Tire Pressure** — All four wheels in Bar (front-left, front-right, rear-left, rear-right)
- **Door & Lock Status** — Doors locked binary sensor
- **GPS Tracking** — Vehicle location as HA device tracker
- **Trip & Charge History** — Last trip distance/duration, last charge energy/duration
- **Warnings** — Engine oil warning, MIL warning, brake warning
- **Buttons** — Horn, flash lights, force-refresh vehicle status
- **Additional Sensors** — Odometer, speed, firmware version, charging base cost

---

## Requirements

- Home Assistant 2024.1.0 or newer
- [HACS](https://hacs.xyz/) installed
- Mitsubishi Connect EU account (the GOA-based app, used in Europe)

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → click the three-dot menu → **Custom repositories**
3. Add: `https://github.com/TomTuTHub/tomtut-mitsubishi-outlander-phev-eu` — Category: **Integration**
4. Search for **TomTuT Mitsubishi Outlander PHEV EU** and click **Download**
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration** → search for **Mitsubishi Connect EU**

### Manual Installation

1. Download or clone this repository
2. Copy `custom_components/mitsubishi_outlander_phev_eu/` into your HA `config/custom_components/` directory
3. Restart Home Assistant
4. Add the integration via **Settings → Devices & Services**

---

## Configuration

During setup you will be prompted for:

| Field | Description |
|---|---|
| **Username** | Your Mitsubishi Connect EU email address |
| **Password** | Your Mitsubishi Connect EU password |
| **PIN** | 4-digit PIN from the Mitsubishi Connect app |
| **Update interval** | Polling interval in minutes (default: 15, minimum: 5) |

After setup, one device per vehicle (VIN) will be created automatically.

Credentials and the update interval can be changed at any time via **Settings → Devices & Services → TomTuT Mitsubishi Outlander PHEV EU → ⚙️ Reconfigure**.

---

## Entity Overview

### Sensors

| Entity | Unit | Description |
|---|---|---|
| Battery Level | % | High-voltage battery state of charge |
| EV Range | km | Estimated electric range |
| Fuel Range | km | Estimated fuel range |
| Total Range | km | Combined EV + fuel range |
| Charging Remaining Time | min | Minutes until charging complete |
| Odometer | km | Total distance driven |
| Speed | km/h | Current vehicle speed *(disabled by default)* |
| Target Temperature | °C | Climate pre-conditioning target temperature |
| Tire Pressure FL/FR/RL/RR | bar | Tire pressure per wheel |
| Charging Base Cost | ct/kWh | Energy cost rate *(disabled by default)* |
| Firmware Version | — | Vehicle firmware version string |
| Last Trip Distance | km | Distance of the last completed trip |
| Last Trip Duration | min | Duration of the last completed trip |
| Last Charge Energy | kWh | Energy added during last charge session |
| Last Charge Duration | min | Duration of last charge session |

### Binary Sensors

| Entity | Description |
|---|---|
| Charging | Is the vehicle currently charging? |
| Plugged In | Is the charge cable connected? |
| Doors Locked | Are all doors locked? |
| Engine On | Is the engine running? |
| AC On | Is the climate system active? *(disabled by default)* |
| Brake Warning | Brake system warning light |
| Engine Oil Warning | Engine oil warning light |
| MIL Warning | Malfunction indicator light (Check Engine) |

### Switches

| Entity | Description |
|---|---|
| Climate | Start / stop remote climate pre-conditioning |
| Charging | Start / stop remote charging |

### Buttons

| Entity | Description |
|---|---|
| Horn | Trigger the horn remotely |
| Lights | Flash the lights remotely |
| Refresh | Force an immediate vehicle status update |

### Other

| Platform | Entity | Description |
|---|---|---|
| Lock | Door Lock | Lock/unlock doors remotely |
| Device Tracker | Location | GPS position of the vehicle |
| Climate | Climate | HVAC pre-conditioning control |

---

## Important Notes

- **Update interval:** The integration polls the Mitsubishi API every 15 minutes by default (minimum: 5 min). The API reflects the last known vehicle state — not always real-time. Polling too frequently may wake the vehicle unnecessarily.
- **Remote commands:** After sending a remote command (e.g. start charging), there is a short delay before the vehicle status reflects the change. The integration waits ~15 seconds before refreshing.
- **Tire pressure:** The API provides tire pressure in kPa. This integration converts and displays it in Bar. Home Assistant's auto-conversion to kPa is suppressed.
- **PIN is required:** Remote commands (lock/unlock, horn, lights, climate, charging) require the 4-digit PIN. Without a valid PIN, these commands will fail.

> ℹ️ **No schedule entities in this integration — by design.**
>
> Charge and climate schedule control via the Mitsubishi API is unreliable and caused persistent errors. This integration intentionally does not implement schedule polling or schedule control.
>
> If you want time-based automation: use **Home Assistant automations** (trigger on time, call the climate or charging switch) — or use the **Mitsubishi Connect app** directly.

---

## Support & Issues

Please report bugs and feature requests at:
[https://github.com/TomTuTHub/tomtut-mitsubishi-outlander-phev-eu/issues](https://github.com/TomTuTHub/tomtut-mitsubishi-outlander-phev-eu/issues)

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## About the Author

I am a trained IT specialist for system integration with many years of experience in IT. Back in the day it was MCSE — today it's vibe coding. This integration was built with the help of Claude and ChatGPT. Without AI assistance I never could have pulled this off on the side — it would have taken me months. The code has been reviewed and tested by me and runs in my own production setup.

---

Das war TomTuT, bleib hart am Gas.
