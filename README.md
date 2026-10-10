# solarprio (provisional name)

Open-source solar surplus router: choose the priority order of your loads
(water heater, EV charger, heat pump, battery, servers...) and let the surplus
flow to them automatically.

**Status: early prototype.** The core engine and the standalone runtime (Docker, MQTT/HTTP)
work and are tested. The Home Assistant integration is only a skeleton.

## Design

One engine, several ways to run it:

| Layer | Role | Status |
|---|---|---|
| `src/solarprio` | Pure Python engine, no Home Assistant dependency | working, tested |
| `src/solarprio/runtime` + Docker | MQTT source, MQTT/HTTP actuators, no Home Assistant needed | working, tested without Docker |
| `custom_components/solarprio` | Home Assistant integration (HACS) | skeleton only |

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

## Develop

```bash
pip install -e ".[dev]"
pytest
```

## License

Apache License 2.0, see [LICENSE](LICENSE). The project name and logo are not
covered by the license.
