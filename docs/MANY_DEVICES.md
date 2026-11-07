# Many devices (company sites) and the Energy dashboard

## Several devices started together

The allocation is a walk down the priority list: every device takes what it needs from the surplus that is left, so
**several devices start in the same control cycle** when the surplus is large enough (for example four 7 kW charging
points on 30 kW of sun, the next water heaters starting as soon as the sun allows). Nothing limits the number of devices.

- A charging point switched by a **contactor** is an *on/off* device with the charger's maximum power: the car decides
  the real current. Give it a **measured power** sensor: when the car draws less than the command (after `settle_s`,
  30 s by default) the difference goes to the next device.
- Water heaters, heat pumps, pumps: *on/off* or *adjustable* devices, each with its own priority. Computing workloads use the
  *computing task* category instead, which only sends a go signal ([TASKS.md](TASKS.md)).
- For the **off-peak top-up** the default is one device at a time (safe for a small subscription). Set the
  **off-peak power budget** (Home Assistant: the setup form; Docker: `[runtime] offpeak_budget_w`) to the power you may
  draw from the grid at night: devices are then topped up in priority order as long as they fit, a finished device frees
  its share at once, and a device that does not fit waits while a smaller one further down may still start. The first
  device always starts, even if it is larger than the budget.

Not done: staggering the starts (a delay between two contactors closing), grouping devices behind one breaker, and
phase balancing. If you need them, say so.

## Pre-filling from the Energy dashboard (Home Assistant)

When you set solarprio up it reads the Energy dashboard (it never writes to it):

- **Grid power sensor** → pre-fills "Grid power sensor" and sets *My meter reports import as positive*, because the
  dashboard counts power drawn from the grid as positive. Only when the dashboard has **exactly one** grid power sensor.
- **Solar power sensor** → pre-fills "Production sensor" in production mode. The dashboard has no whole-house
  consumption, so that sensor is still yours to choose.
- **Devices** → *Configure* > **Import devices from the Energy dashboard** lists the dashboard devices that have a power
  sensor and are not yet used: you pick several, choose their type, and for each one only the entity to control and the
  power remain to be filled; the name and the measured power sensor come from the dashboard.
- *Configure* > **Copy a device** opens a new device with the same power, timers and off-peak settings; you only choose
  its name and entities (entities are never copied).

What it cannot do: the dashboard mostly holds **energy counters** (kWh). Only the optional *power* sensors (`stat_rate`)
are usable, and only if they exist as entities right now. If your dashboard has just counters, nothing is suggested and
you pick the sensors as before. Several grid power sensors (one per phase, for example) are not guessed: which one, or
their sum, is your choice (create a template sensor for the sum).

## What is not verified

- Tested with Home Assistant 2026.2.3 (its real Energy manager, simulated sensors) and a Python MQTT broker. The
  dashboard's data model has changed between versions (power sensors appeared recently): on another version the
  suggestions may be empty.
- Not run on real charging points, contactors or a real site.
