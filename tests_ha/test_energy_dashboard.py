"""Pre-fill from the Energy dashboard, import of its devices, copy of a device, and the off-peak budget."""
from datetime import datetime

from homeassistant.components.energy.data import async_get_manager
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.solarprio.const import DOMAIN
from custom_components.solarprio.energy import async_read_energy_dashboard

from .test_integration import GRID, coordinator, dev, setup
from .test_offpeak import LOADS, Sim

W = {"unit_of_measurement": "W"}


def grid_source(*sensors):
    return {"type": "grid", "flow_from": [], "flow_to": [], "cost_adjustment_day": 0,
            "power": [{"stat_rate": s} for s in sensors]}


def solar_source(rate=None):
    source = {"type": "solar", "stat_energy_from": "sensor.pv_energy", "config_entry_solar_forecast": None}
    if rate:
        source["stat_rate"] = rate
    return source


async def set_dashboard(hass, sources=(), devices=()):
    manager = await async_get_manager(hass)
    await manager.async_update({
        "energy_sources": list(sources),
        "device_consumption": [{"stat_consumption": f"{s}_energy", "stat_rate": s, "name": n} for n, s in devices],
    })


def suggestion(result, key):
    marker = next(k for k in result["data_schema"].schema if str(k) == key)
    return (marker.description or {}).get("suggested_value")


def default_of(result, key):
    marker = next(k for k in result["data_schema"].schema if str(k) == key)
    return marker.default()


async def entities_step(hass, mode="export"):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"mode": mode})


# ------------------------------------------------------------------ reading the dashboard

async def test_nothing_is_suggested_when_the_dashboard_is_empty(hass: HomeAssistant):
    energy = await async_read_energy_dashboard(hass)
    assert energy.grid_power is None and energy.solar_power is None and energy.devices == []
    result = await entities_step(hass)
    assert suggestion(result, "export_entity") is None and default_of(result, "invert") is False


async def test_grid_power_sensor_is_prefilled_and_inverted(hass: HomeAssistant):
    hass.states.async_set(GRID, "-300", W)
    await set_dashboard(hass, [grid_source(GRID)])
    result = await entities_step(hass)
    assert suggestion(result, "export_entity") == GRID
    assert default_of(result, "invert") is True  # the dashboard counts import as positive
    assert result["description_placeholders"]["grid"] == GRID


async def test_solar_power_sensor_is_prefilled_in_production_mode(hass: HomeAssistant):
    hass.states.async_set("sensor.pv_power", "3000", W)
    await set_dashboard(hass, [solar_source("sensor.pv_power")])
    result = await entities_step(hass, "production")
    assert suggestion(result, "production_entity") == "sensor.pv_power"
    assert suggestion(result, "consumption_entity") is None  # the dashboard has no whole-house consumption


async def test_several_grid_sensors_or_missing_entities_are_not_guessed(hass: HomeAssistant):
    hass.states.async_set("sensor.l1", "1", W)
    hass.states.async_set("sensor.l2", "1", W)
    await set_dashboard(hass, [grid_source("sensor.l1", "sensor.l2")])
    energy = await async_read_energy_dashboard(hass)
    assert energy.grid_power is None and energy.grid_sensors == 2  # which one? the user decides

    await set_dashboard(hass, [grid_source("sensor.does_not_exist"), solar_source("sensor.also_missing")])
    energy = await async_read_energy_dashboard(hass)
    assert energy.grid_power is None and energy.solar_power is None


async def test_a_dashboard_with_only_energy_counters_suggests_nothing(hass: HomeAssistant):
    await set_dashboard(hass, [{"type": "grid", "flow_from": [{"stat_energy_from": "sensor.imp", "stat_cost": None,
                                "entity_energy_price": None, "number_energy_price": None}],
                                "flow_to": [], "cost_adjustment_day": 0}, solar_source()])
    energy = await async_read_energy_dashboard(hass)
    assert energy.grid_power is None and energy.solar_power is None


# ------------------------------------------------------------------ importing devices

async def test_devices_of_the_dashboard_are_imported_with_their_name_and_power_sensor(hass: HomeAssistant):
    async_mock_service(hass, "homeassistant", "turn_off")
    for n in (1, 2, 3):
        hass.states.async_set(f"sensor.evse{n}_power", "0", W)
    hass.states.async_set(GRID, "0", W)
    await set_dashboard(hass, devices=[(f"EVSE {n}", f"sensor.evse{n}_power") for n in (1, 2, 3)])
    entry = await setup(hass, devices=[dev(id="old", name="Old", entity_id="switch.old", measured_entity="sensor.evse3_power")])

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "import_energy" in result["menu_options"] and "copy_select" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "import_energy"})
    offered = [o["value"] for o in result["data_schema"].schema["devices"].config["options"]]
    assert offered == ["sensor.evse1_power", "sensor.evse2_power"]  # evse3 already has a device

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"devices": offered, "kind": "on_off"})
    assert result["step_id"] == "device_details"
    assert suggestion(result, "name") is None and default_of(result, "name") == "EVSE 1"
    assert suggestion(result, "measured_entity") == "sensor.evse1_power"
    base = {"priority": 2, "power_w": 7000, "min_on_s": 0, "min_off_s": 0, "start_margin_w": 0, "stay_tolerance_w": 0}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, "name": "EVSE 1", "entity_id": "switch.evse1", "measured_entity": "sensor.evse1_power"})
    assert result["type"] is FlowResultType.FORM and default_of(result, "name") == "EVSE 2"  # next one, nothing saved yet
    assert len(entry.options["devices"]) == 1
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, "priority": 3, "name": "EVSE 2", "entity_id": "switch.evse2",
                            "measured_entity": "sensor.evse2_power"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    devices = entry.options["devices"]
    assert [d["id"] for d in devices] == ["old", "evse_1", "evse_2"]
    assert [d["measured_entity"] for d in devices[1:]] == ["sensor.evse1_power", "sensor.evse2_power"]


async def test_the_import_menu_is_absent_without_dashboard_devices(hass: HomeAssistant):
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, "0", W)
    entry = await setup(hass, devices=[])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["menu_options"] == ["add_device"]


# ------------------------------------------------------------------ copying a device

async def test_a_device_can_be_copied_and_only_its_entities_change(hass: HomeAssistant):
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, "0", W)
    source = dev(id="evse1", name="EVSE 1", entity_id="switch.evse1", priority=1, power_w=7000, min_on_s=300, min_off_s=120,
                 start_margin_w=200, stay_tolerance_w=100, measured_entity="sensor.evse1_power", done_after_s=90)
    entry = await setup(hass, devices=[source])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "copy_select" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "copy_select"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"device": "evse1"})
    assert result["step_id"] == "device_details"
    assert default_of(result, "name") == "EVSE 1 2" and default_of(result, "priority") == 2  # next free priority
    assert default_of(result, "power_w") == 7000 and default_of(result, "min_on_s") == 300
    assert default_of(result, "done_after_s") == 90  # the settings are copied, not the entities
    assert suggestion(result, "measured_entity") is None  # entities are never copied: they would control the same load

    form = {"name": "EVSE 2", "entity_id": "switch.evse2", "priority": 2, "power_w": 7000, "min_on_s": 300, "min_off_s": 120,
            "start_margin_w": 200, "stay_tolerance_w": 100, "measured_entity": "sensor.evse2_power",
            "done_below_w": 0, "done_after_s": 90}
    result = await hass.config_entries.options.async_configure(result["flow_id"], form)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [d["id"] for d in entry.options["devices"]] == ["evse1", "evse_2"]
    assert entry.options["devices"][1]["entity_id"] == "switch.evse2"


# ------------------------------------------------------------------ off-peak budget in Home Assistant

async def test_the_budget_runs_several_chargers_together_overnight(hass: HomeAssistant):
    loads = {f"c{i}": (f"switch.c{i}", f"sensor.c{i}_power", 7000) for i in (1, 2, 3, 4)}
    sim = Sim(hass, datetime(2026, 11, 10, 23, 0), loads)
    chargers = [dev(id=i, name=i, entity_id=e, priority=n, power_w=7000, measured_entity=s, offpeak="22:30-06:30")
                for n, (i, (e, s, _)) in enumerate(loads.items(), 1)]
    data = {"mode": "export", "export_entity": GRID, "invert": False, "interval_s": 5, "stale_after_s": 60, "on_stale": "off",
            "offpeak_budget_w": 21000}
    p1, p2 = sim.patches()
    with p1, p2:
        entry = await setup(hass, data=data, devices=chargers)
        coord = coordinator(hass, entry)
        await sim.advance(coord, 60)
        assert sim.on == {"c1": True, "c2": True, "c3": True, "c4": False}  # 21 kW budget = three 7 kW chargers

        # without a budget: one at a time
    sim2 = Sim(hass, datetime(2026, 11, 10, 23, 0), loads)
    p1, p2 = sim2.patches()
    with p1, p2:
        await hass.config_entries.async_unload(entry.entry_id)
        entry2 = await setup(hass, devices=chargers)
        await sim2.advance(coordinator(hass, entry2), 60)
        assert sum(sim2.on.values()) == 1


async def test_the_budget_field_is_in_the_setup_form(hass: HomeAssistant):
    result = await entities_step(hass)
    assert default_of(result, "offpeak_budget_w") == 0
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"export_entity": GRID, "invert": True, "interval_s": 5, "stale_after_s": 60, "on_stale": "off",
                            "margin_w": 0, "offpeak_budget_w": 14000})
    assert done["data"]["offpeak_budget_w"] == 14000
