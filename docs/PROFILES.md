# Profiles: ready-made devices by brand and model

A **profile** describes a device or a measurement source of a given brand and model: the topics, payloads, limits and
quirks that are known for it. You then only give what is yours (an identifier, a number of phases, the entities). Profiles
are plain JSON files in [`src/solarprio/profiles/data/`](../src/solarprio/profiles/data): adding one needs **no Python**.

## What exists today

| Profile | For | Target | Status |
|---|---|---|---|
| `generic-water-heater-dimmer` | Water heater behind a solar router (adjustable power) | device, Home Assistant + Docker | Simulated |
| `generic-water-heater-relay` | Water heater on a relay or contactor | device, Home Assistant + Docker | Simulated |
| `victron-evcs` | Victron EV Charging Station through a GX device (MQTT) | device, Home Assistant + Docker | Simulated, from docs ([VICTRON.md](VICTRON.md)) |
| `victron-grid` | Grid power per phase from a GX device, with the keep-alive | source, Docker | Simulated, from docs; **sign to verify** |

"Simulated" means automated tests against a simulated device: **nothing is verified on real hardware yet**
([COMPATIBILITY.md](COMPATIBILITY.md)). The panel says so next to every brand model that is not verified.

## Using a profile

**Home Assistant.** *Add a device* lists the models first (`Ready-made`), then the plain types. A model fills the form with
its usual values; you pick the entities. Everything stays editable.

**Docker (TOML).** Write `profile` and `params`; anything you write next to it overrides the profile:

```toml
[source]
profile = "victron-grid"
params = { portal_id = "<PORTAL_ID>", phases = 3, invert = true }

[[device]]
profile = "victron-evcs"
params = { portal_id = "<PORTAL_ID>", instance = 40, phases = 1 }
id = "evcs"
name = "Victron EVCS"
priority = 1
max_current_a = 10          # overrides the profile
```

The full file is [`examples/victron-profile.toml`](../examples/victron-profile.toml); a test checks that it gives exactly the
same configuration as the hand-written `config.victron.example.toml`. A profile source also fills the `[mqtt]` section it
needs (the Victron keep-alive); the `[mqtt]` you write wins.

## Writing a profile

One file `src/solarprio/profiles/data/<brand>-<model>.json`; the id is the file name, in lowercase words joined by dashes.

| Key | Meaning |
|---|---|
| `brand`, `model`, `label` | `label` is `{"en": ..., "fr": ...}` (English required) |
| `category` | `water_heater`, `heat_pump`, `ev_charger`, `battery`, `inverter`, `relay`, `meter`, `task`, `other` |
| `target` | `device` (a load) or `source` (a measurement) |
| `status` | `verified`, `simulated`, `from_docs` or `untested`: be honest, it is shown to users |
| `docs` | the page that explains the quirks |
| `params` | what the user must give: `{"name", "required" or "default", "description"}` |
| `runtime` | the Docker configuration (`[[device]]` or `[source]` keys); `${name}` is replaced by a parameter, and keeps its type |
| `ha` | optional, for devices: `{"kind": ..., "values": {...}}` pre-filled in the Home Assistant form |
| `notes` | what is not verified, what to check |

`{"$repeat": "phases", "template": "...L${n}..."}` repeats a template once per phase (1 to 12). Unknown keys, unknown
placeholders and a wrong id are refused when the catalog loads, and a test loads every profile.

After adding or editing a profile run `python scripts/sync_core.py` (Home Assistant carries a copy) and the test suites,
then add the line to [COMPATIBILITY.md](COMPATIBILITY.md). A profile is the preferred way to add a brand:
[ADDING_COMPATIBILITY.md](ADDING_COMPATIBILITY.md).

## What a profile does not do

It does not change the engine's safety rules, and it does not prove anything on real hardware: a profile written from a
datasheet is `from_docs`, and only a person who ran it and wrote down what they saw can make it `verified`.
