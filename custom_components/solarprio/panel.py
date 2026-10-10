"""Sidebar panel (drag-and-drop priorities): static file, panel registration and websocket API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from .const import CONF_DEVICES, DOMAIN, PANEL_STATIC_URL, PANEL_URL_PATH
from .coordinator import SolarPrioCoordinator

PANEL_JS = Path(__file__).parent / "frontend" / "panel.js"
VERSION = "0.1.0"


async def async_setup_panel_api(hass: HomeAssistant) -> None:
    """Once per HA run: serve the panel file and register websocket commands."""
    await hass.http.async_register_static_paths([StaticPathConfig(PANEL_STATIC_URL, str(PANEL_JS), cache_headers=False)])
    for handler in (ws_state, ws_reorder, ws_set_device_enabled, ws_set_routing):
        websocket_api.async_register_command(hass, handler)


async def async_register_panel(hass: HomeAssistant) -> None:
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name="solarprio-panel",
        sidebar_title="solarprio",
        sidebar_icon="mdi:solar-power",
        module_url=f"{PANEL_STATIC_URL}?v={VERSION}",
        require_admin=True,
    )


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)


def _coordinator(hass: HomeAssistant) -> SolarPrioCoordinator | None:
    return next(iter(hass.data.get(DOMAIN, {}).values()), None)


def _save_devices(hass: HomeAssistant, coordinator: SolarPrioCoordinator, devices: list[dict[str, Any]]) -> None:
    entry = coordinator.config_entry
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_DEVICES: devices})


def _not_configured(connection, msg) -> None:
    connection.send_error(msg["id"], "not_configured", "solarprio is not set up")


@websocket_api.websocket_command({vol.Required("type"): "solarprio/state"})
@websocket_api.require_admin
@callback
def ws_state(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_configured(connection, msg)
        return
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command({vol.Required("type"): "solarprio/reorder", vol.Required("ids"): [str]})
@websocket_api.require_admin
@callback
def ws_reorder(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_configured(connection, msg)
        return
    ids = msg["ids"]
    if sorted(ids) != sorted(coordinator.device_cfgs):
        connection.send_error(msg["id"], "invalid_order", "ids must list every device exactly once")
        return
    order = {device_id: position for position, device_id in enumerate(ids, start=1)}
    devices = [{**cfg, "priority": order[cfg["id"]]} for cfg in coordinator.device_cfgs.values()]
    _save_devices(hass, coordinator, devices)
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command(
    {vol.Required("type"): "solarprio/set_device_enabled", vol.Required("device_id"): str, vol.Required("enabled"): bool}
)
@websocket_api.require_admin
@callback
def ws_set_device_enabled(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_configured(connection, msg)
        return
    if msg["device_id"] not in coordinator.device_cfgs:
        connection.send_error(msg["id"], "unknown_device", "unknown device")
        return
    devices = [
        {**cfg, "enabled": msg["enabled"]} if cfg["id"] == msg["device_id"] else cfg for cfg in coordinator.device_cfgs.values()
    ]
    _save_devices(hass, coordinator, devices)
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command({vol.Required("type"): "solarprio/set_routing", vol.Required("enabled"): bool})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_routing(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_configured(connection, msg)
        return
    await coordinator.async_set_enabled(msg["enabled"])
    connection.send_result(msg["id"], coordinator.snapshot())
