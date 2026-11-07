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
from .coordinator import DEVICE_FIELDS, build_device
from .core import DeviceKind
from .energy import EnergyDashboard, async_read_energy_dashboard

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
    """Form fields for one device type. Optional entities use suggested values so they can be cleared."""

    def default(key: str, fallback: Any) -> Any:
        return values.get(key, fallback)

    def required(key: str, fallback: Any) -> vol.Required:
        return vol.Required(key, default=default(key, fallback))

    def optional(key: str) -> vol.Optional:
        suggested = values.get(key)
        return vol.Optional(key, description={"suggested_value": suggested} if suggested else None)

    fields: dict[Any, Any] = {required("name", ""): str}

    if kind == DeviceKind.EV_CHARGER.value:
        fields[required("entity_id", vol.UNDEFINED)] = _entity(["number", "input_number"])  # charging current, A
        fields[optional("switch_entity")] = _entity(["switch", "input_boolean"])
        fields[required("priority", next_priority)] = _number(None, 1, 999)
        fields[required("phases", "1")] = _select(["1", "3"])
        fields[required("voltage_v", 230)] = _number("V", 100, 480)
        fields[required("min_current_a", 6)] = _number("A", 1, 80)
        fields[required("max_current_a", 16)] = _number("A", 1, 80)
        fields[required("current_step_a", 1)] = _number("A", 0.1, 10)
        fields[optional("connected_entity")] = _entity(["binary_sensor", "sensor", "switch", "input_boolean"])
        fields[optional("soc_entity")] = _entity(["sensor", "number", "input_number"])
        fields[required("soc_max", 100)] = _number("%", 1, 100)
        fields[optional("measured_entity")] = _entity(["sensor"])
    elif kind == DeviceKind.BATTERY.value:
        fields[required("entity_id", vol.UNDEFINED)] = _entity(["number", "input_number"])  # charge setpoint
        fields[required("priority", next_priority)] = _number(None, 1, 999)
        fields[required("power_w", vol.UNDEFINED)] = _number("W", 1)
        fields[required("min_power_w", 0)] = _number("W")
        fields[required("scale", "watts")] = _select(["watts", "percent"])
        fields[optional("soc_entity")] = _entity(["sensor", "number", "input_number"])
        fields[required("soc_max", 100)] = _number("%", 1, 100)
        fields[required("soc_resume_margin", 2)] = _number("%", 0, 50)
        fields[optional("measured_entity")] = _entity(["sensor"])
    elif kind == DeviceKind.PROPORTIONAL.value:
        fields[required("entity_id", vol.UNDEFINED)] = _entity(["light", "number", "input_number"])
        fields[required("priority", next_priority)] = _number(None, 1, 999)
        fields[required("power_w", vol.UNDEFINED)] = _number("W", 1)
        fields[required("min_power_w", 0)] = _number("W")
        fields[required("scale", "percent")] = _select(["percent", "watts"])
        fields[optional("measured_entity")] = _entity(["sensor"])
    else:  # on_off
        fields[required("entity_id", vol.UNDEFINED)] = _entity(["switch", "input_boolean", "light"])
        fields[required("priority", next_priority)] = _number(None, 1, 999)
        fields[required("power_w", vol.UNDEFINED)] = _number("W", 1)
        fields[optional("measured_entity")] = _entity(["sensor"])

    if kind != DeviceKind.BATTERY.value:
        fields[optional("offpeak")] = str
        fields[optional("reset_at")] = str
        fields[required("done_below_w", 0)] = _number("W")
        fields[required("done_after_s", 120)] = _number("s")
    fields[required("min_on_s", 0)] = _number("s")
    fields[required("min_off_s", 0)] = _number("s")
    if kind in (DeviceKind.ON_OFF.value, DeviceKind.EV_CHARGER.value):
        fields[required("start_margin_w", 0)] = _number("W")
        fields[required("stay_tolerance_w", 0)] = _number("W")
    return vol.Schema(fields)


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
                            options=[k.value for k in DeviceKind if k is not DeviceKind.BATTERY],
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
        """Normalise form values and validate them with the core model (raises ValueError if invalid)."""
        device = {**user_input, "kind": self._kind, "priority": int(user_input["priority"])}
        if device.get("offpeak") and not device.get("measured_entity"):
            raise ValueError("off-peak top-up needs a measured power entity")  # it could not tell when the device is finished
        if "phases" in device:
            device["phases"] = int(device["phases"])
        fields = {k: v for k, v in device.items() if k in DEVICE_FIELDS}
        core = build_device({"id": "x", **fields})
        # for an EV charger the power range is derived from the electrical settings: store it for the panel
        device["power_w"], device["min_power_w"] = core.power_w, core.min_power_w
        return device

    def _merge(self, user_input: dict[str, Any]) -> list[dict[str, Any]]:
        devices = self._devices
        if self._editing is None:
            taken = {d["id"] for d in devices}
            base = slugify(user_input["name"]) or "device"
            device_id, n = base, 2
            while device_id in taken:
                device_id, n = f"{base}_{n}", n + 1
            devices.append({**user_input, "id": device_id, "enabled": True})
        else:
            # keep the identity and the on/off state of the device being edited
            old = next(d for d in devices if d["id"] == self._editing)
            edited = {**user_input, "id": self._editing, "enabled": old.get("enabled", True)}
            devices = [edited if d["id"] == self._editing else d for d in devices]
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
