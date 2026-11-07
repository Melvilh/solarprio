# Adding compatibility with your hardware

solarprio is meant to grow with the hardware people actually own. Most of the time **no code is needed**: a working
configuration, tested and written down, is already a contribution. Pick the level that fits.

| Level | You add | Code? | Typical example |
|---|---|---|---|
| 1. Recipe | A tested configuration and a short page | No | "Shelly relay for a boiler", "Tasmota plug", a wallbox that exposes `number` entities |
| 2. Adapter | A new way to read a measurement or send a command in the Docker runtime | Python | Modbus, OCPP, another HTTP style |
| 3. Device type | A new behaviour in the engine | Python + Home Assistant UI | A heat pump with several stages, a two-stage battery |
| 4. Translation | A language for the Home Assistant forms and panel | JSON/JS | Spanish, German |

Before you start, open an issue with the **Compatibility** template so nobody works twice on the same thing, and so we
can tell you which level fits. You do not need to be sure it works: say what you tried and what happened.

## What "supported" means here

Be precise about what you tested; the project never claims more than that (see [COMPATIBILITY.md](COMPATIBILITY.md)).

- **Verified on real hardware**: you ran it on the real device, with the safety devices of the load in place, for a
  meaningful time. Say which firmware/version and what you observed.
- **Simulated**: automated tests with a simulated device or broker. Useful, but it is not hardware.
- **From the manufacturer's documentation**: written from the docs, not run. Say so in the page.

## Level 1 — a recipe (no code)

A load only needs three things: *how to command it*, *how to measure what it draws*, and *how to measure the grid*.

**Home Assistant.** If the device shows up as a Home Assistant entity, it is already usable:

| Load | Device type | Entity |
|---|---|---|
| Relay, contactor, smart plug, charging point behind a contactor | on/off | `switch` / `input_boolean` / `light` |
| Dimmer, solar router, heater with a setpoint | adjustable | `light`, or `number` / `input_number` (percent or watts) |
| Battery inverter charge setpoint | battery | `number` / `input_number` (W or %) |
| Wallbox with a current setpoint | EV charger | `number` (A), optional `switch` to pause |

Add a **measured power** sensor whenever you have one: it lets the engine free the surplus when the load takes less than
commanded, and it is required for the off-peak top-up. Steps: [DEMARRAGE_FR.md](DEMARRAGE_FR.md) (French) and the
examples [WATER_HEATER_EXAMPLE.md](WATER_HEATER_EXAMPLE.md), [MANY_DEVICES.md](MANY_DEVICES.md).

**Docker runtime (no Home Assistant).** Commands go out through an MQTT topic or an HTTP call, measurements come from
MQTT topics. See `config.example.toml` and, for a worked case with JSON payloads and a keep-alive, [VICTRON.md](VICTRON.md).
The actuator options you can use today:

- MQTT: `topic`, `scale` (`watts`, `percent` or `amps`), `payload_on` / `payload_off`, `payload_template` (wraps the
  numeric command, `{value}` is replaced, e.g. `{"value": {value}}`), `switch_topic` for chargers, `retain`.
- HTTP: `url` with the placeholders `{power_w}`, `{percent}`, `{amps}` and `{state}` (on/off), and `method` (default
  `GET`). Only `http://` and `https://` are accepted; no custom headers or body yet. A 4xx/5xx answer counts as a failed command.
- Readings: `measured_topic` (+ `measured_unit`), `soc_topic`, `connected_topic` with `connected_values` /
  `disconnected_values` for numeric status codes.

**What to deliver**

1. `examples/<vendor>-<model>.toml` (Docker) and/or a page `docs/hardware/<vendor>-<model>.md` (use
   [docs/hardware/_TEMPLATE.md](hardware/_TEMPLATE.md)). Every `*.toml` in `examples/` and every `config*.example.toml`
   is parsed by the test suite (`tests/test_examples.py`), so a broken example fails CI.
2. Replace anything personal (addresses, identifiers, passwords) with `<PLACEHOLDERS>`.
3. A line in [COMPATIBILITY.md](COMPATIBILITY.md) with the honest status.
4. If the hardware needs something unusual (a keep-alive, a sign convention, a watchdog), say so in the page; those are
   exactly the things the next person would trip on.

## Level 2 — an adapter for the Docker runtime

The engine only knows two small interfaces, in `src/solarprio/ports.py`:

```python
class PowerSource:     async def read_available_w(self, routed_w: float) -> float: ...
class DeviceActuator:  async def apply(self, device_id: str, power_w: float) -> None: ...
class ReadingsSource:  def read_readings(self) -> dict[str, DeviceReading]: ...
```

To add, say, a Modbus actuator:

1. Write the class in `src/solarprio/runtime/` implementing `apply`. **Raise an exception when the command could not be
   delivered** (do not swallow errors): the controller then retries it and keeps the engine from counting power that
   was never delivered.
2. Teach `DispatchActuator` (`runtime/adapters.py`) about the new type, and add the type name to the check in
   `runtime/config.py` (the list `("mqtt", "http")`) with a start-up validation of its options. Fail at start-up, not at
   the first command.
3. Tests (see below), an example under `examples/`, and a documentation page. Optional dependencies go in an extra in
   `pyproject.toml` so the base install stays light.

A new measurement source follows the same pattern with `PowerSource` / `ReadingsSource`. Remember the rule that makes
the loop stable: `available_w` **includes the power managed loads already draw** (helpers in `sources.py`).

## Level 3 — a new device type

Only when no existing type can express the behaviour. The places to touch, all of them:

| File | What |
|---|---|
| `src/solarprio/models.py` | `DeviceKind` value and the `Device` fields it needs, with validation |
| `src/solarprio/engine.py` | the behaviour in `_wanted` (and in the off-peak/safety paths if relevant) |
| `custom_components/solarprio/coordinator.py` | `DEVICE_FIELDS` and how the command is sent (`_call`) |
| `custom_components/solarprio/forms.py` | the fields of the form for that type (`device_fields`): the Home Assistant form and the panel both read them |
| `custom_components/solarprio/translations/*.json`, `strings.json` | labels and help texts (a test checks the files agree) |
| `src/solarprio/runtime/adapters.py` | how the Docker runtime sends it |
| `docs/`, `README.md`, `CHANGELOG.md` | what it does and what is *not* verified |

After editing `src/`, run `python scripts/sync_core.py` (the Home Assistant copy of the engine; a test fails otherwise).
Design rules that keep the project safe:

- **Fail toward off.** An unknown, missing or out-of-range input means 0, never "keep going".
- **Safety limits beat comfort timers** (state-of-charge limit, car unplugged, measurement lost).
- **No hidden assumptions about real devices.** If a limit comes from a standard or a datasheet, name the source in a
  comment; if you are unsure, make it a setting.

## Tests, the project's contract

Run these before opening a pull request ([CONTRIBUTING.md](../CONTRIBUTING.md) has the setup):

```bash
.venv/bin/pytest                 # engine + standalone runtime (includes the real-MQTT tests)
scripts/test_ha.sh               # Home Assistant integration
```

- Every behaviour change needs a test **that fails when the behaviour is broken**: temporarily break your code and check
  the test goes red. A test that cannot fail proves nothing.
- Engine tests inject time and a wall clock; look at `tests/test_offpeak.py` for a small simulator of loads.
- Use a simulated device for CI; a real-hardware report goes in the documentation, not in the test suite.

## Level 4 — a translation

Copy `custom_components/solarprio/translations/en.json` to `<lang>.json` and translate the values (a test checks the
keys match `strings.json`). The sidebar panel keeps its own small dictionaries in
`custom_components/solarprio/frontend/panel.js` (the object `T`, with one entry per language), chosen from Home
Assistant's language; add yours next to `en` and `fr`.

## Pull request checklist

- [ ] What you tested, on what, and for how long; what you could **not** test.
- [ ] Tests added and shown to fail when the behaviour is broken.
- [ ] `pytest`, `scripts/test_ha.sh` pass; `python scripts/sync_core.py` run if `src/` changed.
- [ ] Documentation and `CHANGELOG.md` updated; no personal data in examples.
- [ ] You agree your work is under the Apache License 2.0.

## En français (résumé)

La plupart des compatibilités ne demandent **aucun code** : une configuration testée et documentée suffit (niveau 1).
Ouvrez un ticket « Compatibility », déposez `examples/<marque>-<modele>.toml` et/ou une fiche `docs/hardware/` d'après le
modèle, et ajoutez une ligne dans [COMPATIBILITY.md](COMPATIBILITY.md) en disant **honnêtement** ce qui a été testé
(matériel réel, simulé, ou d'après la documentation du fabricant). Un nouvel adaptateur (Modbus, OCPP…) ou un nouveau type
d'appareil demande du Python : suivez les tableaux des niveaux 2 et 3. Chaque changement de comportement doit avoir un test
qui échoue quand le comportement est cassé.
