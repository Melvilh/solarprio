# <Vendor> <Model> — <what it is used for>

Copy this file to `docs/hardware/<vendor>-<model>.md`, fill it in, delete these instructions and anything that does not
apply. Be factual: what you ran, what you saw, what you did not check.

## Status

- Status: Verified on real hardware / Simulated / From the manufacturer's documentation (pick one, see
  [COMPATIBILITY.md](../COMPATIBILITY.md)).
- Tested with: hardware revision, firmware/software version, Home Assistant version or the Docker image tag.
- Tested for: how long, under which conditions.

## How it connects

- How the load is commanded: Home Assistant entity (`switch`/`number`/...) or MQTT topic/HTTP call.
- How its real power is measured (needed for the off-peak top-up, recommended otherwise).
- How the grid power is measured, and **its sign convention** (positive = import or export?).
- Anything unusual: a keep-alive, a watchdog/timeout, a mode that must be set first, a minimum value.

## Configuration

Home Assistant: device type, entity, power, minimum power, timers, measured power sensor, off-peak settings.
Docker: link the file in `examples/<vendor>-<model>.toml`.

## Safety

What protects the load besides solarprio (thermostat, breaker, manufacturer's limits)? What happens if the measurement
is lost or Home Assistant restarts? Say what you checked.

## Not verified

List honestly what you did not test.
