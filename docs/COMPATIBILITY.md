# Compatibility

An honest list. "Verified" means run on real hardware by a person who wrote down what they saw. Nothing in this project
is verified on real hardware yet: it was developed with simulated devices. To change a line, see
[ADDING_COMPATIBILITY.md](ADDING_COMPATIBILITY.md).

| Status | Meaning |
|---|---|
| Verified | Run on real hardware, with a report (firmware/version, what was observed) |
| Simulated | Automated tests against a simulated device or broker |
| From docs | Written from the manufacturer's documentation, not run |
| Wanted | Nobody has tried; contributions welcome |

## Generic building blocks

| Block | Status | Notes |
|---|---|---|
| Home Assistant `switch` / `input_boolean` / `light` as an on/off load | Simulated | Home Assistant 2026.2.3 |
| `light` / `number` / `input_number` as an adjustable load (percent or watts) | Simulated | |
| `number` as battery charge setpoint, `number` + optional `switch` as EV charger | Simulated | |
| Pre-fill from the Home Assistant Energy dashboard (power sensors) | Simulated | Real Energy manager, simulated sensors |
| Standalone runtime: MQTT in/out, HTTP out | Simulated | Python test broker (amqtt); not Mosquitto |
| Docker image | Wanted | Never built yet |

## Hardware

| Hardware | Status | Where |
|---|---|---|
| Victron GX (Cerbo GX, Venus OS): grid power, battery charge setpoint, EV Charging Station | From docs, Simulated | [VICTRON.md](VICTRON.md), `config.victron.example.toml` |
| ESPHome solar router (triac) with external control and watchdog | From docs; `esphome config` checked, C++ not compiled | [ESPHOME_ROUTER.md](ESPHOME_ROUTER.md), [WATER_HEATER_EXAMPLE.md](WATER_HEATER_EXAMPLE.md) |
| Linky (French meter) read by ESPHome, as two sensors withdrawn / injected | Simulated | [WATER_HEATER_EXAMPLE.md](WATER_HEATER_EXAMPLE.md) |
| Linky tariff period as the off-peak signal | Simulated; the default state words (`HC..`...) are not verified on a real Linky | [OFFPEAK.md](OFFPEAK.md) |

## Wanted

Nothing below has been tried; each is a good first contribution. They are ideas, not claims that they work.

- Relays and plugs from common vendors (Shelly, Tasmota, Zigbee/Matter plugs) as on/off loads.
- Solar routers other than the ESPHome one (F1ATB and similar): command and measurement recipe.
- Heat pumps and electric radiators with contact inputs or setpoints.
- Wallboxes: through Home Assistant entities, MQTT, and (as an adapter) OCPP or Modbus.
- Inverters and batteries other than Victron.
- Servers and other IT loads (wake/suspend, power capping).
- Meters: other ways to read the grid power, per phase.
