"""Config flow (measurement source) and options flow (devices and their priority)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_CONSUMPTION_ENTITY,
    CONF_DEVICES,
    CONF_EXPORT_ENTITY,
    CONF_INTERVAL,
    CONF_INVERT,
    CONF_MODE,
    CONF_ON_STALE,
    CONF_PRODUCTION_ENTITY,
    CONF_STALE_AFTER,
    DEFAULT_INTERVAL,
    DEFAULT_STALE_AFTER,
    DOMAIN,
    MODE_EXPORT,
    MODE_PRODUCTION,
    ON_STALE_HOLD,
    ON_STALE_OFF,
)
from .core import Device, DeviceKind

SENSOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


def _select(options: list[str]) -> selector.SelectSelector:
    return selector.SelectSelector(selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN))


def _number(unit: str | None = None, minimum: float = 0, maximum: float = 1_000_000) -> selector.NumberSelector:
    config: dict[str, Any] = {"min": minimum, "max": maximum, "step": "any", "mode": selector.NumberSelectorMode.BOX}
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


class SolarPrioConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SolarPrioOptionsFlow:
        return SolarPrioOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_entities()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_MODE, default=MODE_EXPORT): _select([MODE_EXPORT, MODE_PRODUCTION])}),
        )

    async def async_step_entities(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        export = self._data[CONF_MODE] == MODE_EXPORT
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="solarprio", data=self._data, options={CONF_DEVICES: []})
        fields: dict[Any, Any] = (
            {vol.Required(CONF_EXPORT_ENTITY): SENSOR, vol.Required(CONF_INVERT, default=False): selector.BooleanSelector()}
            if export
            else {vol.Required(CONF_PRODUCTION_ENTITY): SENSOR, vol.Required(CONF_CONSUMPTION_ENTITY): SENSOR}
        )
        fields.update(
            {
                vol.Required(CONF_INTERVAL, default=DEFAULT_INTERVAL): _number("s", 1, 300),
                vol.Required(CONF_STALE_AFTER, default=DEFAULT_STALE_AFTER): _number("s", 5, 3600),
                vol.Required(CONF_ON_STALE, default=ON_STALE_OFF): _select([ON_STALE_OFF, ON_STALE_HOLD]),
            }
        )
        return self.async_show_form(step_id="entities", data_schema=vol.Schema(fields))


class SolarPrioOptionsFlow(OptionsFlow):
    """Menu to add, edit and remove devices. Priority = number, lower is served first."""

    def __init__(self) -> None:
        self._editing: str | None = None

    @property
    def _devices(self) -> list[dict[str, Any]]:
        return list(self.config_entry.options.get(CONF_DEVICES, []))

    def _save(self, devices: list[dict[str, Any]]) -> ConfigFlowResult:
        return self.async_create_entry(data={CONF_DEVICES: devices})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["add_device"]
        if self._devices:
            menu += ["edit_select", "remove_device"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    # ---- add / edit ----

    async def async_step_add_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._editing = None
        return await self._device_form("add_device", user_input)

    async def async_step_edit_select(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._editing = user_input["device"]
            return await self._device_form("edit_device", None)
        options = [selector.SelectOptionDict(value=d["id"], label=f"{d['priority']}. {d['name']}") for d in sorted(self._devices, key=lambda d: d["priority"])]
        return self.async_show_form(
            step_id="edit_select",
            data_schema=vol.Schema({vol.Required("device"): selector.SelectSelector(selector.SelectSelectorConfig(options=options))}),
        )

    async def async_step_edit_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._device_form("edit_device", user_input)

    async def _device_form(self, step_id: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = next((d for d in self._devices if d["id"] == self._editing), {})

        if user_input is not None:
            try:
                Device(
                    id="x", name=user_input["name"], priority=int(user_input["priority"]), kind=DeviceKind(user_input["kind"]),
                    power_w=float(user_input["power_w"]), min_power_w=float(user_input.get("min_power_w", 0)),
                )
            except ValueError:
                errors["base"] = "invalid_device"
            else:
                return self._save(self._merge(user_input))

        def default(key: str, fallback: Any) -> Any:
            return (user_input or current).get(key, fallback)

        schema = vol.Schema(
            {
                vol.Required("name", default=default("name", "")): str,
                vol.Required("entity_id", default=default("entity_id", vol.UNDEFINED)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "input_boolean", "light", "number", "input_number"])
                ),
                vol.Required("kind", default=default("kind", DeviceKind.ON_OFF.value)): _select([k.value for k in DeviceKind]),
                vol.Required("priority", default=default("priority", len(self._devices) + 1)): _number(None, 1, 999),
                vol.Required("power_w", default=default("power_w", vol.UNDEFINED)): _number("W", 1),
                vol.Required("min_power_w", default=default("min_power_w", 0)): _number("W"),
                vol.Required("scale", default=default("scale", "percent")): _select(["percent", "watts"]),
                vol.Required("min_on_s", default=default("min_on_s", 0)): _number("s"),
                vol.Required("min_off_s", default=default("min_off_s", 0)): _number("s"),
                vol.Required("start_margin_w", default=default("start_margin_w", 0)): _number("W"),
                vol.Required("stay_tolerance_w", default=default("stay_tolerance_w", 0)): _number("W"),
            }
        )
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    def _merge(self, user_input: dict[str, Any]) -> list[dict[str, Any]]:
        devices = self._devices
        device = {**user_input, "priority": int(user_input["priority"]), "enabled": True}
        if self._editing is None:
            taken = {d["id"] for d in devices}
            base = slugify(device["name"]) or "device"
            device_id, n = base, 2
            while device_id in taken:
                device_id, n = f"{base}_{n}", n + 1
            device["id"] = device_id
            devices.append(device)
        else:
            device["id"] = self._editing
            devices = [device if d["id"] == self._editing else d for d in devices]
        return devices

    # ---- remove ----

    async def async_step_remove_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._save([d for d in self._devices if d["id"] not in user_input["devices"]])
        options = [selector.SelectOptionDict(value=d["id"], label=d["name"]) for d in self._devices]
        return self.async_show_form(
            step_id="remove_device",
            data_schema=vol.Schema({vol.Required("devices"): selector.SelectSelector(selector.SelectSelectorConfig(options=options, multiple=True))}),
        )
