import pytest

from solarprio import Device, DeviceKind, DeviceReading, Engine, available_from_export


def battery(**kw):
    base = dict(id="bat", name="Battery", priority=1, kind=DeviceKind.BATTERY, power_w=3000, min_power_w=200)
    return Device(**{**base, **kw})


def ev(**kw):
    base = dict(id="ev", name="Car", priority=1, kind=DeviceKind.EV_CHARGER, phases=1, voltage_v=230,
                min_current_a=6, max_current_a=16)
    return Device(**{**base, **kw})


def heater(**kw):
    base = dict(id="heater", name="Heater", priority=2, kind=DeviceKind.ON_OFF, power_w=2000)
    return Device(**{**base, **kw})


# ---------------------------------------------------------------- battery

def test_battery_absorbs_surplus_up_to_its_max_charge_power():
    engine = Engine([battery()])
    assert engine.step(1500, now=0)["bat"] == 1500
    assert engine.step(5000, now=1)["bat"] == 3000
    assert engine.step(100, now=2)["bat"] == 0  # below its minimum charge power


def test_battery_priority_decides_whether_loads_or_battery_come_first():
    first = Engine([battery(priority=1), heater(priority=2)])
    assert first.step(4000, now=0) == {"bat": 3000, "heater": 0}
    second = Engine([battery(priority=2), heater(priority=1)])
    assert second.step(4000, now=0) == {"heater": 2000, "bat": 2000}


def test_battery_stops_at_soc_limit_and_resumes_with_hysteresis():
    engine = Engine([battery(soc_max=90, soc_resume_margin=3)])
    engine.set_reading("bat", DeviceReading(soc=80))
    assert engine.step(2000, now=0)["bat"] == 2000
    engine.set_reading("bat", DeviceReading(soc=90))
    assert engine.step(2000, now=1)["bat"] == 0
    engine.set_reading("bat", DeviceReading(soc=88))  # between 87 and 90: still blocked
    assert engine.step(2000, now=2)["bat"] == 0
    engine.set_reading("bat", DeviceReading(soc=87))
    assert engine.step(2000, now=3)["bat"] == 2000


def test_full_battery_frees_the_surplus_for_lower_priorities():
    engine = Engine([battery(priority=1), heater(priority=2)])
    engine.set_reading("bat", DeviceReading(soc=100))
    assert engine.step(2500, now=0) == {"bat": 0, "heater": 2000}


def test_soc_limit_overrides_min_on_time():
    engine = Engine([battery(min_on_s=600, soc_max=95)])
    engine.set_reading("bat", DeviceReading(soc=50))
    assert engine.step(2000, now=0)["bat"] == 2000
    engine.set_reading("bat", DeviceReading(soc=95))
    assert engine.step(2000, now=10)["bat"] == 0  # not held on by min_on_s: safety limit wins


def test_unknown_soc_with_a_limit_means_no_charge_without_a_limit_means_charge():
    limited = Engine([battery(soc_max=90)])
    assert limited.step(2000, now=0)["bat"] == 0
    unlimited = Engine([battery(soc_max=100)])
    assert unlimited.step(2000, now=0)["bat"] == 2000


def test_tapering_battery_frees_surplus_only_after_the_settle_time():
    """The battery is commanded 3000 W but only takes 1000 W (near full). The heater (1500 W) is below it."""
    engine = Engine([battery(priority=1, settle_s=30), heater(priority=2, power_w=1500)])
    engine.set_reading("bat", DeviceReading(measured_w=1000, soc=96))
    assert engine.step(4000, now=0) == {"bat": 3000, "heater": 0}  # remaining 1000 W < 1500 W
    assert engine.step(4000, now=10)["heater"] == 0  # too early to trust the lower measurement
    # settled: the battery is expected to absorb 1000 W, the other 2000 W are free for the heater
    assert engine.step(4000, now=30)["heater"] == 1500


def test_battery_measured_above_command_never_increases_what_it_is_charged_with():
    engine = Engine([battery(priority=1, settle_s=0), heater(priority=2, power_w=1500)])
    engine.set_reading("bat", DeviceReading(measured_w=5000, soc=10))
    engine.step(3500, now=0)
    assert engine.step(3500, now=10) == {"bat": 3000, "heater": 0}


# --------------------------------------------------------------------- EV

def test_ev_power_range_is_derived_from_the_electrical_settings():
    single = ev(phases=1, min_current_a=6, max_current_a=16)
    assert (single.min_power_w, single.power_w) == (1380, 3680)
    three = ev(phases=3, min_current_a=6, max_current_a=16)
    assert (three.min_power_w, three.power_w) == (4140, 11040)
    assert three.current_for(6900) == pytest.approx(10.0)
    assert three.current_for(0) == 0


@pytest.mark.parametrize(
    "kwargs",
    [dict(phases=2), dict(min_current_a=0), dict(min_current_a=20, max_current_a=16), dict(voltage_v=0), dict(soc_max=0)],
)
def test_ev_invalid_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        ev(**kwargs)


def test_ev_never_starts_below_the_minimum_current():
    engine = Engine([ev()])
    assert engine.step(1379, now=0)["ev"] == 0
    assert engine.step(1380, now=1)["ev"] == 1380  # 6 A


def test_ev_start_margin():
    engine = Engine([ev(start_margin_w=200)])
    assert engine.step(1500, now=0)["ev"] == 0  # needs 1580 W
    assert engine.step(1600, now=1)["ev"] == 1380


def test_ev_follows_surplus_in_whole_amp_steps_and_caps_at_max():
    engine = Engine([ev()])
    assert engine.step(2500, now=0)["ev"] == 10 * 230  # floor(2500 / 230) = 10 A
    assert engine.step(2529, now=1)["ev"] == 10 * 230
    assert engine.step(2530, now=2)["ev"] == 11 * 230
    assert engine.step(9000, now=3)["ev"] == 16 * 230


def test_ev_current_step_larger_than_one_amp():
    engine = Engine([ev(current_step_a=2, min_current_a=6)])
    assert engine.step(3000, now=0)["ev"] == 12 * 230  # 13 A rounded down to the 2 A grid: 12 A


def test_ev_rides_out_a_short_dip_down_to_the_stay_tolerance():
    engine = Engine([ev(stay_tolerance_w=300)])
    assert engine.step(1500, now=0)["ev"] == 1380
    assert engine.step(1100, now=1)["ev"] == 1380  # 1080 W is the stay threshold: hold at 6 A
    assert engine.step(1000, now=2)["ev"] == 0


def test_ev_not_connected_gets_nothing_and_frees_surplus_for_others():
    engine = Engine([ev(priority=1), heater(priority=2)])
    engine.set_reading("ev", DeviceReading(connected=False))
    assert engine.step(3000, now=0) == {"ev": 0, "heater": 2000}
    engine.set_reading("ev", DeviceReading(connected=True))
    assert engine.step(3000, now=1)["ev"] == 2990  # 13 A


def test_ev_unknown_connection_state_is_assumed_connected():
    engine = Engine([ev()])
    engine.set_reading("ev", DeviceReading(connected=None))
    assert engine.step(1500, now=0)["ev"] == 1380


def test_unplugging_stops_the_charge_even_during_min_on_time():
    engine = Engine([ev(min_on_s=900)])
    assert engine.step(3000, now=0)["ev"] > 0
    engine.set_reading("ev", DeviceReading(connected=False))
    assert engine.step(3000, now=10)["ev"] == 0


def test_ev_min_on_time_keeps_it_at_the_minimum_current():
    engine = Engine([ev(min_on_s=300)])
    engine.step(3000, now=0)
    assert engine.step(0, now=60)["ev"] == 1380  # held at 6 A, not at the old 13 A
    assert engine.step(0, now=301)["ev"] == 0


def test_ev_soc_target():
    engine = Engine([ev(soc_max=80)])
    engine.set_reading("ev", DeviceReading(soc=60, connected=True))
    assert engine.step(3000, now=0)["ev"] > 0
    engine.set_reading("ev", DeviceReading(soc=80, connected=True))
    assert engine.step(3000, now=1)["ev"] == 0


def test_three_phase_ev_needs_the_three_phase_minimum():
    engine = Engine([ev(phases=3)])
    assert engine.step(4000, now=0)["ev"] == 0  # 6 A on three phases is 4140 W
    assert engine.step(4140, now=1)["ev"] == 4140
    assert engine.step(5000, now=2)["ev"] == 7 * 690  # 7 A


# -------------------------------------------------------------- routed_w

def test_routed_w_prefers_measured_power_over_the_command():
    engine = Engine([ev(), heater()])
    engine.step(5700, now=0)  # ev capped at 16 A = 3680 W, heater 2000 W
    assert engine.routed_w == 5680
    engine.set_reading("ev", DeviceReading(measured_w=1800))  # the car only draws 1800 W
    assert engine.routed_w == 3800
    engine.set_reading("ev", DeviceReading(measured_w=-50))  # negative readings count as zero
    assert engine.routed_w == 2000
    engine.set_reading("ev", None)
    assert engine.routed_w == 5680


def test_closed_loop_with_a_car_that_draws_less_than_commanded_stays_stable():
    """Surplus 4000 W, house 500 W. The car caps itself at 2000 W while commanded more."""
    engine = Engine([ev(priority=1, settle_s=0), heater(priority=2, power_w=1500)])
    production, house = 4500.0, 500.0
    for t in range(10):
        ev_draw = min(engine.state("ev").power_w, 2000.0)
        heater_draw = engine.state("heater").power_w
        engine.set_reading("ev", DeviceReading(measured_w=ev_draw, connected=True))
        routed = engine.routed_w
        export = production - house - ev_draw - heater_draw
        engine.step(available_from_export(export, routed), now=t * 10)
    ev_draw = min(engine.state("ev").power_w, 2000.0)
    assert engine.state("heater").power_w == 1500  # the unused part went to the heater
    assert production - house - ev_draw - engine.state("heater").power_w >= 0  # no grid import
