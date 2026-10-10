"""Interfaces between the engine and the outside world.

Home Assistant, MQTT, HTTP or Modbus runtimes implement these; the engine
never imports them.
"""

from __future__ import annotations

from typing import Protocol


class PowerSource(Protocol):
    async def read_available_w(self, routed_w: float) -> float:
        """Return the solar power available to managed loads (see ``sources``)."""


class DeviceActuator(Protocol):
    async def apply(self, device_id: str, power_w: float) -> None:
        """Command a device to ``power_w`` (0 = off)."""
