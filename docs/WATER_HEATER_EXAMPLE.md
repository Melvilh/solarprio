# Example: a water heater on an ESPHome triac router

Configuration for a water heater driven by an ESPHome router (phase-angle triac), whose grid measurement comes from a
Linky read by another ESP. The router side is described in [ESPHOME_ROUTER.md](ESPHOME_ROUTER.md): the router must have the
external-control pattern (switch, setpoint, timeout, watchdog) before this page makes sense.

The entity ids below come from the ESPHome names of one real configuration, converted with Home Assistant's slug rules.
**Check them in your own *Settings > Entities*** and replace them if they differ.

| Role | Entity id used here |
|---|---|
| Linky, power withdrawn (VA) | `sensor.garage_esp_teleinfo_linky_puissance` |
| Linky, power injected (VA) | `sensor.garage_esp_teleinfo_puissance_injectee` |
| Router order (W) | `number.chauffe_eau_consigne_externe_w` |
| Router real power | `sensor.chauffe_eau_puissance_chauffe_eau` |
| External control switch | `switch.chauffe_eau_pilotage_externe_solarprio` |

## 1. One net grid sensor

The Linky gives two separate positive values (withdrawn, injected). solarprio wants one signed value, positive when
exporting. In `configuration.yaml` (or *Helpers > Template*):

```yaml
template:
  - sensor:
      - name: "Reseau export net"
        unit_of_measurement: "W"
        device_class: power
        state: >
          {{ states('sensor.garage_esp_teleinfo_puissance_injectee') | float
             - states('sensor.garage_esp_teleinfo_linky_puissance') | float }}
        availability: >
          {{ has_value('sensor.garage_esp_teleinfo_puissance_injectee')
             and has_value('sensor.garage_esp_teleinfo_linky_puissance') }}
```

If either Linky sensor is unavailable the net sensor becomes unavailable, which solarprio treats as a lost measurement
(heater ordered to 0 W). The values are in VA and are used as W: close enough for a resistive heater, but it is an
approximation.

## 2. solarprio

- Source: mode **export**, entity `sensor.reseau_export_net`, invert off.
- **Export margin**: 100 W to start with. It is left unrouted on purpose so measurement noise and the delay between
  order and effect do not turn into grid import. Lower it only after watching your real meter.
- Stale after: the net sensor is a template and the ESPHome integration only forwards value *changes*, so a steady value
  can look old. Keep 60 s or more, and put `force_update: true` on the two Linky sensors in the garage ESP.
- Device, type **adjustable**: entity `number.chauffe_eau_consigne_externe_w`, value in **watts**, maximum power = the
  heater power (2400 W in the tests), minimum power 200 W, measured power entity
  `sensor.chauffe_eau_puissance_chauffe_eau`.

Then switch `switch.chauffe_eau_pilotage_externe_solarprio` ON on the ESP. Keep the ESP's timeout at 120 s or more
(solarprio repeats its order every 30 s).

## What the automated test checks

`tests_ha/test_water_heater_example.py`, on a real Home Assistant with simulated sensors and a simulated router:

- the template nets injected and withdrawn power, and goes unavailable (not zero) if one side is missing;
- 800 W exported with a 100 W margin orders 700 W, and the order stays at 700 W once the heater really draws it
  (no oscillation);
- losing a Linky sensor orders 0 W;
- over ten minutes of steady state, the 30 s repeats keep a router with a 120 s watchdog from falling to 0 W; with a
  timeout shorter than the repeat interval it does fall (negative control).

## What is not verified

- Nothing was run on the real ESPs, triac or heater; the router is simulated by its contract.
- The C++ of the ESPHome patch was not compiled.
- Real latency (Linky refresh, Wi-Fi, Home Assistant, triac loop) and whether 100 W is the right margin.
- Phase-angle control of the heater and its electronics: check with the heater's maker, keep its thermostat.
