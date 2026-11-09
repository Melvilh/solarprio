"""Single definition of the device and site-settings forms.

The Home Assistant options flow (config_flow.py) and the sidebar panel (panel.py + frontend) both read these
specifications, so a field added here appears in both and the two can never drift apart. Validation and merging of a
device live here too, for the same reason.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from homeassistant.util import slugify

from .const import (
    CONF_CONSUMPTION_ENTITY,
    CONF_EMERGENCY,
    CONF_EXPORT_ENTITY,
    CONF_HOUSE_ENTITY,
    CONF_INTERVAL,
    CONF_INVERT,
    CONF_MARGIN,
    CONF_MODE,
    CONF_OFFPEAK_BUDGET,
    CONF_ON_STALE,
    CONF_PRODUCTION_ENTITY,
    CONF_STALE_AFTER,
    CONF_SUBSCRIPTION,
    DEFAULT_INTERVAL,
    DEFAULT_STALE_AFTER,
    MODE_EXPORT,
    MODE_PRODUCTION,
    ON_STALE_HOLD,
    ON_STALE_OFF,
)
from .coordinator import DEVICE_FIELDS, build_device
from .core import DeviceKind
from .core.profiles import ha_presets

OFFPEAK_SIGNAL_DOMAINS = ("binary_sensor", "sensor", "input_boolean", "switch", "select", "input_select")
MAX_W = 1_000_000


@dataclass(frozen=True)
class Field:
    """One form field. ``type``: text, number, select, entity or boolean."""

    name: str
    type: str
    required: bool = False
    default: Any = None  # None: no default (a required field must then be filled in)
    domains: tuple[str, ...] = ()  # entity fields: the entity domains offered
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    options: tuple[str, ...] = ()
    show_if: tuple[str, str] | None = None  # shown only when the other field has this value
    advanced: bool = False  # tucked away behind "advanced settings" in the panel

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["domains"], out["options"] = list(self.domains), list(self.options)
        out["show_if"] = list(self.show_if) if self.show_if else None
        return out


def _text(name: str, required: bool = False, default: Any = None, advanced: bool = False) -> Field:
    return Field(name, "text", required, default, advanced=advanced)


def _entity(name: str, domains: tuple[str, ...], required: bool = False, advanced: bool = False) -> Field:
    return Field(name, "entity", required, None, domains=domains, advanced=advanced)


def _number(name: str, unit: str | None, default: Any = None, minimum: float = 0, maximum: float = MAX_W, required: bool = True,
            advanced: bool = False) -> Field:
    return Field(name, "number", required, default, unit=unit, min=minimum, max=maximum, advanced=advanced)


def _select(name: str, options: tuple[str, ...], default: str, advanced: bool = False) -> Field:
    return Field(name, "select", True, default, options=options, advanced=advanced)


def _flag(name: str, advanced: bool = False) -> Field:
    return Field(name, "boolean", False, False, advanced=advanced)


def _temperature_fields() -> list[Field]:
    """Tank temperature limits for a water heater (or anything heated to a temperature), read from one sensor."""
    return [
        _entity("temp_entity", ("sensor",)),
        _number("temp_max_solar", "°C", None, -50, 150, required=False),
        _number("temp_max_offpeak", "°C", None, -50, 150, required=False),
        _number("temp_hysteresis", "°C", 3, 0, 50, advanced=True),
        _number("temp_min", "°C", None, -50, 150, required=False, advanced=True),
        _flag("sanitary_forced_only", advanced=True),
    ]


def device_fields(kind: str, next_priority: int = 1) -> list[Field]:
    """The fields of the form of one device type, in display order."""
    fields = [_text("name", True, "")]
    if kind == DeviceKind.EV_CHARGER.value:
        fields += [
            _entity("entity_id", ("number", "input_number"), True),  # charging current, A
            _entity("switch_entity", ("switch", "input_boolean")),
            _number("priority", None, next_priority, 1, 999),
            _select("phases", ("1", "3"), "1"),
            _number("voltage_v", "V", 230, 100, 480),
            _number("min_current_a", "A", 6, 1, 80),
            _number("max_current_a", "A", 16, 1, 80),
            _number("current_step_a", "A", 1, 0.1, 10),
            _entity("connected_entity", ("binary_sensor", "sensor", "switch", "input_boolean")),
            _entity("soc_entity", ("sensor", "number", "input_number")),
            _number("soc_max", "%", 100, 1, 100),
            _entity("measured_entity", ("sensor",)),
        ]
    elif kind == DeviceKind.BATTERY.value:
        fields += [
            _entity("entity_id", ("number", "input_number"), True),  # charge setpoint
            _number("priority", None, next_priority, 1, 999),
            _number("power_w", "W", None, 1),
            _number("min_power_w", "W", 0, advanced=True),
            _select("scale", ("watts", "percent"), "watts"),
            _entity("soc_entity", ("sensor", "number", "input_number")),
            _number("soc_max", "%", 100, 1, 100),
            _number("soc_resume_margin", "%", 2, 0, 50, advanced=True),
            _entity("measured_entity", ("sensor",)),
        ]
    elif kind == DeviceKind.PROPORTIONAL.value:
        fields += [
            _entity("entity_id", ("light", "number", "input_number"), True),
            _number("priority", None, next_priority, 1, 999),
            _number("power_w", "W", None, 1),
            _select("scale", ("percent", "watts"), "percent"),
            _entity("measured_entity", ("sensor",)),
            *_temperature_fields(),
            _number("min_power_w", "W", 0, advanced=True),
            _number("hold_s", "s", 0, 0, 600, advanced=True),
            _number("ramp_up_w", "W", None, 1, MAX_W, required=False, advanced=True),
            _number("deadband_w", "W", 0, advanced=True),
        ]
    elif kind == DeviceKind.TASK.value:
        fields += [
            _entity("entity_id", ("input_boolean",), True),  # a helper only: never a switch that cuts a power supply
            _number("priority", None, next_priority, 1, 999),
            _number("power_w", "W", None, 1),
        ]
    else:  # on_off
        fields += [
            _entity("entity_id", ("switch", "input_boolean", "light"), True),
            _number("priority", None, next_priority, 1, 999),
            _number("power_w", "W", None, 1),
            _entity("measured_entity", ("sensor",)),
            *_temperature_fields(),
        ]

    if kind != DeviceKind.BATTERY.value:
        fields += [
            _entity("offpeak_entity", OFFPEAK_SIGNAL_DOMAINS),
            _text("offpeak", advanced=True),
            _text("offpeak_extra", advanced=True),
            _text("offpeak_values", advanced=True),
        ]
        if kind != DeviceKind.TASK.value:  # a task has nothing to measure, so nothing that can be "finished"
            fields += [_text("reset_at", advanced=True), _number("done_below_w", "W", 0, advanced=True),
                       _number("done_after_s", "s", 120, advanced=True)]
            fields += [_flag("surplus_only", advanced=True)]
    fields += [_number("min_on_s", "s", 0, advanced=True), _number("min_off_s", "s", 0, advanced=True)]
    if kind in (DeviceKind.ON_OFF.value, DeviceKind.EV_CHARGER.value, DeviceKind.TASK.value):
        fields += [_number("start_margin_w", "W", 0, advanced=True), _number("stay_tolerance_w", "W", 0, advanced=True)]
    return fields


def site_fields() -> list[Field]:
    """The measurement and safety settings of the whole site (the setup form, editable later from the panel)."""
    sensor = ("sensor",)
    return [
        _select(CONF_MODE, (MODE_EXPORT, MODE_PRODUCTION), MODE_EXPORT),
        Field(CONF_EXPORT_ENTITY, "entity", True, None, domains=sensor, show_if=(CONF_MODE, MODE_EXPORT)),
        Field(CONF_INVERT, "boolean", False, False, show_if=(CONF_MODE, MODE_EXPORT)),
        Field(CONF_PRODUCTION_ENTITY, "entity", True, None, domains=sensor, show_if=(CONF_MODE, MODE_PRODUCTION)),
        Field(CONF_CONSUMPTION_ENTITY, "entity", True, None, domains=sensor, show_if=(CONF_MODE, MODE_PRODUCTION)),
        _number(CONF_INTERVAL, "s", DEFAULT_INTERVAL, 1, 300, advanced=True),
        _number(CONF_STALE_AFTER, "s", DEFAULT_STALE_AFTER, 0, 3600, advanced=True),
        _select(CONF_ON_STALE, (ON_STALE_OFF, ON_STALE_HOLD), ON_STALE_OFF, advanced=True),
        _number(CONF_MARGIN, "W", 0, 0, 2000),
        _number(CONF_OFFPEAK_BUDGET, "W", 0, advanced=True),
        _number(CONF_SUBSCRIPTION, "VA", None, 500, 100_000, required=False),
        _entity(CONF_HOUSE_ENTITY, sensor),
        _number(CONF_EMERGENCY, "W", None, 1, 20_000, required=False, advanced=True),
    ]


# Ready-made models (generic or by brand), from the profile catalog: a beginner only picks the entities. The values are the
# usual ones: check them against your own installation.
PRESETS: dict[str, dict[str, Any]] = ha_presets()


# ---- validation and merging (used by the options flow and by the panel) ------------------------------------


def clean_device(kind: str, user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalise form values and validate them with the core model. Raises ValueError (or TypeError) if invalid."""
    device = {k: v for k, v in user_input.items() if v not in (None, "")}
    for f in device_fields(kind):  # what the Home Assistant form's selectors enforce, enforced here for every caller
        if f.required and f.default is None and f.name not in device:
            raise ValueError(f"{f.name} is required")
        if f.name not in device:
            continue
        value = device[f.name]
        if f.type == "number" and not (isinstance(value, (int, float)) and not isinstance(value, bool) and f.min <= value <= f.max):
            raise ValueError(f"{f.name} must be a number between {f.min:g} and {f.max:g}")
        if f.type == "select" and str(value) not in f.options:
            raise ValueError(f"{f.name} must be one of {', '.join(f.options)}")
        if f.type == "entity" and not str(value).startswith(tuple(f"{d}." for d in f.domains)):
            raise ValueError(f"{f.name} must be a {' / '.join(f.domains)} entity")
    device.update(kind=kind, priority=int(user_input["priority"]))
    if any(device.get(k) is not None for k in ("temp_max_solar", "temp_max_offpeak", "temp_min")) and not device.get("temp_entity"):
        raise ValueError("temperature limits need a temperature sensor")
    if (device.get("offpeak") or device.get("offpeak_entity")) and not device.get("measured_entity") and kind != DeviceKind.TASK.value:
        raise ValueError("off-peak top-up needs a measured power entity")  # it could not tell when the device is finished
    if "phases" in device:
        device["phases"] = int(device["phases"])
    fields = {k: v for k, v in device.items() if k in _CORE_KEYS or k == "offpeak_entity"}  # build_device reads the entity
    core = build_device({"id": "x", **fields})
    # for an EV charger the power range is derived from the electrical settings: store it for the panel
    device["power_w"], device["min_power_w"] = core.power_w, core.min_power_w
    return device


def merge_device(devices: list[dict[str, Any]], device: dict[str, Any], editing: str | None) -> list[dict[str, Any]]:
    """The device list with ``device`` added (``editing`` None) or replacing the device ``editing``."""
    devices = list(devices)
    if editing is None:
        taken = {d["id"] for d in devices}
        base = slugify(device["name"]) or "device"
        device_id, n = base, 2
        while device_id in taken:
            device_id, n = f"{base}_{n}", n + 1
        devices.append({**device, "id": device_id, "enabled": True})
        return devices
    # keep the identity and the on/off state of the device being edited
    old = next(d for d in devices if d["id"] == editing)
    edited = {**device, "id": editing, "enabled": old.get("enabled", True)}
    return [edited if d["id"] == editing else d for d in devices]


def clean_site(user_input: dict[str, Any]) -> dict[str, Any]:
    """Validate the site settings. Raises ValueError with the name of the offending field."""
    spec = {f.name: f for f in site_fields()}
    mode = user_input.get(CONF_MODE)
    if mode not in spec[CONF_MODE].options:
        raise ValueError(CONF_MODE)
    out: dict[str, Any] = {CONF_MODE: mode}
    for f in spec.values():
        if f.name == CONF_MODE or (f.show_if and user_input.get(f.show_if[0]) != f.show_if[1]):
            continue
        value = user_input.get(f.name, f.default)  # a setting missing from an older entry takes its default
        if f.type == "entity":
            if value in (None, ""):
                if f.required:
                    raise ValueError(f.name)
                continue
            if not str(value).startswith(tuple(f"{d}." for d in f.domains)):
                raise ValueError(f.name)
            out[f.name] = value
        elif f.type == "number":
            if value in (None, "") and not f.required:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError(f.name) from None
            if not (f.min <= number <= f.max):
                raise ValueError(f.name)
            out[f.name] = int(number) if number == int(number) else number
        elif f.type == "select":
            if value not in f.options:
                raise ValueError(f.name)
            out[f.name] = value
        elif f.type == "boolean":
            out[f.name] = bool(value)
    if out.get(CONF_SUBSCRIPTION) and not out.get(CONF_HOUSE_ENTITY):
        raise ValueError(CONF_HOUSE_ENTITY)  # the cap needs to know what the house draws
    return out


_CORE_KEYS = frozenset(DEVICE_FIELDS)
