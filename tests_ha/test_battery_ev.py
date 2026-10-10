import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import async_mock_service

from .test_integration import GRID, _add_device, coordinator, dev, setup

BATTERY = dev(id="bat", name="Battery", kind="battery", entity_id="number.bat_charge", priority=1, power_w=3000,
              min_power_w=200, scale="watts", soc_entity="sensor.bat_soc", soc_max=90, soc_resume_margin=3,
              measured_entity="sensor.bat_power")
EV = dev(id="ev", name="Car", kind="ev_charger", entity_id="number.ev_current", switch_entity="switch.ev",
         priority=1, phases=1, voltage_v=230, min_current_a=6, max_current_a=16, current_step_a=1,
         power_w=3680, min_power_w=1380, connected_entity="binary_sensor.car_plugged", soc_entity="sensor.car_soc", soc_max=80)
PUMP = dev(id="pump", name="Pump", entity_id="switch.pump", priority=2, power_w=800)


def grid(hass, watts):
    hass.states.async_set(GRID, str(watts), {"unit_of_measurement": "W"})


async def refresh(hass, entry):
    await coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()


async def test_battery_is_charged_with_a_power_setpoint_until_its_soc_limit(hass: HomeAssistant):
    set_value = async_mock_service(hass, "number", "set_value")
    turn_on = async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    grid(hass, 2500)
    hass.states.async_set("sensor.bat_soc", "60")
    entry = await setup(hass, devices=[BATTERY, PUMP])
    assert set_value[-1].data == {"entity_id": "number.bat_charge", "value": 2500.0}  # watts, below the 3000 W max
    assert turn_on == []  # the pump (lower priority) gets nothing yet

    hass.states.async_set("sensor.bat_soc", "90")  # limit reached: battery stops, pump takes over
    await refresh(hass, entry)
    assert set_value[-1].data["value"] == 0.0
    assert [c.data["entity_id"] for c in turn_on] == ["switch.pump"]

    snap = coordinator(hass, entry).snapshot()
    bat = next(d for d in snap["devices"] if d["id"] == "bat")
    assert bat["soc"] == 90.0 and bat["kind"] == "battery"


async def test_battery_percent_scale(hass: HomeAssistant):
    set_value = async_mock_service(hass, "number", "set_value")
    grid(hass, 1500)
    await setup(hass, devices=[{**BATTERY, "scale": "percent", "soc_entity": None, "soc_max": 100}])
    assert set_value[-1].data["value"] == 50.0  # 1500 W of 3000 W


async def test_unknown_soc_with_a_limit_does_not_charge(hass: HomeAssistant):
    set_value = async_mock_service(hass, "number", "set_value")
    grid(hass, 2500)
    await setup(hass, devices=[BATTERY])  # soc sensor does not exist, limit is 90 %
    assert set_value[-1].data["value"] == 0.0


async def test_measured_power_is_used_to_compute_the_surplus(hass: HomeAssistant):
    set_value = async_mock_service(hass, "number", "set_value")
    grid(hass, 1000)
    hass.states.async_set("sensor.bat_soc", "50")
    hass.states.async_set("sensor.bat_power", "0.5", {"unit_of_measurement": "kW"})  # kW converted to 500 W
    entry = await setup(hass, devices=[BATTERY])
    assert coordinator(hass, entry).engine.routed_w == 500
    assert coordinator(hass, entry).engine.reading("bat").measured_w == 500


async def test_ev_charger_current_start_stop_and_switch(hass: HomeAssistant):
    set_value = async_mock_service(hass, "number", "set_value")
    turn_on = async_mock_service(hass, "homeassistant", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set("binary_sensor.car_plugged", "on")
    hass.states.async_set("sensor.car_soc", "40")
    grid(hass, 1000)  # below 6 A (1380 W)
    entry = await setup(hass, devices=[EV])
    assert set_value == [] and [c.data["entity_id"] for c in turn_off] == ["switch.ev"]

    grid(hass, 2500)  # 2500 W -> floor(10.87) = 10 A
    await refresh(hass, entry)
    assert set_value[-1].data == {"entity_id": "number.ev_current", "value": 10.0}
    assert [c.data["entity_id"] for c in turn_on] == ["switch.ev"]

    snap = coordinator(hass, entry).snapshot()
    ev = snap["devices"][0]
    assert ev["current_a"] == 10.0 and ev["connected"] is True and ev["soc"] == 40.0

    hass.states.async_set("binary_sensor.car_plugged", "off")  # unplugged: stops, surplus released
    await refresh(hass, entry)
    assert turn_off[-1].data["entity_id"] == "switch.ev"
    assert coordinator(hass, entry).snapshot()["devices"][0]["current_a"] == 0.0


async def test_ev_without_switch_is_paused_with_zero_amps(hass: HomeAssistant):
    set_value = async_mock_service(hass, "number", "set_value")
    grid(hass, 0)
    await setup(hass, devices=[{**EV, "switch_entity": None, "connected_entity": None, "soc_entity": None, "soc_max": 100}])
    assert set_value[-1].data == {"entity_id": "number.ev_current", "value": 0}


async def test_ev_soc_target_stops_the_charge(hass: HomeAssistant):
    set_value = async_mock_service(hass, "number", "set_value")
    async_mock_service(hass, "homeassistant", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set("binary_sensor.car_plugged", "on")
    hass.states.async_set("sensor.car_soc", "50")
    grid(hass, 3000)
    entry = await setup(hass, devices=[EV])
    assert set_value[-1].data["value"] == 13.0
    n = len(turn_off)
    hass.states.async_set("sensor.car_soc", "80")
    await refresh(hass, entry)
    assert len(turn_off) == n + 1 and turn_off[-1].data["entity_id"] == "switch.ev"


async def test_options_flow_ev_form_stores_the_derived_power_range(hass: HomeAssistant):
    async_mock_service(hass, "homeassistant", "turn_off")
    async_mock_service(hass, "number", "set_value")
    grid(hass, 0)
    entry = await setup(hass, devices=[])
    form = {
        "name": "Wallbox", "entity_id": "number.ev_current", "priority": 1, "phases": "3", "voltage_v": 230,
        "min_current_a": 6, "max_current_a": 16, "current_step_a": 1, "soc_max": 100, "min_on_s": 300, "min_off_s": 0,
        "start_margin_w": 0, "stay_tolerance_w": 0,
    }
    result = await _add_device(hass, entry, "ev_charger", form)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    ev = entry.options["devices"][0]
    assert ev["kind"] == "ev_charger" and ev["phases"] == 3
    assert (ev["min_power_w"], ev["power_w"]) == (4140, 11040)  # 6 A and 16 A on three phases at 230 V


async def test_options_flow_battery_form_and_invalid_ev(hass: HomeAssistant):
    async_mock_service(hass, "homeassistant", "turn_off")
    async_mock_service(hass, "number", "set_value")
    grid(hass, 0)
    entry = await setup(hass, devices=[])
    battery = {
        "name": "Home battery", "entity_id": "number.bat_charge", "priority": 1, "power_w": 3000, "min_power_w": 200,
        "scale": "watts", "soc_entity": "sensor.bat_soc", "soc_max": 95, "soc_resume_margin": 3, "min_on_s": 0, "min_off_s": 0,
    }
    result = await _add_device(hass, entry, "battery", battery)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["devices"][0]["soc_entity"] == "sensor.bat_soc"
    await hass.async_block_till_done()

    bad_ev = {
        "name": "Bad", "entity_id": "number.x", "priority": 2, "phases": "1", "voltage_v": 230, "min_current_a": 20,
        "max_current_a": 16, "current_step_a": 1, "soc_max": 100, "min_on_s": 0, "min_off_s": 0, "start_margin_w": 0, "stay_tolerance_w": 0,
    }
    result = await _add_device(hass, entry, "ev_charger", bad_ev)
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "invalid_device"}
