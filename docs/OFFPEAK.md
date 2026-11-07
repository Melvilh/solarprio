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
- The device **needs a measured power** (a sensor in Home Assistant, a `readings.measured_topic` in the Docker runtime).
  Without it solarprio could not tell when the device is finished, so it never forces the device (and refuses the
  settings in the form / the TOML file).

## Home Assistant

*Configure* > add or edit a device (on/off, adjustable or EV charger; not a battery):

| Field | Example |
|---|---|
| Off-peak windows | `22:30-06:30, 12:30-14:30` (local time, a window may cross midnight) |
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
- Contract-specific rules (off-peak hours that change with the season, "jours Tempo") are not handled: set the windows
  yourself.
