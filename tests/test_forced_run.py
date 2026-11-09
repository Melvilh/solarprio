"""The forced run of a car or a battery: charge from the grid now, up to the state-of-charge limit, inside the subscription."""
from datetime import datetime

import pytest

from solarprio import Device, DeviceKind, DeviceReading, Engine

NOW = datetime(2026, 11, 10, 18, 0)


def car(**kw):
    base = dict(id="car", name="car", priority=1, kind=DeviceKind.EV_CHARGER, phases=1, voltage_v=230.0, min_current_a=6.0,
                max_current_a=16.0, soc_max=80.0, min_on_s=0.0, min_off_s=0.0)
    return Device(**{**base, **kw})


def battery(**kw):
    base = dict(id="bat", name="bat", priority=1, kind=DeviceKind.BATTERY, power_w=2000, min_power_w=100, soc_max=90.0,
                min_on_s=0.0, min_off_s=0.0)
    return Device(**{**base, **kw})


def plugged(e, dev="car", soc=40.0, connected=True, measured=None):
    e.set_reading(dev, DeviceReading(soc=soc, connected=connected, measured_w=measured))


def engine(*devices, va=6000.0):
    return Engine(list(devices), subscription_va=va)


def test_a_forced_car_charges_from_the_grid_at_the_most_the_house_allows():
    e = engine(car())
    plugged(e)
    assert e.step(0.0, 0.0, NOW, house_w=1000.0)["car"] == 0  # no surplus, no forced run: nothing
    e.set_forced_run("car", True)
    cmd = e.step(0.0, 10.0, NOW, house_w=1000.0)["car"]
    assert cmd == 16 * 230 and e.mode("car") == "forced"  # room 5000 W: the car takes its 3680 W maximum


def test_the_forced_run_never_goes_over_the_subscription():
    e = engine(car(phases=3), va=6000.0)  # 16 A on 3 phases = 11 kW
    plugged(e)
    e.set_forced_run("car", True)
    cmd = e.step(0.0, 0.0, NOW, house_w=1500.0)["car"]
    assert cmd <= 6000.0 - 1500.0 and cmd == 6 * 690  # room 4500 W: whole amps, 6 A (the minimum) on 3 phases = 4140 W
    assert e.mode("car") == "forced_limited"
    fresh = engine(car(phases=3), va=6000.0)  # a house at 2000 W with the car off: room 4000 W < the 4140 W of the minimum
    plugged(fresh)
    fresh.set_forced_run("car", True)
    assert fresh.step(0.0, 0.0, NOW, house_w=2000.0)["car"] == 0


def test_a_heavy_house_leaves_no_room_so_the_forced_car_waits_without_taking_the_sun_for_nothing():
    e = engine(car())
    plugged(e)
    e.set_forced_run("car", True)
    assert e.step(0.0, 0.0, NOW, house_w=5900.0)["car"] == 0  # 100 W of room: below the 6 A minimum


def test_without_a_view_on_the_house_nothing_is_forced():
    e = engine(car())
    plugged(e)
    e.set_forced_run("car", True)
    assert e.step(0.0, 0.0, NOW, house_w=None)["car"] == 0


def test_without_a_subscription_limit_a_forced_run_is_refused():
    e = Engine([car()])  # no subscription_va
    plugged(e)
    e.set_forced_run("car", True)
    assert e.step(0.0, 0.0, NOW, house_w=1000.0)["car"] == 0
    assert e.mode("car") == "no_cap"


def test_the_forced_run_stops_at_the_soc_limit_and_when_the_car_is_unplugged():
    e = engine(car())
    e.set_forced_run("car", True)
    plugged(e, soc=40.0)
    assert e.step(0.0, 0.0, NOW, house_w=1000.0)["car"] > 0
    plugged(e, soc=80.0)  # at the limit
    assert e.step(0.0, 10.0, NOW, house_w=1000.0)["car"] == 0
    plugged(e, soc=40.0, connected=False)
    assert e.step(0.0, 20.0, NOW, house_w=1000.0)["car"] == 0


def test_a_soc_limit_that_cannot_be_checked_blocks_the_forced_run():
    e = engine(car())
    e.set_forced_run("car", True)
    e.set_reading("car", DeviceReading(connected=True))  # soc_max 80 but no SoC reading
    assert e.step(0.0, 0.0, NOW, house_w=1000.0)["car"] == 0


def test_surplus_only_forbids_the_forced_run():
    e = engine(car(surplus_only=True))
    e.set_forced_run("car", True)
    plugged(e)
    assert e.step(0.0, 0.0, NOW, house_w=1000.0)["car"] == 0


def test_a_forced_battery_charges_from_the_grid_up_to_its_limit():
    e = engine(battery())
    e.set_reading("bat", DeviceReading(soc=50.0))
    e.set_forced_run("bat", True)
    assert e.step(0.0, 0.0, NOW, house_w=1000.0)["bat"] == 2000 and e.mode("bat") == "forced"
    e.set_reading("bat", DeviceReading(soc=95.0))
    assert e.step(0.0, 10.0, NOW, house_w=1000.0)["bat"] == 0


def test_the_forced_car_comes_before_an_off_peak_heater_in_the_room_that_is_left():
    heater = Device(id="ecs", name="ecs", priority=2, kind=DeviceKind.ON_OFF, power_w=2400, temp_max_solar=65.0,
                    temp_hysteresis=3.0, offpeak=("17:00-23:00",), min_on_s=0.0, min_off_s=0.0)
    e = engine(car(), heater, va=6000.0)
    plugged(e)
    e.set_reading("ecs", DeviceReading(temperature=50.0))
    e.set_forced_run("car", True)
    cmd = e.step(0.0, 0.0, NOW, house_w=1500.0)
    assert cmd["car"] == 16 * 230  # 3680 W
    assert cmd["ecs"] == 0  # 6000 - 1500 - 3680 = 820 W left: the heater does not fit


def test_the_switch_of_a_heater_does_not_force_it():
    heater = Device(id="ecs", name="ecs", priority=1, kind=DeviceKind.ON_OFF, power_w=2400, temp_max_solar=65.0,
                    temp_hysteresis=3.0, temp_min=40.0, min_on_s=0.0, min_off_s=0.0)
    e = engine(heater)
    e.set_reading("ecs", DeviceReading(temperature=55.0))  # warm: no sanitary need
    e.set_forced_run("ecs", True)
    assert e.step(0.0, 0.0, NOW, house_w=1000.0)["ecs"] == 0
