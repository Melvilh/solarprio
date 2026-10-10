"""Unchanged commands are re-sent periodically: a device with a watchdog (an ESPHome router that drops to 0 W
when it stops hearing from us) must keep receiving its order even when the setpoint is steady."""
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.solarprio.const import RESEND_EVERY_S

from .test_integration import GRID, _add_device, coordinator, dev, setup

ROUTER = dev(id="heater", name="Water heater", kind="proportional", entity_id="number.heater_setpoint_w",
             priority=1, power_w=2400, min_power_w=100, scale="watts", measured_entity="sensor.heater_power")


async def test_unchanged_command_is_resent_every_30_seconds(hass: HomeAssistant):
    set_value = async_mock_service(hass, "number", "set_value")
    clock = [1000.0]
    with patch("custom_components.solarprio.coordinator.time", SimpleNamespace(monotonic=lambda: clock[0])):
        hass.states.async_set(GRID, "1500", {"unit_of_measurement": "W"})
        hass.states.async_set("sensor.heater_power", "0", {"unit_of_measurement": "W"})
        entry = await setup(hass, devices=[ROUTER])
        coord = coordinator(hass, entry)
        assert [c.data["value"] for c in set_value] == [1500.0]  # watts, as configured

        clock[0] += RESEND_EVERY_S - 1
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert len(set_value) == 1  # steady setpoint, not yet time

        clock[0] += 2  # 31 s since the last send
        # the router did what it was told: it draws 1500 W, so the export measured at the meter falls to zero
        hass.states.async_set("sensor.heater_power", "1500", {"unit_of_measurement": "W"})
        hass.states.async_set(GRID, "0", {"unit_of_measurement": "W"})
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert [c.data["value"] for c in set_value] == [1500.0, 1500.0]  # heartbeat: same value again

        clock[0] += 5
        hass.states.async_set(GRID, "500", {"unit_of_measurement": "W"})  # a real change is still sent immediately
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert set_value[-1].data["value"] == 2000.0  # 500 W export + 1500 W already routed
        assert len(set_value) == 3


async def test_a_failed_send_is_retried_and_not_counted_as_routed(hass: HomeAssistant):
    calls, failing = [], {"on": True}

    async def set_value(call):
        if failing["on"]:
            raise RuntimeError("router unreachable")
        calls.append(call.data["value"])

    hass.services.async_register("number", "set_value", set_value)
    clock = [50.0]
    with patch("custom_components.solarprio.coordinator.time", SimpleNamespace(monotonic=lambda: clock[0])):
        hass.states.async_set(GRID, "1000", {"unit_of_measurement": "W"})
        entry = await setup(hass, devices=[{**ROUTER, "measured_entity": None}])
        coord = coordinator(hass, entry)
        assert coord.engine.routed_w == 0  # nothing reached the router

        failing["on"] = False
        clock[0] += 5  # well before the heartbeat interval: the failed command is retried anyway
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert calls == [1000.0]


async def test_proportional_form_offers_the_measured_power_entity(hass: HomeAssistant):
    async_mock_service(hass, "number", "set_value")
    hass.states.async_set(GRID, "0", {"unit_of_measurement": "W"})
    entry = await setup(hass, devices=[])
    form = {"name": "Router", "entity_id": "number.heater_setpoint_w", "priority": 1, "power_w": 2400, "min_power_w": 100,
            "scale": "watts", "measured_entity": "sensor.heater_power", "min_on_s": 0, "min_off_s": 0}
    result = await _add_device(hass, entry, "proportional", form)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["devices"][0]["measured_entity"] == "sensor.heater_power"
