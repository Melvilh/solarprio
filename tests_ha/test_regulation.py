"""Central regulation in Home Assistant: the engine decides everything (temperatures, sanitary minimum, subscription
cap, emergency cut) and the device only receives a power."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.solarprio.const import DOMAIN

from .test_integration import GRID, coordinator, dev, setup
from .test_panel import ws

SETPOINT = "number.chauffe_eau_consigne_externe_w"
POWER = "sensor.chauffe_eau_puissance"
TEMP = "sensor.chauffe_eau_temperature"
HOUSE = "sensor.maison_puissance"
W = {"unit_of_measurement": "W"}
HEATER = dev(id="ecs", name="Chauffe-eau", kind="proportional", entity_id=SETPOINT, priority=1, power_w=2400, min_power_w=15,
             scale="watts", measured_entity=POWER, temp_entity=TEMP, temp_max_solar=65, temp_max_offpeak=60, temp_hysteresis=3,
             temp_min=40, min_on_s=0, min_off_s=0)
DATA = {"mode": "export", "export_entity": GRID, "invert": False, "interval_s": 5, "stale_after_s": 60, "on_stale": "off",
        "margin_w": 0}
SITE = {**DATA, "subscription_va": 5700, "house_entity": HOUSE, "emergency_import_w": 250}


class World:
    """A clock that moves and a heater that follows its setpoint."""

    def __init__(self, hass, data=DATA, devices=(HEATER,), temp="50", house="1000", grid="0", local=datetime(2026, 11, 10, 14, 0)):
        self.hass, self.data, self.devices, self.local, self.mono = hass, data, list(devices), local, 1000.0
        self.set_value = async_mock_service(hass, "number", "set_value")
        hass.states.async_set(TEMP, temp, {"unit_of_measurement": "°C"})
        hass.states.async_set(HOUSE, house, W)
        hass.states.async_set(GRID, grid, W)
        hass.states.async_set(POWER, "0", W)

    def patches(self):
        return (patch("custom_components.solarprio.coordinator.time", SimpleNamespace(monotonic=lambda: self.mono)),
                patch.object(dt_util, "now", lambda *a, **k: self.local))

    @property
    def order(self):
        return self.set_value[-1].data["value"] if self.set_value else None

    async def tick(self, coord, seconds=5):
        self.local += timedelta(seconds=seconds)
        self.mono += seconds
        await coord.async_refresh()
        await self.hass.async_block_till_done()


async def started(world, **kw):
    entry = await setup(world.hass, data=world.data, devices=world.devices)
    return coordinator(world.hass, entry)


async def test_the_sun_heats_and_the_tank_temperature_stops_it(hass: HomeAssistant):
    world = World(hass, grid="1500")
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        assert world.order == 1500.0 and coord.snapshot()["devices"][0]["mode"] == "solar"
        hass.states.async_set(TEMP, "66", {"unit_of_measurement": "°C"})
        await world.tick(coord)
        assert world.order == 0.0 and coord.snapshot()["devices"][0]["mode"] == "hot"
        assert coord.snapshot()["devices"][0]["temperature_c"] == 66.0


async def test_a_missing_temperature_stops_the_heater_and_fahrenheit_is_converted(hass: HomeAssistant):
    world = World(hass, grid="1500")
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        assert world.order == 1500.0
        hass.states.async_set(TEMP, "unavailable")
        await world.tick(coord)
        assert world.order == 0.0 and coord.snapshot()["devices"][0]["mode"] == "sensor_fault"
        hass.states.async_set(TEMP, "149", {"unit_of_measurement": "°F"})  # 65 °C
        await world.tick(coord)
        assert coord.snapshot()["devices"][0]["temperature_c"] == pytest.approx(65.0)


async def test_a_cold_tank_is_heated_from_the_grid_inside_the_subscription(hass: HomeAssistant):
    world = World(hass, data=SITE, temp="38", house="3000", grid="-3000")  # no sun, the house imports 3000 W
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        assert world.order == 2400.0 and coord.snapshot()["devices"][0]["mode"] == "sanitary"  # 2700 W of room
        hass.states.async_set(HOUSE, "5600")  # the rest of the house now fills the subscription (heater not drawing yet)
        hass.states.async_set(GRID, "-5600", W)
        await world.tick(coord)
        assert world.order == 0.0 and coord.snapshot()["devices"][0]["mode"] == "sanitary_limited"


async def test_nothing_is_fed_from_the_grid_when_the_house_power_is_unknown(hass: HomeAssistant):
    world = World(hass, data=SITE, temp="38", house="3000", grid="-3000")
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        assert world.order == 2400.0
        hass.states.async_set(HOUSE, "unavailable")  # not a lost measurement: just no grid feeding
        await world.tick(coord)
        assert world.order == 0.0
        assert coord.snapshot()["status"] == "routing"


async def test_the_emergency_cut_stops_a_device_running_on_the_sun(hass: HomeAssistant):
    heater = dev(**{**HEATER, "temp_min": None, "min_on_s": 600, "temp_entity": None, "temp_max_solar": None, "temp_max_offpeak": None})
    world = World(hass, data=SITE, devices=[heater], grid="1500")
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        assert world.order == 1500.0
        hass.states.async_set(POWER, "1500", W)
        hass.states.async_set(GRID, "-400", W)  # the clouds came: 400 W imported, over the 250 W threshold
        await world.tick(coord)
        assert world.order == 0.0  # no minimum run time holds it


async def test_a_sensor_that_only_reports_changes_is_not_lost_when_the_delay_is_zero(hass: HomeAssistant):
    world = World(hass, data={**DATA, "stale_after_s": 0}, devices=[dev(id="p", name="P", entity_id="switch.p", power_w=500)], grid="800")
    turn_on = async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        assert turn_on and coord.snapshot()["status"] == "routing"
        old = dt_util.utcnow() + timedelta(hours=3)  # three hours later, the value never changed and was never re-reported
        with patch.object(dt_util, "utcnow", lambda: old):
            await world.tick(coord)
        assert coord.snapshot()["status"] == "routing"


async def test_with_a_delay_the_same_sensor_is_reported_lost_and_the_panel_says_why(hass: HomeAssistant, hass_ws_client):
    world = World(hass, data={**DATA, "stale_after_s": 60}, devices=[dev(id="p", name="P", entity_id="switch.p", power_w=500)], grid="800")
    async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    p1, p2 = world.patches()
    with p1, p2:
        coord = await started(world)
        client = await hass_ws_client(hass)
        old = dt_util.utcnow() + timedelta(hours=3)
        with patch.object(dt_util, "utcnow", lambda: old):
            await world.tick(coord)
        result = (await ws(client, type="solarprio/state"))["result"]
        assert result["status"] == "measurement_lost_off" and f"{GRID} has not reported for" in result["detail"]


async def test_the_regulation_settings_can_be_saved_and_the_temperature_needs_its_sensor(hass: HomeAssistant, hass_ws_client):
    world = World(hass, devices=[])
    p1, p2 = world.patches()
    with p1, p2:
        entry = await setup(hass, data=SITE, devices=[])
        client = await hass_ws_client(hass)
        form = {"name": "ECS", "entity_id": SETPOINT, "priority": 1, "power_w": 2400, "scale": "watts", "min_power_w": 15,
                "measured_entity": POWER, "min_on_s": 0, "min_off_s": 0, "hold_s": 8, "ramp_up_w": 200, "deadband_w": 15,
                "temp_max_solar": 65, "temp_max_offpeak": 60, "temp_hysteresis": 3, "temp_min": 40}
        refused = await ws(client, type="solarprio/device_save", kind="proportional", values=form)
        assert refused["error"]["code"] == "invalid_device" and "temperature" in refused["error"]["message"]
        saved = await ws(client, type="solarprio/device_save", kind="proportional", values={**form, "temp_entity": TEMP})
        assert saved["success"]
        await hass.async_block_till_done()
        device = coordinator(hass, entry).engine.device("ecs")
        assert (device.temp_max_solar, device.temp_max_offpeak, device.temp_min, device.hold_s, device.ramp_up_w) == (65, 60, 40, 8, 200)
        assert coordinator(hass, entry).engine._subscription_va == 5700  # the site settings reached the engine


async def test_the_site_settings_need_the_house_sensor_for_a_subscription_limit(hass: HomeAssistant, hass_ws_client):
    world = World(hass, devices=[])
    p1, p2 = world.patches()
    with p1, p2:
        entry = await setup(hass, data=DATA, devices=[])
        client = await hass_ws_client(hass)
        values = {**DATA, "offpeak_budget_w": 0, "subscription_va": 5700}
        refused = await ws(client, type="solarprio/settings_save", values=values)
        assert refused["error"]["message"] == "house_entity"
        saved = await ws(client, type="solarprio/settings_save", values={**values, "house_entity": HOUSE})
        assert saved["success"]
        await hass.async_block_till_done()
        assert entry.data["subscription_va"] == 5700 and entry.data["house_entity"] == HOUSE
        assert coordinator(hass, entry).engine._subscription_va == 5700


async def test_advanced_fields_are_flagged_for_the_panel(hass: HomeAssistant, hass_ws_client):
    world = World(hass, devices=[])
    p1, p2 = world.patches()
    with p1, p2:
        await setup(hass, data=DATA, devices=[])
        client = await hass_ws_client(hass)
        fields = {f["name"]: f for f in (await ws(client, type="solarprio/device_form", kind="proportional", language="fr"))["result"]["fields"]}
        basic = [n for n, f in fields.items() if not f["advanced"]]
        assert basic == ["name", "entity_id", "priority", "power_w", "scale", "measured_entity", "temp_entity", "temp_max_solar",
                         "temp_max_offpeak", "offpeak_entity"]
        assert all(fields[n]["advanced"] for n in ("hold_s", "ramp_up_w", "deadband_w", "temp_min", "temp_hysteresis", "surplus_only"))


async def test_a_tariff_entity_that_is_a_number_is_flagged_as_probably_the_wrong_entity(hass: HomeAssistant, hass_ws_client):
    world = World(hass, devices=[])
    hass.states.async_set("sensor.linky_heures_creuses_index", "35495096.0", {"unit_of_measurement": "Wh"})
    hass.states.async_set("sensor.linky_periode", "HP..")
    p1, p2 = world.patches()
    with p1, p2:
        await setup(hass, data=DATA, devices=[])
        client = await hass_ws_client(hass)
        base = {"name": "ECS", "entity_id": SETPOINT, "priority": 1, "power_w": 2400, "scale": "watts", "min_power_w": 15,
                "measured_entity": POWER, "min_on_s": 0, "min_off_s": 0}
        index = await ws(client, type="solarprio/device_save", kind="proportional",
                         values={**base, "offpeak_entity": "sensor.linky_heures_creuses_index"})
        assert index["success"] and "offpeak_numeric" in index["result"]["warnings"]  # saved, but the user is told
        await hass.async_block_till_done()
        period = await ws(client, type="solarprio/device_save", kind="proportional",
                          values={**base, "name": "ECS 2", "offpeak_entity": "sensor.linky_periode", "offpeak_values": "HC*"})
        assert "offpeak_numeric" not in period["result"]["warnings"]


async def test_the_presets_fill_a_new_water_heater_form_and_pass_the_validation(hass: HomeAssistant, hass_ws_client):
    from custom_components.solarprio.forms import PRESETS, clean_device

    world = World(hass, devices=[])
    p1, p2 = world.patches()
    with p1, p2:
        await setup(hass, data=DATA, devices=[])
        client = await hass_ws_client(hass)
        for language, expected in (("fr", "Chauffe-eau sur routeur solaire"), ("en", "Water heater on a solar router")):
            first = (await ws(client, type="solarprio/device_form", kind="on_off", language=language))["result"]
            assert [p["id"] for p in first["presets"]] == list(PRESETS)
            assert expected in next(p["label"] for p in first["presets"] if p["id"] == "generic-water-heater-dimmer")
        assert {"victron-evcs", "generic-water-heater-relay"} <= set(PRESETS)
        for preset, spec in PRESETS.items():
            if spec["kind"] == "ev_charger":  # a brand model: its values are fields of the form, the entities stay to be picked
                form = (await ws(client, type="solarprio/device_form", kind="ev_charger", preset=preset, language="en"))["result"]
                assert set(form["values"]) <= {f["name"] for f in form["fields"]}
                assert next(p for p in form["presets"] if p["id"] == preset)["brand"] == "Victron Energy"
                continue
            result = (await ws(client, type="solarprio/device_form", kind=spec["kind"], preset=preset, language="fr"))["result"]
            assert result["values"]["temp_max_solar"] == 65 and result["values"]["temp_min"] == 40
            names = {f["name"] for f in result["fields"]}
            assert set(result["values"]) <= names, set(result["values"]) - names  # every preset value is a field of that form
            # with an entity, a power and a temperature sensor added, the preset is a valid device
            clean_device(spec["kind"], {**result["values"], "name": "ECS", "entity_id": SETPOINT if spec["kind"] == "proportional" else "switch.ecs",
                                        "priority": 1, "power_w": 2400, "temp_entity": TEMP})
        proportional = (await ws(client, type="solarprio/device_form", kind="proportional", preset="generic-water-heater-dimmer"))["result"]["values"]
        assert (proportional["hold_s"], proportional["ramp_up_w"], proportional["deadband_w"]) == (8, 200, 15)
        unknown = await ws(client, type="solarprio/device_form", kind="proportional", preset="toaster")
        assert not unknown["success"]


async def test_saving_a_grid_fed_device_without_a_subscription_limit_warns_and_a_numeric_off_peak_entity_always_warns(
    hass: HomeAssistant, hass_ws_client
):
    world = World(hass, devices=[], local=datetime(2026, 11, 10, 17, 0))
    p1, p2 = world.patches()
    with p1, p2:
        await setup(hass, data=DATA, devices=[])  # no subscription limit in DATA
        client = await hass_ws_client(hass)
        hass.states.async_set("sensor.index_hc", "35507504.0", {"unit_of_measurement": "Wh"})
        base = {"name": "ECS", "entity_id": SETPOINT, "priority": 1, "power_w": 2400, "measured_entity": POWER,
                "temp_entity": TEMP, "temp_max_solar": 65, "scale": "watts"}
        # a sanitary minimum feeds the heater from the grid: no cap, so a warning
        saved = await ws(client, type="solarprio/device_save", kind="proportional", values={**base, "temp_min": 40})
        assert saved["result"]["warnings"] == ["no_subscription_cap"]
        # surplus only never feeds from the grid: no warning
        saved = await ws(client, type="solarprio/device_save", kind="proportional", device_id="ecs",
                         values={**base, "temp_min": 40, "surplus_only": True})
        assert saved["result"]["warnings"] == []
        # a numeric index is flagged even when states were typed (HC* can never match a number)
        saved = await ws(client, type="solarprio/device_save", kind="proportional", device_id="ecs",
                         values={**base, "surplus_only": True, "offpeak_entity": "sensor.index_hc", "offpeak_values": "HC*"})
        assert "offpeak_numeric" in saved["result"]["warnings"]
        # a price level typed as a number on purpose is fine
        saved = await ws(client, type="solarprio/device_save", kind="proportional", device_id="ecs",
                         values={**base, "surplus_only": True, "offpeak_entity": "sensor.index_hc", "offpeak_values": "35507504.0"})
        assert "offpeak_numeric" not in saved["result"]["warnings"]


async def test_with_a_subscription_limit_there_is_no_cap_warning(hass: HomeAssistant, hass_ws_client):
    from .test_regulation import SITE

    world = World(hass, data=SITE, devices=[], local=datetime(2026, 11, 10, 17, 0))
    p1, p2 = world.patches()
    with p1, p2:
        await setup(hass, data=SITE, devices=[])
        client = await hass_ws_client(hass)
        saved = await ws(client, type="solarprio/device_save", kind="proportional", values={
            "name": "ECS", "entity_id": SETPOINT, "priority": 1, "power_w": 2400, "measured_entity": POWER, "temp_entity": TEMP,
            "temp_max_solar": 65, "temp_min": 40, "scale": "watts"})
        assert saved["result"]["warnings"] == []
