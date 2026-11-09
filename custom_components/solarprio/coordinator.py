"""Coordinator: reads HA entities, runs the engine, drives the devices."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CONSUMPTION_ENTITY,
    CONF_DEVICES,
    CONF_EMERGENCY,
    CONF_EXPORT_ENTITY,
    CONF_HOUSE_ENTITY,
    CONF_INTERVAL,
    CONF_INVERT,
    CONF_MARGIN,
    CONF_OFFPEAK_BUDGET,
    CONF_OFFPEAK_ENTITY,
    CONF_OFFPEAK_EXTRA,
    CONF_OFFPEAK_VALUES,
    CONF_OFFPEAK_WINDOWS,
    CONF_MODE,
    CONF_ON_STALE,
    CONF_PRODUCTION_ENTITY,
    CONF_STALE_AFTER,
    CONF_SUBSCRIPTION,
    DEFAULT_INTERVAL,
    DEFAULT_STALE_AFTER,
    DOMAIN,
    MODE_EXPORT,
    ON_STALE_HOLD,
    RESEND_EVERY_S,
)
from .core import (
    Device,
    DeviceKind,
    DeviceReading,
    Engine,
    available_from_export,
    available_from_production,
    parse_offpeak_state,
)

_LOGGER = logging.getLogger(__name__)

DEVICE_FIELDS = (
    "id", "name", "priority", "kind", "power_w", "min_power_w",
    "min_on_s", "min_off_s", "start_margin_w", "stay_tolerance_w", "enabled",
    "soc_max", "soc_resume_margin", "settle_s",
    "voltage_v", "phases", "min_current_a", "max_current_a", "current_step_a",
    "offpeak", "offpeak_extra", "reset_at", "done_below_w", "done_after_s", "offpeak_signal", "sanitary_forced_only",
    "temp_max_solar", "temp_max_offpeak", "temp_hysteresis", "temp_min", "surplus_only", "hold_s", "ramp_up_w", "deadband_w",
)


def with_site_offpeak(cfg: dict[str, Any], site: dict[str, Any]) -> dict[str, Any]:
    """The device settings with the site's off-peak hours filled in, for a device that follows them.

    What the device sets itself wins: a device with its own off-peak entity keeps it (and its states), one with its own windows
    keeps them.
    """
    if not cfg.get("offpeak_site"):
        return cfg
    out = dict(cfg)
    if not cfg.get("offpeak_entity") and site.get(CONF_OFFPEAK_ENTITY):
        out["offpeak_entity"] = site[CONF_OFFPEAK_ENTITY]
        out["offpeak_values"] = site.get(CONF_OFFPEAK_VALUES) or cfg.get("offpeak_values")
    if not cfg.get("offpeak") and site.get(CONF_OFFPEAK_WINDOWS):
        out["offpeak"] = site[CONF_OFFPEAK_WINDOWS]
    if not cfg.get("offpeak_extra") and site.get(CONF_OFFPEAK_EXTRA):
        out["offpeak_extra"] = site[CONF_OFFPEAK_EXTRA]
    return out


class MeasurementUnavailable(Exception):
    """A required power measurement is missing or too old."""


def build_device(cfg: dict[str, Any]) -> Device:
    values = {k: cfg[k] for k in DEVICE_FIELDS if k in cfg}
    values["kind"] = DeviceKind(values["kind"])
    if "phases" in values:
        values["phases"] = int(values["phases"])
    if isinstance(values.get("offpeak"), str):  # the form holds the windows as one text: "22:30-06:30, 12:30-14:30"
        values["offpeak"] = tuple(w.strip() for w in values["offpeak"].replace(";", ",").split(",") if w.strip())
    if isinstance(values.get("offpeak_extra"), str):
        values["offpeak_extra"] = tuple(w.strip() for w in values["offpeak_extra"].replace(";", ",").split(",") if w.strip())
    values["reset_at"] = values.get("reset_at") or None
    values["offpeak_signal"] = bool(cfg.get("offpeak_entity"))  # off-peak told by an entity instead of windows
    values["done_below_w"] = float(values["done_below_w"]) if values.get("done_below_w") else None  # 0 = automatic
    if "done_after_s" in values:
        values["done_after_s"] = float(values["done_after_s"])
    return Device(**values)


class SolarPrioCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._conf = {**entry.data}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=self._conf.get(CONF_INTERVAL, DEFAULT_INTERVAL)),
        )
        self.device_cfgs: dict[str, dict[str, Any]] = {d["id"]: d for d in entry.options.get(CONF_DEVICES, [])}
        self.engine = Engine(
            [build_device(with_site_offpeak(d, self._conf)) for d in self.device_cfgs.values()],
            offpeak_budget_w=float(self._conf.get(CONF_OFFPEAK_BUDGET, 0) or 0),
            subscription_va=float(self._conf.get(CONF_SUBSCRIPTION) or 0) or None,
            emergency_import_w=float(self._conf.get(CONF_EMERGENCY) or 0) or None,
        )
        self.enabled = True
        self._sent: dict[str, tuple[float, float]] = {}  # device -> (power_w, monotonic time it was sent)

    # ---- measurement -------------------------------------------------

    def _read_watts(self, entity_id: str) -> float:
        state: State | None = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            raise MeasurementUnavailable(f"{entity_id} is unavailable")
        age = (dt_util.utcnow() - state.last_reported).total_seconds()
        limit = self._conf.get(CONF_STALE_AFTER, DEFAULT_STALE_AFTER)
        if limit and age > limit:  # 0 = never judge by age: a sensor that only reports changes can look old while it is fine
            raise MeasurementUnavailable(f"{entity_id} has not reported for {age:.0f}s")
        try:
            value = float(state.state)
        except ValueError as err:
            raise MeasurementUnavailable(f"{entity_id} has a non-numeric state {state.state!r}") from err
        if state.attributes.get("unit_of_measurement") == "kW":
            value *= 1000
        return value

    def _read_optional(self, entity_id: str | None) -> State | None:
        """State of an optional entity, or None when not configured, unavailable, unknown or too old."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        age = (dt_util.utcnow() - state.last_reported).total_seconds()
        limit = self._conf.get(CONF_STALE_AFTER, DEFAULT_STALE_AFTER)
        if limit and age > limit:
            return None
        return state

    def _read_reading(self, cfg: dict[str, Any]) -> DeviceReading | None:
        """Measured power, state of charge and plug state of a device, from its optional entities."""
        cfg = with_site_offpeak(cfg, self._conf)  # a device that follows the site off-peak hours reads the site's signal
        measured = soc = connected = offpeak = temperature = None
        if state := self._read_optional(cfg.get("temp_entity")):
            try:
                temperature = float(state.state)
                if state.attributes.get("unit_of_measurement") == "°F":
                    temperature = (temperature - 32) / 1.8
            except ValueError:
                pass
        if cfg.get("offpeak_entity"):
            state = self.hass.states.get(cfg["offpeak_entity"])
            if state is not None:
                values = [v.strip() for v in str(cfg.get("offpeak_values") or "").replace(";", ",").split(",") if v.strip()]
                offpeak = parse_offpeak_state(state.state, values or None)
        if state := self._read_optional(cfg.get("measured_entity")):
            try:
                measured = float(state.state) * (1000 if state.attributes.get("unit_of_measurement") == "kW" else 1)
            except ValueError:
                pass
        if state := self._read_optional(cfg.get("soc_entity")):
            try:
                soc = float(state.state)
            except ValueError:
                pass
        if state := self._read_optional(cfg.get("connected_entity")):
            if state.state in ("on", "true", "True", "connected", "plugged_in"):
                connected = True
            elif state.state in ("off", "false", "False", "disconnected", "unplugged"):
                connected = False
        if measured is None and soc is None and connected is None and offpeak is None and temperature is None:
            return None
        return DeviceReading(measured_w=measured, soc=soc, connected=connected, offpeak=offpeak, temperature=temperature)

    def _update_readings(self) -> None:
        for device_id, cfg in self.device_cfgs.items():
            self.engine.set_reading(device_id, self._read_reading(cfg))

    def _available_w(self) -> tuple[float, float]:
        """The surplus the engine may hand out (minus the export margin kept on purpose) and the grid import now."""
        routed = self.engine.routed_w
        if self._conf[CONF_MODE] == MODE_EXPORT:
            export = self._read_watts(self._conf[CONF_EXPORT_ENTITY])
            if self._conf.get(CONF_INVERT):
                export = -export
            available = available_from_export(export, routed)
            grid_import = -export
        else:
            production = self._read_watts(self._conf[CONF_PRODUCTION_ENTITY])
            consumption = self._read_watts(self._conf[CONF_CONSUMPTION_ENTITY])
            available = available_from_production(production, consumption, routed)
            grid_import = consumption - production
        return available - float(self._conf.get(CONF_MARGIN, 0) or 0), grid_import

    def _house_w(self) -> float | None:
        """What the whole house draws, for the subscription cap. Unknown is not a lost measurement: the engine then simply
        feeds nothing from the grid."""
        entity = self._conf.get(CONF_HOUSE_ENTITY)
        if not entity:
            return None
        try:
            return self._read_watts(entity)
        except MeasurementUnavailable:
            return None

    # ---- control loop ------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        now = time.monotonic()
        self._update_readings()
        if not self.enabled:
            return self._result("disabled", None)
        try:
            available, grid_import = self._available_w()
        except MeasurementUnavailable as err:
            if self._conf.get(CONF_ON_STALE) == ON_STALE_HOLD:
                _LOGGER.warning("Measurement lost (%s): holding current state", err)
                return self._result("measurement_lost_hold", None, str(err))
            _LOGGER.warning("Measurement lost (%s): switching loads off", err)
            commands = self.engine.step(0.0, now)  # still honors min on/off durations
            await self._apply(commands, now)
            return self._result("measurement_lost_off", None, str(err))

        commands = self.engine.step(available, now, dt_util.now(), self._house_w(), grid_import)
        await self._apply(commands, now)
        return self._result("routing", available)

    def _result(self, status: str, available: float | None, detail: str | None = None) -> dict[str, Any]:
        return {
            "status": status,
            "detail": detail,  # why, for a lost measurement (which sensor, how old...)
            "available_w": available,
            "routed_w": self.engine.routed_w,
            "commands": {i: self.engine.state(i).power_w for i in self.device_cfgs},
        }

    async def _apply(self, commands: dict[str, float], now: float) -> None:
        """Send changed commands, and re-send unchanged ones every ``RESEND_EVERY_S``.

        The periodic re-send is a heartbeat: a device with a watchdog (an ESPHome router that drops to 0 W when
        it stops hearing from us) needs to keep receiving orders even when the setpoint does not change.
        """
        for device_id, power in commands.items():
            previous = self._sent.get(device_id)
            if previous is not None and previous[0] == power and now - previous[1] < RESEND_EVERY_S:
                continue
            try:
                await self._call(self.device_cfgs[device_id], power)
            except Exception:  # noqa: BLE001 - one failing device must not stop the others
                _LOGGER.exception("Failed to apply %.0f W to %s", power, device_id)
                # still at the last confirmed value
                self.engine.rollback_command(device_id, previous[0] if previous else 0.0)
                continue
            self._sent[device_id] = (power, now)

    async def _call(self, cfg: dict[str, Any], power: float) -> None:
        entity = cfg["entity_id"]
        domain = entity.split(".")[0]
        services = self.hass.services

        if cfg["kind"] in (DeviceKind.ON_OFF.value, DeviceKind.TASK.value):
            await services.async_call(
                "homeassistant", "turn_on" if power > 0 else "turn_off", {"entity_id": entity}, blocking=True
            )
            return

        if cfg["kind"] == DeviceKind.EV_CHARGER.value:
            await self._call_ev(cfg, power)
            return

        percent = power / cfg["power_w"] * 100
        if cfg["kind"] == DeviceKind.BATTERY.value:
            if domain not in ("number", "input_number"):
                raise ValueError(f"a battery needs a number entity for its charge setpoint, got {domain}")
            value = percent if cfg.get("scale") == "percent" else power
            await services.async_call(domain, "set_value", {"entity_id": entity, "value": round(value, 1)}, blocking=True)
            return

        if domain == "light":
            if power > 0:
                await services.async_call("light", "turn_on", {"entity_id": entity, "brightness_pct": round(percent)}, blocking=True)
            else:
                await services.async_call("light", "turn_off", {"entity_id": entity}, blocking=True)
        elif domain in ("number", "input_number"):
            value = power if cfg.get("scale") == "watts" else percent
            await services.async_call(domain, "set_value", {"entity_id": entity, "value": round(value, 1)}, blocking=True)
        else:
            raise ValueError(f"unsupported entity domain for a proportional device: {domain}")

    async def _call_ev(self, cfg: dict[str, Any], power: float) -> None:
        """Set the charging current (A) on a number entity; also switch the charger if a switch is configured."""
        device = self.engine.device(cfg["id"])
        number = cfg["entity_id"]
        number_domain = number.split(".")[0]
        switch = cfg.get("switch_entity")
        services = self.hass.services
        amps = round(device.current_for(power), 2)

        if power > 0:
            await services.async_call(number_domain, "set_value", {"entity_id": number, "value": amps}, blocking=True)
            if switch:
                await services.async_call("homeassistant", "turn_on", {"entity_id": switch}, blocking=True)
        elif switch:
            await services.async_call("homeassistant", "turn_off", {"entity_id": switch}, blocking=True)
        else:
            # no switch: 0 A is how this charger is paused (not every charger accepts it)
            await services.async_call(number_domain, "set_value", {"entity_id": number, "value": 0}, blocking=True)

    # ---- live changes from the panel ----------------------------------

    def set_forced_run(self, device_id: str, on: bool) -> None:
        """The "forced run" switch of a device (its sanitary minimum only feeds it while this is on)."""
        if device_id in self.device_cfgs:
            self.engine.set_forced_run(device_id, on)

    def set_extra_windows(self, device_id: str, on: bool) -> None:
        """The "extra windows" switch of a device (its extra off-peak windows count only while this is on)."""
        if device_id in self.device_cfgs:
            self.engine.set_extra_windows(device_id, on)

    def settings_changed(self, data: dict[str, Any]) -> bool:
        """True when the site settings (measurement, safety) differ from the ones this coordinator runs with."""
        return dict(data) != self._conf

    def apply_device_options(self, devices: list[dict[str, Any]]) -> bool:
        """Apply new device options in place when only priority/enabled changed.

        Returns False when anything else changed (devices added/removed/edited): the caller must reload.
        """
        new = {d["id"]: d for d in devices}
        if set(new) != set(self.device_cfgs):
            return False
        live_keys = ("priority", "enabled")
        for device_id, cfg in new.items():
            old = self.device_cfgs[device_id]
            if {k: v for k, v in cfg.items() if k not in live_keys} != {k: v for k, v in old.items() if k not in live_keys}:
                return False
        for device_id, cfg in new.items():
            self.engine.set_priority(device_id, int(cfg["priority"]))
            self.engine.set_enabled(device_id, bool(cfg.get("enabled", True)))
            self.device_cfgs[device_id] = cfg
        return True

    def _device_snapshot(self, cfg: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        cmd_w = data["commands"].get(cfg["id"], 0.0)
        reading = self.engine.reading(cfg["id"])
        out = {
            "id": cfg["id"], "name": cfg["name"], "entity_id": cfg["entity_id"], "kind": cfg["kind"],
            "priority": cfg["priority"], "power_w": cfg["power_w"], "enabled": cfg.get("enabled", True),
            "cmd_w": cmd_w,
            "soc": reading.soc if reading else None,
            "connected": reading.connected if reading else None,
            "measured_w": reading.measured_w if reading else None,
            "current_a": None,
            "offpeak": self.engine.offpeak_status(cfg["id"], dt_util.now()),
            "mode": self.engine.mode(cfg["id"]),
            "hot": self.engine.is_hot(cfg["id"]),
            "forced_run": self.engine.state(cfg["id"]).forced_run,
            "extra_windows": self.engine.state(cfg["id"]).extra_on,
            "temperature_c": reading.temperature if reading else None,
        }
        if cfg["kind"] == DeviceKind.EV_CHARGER.value:
            out["current_a"] = round(self.engine.device(cfg["id"]).current_for(cmd_w), 1)
        return out

    def snapshot(self) -> dict[str, Any]:
        data = self.data or self._result("starting", None)
        devices = [self._device_snapshot(d, data) for d in sorted(self.device_cfgs.values(), key=lambda d: d["priority"])]
        return {
            "status": data["status"], "detail": data.get("detail"), "available_w": data["available_w"], "routed_w": data["routed_w"],
            "routing_enabled": self.enabled, "devices": devices,
        }

    async def async_shutdown_loads(self) -> list[str]:
        """Switch every device off, ignoring min on/off durations. Returns ids that failed."""
        failed = []
        for device_id, cfg in self.device_cfgs.items():
            try:
                await self._call(cfg, 0.0)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Could not switch off %s", device_id)
                failed.append(device_id)
        self._sent.clear()
        self.engine.reset()
        return failed

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            await self.async_shutdown_loads()
        await self.async_request_refresh()
