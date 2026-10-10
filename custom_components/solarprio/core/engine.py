"""Priority-based solar surplus allocator.

Pure logic: time is injected, nothing here touches the network or Home Assistant.
"""

from __future__ import annotations

from .models import Device, DeviceKind, DeviceReading, DeviceState


class Engine:
    def __init__(self, devices: list[Device] | None = None) -> None:
        self._devices: dict[str, Device] = {}
        self._states: dict[str, DeviceState] = {}
        self._readings: dict[str, DeviceReading] = {}
        for device in devices or []:
            self.add_device(device)

    def add_device(self, device: Device) -> None:
        if device.id in self._devices:
            raise ValueError(f"duplicate device id: {device.id}")
        self._devices[device.id] = device
        self._states[device.id] = DeviceState()

    def remove_device(self, device_id: str) -> None:
        del self._devices[device_id]
        del self._states[device_id]
        self._readings.pop(device_id, None)

    def set_reading(self, device_id: str, reading: DeviceReading | None) -> None:
        """Provide (or clear, with None) what is known about a device: measured power, SoC, plug state."""
        if reading is None:
            self._readings.pop(device_id, None)
        else:
            self._readings[device_id] = reading

    @property
    def device_ids(self) -> list[str]:
        return list(self._devices)

    def reading(self, device_id: str) -> DeviceReading | None:
        return self._readings.get(device_id)

    @property
    def routed_w(self) -> float:
        """Power managed devices really draw: measured when known, else the last command.

        This is what must be added back to a grid-export measurement to get the surplus.
        """
        return sum(self._drawn_w(i) for i in self._states)

    def _drawn_w(self, device_id: str) -> float:
        reading = self._readings.get(device_id)
        if reading is not None and reading.measured_w is not None:
            return max(reading.measured_w, 0.0)
        return self._states[device_id].power_w

    def state(self, device_id: str) -> DeviceState:
        return self._states[device_id]

    def device(self, device_id: str) -> Device:
        return self._devices[device_id]

    def set_priority(self, device_id: str, priority: int) -> None:
        """Change a device priority on the fly; its state and timers are kept."""
        self._devices[device_id].priority = priority

    def set_enabled(self, device_id: str, enabled: bool) -> None:
        self._devices[device_id].enabled = enabled

    def reset(self) -> None:
        """Forget all commands and timers (loads were switched off from outside the engine)."""
        for device_id in self._states:
            self._states[device_id] = DeviceState()
        self._readings.clear()

    def step(self, available_w: float, now: float) -> dict[str, float]:
        """Allocate ``available_w`` by priority and return the new command per device.

        ``available_w`` is the total solar power that could feed managed loads,
        including what they already consume (see ``sources.available_*``).
        """
        remaining = max(available_w, 0.0)
        commands: dict[str, float] = {}

        for dev in sorted(self._devices.values(), key=lambda d: d.priority):
            state = self._states[dev.id]
            reading = self._readings.get(dev.id)
            if dev.enabled:
                wanted, forced_off = self._wanted(dev, state, reading, remaining)
            else:
                wanted, forced_off = 0.0, True
            power = wanted if forced_off else self._apply_timers(dev, state, wanted, now)
            self._commit(state, power, now)
            commands[dev.id] = power
            remaining = max(remaining - self._consumed(dev, state, reading, power, now), 0.0)

        return commands

    @staticmethod
    def _consumed(dev: Device, state: DeviceState, reading: DeviceReading | None, power: float, now: float) -> float:
        """Surplus a device is expected to absorb, to leave the rest to lower priorities.

        A device that is measured to draw less than commanded for a while (a full battery tapering, a car that
        limits itself) frees the difference. Right after a change we keep trusting the command.
        """
        if reading is None or reading.measured_w is None or power <= 0:
            return power
        settled = state.power_changed_at is not None and now - state.power_changed_at >= dev.settle_s
        return min(power, max(reading.measured_w, 0.0)) if settled else power

    @staticmethod
    def _soc_blocked(dev: Device, state: DeviceState, reading: DeviceReading | None) -> bool:
        """True when the state of charge forbids charging (with hysteresis)."""
        if dev.kind not in (DeviceKind.BATTERY, DeviceKind.EV_CHARGER):
            return False
        soc = reading.soc if reading is not None else None
        if soc is None:
            state.soc_blocked = False
            return dev.soc_max < 100  # a limit was asked for but cannot be checked: do not charge
        if soc >= dev.soc_max:
            state.soc_blocked = True
        elif soc <= dev.soc_max - dev.soc_resume_margin:
            state.soc_blocked = False
        return state.soc_blocked

    @classmethod
    def _wanted(cls, dev: Device, state: DeviceState, reading: DeviceReading | None, remaining: float) -> tuple[float, bool]:
        """Return ``(power, forced_off)``. ``forced_off`` skips the min on/off timers (safety limits)."""
        if dev.kind is DeviceKind.ON_OFF:
            if state.on:
                keep = remaining >= dev.power_w - dev.stay_tolerance_w
                return (dev.power_w if keep else 0.0), False
            start = remaining >= dev.power_w + dev.start_margin_w
            return (dev.power_w if start else 0.0), False

        if dev.kind is DeviceKind.PROPORTIONAL:
            power = min(remaining, dev.power_w)
            return (power if power > 0 and power >= dev.min_power_w else 0.0), False

        # battery and EV charger: safety gates first
        if cls._soc_blocked(dev, state, reading):
            return 0.0, True
        if dev.kind is DeviceKind.EV_CHARGER and reading is not None and reading.connected is False:
            return 0.0, True

        if dev.kind is DeviceKind.BATTERY:
            power = min(remaining, dev.power_w)
            return (power if power > 0 and power >= dev.min_power_w else 0.0), False

        # EV charger: whole current steps, never below the minimum current
        if state.on:
            power = dev.quantize_power(remaining)
            if power == 0 and remaining >= dev.min_power_w - dev.stay_tolerance_w:
                power = dev.min_power_w  # ride out a short dip instead of stopping the session
            return power, False
        if remaining >= dev.min_power_w + dev.start_margin_w:
            return dev.quantize_power(remaining), False
        return 0.0, False

    @staticmethod
    def _apply_timers(dev: Device, state: DeviceState, wanted: float, now: float) -> float:
        """Enforce min on/off durations by holding the current on/off state."""
        if state.changed_at is None:
            return wanted
        elapsed = now - state.changed_at
        if state.on and wanted == 0 and elapsed < dev.min_on_s:
            # held on: keep the lowest power the load accepts
            if dev.kind is not DeviceKind.ON_OFF and dev.min_power_w > 0:
                return dev.min_power_w
            return state.power_w
        if not state.on and wanted > 0 and elapsed < dev.min_off_s:
            return 0.0
        return wanted

    @staticmethod
    def _commit(state: DeviceState, power: float, now: float) -> None:
        was_on = state.on
        if power != state.power_w:
            state.power_changed_at = now
        state.power_w = power
        if was_on != state.on:
            state.changed_at = now
