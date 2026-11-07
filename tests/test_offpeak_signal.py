"""Off-peak told by a signal (a tariff entity or topic) instead of time windows, like the Linky's tariff period."""
from datetime import datetime, timedelta

import pytest

from solarprio import Device, DeviceKind, DeviceReading, Engine, parse_offpeak_state

BASE = datetime(2026, 11, 10, 0, 0)
NOW = datetime(2026, 11, 10, 12, 0)  # the wall clock is irrelevant to a signal-driven device


def heater(id="ecs", priority=1, **kw):
    return Device(**{**dict(id=id, name=id, priority=priority, kind=DeviceKind.ON_OFF, power_w=2000, offpeak_signal=True), **kw})


class Sim:
    """Loads draw their rated power when commanded unless hot; ``signal`` is the tariff, None = unknown."""

    def __init__(self, devices, hot=(), budget=0.0, signal=False):
        self.engine, self.t, self.hot, self.signal = Engine(devices, offpeak_budget_w=budget), NOW, set(hot), signal
        self.rated = {d.id: d.power_w for d in devices}

    def run(self, seconds, step_s=5, local=True):
        cmd = {}
        for _ in range(int(seconds / step_s)):
            for dev_id, rated in self.rated.items():
                drawn = 0.0 if dev_id in self.hot else (rated if self.engine.state(dev_id).power_w > 0 else 0.0)
                self.engine.set_reading(dev_id, DeviceReading(measured_w=drawn, offpeak=self.signal))
            cmd = self.engine.step(0.0, (self.t - BASE).total_seconds(), self.t if local else None)
            self.t += timedelta(seconds=step_s)
        return cmd


@pytest.mark.parametrize("text, expected", [
    ("on", True), ("ON", True), ("true", True), ("HC..", True), ("hc..", True), ("HC", True), ("Heures Creuses", True),
    ("HEURE CREUSE", True), ("off", False), ("HP..", False), ("HEURES PLEINES", False), ("TH..", False), ("something", False),
    ("unknown", None), ("unavailable", None), ("", None), ("None", None), ('"HC.."', True),
])
def test_default_interpretation_of_a_tariff_state(text, expected):
    assert parse_offpeak_state(text) is expected


@pytest.mark.parametrize("state, values, expected", [
    ("HC..", ["HC*"], True), ("HC", ["HC*"], True), ("hchp", ["HC*"], True), ("HP..", ["HC*"], False),
    ("35495096.0", ["HC*"], False),  # an energy index is not a tariff period
    ("HP..", ["HC*", "2"], False), ("2", ["HC*", "2"], True), ("hc..", ["HC.."], True), ("HC", ["HC.."], False),
    ("anything", ["*"], True),
])
def test_a_trailing_star_matches_any_ending(state, values, expected):
    assert parse_offpeak_state(state, values) is expected


def test_explicit_values_replace_the_defaults():
    assert parse_offpeak_state("2", ["2"]) is True
    assert parse_offpeak_state("1", ["2"]) is False
    assert parse_offpeak_state("on", ["2"]) is False  # the user's list is the only truth
    assert parse_offpeak_state("hc..", ["HC.."]) is True
    assert parse_offpeak_state("unavailable", ["unavailable"]) is None  # unknown is never off-peak


def test_the_device_is_fed_while_the_signal_says_off_peak():
    sim = Sim([heater()])
    assert sim.run(120)["ecs"] == 0  # peak hours: nothing, whatever the clock
    sim.signal = True
    assert sim.run(30)["ecs"] == 2000
    sim.signal = False
    assert sim.run(60)["ecs"] == 0  # back to peak: dropped (min on time is 0)


def test_an_unknown_signal_never_starts_anything_and_keeps_the_period():
    sim = Sim([heater()], signal=None)
    assert sim.run(60)["ecs"] == 0
    sim.signal = True
    sim.run(30)
    assert sim.engine.state("ecs").forced
    sim.signal = None  # sensor flaps to unavailable
    assert sim.run(30)["ecs"] == 0  # unknown: not forced
    sim.signal = True  # and comes back: same off-peak period, not a new one
    sim.run(5)
    assert sim.engine.state("ecs").signal_period == 1


def test_a_hot_device_is_left_alone_until_the_next_off_peak_period():
    sim = Sim([heater()], hot={"ecs"}, signal=True)
    sim.run(180)
    assert sim.engine.offpeak_status("ecs", sim.t) == "done"
    assert sim.run(3600)["ecs"] == 0  # same period: not tried again
    sim.signal = False
    sim.run(600)
    sim.hot.clear()  # the tank cooled down by the next night
    sim.signal = True
    assert sim.run(30)["ecs"] == 2000  # a new off-peak period tries it again
    assert sim.engine.state("ecs").signal_period == 2


def test_devices_follow_the_same_sequence_and_budget_as_windows():
    sim = Sim([heater("a", 1), heater("b", 2)], hot={"a"}, signal=True)
    assert sim.run(30) == {"a": 2000, "b": 0}  # one at a time
    assert sim.run(180) == {"a": 0, "b": 2000}  # a is hot: b takes over
    sim = Sim([heater("a", 1), heater("b", 2)], budget=4000, signal=True)
    assert sim.run(30) == {"a": 2000, "b": 2000}


def test_nothing_is_forced_when_the_caller_gives_no_clock():
    """The callers pass no clock when the grid measurement is lost: even a signal must not start a load then."""
    sim = Sim([heater()], signal=True)
    assert sim.run(60, local=False)["ecs"] == 0


def test_a_missing_power_measurement_means_no_top_up():
    e = Engine([heater()])
    e.set_reading("ecs", DeviceReading(offpeak=True))
    assert e.step(0.0, 0.0, NOW)["ecs"] == 0


def test_reset_keeps_the_period_so_a_finished_device_stays_finished():
    sim = Sim([heater()], hot={"ecs"}, signal=True)
    sim.run(180)
    sim.engine.reset()
    assert sim.engine.offpeak_status("ecs", sim.t) == "done"
    sim.run(5)
    assert sim.engine.state("ecs").signal_period == 1  # not counted as a new period


def test_a_battery_cannot_follow_a_signal():
    with pytest.raises(ValueError):
        Device(id="b", name="b", priority=1, kind=DeviceKind.BATTERY, power_w=3000, offpeak_signal=True)


def test_a_device_without_a_schedule_has_no_status():
    e = Engine([Device(id="p", name="p", priority=1, kind=DeviceKind.ON_OFF, power_w=500)])
    assert e.offpeak_status("p", NOW) is None
