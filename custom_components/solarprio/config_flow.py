"""Config flow (measurement source) and options flow (devices and their priority)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CONSUMPTION_ENTITY,
    CONF_DEVICES,
    CONF_EXPORT_ENTITY,
    CONF_INTERVAL,
    CONF_INVERT,
    CONF_MARGIN,
    CONF_MODE,
    CONF_OFFPEAK_BUDGET,
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
from .core import DeviceKind
from .energy import EnergyDashboard, async_read_energy_dashboard
from .forms import clean_device, device_fields, merge_device

SENSOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


def _select(options: list[str]) -> selector.SelectSelector:
    return selector.SelectSelector(selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN))


def _number(unit: str | None = None, minimum: float = 0, maximum: float = 1_000_000) -> selector.NumberSelector:
    config: dict[str, Any] = {"min": minimum, "max": maximum, "step": "any", "mode": selector.NumberSelectorMode.BOX}
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


def _entity(domains: list[str]) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domains))


def _suggest(entity_id: str | None) -> dict[str, Any] | None:
    return {"suggested_value": entity_id} if entity_id else None


def _details_schema(kind: str, values: dict[str, Any], next_priority: int) -> vol.Schema:
    """The form of one device type, built from the shared field specification (forms.py).

    Optional entities and texts use suggested values so they can be cleared.
    """
    schema: dict[Any, Any] = {}
    for f in device_fields(kind, next_priority):
        if f.required:
            fallback = f.default if f.default is not None else vol.UNDEFINED
            marker: Any = vol.Required(f.name, default=values.get(f.name, fallback))
        else:
            marker = vol.Optional(f.name, description=_suggest(values.get(f.name)))
        if f.type == "entity":
            schema[marker] = _entity(list(f.domains))
        elif f.type == "number":
            schema[marker] = _number(f.unit, f.min if f.min is not None else 0, f.max if f.max is not None else 1_000_000)
        elif f.type == "select":
            schema[marker] = _select(list(f.options))
        elif f.type == "boolean":
            schema[marker] = selector.BooleanSelector()
        else:
            schema[marker] = str
    return vol.Schema(schema)


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
        energy = await async_read_energy_dashboard(self.hass)
        # The Energy dashboard counts power drawn from the grid as positive, so its grid sensor needs "invert".
        # The dashboard has no whole-house consumption, so the consumption sensor is never pre-filled.
        fields: dict[Any, Any] = (
            {
                vol.Required(CONF_EXPORT_ENTITY, description=_suggest(energy.grid_power)): SENSOR,
                vol.Required(CONF_INVERT, default=energy.grid_power is not None): selector.BooleanSelector(),
            }
            if export
            else {
                vol.Required(CONF_PRODUCTION_ENTITY, description=_suggest(energy.solar_power)): SENSOR,
                vol.Required(CONF_CONSUMPTION_ENTITY): SENSOR,
            }
        )
        fields.update(
            {
                vol.Required(CONF_INTERVAL, default=DEFAULT_INTERVAL): _number("s", 1, 300),
                vol.Required(CONF_STALE_AFTER, default=DEFAULT_STALE_AFTER): _number("s", 5, 3600),
                vol.Required(CONF_ON_STALE, default=ON_STALE_OFF): _select([ON_STALE_OFF, ON_STALE_HOLD]),
                vol.Required(CONF_MARGIN, default=0): _number("W", 0, 2000),
                vol.Required(CONF_OFFPEAK_BUDGET, default=0): _number("W", 0, 1_000_000),
            }
        )
        return self.async_show_form(
            step_id="entities",
            data_schema=vol.Schema(fields),
            description_placeholders={
                "grid": energy.grid_power or ("-" if energy.grid_sensors == 0 else str(energy.grid_sensors)),
                "solar": energy.solar_power or "-",
            },
        )


COPY_NOT_KEPT = ("id", "name", "entity_id", "switch_entity", "soc_entity", "connected_entity", "measured_entity", "priority", "enabled")


class SolarPrioOptionsFlow(OptionsFlow):
    """Menu to add, edit and remove devices. Priority = number, lower is served first."""

    def __init__(self) -> None:
        self._editing: str | None = None
        self._kind: str = DeviceKind.ON_OFF.value
        self._prefill: dict[str, Any] = {}  # suggested values of a new device (copy, Energy dashboard import)
        self._queue: list[tuple[str, str]] = []  # Energy dashboard devices still to configure
        self._working: list[dict[str, Any]] | None = None  # devices added so far during an import

    @property
    def _devices(self) -> list[dict[str, Any]]:
        if self._working is not None:
            return self._working
        return list(self.config_entry.options.get(CONF_DEVICES, []))

    def _save(self, devices: list[dict[str, Any]]) -> ConfigFlowResult:
        return self.async_create_entry(data={CONF_DEVICES: devices})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["add_device"]
        if await self._importable():
            menu.append("import_energy")
        if self._devices:
            menu += ["copy_select", "edit_select", "remove_device"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    # ---- import from the Energy dashboard / copy ----

    async def _importable(self) -> list[tuple[str, str]]:
        """Devices of the Energy dashboard with a power sensor that no solarprio device uses yet."""
        used = {d.get("measured_entity") for d in self._devices}
        energy = await async_read_energy_dashboard(self.hass)
        return [(name, sensor) for name, sensor in energy.devices if sensor not in used]

    async def async_step_import_energy(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick devices already tracked in the Energy dashboard: their name and power sensor are reused."""
        available = await self._importable()
        names = dict((sensor, name) for name, sensor in available)
        if user_input is not None and user_input["devices"]:
            self._kind, self._editing = user_input["kind"], None
            self._queue = [(names[s], s) for s in user_input["devices"] if s in names]
            self._working = list(self._devices)
            return await self._next_import()
        options = [selector.SelectOptionDict(value=s, label=f"{n} ({s})") for n, s in available]
        return self.async_show_form(
            step_id="import_energy",
            data_schema=vol.Schema(
                {
                    vol.Required("devices"): selector.SelectSelector(selector.SelectSelectorConfig(options=options, multiple=True)),
                    vol.Required("kind", default=DeviceKind.ON_OFF.value): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[k.value for k in DeviceKind if k not in (DeviceKind.BATTERY, DeviceKind.TASK)],
                            translation_key="device_kind",
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def _next_import(self) -> ConfigFlowResult:
        name, sensor = self._queue.pop(0)
        self._prefill = {"name": name, "measured_entity": sensor}
        return await self._details_form(None)

    async def async_step_copy_select(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """New device pre-filled with the settings of an existing one (only entities and name to change)."""
        if user_input is not None:
            source = next(d for d in self._devices if d["id"] == user_input["device"])
            self._editing, self._kind, self._working, self._queue = None, source["kind"], None, []
            self._prefill = {k: v for k, v in source.items() if k not in COPY_NOT_KEPT} | {"name": f"{source['name']} 2"}
            return await self._details_form(None)
        options = [selector.SelectOptionDict(value=d["id"], label=f"{d['priority']}. {d['name']}") for d in sorted(self._devices, key=lambda d: d["priority"])]
        return self.async_show_form(
            step_id="copy_select",
            data_schema=vol.Schema({vol.Required("device"): selector.SelectSelector(selector.SelectSelectorConfig(options=options))}),
        )

    # ---- add / edit ----

    async def async_step_add_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """First step of an addition: pick the type, then fill the form specific to it."""
        self._editing = None
        if user_input is not None:
            self._kind = user_input["kind"]
            return await self._details_form(None)
        return self.async_show_form(
            step_id="add_device",
            data_schema=vol.Schema(
                {
                    vol.Required("kind", default=DeviceKind.ON_OFF.value): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[k.value for k in DeviceKind], translation_key="device_kind", mode=selector.SelectSelectorMode.LIST
                        )
                    )
                }
            ),
        )

    async def async_step_edit_select(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._editing = user_input["device"]
            self._kind = next(d for d in self._devices if d["id"] == self._editing)["kind"]
            return await self._details_form(None)
        options = [selector.SelectOptionDict(value=d["id"], label=f"{d['priority']}. {d['name']}") for d in sorted(self._devices, key=lambda d: d["priority"])]
        return self.async_show_form(
            step_id="edit_select",
            data_schema=vol.Schema({vol.Required("device"): selector.SelectSelector(selector.SelectSelectorConfig(options=options))}),
        )

    async def async_step_device_details(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._details_form(user_input)

    async def _details_form(self, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = next((d for d in self._devices if d["id"] == self._editing), {})

        if user_input is not None:
            try:
                device = self._clean(user_input)
            except (ValueError, TypeError):
                errors["base"] = "invalid_device"
            else:
                merged = self._merge(device)
                if self._queue:  # more devices to import: keep what we have and show the next form
                    self._working = merged
                    return await self._next_import()
                return self._save(merged)

        values = user_input or current or self._prefill
        return self.async_show_form(
            step_id="device_details",
            data_schema=_details_schema(self._kind, values, len(self._devices) + 1),
            errors=errors,
            description_placeholders={"kind": self._kind},
        )

    def _clean(self, user_input: dict[str, Any]) -> dict[str, Any]:
        return clean_device(self._kind, user_input)

    def _merge(self, user_input: dict[str, Any]) -> list[dict[str, Any]]:
        return merge_device(self._devices, user_input, self._editing)

    # ---- remove ----

    async def async_step_remove_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._save([d for d in self._devices if d["id"] not in user_input["devices"]])
        options = [selector.SelectOptionDict(value=d["id"], label=d["name"]) for d in self._devices]
        return self.async_show_form(
            step_id="remove_device",
            data_schema=vol.Schema({vol.Required("devices"): selector.SelectSelector(selector.SelectSelectorConfig(options=options, multiple=True))}),
        )
