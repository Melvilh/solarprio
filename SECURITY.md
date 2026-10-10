# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's *Security > Report a vulnerability* on the repository
(private vulnerability reporting), not in a public issue. Include what you found, how to reproduce it and what
it could affect. Maintainers will acknowledge reports as soon as they can; this is a volunteer project.

## What to keep in mind

- This software controls electrical loads; a flaw can mean a load stays on or off unexpectedly.
  Keep your hardware's own protections in place.
- **Home Assistant:** the sidebar panel and every websocket command are restricted to administrators.
  Device commands are only sent to entities you configured.
- **Standalone runtime:** MQTT credentials are read from the configuration file in clear text, and the runtime
  supports username/password only (no TLS options yet). HTTP actuators call URLs written by the operator in
  the configuration file. Protect that file, keep the broker off untrusted networks, and do not use the
  anonymous example broker configuration (`mosquitto.conf`) outside a test setup.
- The container runs as a non-root user.
