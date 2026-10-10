# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

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

### Safety behaviour
- Undelivered commands (broker down, service error) are retried and never counted as routed power.
- On shutdown every configured device is switched off, and the process exits non-zero if some may still be on.

### Known limitations
- Not tested on real inverters, batteries or wallboxes.
- No automatic 1/3 phase switching, no battery discharge control, no two-stage battery priority.
- A battery charge setpoint goes to 0 W when routing stops.
