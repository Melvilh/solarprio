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
    ON_STALE_HOLD,
)
from .core import Device, DeviceKind, Engine, available_from_export, available_from_production

_LOGGER = logging.getLogger(__name__)

DEVICE_FIELDS = (
    "id", "name", "priority", "kind", "power_w", "min_power_w",
    "min_on_s", "min_off_s", "start_margin_w", "stay_tolerance_w", "enabled",
)


class MeasurementUnavailable(Exception):
    """A required power measurement is missing or too old."""


def build_device(cfg: dict[str, Any]) -> Device:
    values = {k: cfg[k] for k in DEVICE_FIELDS if k in cfg}
    values["kind"] = DeviceKind(values["kind"])
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
        self.engine = Engine([build_device(d) for d in self.device_cfgs.values()])
        self.enabled = True
        self._sent: dict[str, float] = {}

    # ---- measurement -------------------------------------------------

    def _read_watts(self, entity_id: str) -> float:
        state: State | None = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            raise MeasurementUnavailable(f"{entity_id} is unavailable")
        age = (dt_util.utcnow() - state.last_reported).total_seconds()
        if age > self._conf.get(CONF_STALE_AFTER, DEFAULT_STALE_AFTER):
            raise MeasurementUnavailable(f"{entity_id} has not reported for {age:.0f}s")
        try:
            value = float(state.state)
        except ValueError as err:
            raise MeasurementUnavailable(f"{entity_id} has a non-numeric state {state.state!r}") from err
        if state.attributes.get("unit_of_measurement") == "kW":
            value *= 1000
        return value

    def _available_w(self) -> float:
        routed = self.engine.routed_w
        if self._conf[CONF_MODE] == MODE_EXPORT:
            export = self._read_watts(self._conf[CONF_EXPORT_ENTITY])
            if self._conf.get(CONF_INVERT):
                export = -export
            return available_from_export(export, routed)
        return available_from_production(
            self._read_watts(self._conf[CONF_PRODUCTION_ENTITY]),
            self._read_watts(self._conf[CONF_CONSUMPTION_ENTITY]),
            routed,
        )

    # ---- control loop ------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        now = time.monotonic()
        if not self.enabled:
            return self._result("disabled", None)
        try:
            available = self._available_w()
        except MeasurementUnavailable as err:
            if self._conf.get(CONF_ON_STALE) == ON_STALE_HOLD:
                _LOGGER.warning("Measurement lost (%s): holding current state", err)
                return self._result("measurement_lost_hold", None)
            _LOGGER.warning("Measurement lost (%s): switching loads off", err)
            commands = self.engine.step(0.0, now)  # still honors min on/off durations
            await self._apply(commands)
            return self._result("measurement_lost_off", None)

        commands = self.engine.step(available, now)
        await self._apply(commands)
        return self._result("routing", available)

    def _result(self, status: str, available: float | None) -> dict[str, Any]:
        return {
            "status": status,
            "available_w": available,
            "routed_w": self.engine.routed_w,
            "commands": {i: self.engine.state(i).power_w for i in self.device_cfgs},
        }

    async def _apply(self, commands: dict[str, float]) -> None:
        for device_id, power in commands.items():
            if self._sent.get(device_id) == power:
                continue
            try:
                await self._call(self.device_cfgs[device_id], power)
            except Exception:  # noqa: BLE001 - one failing device must not stop the others
                _LOGGER.exception("Failed to apply %.0f W to %s", power, device_id)
                continue
            self._sent[device_id] = power

    async def _call(self, cfg: dict[str, Any], power: float) -> None:
        entity = cfg["entity_id"]
        domain = entity.split(".")[0]
        services = self.hass.services

        if cfg["kind"] == DeviceKind.ON_OFF.value:
            await services.async_call(
                "homeassistant", "turn_on" if power > 0 else "turn_off", {"entity_id": entity}, blocking=True
            )
            return

        percent = power / cfg["power_w"] * 100
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
