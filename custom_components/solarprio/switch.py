"""Master switch to enable or disable routing."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SolarPrioCoordinator
from .core import DeviceKind
from .sensor import device_info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SolarPrioCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [RoutingSwitch(coordinator, entry)]
    for cfg in coordinator.device_cfgs.values():
        device = coordinator.engine.device(cfg["id"])
        if device.sanitary_forced_only or device.kind in (DeviceKind.EV_CHARGER, DeviceKind.BATTERY):
            entities.append(DeviceFlagSwitch(coordinator, entry, cfg, "forced_run", "forced run", "mdi:water-boiler-alert"))
        if device.windows_extra:
            entities.append(DeviceFlagSwitch(coordinator, entry, cfg, "extra_windows", "extra off-peak windows", "mdi:clock-plus-outline"))
    async_add_entities(entities)


class RoutingSwitch(CoordinatorEntity[SolarPrioCoordinator], SwitchEntity, RestoreEntity):
    """On = routing active. Off = every managed load is switched off and left alone."""

    _attr_has_entity_name = True
    _attr_name = "Routing"

    def __init__(self, coordinator: SolarPrioCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_routing"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == "off":
            await self.coordinator.async_set_enabled(False)

    @property
    def is_on(self) -> bool:
        return self.coordinator.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_enabled(False)


class DeviceFlagSwitch(CoordinatorEntity[SolarPrioCoordinator], SwitchEntity, RestoreEntity):
    """A switch of one device that the user flips from Home Assistant: "forced run" or "extra off-peak windows".

    The state is restored after a restart; without a previous state both start off, so nothing is fed from the grid
    until the user asks for it.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: SolarPrioCoordinator, entry: ConfigEntry, cfg: dict[str, Any], flag: str, label: str, icon: str) -> None:
        super().__init__(coordinator)
        self._device_id, self._flag = cfg["id"], flag
        self._attr_unique_id = f"{entry.entry_id}_{flag}_{cfg['id']}"
        self._attr_name = f"{cfg['name']} {label}"
        self._attr_icon = icon
        self._attr_device_info = device_info(entry)

    def _set(self, on: bool) -> None:
        setter = self.coordinator.set_forced_run if self._flag == "forced_run" else self.coordinator.set_extra_windows
        setter(self._device_id, on)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._set(last is not None and last.state == "on")

    @property
    def is_on(self) -> bool:
        state = self.coordinator.engine.state(self._device_id)
        return state.forced_run if self._flag == "forced_run" else state.extra_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._set(True)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._set(False)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
