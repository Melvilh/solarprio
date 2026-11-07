"""The task category: a "go" signal for computing tasks. It switches nothing, follows the surplus or the off-peak periods,
and needs no power measurement."""
from datetime import datetime, timedelta

import pytest

from solarprio import Device, DeviceKind, DeviceReading, Engine

BASE = datetime(2026, 11, 10, 0, 0)
NIGHT = ("22:30-06:30",)


def at(hour, minute=0):
    return datetime(2026, 11, 10, hour, minute)


def clock(t):
    return (t - BASE).total_seconds()


def task(id="ia", priority=1, power_w=100, **kw):
    return Device(id=id, name=id, priority=priority, kind=DeviceKind.TASK, power_w=power_w, **kw)


def heater(id="ecs", priority=2, **kw):
    return Device(id=id, name=id, priority=priority, kind=DeviceKind.ON_OFF, power_w=2000, **kw)


def test_a_task_follows_the_surplus_like_an_on_off_load():
    e = Engine([task(start_margin_w=50, stay_tolerance_w=30, min_on_s=300)])
    assert e.step(120, 0.0)["ia"] == 0  # 100 W + 50 W margin needed
    assert e.step(150, 10.0)["ia"] == 100
    assert e.step(75, 20.0)["ia"] == 100  # stays within the tolerance (100 - 30) ...
    assert e.step(0, 30.0)["ia"] == 100  # ... and the minimum run time holds it on
    assert e.step(0, 400.0)["ia"] == 0


def test_a_task_is_fed_during_off_peak_without_any_measurement():
    e = Engine([task(offpeak=NIGHT)])
    assert e.step(0.0, clock(at(12)), at(12))["ia"] == 0
    assert e.step(0.0, clock(at(23)), at(23))["ia"] == 100  # no reading, no measured power: still a go
    assert e.state("ia").forced
    morning = datetime(2026, 11, 11, 7, 0)  # the next morning (time only moves forward)
    assert e.step(0.0, clock(morning), morning)["ia"] == 0


def test_a_task_follows_an_off_peak_signal_and_never_a_doubtful_one():
    e = Engine([task(offpeak_signal=True)])
    t = at(12)
    for signal, expected in ((True, 100), (False, 0), (None, 0)):
        e.set_reading("ia", DeviceReading(offpeak=signal))
        t += timedelta(minutes=10)
        assert e.step(0.0, clock(t), t)["ia"] == expected, signal
    e.set_reading("ia", None)
    assert e.step(0.0, clock(t + timedelta(minutes=10)), t + timedelta(minutes=10))["ia"] == 0


def test_a_task_is_never_finished_it_stays_on_for_the_whole_off_peak_period():
    e = Engine([task(offpeak=NIGHT)])
    t = at(23)
    for _ in range(120):  # two hours, a measured power of 0 would have meant "finished" for a heater
        e.set_reading("ia", DeviceReading(measured_w=0.0))
        assert e.step(0.0, clock(t), t)["ia"] == 100
        t += timedelta(minutes=1)
    assert e.offpeak_status("ia", t) == "heating"


def test_tasks_do_not_take_the_turn_or_the_budget_of_the_heaters():
    """A heater is still topped up (one at a time) and the task is on as well."""
    e = Engine([task(offpeak=NIGHT), heater("a", 2, offpeak=NIGHT), heater("b", 3, offpeak=NIGHT)])
    t = at(23)
    for dev in ("a", "b"):
        e.set_reading(dev, DeviceReading(measured_w=0.0))
    cmd = e.step(0.0, clock(t), t)
    assert cmd == {"ia": 100, "a": 2000, "b": 0}  # the task did not make the first heater wait


def test_the_power_of_a_forced_task_is_taken_out_of_the_sun():
    e = Engine([task(offpeak=("12:00-14:00",), power_w=300), Device(id="dim", name="d", priority=2, kind=DeviceKind.PROPORTIONAL, power_w=2000)])
    cmd = e.step(1000.0, clock(at(12, 30)), at(12, 30))
    assert cmd == {"ia": 300, "dim": 700.0}


def test_no_clock_means_no_forced_task_but_the_sun_still_works():
    e = Engine([task(offpeak=NIGHT)])
    assert e.step(0.0, 0.0)["ia"] == 0
    assert e.step(500.0, 10.0)["ia"] == 100


def test_a_task_needs_no_measured_power_and_no_energy_target_settings():
    Device(id="ia", name="ia", priority=1, kind="task", power_w=100, offpeak=NIGHT)  # accepted as is
    with pytest.raises(ValueError):
        Device(id="ia", name="ia", priority=1, kind="task", power_w=0)  # an estimate of the tasks' power is still required
