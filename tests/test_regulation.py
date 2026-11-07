"""Central regulation of heaters and variable loads: tank temperatures, sanitary minimum, subscription cap, smooth ramps,
emergency cut. All decisions live in the engine; the device only executes a power."""
from datetime import datetime

import pytest

from solarprio import Device, DeviceKind, DeviceReading, Engine

NOW = datetime(2026, 11, 10, 14, 0)
NIGHT = datetime(2026, 11, 10, 23, 0)


def heater(id="ecs", priority=1, kind=DeviceKind.PROPORTIONAL, **kw):
    base = dict(id=id, name=id, priority=priority, kind=kind, power_w=2400, temp_max_solar=65.0, temp_max_offpeak=60.0,
                temp_hysteresis=3.0, temp_min=40.0)
    if kind is DeviceKind.PROPORTIONAL:
        base["min_power_w"] = 15.0
    return Device(**{**base, **kw})


def read(e, dev="ecs", temp=50.0, measured=None, offpeak=None):
    e.set_reading(dev, DeviceReading(temperature=temp, measured_w=measured, offpeak=offpeak))


# ------------------------------------------------------------------ tank temperature, with the sun

def test_the_sun_heats_until_the_solar_maximum_then_waits_for_the_hysteresis():
    e = Engine([heater(min_on_s=600)])
    read(e, temp=60.0)
    assert e.step(2000, 0.0)["ecs"] == 2000 and e.mode("ecs") == "solar"
    read(e, temp=66.0)  # above 65: stop at once, the minimum run time does not hold a hot tank on
    assert e.step(2000, 5.0)["ecs"] == 0 and e.mode("ecs") == "hot"
    read(e, temp=63.0)  # inside the hysteresis band: still waiting
    assert e.step(2000, 10.0)["ecs"] == 0
    read(e, temp=61.9)  # below 65 - 3: heats again
    assert e.step(2000, 700.0)["ecs"] == 2000


def test_an_unknown_temperature_is_a_sensor_fault_and_nothing_is_fed():
    e = Engine([heater()])
    e.set_reading("ecs", DeviceReading())  # no temperature
    assert e.step(2000, 0.0)["ecs"] == 0 and e.mode("ecs") == "sensor_fault"
    e.set_reading("ecs", DeviceReading(temperature=float("nan")))
    assert e.step(2000, 5.0)["ecs"] == 0
    e.set_reading("ecs", None)
    assert e.step(2000, 10.0)["ecs"] == 0
    read(e, temp=50.0)
    assert e.step(2000, 15.0)["ecs"] == 2000  # back to normal when the reading is back


def test_a_device_without_temperature_settings_is_not_affected_by_a_missing_reading():
    e = Engine([Device(id="p", name="p", priority=1, kind=DeviceKind.ON_OFF, power_w=800)])
    assert e.step(1000, 0.0)["p"] == 800


# ------------------------------------------------------------------ off-peak top-up and the tank temperature

def test_off_peak_heats_until_the_off_peak_maximum_without_any_power_measurement():
    e = Engine([heater(offpeak=("22:30-06:30",))])
    read(e, temp=50.0)  # no measured power: the temperature is enough to tell when to stop
    assert e.step(0.0, 0.0, NIGHT)["ecs"] == 2400 and e.mode("ecs") == "offpeak"
    read(e, temp=61.0)  # above the off-peak limit of 60
    assert e.step(0.0, 5.0, NIGHT)["ecs"] == 0
    read(e, temp=58.0)  # inside the band
    assert e.step(0.0, 10.0, NIGHT)["ecs"] == 0
    read(e, temp=56.0)  # below 60 - 3
    assert e.step(0.0, 700.0, NIGHT)["ecs"] == 2400


def test_between_the_two_maximums_the_sun_can_still_heat():
    """Off-peak stops at 60, the sun goes on up to 65."""
    e = Engine([heater(offpeak=("22:30-06:30",))])
    read(e, temp=61.0)
    assert e.step(1500, 0.0, NIGHT)["ecs"] == 1500  # not forced, but the surplus is used
    read(e, temp=66.0)
    assert e.step(1500, 5.0, NIGHT)["ecs"] == 0


def test_the_consumption_criterion_still_ends_a_top_up_when_the_thermostat_cuts():
    e = Engine([heater(offpeak=("22:30-06:30",), done_after_s=60)])
    t = 0.0
    for _ in range(40):
        read(e, temp=50.0, measured=0.0)  # the tank thermostat opened: nothing is drawn
        e.step(0.0, t, NIGHT)
        t += 5.0
    assert e.offpeak_status("ecs", NIGHT) == "done" and e.state("ecs").power_w == 0


def test_surplus_only_forbids_every_grid_feeding():
    e = Engine([heater(offpeak=("22:30-06:30",), surplus_only=True)])
    read(e, temp=30.0)  # far under the sanitary minimum
    assert e.step(0.0, 0.0, NIGHT)["ecs"] == 0
    assert e.step(500.0, 5.0, NIGHT)["ecs"] == 500  # the sun is still welcome


# ------------------------------------------------------------------ sanitary minimum

def test_a_cold_tank_is_heated_from_the_grid_whatever_the_sun_until_the_hysteresis():
    e = Engine([heater()])
    read(e, temp=39.0)
    assert e.step(0.0, 0.0, NOW)["ecs"] == 2400 and e.mode("ecs") == "sanitary"
    read(e, temp=42.0)  # between 40 and 40 + 3: keeps going
    assert e.step(0.0, 5.0, NOW)["ecs"] == 2400
    read(e, temp=43.5)
    assert e.step(0.0, 10.0, NOW)["ecs"] == 0


def test_the_sanitary_minimum_needs_a_known_temperature_and_a_clock():
    e = Engine([heater()])
    read(e, temp=39.0)
    assert e.step(0.0, 0.0)["ecs"] == 0  # no clock = grid measurement lost: nothing from the grid
    e.set_reading("ecs", DeviceReading())
    assert e.step(0.0, 5.0, NOW)["ecs"] == 0  # no temperature: fault, nothing


def test_the_sanitary_minimum_only_exists_if_it_is_set():
    e = Engine([heater(temp_min=None)])
    read(e, temp=10.0)
    assert e.step(0.0, 0.0, NOW)["ecs"] == 0


# ------------------------------------------------------------------ the subscription cap

def capped(*devices, va=5700.0):
    return Engine(list(devices), subscription_va=va)


def test_the_cap_is_the_subscription_minus_the_rest_of_the_house():
    e = capped(heater())
    read(e, temp=30.0, measured=0.0)
    assert e.step(0.0, 0.0, NOW, house_w=3000.0)["ecs"] == 2400  # 2700 W of room: the full heater
    e = capped(heater())
    read(e, temp=30.0, measured=0.0)
    assert e.step(0.0, 0.0, NOW, house_w=4550.0)["ecs"] == 1100  # 1150 W of room, rounded down to the 100 W step
    e = capped(heater())
    read(e, temp=30.0, measured=0.0)
    assert e.step(0.0, 0.0, NOW, house_w=5600.0)["ecs"] == 0  # under 150 W of room: nothing
    assert e.mode("ecs") == "sanitary_limited"


def test_a_load_that_does_not_fit_the_last_few_watts_of_room_stays_off():
    small = heater("small", 1, kind=DeviceKind.ON_OFF, power_w=100, temp_min=40.0)
    e = capped(small)
    read(e, "small", temp=30.0, measured=0.0)
    assert e.step(0.0, 0.0, NOW, house_w=5560.0)["small"] == 0  # 140 W of room: below the 150 W worth feeding
    assert e.step(0.0, 5.0, NOW, house_w=5500.0)["small"] == 100  # 200 W of room: fits


def test_what_the_heater_itself_draws_is_not_counted_as_the_rest_of_the_house():
    e = capped(heater())
    read(e, temp=30.0, measured=0.0)
    e.step(0.0, 0.0, NOW, house_w=3000.0)  # heater commanded 2400
    read(e, temp=30.0, measured=2400.0)  # the house now shows 5400 with the heater running: 3000 W for the rest
    assert e.step(0.0, 100.0, NOW, house_w=5400.0)["ecs"] == 2400  # no hunting


def test_without_a_view_on_the_house_nothing_is_fed_from_the_grid_and_the_sun_is_not_used_either_for_sanitary():
    e = capped(heater())
    read(e, temp=30.0, measured=0.0)
    assert e.step(2000.0, 0.0, NOW, house_w=None)["ecs"] == 0  # sanitary blocked blind, even with surplus


def test_off_peak_falls_back_to_the_sun_when_the_cap_leaves_no_room():
    e = capped(heater(offpeak=("22:30-06:30",), temp_min=None))
    read(e, temp=50.0, measured=0.0)
    assert e.step(800.0, 0.0, NIGHT, house_w=5650.0)["ecs"] == 800  # no room from the grid, the surplus is used


def test_a_clear_overshoot_lets_go_of_the_grid_fed_load_for_a_minute():
    e = capped(heater())
    read(e, temp=30.0, measured=0.0)
    assert e.step(0.0, 0.0, NOW, house_w=3000.0)["ecs"] == 2400
    read(e, temp=30.0, measured=2400.0)
    assert e.step(0.0, 10.0, NOW, house_w=6000.0)["ecs"] == 0  # above 5700 + 200 while running
    assert e.step(0.0, 40.0, NOW, house_w=3000.0)["ecs"] == 0  # still waiting
    read(e, temp=30.0, measured=0.0)
    assert e.step(0.0, 75.0, NOW, house_w=3000.0)["ecs"] == 2400  # a minute later it resumes


def test_the_subscription_cut_is_immediate_whatever_the_minimum_run_time():
    """A safety cut must not be held back by a comfort timer."""
    e = capped(heater(min_on_s=600))
    read(e, temp=30.0, measured=0.0)
    assert e.step(0.0, 0.0, NOW, house_w=3000.0)["ecs"] == 2400
    read(e, temp=30.0, measured=2400.0)
    assert e.step(0.0, 10.0, NOW, house_w=6000.0)["ecs"] == 0  # overshoot
    e2 = capped(heater(min_on_s=600))
    read(e2, temp=30.0, measured=0.0)
    e2.step(0.0, 0.0, NOW, house_w=3000.0)
    assert e2.step(0.0, 10.0, NOW, house_w=None)["ecs"] == 0  # the house power is lost
    e3 = capped(heater(min_on_s=600))
    read(e3, temp=30.0, measured=0.0)
    e3.step(0.0, 0.0, NOW, house_w=3000.0)
    read(e3, temp=30.0, measured=2400.0)
    assert e3.step(0.0, 10.0, NOW, house_w=5800.0)["ecs"] == 2300  # the rest of the house is 3400 W: 2300 W of room, at once


def test_a_start_from_the_grid_still_honours_the_minimum_rest_time():
    e = capped(heater(min_off_s=600))
    read(e, temp=50.0, measured=0.0)
    e.step(1000.0, 0.0, NOW, house_w=1000.0)  # runs on the sun
    e.step(0.0, 10.0, NOW, house_w=1000.0)  # and stops
    read(e, temp=30.0, measured=0.0)
    assert e.step(0.0, 20.0, NOW, house_w=1000.0)["ecs"] == 0  # cold now, but it just stopped: rests first
    assert e.step(0.0, 700.0, NOW, house_w=1000.0)["ecs"] == 2400


def test_an_adjustable_grid_fed_load_does_not_creep_up_by_small_steps():
    e = capped(heater())
    read(e, temp=30.0, measured=0.0)
    assert e.step(0.0, 0.0, NOW, house_w=4550.0)["ecs"] == 1100  # 1150 W of room, rounded down
    read(e, temp=30.0, measured=1100.0)
    assert e.step(0.0, 10.0, NOW, house_w=5600.0)["ecs"] == 1100  # the rest of the house is 4500 W: 1200 W of room, a rise of 100 W only
    assert e.step(0.0, 20.0, NOW, house_w=5650.0)["ecs"] == 1100  # the rest is 4550 W again
    assert e.step(0.0, 30.0, NOW, house_w=5750.0)["ecs"] == 1000  # less room: down at once
    read(e, temp=30.0, measured=1000.0)
    assert e.step(0.0, 40.0, NOW, house_w=4000.0)["ecs"] == 2400  # a real rise goes through (3000 W for the rest)


def test_an_on_off_load_either_fits_or_stays_off_and_two_heaters_share_the_room_by_priority():
    a = heater("a", 1, kind=DeviceKind.ON_OFF, power_w=2000, temp_min=40.0)
    b = heater("b", 2, kind=DeviceKind.ON_OFF, power_w=2000, temp_min=40.0)
    e = capped(a, b)
    for dev in "ab":
        read(e, dev, temp=30.0, measured=0.0)
    cmd = e.step(0.0, 0.0, NOW, house_w=2500.0)  # 3200 W of room: one heater of 2000 W, not two
    assert cmd == {"a": 2000.0, "b": 0.0}
    assert e.mode("b") == "sanitary_limited"


def test_no_subscription_means_no_cap():
    e = Engine([heater()])
    read(e, temp=30.0)
    assert e.step(0.0, 0.0, NOW)["ecs"] == 2400  # no house power needed


# ------------------------------------------------------------------ smooth regulation

def test_an_increase_waits_for_the_hold_time_and_a_decrease_for_half_of_it():
    e = Engine([Device(id="d", name="d", priority=1, kind=DeviceKind.PROPORTIONAL, power_w=2400, min_power_w=15, hold_s=8.0)])
    assert e.step(1000, 0.0)["d"] == 1000
    assert e.step(1500, 4.0)["d"] == 1000  # a change was made 4 s ago: wait
    assert e.step(1500, 8.1)["d"] == 1500
    assert e.step(1000, 10.0)["d"] == 1500  # decreases wait for half of the hold time: 4 s
    assert e.step(1000, 12.2)["d"] == 1000


def test_the_steps_up_are_limited_and_small_changes_are_ignored():
    e = Engine([Device(id="d", name="d", priority=1, kind=DeviceKind.PROPORTIONAL, power_w=2400, min_power_w=15,
                       ramp_up_w=200.0, deadband_w=15.0)])
    assert e.step(2000, 0.0)["d"] == 200  # starts at one step
    assert e.step(2000, 5.0)["d"] == 400
    assert e.step(405, 10.0)["d"] == 400  # 5 W: inside the dead band
    assert e.step(100, 15.0)["d"] == 100  # a decrease is immediate and complete
    assert e.step(0, 20.0)["d"] == 0  # going to zero is never ignored


def test_the_ramp_never_starts_below_the_minimum_power():
    e = Engine([Device(id="d", name="d", priority=1, kind=DeviceKind.PROPORTIONAL, power_w=2400, min_power_w=300, ramp_up_w=100.0)])
    assert e.step(2000, 0.0)["d"] == 300


def test_without_these_settings_nothing_changes():
    e = Engine([Device(id="d", name="d", priority=1, kind=DeviceKind.PROPORTIONAL, power_w=2400)])
    assert [e.step(w, t)["d"] for t, w in enumerate((1000, 1500, 1400, 0))] == [1000, 1500, 1400, 0]


# ------------------------------------------------------------------ emergency cut

def test_a_clear_grid_import_cuts_everything_that_runs_on_the_sun_at_once():
    e = Engine([heater(temp_min=None, min_on_s=600, ramp_up_w=200.0)], emergency_import_w=250.0)
    read(e, temp=50.0)
    for t in (0.0, 5.0, 10.0):
        e.step(2000, t, import_w=0.0)
    assert e.state("ecs").power_w > 0
    assert e.step(2000, 15.0, import_w=400.0)["ecs"] == 0  # no timer holds it
    assert e.step(2000, 20.0, import_w=0.0)["ecs"] > 0  # and it restarts, softly
    assert e.state("ecs").power_w <= 200.0


def test_the_emergency_cut_ignores_what_grid_fed_devices_draw_on_purpose():
    """A heater fed from the grid at night draws 2400 W on purpose; a device running on the sun must not be cut for it."""
    pump = Device(id="pump", name="pump", priority=2, kind=DeviceKind.ON_OFF, power_w=500)
    e = Engine([heater(temp_min=None, offpeak=("22:30-06:30",)), pump], emergency_import_w=250.0)
    read(e, temp=50.0, measured=0.0)
    cmd = e.step(600.0, 0.0, NIGHT, import_w=0.0)
    assert cmd == {"ecs": 2400, "pump": 0.0}  # the surplus (600 W) is taken out by the heater's share first
    e2 = Engine([heater(temp_min=None, offpeak=("22:30-06:30",)), pump], emergency_import_w=250.0)
    read(e2, temp=50.0, measured=0.0)
    e2.step(3500.0, 0.0, NIGHT, import_w=0.0)
    assert e2.state("pump").power_w == 500  # running on the 1100 W of sun left after the heater
    read(e2, temp=50.0, measured=2400.0)
    assert e2.step(3500.0, 5.0, NIGHT, import_w=2400.0)["pump"] == 500  # 2400 W imported by the heater: not an emergency
    assert e2.step(3500.0, 10.0, NIGHT, import_w=2800.0)["pump"] == 0  # 400 W more than the heater: it is


def test_no_emergency_setting_or_no_import_figure_means_no_cut():
    e = Engine([Device(id="p", name="p", priority=1, kind=DeviceKind.ON_OFF, power_w=500)])
    e.step(600, 0.0)
    assert e.step(600, 5.0, import_w=5000.0)["p"] == 500


# ------------------------------------------------------------------ several heaters, windows and signals

def test_several_heaters_share_the_sun_and_a_hot_one_gives_way_to_the_next():
    e = Engine([heater("a", 1, temp_min=None), heater("b", 2, temp_min=None)])
    read(e, "a", temp=50.0)
    read(e, "b", temp=50.0)
    assert e.step(3000, 0.0) == {"a": 2400, "b": 600}
    read(e, "a", temp=66.0)  # a is hot
    assert e.step(3000, 5.0) == {"a": 0, "b": 2400}


def test_windows_and_a_signal_together_both_have_to_say_off_peak():
    e = Engine([Device(id="d", name="d", priority=1, kind=DeviceKind.PROPORTIONAL, power_w=2000, min_power_w=10,
                       offpeak=("22:30-06:30",), offpeak_signal=True)])
    t = 0.0
    for local, signal, expected in ((NIGHT, True, 2000), (NIGHT, False, 0), (NOW, True, 0), (NOW, False, 0)):
        e.set_reading("d", DeviceReading(measured_w=0.0, offpeak=signal))
        t += 700.0
        assert e.step(0.0, t, local)["d"] == expected, (local, signal)


def test_the_temperature_memory_survives_a_reset():
    e = Engine([heater()])
    read(e, temp=66.0)
    e.step(0, 0.0)
    e.reset()
    read(e, temp=64.0)  # inside the band: still "hot", it did not forget
    assert e.step(2000, 5.0)["ecs"] == 0


# ------------------------------------------------------------------ settings are checked

@pytest.mark.parametrize("kw", [
    {"kind": DeviceKind.BATTERY}, {"kind": DeviceKind.EV_CHARGER}, {"kind": DeviceKind.TASK},
    {"temp_max_solar": 200.0}, {"temp_hysteresis": -1.0}, {"temp_min": 62.0},  # minimum + hysteresis not under the maximum
    {"hold_s": -1.0}, {"deadband_w": -5.0}, {"ramp_up_w": 0.0},
])
def test_invalid_regulation_settings_are_refused(kw):
    base = dict(id="d", name="d", priority=1, kind=DeviceKind.PROPORTIONAL, power_w=2400, temp_max_solar=65.0, temp_min=40.0)
    with pytest.raises(ValueError):
        Device(**{**base, **kw})


def test_engine_limits_must_not_be_negative():
    for kw in ({"subscription_va": -1.0}, {"emergency_import_w": -5.0}):
        with pytest.raises(ValueError):
            Engine([], **kw)
