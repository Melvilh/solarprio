"""The mode the user chooses for a device (off, router only, router + off-peak hours, forced run): one choice that flips what
already exists, so the selector, the switches and the panel always agree."""
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.solarprio.const import DOMAIN

from .test_battery_ev import EV
from .test_integration import GRID, coordinator, setup
from .test_panel import ws
from .test_regulation import DATA, HEATER, HOUSE, POWER, SITE, World, started
from .test_site_offpeak import PERIOD, SITE_OFFPEAK, entity

NIGHT = datetime(2026, 11, 10, 23, 0)


def heater(**kw):
    return {**HEATER, "temp_min": 40, "sanitary_forced_only": True, "measured_entity": POWER, **kw}


async def test_the_choices_offered_depend_on_what_the_device_can_do(hass: HomeAssistant):
    world = World(hass, data=SITE_OFFPEAK, devices=[heater()], temp="50", local=NIGHT)
    hass.states.async_set(PERIOD, "HC..")
    hass.states.async_set(HOUSE, "1000", {"unit_of_measurement": "W"})
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        assert coord.available_modes("ecs") == ["off", "router", "router_offpeak", "forced"]
        assert coord.current_mode("ecs") == "router"  # the default: the router only
    plain = World(hass, data=DATA, devices=[{**HEATER, "temp_min": None}], local=NIGHT)  # no off-peak hours, no forced run
    p1, p2 = plain.patches()
    with p1, p2:
        entry = await setup(hass, data=DATA, devices=[{**HEATER, "temp_min": None}])
        assert coordinator(hass, entry).available_modes("ecs") == ["off", "router"]


async def test_choosing_a_mode_flips_the_switches_and_the_selector_follows_them(hass: HomeAssistant):
    world = World(hass, data=SITE_OFFPEAK, devices=[heater()], temp="50", local=NIGHT)
    hass.states.async_set(PERIOD, "HC..")
    hass.states.async_set(HOUSE, "1000", {"unit_of_measurement": "W"})
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        select = entity(hass, "select", "modechoice_ecs")
        offpeak_sw, forced_sw = entity(hass, "switch", "offpeak_ecs"), entity(hass, "switch", "forced_run_ecs")
        assert hass.states.get(select).state == "router"
        await hass.services.async_call("select", "select_option", {"entity_id": select, "option": "router_offpeak"}, blocking=True)
        assert hass.states.get(offpeak_sw).state == "on" and hass.states.get(select).state == "router_offpeak"
        await world.tick(coord)
        assert coord.snapshot()["devices"][0]["mode"] == "offpeak"  # night, off-peak, chosen: fed from the grid
        await hass.services.async_call("select", "select_option", {"entity_id": select, "option": "forced"}, blocking=True)
        assert hass.states.get(forced_sw).state == "on" and hass.states.get(select).state == "forced"
        # flipping a switch by hand moves the selector too
        await hass.services.async_call("switch", "turn_off", {"entity_id": forced_sw}, blocking=True)
        assert hass.states.get(select).state == "router_offpeak"
        await hass.services.async_call("select", "select_option", {"entity_id": select, "option": "router"}, blocking=True)
        assert hass.states.get(offpeak_sw).state == "off" and hass.states.get(forced_sw).state == "off"
        await world.tick(coord)
        assert coord.snapshot()["devices"][0]["mode"] != "offpeak"


async def test_off_stops_the_device_and_survives_the_options_update_and_a_mode_brings_it_back(hass: HomeAssistant):
    world = World(hass, data=SITE_OFFPEAK, devices=[heater()], temp="50", local=NIGHT)
    hass.states.async_set(PERIOD, "HC..")
    hass.states.async_set(HOUSE, "1000", {"unit_of_measurement": "W"})
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        select = entity(hass, "select", "modechoice_ecs")
        await hass.services.async_call("select", "select_option", {"entity_id": select, "option": "router_offpeak"}, blocking=True)
        await hass.services.async_call("select", "select_option", {"entity_id": select, "option": "off"}, blocking=True)
        await hass.async_block_till_done()
        assert hass.states.get(select).state == "off" and coord.snapshot()["devices"][0]["enabled"] is False
        assert hass.config_entries.async_entries(DOMAIN)[0].options["devices"][0]["enabled"] is False  # saved, not only live
        await world.tick(coord)
        assert coord.snapshot()["devices"][0]["cmd_w"] == 0 and coord.snapshot()["devices"][0]["mode"] == "disabled"
        await hass.services.async_call("select", "select_option", {"entity_id": select, "option": "router"}, blocking=True)
        await hass.async_block_till_done()
        assert hass.states.get(select).state == "router" and coord.snapshot()["devices"][0]["enabled"] is True


async def test_the_panel_sets_the_mode_and_refuses_one_the_device_does_not_offer(hass: HomeAssistant, hass_ws_client):
    world = World(hass, data=DATA, devices=[{**HEATER, "temp_min": None}], local=NIGHT)  # nothing but off and router
    p1, p2 = world.patches()
    with p1, p2:
        await started(world)
        client = await hass_ws_client(hass)
        snap = (await ws(client, type="solarprio/state"))["result"]["devices"][0]
        assert snap["mode_choices"] == ["off", "router"] and snap["mode_choice"] == "router"
        ok = await ws(client, type="solarprio/set_device_mode", device_id="ecs", mode="off")
        assert ok["success"] and ok["result"]["devices"][0]["mode_choice"] == "off"
        refused = await ws(client, type="solarprio/set_device_mode", device_id="ecs", mode="forced")
        assert not refused["success"] and refused["error"]["code"] == "no_such_mode"
        missing = await ws(client, type="solarprio/set_device_mode", device_id="nope", mode="router")
        assert not missing["success"] and missing["error"]["code"] == "unknown_device"


async def test_the_forced_mode_of_a_car_still_needs_a_subscription_limit(hass: HomeAssistant):
    async_mock_service(hass, "number", "set_value")
    async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, "0", {"unit_of_measurement": "W"})
    hass.states.async_set("binary_sensor.car_plugged", "on")
    hass.states.async_set("sensor.car_soc", "40")
    entry = await setup(hass, data=DATA, devices=[{**EV, "min_on_s": 0, "min_off_s": 0}])  # no subscription limit
    coord = coordinator(hass, entry)
    await hass.services.async_call("select", "select_option", {"entity_id": entity(hass, "select", "modechoice_ev"), "option": "forced"},
                                   blocking=True)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity(hass, "sensor", "mode_ev")).state == "no_cap"  # the safety still holds behind the choice
