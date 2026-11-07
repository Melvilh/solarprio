"""Off-peak told by an entity (the Linky's tariff period, a binary sensor...) instead of windows, in Home Assistant."""
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import async_mock_service

from .test_integration import GRID, _add_device, coordinator, dev, setup
from .test_offpeak import LOADS, Sim

TARIFF = "sensor.linky_periode_tarifaire"
ECS = dev(id="ecs", name="Water heater", entity_id="switch.ecs", priority=1, power_w=2000, measured_entity="sensor.ecs_power",
          offpeak_entity=TARIFF, done_below_w=0, done_after_s=120)
RADIATOR = dev(id="rad", name="Radiator", entity_id="switch.rad", priority=2, power_w=1500, measured_entity="sensor.rad_power",
               offpeak_entity=TARIFF, done_below_w=0, done_after_s=120)
W = {"unit_of_measurement": "W"}


async def start(hass, devices, hot=(), tariff="HP.."):
    sim = Sim(hass, datetime(2026, 11, 10, 12, 0), LOADS, hot=hot)  # midday: windows would say nothing
    hass.states.async_set(TARIFF, tariff)
    return sim


async def test_the_linky_tariff_period_drives_the_top_up(hass: HomeAssistant):
    sim = await start(hass, [ECS])
    p1, p2 = sim.patches()
    with p1, p2:
        coord = coordinator(hass, await setup(hass, devices=[ECS]))
        await sim.advance(coord, 120)
        assert not sim.on["ecs"]  # peak hours (HP..)
        assert coord.snapshot()["devices"][0]["offpeak"] == "waiting"
        hass.states.async_set(TARIFF, "HC..")
        await sim.advance(coord, 60)
        assert sim.on["ecs"] and coord.snapshot()["devices"][0]["offpeak"] == "heating"
        hass.states.async_set(TARIFF, "HP..")
        await sim.advance(coord, 60)
        assert not sim.on["ecs"]


async def test_a_hot_heater_hands_over_and_is_tried_again_in_the_next_period(hass: HomeAssistant):
    sim = await start(hass, [ECS, RADIATOR], hot={"ecs"}, tariff="HC..")
    p1, p2 = sim.patches()
    with p1, p2:
        coord = coordinator(hass, await setup(hass, devices=[ECS, RADIATOR]))
        await sim.advance(coord, 300)
        assert sim.on == {"ecs": False, "rad": True}
        assert [d["offpeak"] for d in coord.snapshot()["devices"]] == ["done", "heating"]
        hass.states.async_set(TARIFF, "HP..")
        await sim.advance(coord, 60)
        sim.hot.clear()
        hass.states.async_set(TARIFF, "HC..")  # next night
        await sim.advance(coord, 60)
        assert sim.on["ecs"] is True


async def test_custom_values_for_a_numeric_tariff_index(hass: HomeAssistant):
    ecs = dev(**{**ECS, "offpeak_values": "2"})
    sim = await start(hass, [ecs], tariff="1")
    p1, p2 = sim.patches()
    with p1, p2:
        coord = coordinator(hass, await setup(hass, devices=[ecs]))
        await sim.advance(coord, 60)
        assert not sim.on["ecs"]
        hass.states.async_set(TARIFF, "2")
        await sim.advance(coord, 60)
        assert sim.on["ecs"]
        hass.states.async_set(TARIFF, "on")  # not in the user's list: not off-peak
        await sim.advance(coord, 60)
        assert not sim.on["ecs"]


async def test_an_unavailable_signal_never_starts_the_heater(hass: HomeAssistant):
    sim = await start(hass, [ECS], tariff="unavailable")
    p1, p2 = sim.patches()
    with p1, p2:
        coord = coordinator(hass, await setup(hass, devices=[ECS]))
        await sim.advance(coord, 120)
        assert not sim.on["ecs"]
        hass.states.async_remove(TARIFF)  # entity gone altogether
        await sim.advance(coord, 60)
        assert not sim.on["ecs"]


async def test_a_lost_grid_measurement_still_switches_off_during_off_peak(hass: HomeAssistant):
    sim = await start(hass, [ECS], tariff="HC..")
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


async def test_form_takes_a_signal_entity_but_not_together_with_windows(hass: HomeAssistant):
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, "0", W)
    entry = await setup(hass, devices=[])
    form = {"name": "Water heater", "entity_id": "switch.heater", "priority": 1, "power_w": 2000, "min_on_s": 0, "min_off_s": 0,
            "start_margin_w": 0, "stay_tolerance_w": 0}

    bad = await _add_device(hass, entry, "on_off", {**form, "offpeak_entity": TARIFF})  # no measured power sensor
    assert bad["type"] is FlowResultType.FORM and bad["errors"] == {"base": "invalid_device"}
    bad = await hass.config_entries.options.async_configure(
        bad["flow_id"], {**form, "offpeak_entity": TARIFF, "offpeak": "22:30-06:30", "measured_entity": "sensor.ecs_power"})
    assert bad["errors"] == {"base": "invalid_device"}  # windows AND signal

    good = await hass.config_entries.options.async_configure(
        bad["flow_id"], {**form, "offpeak_entity": TARIFF, "offpeak_values": "HC.., 2", "measured_entity": "sensor.ecs_power"})
    assert good["type"] is FlowResultType.CREATE_ENTRY
    saved = entry.options["devices"][0]
    assert saved["offpeak_entity"] == TARIFF and saved["offpeak_values"] == "HC.., 2"
    await hass.async_block_till_done()
    assert coordinator(hass, entry).engine.device("water_heater").offpeak_signal is True
