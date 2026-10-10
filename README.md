# solarprio (provisional name)

Open-source solar surplus router: choose the priority order of your loads
(water heater, EV charger, battery, heat pump, servers...) and let the surplus
flow to them automatically.

**Status: early prototype.** The core engine and the standalone runtime (Docker, MQTT/HTTP)
work and are tested. The Home Assistant integration works in automated tests
(Home Assistant 2026.2.3) but has not been tried in a real installation yet.

## Design

One engine, several ways to run it:

| Layer | Role | Status |
|---|---|---|
| `src/solarprio` | Pure Python engine, no Home Assistant dependency | working, tested |
| `src/solarprio/runtime` + Docker | MQTT source, MQTT/HTTP actuators, no Home Assistant needed | working, tested without Docker |
| `custom_components/solarprio` | Home Assistant integration (HACS), carries a copy of the core | working in tests, not yet tried on a real HA |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Device types

| Type | Command | Specifics |
|---|---|---|
| On/off | switch | start margin, stay tolerance, min on/off times |
| Adjustable | light / number | percent or watts, minimum power |
| Battery | number (charge setpoint, W or %) | stops at a state-of-charge limit and resumes a few % lower; optional SoC and measured-power sensors |
| EV charger | number (current, A) + optional on/off switch | never below the minimum current (6 A by default, IEC 61851-1), whole-amp steps, fixed 1 or 3 phases, optional plugged-in, SoC and measured-power entities |

Behaviours worth knowing:

- A **full battery** (or a car at its target) stops asking for power, so the surplus goes to the next priority.
- An **unplugged car** gets nothing and does not reserve surplus. Unknown plug state counts as plugged.
- With a **measured power** entity, the engine uses the real consumption instead of the command, and frees
  the difference for lower priorities when a device takes less than commanded (a tapering battery) after a settle time.
- A SoC limit below 100 % **without a SoC sensor means no charging** (the limit cannot be checked).
- When routing stops (switch off, measurement lost, HA stops) every device gets 0: **a battery's charge setpoint
  goes to 0 W**, so a battery that normally charges by itself will not until routing resumes.
- Without an on/off switch an EV charger is paused with 0 A, which not every charger accepts.
- **Not supported:** automatic 1-phase/3-phase switching (hardware specific; some chargers need a re-plug to
  go back to 3 phases), discharge control of the battery, charging a battery in two priority stages.

## Run without Home Assistant

```bash
cp config.example.toml config.toml        # edit topics, powers, devices
docker compose -f docker-compose.example.yml up --build
```

or `pip install ".[runtime]" && solarprio --config config.toml`.

The runtime reads your meter from MQTT, decides, and publishes commands to MQTT topics
or calls HTTP URLs. If the measurement is lost it switches loads off (`on_stale = "off"`,
or `"hold"` to keep them as they are). On `SIGTERM` / `docker stop` it switches all
loads off before exiting.

## Use with Home Assistant

Copy `custom_components/solarprio` into your HA `config/custom_components/` (HACS publication
comes later), restart, then *Settings > Devices & services > Add integration > solarprio*:
pick the grid power sensor (or production + consumption), then use **Configure** to add
devices: pick the type first (on/off, adjustable, battery, EV charger), then fill the form for that type.
A `Routing` switch turns routing on/off; sensors show available power, routed power,
status and each device's commanded power.

**Priority panel.** A *solarprio* entry appears in the sidebar (admins only): drag a device by its
handle (mouse or touch), or use the arrows, to set the order; the top device is served first.
Changes apply immediately without switching anything off, and are saved. Each device also has an
on/off switch there, next to the master routing switch.

## Develop

```bash
pip install -e ".[dev]"
pytest                      # core + standalone runtime
python scripts/sync_core.py # after editing src/solarprio: refresh the copy used by the HA integration
python -m venv .venv-ha && .venv-ha/bin/pip install pytest-homeassistant-custom-component
scripts/test_ha.sh          # Home Assistant integration tests
scripts/e2e_ha.sh           # real Home Assistant + real Chromium driving the panel (slow)
```

The end-to-end test needs, in `.venv-ha`: `playwright`, and the packages in
`tests_e2e/ha-requirements.txt` (the frontend and the components it pulls in, pinned for
Home Assistant 2026.2.3). Chromium is read from `/opt/pw-browsers/chromium`.

## License

Apache License 2.0, see [LICENSE](LICENSE). The project name and logo are not
covered by the license.
