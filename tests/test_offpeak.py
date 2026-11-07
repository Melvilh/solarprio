"""Off-peak top-up: in the off-peak windows a device is fed at full power until it stops consuming (it is hot or full),
then the next device in priority order takes its turn. The counter restarts the next day."""
from datetime import datetime, timedelta, timezone

import pytest

from solarprio import Device, DeviceKind, DeviceReading, Engine

BASE = datetime(2026, 11, 10, 0, 0)
NIGHT = ("22:30-06:30",)


def heater(id="ecs", priority=1, **kw):
    return Device(**{**dict(id=id, name=id, priority=priority, kind=DeviceKind.ON_OFF, power_w=2000, offpeak=NIGHT), **kw})


def at(hour, minute=0, day=10):
    return datetime(2026, 11, day, hour, minute)


class Sim:
    """An engine plus loads that draw their rated power when commanded, unless they are ``hot`` (thermostat open)."""

    def __init__(self, devices, start, hot=(), budget=0.0):
        self.engine, self.t, self.hot, self.history = Engine(devices, offpeak_budget_w=budget), start, set(hot), []
        self.rated = {d.id: d.power_w for d in devices}

    def clock(self):
        return (self.t - BASE).total_seconds()

    def run(self, seconds, available=0.0, step_s=5, measure=True):
        cmd = {}
        for _ in range(int(seconds / step_s)):
            for dev_id, rated in self.rated.items():
                drawn = 0.0 if dev_id in self.hot else (rated if self.engine.state(dev_id).power_w > 0 else 0.0)
                self.engine.set_reading(dev_id, DeviceReading(measured_w=drawn) if measure else None)
            cmd = self.engine.step(available, self.clock(), self.t)
            self.history.append((self.t, dict(cmd)))
            self.t += timedelta(seconds=step_s)
        return cmd


def test_a_cold_heater_is_fed_all_night():
    sim = Sim([heater()], at(22, 0))
    assert sim.run(25 * 60)["ecs"] == 0  # window not open yet
    assert sim.run(6 * 60)["ecs"] == 2000  # opened at 22:30
    assert sim.run(5 * 3600)["ecs"] == 2000  # still consuming at 03:30
    assert sim.engine.state("ecs").forced


def test_a_hot_heater_is_tried_briefly_then_left_alone():
    sim = Sim([heater()], at(22, 29), hot={"ecs"})
    assert sim.run(90)["ecs"] == 2000  # inside the grace period: the load gets a chance to start
    cmd = sim.run(120)  # on since 22:30:05, so found finished at 22:32:05
    assert cmd["ecs"] == 0 and sim.engine.offpeak_status("ecs", sim.t) == "done"
    assert sim.run(5 * 3600)["ecs"] == 0  # and it stays off for the rest of the night
    assert all(c["ecs"] == 0 for t, c in sim.history if t > at(22, 33))


def test_the_thermostat_cutting_in_the_middle_of_the_night_ends_the_top_up():
    sim = Sim([heater()], at(22, 30))
    assert sim.run(3 * 3600)["ecs"] == 2000
    sim.hot.add("ecs")  # tank reached its setpoint
    sim.run(30)  # one more reading cycle
    cmd = sim.run(30)
    assert cmd["ecs"] == 0 and sim.engine.offpeak_status("ecs", sim.t) == "done"


def test_the_next_device_takes_over_when_the_first_is_finished():
    sim = Sim([heater("ecs", 1), heater("radiator", 2, power_w=1500)], at(22, 30), hot={"ecs"})
    cmd = sim.run(60)
    assert cmd == {"ecs": 2000, "radiator": 0}  # one at a time, in priority order
    cmd = sim.run(120)  # ecs found hot after the grace period
    assert cmd == {"ecs": 0, "radiator": 1500}
    # the handover happens in the very step that finds the first one finished: nobody is left idle waiting
    first_radiator = next(t for t, c in sim.history if c["radiator"] > 0)
    ecs_was_on = False
    for t, c in sim.history:
        ecs_was_on = ecs_was_on or c["ecs"] > 0
        if ecs_was_on and c["ecs"] == 0:
            assert t == first_radiator
            break
    else:
        pytest.fail("ecs never stopped")


def test_devices_are_never_topped_up_together():
    sim = Sim([heater("ecs", 1), heater("radiator", 2, power_w=1500)], at(23, 0))
    sim.run(6 * 3600)
    assert all(not (c["ecs"] > 0 and c["radiator"] > 0) for _, c in sim.history)


def test_the_next_day_it_is_topped_up_again():
    sim = Sim([heater()], at(22, 30), hot={"ecs"})
    sim.run(10 * 60)
    assert sim.engine.offpeak_status("ecs", sim.t) == "done"
    sim.t = at(22, 20, day=11)
    sim.hot.clear()
    assert sim.run(15 * 60)["ecs"] == 2000  # the window opens at 22:30 the next day


def test_midnight_does_not_reset_but_the_end_of_the_window_does():
    sim = Sim([heater()], at(23, 0), hot={"ecs"})
    sim.run(5 * 60)
    sim.t = at(0, 30, day=11)
    assert sim.run(5 * 60)["ecs"] == 0  # still the same night: finished stays finished
    sim.t = at(6, 20, day=11)
    sim.run(20 * 60)  # across 06:30: a new period begins (but the window is closed)
    assert sim.engine.offpeak_status("ecs", sim.t) == "waiting"


def test_with_two_windows_a_device_finished_at_night_is_not_tried_again_at_midday_unless_reset_at_says_so():
    sim = Sim([heater(offpeak=("22:30-06:30", "12:30-14:30"))], at(22, 30), hot={"ecs"})
    sim.run(10 * 60)
    sim.t = at(12, 40, day=11)
    assert sim.run(10 * 60)["ecs"] == 0
    sim = Sim([heater(offpeak=("22:30-06:30", "12:30-14:30"), reset_at="12:00")], at(22, 30), hot={"ecs"})
    sim.run(10 * 60)
    sim.t = at(12, 40, day=11)
    assert sim.run(60)["ecs"] == 2000


def test_nothing_is_forced_without_a_measured_power():
    sim = Sim([heater()], at(23, 0))
    assert sim.run(10 * 60, measure=False)["ecs"] == 0


def test_no_top_up_by_day_without_a_clock_or_when_disabled():
    assert Sim([heater()], at(12, 0)).run(10 * 60)["ecs"] == 0
    sim = Sim([heater()], at(23, 0))
    assert sim.engine.step(0.0, 0.0)["ecs"] == 0  # no wall clock
    assert Sim([heater(enabled=False)], at(23, 0)).run(60)["ecs"] == 0


def test_top_up_power_is_taken_out_of_what_the_others_share():
    dimmer = Device(id="dim", name="Dimmer", priority=0, kind=DeviceKind.PROPORTIONAL, power_w=1500)
    sim = Sim([dimmer, heater(offpeak=("12:00-14:00",))], at(12, 30))
    cmd = sim.run(5, available=2500)
    assert cmd == {"dim": 500.0, "ecs": 2000.0}  # the higher priority did not take the sun the heater needs


def test_a_finished_device_goes_back_to_taking_the_surplus():
    sim = Sim([heater(offpeak=("12:00-14:00",))], at(12, 30), hot={"ecs"})
    sim.run(5 * 60)
    assert sim.engine.offpeak_status("ecs", sim.t) == "done"
    sim.hot.clear()
    assert sim.run(30, available=2500)["ecs"] == 2000  # sun heats it, like any surplus load


def test_a_slow_start_is_not_mistaken_for_a_finished_device():
    """Measured power is 0 for the first 100 s (slow sensor): still inside the grace period."""
    sim = Sim([heater()], at(22, 30))
    sim.hot.add("ecs")
    sim.run(100)
    sim.hot.clear()
    sim.run(120)
    assert sim.engine.state("ecs").power_w == 2000 and sim.engine.offpeak_status("ecs", sim.t) == "heating"


def test_the_finished_threshold_defaults_to_five_percent_and_can_be_set():
    sim = Sim([heater()], at(22, 30))
    sim.rated["ecs"] = 90  # 4.5 % of 2000 W: standby draw of a hot tank's electronics
    assert sim.run(300)["ecs"] == 0
    sim = Sim([heater(done_below_w=50)], at(22, 30))
    sim.rated["ecs"] = 90
    assert sim.run(300)["ecs"] == 2000


def test_min_off_time_is_respected_when_the_window_opens():
    sim = Sim([heater(min_off_s=1800)], at(22, 20))
    sim.run(10, available=2500)  # the sun turns it on...
    sim.run(5)  # ...and it is off again: a 30 minute rest starts
    assert sim.run(25 * 60)["ecs"] == 0  # 22:45, window open but still resting
    assert sim.run(6 * 60)["ecs"] == 2000  # 22:51


def test_an_unplugged_car_is_skipped_and_the_next_device_is_used():
    car = Device(id="car", name="Car", priority=1, kind=DeviceKind.EV_CHARGER, offpeak=NIGHT)
    sim = Sim([car, heater("ecs", 2)], at(23, 0))
    sim.engine.set_reading("car", DeviceReading(measured_w=0.0, connected=False))
    sim.engine.set_reading("ecs", DeviceReading(measured_w=0.0))
    cmd = sim.engine.step(0.0, sim.clock(), sim.t)
    assert cmd["car"] == 0 and cmd["ecs"] == 2000


def test_reset_keeps_a_device_found_finished_tonight():
    sim = Sim([heater()], at(23, 0), hot={"ecs"})
    sim.run(5 * 60)
    sim.engine.reset()
    assert sim.engine.offpeak_status("ecs", sim.t) == "done"


def test_timezone_aware_local_time_uses_the_wall_clock():
    e = Engine([heater()])
    e.set_reading("ecs", DeviceReading(measured_w=0.0))
    assert e.step(0.0, 0.0, datetime(2026, 11, 10, 23, 0, tzinfo=timezone(timedelta(hours=1))))["ecs"] == 2000


@pytest.mark.parametrize("kw", [
    {"offpeak": ("25:00-06:00",)}, {"offpeak": ("22:00",)}, {"offpeak": ("22:00-22:00",)}, {"offpeak": ("a-b",)},
    {"reset_at": "7h"}, {"done_below_w": -1.0}, {"done_below_w": 5000.0}, {"done_after_s": -1.0},
    {"kind": DeviceKind.BATTERY},
])
def test_invalid_settings_are_refused(kw):
    with pytest.raises(ValueError):
        heater(**kw)


# ---------------------------------------------------------------- several devices at once (company sites)

def fleet(n=4, power=7000, **kw):
    return [heater(f"c{i}", i, power_w=power, **kw) for i in range(1, n + 1)]


def test_a_budget_lets_several_devices_be_topped_up_together_in_priority_order():
    sim = Sim(fleet(4), at(23, 0), budget=21000)  # 4 chargers of 7 kW, 21 kW available at night
    cmd = sim.run(30)
    assert cmd == {"c1": 7000, "c2": 7000, "c3": 7000, "c4": 0}
    assert sum(cmd.values()) <= 21000


def test_the_first_device_always_starts_even_if_it_exceeds_the_budget():
    sim = Sim(fleet(2), at(23, 0), budget=3000)
    assert sim.run(30) == {"c1": 7000, "c2": 0}


def test_a_device_that_does_not_fit_waits_and_a_smaller_one_below_it_may_start():
    devices = [heater("big", 1, power_w=7000), heater("huge", 2, power_w=7000), heater("small", 3, power_w=2000)]
    sim = Sim(devices, at(23, 0), budget=10000)
    assert sim.run(30) == {"big": 7000, "huge": 0, "small": 2000}


def test_a_finished_device_frees_its_share_of_the_budget_at_once():
    sim = Sim(fleet(3), at(22, 30), hot={"c1"}, budget=14000)
    first = sim.run(60)
    assert first == {"c1": 7000, "c2": 7000, "c3": 0}
    cmd = sim.run(120)  # c1 found hot after the grace period
    assert cmd == {"c1": 0, "c2": 7000, "c3": 7000}


def test_without_a_budget_devices_are_still_one_at_a_time():
    sim = Sim(fleet(3), at(23, 0))
    assert sim.run(30) == {"c1": 7000, "c2": 0, "c3": 0}


def test_the_budget_cannot_be_negative():
    with pytest.raises(ValueError):
        Engine([], offpeak_budget_w=-1)


def test_the_power_of_all_topped_up_devices_is_taken_out_of_the_sun():
    dimmer = Device(id="dim", name="Dimmer", priority=0, kind=DeviceKind.PROPORTIONAL, power_w=9000)
    sim = Sim([dimmer, *fleet(2, offpeak=("12:00-14:00",))], at(12, 30), budget=14000)
    assert sim.run(5, available=16000) == {"dim": 2000.0, "c1": 7000.0, "c2": 7000.0}
