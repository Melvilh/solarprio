"""The task category in Home Assistant: a "go" signal on a helper, never a switch that could cut a power supply."""
from datetime import datetime

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.solarprio.config_flow import _details_schema
from custom_components.solarprio.const import DOMAIN
from custom_components.solarprio.forms import clean_device, device_fields

from .test_integration import GRID, _add_device, coordinator, dev, setup
from .test_offpeak import Sim
from .test_panel import prepare, ws

GO = "input_boolean.go_heavy_tasks"
TASK = dict(name="Heavy tasks", entity_id=GO, priority=1, power_w=100, min_on_s=0, min_off_s=0, start_margin_w=0, stay_tolerance_w=0)
W = {"unit_of_measurement": "W"}


def test_the_task_form_offers_only_helpers_and_nothing_to_measure():
    fields = {f.name: f for f in device_fields("task")}
    assert fields["entity_id"].domains == ("input_boolean",)
    assert list(fields) == ["name", "entity_id", "priority", "power_w", "offpeak_entity", "offpeak", "offpeak_extra", "offpeak_values",
                            "min_on_s", "min_off_s", "start_margin_w", "stay_tolerance_w"]
    assert not {"measured_entity", "reset_at", "done_below_w", "done_after_s"} & set(fields)


@pytest.mark.parametrize("entity", ["switch.prise_serveur", "light.lamp", "number.x", "sensor.power", "input_boolean_x", "switch.nas"])
def test_a_task_can_never_target_a_physical_switch_or_anything_but_a_helper(entity):
    with pytest.raises(ValueError, match="input_boolean"):
        clean_device("task", {**TASK, "entity_id": entity})
    assert clean_device("task", TASK)["entity_id"] == GO


def test_a_task_needs_no_measured_power_for_off_peak():
    assert clean_device("task", {**TASK, "offpeak": "22:30-06:30"})["offpeak"] == "22:30-06:30"
    assert clean_device("task", {**TASK, "offpeak_entity": "sensor.linky_periode_tarifaire"})
    with pytest.raises(ValueError):  # a heater still needs one
        clean_device("on_off", {**TASK, "entity_id": "switch.heater", "offpeak": "22:30-06:30"})


async def test_the_panel_and_the_options_flow_show_the_same_task_fields(hass: HomeAssistant, hass_ws_client):
    await prepare(hass)
    client = await hass_ws_client(hass)
    resp = await ws(client, type="solarprio/device_form", kind="task", language="fr")
    assert [f["name"] for f in resp["result"]["fields"]] == [str(k) for k in _details_schema("task", {}, 1).schema]
    assert "task" in resp["result"]["kinds"] and "jamais" in resp["result"]["kinds"]["task"]


async def test_no_label_suggests_a_server_as_an_on_off_load_and_the_warning_is_there(hass: HomeAssistant):
    for language in ("en", "fr"):
        texts = await async_get_translations(hass, language, "selector", [DOMAIN])
        label = texts[f"component.{DOMAIN}.selector.device_kind.options.on_off"].lower()
        assert "serv" not in label and "nas" not in label, label
        options = await async_get_translations(hass, language, "options", [DOMAIN])
        help_text = options[f"component.{DOMAIN}.options.step.device_details.data_description.entity_id"].lower()
        assert "input_boolean" in help_text and ("server" in help_text or "serveur" in help_text)  # the warning


async def test_a_task_signals_go_with_the_sun_on_a_helper(hass: HomeAssistant):
    turn_on = async_mock_service(hass, "homeassistant", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, "0", W)
    entry = await setup(hass, devices=[dev(**{**TASK, "id": "ia", "kind": "task"})])
    coord = coordinator(hass, entry)
    assert [c.data["entity_id"] for c in turn_off] == [GO] and not turn_on  # no surplus: stop signal
    hass.states.async_set(GRID, "400", W)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in turn_on] == [GO]  # surplus: go
    assert all(c.domain == "homeassistant" for c in turn_on + turn_off)  # only the generic on/off service on the helper


async def test_a_task_is_on_during_off_peak_even_without_the_sun(hass: HomeAssistant):
    loads = {"ia": (GO, "sensor.unused_power", 100)}
    sim = Sim(hass, datetime(2026, 11, 10, 12, 0), loads)
    sim.on = {"ia": False}
    p1, p2 = sim.patches()
    task = dev(**{**TASK, "id": "ia", "kind": "task", "offpeak_entity": "sensor.linky_periode_tarifaire"})
    with p1, p2:
        hass.states.async_set("sensor.linky_periode_tarifaire", "HP..")
        coord = coordinator(hass, await setup(hass, devices=[task]))
        await sim.advance(coord, 60)
        assert not sim.on["ia"]
        hass.states.async_set("sensor.linky_periode_tarifaire", "HC..")
        await sim.advance(coord, 60)
        assert sim.on["ia"] and coord.snapshot()["devices"][0]["offpeak"] == "heating"
        hass.states.async_set("sensor.linky_periode_tarifaire", "HP..")
        await sim.advance(coord, 60)
        assert not sim.on["ia"]


async def test_the_add_flow_offers_the_task_category_but_the_energy_import_does_not(hass: HomeAssistant):
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, "0", W)
    entry = await setup(hass, devices=[])
    result = await _add_device(hass, entry, "task", {**TASK})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (saved,) = entry.options["devices"]
    assert saved["kind"] == "task" and saved["entity_id"] == GO

    with pytest.raises(InvalidData) as refused:  # Home Assistant's own selector already refuses a switch
        await _add_device(hass, entry, "task", {**TASK, "name": "Bad", "entity_id": "switch.prise_serveur"})
    assert "input_boolean" in str(refused.value.schema_errors)
    assert len(entry.options["devices"]) == 1
