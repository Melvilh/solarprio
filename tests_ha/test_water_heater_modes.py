"""Water heater controls in Home Assistant: a forced-run switch, extra off-peak windows chosen by a switch, a "hot" sensor
and a mode sensor, all driven by the engine."""
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.solarprio.const import DOMAIN

from .test_integration import coordinator, setup
from .test_panel import ws
from .test_regulation import DATA, HEATER, TEMP, World, started

AFTERNOON = datetime(2026, 11, 10, 17, 0)
MIDDAY = datetime(2026, 11, 10, 13, 0)


def entity(hass, domain, suffix):
    registry = er.async_get(hass)
    found = [e.entity_id for e in registry.entities.values() if e.platform == DOMAIN and e.domain == domain and e.unique_id.endswith(suffix)]
    assert len(found) == 1, (domain, suffix, found)
    return found[0]


async def test_the_sanitary_minimum_waits_for_the_forced_run_switch(hass: HomeAssistant):
    heater = {**HEATER, "sanitary_forced_only": True, "temp_max_solar": 65, "temp_min": 40}
    world = World(hass, devices=[heater], temp="30", local=AFTERNOON)
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        assert coord.snapshot()["devices"][0]["cmd_w"] == 0 and coord.snapshot()["devices"][0]["mode"] != "sanitary"
        switch = entity(hass, "switch", "forced_run_ecs")
        assert hass.states.get(switch).state == "off"  # nothing is fed from the grid until the user asks
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
        await world.tick(coord)
        assert hass.states.get(switch).state == "on"
        assert coord.snapshot()["devices"][0]["mode"] == "sanitary" and coord.snapshot()["devices"][0]["forced_run"]
        await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
        await world.tick(coord, 400)
        assert coord.snapshot()["devices"][0]["cmd_w"] == 0


async def test_a_device_without_the_options_gets_no_extra_switch(hass: HomeAssistant):
    world = World(hass, local=AFTERNOON)
    p1, p2 = world.patches()
    with p1, p2:
        await started(world)
        registry = er.async_get(hass)
        assert not [e for e in registry.entities.values() if e.platform == DOMAIN and ("forced_run" in e.unique_id or "extra_windows" in e.unique_id)]


async def test_the_midday_switch_chooses_whether_the_midday_off_peak_hours_heat(hass: HomeAssistant):
    heater = {**HEATER, "temp_min": None, "offpeak": "22:30-06:30", "offpeak_extra": "12:30-14:30"}
    world = World(hass, devices=[heater], temp="50", local=MIDDAY)
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        switch = entity(hass, "switch", "extra_windows_ecs")
        assert hass.states.get(switch).state == "off" and coord.snapshot()["devices"][0]["cmd_w"] == 0
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
        await world.tick(coord)
        assert coord.snapshot()["devices"][0]["mode"] == "offpeak" and coord.snapshot()["devices"][0]["cmd_w"] == 2400


async def test_the_hot_sensor_and_the_mode_sensor_follow_the_tank(hass: HomeAssistant):
    world = World(hass, grid="1500", local=AFTERNOON)
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        hot, mode = entity(hass, "binary_sensor", "hot_ecs"), entity(hass, "sensor", "mode_ecs")
        assert hass.states.get(hot).state == "off" and hass.states.get(mode).state == "solar"
        hass.states.async_set(TEMP, "66", {"unit_of_measurement": "°C"})
        await world.tick(coord)
        assert hass.states.get(hot).state == "on" and hass.states.get(hot).attributes["device_class"] == "heat"
        assert hass.states.get(mode).state == "hot"


async def test_the_form_offers_the_new_options_and_the_panel_saves_them(hass: HomeAssistant, hass_ws_client):
    world = World(hass, devices=[], local=AFTERNOON)
    p1, p2 = world.patches()
    with p1, p2:
        await setup(hass, data=DATA, devices=[])
        client = await hass_ws_client(hass)
        form = (await ws(client, type="solarprio/device_form", kind="on_off", language="fr"))["result"]
        names = {f["name"]: f for f in form["fields"]}
        assert "offpeak_extra" in names and "sanitary_forced_only" in names
        assert names["sanitary_forced_only"]["label"] != "sanitary_forced_only"  # translated
        saved = await ws(client, type="solarprio/device_save", kind="on_off", values={
            "name": "ECS", "entity_id": "switch.ecs", "priority": 1, "power_w": 2400, "temp_entity": TEMP, "temp_max_solar": 65,
            "temp_min": 40, "sanitary_forced_only": True, "offpeak": "22:30-06:30", "offpeak_extra": "12:30-14:30",
            "measured_entity": "sensor.chauffe_eau_puissance"})
        assert saved["success"], saved
        await hass.async_block_till_done()
        coord = coordinator(hass, hass.config_entries.async_entries(DOMAIN)[0])
        device = coord.engine.device("ecs")
        assert device.sanitary_forced_only and len(device.windows_extra) == 1
