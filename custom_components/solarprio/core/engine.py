"""Priority-based solar surplus allocator.

Pure logic: time is injected, nothing here touches the network or Home Assistant.
"""

from __future__ import annotations

from datetime import datetime

from .models import Device, DeviceKind, DeviceReading, DeviceState


class Engine:
    def __init__(self, devices: list[Device] | None = None, offpeak_budget_w: float = 0.0) -> None:
        """``offpeak_budget_w``: total power the off-peak top-up may feed at once. 0 means one device at a time;
        otherwise devices are topped up in priority order as long as they fit (the first one always starts)."""
        if offpeak_budget_w < 0:
            raise ValueError("offpeak_budget_w must be >= 0")
        self._offpeak_budget_w = offpeak_budget_w
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

    def rollback_command(self, device_id: str, confirmed_w: float) -> None:
        """A command could not be delivered: the device is still at ``confirmed_w``.

        Keeps ``routed_w`` and the on/off logic truthful; min on/off timers are left as they are.
        """
        self._states[device_id].power_w = confirmed_w

    def reset(self) -> None:
        """Forget all commands and timers (loads were switched off from outside the engine)."""
        for device_id, old in self._states.items():
            fresh = DeviceState()
            fresh.done_cycle = old.done_cycle  # a device found finished tonight is not topped up again tonight
            fresh.signal_prev, fresh.signal_period = old.signal_prev, old.signal_period
            self._states[device_id] = fresh
        self._readings.clear()

    # ---- off-peak top-up ----

    def offpeak_status(self, device_id: str, local: datetime) -> str | None:
        """None (no schedule), ``"heating"``, ``"done"`` (finished in this daily period) or ``"waiting"``."""
        dev, state = self._devices[device_id], self._states[device_id]
        if not dev.has_schedule:
            return None
        if state.forced:
            return "heating"
        key = self._period_key(dev, state, local)
        return "done" if key is not None and state.done_cycle == key else "waiting"

    @staticmethod
    def _period_key(dev: Device, state: DeviceState, local: datetime | None) -> str | None:
        """The period in which a device may be found finished once: a day (windows) or one off-peak period (signal)."""
        if dev.offpeak_signal:
            return f"signal:{state.signal_period}"
        return dev.cycle_key(local) if local is not None else None

    def _track_signals(self) -> None:
        """Count the off-peak periods of signal-driven devices: each change to off-peak starts a new one.

        An unknown signal changes nothing, so a flapping sensor does not restart the top-up.
        """
        for dev in self._devices.values():
            if not dev.offpeak_signal:
                continue
            state, reading = self._states[dev.id], self._readings.get(dev.id)
            signal = reading.offpeak if reading is not None else None
            if signal is None:
                continue
            if signal and state.signal_prev is not True:
                state.signal_period += 1
            state.signal_prev = signal

    def _top_up_candidate(self, dev: Device, state: DeviceState, reading: DeviceReading | None, local: datetime | None) -> bool:
        """Off-peak now (window or signal), not finished yet, and its consumption can be checked."""
        if not (dev.enabled and dev.has_schedule):
            return False
        if dev.offpeak_signal:
            if reading is None or reading.offpeak is not True:
                return False  # unknown or not off-peak: never force on a doubtful signal
        elif local is None or not dev.in_offpeak(local):
            return False
        if state.done_cycle == self._period_key(dev, state, local):
            return False
        if dev.kind is DeviceKind.TASK:
            return True  # a go signal: nothing to measure, nothing to finish
        if reading is None or reading.measured_w is None:
            return False  # without a measured power we could not tell when it is finished: never force blindly
        if dev.kind is DeviceKind.EV_CHARGER:
            return not self._soc_blocked(dev, state, reading) and reading.connected is not False
        return True

    def _top_up(self, now: float, local: datetime | None) -> set[str]:
        """Pick the devices to feed from the grid now: those not finished, by priority, as far as the budget allows.

        A device that has been on for ``done_after_s`` and consumes (almost) nothing is finished: it is marked done
        for this daily period and the next device in priority order takes its turn, in the same step. A device that
        does not fit in the budget waits (a smaller one further down may still fit).
        """
        chosen: set[str] = set()
        fed: set[str] = set()  # the devices that count against the budget (tasks are only signals)
        used_w = 0.0
        if local is None:  # callers pass no clock when the grid measurement is lost: nothing is forced, whatever the mode
            for state in self._states.values():
                state.topup_since = None
            return chosen
        for dev in sorted(self._devices.values(), key=lambda d: d.priority):
            state, reading = self._states[dev.id], self._readings.get(dev.id)
            if not self._top_up_candidate(dev, state, reading, local):
                state.topup_since = None
                continue
            if dev.kind is DeviceKind.TASK:  # a go signal for the whole off-peak period: no turn, no budget, never "finished"
                chosen.add(dev.id)
                state.topup_since = None
                continue
            if fed and used_w + dev.power_w > self._offpeak_budget_w:
                state.topup_since = None  # waits its turn
                continue
            if state.power_w > 0:
                if state.topup_since is None:
                    state.topup_since = now
                elif now - state.topup_since >= dev.done_after_s and reading.measured_w <= dev.done_threshold_w:
                    state.done_cycle, state.topup_since = self._period_key(dev, state, local), None
                    continue
            else:
                state.topup_since = None
            chosen.add(dev.id)
            fed.add(dev.id)
            used_w += dev.power_w
        return chosen

    def step(self, available_w: float, now: float, local: datetime | None = None) -> dict[str, float]:
        """Allocate ``available_w`` by priority and return the new command per device.

        ``available_w`` is the total solar power that could feed managed loads,
        including what they already consume (see ``sources.available_*``).

        ``local`` is the wall-clock time (devices with off-peak windows use it; devices driven by an off-peak signal read
        the signal from their reading). Passing no ``local`` disables the off-peak top-up for every device, which is what
        callers do when the grid measurement is lost. The devices being topped up get their full power first and that power is taken out of what
        the others may share.
        """
        self._track_signals()
        top_up = self._top_up(now, local)
        for dev_id, state in self._states.items():
            state.forced = dev_id in top_up
        remaining = max(available_w - sum(self._devices[i].power_w for i in top_up), 0.0)
        commands: dict[str, float] = {}

        for dev in sorted(self._devices.values(), key=lambda d: d.priority):
            state = self._states[dev.id]
            reading = self._readings.get(dev.id)
            if dev.id in top_up:
                power = self._apply_timers(dev, state, dev.power_w, now)
                self._commit(state, power, now)
                commands[dev.id] = power
                continue  # its power was already taken out of ``remaining``
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
        if dev.kind in (DeviceKind.ON_OFF, DeviceKind.TASK):
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
            if dev.kind not in (DeviceKind.ON_OFF, DeviceKind.TASK) and dev.min_power_w > 0:
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
