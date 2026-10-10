"""Data models for the routing engine. No Home Assistant dependency."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DeviceKind(str, Enum):
    ON_OFF = "on_off"  # fixed load: water heater, socket, server...
    PROPORTIONAL = "proportional"  # adjustable load: dimmer, F1ATB, EV charger...


@dataclass
class Device:
    """A load that can be fed with solar surplus.

    Lower ``priority`` number = served first.
    """

    id: str
    name: str
    priority: int
    kind: DeviceKind
    power_w: float  # maximum power of the load
    min_power_w: float = 0.0  # proportional only: below this the load is off
    min_on_s: float = 0.0  # minimum run time once started
    min_off_s: float = 0.0  # minimum rest time once stopped
    start_margin_w: float = 0.0  # extra surplus required to start an on/off load
    stay_tolerance_w: float = 0.0  # grid import tolerated to keep a load running
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.power_w <= 0:
            raise ValueError(f"{self.id}: power_w must be > 0")
        if not 0 <= self.min_power_w <= self.power_w:
            raise ValueError(f"{self.id}: min_power_w must be within 0..power_w")


@dataclass
class DeviceState:
    power_w: float = 0.0  # last commanded power
    changed_at: float | None = None  # timestamp of the last on/off transition

    @property
    def on(self) -> bool:
        return self.power_w > 0
