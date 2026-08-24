# Hitachi ModBus Gateway – Home Assistant Integration

[![HACS Custom Repository](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.2%2B-blue)](https://www.home-assistant.io/)

A Home Assistant custom integration for **Hitachi HC-A(8/16/64)MB ModBus gateways**, enabling local control of Hitachi indoor units (VRF, RAC, ATW) via Modbus TCP.

> **Note:** This project was developed with the assistance of [Claude](https://claude.ai) (Anthropic AI). The register map and protocol details are based on the official Hitachi documentation referenced below.

---

## Supported Hardware

| Gateway model | Units | Notes |
|---|---|---|
| HC-A8MB | up to 8 | Modbus TCP over LAN |
| HC-A16MB | up to 16 | Modbus TCP over LAN |
| HC-A64MB | up to 64 | Modbus TCP over LAN (§5.2.2 extended space required for ATW) |

> **Current limit:** discovery scans slots **0–15**. On an HC-A64MB, indoor units
> in slots 16–63 are not found yet.

**Unit types supported:**

| Type | Description |
|---|---|
| **VRF** | Variable Refrigerant Flow (multi-split cassette/duct/wall) |
| **RAC** | Room Air Conditioner (single-split wall unit) |
| **ATW** | Air to Water (hydronic heat pump – requires HC-A16MB or HC-A64MB) |

---

## Features

### Climate entity (all unit types)
- On/Off, HVAC mode (Cool / Heat / Dry / Fan Only / Auto – per type)
- Target temperature setpoint
- Fan speed control (VRF/RAC only): `low` / `medium` / `high` / `auto`
- Current temperature (room inlet sensor for VRF/RAC; actual DHW tank temperature for ATW)
- Extra state attributes: pipe temperatures, alarm code, valve opening, operation state

### Switch entities (ATW only)
| Entity | Function |
|---|---|
| DHWT Run/Stop | Start or stop domestic hot water tank |
| DHW Boost | Request a one-shot DHW boost |
| DHW High Demand Mode | Switch between standard and high-demand mode |
| AntiLegionella | Enable/disable anti-legionella cycle |

### Number entities (ATW only)
| Entity | Range | Description |
|---|---|---|
| Circuit 1 Heating Setpoint | 0–80 °C | Water heating target temperature |
| Circuit 1 Cooling Setpoint | 0–80 °C | Water cooling target temperature |
| Circuit 1 Heat ECO Offset | 1–10 °C | ECO mode offset for heating |
| Circuit 1 Cool ECO Offset | 1–10 °C | ECO mode offset for cooling |
| AntiLegionella Setting Temperature | 0–80 °C | Anti-legionella cycle target temperature |

### Developer services
- `hitachi_modbus.read_register` – read any raw Modbus register
- `hitachi_modbus.write_register` – write any raw Modbus register

---

## Installation via HACS (recommended)

1. Open **HACS** in Home Assistant.
2. Click the three-dot menu (⋮) → **Custom repositories**.
3. Add the repository URL:
   ```
   https://github.com/st3f4n1n0/hitachimodbus-ha
   ```
   and select **Integration** as the category.
4. Search for **Hitachi ModBus Gateway** in HACS and click **Download**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & Services → Add Integration** and search for **Hitachi ModBus Gateway**.

---

## Manual Installation

1. Download or clone this repository.
2. Copy the `custom_components/hitachi_modbus` folder into your Home Assistant `config/custom_components/` directory.
3. Restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** and search for **Hitachi ModBus Gateway**.

---

## Configuration

The integration uses a guided UI setup flow with three steps.

### Step 1 – Connection

| Field | Default | Description |
|---|---|---|
| Gateway IP address | – | IP or hostname of the HC-A gateway |
| Modbus TCP port | 502 | Leave at 502 unless you changed it |
| Modbus slave ID | 1 | As configured in the gateway (usually 1) |
| Register base address | 2000 | `2000` (standard) or `20000` (legacy) |
| Polling interval | 30 s | How often HA reads the gateway (5–3600 s) |

### Step 2 – Discovered units

The integration scans gateway slots 0–15 and lists the indoor units found. Review and confirm.

### Step 3 – Unit type

For each discovered unit, select the type:

- **vrf** – Variable Refrigerant Flow
- **rac** – Room Air Conditioner
- **atw** – Air to Water (hydronic heat pump)

The type determines which HA platforms (climate / switch / number) and which modes are available.

### Changing settings later

**Settings → Devices & Services → Hitachi ModBus Gateway → Configure** re-opens
the polling interval **and the type of every unit**, so a slot set to the wrong
type during setup can be corrected without removing and re-adding the
integration.

Changing a type reloads the integration: the unit switches between the §5.2.1
and §5.2.2 register spaces and its entities are rebuilt. A unit that is no
longer **ATW** loses its switch and number entities, and those are removed from
the entity registry rather than left behind as unavailable.

---

## Prerequisites

- The HC-A gateway must be reachable from the Home Assistant host over TCP (default port 502).
- `pymodbus` is declared in `manifest.json` and installed automatically by Home Assistant on first setup.
- For ATW units, the gateway must be an HC-A16MB or HC-A64MB (ATW §5.2.2 address space is not available on HC-A8MB).

---

## Register map reference

The register addresses and protocol details implemented in this integration are based on the official Hitachi technical documentation:

- **PMML0351A rev.4** – *HC-A(8/16/64)MB Modbus protocol specification*  
  This document describes §5.2.1 (VRF/RAC register space) and §5.2.2 (ATW extended register space).

A copy of the relevant documentation pages is included in the [`Documentation/`](Documentation/) folder of this repository.

### A note on the "High2" fan speed

PMML0351A defines fan register value `3` as **High2** (also called *High H*), but
it is an optional indoor-unit function – see optional function **EF**, *"Control
in Automatic indoor fan speed mode (supporting High H)"*. Units that do not
implement it, RAC wall units in particular, accept the value and simply run the
fan at **High**.

The speed is therefore **not offered** by this integration. If a unit reports
register value `3` (for example because it was set from a wired remote), it is
shown as `high`, which is what the unit is actually doing. Automations that
still send `high2` keep working: the value is translated to `high`.

The **Hitachi Net Configurator** Java application (the official Windows tool for gateway configuration) is available separately and can be requested from your Hitachi HVAC distributor. It is not included in this repository.

---

## Troubleshooting

**Cannot connect / no units found**
- Verify the gateway IP and port are correct and reachable (`ping` / `telnet <ip> 502`).
- Check the slave ID matches the gateway configuration (default: 1).
- Try switching the register base between `2000` and `20000`.

**ATW sensors show 0 or unavailable**
- ATW uses a separate register space (§5.2.2: `5000 + slot_id×200 + offset`). Make sure you selected **atw** as the unit type during setup.
- Some sensors (water inlet temperature) may read 0 if the corresponding probe is not connected.

**The `high2` fan speed disappeared**
- It was removed on purpose: see [A note on the "High2" fan speed](#a-note-on-the-high2-fan-speed) above. Selecting it never produced a different fan speed on RAC units.

**A unit behaves oddly / shows the wrong modes**
- Check its type under **Configure** – a RAC or ATW unit left as the default `vrf` exposes modes its hardware does not have. ATW units in particular need `atw`, or they are read from the wrong register space.

**Entities are unavailable after HA restart**
- This is normal for the first poll cycle. The coordinator fetches data shortly after startup.

---

## License

This project is released under the [MIT License](LICENSE).
