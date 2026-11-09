# Off-peak top-up ("chauffe en heures creuses")

A device can be fed **from the grid during your off-peak hours** when the sun did not finish the job, and left alone
once it is done. "Done" is detected from its **consumption**: a water heater whose thermostat opened (the tank is hot)
stops drawing power, so it is finished and the next device in priority order takes its turn.

## How it behaves

- In an off-peak window, the first device (by priority) that is not finished is fed at its **full power**, whatever
  the sun does. Its power is taken out of what the other devices may share.
- **One device at a time** by default: the others wait, so you do not exceed your subscribed power. When the first is
  found finished, the next one starts in that same control cycle. To top up several devices together (a company site
  with several chargers or water heaters), set the off-peak power budget, see [MANY_DEVICES.md](MANY_DEVICES.md).
- A device is found finished when it has been on for `done_after_s` (default 120 s, so a slow sensor or the start-up
  of a load is not mistaken for "hot") and its measured power is at or below `done_below_w` (default 5 % of its power).
- Finished means finished **for the daily period**: it is not tried again until `reset_at` (default: the end of the
  first window, so once a day). A hot tank therefore costs one short pulse of about two minutes per day.
- Outside the windows, or once finished, the device is an ordinary surplus device again (the sun can heat it).
- A device of the **computing task** category is the exception: it needs no measured power and is never "finished"
  ([TASKS.md](TASKS.md)).
- The device **needs a measured power** (a sensor in Home Assistant, a `readings.measured_topic` in the Docker runtime).
  Without it solarprio could not tell when the device is finished, so it never forces the device (and refuses the
  settings in the form / the TOML file).

## Off-peak from an entity (like the Linky's tariff period)

Instead of typing hours you can point a device at an **entity that tells when it is off-peak**: the tariff period
of your Linky (a sensor), a binary sensor, a boolean, a select. This follows your real contract, including hours that
change, with no hours to maintain.

- The top-up runs **while the entity says off-peak**. Each new off-peak period (the entity going from peak to off-peak)
  tries the device again, so a contract with two off-peak slots a day tries it at each slot. This differs from windows,
  where a device found finished is left alone until the next day.
- **Which states mean off-peak?** By default: `on`, `true`, `1`, `yes`, `HC`, `HC..`, `off_peak`, `low`, and any text
  containing "creuse" (for example `HEURES CREUSES`), whatever the case. These defaults are what such sensors usually
  report, **not verified on a real Linky**: look at the real state of your entity in *Developer tools > States* and, if
  it differs, list the off-peak states yourself (for example `HC..` or a tariff index like `2`). When you list values,
  only those count.
- **Unknown or unavailable never starts anything**, and a sensor that flaps to unavailable and back does not count as
  a new period.
- Use it **instead of** windows, or **together with** them: when both are filled, both must say off-peak (for example the
  tariff signal, but only during the night hours). With a **temperature sensor** on the device (see
  [REGULATION.md](REGULATION.md)) no measured power is needed: the top-up ends when the tank reaches its off-peak maximum.
- The states meaning off-peak accept a trailing star: `HC*` matches `HC`, `HC..` and `HCHP`. Choose the **tariff period**
  (a text such as `HC..` / `HP..`), never an energy index (a number that only grows): the panel warns when the entity you pick
  reports a number.

## Off-peak hours for the whole site (Home Assistant)

Your off-peak hours are the same for every device, so they are set **once**, in the panel's *Settings*:

- *Off-peak signal*: the entity that tells the tariff (your Linky tariff period, `HC..` / `HP..`), and *States that mean off-peak*
  (for example `HC*`).
- *Off-peak windows*: for example `22:30-06:30` (your own night hours).
- *Extra off-peak windows*: for example the midday hours `12:30-14:30`. They count only for the devices whose
  `extra off-peak windows` switch is on, so each device chooses.

Then each device **chooses**, with its own switch **"off-peak hours"** (created for every device except batteries), between:

- **router + off-peak hours** (switch on): the surplus first, and the off-peak hours of the Settings in addition;
- **router only** (switch off): only the surplus, which is what you want for a load that should never run from the grid.

The panel shows which one each device is in. The switch starts **off** (the router only) and keeps its state across restarts, so
nothing is fed from the grid until you ask. The hours themselves are only in the Settings: a device form has no off-peak
settings. When both a signal and windows are given, BOTH must say off-peak; with the signal alone, every off-peak period of the
tariff counts (night and midday). **The windows are optional**: they are only needed to tell the night from the midday, so that
each device can choose the midday with its `extra off-peak windows` switch. A device configured by an older version with off-peak
hours of its own keeps using them (its switch starts on). The *Off-peak power budget* (also in the Settings) says how much power may be fed at once.

Whatever feeds a device from the grid on purpose stays under your **subscription limit** (see [REGULATION.md](REGULATION.md)): set
it, for example 5700 VA on a 6 kVA meter, with the house power sensor. The panel warns when a device can be fed from the grid
and no limit is set.

## Forced run of a car or a battery

Every EV charger and every battery gets a switch `<device> forced run` (off by default, restored after a restart). When it is
on, the device is charged **from the grid now**, at the most the subscription limit leaves free, up to its state-of-charge
limit, and stops when the car is unplugged. It does not wait for the surplus nor for the off-peak hours. Three safeties:

- it **needs a subscription limit**: without one the forced run is refused and the `mode` sensor says so;
- a state-of-charge limit that cannot be checked (no SoC sensor) blocks it;
- *Surplus only* forbids it.

For a water heater the "forced run" switch is the sanitary one (*Sanitary minimum only on a forced run*), as before.

## Home Assistant (a device with its own hours)

*Configure* > add or edit a device (on/off, adjustable or EV charger; not a battery):

| Field | Example |
|---|---|
| Off-peak windows | `22:30-06:30, 12:30-14:30` (local time, a window may cross midnight) |
| or Off-peak signal entity | `sensor.linky_periode_tarifaire` (and, if needed, *States meaning off-peak*: `HC..`) |
| Measured power sensor | `sensor.chauffe_eau_puissance_chauffe_eau` |
| Finished when consumption falls to | `0` = automatic (5 % of the power) |
| Check for finished only after it has run for | `120` s |
| Top up again from (optional) | `07:00` |

The windows above are only an example: use the hours of your own contract. The panel shows
*off-peak: waiting / heating / finished* on the device row.

## Docker runtime (TOML)

```toml
[[device]]
id = "water_heater"
name = "Water heater"
priority = 1
kind = "proportional"
power_w = 2400
offpeak = ["22:30-06:30"]       # your contract's hours
# reset_at = "07:00"            # default: end of the first window
# Instead of `offpeak`, follow a tariff topic (add offpeak_topic below, keep measured_topic):
#   [device.readings]  offpeak_topic = "linky/tariff"   offpeak_values = ["HC.."]   # values optional
# done_below_w = 100            # default: 5 % of power_w
# done_after_s = 120
  [device.actuator]
  type = "mqtt"
  topic = "heater/set_watts"
  scale = "watts"
  [device.readings]
  measured_topic = "heater/power"      # required with offpeak
```

The container uses its own clock: set `TZ` (for example `TZ=Europe/Paris`), otherwise the windows are read in the container default time zone (usually UTC).

## With the ESPHome router of [ESPHOME_ROUTER.md](ESPHOME_ROUTER.md)

Use `sensor.chauffe_eau_puissance_chauffe_eau` as the measured power. In the ESPHome file it is computed from the
current actually measured on the heater (`P = R·I²`) and is 0 when the triac is not commanded, so it falls to 0 when
the thermostat opens. It is only as reliable as that current sensor: check what it reads on a hot tank before trusting
the "finished" detection.

## Limits and what is not verified

- Tested with simulated clocks and simulated loads only (engine, Home Assistant 2026.2.3, MQTT runtime). Not run on a
  real heater, thermostat, or contract; the behaviour of a given thermostat and sensor is untested.
- If the measurement of the grid is lost, the safety rule wins: the device is switched **off**, even inside a window
  (the top-up itself does not need the grid measurement, but the rule is kept simple and safe). With `on_stale = "hold"`
  the current state is held.
- The "finished" memory is not saved: after a restart during the night the device is tried again and found finished
  again after about two minutes.
- A device that never draws more than the threshold (a very small load, or a faulty sensor) is considered finished.
- Energy objectives (a kWh target per day) are **not** implemented: only the "stops consuming" criterion.
- Windows are fixed hours; for hours that change (seasons, tariff days) use the off-peak signal entity or topic.
