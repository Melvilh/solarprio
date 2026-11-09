"""Off-peak hours set once for the whole site, followed by the devices that choose to, and the forced run of a car."""
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.solarprio.const import DOMAIN
from custom_components.solarprio.coordinator import uses_site_hours, with_site_offpeak
from custom_components.solarprio.forms import clean_site

from .test_battery_ev import EV
from .test_integration import GRID, coordinator, dev, setup
from .test_panel import ws
from .test_regulation import DATA, HEATER, HOUSE, POWER, SETPOINT, SITE, TEMP, World, started

PERIOD = "sensor.linky_periode"
NIGHT = datetime(2026, 11, 10, 23, 0)
MIDDAY = datetime(2026, 11, 10, 13, 0)
SITE_OFFPEAK = {**SITE, "offpeak_entity": PERIOD, "offpeak_values": "HC*", "offpeak": "22:30-06:30", "offpeak_extra": "12:30-14:30"}


def entity(hass, domain, suffix):
    registry = er.async_get(hass)
    found = [e.entity_id for e in registry.entities.values() if e.platform == DOMAIN and e.domain == domain and e.unique_id.endswith(suffix)]
    assert len(found) == 1, (domain, suffix, found)
    return found[0]


def test_a_device_uses_the_site_hours_unless_it_has_older_hours_of_its_own_and_batteries_have_none():
    site = {"offpeak_entity": PERIOD, "offpeak_values": "HC*", "offpeak": "22:30-06:30", "offpeak_extra": "12:30-14:30"}
    plain = {"id": "a", "kind": "on_off"}
    got = with_site_offpeak(plain, site)
    assert (got["offpeak_entity"], got["offpeak_values"], got["offpeak"], got["offpeak_extra"]) == (PERIOD, "HC*", "22:30-06:30", "12:30-14:30")
    assert uses_site_hours(plain, site) and not uses_site_hours({"id": "b", "kind": "battery"}, site)
    legacy = {"id": "a", "kind": "on_off", "offpeak": "01:00-05:00", "offpeak_entity": "sensor.old_index"}  # from an older version
    assert with_site_offpeak(legacy, site) == legacy and not uses_site_hours(legacy, site)  # it keeps what it had
    # an older "follow the site" choice meant "none of my own": the old index it still carries no longer wins
    followed = with_site_offpeak({**legacy, "offpeak_site": True}, site)
    assert followed["offpeak_entity"] == PERIOD and followed["offpeak"] == "22:30-06:30"
    # the site has no hours: nothing is added, the device has none
    assert with_site_offpeak(plain, {}) == plain and not uses_site_hours(plain, {})


def test_the_site_off_peak_settings_are_validated():
    base = {"mode": "export", "export_entity": GRID, "interval_s": 5, "stale_after_s": 0, "on_stale": "off", "margin_w": 0}
    ok = clean_site({**base, "offpeak_entity": PERIOD, "offpeak": "22:30-06:30, 12:30-14:30", "offpeak_values": "HC*"})
    assert ok["offpeak"] == "22:30-06:30, 12:30-14:30" and ok["offpeak_entity"] == PERIOD
    for bad in ("22h30-6h30", "25:00-26:00", "nonsense"):
        try:
            clean_site({**base, "offpeak": bad})
        except ValueError as err:
            assert str(err) == "offpeak"
        else:
            raise AssertionError(f"{bad!r} should be refused")
    assert "offpeak" not in clean_site({**base, "offpeak": "  "})


async def test_the_off_peak_switch_chooses_between_the_router_only_and_the_router_with_the_site_hours(hass: HomeAssistant):
    heater = {**HEATER, "temp_min": None, "measured_entity": POWER}  # nothing of its own: it can use the site's hours
    world = World(hass, data=SITE_OFFPEAK, devices=[heater], temp="50", local=NIGHT)
    hass.states.async_set(PERIOD, "HC..")
    hass.states.async_set(HOUSE, "1000", {"unit_of_measurement": "W"})
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        switch = entity(hass, "switch", "offpeak_ecs")
        assert hass.states.get(switch).state == "off"  # the default on the site's hours: the router only
        assert coord.snapshot()["devices"][0]["offpeak_mode"] == "router_only"
        assert coord.snapshot()["devices"][0]["cmd_w"] == 0  # night, off-peak, but not chosen: nothing is fed from the grid
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
        await world.tick(coord)
        assert coord.snapshot()["devices"][0]["offpeak_mode"] == "router_offpeak"
        assert coord.snapshot()["devices"][0]["mode"] == "offpeak" and coord.snapshot()["devices"][0]["cmd_w"] > 0
        await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
        await world.tick(coord)
        assert coord.snapshot()["devices"][0]["mode"] != "offpeak"


async def test_the_midday_switch_still_chooses_the_midday_hours_for_a_device_that_uses_the_site_hours(hass: HomeAssistant):
    heater = {**HEATER, "temp_min": None, "measured_entity": POWER}
    world = World(hass, data=SITE_OFFPEAK, devices=[heater], temp="50", local=MIDDAY)
    hass.states.async_set(PERIOD, "HC..")
    hass.states.async_set(HOUSE, "1000", {"unit_of_measurement": "W"})
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        await hass.services.async_call("switch", "turn_on", {"entity_id": entity(hass, "switch", "offpeak_ecs")}, blocking=True)
        extra = entity(hass, "switch", "extra_windows_ecs")  # created because the SITE has extra windows
        await world.tick(coord)
        assert coord.snapshot()["devices"][0]["cmd_w"] == 0  # midday, extra windows off
        await hass.services.async_call("switch", "turn_on", {"entity_id": extra}, blocking=True)
        await world.tick(coord)
        assert coord.snapshot()["devices"][0]["mode"] == "offpeak"
        hass.states.async_set(PERIOD, "HP..")  # the tariff says peak: never forced
        await world.tick(coord)
        assert coord.snapshot()["devices"][0]["mode"] != "offpeak"


async def test_a_device_with_older_hours_of_its_own_keeps_using_them_and_its_switch_starts_on(hass: HomeAssistant):
    heater = {**HEATER, "temp_min": None, "measured_entity": POWER, "offpeak": "22:30-06:30"}
    world = World(hass, data=DATA, devices=[heater], temp="50", local=NIGHT)  # the site has no off-peak hours at all
    hass.states.async_set(HOUSE, "1000", {"unit_of_measurement": "W"})
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        assert hass.states.get(entity(hass, "switch", "offpeak_ecs")).state == "on"
        assert coord.snapshot()["devices"][0]["offpeak_mode"] == "router_offpeak"


async def test_a_device_without_off_peak_hours_shows_neither_mode_and_has_no_switch(hass: HomeAssistant):
    world = World(hass, data=DATA, devices=[{**HEATER, "temp_min": None}], local=NIGHT)
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        assert coord.snapshot()["devices"][0]["offpeak_mode"] is None
        registry = er.async_get(hass)
        assert not [e for e in registry.entities.values() if e.platform == DOMAIN and "offpeak_" in e.unique_id]


async def test_the_forced_run_switch_of_a_car_charges_it_inside_the_subscription(hass: HomeAssistant):
    set_value = async_mock_service(hass, "number", "set_value")
    async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, "0", {"unit_of_measurement": "W"})
    hass.states.async_set(HOUSE, "1500", {"unit_of_measurement": "W"})
    hass.states.async_set("binary_sensor.car_plugged", "on")
    hass.states.async_set("sensor.car_soc", "40")
    ev = {**EV, "min_on_s": 0, "min_off_s": 0}
    entry = await setup(hass, data=SITE, devices=[ev])
    coord = coordinator(hass, entry)
    switch = entity(hass, "switch", "forced_run_ev")
    assert hass.states.get(switch).state == "off"
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert not set_value and coord.snapshot()["devices"][0]["cmd_w"] == 0  # no surplus and no forced run: nothing is sent
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert set_value[-1].data["value"] == 16.0  # 16 A: 3680 W fits in 5700 - 1500 W
    device = coord.snapshot()["devices"][0]
    assert device["mode"] == "forced" and device["forced_run"]
    hass.states.async_set("sensor.car_soc", "80")  # the limit: the forced run stops
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.snapshot()["devices"][0]["cmd_w"] == 0  # the charger is paused with its switch, the current is left as it was


async def test_a_forced_run_without_a_subscription_limit_is_refused_and_says_why(hass: HomeAssistant):
    async_mock_service(hass, "number", "set_value")
    async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, "0", {"unit_of_measurement": "W"})
    hass.states.async_set("binary_sensor.car_plugged", "on")
    hass.states.async_set("sensor.car_soc", "40")
    entry = await setup(hass, data=DATA, devices=[{**EV, "min_on_s": 0, "min_off_s": 0}])  # DATA has no subscription limit
    coord = coordinator(hass, entry)
    switch = entity(hass, "switch", "forced_run_ev")
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity(hass, "sensor", "mode_ev")).state == "no_cap"


async def test_the_panel_saves_the_site_off_peak_hours_and_refuses_a_bad_window(hass: HomeAssistant, hass_ws_client):
    world = World(hass, data=SITE, devices=[])
    p1, p2 = world.patches()
    with p1, p2:
        await setup(hass, data=SITE, devices=[])
        client = await hass_ws_client(hass)
        form = (await ws(client, type="solarprio/settings_form", language="fr"))["result"]
        names = {f["name"]: f for f in form["fields"]}
        assert {"offpeak_entity", "offpeak", "offpeak_extra", "offpeak_values"} <= set(names)
        assert names["offpeak"]["label"] != "offpeak"  # translated
        bad = await ws(client, type="solarprio/settings_save", values={**form["values"], "offpeak": "soon"})
        assert not bad["success"] or bad["result"].get("field") == "offpeak" or "offpeak" in str(bad)
        good = await ws(client, type="solarprio/settings_save", values={**form["values"], "offpeak_entity": PERIOD, "offpeak": "22:30-06:30"})
        assert good["success"], good


async def test_the_panel_warns_about_a_numeric_site_signal(hass: HomeAssistant, hass_ws_client):
    hass.states.async_set("sensor.index_wh", "0.0", {"unit_of_measurement": "Wh", "device_class": "energy"})
    world = World(hass, data=SITE_OFFPEAK, devices=[])
    hass.states.async_set(PERIOD, "HP..")
    p1, p2 = world.patches()
    with p1, p2:
        await setup(hass, data=SITE_OFFPEAK, devices=[])
        client = await hass_ws_client(hass)
        form = (await ws(client, type="solarprio/settings_form", language="en"))["result"]
        bad = await ws(client, type="solarprio/settings_save", values={**form["values"], "offpeak_entity": "sensor.index_wh",
                                                                       "offpeak_values": "HC.."})
        assert bad["success"] and bad["result"]["warnings"] == ["offpeak_numeric"]
        await hass.async_block_till_done()
        # a device on the site's hours is checked against the site's signal
        base = {"name": "ECS", "entity_id": SETPOINT, "priority": 1, "power_w": 2400, "measured_entity": POWER, "temp_entity": TEMP,
                "temp_max_solar": 65, "scale": "watts"}
        saved = await ws(client, type="solarprio/device_save", kind="proportional", values=base)
        assert "offpeak_numeric" in saved["result"]["warnings"]
        await hass.async_block_till_done()
        good = await ws(client, type="solarprio/settings_save", values={**form["values"], "offpeak_entity": PERIOD})
        assert good["result"]["warnings"] == []
        await hass.async_block_till_done()
        again = await ws(client, type="solarprio/device_save", kind="proportional", device_id="ecs", values=base)
        assert "offpeak_numeric" not in again["result"]["warnings"]


async def test_editing_a_device_keeps_its_older_own_off_peak_hours_and_drops_an_older_follow_the_site_leftover(
        hass: HomeAssistant, hass_ws_client):
    world = World(hass, data=SITE_OFFPEAK, devices=[])
    hass.states.async_set(PERIOD, "HP..")
    p1, p2 = world.patches()
    with p1, p2:
        old = {**HEATER, "temp_min": None, "measured_entity": POWER, "offpeak": "01:00-05:00"}  # written before the Settings had hours
        await setup(hass, data=SITE_OFFPEAK, devices=[old])
        client = await hass_ws_client(hass)
        values = {"name": "Chauffe-eau", "entity_id": SETPOINT, "priority": 1, "power_w": 2400, "measured_entity": POWER,
                  "temp_entity": TEMP, "temp_max_solar": 65, "scale": "watts"}  # the form no longer carries the hours
        await ws(client, type="solarprio/device_save", kind="proportional", device_id="ecs", values=values)
        await hass.async_block_till_done()
        assert hass.config_entries.async_entries(DOMAIN)[0].options["devices"][0]["offpeak"] == "01:00-05:00"  # not lost silently
    world2 = World(hass, data=SITE_OFFPEAK, devices=[])
    p1, p2 = world2.patches()
    with p1, p2:
        # a device saved by the previous version: "follow the site" ticked, and an old index of its own that must not come back
        left = {**HEATER, "id": "ecs2", "name": "ECS2", "temp_min": None, "measured_entity": POWER, "offpeak_site": True,
                "offpeak_entity": "sensor.old_index"}
        from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: F401
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        hass.config_entries.async_update_entry(entry, options={"devices": [left]})
        await hass.async_block_till_done()
        client = await hass_ws_client(hass)
        await ws(client, type="solarprio/device_save", kind="proportional", device_id="ecs2", values={**values, "name": "ECS2"})
        await hass.async_block_till_done()
        saved = hass.config_entries.async_entries(DOMAIN)[0].options["devices"][0]
        assert "offpeak_entity" not in saved and "offpeak_site" not in saved  # the old index does not come back


async def test_the_panel_flips_the_same_switches_as_the_entities(hass: HomeAssistant, hass_ws_client):
    heater = {**HEATER, "temp_min": 40, "sanitary_forced_only": True, "measured_entity": POWER}
    world = World(hass, data=SITE_OFFPEAK, devices=[heater], temp="50", local=NIGHT)
    hass.states.async_set(PERIOD, "HC..")
    hass.states.async_set(HOUSE, "1000", {"unit_of_measurement": "W"})
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        client = await hass_ws_client(hass)
        snap = (await ws(client, type="solarprio/state"))["result"]
        assert snap["devices"][0]["controls"] == {"offpeak": False, "forced_run": False, "extra_windows": False}
        res = await ws(client, type="solarprio/set_device_control", device_id="ecs", control="offpeak", on=True)
        assert res["success"] and res["result"]["devices"][0]["controls"]["offpeak"] is True
        assert hass.states.get(entity(hass, "switch", "offpeak_ecs")).state == "on"  # the entity follows
        assert res["result"]["devices"][0]["offpeak_mode"] == "router_offpeak"
        # and the other way round: the entity changes what the panel shows
        await hass.services.async_call("switch", "turn_off", {"entity_id": entity(hass, "switch", "offpeak_ecs")}, blocking=True)
        assert coord.snapshot()["devices"][0]["controls"]["offpeak"] is False
        res = await ws(client, type="solarprio/set_device_control", device_id="ecs", control="forced_run", on=True)
        assert res["result"]["devices"][0]["controls"]["forced_run"] is True
        assert hass.states.get(entity(hass, "switch", "forced_run_ecs")).state == "on"
        # a switch the device does not have, and a device that does not exist
        plain = await ws(client, type="solarprio/set_device_control", device_id="nope", control="offpeak", on=True)
        assert not plain["success"] and plain["error"]["code"] == "unknown_device"


async def test_a_device_without_a_switch_refuses_that_control(hass: HomeAssistant, hass_ws_client):
    world = World(hass, data=DATA, devices=[{**HEATER, "temp_min": None}], local=NIGHT)  # no off-peak hours, no forced run
    p1, p2 = world.patches()
    with p1, p2:
        await started(world)
        client = await hass_ws_client(hass)
        res = await ws(client, type="solarprio/set_device_control", device_id="ecs", control="offpeak", on=True)
        assert not res["success"] and res["error"]["code"] == "no_such_control"
        assert (await ws(client, type="solarprio/state"))["result"]["devices"][0]["controls"] == {}
