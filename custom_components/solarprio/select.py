"""One selector per device: the mode the user chooses (off, router only, router + off-peak hours, forced run)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SolarPrioCoordinator
from .sensor import device_info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SolarPrioCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(DeviceModeSelect(coordinator, entry, cfg["id"], cfg["name"]) for cfg in coordinator.device_cfgs.values())


class DeviceModeSelect(CoordinatorEntity[SolarPrioCoordinator], SelectEntity):
    """What the user wants for the device. It is derived from the device's on/off state and its switches, so it always agrees with them
    and with the panel; the "mode" sensor is what the device is actually doing."""

    _attr_has_entity_name = True
    _attr_translation_key = "device_mode"
    _attr_icon = "mdi:tune-variant"

    def __init__(self, coordinator: SolarPrioCoordinator, entry: ConfigEntry, device_id: str, name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{entry.entry_id}_modechoice_{device_id}"
        self._attr_translation_placeholders = {"device": name}
        self._attr_options = coordinator.available_modes(device_id)
        self._attr_device_info = device_info(entry)

    @property
    def current_option(self) -> str | None:
        if self._device_id not in self.coordinator.device_cfgs:
            return None
        return self.coordinator.current_mode(self._device_id)

    async def async_select_option(self, option: str) -> None:
        if self.coordinator.set_mode(self._device_id, option):
            self.coordinator.async_update_listeners()
