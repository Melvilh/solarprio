"""Priority-based solar surplus allocator.

Pure logic: time is injected, nothing here touches the network or Home Assistant.

Besides handing the surplus out by priority, the engine can feed some devices from the grid on purpose, and then keeps
the house inside its subscription:

- **off-peak top-up**: during off-peak periods (time windows and/or a tariff signal) a device is fed until it stops
  consuming or its tank is hot;
- **sanitary minimum**: a tank that falls under its minimum temperature is heated from the grid, whatever the sun.

Both are limited by a dynamic cap (``subscription_va`` minus what the rest of the house draws) and both are switched off
when the grid measurement is lost.
"""

from __future__ import annotations

import math
from datetime import datetime

from .models import Device, DeviceKind, DeviceReading, DeviceState

SHED_S = 60.0  # after a clear overshoot of the subscription, grid-fed devices wait this long
SHED_MARGIN_VA = 200.0  # "clear" overshoot: this far above the subscription
CAP_MIN_W = 150.0  # not worth feeding anything from the grid with less room than this
CAP_STEP_W = 100.0  # the room is rounded down to this step
RISE_STEP_W = 200.0  # a grid-fed adjustable load only goes up by at least this much at a time


class Engine:
    def __init__(
        self,
        devices: list[Device] | None = None,
        offpeak_budget_w: float = 0.0,
        subscription_va: float | None = None,
        emergency_import_w: float | None = None,
    ) -> None:
        """``offpeak_budget_w``: total power the off-peak top-up may feed at once. 0 means one device at a time;
        otherwise devices are topped up in priority order as long as they fit (the first one always starts).

        ``subscription_va``: house power limit. When set, the power fed from the grid on purpose is capped at the room
        left (see ``step``'s ``house_w``) and nothing is fed from the grid while the house power is unknown.

        ``emergency_import_w``: when the grid import (``step``'s ``import_w``, not counting what grid-fed devices draw
        on purpose) exceeds this, every device running on the surplus is cut at once.
        """
        for name, value in (("offpeak_budget_w", offpeak_budget_w), ("subscription_va", subscription_va),
                            ("emergency_import_w", emergency_import_w)):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be >= 0")
        self._offpeak_budget_w = offpeak_budget_w
        self._subscription_va = subscription_va or None
        self._emergency_import_w = emergency_import_w or None
        self._shed_until = -math.inf
        self._temp_fault: set[str] = set()
        self._no_cap: set[str] = set()  # devices whose forced run is blocked for want of a subscription limit
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
        """Provide (or clear, with None) what is known about a device: measured power, SoC, plug state, temperature."""
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

    def mode(self, device_id: str) -> str:
        """What drives the device now: idle, solar, offpeak, sanitary (and ``_limited`` when the subscription cut the
        power), hot (tank at its maximum), sensor_fault (temperature unknown), disabled."""
        return self._states[device_id].reason

    def is_hot(self, device_id: str) -> bool:
        """The tank is at (or above) a maximum temperature and waits to cool down by the hysteresis."""
        state = self._states[device_id]
        return self._devices[device_id].has_temperature and (state.hot_solar or state.hot_offpeak)

    def set_forced_run(self, device_id: str, on: bool) -> None:
        """The "forced run" switch of a device (it only matters for ``sanitary_forced_only`` devices)."""
        self._states[device_id].forced_run = bool(on)

    def set_offpeak(self, device_id: str, on: bool) -> None:
        """The "use the off-peak hours" switch of a device: off means the router only (the surplus), no off-peak top-up."""
        self._states[device_id].offpeak_on = bool(on)

    def offpeak_in_use(self, device_id: str) -> bool | None:
        """True: router and off-peak hours. False: the router only. None: the device has no off-peak hours at all."""
        if not self._devices[device_id].has_schedule:
            return None
        return self._states[device_id].offpeak_on

    def set_extra_windows(self, device_id: str, on: bool) -> None:
        """Whether the device's ``offpeak_extra`` windows (for example the midday off-peak hours) count as off-peak."""
        self._states[device_id].extra_on = bool(on)

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
            fresh.hot_solar, fresh.hot_offpeak, fresh.cold = old.hot_solar, old.hot_offpeak, old.cold  # real temperatures
            fresh.forced_run, fresh.extra_on, fresh.offpeak_on = old.forced_run, old.extra_on, old.offpeak_on  # the user's switches
            self._states[device_id] = fresh
        self._readings.clear()
        self._shed_until = -math.inf

    # ---- tank temperature ----

    def _track_temperatures(self) -> None:
        """Update the hysteresis memories from the temperatures. An unknown temperature on a device that has temperature
        settings is a sensor fault: it gets nothing (the limits cannot be checked) until the reading is back."""
        self._temp_fault = set()
        for dev in self._devices.values():
            if not dev.has_temperature:
                continue
            state, reading = self._states[dev.id], self._readings.get(dev.id)
            t = reading.temperature if reading is not None else None
            if t is None or not math.isfinite(t):
                self._temp_fault.add(dev.id)
                continue
            hys = dev.temp_hysteresis
            if dev.temp_max_solar is not None:
                if t > dev.temp_max_solar:
                    state.hot_solar = True
                elif t < dev.temp_max_solar - hys:
                    state.hot_solar = False
            limit = dev.offpeak_temp_limit
            if limit is not None:
                if t > limit:
                    state.hot_offpeak = True
                elif t < limit - hys:
                    state.hot_offpeak = False
            if dev.temp_min is not None:
                if t < dev.temp_min:
                    state.cold = True
                elif t > dev.temp_min + hys:
                    state.cold = False

    # ---- off-peak top-up ----

    def offpeak_status(self, device_id: str, local: datetime) -> str | None:
        """None (no schedule), ``"heating"``, ``"done"`` (finished in this period) or ``"waiting"``."""
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
        """Off-peak now (window and/or signal), not finished yet, and the end of the heating can be told."""
        if not (dev.enabled and dev.has_schedule) or dev.surplus_only or dev.id in self._temp_fault:
            return False
        if not state.offpeak_on:
            return False  # the user chose the router only for this device
        if dev.offpeak_signal and (reading is None or reading.offpeak is not True):
            return False  # unknown or not off-peak: never force on a doubtful signal
        if (dev.windows or dev.windows_extra) and (local is None or not dev.in_offpeak(local, state.extra_on)):
            return False
        if state.done_cycle == self._period_key(dev, state, local):
            return False
        if dev.kind is DeviceKind.TASK:
            return True  # a go signal: nothing to measure, nothing to finish
        if dev.offpeak_temp_limit is not None and state.hot_offpeak:
            return False  # the tank is hot enough
        if not dev.has_temperature and (reading is None or reading.measured_w is None):
            return False  # without a temperature or a measured power we could not tell when it is finished
        if dev.kind is DeviceKind.EV_CHARGER:
            return not self._soc_blocked(dev, state, reading) and reading.connected is not False
        return True

    def _top_up(self, now: float, local: datetime | None) -> set[str]:
        """Pick the devices to feed from the grid now: those not finished, by priority, as far as the budget allows.

        A device that has been on for ``done_after_s`` and consumes (almost) nothing is finished: it is marked done
        for this period and the next device in priority order takes its turn, in the same step. A device that
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
            measured = reading.measured_w if reading is not None else None
            if state.power_w > 0 and measured is not None:
                if state.topup_since is None:
                    state.topup_since = now
                elif now - state.topup_since >= dev.done_after_s and measured <= dev.done_threshold_w:
                    state.done_cycle, state.topup_since = self._period_key(dev, state, local), None
                    continue
            else:
                state.topup_since = None
            chosen.add(dev.id)
            fed.add(dev.id)
            used_w += dev.power_w
        return chosen

    # ---- feeding from the grid on purpose, inside the subscription ----

    def _sanitary_candidate(self, dev: Device, state: DeviceState) -> bool:
        if dev.sanitary_forced_only and not state.forced_run:
            return False  # the user wants the sanitary minimum only when they ask for a forced run
        return dev.enabled and dev.temp_min is not None and not dev.surplus_only and dev.id not in self._temp_fault and state.cold

    def _cap_w(self, now: float, house_w: float | None) -> float | None:
        """Room left for the power fed from the grid on purpose: None = no limit, 0 = nothing allowed now."""
        if self._subscription_va is None:
            return None
        if house_w is None or not math.isfinite(house_w):
            return 0.0  # no view on the house: never feed from the grid blindly
        if now < self._shed_until:
            return 0.0
        running = any(s.forced and s.power_w > 0 for s in self._states.values())
        if house_w > self._subscription_va + SHED_MARGIN_VA and running:
            self._shed_until = now + SHED_S  # a clear overshoot: let go of everything and wait
            return 0.0
        others = max(house_w - self.routed_w, 0.0)  # the rest of the house, what managed devices draw taken out
        room = self._subscription_va - others
        if room < CAP_MIN_W:
            return 0.0
        return math.floor(room / CAP_STEP_W) * CAP_STEP_W

    @staticmethod
    def _fit(dev: Device, state: DeviceState, left: float) -> float:
        """The power a grid-fed device gets out of ``left`` watts of room."""
        if math.isinf(left):
            return dev.power_w
        if dev.kind is DeviceKind.PROPORTIONAL:
            p = min(dev.power_w, left)
            if state.power_w < p < state.power_w + RISE_STEP_W and p < dev.power_w:
                p = min(state.power_w, left)  # no small steps up: they would only make the grid measurement hunt
            return p if p > 0 and p >= dev.min_power_w else 0.0
        if dev.kind is DeviceKind.ON_OFF:
            return dev.power_w if dev.power_w <= left else 0.0
        if dev.kind is DeviceKind.EV_CHARGER:
            return dev.quantize_power(min(dev.power_w, left))
        if dev.kind is DeviceKind.BATTERY:
            p = min(dev.power_w, left)
            return p if p > 0 and p >= dev.min_power_w else 0.0
        return 0.0

    def _force_candidate(self, dev: Device, state: DeviceState, reading: DeviceReading | None) -> bool:
        """The user asked for a forced run of a car or a battery: charge from the grid now, up to the state-of-charge limit."""
        if not (state.forced_run and dev.enabled) or dev.surplus_only or dev.id in self._temp_fault:
            return False
        if dev.kind not in (DeviceKind.EV_CHARGER, DeviceKind.BATTERY):
            return False  # a water heater's forced run is the sanitary one (sanitary_forced_only)
        if self._soc_blocked(dev, state, reading):
            return False
        return not (dev.kind is DeviceKind.EV_CHARGER and reading is not None and reading.connected is False)

    def _grid_fed(
        self, now: float, local: datetime | None, house_w: float | None
    ) -> tuple[dict[str, float], set[str], set[str], set[str]]:
        """Devices fed from the grid on purpose now, with the power each gets.

        Returns ``(power per device, sanitary ones, forced-run ones, ones cut short by the subscription)``. A sanitary device
        that gets nothing stays at nothing (it does not take the sun either); a forced or off-peak one that gets nothing goes
        back to the surplus. A forced run needs a subscription limit: without one nothing keeps the house under the meter.
        """
        fed: dict[str, float] = {}
        sanitary: set[str] = set()
        forced: set[str] = set()
        limited: set[str] = set()
        self._no_cap = set()
        if local is None:
            return fed, sanitary, forced, limited
        ordered = sorted(self._devices.values(), key=lambda d: d.priority)
        sanitary_ids = [d.id for d in ordered if self._sanitary_candidate(d, self._states[d.id])]
        forced_ids = [d.id for d in ordered if self._force_candidate(d, self._states[d.id], self._readings.get(d.id))]
        if forced_ids and self._subscription_va is None:
            self._no_cap, forced_ids = set(forced_ids), []
        offpeak_ids = self._top_up(now, local)
        wanted = (
            sanitary_ids
            + [i for i in forced_ids if i not in sanitary_ids]
            + [d.id for d in ordered if d.id in offpeak_ids and d.id not in sanitary_ids and d.id not in forced_ids]
        )
        cap = self._cap_w(now, house_w)
        left = math.inf if cap is None else cap
        for dev_id in wanted:
            dev, state = self._devices[dev_id], self._states[dev_id]
            if dev.kind is DeviceKind.TASK:
                fed[dev_id] = dev.power_w  # a signal: not limited by the subscription
                continue
            p = self._fit(dev, state, left)
            if dev_id in sanitary_ids:
                fed[dev_id] = p
                sanitary.add(dev_id)
            elif dev_id in forced_ids and p > 0:
                fed[dev_id] = p
                forced.add(dev_id)
            elif p > 0:
                fed[dev_id] = p
            else:
                continue
            if p < dev.power_w:
                limited.add(dev_id)
            left -= p
        return fed, sanitary, forced, limited

    # ---- the control step ----

    def step(
        self,
        available_w: float,
        now: float,
        local: datetime | None = None,
        house_w: float | None = None,
        import_w: float | None = None,
    ) -> dict[str, float]:
        """Allocate ``available_w`` by priority and return the new command per device.

        ``available_w`` is the total solar power that could feed managed loads,
        including what they already consume (see ``sources.available_*``).

        ``local`` is the wall-clock time (devices with off-peak windows use it; devices driven by an off-peak signal read
        the signal from their reading). Passing no ``local`` disables everything fed from the grid on purpose (off-peak
        top-up, sanitary minimum), which is what callers do when the grid measurement is lost.
        The devices fed from the grid get their power first and it is taken out of what the others may share.

        ``house_w``: what the whole house draws now (needed for the subscription cap).
        ``import_w``: what is imported from the grid now (for the emergency cut).
        """
        self._track_signals()
        self._track_temperatures()
        fed, sanitary, forced, limited = self._grid_fed(now, local, house_w)
        for dev_id, state in self._states.items():
            state.forced = fed.get(dev_id, 0.0) > 0
        remaining = max(available_w - sum(fed.values()), 0.0)
        emergency = (
            self._emergency_import_w is not None
            and import_w is not None
            and import_w - sum(self._drawn_w(i) for i in fed) > self._emergency_import_w
        )
        commands: dict[str, float] = {}

        for dev in sorted(self._devices.values(), key=lambda d: d.priority):
            state = self._states[dev.id]
            reading = self._readings.get(dev.id)
            if dev.id in fed:
                # a decrease here comes from the subscription cap (or an overshoot): a safety cut that no minimum run time
                # may hold back; a start still honours the minimum rest time
                power = fed[dev.id] if fed[dev.id] <= state.power_w else self._apply_timers(dev, state, fed[dev.id], now)
                self._commit(state, power, now)
                commands[dev.id] = power
                base = "sanitary" if dev.id in sanitary else "forced" if dev.id in forced else "offpeak"
                state.reason = base + ("_limited" if dev.id in limited else "")
                continue  # its power was already taken out of ``remaining``
            reason = "idle"
            if not dev.enabled:
                wanted, forced_off, reason = 0.0, True, "disabled"
            elif dev.id in self._temp_fault:
                wanted, forced_off, reason = 0.0, True, "sensor_fault"
            elif dev.temp_max_solar is not None and state.hot_solar:
                wanted, forced_off, reason = 0.0, True, "hot"
            elif emergency and state.power_w > 0:
                wanted, forced_off = 0.0, True  # too much is imported: let go at once, no timer, no ramp
            else:
                wanted, forced_off = self._wanted(dev, state, reading, remaining)
            power = wanted if forced_off else self._apply_timers(dev, state, wanted, now)
            if not forced_off:
                power = self._slew(dev, state, power, now)
            self._commit(state, power, now)
            commands[dev.id] = power
            if reason == "idle" and power <= 0 and dev.id in self._no_cap:
                reason = "no_cap"  # a forced run was asked for but no subscription limit is set: nothing is fed from the grid
            state.reason = reason if power <= 0 or reason != "idle" else "solar"
            remaining = max(remaining - self._consumed(dev, state, reading, power, now), 0.0)

        return commands

    @staticmethod
    def _slew(dev: Device, state: DeviceState, power: float, now: float) -> float:
        """Smooth an adjustable load: wait after a change, limit the steps up, ignore tiny changes.

        The grid measurement lags behind a change of power; correcting on a reading that does not show the last change
        yet is what makes a regulation overshoot and import from the grid.
        """
        if dev.kind is not DeviceKind.PROPORTIONAL or not (dev.hold_s or dev.ramp_up_w or dev.deadband_w):
            return power
        current = state.power_w
        if power == current:
            return power
        rising = power > current
        if state.power_changed_at is not None and now - state.power_changed_at < (dev.hold_s if rising else dev.hold_s / 2):
            return current
        if current > 0 and power > 0 and abs(power - current) < dev.deadband_w:
            return current
        if rising and dev.ramp_up_w is not None and power > current + dev.ramp_up_w:
            power = max(current + dev.ramp_up_w, dev.min_power_w)
        return power

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
