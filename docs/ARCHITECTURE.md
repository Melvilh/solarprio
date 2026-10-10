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

## Not yet decided or built

- Runtime tested with a Python MQTT broker (amqtt), not with Mosquitto, and the Docker
  image has not been built yet (no Docker daemon was available).
- No authentication/TLS options for MQTT beyond username/password.
- HTTP actuator: no custom headers or body.
- HA integration: how it gets the core. Options: publish `solarprio` on PyPI and
  list it in `manifest.json` requirements, or vendor a copy. Not decided.
- Battery (SoC limits, charge/discharge) and EV charger (current steps,
  minimum 6 A) need dedicated device kinds; the current two kinds do not model them.
- Safety: measurement loss is handled (`on_stale`), but the behavior when a device stops
  responding (command sent, load not actually switched) is not detected: no feedback loop yet.
