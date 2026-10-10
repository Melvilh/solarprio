"""Priority-based solar surplus allocator.

Pure logic: time is injected, nothing here touches the network or Home Assistant.
"""

from __future__ import annotations

from .models import Device, DeviceKind, DeviceState


class Engine:
    def __init__(self, devices: list[Device] | None = None) -> None:
        self._devices: dict[str, Device] = {}
        self._states: dict[str, DeviceState] = {}
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

    @property
    def routed_w(self) -> float:
        """Power currently sent to managed devices (last commands)."""
        return sum(s.power_w for s in self._states.values())

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

    def step(self, available_w: float, now: float) -> dict[str, float]:
        """Allocate ``available_w`` by priority and return the new command per device.

        ``available_w`` is the total solar power that could feed managed loads,
        including what they already consume (see ``sources.available_*``).
        """
        remaining = max(available_w, 0.0)
        commands: dict[str, float] = {}

        for dev in sorted(self._devices.values(), key=lambda d: d.priority):
            state = self._states[dev.id]
            wanted = self._wanted(dev, state, remaining) if dev.enabled else 0.0
            power = self._apply_timers(dev, state, wanted, now)
            self._commit(state, power, now)
            commands[dev.id] = power
            remaining = max(remaining - power, 0.0)

        return commands

    @staticmethod
    def _wanted(dev: Device, state: DeviceState, remaining: float) -> float:
        if dev.kind is DeviceKind.ON_OFF:
            if state.on:
                keep = remaining >= dev.power_w - dev.stay_tolerance_w
                return dev.power_w if keep else 0.0
            start = remaining >= dev.power_w + dev.start_margin_w
            return dev.power_w if start else 0.0

        # proportional
        power = min(remaining, dev.power_w)
        return power if power > 0 and power >= dev.min_power_w else 0.0

    @staticmethod
    def _apply_timers(dev: Device, state: DeviceState, wanted: float, now: float) -> float:
        """Enforce min on/off durations by holding the current on/off state."""
        if state.changed_at is None:
            return wanted
        elapsed = now - state.changed_at
        if state.on and wanted == 0 and elapsed < dev.min_on_s:
            # held on: keep the lowest power the load accepts
            return dev.min_power_w if dev.kind is DeviceKind.PROPORTIONAL and dev.min_power_w > 0 else state.power_w
        if not state.on and wanted > 0 and elapsed < dev.min_off_s:
            return 0.0
        return wanted

    @staticmethod
    def _commit(state: DeviceState, power: float, now: float) -> None:
        was_on = state.on
        state.power_w = power
        if was_on != state.on:
            state.changed_at = now
