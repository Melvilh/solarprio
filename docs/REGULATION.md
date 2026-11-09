# Central regulation: one brain for every heater and variable load

solarprio takes **every decision**. The devices only execute a power. That is the point: with several water heaters, a heat
pump, a battery, a charger, the rules (temperatures, off-peak hours, subscription, smooth ramps) live in one place, are the
same for all of them, and a low-cost solar router only has to be an actuator that follows an order in watts.

What stays in the device, on purpose, are the protections of the equipment itself: a triac that is too hot, a missing
temperature probe, an absolute maximum temperature, a watchdog that goes to 0 W when no order arrives. See
[ESPHOME_ROUTER.md](ESPHOME_ROUTER.md) and [`examples/esphome/solar-router-actuator.yaml`](../examples/esphome/solar-router-actuator.yaml).

## What solarprio decides, in this order

For every device, at every control cycle:

1. **Disabled** (the switch in the panel): 0.
2. **Temperature unknown** on a device that has temperature settings: 0 (*sensor fault*). The limits cannot be checked, so
   nothing is fed, with the sun or from the grid, until the reading is back.
3. **Sanitary minimum** (`temp_min`): the water fell under it, so it is fed **from the grid** at full power whatever the
   sun or the hours, until it is back above the minimum plus the hysteresis. Not if *Surplus only* is set.
4. **Off-peak top-up**: during off-peak periods the device is fed from the grid until the tank reaches its off-peak
   maximum, or it stops consuming (a thermostat opened). See [OFFPEAK.md](OFFPEAK.md). Not if *Surplus only* is set.
5. **Tank at its solar maximum** (`temp_max_solar`): no more heating with the sun (*hot*), resumes below the maximum
   minus the hysteresis.
6. **Emergency cut**: more than `emergency_import_w` is imported from the grid (not counting what is fed from the grid on
   purpose): everything running on the sun is cut at once, no timer holds it back.
7. **Solar surplus** by priority, smoothed: after a change the device waits `hold_s` before going up (half before going
   down), goes up by at most `ramp_up_w` at a time, and ignores changes under `deadband_w`.

When the **grid measurement is lost** nothing is fed from the grid on purpose (3 and 4 are off) and the devices stop,
unless you chose to hold the state.

## The subscription cap

If you give the **house limit** (your subscription in VA) and a **house power sensor**, everything fed from the grid on
purpose (3 and 4) is limited to the room left:

- the room is the limit minus what the *rest* of the house draws (the house power minus what the managed devices draw);
- under 150 W of room nothing is fed; the room is rounded down to 100 W steps;
- an adjustable load gets what fits (a heater of 2400 W in 1200 W of room gets 1200 W); an on/off load either fits or stays
  off; two heaters share the room by priority;
- an adjustable load does not go up by steps smaller than 200 W (the measurement would only hunt); it goes down at once;
- if the house goes more than 200 VA over the limit while grid-fed loads run, they are all cut and wait 60 seconds;
- **without a view on the house power, nothing is fed from the grid.** A device cut by the cap is cut at once: no minimum
  run time holds it on.

Without a house limit there is no cap (the off-peak budget of [MANY_DEVICES.md](MANY_DEVICES.md) still applies).

## Settings of a device

Water heater and any load heated to a temperature (a heat pump tank, a buffer), on/off or adjustable. Most are under
*Advanced settings* in the panel; the **ready-made models** fill them with the usual values for a domestic water heater
(check them with your installer).

| Setting | Meaning | Usual |
|---|---|---|
| Temperature sensor | where the water temperature comes from; needed by every temperature setting | |
| Stop with the sun at (`temp_max_solar`) | no solar heating above it | 65 °C |
| Stop in off-peak hours at (`temp_max_offpeak`) | same for the off-peak top-up; default: the solar value | 60 °C |
| Hysteresis (`temp_hysteresis`) | how far below a limit before heating resumes | 3 °C |
| Sanitary minimum (`temp_min`) | below it, fed from the grid; empty = never for this reason | 40 °C |
| Surplus only (`surplus_only`) | never fed from the grid (no off-peak, no sanitary) | off |
| Wait after a change (`hold_s`) | settle time before raising the power (adjustable loads) | 8 s |
| Largest step up (`ramp_up_w`) | the power never rises by more than this at once | 200 W |
| Ignore changes under (`deadband_w`) | no change for a few watts | 15 W |

Why `hold_s` matters: the grid measurement needs a few seconds to show the effect of a change of power. Correcting again on
a reading that does not show the last change yet is what makes a regulation overshoot and import from the grid.

## Settings of the site

| Setting | Meaning |
|---|---|
| Subscription limit (VA) and house power sensor | the cap above |
| Emergency cut (W) | import above which everything running on the sun is cut |
| Margin (W) | watts deliberately left unrouted, so noise does not become import |
| Measurement lost after (s) | 0 = never judge by age, only by availability (see below) |

**A sensor that does not repeat a value that did not change** (typical of ESPHome sensors seen by Home Assistant) looks
"old" while it is perfectly healthy: the panel then says *has not reported for N s*. Set the delay to 0 for such a sensor;
a dead ESP still makes its sensors *unavailable*, which is detected.

## The water heater controls (Home Assistant)

These replace the switches and sensors you used to have on the router itself ("Forced run", "HC midi", "Is it hot", "Heating
mode"). They belong to solarprio, so they work the same for every heater.

| What you want | Setting of the device | Entity created in Home Assistant |
|---|---|---|
| The sanitary minimum heats from the grid **only when you ask for a forced run** | tick *Sanitary minimum only on a forced run* (needs the minimum temperature) | switch `<device> forced run` (off after a first install; the state is restored after a restart) |
| Choose whether the **midday off-peak hours** heat, the night always does | *Off-peak windows*: `22:30-06:30`; *Extra off-peak windows*: `12:30-14:30` | switch `<device> extra off-peak windows` |
| Is it hot? | any temperature limit | binary sensor `<device> hot` (on from the maximum temperature until it has cooled by the hysteresis) |
| What is it doing? | always | sensor `<device> mode`: idle, solar surplus, off-peak top-up, sanitary minimum, hot, sensor fault, disabled (and "limited by the subscription") |

Notes:

- Without the option, the sanitary minimum stays automatic: a cold tank is heated whenever it is too cold. The forced-run
  switch changes nothing for such a device.
- The extra windows combine with the tariff signal exactly like the others: if you also give an off-peak entity (the Linky
  period), it must say off-peak too. The usual setup is the Linky as the signal, the night as the window and the midday
  hours as the extra window.
- *Surplus only* still forbids everything fed from the grid, a forced run included.
- Both options need these switches, which only exist in the Home Assistant integration: the standalone Docker runtime
  refuses them in its configuration instead of silently never acting.
- "Hot" is true from the first maximum reached (the off-peak one included); `mode` says which rule is driving the device.

## Several heaters, heat pumps, batteries

Nothing limits the number of devices; each has its own priority and settings. Temperature settings apply to on/off and
adjustable devices. Batteries keep their state-of-charge limits, chargers their plug and SoC rules.

## What is not verified

Everything above is tested with simulated sensors and devices (engine, Home Assistant, a Python MQTT broker). Not run on a
real heater, router or house. The "usual" values are the ones commonly used for a domestic water heater: they are starting
points, not a guarantee for your installation.
