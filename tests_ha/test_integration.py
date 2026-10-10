from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.solarprio.const import DOMAIN

ROOT = Path(__file__).resolve().parent.parent
GRID = "sensor.grid_power"

DATA = {
    "mode": "export", "export_entity": GRID, "invert": False,
    "interval_s": 5, "stale_after_s": 60, "on_stale": "off",
}


def dev(**kw):
    base = {
        "id": "x", "name": "X", "entity_id": "switch.x", "kind": "on_off", "priority": 1, "power_w": 1000,
        "min_power_w": 0, "scale": "percent", "min_on_s": 0, "min_off_s": 0,
        "start_margin_w": 0, "stay_tolerance_w": 0, "enabled": True,
    }
    return {**base, **kw}


DEVICES = [
    dev(id="dimmer", name="Dimmer", entity_id="number.dimmer", kind="proportional", priority=1, power_w=2000),
    dev(id="pump", name="Pump", entity_id="switch.pump", priority=2, power_w=800),
]


async def setup(hass: HomeAssistant, data=None, devices=None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=data or DATA, options={"devices": DEVICES if devices is None else devices}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def coordinator(hass, entry):
    return hass.data[DOMAIN][entry.entry_id]


def test_vendored_core_is_in_sync_with_source():
    for name in ("__init__.py", "engine.py", "models.py", "ports.py", "sources.py"):
        src = (ROOT / "src" / "solarprio" / name).read_text()
        vendored = (ROOT / "custom_components" / "solarprio" / "core" / name).read_text()
        assert src == vendored, f"{name} differs: run scripts/sync_core.py"


async def test_surplus_is_routed_by_priority(hass: HomeAssistant):
    set_value = async_mock_service(hass, "number", "set_value")
    turn_on = async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, "2300", {"unit_of_measurement": "W"})
    entry = await setup(hass)

    # 2300 W surplus: dimmer takes 2000 W (100 %), pump needs 800 W but only 300 W is left
    assert [c.data for c in set_value] == [{"entity_id": "number.dimmer", "value": 100.0}]
    assert turn_on == []
    assert hass.states.get("sensor.solarprio_available_power").state == "2300.0"
    assert hass.states.get("sensor.solarprio_status").state == "routing"

    # more surplus: routed power is added back, pump now fits
    hass.states.async_set(GRID, "900", {"unit_of_measurement": "W"})  # 900 export on top of 2000 routed
    await coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in turn_on] == ["switch.pump"]


async def test_kw_unit_is_converted(hass: HomeAssistant):
    set_value = async_mock_service(hass, "number", "set_value")
    hass.states.async_set(GRID, "1.0", {"unit_of_measurement": "kW"})
    await setup(hass)
    assert set_value[0].data["value"] == 50.0  # 1000 W of 2000 W


async def test_measurement_lost_switches_off(hass: HomeAssistant):
    async_mock_service(hass, "number", "set_value")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    async_mock_service(hass, "homeassistant", "turn_on")
    hass.states.async_set(GRID, "3000", {"unit_of_measurement": "W"})
    entry = await setup(hass)

    hass.states.async_set(GRID, "unavailable")
    await coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.solarprio_status").state == "measurement_lost_off"
    assert "switch.pump" in [c.data["entity_id"] for c in turn_off]


async def test_missing_sensor_entity_is_treated_as_lost(hass: HomeAssistant):
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    async_mock_service(hass, "number", "set_value")
    entry = await setup(hass)  # GRID has no state at all
    assert hass.states.get("sensor.solarprio_status").state == "measurement_lost_off"
    assert coordinator(hass, entry).data["available_w"] is None


async def test_routing_switch_off_turns_loads_off_and_stops_routing(hass: HomeAssistant):
    set_value = async_mock_service(hass, "number", "set_value")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    async_mock_service(hass, "homeassistant", "turn_on")
    hass.states.async_set(GRID, "3000", {"unit_of_measurement": "W"})
    await setup(hass)
    n_set = len(set_value)

    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.solarprio_routing"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.solarprio_status").state == "disabled"
    assert {c.data["entity_id"] for c in turn_off} >= {"switch.pump"}
    assert set_value[-1].data["value"] == 0.0  # dimmer set to 0
    assert len(set_value) == n_set + 1


async def test_unloading_switches_loads_off(hass: HomeAssistant):
    set_value = async_mock_service(hass, "number", "set_value")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    async_mock_service(hass, "homeassistant", "turn_on")
    hass.states.async_set(GRID, "3000", {"unit_of_measurement": "W"})
    entry = await setup(hass)
    turn_off.clear()
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert "switch.pump" in [c.data["entity_id"] for c in turn_off]


async def test_config_flow_creates_entry(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"mode": "export"})
    assert result["step_id"] == "entities"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"export_entity": GRID, "invert": True, "interval_s": 5, "stale_after_s": 60, "on_stale": "off"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["export_entity"] == GRID
    assert result["options"] == {"devices": []}


async def test_config_flow_single_instance(hass: HomeAssistant):
    await setup(hass, devices=[])
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.ABORT


async def _add_device(hass, entry, kind, form):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_device"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"kind": kind})
    assert result["step_id"] == "device_details"
    return await hass.config_entries.options.async_configure(result["flow_id"], form)


async def test_options_flow_add_edit_remove_device(hass: HomeAssistant):
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, "0", {"unit_of_measurement": "W"})
    entry = await setup(hass, devices=[])

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["add_device"]  # no edit/remove while empty

    form = {
        "name": "Water heater", "entity_id": "switch.heater", "priority": 1, "power_w": 2000,
        "min_on_s": 60, "min_off_s": 30, "start_margin_w": 0, "stay_tolerance_w": 0,
    }
    result = await _add_device(hass, entry, "on_off", form)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    devices = entry.options["devices"]
    assert [d["id"] for d in devices] == ["water_heater"]
    assert devices[0]["priority"] == 1 and devices[0]["enabled"] is True and devices[0]["kind"] == "on_off"
    await hass.async_block_till_done()  # entry reloaded with the new device

    # invalid: minimum power above maximum power (proportional)
    bad = {"name": "Bad", "entity_id": "light.x", "priority": 2, "power_w": 100, "min_power_w": 500, "scale": "percent", "min_on_s": 0, "min_off_s": 0}
    result = await _add_device(hass, entry, "proportional", bad)
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "invalid_device"}

    # edit the priority: kind-specific form is shown again, identity is kept
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "edit_select"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"device": "water_heater"})
    assert result["step_id"] == "device_details"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**form, "priority": 5})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["devices"][0]["priority"] == 5
    assert entry.options["devices"][0]["id"] == "water_heater"
    await hass.async_block_till_done()

    # remove
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "remove_device"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"devices": ["water_heater"]})
    assert entry.options["devices"] == []


async def test_editing_a_disabled_device_keeps_it_disabled(hass: HomeAssistant):
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, "0", {"unit_of_measurement": "W"})
    entry = await setup(hass, devices=[dev(id="pump", name="Pump", entity_id="switch.pump", enabled=False)])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "edit_select"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"device": "pump"})
    form = {"name": "Pump 2", "entity_id": "switch.pump", "priority": 1, "power_w": 900, "min_on_s": 0, "min_off_s": 0,
            "start_margin_w": 0, "stay_tolerance_w": 0}
    result = await hass.config_entries.options.async_configure(result["flow_id"], form)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["devices"][0]["name"] == "Pump 2"
    assert entry.options["devices"][0]["enabled"] is False


async def test_failed_service_call_is_not_counted_as_routed_power_and_is_retried(hass: HomeAssistant):
    calls = []
    failing = {"on": True}

    async def turn_on(call):
        if failing["on"]:
            raise RuntimeError("device unreachable")
        calls.append(call.data["entity_id"])

    hass.services.async_register("homeassistant", "turn_on", turn_on)
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, "900", {"unit_of_measurement": "W"})
    entry = await setup(hass, devices=[dev(id="pump", name="Pump", entity_id="switch.pump", power_w=800)])

    coord = coordinator(hass, entry)
    assert coord.engine.routed_w == 0  # the "on" never reached the pump
    failing["on"] = False
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert calls == ["switch.pump"]  # retried
    assert coord.engine.routed_w == 800
