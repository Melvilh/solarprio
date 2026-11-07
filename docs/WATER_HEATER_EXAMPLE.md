# Example: a water heater on a solar router, everything decided by solarprio

The router (an ESP32 with a triac dimmer) is only the **actuator**: it applies a power order in watts and reports the water
temperature and the real power. solarprio decides, using the Linky and the tariff.
Concepts: [REGULATION.md](REGULATION.md). The router side: [ESPHOME_ROUTER.md](ESPHOME_ROUTER.md).

The entity ids below are those of one real installation (area `garage_`). **Check yours** in *Settings > Entities*: they
start with the area of the device and follow its names.

## 1. The router

Flash [`examples/esphome/solar-router-actuator.yaml`](../examples/esphome/solar-router-actuator.yaml) (fill its
substitutions: pins, probe addresses, power) after compiling it yourself. It creates the number **Consigne externe (W)**,
which solarprio writes; a watchdog (120 s by default) brings it back to 0 W if the orders stop.

## 2. The site settings (solarprio panel > Settings)

| Setting | Value | Why |
|---|---|---|
| Grid power sensor | a sensor that **changes all the time**, positive when you import (tick *import is positive*) | for example the net power of the Energy dashboard |
| Measurement lost after | `0` | the Linky injection sensor does not repeat a value that did not change |
| Margin | 60 W | what the router used to keep |
| Subscription limit | 5700 VA | 6 kVA minus 300 VA |
| House power sensor | `sensor.garage_esp_teleinfo_linky_puissance` | the house as seen by the meter |
| Emergency cut | 250 W | |

Check the **sign** with the sun out and little consumption: the sensor must show an export.

## 3. The device (panel > Add a device > *Water heater on a solar router*)

| Field | Value |
|---|---|
| Entity to control | `number.garage_chauffe_eau_consigne_externe_w` |
| Value sent | watts |
| Maximum power | 2400 |
| Measured power | `sensor.garage_chauffe_eau_puissance_chauffe_eau` |
| Temperature sensor | `sensor.garage_chauffe_eau_temperature_chauffe_eau` |
| Stop with the sun / off-peak | 65 °C / 60 °C |
| Off-peak entity | `sensor.garage_esp_teleinfo_linky_periode_tarifaire_brute` |
| States meaning off-peak | `HC*` |

The model already sets the rest: hysteresis 3 °C, sanitary minimum 40 °C, wait 8 s, step 200 W, ignore 15 W, minimum run and
rest 30 s. To use only the **night** off-peak hours (what the old *HC_midi* switch off did), also fill the windows
(`22:30-06:30`, your own hours): both the tariff signal and the window must then say off-peak.

**Mistake seen on a real installation**: `sensor.garage_esp_teleinfo_linky_heures_creuses` is an **energy index** (a number
that only grows), not the tariff period. The period reads `HP..` or `HC..`. The panel warns when the chosen entity gives a
number.

## 4. What replaces what

| In the old ESP file | Now |
|---|---|
| Solar routing from the Linky (feed-forward), margin | solarprio: surplus by priority, *margin* |
| Wait for a fresh Linky reading after a change | *Wait after a change* (`hold_s`) |
| Step up limit, dead zone | *Largest step up*, *Ignore changes under* |
| Emergency cut on grid import | site *Emergency cut* |
| `Température Max ... solaire / HC`, hysteresis | the two maximums and the hysteresis of the device |
| `CE Trop Froid`, *Marche forcée* | *Sanitary minimum* (on as soon as the minimum is set) |
| *Surplus uniquement* | *Surplus only* of the device |
| `Mode HC`, `HC_midi` | the off-peak entity (and optional windows) |
| Subscription ceiling (`Plafond puissance maison`) | site *Subscription limit* with the house power sensor |
| `Mode Auto`, `Routage Solaire Actif` | the device switch and the routing switch of the panel |
| Triac temperature, probe fault, API disconnect | **kept in the ESP** (equipment protections) |
| Absolute maximum temperature | **kept in the ESP** (*Température de sécurité*, 75 °C) |

## 5. Putting it into service

1. Keep the old ESP file (the sanitary copy of it stays yours). Flash the new one: the heater is at 0 W until solarprio sends.
2. Add the site settings and the device. In the panel the row shows the temperature and the mode (solar, off-peak, sanitary,
   hot, limited by the subscription, temperature unknown).
3. **Watch the first day** with the heater's own mechanical thermostat in place. The tests use simulated sensors and heaters.
4. Rolling back: flash the old file.

## Not verified

Nothing here ran on a real router, heater or Linky. The new ESP file passed `esphome config`; its C++ was not compiled.
