"""Off-peak top-up in the standalone runtime: the control loop and the TOML options."""
import asyncio
from datetime import datetime, timedelta

import pytest

from solarprio import Device, DeviceKind, DeviceReading, Engine
from solarprio.runtime.adapters import MeasurementUnavailable
from solarprio.runtime.config import ConfigError, RuntimeConfig, parse_config
from solarprio.runtime.controller import Controller

from test_config import minimal
from test_controller import FakeActuator, FakeSource


def build(start=datetime(2026, 11, 10, 23, 0)):
    clock, local = [0.0], [start]
    source, actuator = FakeSource(), FakeActuator()
    devices = [
        Device(id="ecs", name="Water heater", priority=1, kind=DeviceKind.ON_OFF, power_w=2000, offpeak=("22:30-06:30",)),
        Device(id="pump", name="Pump", priority=2, kind=DeviceKind.ON_OFF, power_w=800, offpeak=("22:30-06:30",)),
    ]
    engine = Engine(devices)
    ctl = Controller(engine, source, actuator, RuntimeConfig(), lambda: clock[0], local_clock=lambda: local[0])
    return ctl, engine, source, actuator, clock, local


def advance(ctl, engine, clock, local, seconds, hot=()):
    for _ in range(int(seconds / 5)):
        clock[0] += 5
        local[0] += timedelta(seconds=5)
        for dev_id in engine.device_ids:
            on = engine.state(dev_id).power_w > 0 and dev_id not in hot
            engine.set_reading(dev_id, DeviceReading(measured_w=engine.device(dev_id).power_w if on else 0.0))
        asyncio.run(ctl.tick())


def last_command(actuator, dev_id):
    return [p for d, p in actuator.calls if d == dev_id][-1]


def test_the_heater_is_fed_at_night_and_the_pump_waits():
    ctl, engine, source, actuator, clock, local = build()
    advance(ctl, engine, clock, local, 60)
    assert last_command(actuator, "ecs") == 2000.0
    assert not [c for c in actuator.calls if c[0] == "pump" and c[1] > 0]


def test_a_hot_heater_hands_over_to_the_pump():
    ctl, engine, source, actuator, clock, local = build()
    advance(ctl, engine, clock, local, 300, hot={"ecs"})
    assert last_command(actuator, "ecs") == 0.0 and last_command(actuator, "pump") == 800.0


def test_nothing_happens_by_day():
    ctl, engine, source, actuator, clock, local = build(datetime(2026, 11, 10, 12, 0))
    advance(ctl, engine, clock, local, 120)
    assert all(power == 0 for _, power in actuator.calls)


def test_a_lost_measurement_still_switches_off_at_night():
    ctl, engine, source, actuator, clock, local = build()
    advance(ctl, engine, clock, local, 30)
    assert last_command(actuator, "ecs") == 2000.0
    source.error = MeasurementUnavailable("gone")
    clock[0] += 5
    asyncio.run(ctl.tick())
    assert last_command(actuator, "ecs") == 0.0


def test_toml_options_are_parsed_and_need_a_measured_topic():
    raw = minimal()
    raw["device"][0].update(offpeak=["22:30-06:30", "12:30-14:30"], reset_at="07:00", done_below_w=40, done_after_s=90,
                            readings={"measured_topic": "heater/power"})
    dev = parse_config(raw).devices[0]
    assert dev.windows == ((1350, 390), (750, 870)) and dev.reset_minute == 420
    assert dev.done_threshold_w == 40 and dev.done_after_s == 90

    raw["device"][0].pop("readings")
    with pytest.raises(ConfigError, match="measured_topic"):
        parse_config(raw)


@pytest.mark.parametrize("bad", [{"offpeak": ["99:00-06:00"]}, {"offpeak": ["22:00-06:00"], "done_below_w": 5000}])
def test_bad_schedules_are_reported_with_the_device_id(bad):
    raw = minimal()
    raw["device"][0].update(bad, readings={"measured_topic": "t"})
    with pytest.raises(ConfigError, match="'a'"):
        parse_config(raw)


def test_offpeak_budget_lets_the_runtime_feed_several_devices_together():
    raw = minimal(runtime={"offpeak_budget_w": 21000})
    raw["device"] = [
        {"id": f"c{i}", "name": f"Charger {i}", "priority": i, "kind": "on_off", "power_w": 7000, "offpeak": ["22:30-06:30"],
         "actuator": {"type": "mqtt", "topic": f"c{i}/set"}, "readings": {"measured_topic": f"c{i}/power"}}
        for i in range(1, 5)
    ]
    cfg = parse_config(raw)
    assert cfg.runtime.offpeak_budget_w == 21000
    clock, local = [0.0], [datetime(2026, 11, 10, 23, 0)]
    engine = Engine(cfg.devices, offpeak_budget_w=cfg.runtime.offpeak_budget_w)
    actuator = FakeActuator()
    ctl = Controller(engine, FakeSource(), actuator, cfg.runtime, lambda: clock[0], local_clock=lambda: local[0])
    for dev_id in engine.device_ids:
        engine.set_reading(dev_id, DeviceReading(measured_w=0.0))
    asyncio.run(ctl.tick())
    assert {d: p for d, p in actuator.calls} == {"c1": 7000.0, "c2": 7000.0, "c3": 7000.0, "c4": 0.0}


def test_a_negative_budget_is_refused():
    with pytest.raises(ConfigError, match="offpeak_budget_w"):
        parse_config(minimal(runtime={"offpeak_budget_w": -1}))
