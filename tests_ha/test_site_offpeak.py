"""Off-peak hours set once for the whole site, followed by the devices that choose to, and the forced run of a car."""
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.solarprio.const import DOMAIN
from custom_components.solarprio.coordinator import with_site_offpeak
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


def test_a_device_follows_the_site_hours_only_when_it_chooses_to_and_its_own_settings_win():
    site = {"offpeak_entity": PERIOD, "offpeak_values": "HC*", "offpeak": "22:30-06:30", "offpeak_extra": "12:30-14:30"}
    assert with_site_offpeak({"id": "a"}, site) == {"id": "a"}  # does not follow: untouched
    follows = with_site_offpeak({"id": "a", "offpeak_site": True}, site)
    assert (follows["offpeak_entity"], follows["offpeak_values"], follows["offpeak"], follows["offpeak_extra"]) == (
        PERIOD, "HC*", "22:30-06:30", "12:30-14:30")
    own = with_site_offpeak({"id": "a", "offpeak_site": True, "offpeak": "01:00-05:00", "offpeak_entity": "sensor.mine"}, site)
    assert own["offpeak"] == "01:00-05:00" and own["offpeak_entity"] == "sensor.mine"  # what the device sets wins


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


async def test_a_heater_following_the_site_is_fed_in_the_site_windows_and_the_midday_switch_chooses(hass: HomeAssistant):
    heater = {**HEATER, "temp_min": None, "offpeak_site": True, "measured_entity": POWER}
    world = World(hass, data=SITE_OFFPEAK, devices=[heater], temp="50", local=MIDDAY)
    hass.states.async_set(PERIOD, "HC..")
    hass.states.async_set(HOUSE, "1000", {"unit_of_measurement": "W"})
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        switch = entity(hass, "switch", "extra_windows_ecs")  # created because the SITE has extra windows
        assert hass.states.get(switch).state == "off" and coord.snapshot()["devices"][0]["cmd_w"] == 0  # midday: switch off
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
        await world.tick(coord)
        assert coord.snapshot()["devices"][0]["mode"] == "offpeak"
        hass.states.async_set(PERIOD, "HP..")  # the tariff says peak: never forced
        await world.tick(coord)
        assert coord.snapshot()["devices"][0]["mode"] != "offpeak"


async def test_a_heater_that_does_not_follow_the_site_ignores_its_hours(hass: HomeAssistant):
    heater = {**HEATER, "temp_min": None, "measured_entity": POWER}  # offpeak_site not ticked
    world = World(hass, data=SITE_OFFPEAK, devices=[heater], temp="50", local=NIGHT)
    hass.states.async_set(PERIOD, "HC..")
    hass.states.async_set(HOUSE, "1000", {"unit_of_measurement": "W"})
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        assert coord.snapshot()["devices"][0]["mode"] != "offpeak" and coord.snapshot()["devices"][0]["cmd_w"] == 0


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
