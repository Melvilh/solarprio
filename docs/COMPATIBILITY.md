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

## Profiles (by brand and model)

Ready-made models in [PROFILES.md](PROFILES.md). The status is the one stored in the profile file.

| Profile | Brand / model | Status |
|---|---|---|
| `generic-water-heater-dimmer` | Generic: water heater behind a solar router | Simulated |
| `generic-water-heater-relay` | Generic: water heater on a relay or contactor | Simulated |
| `victron-evcs` | Victron EV Charging Station (GX device, MQTT) | Simulated, from docs |
| `victron-grid` | Victron grid power per phase (GX device, MQTT) | Simulated, from docs; sign to verify |

## Hardware

| Hardware | Status | Where |
|---|---|---|
| Victron GX (Cerbo GX, Venus OS): grid power, battery charge setpoint, EV Charging Station | From docs, Simulated | [VICTRON.md](VICTRON.md), `config.victron.example.toml` |
| ESPHome solar router (triac) with external control and watchdog | From docs; `esphome config` checked, C++ not compiled | [ESPHOME_ROUTER.md](ESPHOME_ROUTER.md), [WATER_HEATER_EXAMPLE.md](WATER_HEATER_EXAMPLE.md) |
| Linky (French meter) read by ESPHome, as two sensors withdrawn / injected | Simulated | [WATER_HEATER_EXAMPLE.md](WATER_HEATER_EXAMPLE.md) |
| ESPHome solar router as an actuator only (`examples/esphome/solar-router-actuator.yaml`) | From docs; `esphome config` checked, C++ not compiled | [ESPHOME_ROUTER.md](ESPHOME_ROUTER.md), [WATER_HEATER_EXAMPLE.md](WATER_HEATER_EXAMPLE.md) |
| Linky tariff period as the off-peak signal | Simulated; the default state words (`HC..`...) are not verified on a real Linky | [OFFPEAK.md](OFFPEAK.md) |

## Wanted

Nothing below has been tried; each is a good first contribution, ideally as a [profile](PROFILES.md). They are ideas, not
claims that they work: no profile exists for them yet.

- Relays and plugs from common vendors (Shelly, Tasmota, Zigbee/Matter plugs) as on/off loads.
- Solar routers other than the ESPHome one (F1ATB and similar): command and measurement recipe.
- Heat pumps and electric radiators with contact inputs or setpoints.
- Wallboxes: through Home Assistant entities, MQTT, and (as an adapter) OCPP or Modbus.
- Inverters and batteries other than Victron.
- Computing workloads (see [TASKS.md](TASKS.md)): scripts and schedulers that read the go signal (cron, systemd timers, job queues).
- Meters: other ways to read the grid power, per phase.
