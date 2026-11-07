# Driving an ESPHome solar router from solarprio

> **Recommended: the router as an actuator only.** Let solarprio take every decision (temperatures, off-peak, sanitary
> minimum, subscription, smooth ramps) and keep in the ESP only what protects the equipment. Use
> [`examples/esphome/solar-router-actuator.yaml`](../examples/esphome/solar-router-actuator.yaml) and follow
> [WATER_HEATER_EXAMPLE.md](WATER_HEATER_EXAMPLE.md). What the ESP then does: applies the order in watts of the number
> *Consigne externe (W)*; goes to 0 W by itself at boot, when Home Assistant disconnects, when no order arrives within the
> delay (default 120 s, solarprio resends every 30 s), when the triac is too hot, when the tank probe is missing and above
> an absolute safety temperature; reports the water temperature and the real power (R x I squared). Passed `esphome
> config`; the C++ was not compiled and nothing was run on hardware.
>
> The rest of this page describes the **other** way: keeping the router's own regulation and adding an external-control
> input to it. Only useful if you want the router to keep deciding by itself.

An ESPHome router (a triac or SSR output for a water heater, regulated from a grid measurement) normally closes its
own loop: it measures the grid and decides how much to heat. solarprio decides **between several loads** (heater,
EV charger, battery...), so the router must also accept a power order from outside. This page describes a pattern
that keeps every local safety of the router and adds that input. It was written for one real configuration (a
water heater with a phase-angle triac) and checked with `esphome config` (ESPHome 2026.9.1). **The C++ of the
lambdas was not compiled** (the build tool could not be downloaded in the environment used), and nothing was run on
hardware: compile it yourself and test with the heater's own mechanical safety thermostat in place.

## The pattern

Three entities on the ESP, one rule in its control script:

| Entity | Role |
|---|---|
| `switch` "External control" | ON: the local grid-based regulation is suspended, the power comes from the order. OFF (default after a reboot): local regulation, as before. |
| `number` "External setpoint (W)" | The power solarprio asks for. **Never restored** at boot. |
| `number` "External control timeout (s)" | No new order within this delay: the power falls back to 0 W. |

The rule, placed **after** all the safety checks of the script (mode, triac temperature, tank probe, maximum
temperature), so none of them can be bypassed:

```cpp
if (id(external_control)->state) {
  const uint32_t timeout_ms = (uint32_t)(id(external_timeout)->state * 1000.0f);
  if (id(last_order_ms) == 0 || (uint32_t)(now - id(last_order_ms)) > timeout_ms) {
    apply(0, "External control: no recent order");   // watchdog
    return;
  }
  float order = id(external_setpoint)->state;
  if (std::isnan(order) || order < 0.0f) order = 0.0f;
  apply(order, "External control");                  // apply() clamps to the heater's maximum power
  return;
}
```

Four details that matter (each was a real bug candidate):

1. **Timestamp real orders only.** The setpoint `number` uses `set_action` (runs only when something *writes* the
   value), not `on_value` (also runs on the ESP's own `publish_state`, so a boot or a reset would look like an order).
   ESPHome's template number runs `set_action` on every write, including a repeated identical value.
2. **Invalidate the order when Home Assistant disconnects.** If the API-disconnect handler only zeroes the output, a
   1 Hz control script re-applies the previous setpoint until the timeout expires, while solarprio is unreachable.
   Set `last_order_ms = 0` there, and when the external-control switch changes.
3. **The sender must repeat its orders.** The Home Assistant integration re-sends unchanged commands every 30 s
   (`RESEND_EVERY_S`), the Docker runtime every `resend_every_s` (60 s by default). Keep the timeout **at least twice**
   that interval (default 120 s).
4. **Fail towards zero.** No order, an invalidated order, an out-of-range value or `NaN`: 0 W.

## Configuring solarprio

In Home Assistant: *Configure* > add a device of type **adjustable**:

- entity: the "External setpoint (W)" `number`;
- type of value: **watts**; maximum power: the heater's power (the same as the ESP's maximum power);
- measured power entity (optional but recommended): the heater's real power sensor, so the engine uses the real
  consumption instead of the command;
- minimum run and rest times as you like.

Then turn the ESP's "External control" switch ON. If you want solarprio to be in charge permanently, you may switch
its restore mode to ON in the ESP configuration; the heater still draws 0 W until the first order arrives.

## Two things found on the way (checked in the sources)

- **Home Assistant only forwards state *changes* to ESPHome.** The integration subscribes to state-change events
  (Home Assistant 2026.2.3, `esphome/manager.py`). A Linky value that stays identical for 30 s therefore looks like
  "no data" to a freshness watchdog on the router. ESPHome's `force_update: true` on the *source* sensor makes Home
  Assistant emit a state change even when the value is unchanged (it can enlarge the database: exclude those entities
  from the recorder if needed).
- **An unavailable entity reaches the ESP as `NaN`**, not as "no state" (ESPHome 2026.9.1,
  `homeassistant_sensor.cpp`). A script that only checks `has_state()` keeps treating `NaN` as a measurement:
  ignore `NaN` when timestamping, and treat `NaN` as invalid in the regulation.

## What is not verified

- The lambdas' C++ was not compiled and nothing was run on hardware.
- The behaviour of a particular heater's own thermostat and safety devices.
- Latency from solarprio to the triac in a real installation (Home Assistant, Wi-Fi, ESP loop).
