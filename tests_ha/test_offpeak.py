"""Off-peak top-up in Home Assistant: behaviour with a simulated clock and loads, and the device form."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from .test_integration import DATA, GRID, _add_device, coordinator, dev, setup

W = {"unit_of_measurement": "W"}
ECS = dev(id="ecs", name="Water heater", entity_id="switch.ecs", priority=1, power_w=2000, measured_entity="sensor.ecs_power",
          offpeak="22:30-06:30", done_below_w=0, done_after_s=120)
RADIATOR = dev(id="rad", name="Radiator", entity_id="switch.rad", priority=2, power_w=1500, measured_entity="sensor.rad_power",
               offpeak="22:30-06:30", done_below_w=0, done_after_s=120)


class Sim:
    """Wall clock + monotonic clock moving together, and loads that draw their rated power when on (unless hot)."""

    def __init__(self, hass, start, loads, hot=()):
        self.hass, self.local, self.mono, self.hot = hass, start, 1000.0, set(hot)
        self.loads = loads  # id -> (switch entity, power sensor, rated W)
        self.on = {i: False for i in loads}
        hass.states.async_set(GRID, "0", W)
        for _, sensor, _ in loads.values():
            hass.states.async_set(sensor, "0", W)
        for service, value in (("turn_on", True), ("turn_off", False)):
            async def handler(call, value=value):
                for i, (entity, _, _) in self.loads.items():
                    if entity == call.data["entity_id"]:
                        self.on[i] = value
            hass.services.async_register("homeassistant", service, handler)

    def patches(self):
        return (patch("custom_components.solarprio.coordinator.time", SimpleNamespace(monotonic=lambda: self.mono)),
                patch.object(dt_util, "now", lambda *a, **k: self.local))

    def draw(self, i):
        return 0 if (i in self.hot or not self.on[i]) else self.loads[i][2]

    async def advance(self, coord, seconds, step=10):
        for _ in range(int(seconds / step)):
            self.local += timedelta(seconds=step)
            self.mono += step
            for i, (_, sensor, _) in self.loads.items():
                self.hass.states.async_set(sensor, str(self.draw(i)), W)
            self.hass.states.async_set(GRID, str(-sum(self.draw(i) for i in self.loads)), W)  # night: all from the grid
            await coord.async_refresh()
            await self.hass.async_block_till_done()


LOADS = {"ecs": ("switch.ecs", "sensor.ecs_power", 2000), "rad": ("switch.rad", "sensor.rad_power", 1500)}


async def test_a_cold_heater_is_fed_and_the_next_device_waits(hass: HomeAssistant):
    sim = Sim(hass, datetime(2026, 11, 10, 22, 0), LOADS)
    p1, p2 = sim.patches()
    with p1, p2:
        coord = coordinator(hass, await setup(hass, devices=[ECS, RADIATOR]))
        await sim.advance(coord, 20 * 60)
        assert not sim.on["ecs"]  # before the window
        await sim.advance(coord, 20 * 60)
        assert sim.on == {"ecs": True, "rad": False}
        assert [d["offpeak"] for d in coord.snapshot()["devices"]] == ["heating", "waiting"]


async def test_a_hot_heater_is_dropped_and_the_next_device_takes_over(hass: HomeAssistant):
    sim = Sim(hass, datetime(2026, 11, 10, 22, 29), LOADS, hot={"ecs"})
    p1, p2 = sim.patches()
    with p1, p2:
        coord = coordinator(hass, await setup(hass, devices=[ECS, RADIATOR]))
        await sim.advance(coord, 5 * 60)
        assert sim.on == {"ecs": False, "rad": True}
        assert [d["offpeak"] for d in coord.snapshot()["devices"]] == ["done", "heating"]
        await sim.advance(coord, 2 * 3600)
        assert sim.on["ecs"] is False  # it is not tried again tonight


async def test_a_lost_measurement_switches_off_even_in_the_window(hass: HomeAssistant):
    """Documented: the safety rule for a lost measurement wins over the top-up."""
    sim = Sim(hass, datetime(2026, 11, 10, 23, 0), LOADS)
    p1, p2 = sim.patches()
    with p1, p2:
        coord = coordinator(hass, await setup(hass, devices=[ECS]))
        await sim.advance(coord, 60)
        assert sim.on["ecs"]
        hass.states.async_set(GRID, "unavailable")
        sim.local += timedelta(seconds=10)
        sim.mono += 10
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert not sim.on["ecs"]


async def test_a_missing_power_sensor_means_no_top_up(hass: HomeAssistant):
    sim = Sim(hass, datetime(2026, 11, 10, 23, 0), LOADS)
    p1, p2 = sim.patches()
    with p1, p2:
        coord = coordinator(hass, await setup(hass, devices=[ECS]))
        await sim.advance(coord, 60)
        assert sim.on["ecs"]  # topped up while its power can be read
        hass.states.async_set("sensor.ecs_power", "unavailable")  # the grid still shows its 2000 W import
        sim.local += timedelta(seconds=10)
        sim.mono += 10
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert not sim.on["ecs"]


async def test_a_device_added_with_the_form_has_no_hours_of_its_own_and_gets_the_site_windows(hass: HomeAssistant):
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, "0", W)
    site = {**DATA, "offpeak": "22:30-06:30, 12:30-14:30"}  # the hours are set once, for the whole site
    entry = await setup(hass, data=site, devices=[])
    form = {"name": "Water heater", "entity_id": "switch.heater", "priority": 1, "power_w": 2000, "min_on_s": 0, "min_off_s": 0,
            "start_margin_w": 0, "stay_tolerance_w": 0, "measured_entity": "sensor.ecs_power", "reset_at": "07:00",
            "done_below_w": 40}
    result = await _add_device(hass, entry, "on_off", form)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    saved = entry.options["devices"][0]
    assert not {"offpeak", "offpeak_entity", "offpeak_values", "offpeak_extra"} & set(saved)  # nothing of its own
    assert saved["reset_at"] == "07:00" and saved["done_after_s"] == 120
    await hass.async_block_till_done()
    engine_dev = coordinator(hass, entry).engine.device("water_heater")
    assert engine_dev.windows == ((1350, 390), (750, 870)) and engine_dev.reset_minute == 420 and engine_dev.done_threshold_w == 40


async def test_forms_offer_the_schedule_except_for_a_battery(hass: HomeAssistant):
    from custom_components.solarprio.config_flow import _details_schema

    fields = {"reset_at", "done_below_w", "done_after_s"}
    assert not fields & {str(k) for k in _details_schema("battery", {}, 1).schema}
    for kind in ("on_off", "proportional", "ev_charger"):
        keys = {str(k) for k in _details_schema(kind, {}, 1).schema}
        assert fields <= keys and "measured_entity" in keys
        # the off-peak hours themselves are only in the Settings of the site
        assert not {"offpeak", "offpeak_entity", "offpeak_values", "offpeak_extra", "offpeak_site"} & keys
