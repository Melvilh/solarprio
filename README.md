# solarprio (provisional name)

Open-source solar surplus router: choose the priority order of your loads
(water heater, EV charger, heat pump, battery, servers...) and let the surplus
flow to them automatically.

**Status: early prototype.** Only the core engine exists and is tested.
Home Assistant integration and the standalone runtime are not implemented yet.

## Design

One engine, several ways to run it:

| Layer | Role | Status |
|---|---|---|
| `src/solarprio` | Pure Python engine, no Home Assistant dependency | working, tested |
| Standalone runtime (Docker) | MQTT / HTTP adapters, no Home Assistant needed | not started |
| `custom_components/solarprio` | Home Assistant integration (HACS) | skeleton only |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Develop

```bash
pip install -e ".[dev]"
pytest
```

## License

Apache License 2.0, see [LICENSE](LICENSE). The project name and logo are not
covered by the license.
