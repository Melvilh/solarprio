# Architecture

## Goal

Same routing logic whether the user runs Home Assistant or only a Docker
container. So the engine knows nothing about Home Assistant.

```
            +------------------+
 PowerSource|  solarprio core  |DeviceActuator
 (measure)->|  Engine.step()   |->(commands)
            +------------------+
              ^              ^
   +----------+--+        +--+----------------+
   | HA runtime  |        | Standalone runtime|
   | (entities)  |        | (MQTT/HTTP/Modbus)|
   +-------------+        +-------------------+
```

## Core (`src/solarprio`)

- `Device`: priority, kind (`on_off` / `proportional`), max and min power,
  min on/off time, start margin, stay tolerance.
- `Engine.step(available_w, now)`: walks devices by priority, hands out the
  surplus, applies hysteresis and min on/off timers, returns one command per device (watts).
- Device types: `on_off`, `proportional`, `battery`, `ev_charger`. An EV charger's power range is derived
  from voltage, phases and min/max current; commands stay in watts, runtimes convert with `Device.current_for`.
- `DeviceReading` (`Engine.set_reading`): optional measured power, state of charge and plug state per device.
  Safety limits (SoC reached, car unplugged) override the min on/off timers. `routed_w` uses measured power when known,
  and a device measured below its command (after `settle_s`) frees the difference for lower priorities.
- Off-peak top-up (`Device.offpeak`): `Engine.step(..., local)` picks one device inside its window, feeds it at full
  power (taken out of the shared surplus), and marks it done for the daily period when its measured power stays low
  after `done_after_s`. Without `local` (measurement lost) there is no top-up.
- `available_w` **includes what managed loads already consume**. Helpers in
  `sources.py` compute it from grid export or from production and consumption.
  Without this, the loop would oscillate: a heater that starts reduces the
  measured export, which would then switch it off.
- Time is passed in, so behavior is deterministic and testable.

## Ports (`ports.py`)

`PowerSource` and `DeviceActuator` are the only things a runtime must implement.

## Standalone runtime (`src/solarprio/runtime`)

- `config.py`: TOML parsing and validation.
- `mqtt_bus.py`: paho-mqtt wrapper caching the latest value (with age) per topic.
- `adapters.py`: `MqttPowerSource`, `MqttReadings` (SoC / plug / measured power topics), `MqttActuator`
  (watts, percent or amps; EV `switch_topic`), `HttpActuator` (`{power_w}`, `{percent}`, `{amps}`, `{state}`).
- `keepalive.py`: periodic keep-alive for brokers that only publish on request (Victron); the first request and the first
  after a reconnection are empty (full republish), later ones suppress the republish.
- `controller.py`: the loop. A command that cannot be delivered is retried next cycle and the engine is rolled back
  (`Engine.rollback_command`) so it never counts undelivered power as routed. On shutdown every configured device is
  addressed, not only those commanded in this run; the process exits non-zero if some may still be on.
  Also: Sends only changed commands (plus a periodic resend),
  sends concurrently, retries failed sends, handles measurement loss, switches off on shutdown.

## Home Assistant integration (`custom_components/solarprio`)

- HACS installs only `custom_components/<domain>`, so the integration carries a copy of the
  core in `core/`, made by `scripts/sync_core.py`. A test fails if the copy drifts from `src/`.
  No PyPI package is needed.
- `config_flow.py`: measurement source. Options flow: add / edit / remove devices and their
  priority number.
- `coordinator.py`: re-sends unchanged commands every `RESEND_EVERY_S` (30 s): a heartbeat for devices with a watchdog. Reads the sensors (kW converted to W, unavailable or too-old values count as
  lost), runs the engine, calls services (`homeassistant.turn_on/off`, `light.turn_on`,
  `number.set_value`). Loads are switched off when the entry is unloaded and when HA stops.
- `panel.py` + `frontend/panel.js`: sidebar panel (custom element, no build step, no dependency).
  Websocket API: `solarprio/state`, `solarprio/reorder`, `solarprio/set_device_enabled`,
  `solarprio/set_routing` (writes need admin). A reorder or an enable change updates the config entry;
  the update listener applies it **in place** (`Coordinator.apply_device_options`) and only reloads
  the entry when something else changed, so a drag and drop never switches loads off.
  Drag and drop uses pointer events (mouse and touch) with arrow buttons as the keyboard path.
  The panel patches values in place and rebuilds the list only when devices or their order change.
- Entities: `Routing` switch (restored across restarts), available / routed power, status,
  one command sensor per device.

## Not yet decided or built

- HA integration: After a HA
  restart the engine starts with all loads assumed off, so the first cycle can under-estimate
  the surplus until loads are commanded again. Not validated with HACS / hassfest; the
  `documentation` and `issue_tracker` URLs in `manifest.json` are placeholders.
- Panel: tested in Chromium at desktop and phone widths, not on a real touch device or in Safari/Firefox.
  Home Assistant runs a View Transition after page load during which clicks anywhere are swallowed
  (observed in the e2e test); this is Home Assistant's behaviour and cannot be fixed from the panel.
- `last_reported` staleness: a sensor that only updates on change (some Zigbee meters) can be treated as
  lost after `stale_after_s`; raise that setting for such sensors.
- Proportional devices are limited to `light` and `number`/`input_number` entities. Battery charge setpoints and
  EV currents must be `number`/`input_number` entities.

- Runtime tested with a Python MQTT broker (amqtt), not with Mosquitto, and the Docker
  image has not been built yet (no Docker daemon was available).
- No authentication/TLS options for MQTT beyond username/password.
- HTTP actuator: no custom headers or body.
- Battery and EV charger: tested on the engine, on Home Assistant (config flow, services, panel) and over MQTT,
  with simulated entities and meters, not with real inverters or wallboxes. No automatic 1/3 phase switching, no
  battery discharge control, no two-stage battery priority (e.g. 30 % first, 100 % last), no EV departure-time logic.
- When routing stops a battery setpoint goes to 0 W (see README); a configurable release value is not implemented.
- Safety: measurement loss is handled (`on_stale`), but the behavior when a device stops
  responding (command sent, load not actually switched) is not detected: no feedback loop yet.
