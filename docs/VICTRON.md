# Victron (GX device, Multi / Quattro / MultiPlus-II / Multi RS, EV Charging Station)

> **Not tested on real Victron hardware.** What follows is built from Victron's own documentation and exercised
> against a *simulated* GX device on a real MQTT broker. Read "What is verified" before relying on it.

## How it fits together

A Victron system with ESS charges its battery from solar **by itself**, first. What the battery cannot absorb is
exported to the grid. solarprio reads that export (the grid power) as the **surplus** and routes it to your
loads, here the EV charger. You do not need to manage the battery for this to work:

```
solar -> house loads -> battery (Victron ESS) -> grid export  --measured-->  solarprio  --> EV charger
```

Consequences: loads only get what the battery leaves. If you want a load to be served **before** the battery,
the battery's charge power would have to be limited, which this setup does **not** do (see "The battery").

## Setup (standalone runtime over MQTT)

The same configuration is available as profiles (`victron-grid`, `victron-evcs`, see [PROFILES.md](PROFILES.md) and
`examples/victron-profile.toml`); the steps below apply to both.

1. On the GX device, enable the MQTT broker on the local network (Venus OS settings; check Victron's manual for
   the exact menu of your firmware).
2. Find the **portal ID** (`<PORTAL_ID>`): subscribe to `N/#` with any MQTT client (for example
   `mosquitto_sub -h <gx-ip> -t 'N/#' -v`), then send a keep-alive (below). The topics look like
   `N/<portal ID>/system/0/...`.
3. Find the EV charger's **device instance** the same way: it appears as `N/<portal ID>/evcharger/<instance>/...`.
4. Put the EV Charging Station in **Manual** mode (`/Mode` = 0): Victron's documentation says `/SetCurrent` is
   only controllable in Manual mode.
5. Copy `config.victron.example.toml`, replace the `<...>` values, set the number of phases of your installation,
   and **check the sign** (next section).

### Keep-alive

Venus OS publishes values only after it receives a read request on `R/<portal ID>/keepalive`, and stops after
60 seconds without one. The runtime does this for you when `mqtt.keepalive_topic` is set: the first request (and the
first after a reconnection) is empty so that every value is republished; later ones carry
`{"keepalive-options": ["suppress-republish"]}`. The default interval is 30 s.

### Check the sign of the grid power

solarprio wants **positive = exporting to the grid**. Victron's documentation lists the grid power paths but does
not state their sign. The usual Victron convention is negative when exporting, which is why the example sets
`invert = true`, but **verify it on your system**:

1. Pick a moment where you are clearly exporting (sunny, battery full, nothing running), or clearly importing.
2. Watch `N/<portal ID>/system/0/Ac/Grid/L1/Power` (and L2, L3 if present).
3. If the numbers are **negative while exporting**, keep `invert = true`. If they are **positive while exporting**,
   set `invert = false`.

A wrong sign sends the surplus to the loads when you are importing and removes it when you are exporting.

### Phases

List in `export_topic` only the phases that exist. A phase that does not exist publishes `null`; the runtime then
treats the whole measurement as unavailable (by design: it does not under-count silently) and switches the loads off.

## The EV charger

- Commands: `/SetCurrent` (amps) and `/StartStop` (1 start, 0 stop), written as `{"value": X}` on
  `W/<portal ID>/evcharger/<instance>/...`, without the retain flag.
- Plug state from `/Status`: 0 = disconnected; 1 to 7 and 21 to 24 are treated as plugged in; other codes (errors)
  count as unknown, which the engine treats as plugged in.
- Measured power from `/Ac/Power`, so the engine uses the real consumption.
- `min_current_a` / `max_current_a` in the example are generic (6 A / 16 A): set them to your charger's limits
  (`/MinCurrent`, `/MaxCurrent`). Victron documents `/MaxCurrent` as an installer setting, not for dynamic control.
- Victron's own **Auto** and **Scheduled** modes (and the "Waiting for sun" state) can do excess-solar charging
  by themselves. Use one controller or the other for a given charger, not both.
- Automatic 1/3 phase switching is not supported by solarprio (the charger may do it itself; the number of phases
  you configure is fixed).

## The battery

Not managed in the example. Victron documents `Settings/CGwacs/MaxChargePower` ("Max Charge Power") and
`Settings/CGwacs/AcPowerSetPoint` (grid set-point) as ESS **user settings**, and `hub4/0/Overrides/Setpoint`.
Limiting the battery's charge power from solarprio is therefore possible in principle (a `battery` device writing
`MaxChargePower` with `payload_template`), but I did not verify what the system does with such values, how often
they may be written, or how it interacts with BatteryLife, Dynamic ESS or the ESS mode. Community reports say the
ESS ramps gradually and that some setpoints revert after about a minute on some devices. Do not automate this
without reading Victron's ESS documentation and testing carefully.

## Home Assistant

The integration works with any entities. Home Assistant's documentation lists a **Victron GX** integration
(MQTT, GX devices); it is newer than the Home Assistant version used to test solarprio (2026.2.3), so
**I have not tried it** and do not know which entities it exposes. You need: a power sensor for the grid
(positive = export, or use production and consumption sensors), and for the charger a `number` entity for the
charging current in amps plus, ideally, a switch for start/stop and a plugged-in entity.

## What is verified

| Item | Source | Status |
|---|---|---|
| `N/` topics carry `{"value": X}`, `null` when unavailable | [dbus-flashmq README](https://github.com/victronenergy/dbus-flashmq) | read in the source |
| Keep-alive on `R/<id>/keepalive`, 60 s timeout, `suppress-republish` option | same | read in the source, simulated |
| Writes on `W/<id>/...` with `{"value": X}`, no retain | same | read in the source, simulated |
| EVCS paths `/SetCurrent`, `/StartStop`, `/Mode`, `/Status`, `/Ac/Power`; `/SetCurrent` only in Manual mode | [Venus OS D-Bus list](https://github.com/victronenergy/venus/wiki/dbus) | read in the source |
| `/Dc/Battery/Soc`, `/Dc/Battery/Power` exist; battery power is positive when charging | same | read in the source |
| Grid power paths per phase on the system service | same | read in the source |
| **Sign of the grid power** | not stated | **you must verify** |
| Behaviour on a real GX / EVCS / Multi | none | **not tested** |

## Limits

- No real-hardware test; the simulated device is my reading of the documentation.
- TLS and Victron's cloud (VRM) MQTT broker are not supported: only the GX device's local broker, with optional
  username/password.
- Battery management, Dynamic ESS and ESS mode interplay: not handled.
