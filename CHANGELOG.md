# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- Home Assistant warned about a blocking call at start-up: the panel file is now hashed outside the event loop (0.2.2).
- The panel module could be evaluated twice in one page ("the name solarprio-panel has already been used"): the element is
  now defined only once.
- `examples/esphome/solar-router-actuator.yaml` did not compile: a YAML-style `#` comment sat inside a C++ lambda (found by
  the first real build). A test now rejects `#` inside the examples' C++ blocks.

## [0.2.2] - 2026-11-09

### Added
- Water heater controls in Home Assistant: option *Sanitary minimum only on a forced run* with a `forced run` switch per
  device, *Extra off-peak windows* (for example the midday hours) chosen with an `extra off-peak windows` switch, a `hot`
  binary sensor and a `mode` sensor per device. See `docs/REGULATION.md`. The standalone runtime refuses the two new
  options (it has no switches yet).

## [0.2.1] - 2026-11-09

### Added
- **Profile catalog** (`src/solarprio/profiles`): ready-made devices by brand and model as JSON files: Victron EV Charging
  Station, Victron grid power (with the keep-alive), generic water heaters. Docker: `profile = "..."` and `params` in
  `[source]` and `[[device]]`, local values win. Home Assistant: the profiles with an `ha` section are the models offered by
  *Add a device*, with their verification status. Guide `docs/PROFILES.md`; `examples/victron-profile.toml` gives the same
  configuration as `config.victron.example.toml` (tested).
- **Central regulation**: the engine now decides tank temperatures (solar and off-peak maximums, hysteresis), a sanitary
  minimum fed from the grid, a dynamic subscription cap for everything fed from the grid on purpose, smooth ramps (wait after
  a change, largest step, dead band), an emergency cut on grid import, and "surplus only". Settings are per device; the
  site settings gain the subscription limit, the house power sensor and the emergency threshold. Same in the Docker runtime.
- Water heater models in the panel (dimmer / relay), advanced settings folded away, the temperature and the mode shown on
  each row, and a warning when the chosen off-peak entity is a number (an energy index).
- A solar router that is only an actuator: `examples/esphome/solar-router-actuator.yaml`; guide `docs/REGULATION.md`.
- Off-peak windows and a tariff signal can be combined (both must say off-peak); `HC*` style wildcard in the states.

### Changed
- The panel now uses Home Assistant's own components (dialog, entity pickers with search, fields, buttons, switches,
  notifications), so forms look and behave like the rest of Home Assistant.
- The measurement delay can be 0 (never judge by age, only by availability): a sensor that does not repeat an unchanged value
  no longer makes the measurement look lost.
- A grid-fed device cut by the subscription cap is cut at once: no minimum run time holds it on.

## [0.1.2] - 2026-11-07

### Added
- **Computing task** category: a "go" signal for computing workloads that follows the solar surplus or the off-peak
  periods. It switches nothing (the Home Assistant form accepts only an `input_boolean`), needs no measured power and is never
  "finished". Example script `examples/task-go-poll.sh` and guide `docs/TASKS.md`.

### Changed
- A server or computer is no longer given as an example of an on/off load, and the on/off help warns against using it
  for a machine that must not lose its power. The Docker example uses a task instead.
- The off-peak status in the panel reads "running" instead of "heating".

## [0.1.1] - 2026-11-07

### Added
- Add, edit, delete devices and edit the measurement and safety settings from the sidebar panel (the forms come from the
  same field definitions as Home Assistant's own form, with the labels and help texts of the integration's translations).
- The panel says why a measurement was lost (which sensor, how old).

### Changed
- The panel stays in place when settings are saved (the integration reloads behind it), and is removed only when the
  integration is deleted or disabled.
- Device values are checked against the field ranges and choices whatever the way they are entered.

## [0.1.0] - 2026-11-07

First public version (alpha).

### Added
- Priority-based surplus allocation engine (pure Python): on/off, adjustable, battery and EV charger devices,
  hysteresis, minimum run/rest times, state-of-charge limits, plug state, measured power.
- Home Assistant integration: config and options flows, sensors, routing switch, sidebar panel with
  drag-and-drop priorities (English and French).
- Standalone runtime with MQTT and HTTP adapters and a Docker image definition.
- Brand icon (`brand/icon.png`, used by Home Assistant 2026.3 and later).

- Standalone runtime: periodic MQTT keep-alive (needed by Victron Venus OS), grid power summed over several topics
  (one per phase), JSON command payloads (`payload_template`), explicit plugged/unplugged values for numeric status codes.
- Victron example configuration and guide (simulated device only, not tested on real hardware).

- Home Assistant: unchanged commands are re-sent every 30 s (heartbeat for devices with a watchdog); adjustable devices
  accept a measured-power entity.
- Guide for driving an ESPHome solar router from solarprio with a watchdog (`docs/ESPHOME_ROUTER.md`).
- Export margin (`margin_w`, Home Assistant and standalone): watts deliberately left unrouted.
- Water-heater example with a template sensor for a Linky that reports withdrawn and injected power separately
  (`docs/WATER_HEATER_EXAMPLE.md`).
- Off-peak top-up: off-peak windows per device, fed at full power until it stops consuming, then the next device in
  priority order (`docs/OFFPEAK.md`). Needs a measured power sensor.
- Off-peak power budget (`offpeak_budget_w`): top up several devices together up to a power, default one at a time.
- Home Assistant setup pre-filled from the Energy dashboard (grid and solar power sensors), import of the dashboard's
  devices, and copy of a device (`docs/MANY_DEVICES.md`).
- Contribution documentation: how to add compatibility (`docs/ADDING_COMPATIBILITY.md`), a compatibility list, hardware page
  and example templates, a roadmap, a compatibility issue template; every example configuration is validated by the tests.
- Off-peak told by an entity or an MQTT topic (the Linky's tariff period, a binary sensor...) instead of time windows:
  each new off-peak period tries the device again; unknown or unavailable never starts anything.

### Safety behaviour
- Undelivered commands (broker down, service error) are retried and never counted as routed power.
- On shutdown every configured device is switched off, and the process exits non-zero if some may still be on.

### Known limitations
- Not tested on real inverters, batteries or wallboxes.
- No automatic 1/3 phase switching, no battery discharge control, no two-stage battery priority.
- A battery charge setpoint goes to 0 W when routing stops.
