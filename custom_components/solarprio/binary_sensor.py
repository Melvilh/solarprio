"""One "hot" binary sensor per device with temperature limits: the tank reached its maximum temperature."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SolarPrioCoordinator
from .sensor import device_info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SolarPrioCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HotSensor(coordinator, entry, d["id"], d["name"])
        for d in coordinator.device_cfgs.values()
        if coordinator.engine.device(d["id"]).has_temperature
    )


class HotSensor(CoordinatorEntity[SolarPrioCoordinator], BinarySensorEntity):
    """On while the tank is at or above a maximum temperature (until it has cooled down by the hysteresis)."""

    _attr_has_entity_name = True
    _attr_translation_key = "hot"
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator: SolarPrioCoordinator, entry: ConfigEntry, device_id: str, name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{entry.entry_id}_hot_{device_id}"
        self._attr_translation_placeholders = {"device": name}
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool | None:
        if self._device_id not in self.coordinator.device_cfgs:
            return None
        return self.coordinator.engine.is_hot(self._device_id)
