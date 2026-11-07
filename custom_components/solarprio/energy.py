"""Read what the user already declared in Home Assistant's Energy dashboard, to pre-fill the setup.

Only instantaneous power sensors (``stat_rate``) are used: the dashboard mostly holds cumulative energy counters
(kWh), which cannot tell the power right now. Nothing is written to the dashboard.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class EnergyDashboard:
    grid_power: str | None = None  # the single grid power sensor; positive = power drawn from the grid
    grid_sensors: int = 0  # how many grid power sensors the dashboard has (we only pre-fill when it is exactly one)
    solar_power: str | None = None  # the single solar production power sensor
    devices: list[tuple[str, str]] = field(default_factory=list)  # (name, power sensor) of tracked devices


def _usable(hass: HomeAssistant, entity_id: object) -> str | None:
    """The entity id if it exists right now (a pre-filled sensor that does not exist would only confuse)."""
    return entity_id if isinstance(entity_id, str) and hass.states.get(entity_id) is not None else None


async def async_read_energy_dashboard(hass: HomeAssistant) -> EnergyDashboard:
    try:
        from homeassistant.components.energy.data import async_get_manager  # noqa: PLC0415
    except ImportError:  # pragma: no cover - the energy integration ships with Home Assistant
        return EnergyDashboard()
    try:
        manager = await async_get_manager(hass)
        prefs = manager.data or {}
    except Exception:  # noqa: BLE001 - a broken dashboard must never break our setup
        _LOGGER.debug("Could not read the Energy dashboard preferences", exc_info=True)
        return EnergyDashboard()

    result = EnergyDashboard()
    grid, solar = [], []
    for source in prefs.get("energy_sources", []):
        if source.get("type") == "grid":
            grid += [_usable(hass, p.get("stat_rate")) for p in source.get("power", [])]
        elif source.get("type") == "solar":
            solar.append(_usable(hass, source.get("stat_rate")))
    result.grid_sensors = len(grid)
    result.grid_power = grid[0] if len(grid) == 1 else None
    result.solar_power = solar[0] if len(solar) == 1 else None
    for device in prefs.get("device_consumption", []):
        if sensor := _usable(hass, device.get("stat_rate")):
            name = device.get("name") or hass.states.get(sensor).name
            result.devices.append((str(name), sensor))
    return result
