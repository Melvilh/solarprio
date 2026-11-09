"""Sensors: available power, routed power, status and one commanded-power sensor per device."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SolarPrioCoordinator


def device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name="solarprio")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SolarPrioCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        SummarySensor(coordinator, entry, "available_w", "available_power"),
        SummarySensor(coordinator, entry, "routed_w", "routed_power"),
        StatusSensor(coordinator, entry),
    ]
    entities += [DeviceSensor(coordinator, entry, d["id"], d["name"]) for d in coordinator.device_cfgs.values()]
    entities += [HeatingModeSensor(coordinator, entry, d["id"], d["name"]) for d in coordinator.device_cfgs.values()]
    async_add_entities(entities)


class _Base(CoordinatorEntity[SolarPrioCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SolarPrioCoordinator, entry: ConfigEntry, key: str, translation_key: str,
                 device_name: str | None = None) -> None:
        """``translation_key``: the name of the entity in the user's language (strings.json); ``device_name`` fills its {device}."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = translation_key
        if device_name is not None:
            self._attr_translation_placeholders = {"device": device_name}
        self._attr_device_info = device_info(entry)


class SummarySensor(_Base):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, key: str, translation_key: str) -> None:
        super().__init__(coordinator, entry, key, translation_key)
        self._key = key

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get(self._key) if self.coordinator.data else None


class StatusSensor(_Base):
    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "status", "status")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data["status"] if self.coordinator.data else None


MODES = ["idle", "solar", "offpeak", "offpeak_limited", "sanitary", "sanitary_limited", "forced", "forced_limited", "no_cap", "hot",
         "sensor_fault", "disabled"]


class HeatingModeSensor(_Base):
    """What drives the device now (solar surplus, off-peak top-up, sanitary minimum, hot, ...)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = MODES

    def __init__(self, coordinator, entry, device_id: str, name: str) -> None:
        super().__init__(coordinator, entry, f"mode_{device_id}", "heating_mode", name)
        self._device_id = device_id

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data or self._device_id not in self.coordinator.device_cfgs:
            return None
        mode = self.coordinator.engine.mode(self._device_id)
        return mode if mode in MODES else "idle"


class DeviceSensor(_Base):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, device_id: str, name: str) -> None:
        super().__init__(coordinator, entry, f"cmd_{device_id}", "device_command", name)
        self._device_id = device_id

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data["commands"].get(self._device_id) if self.coordinator.data else None
