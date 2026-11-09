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
from .core import DeviceKind
from .core.profiles import localized
from .forms import PRESETS, Field, clean_device, clean_site, device_fields, merge_device, site_fields

PANEL_JS = Path(__file__).parent / "frontend" / "panel.js"
VERSION = "0.2.1"


async def async_setup_panel_api(hass: HomeAssistant) -> None:
    """Once per HA run: serve the panel file and register websocket commands."""
    await hass.http.async_register_static_paths([StaticPathConfig(PANEL_STATIC_URL, str(PANEL_JS), cache_headers=False)])
    for handler in (ws_state, ws_reorder, ws_set_device_enabled, ws_set_routing, ws_device_form, ws_device_save,
                    ws_device_remove, ws_settings_form, ws_settings_save):
        websocket_api.async_register_command(hass, handler)


async def async_register_panel(hass: HomeAssistant) -> None:
    if PANEL_URL_PATH in hass.data.get("frontend_panels", {}):
        return  # kept across a reload of the entry, so an open panel does not vanish when settings are saved
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


# ---- adding, editing and removing devices and editing the site settings from the panel ------------------------


async def _translations(hass: HomeAssistant, language: str) -> dict[str, str]:
    """Texts of the integration in ``language``; Home Assistant itself falls back to English for what is missing."""
    from homeassistant.helpers.translation import async_get_translations  # noqa: PLC0415

    merged: dict[str, str] = {}
    for category in ("options", "config", "selector"):
        merged.update(await async_get_translations(hass, language, category, [DOMAIN]))
    return merged


def _serialize(fields: list[Field], translations: dict[str, str], data_prefix: str, desc_prefix: str) -> list[dict[str, Any]]:
    out = []
    for f in fields:
        item = f.as_dict()
        item["label"] = translations.get(f"{data_prefix}.{f.name}") or f.name
        item["description"] = translations.get(f"{desc_prefix}.{f.name}") or ""
        out.append(item)
    return out


_DEVICE_PREFIX = f"component.{DOMAIN}.options.step.device_details"
_SITE_PREFIX = f"component.{DOMAIN}.config.step.entities"
_KINDS = [k.value for k in DeviceKind]


@websocket_api.websocket_command(
    {vol.Required("type"): "solarprio/device_form", vol.Required("kind"): vol.In(_KINDS), vol.Optional("device_id"): str,
     vol.Optional("preset"): vol.In(list(PRESETS)), vol.Optional("language", default="en"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_device_form(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The fields of a device form (with labels in the user's language) and the current values when editing."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_configured(connection, msg)
        return
    values: dict[str, Any] = {}
    if msg.get("device_id"):
        if msg["device_id"] not in coordinator.device_cfgs:
            connection.send_error(msg["id"], "unknown_device", "unknown device")
            return
        values = dict(coordinator.device_cfgs[msg["device_id"]])
    translations = await _translations(hass, msg["language"])
    fields = _serialize(
        device_fields(msg["kind"], len(coordinator.device_cfgs) + 1),
        translations, f"{_DEVICE_PREFIX}.data", f"{_DEVICE_PREFIX}.data_description",
    )
    kinds = {k: translations.get(f"component.{DOMAIN}.selector.device_kind.options.{k}") or k for k in _KINDS}
    if msg.get("preset") and not values:  # a new device that starts from a ready-made set of values
        values = dict(PRESETS[msg["preset"]]["values"])
    presets = [
        {"id": p, "kind": spec["kind"], "label": localized(spec["label"], msg["language"]), "brand": spec["brand"],
         "status": spec["status"], "notes": localized(spec["notes"], msg["language"]) if isinstance(spec["notes"], dict) else spec["notes"]}
        for p, spec in PRESETS.items()
    ]
    connection.send_result(msg["id"], {"fields": fields, "values": values, "kinds": kinds, "presets": presets})


def _warnings(hass: HomeAssistant, device: dict[str, Any]) -> list[str]:
    """Mistakes that are valid but certainly wrong, spotted from the current state of the chosen entities."""
    warnings = []
    entity = device.get("offpeak_entity")
    state = hass.states.get(entity) if entity else None
    if state is not None and not device.get("offpeak_values"):
        try:
            float(state.state)
        except ValueError:
            pass
        else:  # a number is never "HC": it is an index or a price, which only grows or moves
            warnings.append("offpeak_numeric")
    return warnings


@websocket_api.websocket_command(
    {vol.Required("type"): "solarprio/device_save", vol.Required("kind"): vol.In(_KINDS), vol.Optional("device_id"): str,
     vol.Required("values"): dict}
)
@websocket_api.require_admin
@callback
def ws_device_save(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_configured(connection, msg)
        return
    editing = msg.get("device_id")
    if editing is not None and editing not in coordinator.device_cfgs:
        connection.send_error(msg["id"], "unknown_device", "unknown device")
        return
    try:
        device = clean_device(msg["kind"], msg["values"])
    except (ValueError, TypeError, KeyError) as err:
        connection.send_error(msg["id"], "invalid_device", str(err))
        return
    devices = merge_device(list(coordinator.device_cfgs.values()), device, editing)
    _save_devices(hass, coordinator, devices)
    connection.send_result(msg["id"], {"saved": True, "warnings": _warnings(hass, device)})


@websocket_api.websocket_command({vol.Required("type"): "solarprio/device_remove", vol.Required("device_id"): str})
@websocket_api.require_admin
@callback
def ws_device_remove(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Remove a device. The entry reload that follows switches every load of the old configuration off, this one included."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_configured(connection, msg)
        return
    if msg["device_id"] not in coordinator.device_cfgs:
        connection.send_error(msg["id"], "unknown_device", "unknown device")
        return
    devices = [cfg for cfg in coordinator.device_cfgs.values() if cfg["id"] != msg["device_id"]]
    _save_devices(hass, coordinator, devices)
    connection.send_result(msg["id"], {"removed": True})


@websocket_api.websocket_command({vol.Required("type"): "solarprio/settings_form", vol.Optional("language", default="en"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_settings_form(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_configured(connection, msg)
        return
    translations = await _translations(hass, msg["language"])
    # the mode label lives in the first setup step
    translations.setdefault(f"{_SITE_PREFIX}.data.mode", translations.get(f"component.{DOMAIN}.config.step.user.data.mode", "mode"))
    fields = _serialize(site_fields(), translations, f"{_SITE_PREFIX}.data", f"{_SITE_PREFIX}.data_description")
    defaults = {f.name: f.default for f in site_fields() if f.default is not None}
    connection.send_result(msg["id"], {"fields": fields, "values": {**defaults, **coordinator.config_entry.data}})


@websocket_api.websocket_command({vol.Required("type"): "solarprio/settings_save", vol.Required("values"): dict})
@websocket_api.require_admin
@callback
def ws_settings_save(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_configured(connection, msg)
        return
    try:
        data = clean_site(msg["values"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_settings", str(err))  # the message is the offending field
        return
    entry = coordinator.config_entry
    hass.config_entries.async_update_entry(entry, data=data)  # the update listener reloads the entry
    connection.send_result(msg["id"], {"saved": True})
