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
  surplus, applies hysteresis and min on/off timers, returns one command per device.
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
- `adapters.py`: `MqttPowerSource`, `MqttActuator`, `HttpActuator`.
- `controller.py`: the loop. Sends only changed commands (plus a periodic resend),
  sends concurrently, retries failed sends, handles measurement loss, switches off on shutdown.

## Home Assistant integration (`custom_components/solarprio`)

- HACS installs only `custom_components/<domain>`, so the integration carries a copy of the
  core in `core/`, made by `scripts/sync_core.py`. A test fails if the copy drifts from `src/`.
  No PyPI package is needed.
- `config_flow.py`: measurement source. Options flow: add / edit / remove devices and their
  priority number.
- `coordinator.py`: reads the sensors (kW converted to W, unavailable or too-old values count as
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
- Proportional devices are limited to `light` and `number`/`input_number` entities.

- Runtime tested with a Python MQTT broker (amqtt), not with Mosquitto, and the Docker
  image has not been built yet (no Docker daemon was available).
- No authentication/TLS options for MQTT beyond username/password.
- HTTP actuator: no custom headers or body.
- Battery (SoC limits, charge/discharge) and EV charger (current steps,
  minimum 6 A) need dedicated device kinds; the current two kinds do not model them.
- Safety: measurement loss is handled (`on_stale`), but the behavior when a device stops
  responding (command sent, load not actually switched) is not detected: no feedback loop yet.
