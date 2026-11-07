"""Data models for the routing engine. No Home Assistant dependency."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


def parse_hhmm(text: str) -> int:
    """``"06:30"`` -> minutes since midnight."""
    try:
        hours, minutes = str(text).strip().split(":")
        h, m = int(hours), int(minutes)
    except ValueError:
        raise ValueError(f"invalid time {text!r}, expected HH:MM") from None
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"invalid time {text!r}, expected HH:MM")
    return h * 60 + m


def parse_window(text: str) -> tuple[int, int]:
    """``"22:30-06:30"`` -> (start, end) in minutes since midnight; the end may be on the next day."""
    parts = str(text).split("-")
    if len(parts) != 2:
        raise ValueError(f"invalid window {text!r}, expected HH:MM-HH:MM")
    start, end = parse_hhmm(parts[0]), parse_hhmm(parts[1])
    if start == end:
        raise ValueError(f"invalid window {text!r}: start and end are the same")
    return start, end


class DeviceKind(str, Enum):
    ON_OFF = "on_off"  # fixed load: water heater, socket, server...
    PROPORTIONAL = "proportional"  # adjustable load: dimmer, F1ATB...
    BATTERY = "battery"  # absorbs surplus as charge power, limited by its state of charge
    EV_CHARGER = "ev_charger"  # current-controlled: starts at min_current_a, steps of current_step_a


@dataclass
class Device:
    """A load that can be fed with solar surplus.

    Lower ``priority`` number = served first.

    For ``EV_CHARGER`` the power range is derived from the electrical settings
    (``voltage_v``, ``phases``, ``min_current_a``, ``max_current_a``); ``power_w`` may be left at 0.
    """

    id: str
    name: str
    priority: int
    kind: DeviceKind
    power_w: float = 0.0  # maximum power of the load (battery: max charge power)
    min_power_w: float = 0.0  # proportional / battery: below this the load is off
    min_on_s: float = 0.0  # minimum run time once started
    min_off_s: float = 0.0  # minimum rest time once stopped
    start_margin_w: float = 0.0  # extra surplus required to start an on/off load or an EV charge
    stay_tolerance_w: float = 0.0  # grid import tolerated to keep a load running
    enabled: bool = True
    # battery and EV charger
    soc_max: float = 100.0  # stop charging at this state of charge (%)
    soc_resume_margin: float = 2.0  # resume charging once soc <= soc_max - margin
    settle_s: float = 30.0  # after a power change, wait this long before trusting a lower measured power
    # EV charger only
    voltage_v: float = 230.0
    phases: int = 1
    min_current_a: float = 6.0  # IEC 61851-1 minimum for AC charging; some chargers differ
    max_current_a: float = 16.0
    current_step_a: float = 1.0
    # off-peak top-up: inside these windows the device is fed at full power until it stops consuming (it is hot / full)
    offpeak: tuple[str, ...] = ()  # windows "HH:MM-HH:MM" (local time), may cross midnight
    reset_at: str | None = None  # "HH:MM" from which the device may be topped up again; default: end of the first window
    done_below_w: float | None = None  # measured power at or below which the device counts as finished; default 5 % of power_w
    done_after_s: float = 120.0  # how long it must have been on before a low measured power means "finished"
    windows: tuple[tuple[int, int], ...] = field(init=False, default=(), repr=False, compare=False)
    reset_minute: int = field(init=False, default=0, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.kind = DeviceKind(self.kind)
        if self.kind is DeviceKind.EV_CHARGER:
            if self.phases not in (1, 3):
                raise ValueError(f"{self.id}: phases must be 1 or 3")
            if self.voltage_v <= 0 or self.current_step_a <= 0:
                raise ValueError(f"{self.id}: voltage_v and current_step_a must be > 0")
            if not 0 < self.min_current_a <= self.max_current_a:
                raise ValueError(f"{self.id}: need 0 < min_current_a <= max_current_a")
            self.power_w = self.volts_amps_to_w(self.max_current_a)
            self.min_power_w = self.volts_amps_to_w(self.min_current_a)
        if self.power_w <= 0:
            raise ValueError(f"{self.id}: power_w must be > 0")
        if not 0 <= self.min_power_w <= self.power_w:
            raise ValueError(f"{self.id}: min_power_w must be within 0..power_w")
        if not 0 < self.soc_max <= 100:
            raise ValueError(f"{self.id}: soc_max must be within 0..100")
        self.offpeak = tuple(self.offpeak)
        try:
            self.windows = tuple(parse_window(w) for w in self.offpeak)
            self.reset_minute = parse_hhmm(self.reset_at) if self.reset_at else (self.windows[0][1] if self.windows else 0)
        except ValueError as err:
            raise ValueError(f"{self.id}: {err}") from None
        if self.windows and self.kind is DeviceKind.BATTERY:
            raise ValueError(f"{self.id}: a battery cannot have off-peak windows")
        if self.done_below_w is not None and not 0 <= self.done_below_w < self.power_w:
            raise ValueError(f"{self.id}: done_below_w must be within 0..power_w")
        if not math.isfinite(self.done_after_s) or self.done_after_s < 0:
            raise ValueError(f"{self.id}: done_after_s must be >= 0")

    # ---- off-peak helpers ----

    @property
    def done_threshold_w(self) -> float:
        return self.done_below_w if self.done_below_w is not None else 0.05 * self.power_w

    def in_offpeak(self, local: datetime) -> bool:
        minute = local.hour * 60 + local.minute
        return any((s <= minute < e) if s < e else (minute >= s or minute < e) for s, e in self.windows)

    def cycle_key(self, local: datetime) -> str:
        """Identifier of the daily period containing ``local``; a device finished in one period is topped up again in the next."""
        return (local.replace(tzinfo=None) - timedelta(minutes=self.reset_minute)).date().isoformat()

    # ---- EV helpers ----

    @property
    def watts_per_amp(self) -> float:
        return self.voltage_v * self.phases

    def volts_amps_to_w(self, amps: float) -> float:
        return amps * self.watts_per_amp

    def current_for(self, power_w: float) -> float:
        """Current (A) matching a commanded power, 0 when off."""
        return power_w / self.watts_per_amp if power_w > 0 else 0.0

    def quantize_power(self, available_w: float) -> float:
        """Largest power <= available_w that lands on a whole current step, within [min, max]; 0 if below min."""
        amps = math.floor(available_w / self.watts_per_amp / self.current_step_a + 1e-9) * self.current_step_a
        amps = min(amps, self.max_current_a)
        if amps < self.min_current_a - 1e-9:
            return 0.0
        return self.volts_amps_to_w(amps)


@dataclass
class DeviceReading:
    """What the outside world tells the engine about a device (all optional)."""

    measured_w: float | None = None  # real power drawn (charge power for a battery)
    soc: float | None = None  # state of charge, %
    connected: bool | None = None  # EV plugged in; None = unknown, assumed connected


@dataclass
class DeviceState:
    power_w: float = 0.0  # last commanded power
    changed_at: float | None = None  # timestamp of the last on/off transition
    power_changed_at: float | None = None  # timestamp of the last change of commanded power
    soc_blocked: bool = False  # charging stopped by the SoC limit (hysteresis memory)
    done_cycle: str | None = None  # the daily period in which the off-peak top-up found the device finished
    topup_since: float | None = None  # when the device was first seen on during its top-up
    forced: bool = False  # fed at full power by the off-peak top-up in the last step

    @property
    def on(self) -> bool:
        return self.power_w > 0
