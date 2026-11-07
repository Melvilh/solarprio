from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.solarprio.const import DOMAIN, PANEL_STATIC_URL, PANEL_URL_PATH

from .test_integration import DEVICES, GRID, coordinator, dev, setup


async def ws(client, **msg):
    await client.send_json({"id": ws.n, **msg})
    ws.n += 1
    return await client.receive_json()


ws.n = 1


async def prepare(hass: HomeAssistant, devices=None, grid="2300"):
    set_value = async_mock_service(hass, "number", "set_value")
    turn_on = async_mock_service(hass, "homeassistant", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(GRID, grid, {"unit_of_measurement": "W"})
    entry = await setup(hass, devices=devices)
    return entry, set_value, turn_on, turn_off


async def test_panel_is_registered_and_removed(hass: HomeAssistant):
    entry, *_ = await prepare(hass)
    panels = hass.data["frontend_panels"]
    assert PANEL_URL_PATH in panels
    assert panels[PANEL_URL_PATH].require_admin is True
    assert panels[PANEL_URL_PATH].config["_panel_custom"]["name"] == "solarprio-panel"
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH in hass.data["frontend_panels"]  # a reload keeps the panel (an open page must not vanish)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH not in hass.data["frontend_panels"]


async def test_panel_js_is_served(hass: HomeAssistant, hass_client):
    await prepare(hass)
    client = await hass_client()
    resp = await client.get(PANEL_STATIC_URL)
    assert resp.status == 200
    assert "solarprio-panel" in await resp.text()


async def test_state_lists_devices_by_priority(hass: HomeAssistant, hass_ws_client):
    await prepare(hass)
    client = await hass_ws_client(hass)
    resp = await ws(client, type="solarprio/state")
    assert resp["success"]
    result = resp["result"]
    assert [d["id"] for d in result["devices"]] == ["dimmer", "pump"]
    assert result["devices"][0]["cmd_w"] == 2000.0  # 2300 W surplus: dimmer at max
    assert result["available_w"] == 2300.0 and result["routing_enabled"] is True


async def test_reorder_changes_priority_live_without_reload(hass: HomeAssistant, hass_ws_client):
    # 1000 W export: dimmer (priority 1) takes it all (50 %), pump (800 W) gets nothing
    entry, set_value, turn_on, turn_off = await prepare(hass, grid="1000")
    assert set_value[-1].data["value"] == 50.0
    coord = coordinator(hass, entry)
    client = await hass_ws_client(hass)
    offs_before = len(turn_off)  # at startup the pump got an initial "off" (not enough surplus)

    resp = await ws(client, type="solarprio/reorder", ids=["pump", "dimmer"])
    await hass.async_block_till_done()
    assert resp["success"]
    assert [d["id"] for d in resp["result"]["devices"]] == ["pump", "dimmer"]
    assert [d["priority"] for d in entry.options["devices"] if d["id"] == "pump"] == [1]
    assert coordinator(hass, entry) is coord  # same coordinator: entry was not reloaded
    assert len(turn_off) == offs_before  # the reorder switched nothing off

    # available = 1000 export + 1000 already routed = 2000 W: pump first (800 W), dimmer gets 1200 W = 60 %
    assert [c.data["entity_id"] for c in turn_on] == ["switch.pump"]
    assert set_value[-1].data == {"entity_id": "number.dimmer", "value": 60.0}


async def test_reorder_rejects_unknown_or_partial_lists(hass: HomeAssistant, hass_ws_client):
    await prepare(hass)
    client = await hass_ws_client(hass)
    for ids in (["pump"], ["pump", "dimmer", "ghost"], ["pump", "pump"]):
        resp = await ws(client, type="solarprio/reorder", ids=ids)
        assert not resp["success"] and resp["error"]["code"] == "invalid_order"


async def test_device_enabled_toggle_switches_it_off(hass: HomeAssistant, hass_ws_client):
    entry, set_value, turn_on, turn_off = await prepare(hass, devices=[dev(id="pump", name="Pump", entity_id="switch.pump", power_w=800)])
    client = await hass_ws_client(hass)
    assert [c.data["entity_id"] for c in turn_on] == ["switch.pump"]
    resp = await ws(client, type="solarprio/set_device_enabled", device_id="pump", enabled=False)
    await hass.async_block_till_done()
    assert resp["success"] and resp["result"]["devices"][0]["enabled"] is False
    assert [c.data["entity_id"] for c in turn_off] == ["switch.pump"]
    resp = await ws(client, type="solarprio/set_device_enabled", device_id="ghost", enabled=True)
    assert resp["error"]["code"] == "unknown_device"


async def test_set_routing_from_panel(hass: HomeAssistant, hass_ws_client):
    await prepare(hass)
    client = await hass_ws_client(hass)
    resp = await ws(client, type="solarprio/set_routing", enabled=False)
    assert resp["result"]["routing_enabled"] is False and resp["result"]["status"] == "disabled"


async def test_all_commands_require_admin(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    await prepare(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for msg in (
        {"type": "solarprio/state"},
        {"type": "solarprio/reorder", "ids": ["pump", "dimmer"]},
        {"type": "solarprio/set_routing", "enabled": False},
        {"type": "solarprio/set_device_enabled", "device_id": "pump", "enabled": False},
        {"type": "solarprio/device_form", "kind": "on_off"},
        {"type": "solarprio/device_save", "kind": "on_off", "values": {}},
        {"type": "solarprio/device_remove", "device_id": "pump"},
        {"type": "solarprio/settings_form"},
        {"type": "solarprio/settings_save", "values": {}},
    ):
        resp = await ws(client, **msg)
        assert not resp["success"] and resp["error"]["code"] == "unauthorized"


async def test_state_when_not_configured(hass: HomeAssistant, hass_ws_client):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    resp = await ws(client, type="solarprio/state")
    assert resp["error"]["code"] == "not_configured"


async def test_panel_is_removed_when_the_entry_is_disabled(hass: HomeAssistant):
    from homeassistant.config_entries import ConfigEntryDisabler

    entry, *_ = await prepare(hass)
    await hass.config_entries.async_set_disabled_by(entry.entry_id, ConfigEntryDisabler.USER)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH not in hass.data["frontend_panels"]
    await hass.config_entries.async_set_disabled_by(entry.entry_id, None)  # and comes back when enabled again
    await hass.async_block_till_done()
    assert PANEL_URL_PATH in hass.data["frontend_panels"]


async def test_a_lost_measurement_says_which_sensor_and_why(hass: HomeAssistant, hass_ws_client):
    await prepare(hass)
    client = await hass_ws_client(hass)
    hass.states.async_set(GRID, "unavailable")
    await coordinator(hass, hass.config_entries.async_entries(DOMAIN)[0]).async_refresh()
    result = (await ws(client, type="solarprio/state"))["result"]
    assert result["status"] == "measurement_lost_off"
    assert result["detail"] == f"{GRID} is unavailable"
    hass.states.async_set(GRID, "500", {"unit_of_measurement": "W"})
    await coordinator(hass, hass.config_entries.async_entries(DOMAIN)[0]).async_refresh()
    result = (await ws(client, type="solarprio/state"))["result"]
    assert result["status"] == "routing" and result["detail"] is None
