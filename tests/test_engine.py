import pytest

from solarprio import (
    Device,
    DeviceKind,
    Engine,
    available_from_export,
    available_from_production,
)


def heater(**kw):
    base = dict(id="heater", name="Water heater", priority=2, kind=DeviceKind.ON_OFF, power_w=2000)
    return Device(**{**base, **kw})


def dimmer(**kw):
    base = dict(
        id="dimmer", name="Dimmer", priority=1, kind=DeviceKind.PROPORTIONAL, power_w=3000, min_power_w=200
    )
    return Device(**{**base, **kw})


def test_priority_order_decides_who_is_served_first():
    engine = Engine([heater(priority=2), dimmer(priority=1)])
    cmd = engine.step(3500, now=0)
    assert cmd["dimmer"] == 3000
    assert cmd["heater"] == 0  # only 500 W left, heater needs 2000


def test_changing_priority_swaps_who_is_served():
    engine = Engine([heater(priority=1), dimmer(priority=2)])
    cmd = engine.step(3500, now=0)
    assert cmd["heater"] == 2000
    assert cmd["dimmer"] == 1500


def test_proportional_below_min_power_stays_off():
    engine = Engine([dimmer()])
    assert engine.step(150, now=0)["dimmer"] == 0
    assert engine.step(250, now=1)["dimmer"] == 250


def test_on_off_start_margin_and_stay_tolerance():
    engine = Engine([heater(start_margin_w=200, stay_tolerance_w=300)])
    assert engine.step(2100, now=0)["heater"] == 0  # needs 2200 to start
    assert engine.step(2200, now=1)["heater"] == 2000
    assert engine.step(1750, now=2)["heater"] == 2000  # 1700 is the stay threshold
    assert engine.step(1600, now=3)["heater"] == 0


def test_min_on_time_holds_the_load():
    engine = Engine([heater(min_on_s=60)])
    assert engine.step(2000, now=0)["heater"] == 2000
    assert engine.step(0, now=30)["heater"] == 2000  # held
    assert engine.step(0, now=61)["heater"] == 0


def test_min_off_time_blocks_restart():
    engine = Engine([heater(min_off_s=60)])
    engine.step(2000, now=0)
    engine.step(0, now=10)
    assert engine.step(2000, now=30)["heater"] == 0  # too early
    assert engine.step(2000, now=71)["heater"] == 2000


def test_held_load_consumes_surplus_of_lower_priorities():
    engine = Engine([heater(priority=1, min_on_s=60), dimmer(priority=2)])
    engine.step(2000, now=0)
    cmd = engine.step(2500, now=30)  # heater still held at 2000 -> 500 left
    assert cmd["heater"] == 2000
    assert cmd["dimmer"] == 500


def test_disabled_device_is_skipped():
    engine = Engine([dimmer(priority=1, enabled=False), heater(priority=2)])
    cmd = engine.step(3000, now=0)
    assert cmd["dimmer"] == 0
    assert cmd["heater"] == 2000


def test_negative_available_turns_everything_off():
    engine = Engine([dimmer(), heater()])
    engine.step(5000, now=0)
    cmd = engine.step(-400, now=1)
    assert cmd == {"dimmer": 0, "heater": 0}


def test_routed_w_sums_last_commands():
    engine = Engine([dimmer(), heater()])
    engine.step(5000, now=0)  # dimmer 3000 + heater 2000
    assert engine.routed_w == 5000
    engine.step(4000, now=1)  # dimmer 3000, 1000 W left: heater cannot stay on
    assert engine.routed_w == 3000


def test_duplicate_id_and_invalid_power_rejected():
    engine = Engine([heater()])
    with pytest.raises(ValueError):
        engine.add_device(heater())
    with pytest.raises(ValueError):
        heater(id="bad", power_w=0)
    with pytest.raises(ValueError):
        dimmer(id="bad", min_power_w=5000)


def test_available_includes_already_routed_power():
    # 2000 W already routed, 300 W still exported -> 2300 W available
    assert available_from_export(300, 2000) == 2300
    # production 4000, house 3000 of which 2000 managed -> 3000 available
    assert available_from_production(4000, 3000, 2000) == 3000


def test_closed_loop_does_not_oscillate_with_export_measurement():
    """Feeding the measured export back each tick must converge, not flip-flop."""
    engine = Engine([dimmer()])
    production, house_base = 2500.0, 500.0
    for t in range(5):
        routed = engine.routed_w
        export = production - house_base - routed
        available = available_from_export(export, routed)
        engine.step(available, now=t)
    assert engine.state("dimmer").power_w == 2000


def test_reset_forgets_commands_and_timers():
    engine = Engine([heater(min_on_s=600)])
    engine.step(2000, now=0)
    engine.reset()
    assert engine.routed_w == 0
    engine.step(0, now=1)  # no min_on hold after reset
    assert engine.routed_w == 0


def test_priority_can_change_on_the_fly_keeping_state():
    engine = Engine([dimmer(priority=1), heater(priority=2, min_on_s=600)])
    engine.step(5000, now=0)  # dimmer 3000 + heater 2000
    engine.set_priority("heater", 1)
    engine.set_priority("dimmer", 2)
    cmd = engine.step(2500, now=10)  # heater (held by min_on) now first
    assert cmd["heater"] == 2000 and cmd["dimmer"] == 500


def test_disabled_device_is_switched_off_on_next_step():
    engine = Engine([heater()])
    engine.step(2000, now=0)
    engine.set_enabled("heater", False)
    assert engine.step(2000, now=1)["heater"] == 0


def test_rollback_command_keeps_routed_power_truthful():
    engine = Engine([heater()])
    assert engine.step(2000, now=0)["heater"] == 2000
    engine.rollback_command("heater", 0.0)  # the "on" command never reached the device
    assert engine.routed_w == 0
    assert not engine.state("heater").on
