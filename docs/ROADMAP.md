# Ideas and open work

solarprio is young and meant to grow. Nothing below is promised: it is a list of **known gaps** (each one is stated as
a limit elsewhere in the documentation) and of ideas that came up. Pick one, open an issue to say so, and read
[ADDING_COMPATIBILITY.md](ADDING_COMPATIBILITY.md).

## Verification (the most valuable work right now)

- Run it on real installations and report what you saw (inverters, batteries, wallboxes, heaters, routers).
- Build and run the Docker image; try it with Mosquitto instead of the Python test broker.
- Other Home Assistant versions than 2026.2.3 (then relax the minimum version in `hacs.json`), touch devices, Safari and Firefox for the panel.

## Behaviour

- Automatic 1-phase / 3-phase switching for EV chargers (hardware specific).
- Battery discharge control and a two-stage battery priority (for example 30 % first, 100 % last).
- EV departure time ("100 % by 7:00") on top of the surplus logic.
- Off-peak top-up: an energy target (kWh) as an alternative to "stops consuming"; windows that change with the season or
  with tariff days; remembering that a device was found finished across restarts.
- Company sites: delay between two contactors closing, grouping devices behind one breaker, phase balancing.
- Detecting a device that does not obey (command sent, load not actually switched): there is no feedback loop yet.
- Home Assistant restart: the engine starts assuming every load is off, so the first cycle can under-estimate the surplus.

## Runtime and integrations

- Adapters for the Docker runtime: Modbus (TCP/RTU), OCPP, other HTTP styles (headers, body, authentication).
- MQTT TLS and client certificates (only user name and password today).
- Persisting runtime state across container restarts.
- A published Python package for the engine, so other projects can reuse it.

## Compatibility

See the "Wanted" list in [COMPATIBILITY.md](COMPATIBILITY.md). The most useful contribution is a brand- or model-specific
[profile](PROFILES.md): wallboxes (Zaptec, Easee, Wallbox...), heat pumps, other inverters and batteries, solar routers,
relays (Shelly, Tasmota). Ideas for the catalog itself: profiles that bring several devices at once (a router with its two
heaters), and a check that compares a profile's topics with a recorded device log.

## Community

- Translations of the Home Assistant forms and panel (level 4 of the contribution guide).
- Documentation in more languages, and worked examples for common installations.
