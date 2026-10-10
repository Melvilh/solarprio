# solarprio (provisional name)

Open-source solar surplus router: choose the priority order of your loads
(water heater, EV charger, heat pump, battery, servers...) and let the surplus
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
devices (switch, light, number) and set their priority number (lower = served first).
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
