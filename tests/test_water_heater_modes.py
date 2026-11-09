"""What a water heater owner asks of the controller: a sanitary minimum only on a forced run, the midday off-peak hours
chosen by a switch, and the answers "is it hot?" and "what is it doing?"."""
from datetime import datetime

import pytest

from solarprio import Device, DeviceKind, DeviceReading, Engine

NIGHT = datetime(2026, 11, 10, 23, 0)
MIDDAY = datetime(2026, 11, 10, 13, 0)
AFTERNOON = datetime(2026, 11, 10, 17, 0)


def heater(**kw):
    base = dict(id="ecs", name="ecs", priority=1, kind=DeviceKind.ON_OFF, power_w=2400, temp_max_solar=65.0, temp_max_offpeak=60.0,
                temp_hysteresis=3.0, temp_min=40.0)
    return Device(**{**base, **kw})


def read(e, temp=50.0, offpeak=None):
    e.set_reading("ecs", DeviceReading(temperature=temp, offpeak=offpeak))


# ---- the sanitary minimum only on a forced run

def test_with_sanitary_forced_only_a_cold_tank_is_not_fed_until_the_forced_run_is_on():
    e = Engine([heater(sanitary_forced_only=True)])
    read(e, temp=30.0)
    assert e.step(0.0, 0.0, AFTERNOON)["ecs"] == 0  # cold, but the user did not ask for the forced run
    e.set_forced_run("ecs", True)
    assert e.step(0.0, 10.0, AFTERNOON)["ecs"] == 2400 and e.mode("ecs") == "sanitary"
    e.set_forced_run("ecs", False)
    read(e, temp=30.0)
    assert e.step(0.0, 700.0, AFTERNOON)["ecs"] == 0  # and it stops when the switch goes off


def test_without_the_option_the_forced_run_changes_nothing_and_the_sanitary_minimum_stays_automatic():
    e = Engine([heater()])
    read(e, temp=30.0)
    assert e.step(0.0, 0.0, AFTERNOON)["ecs"] == 2400


def test_a_forced_run_on_a_warm_tank_feeds_nothing():
    e = Engine([heater(sanitary_forced_only=True)])
    e.set_forced_run("ecs", True)
    read(e, temp=55.0)
    assert e.step(0.0, 0.0, AFTERNOON)["ecs"] == 0


def test_the_option_needs_a_sanitary_minimum():
    with pytest.raises(ValueError, match="temp_min"):
        heater(sanitary_forced_only=True, temp_min=None, temp_max_solar=65.0, temp_max_offpeak=60.0)


def test_the_forced_run_never_overrides_surplus_only():
    e = Engine([heater(sanitary_forced_only=True, surplus_only=True)])
    e.set_forced_run("ecs", True)
    read(e, temp=30.0)
    assert e.step(0.0, 0.0, AFTERNOON)["ecs"] == 0


# ---- the midday off-peak hours chosen by a switch

def midday_heater(**kw):
    return heater(**{"offpeak": ("22:30-06:30",), "offpeak_extra": ("12:30-14:30",), "temp_min": None, **kw})


def test_the_midday_window_only_counts_when_its_switch_is_on_and_the_night_always_does():
    e = Engine([midday_heater()])
    read(e, temp=50.0)
    assert e.step(0.0, 0.0, NIGHT)["ecs"] == 2400  # night: always
    read(e, temp=50.0)
    off = Engine([midday_heater()])
    read(off, temp=50.0)
    assert off.step(0.0, 0.0, MIDDAY)["ecs"] == 0  # midday, switch off
    off.set_extra_windows("ecs", True)
    read(off, temp=50.0)
    assert off.step(0.0, 5.0, MIDDAY)["ecs"] == 2400 and off.mode("ecs") == "offpeak"
    assert off.step(0.0, 10.0, AFTERNOON)["ecs"] == 0  # outside both windows


def test_the_midday_window_alone_is_enough_to_make_it_an_off_peak_device():
    e = Engine([heater(offpeak_extra=("12:30-14:30",), temp_min=None)])
    e.set_extra_windows("ecs", True)
    read(e, temp=50.0)
    assert e.step(0.0, 0.0, MIDDAY)["ecs"] == 2400


def test_the_midday_window_still_needs_the_tariff_signal_when_there_is_one():
    e = Engine([heater(offpeak=("22:30-06:30",), offpeak_extra=("12:30-14:30",), offpeak_signal=True, temp_min=None)])
    e.set_extra_windows("ecs", True)
    read(e, temp=50.0, offpeak=False)
    assert e.step(0.0, 0.0, MIDDAY)["ecs"] == 0  # the Linky says peak: never forced
    read(e, temp=50.0, offpeak=True)
    assert e.step(0.0, 5.0, MIDDAY)["ecs"] == 2400


def test_the_switches_survive_a_reset():
    e = Engine([midday_heater(sanitary_forced_only=True, temp_min=40.0)])
    e.set_forced_run("ecs", True)
    e.set_extra_windows("ecs", True)
    e.reset()
    assert e.state("ecs").forced_run and e.state("ecs").extra_on


# ---- "is it hot?"

def test_is_hot_follows_the_temperature_limits_with_the_hysteresis():
    e = Engine([heater(temp_min=None, temp_max_offpeak=None)])
    read(e, temp=50.0)
    e.step(1000.0, 0.0, AFTERNOON)
    assert not e.is_hot("ecs")
    read(e, temp=66.0)
    e.step(1000.0, 5.0, AFTERNOON)
    assert e.is_hot("ecs") and e.mode("ecs") == "hot"
    read(e, temp=63.0)  # within the hysteresis: still hot
    e.step(1000.0, 10.0, AFTERNOON)
    assert e.is_hot("ecs")
    read(e, temp=61.0)
    e.step(1000.0, 15.0, AFTERNOON)
    assert not e.is_hot("ecs")


def test_a_device_without_temperature_is_never_hot():
    e = Engine([Device(id="p", name="p", priority=1, kind=DeviceKind.ON_OFF, power_w=500)])
    assert not e.is_hot("p")


def test_the_standalone_runtime_refuses_options_it_has_no_switch_for():
    from solarprio.runtime.config import ConfigError, parse_config

    base = {"source": {"mode": "export", "export_topic": "t"},
            "device": [{"id": "d", "name": "d", "priority": 1, "kind": "on_off", "power_w": 1000, "temp_min": 40,
                        "actuator": {"type": "mqtt", "topic": "x"}}]}
    parse_config(base)  # fine without the options
    for extra in ({"sanitary_forced_only": True}, {"offpeak_extra": ["12:00-14:00"]}):
        bad = {**base, "device": [{**base["device"][0], **extra}]}
        with pytest.raises(ConfigError, match="Home Assistant"):
            parse_config(bad)
