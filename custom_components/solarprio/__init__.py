"""Home Assistant integration for solarprio."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant

from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_DEVICES, DOMAIN
from .coordinator import SolarPrioCoordinator
from .panel import async_register_panel, async_remove_panel, async_setup_panel_api

PLATFORMS = [Platform.SENSOR, Platform.SWITCH]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    await async_setup_panel_api(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = SolarPrioCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    async def _on_stop(_: Event) -> None:
        await coordinator.async_shutdown_loads()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register_panel(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        async_remove_panel(hass)
        coordinator: SolarPrioCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown_loads()
    return unloaded


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply priority/enabled changes live (panel drag and drop); reload for anything else."""
    coordinator: SolarPrioCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.apply_device_options(entry.options.get(CONF_DEVICES, [])):
        await coordinator.async_request_refresh()
    else:
        await hass.config_entries.async_reload(entry.entry_id)
