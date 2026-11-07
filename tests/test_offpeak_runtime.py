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


# ---------------------------------------------------------------- off-peak told by an MQTT topic

def _signal_raw(**device):
    raw = minimal()
    raw["device"][0].update(readings={"measured_topic": "heater/power", "offpeak_topic": "linky/tariff", **device.pop("readings", {})},
                            **device)
    return raw


def test_an_offpeak_topic_makes_the_device_follow_the_signal():
    dev = parse_config(_signal_raw()).devices[0]
    assert dev.offpeak_signal and dev.has_schedule and not dev.windows


def test_a_signal_needs_a_measured_topic_and_can_be_limited_to_windows():
    raw = minimal()
    raw["device"][0]["readings"] = {"offpeak_topic": "linky/tariff"}
    with pytest.raises(ConfigError, match="measured_topic"):
        parse_config(raw)
    both = parse_config(_signal_raw(offpeak=["22:30-06:30"])).devices[0]  # a signal AND windows: both must say off-peak
    assert both.offpeak_signal and both.windows


@pytest.mark.parametrize("payload, values, field, expected", [
    ("HC..", None, None, True), ("HP..", None, None, False), ("unavailable", None, None, None),
    ("2", ["2"], None, True), ("1", ["2"], None, False),
    ('{"value": 2}', ["2"], "value", True), ('{"value": 1}', ["2"], "value", False), ("not json", ["2"], "value", None),
])
def test_the_topic_payload_is_read_as_a_tariff_state(payload, values, field, expected):
    from fakes import FakeBus
    from solarprio.runtime.adapters import MqttReadings
    from solarprio.runtime.config import ReadingsConfig

    bus = FakeBus()
    cfg = {"a": ReadingsConfig(measured_topic="heater/power", offpeak_topic="linky/tariff", offpeak_values=values, field=field)}
    readings = MqttReadings(bus, cfg, stale_after_s=30)
    assert "linky/tariff" in bus.subscribed
    bus.feed("linky/tariff", payload)
    bus.feed("heater/power", '{"value": 0}' if field else "0")
    assert readings.read_readings()["a"].offpeak is expected


def test_a_stale_tariff_topic_is_unknown():
    from fakes import FakeBus
    from solarprio.runtime.adapters import MqttReadings
    from solarprio.runtime.config import ReadingsConfig

    bus = FakeBus()
    readings = MqttReadings(bus, {"a": ReadingsConfig(measured_topic="p", offpeak_topic="t")}, stale_after_s=30)
    bus.feed("t", "HC..", age=300)
    bus.feed("p", "0")
    assert readings.read_readings()["a"].offpeak is None


def test_the_controller_feeds_a_device_while_the_topic_says_off_peak():
    from fakes import FakeBus
    from solarprio.runtime.adapters import MqttReadings
    from solarprio.runtime.config import ReadingsConfig

    bus, actuator, source = FakeBus(), FakeActuator(), FakeSource()
    engine = Engine([Device(id="ecs", name="ECS", priority=1, kind=DeviceKind.ON_OFF, power_w=2000, offpeak_signal=True)])
    readings = MqttReadings(bus, {"ecs": ReadingsConfig(measured_topic="p", offpeak_topic="t")}, stale_after_s=30)
    ctl = Controller(engine, source, actuator, RuntimeConfig(), lambda: 0.0, readings=readings,
                     local_clock=lambda: datetime(2026, 11, 10, 12, 0))
    bus.feed("p", "0")
    bus.feed("t", "HP..")
    asyncio.run(ctl.tick())
    assert all(power == 0 for _, power in actuator.calls)  # peak hours: never fed
    bus.feed("t", "HC..")
    asyncio.run(ctl.tick())
    assert actuator.calls[-1] == ("ecs", 2000.0)
    source.error = MeasurementUnavailable("grid sensor gone")  # safety first, even in off-peak
    asyncio.run(ctl.tick())
    assert actuator.calls[-1] == ("ecs", 0.0)


# ---------------------------------------------------------------- the task category

def test_a_task_publishes_a_go_signal_and_needs_no_measured_topic_for_off_peak():
    from fakes import FakeBus
    from solarprio.runtime.adapters import MqttActuator

    raw = minimal()
    raw["device"][0].update(kind="task", power_w=100, offpeak=["22:30-06:30"])  # no readings.measured_topic: accepted for a task
    cfg = parse_config(raw)
    dev = cfg.devices[0]
    assert dev.kind.value == "task" and dev.has_schedule

    bus = FakeBus()
    actuator = MqttActuator(bus, {dev.id: dev}, {dev.id: {"topic": "home/tasks/go", "payload_on": "GO", "payload_off": "STOP"}})
    asyncio.run(actuator.apply(dev.id, 100.0))
    asyncio.run(actuator.apply(dev.id, 0.0))
    assert bus.published == [("home/tasks/go", "GO"), ("home/tasks/go", "STOP")]


def test_a_task_is_fed_by_the_controller_during_off_peak_without_a_measurement():
    engine = Engine([Device(id="ia", name="IA", priority=1, kind=DeviceKind.TASK, power_w=100, offpeak=("22:30-06:30",))])
    actuator = FakeActuator()
    ctl = Controller(engine, FakeSource(), actuator, RuntimeConfig(), lambda: 0.0, local_clock=lambda: datetime(2026, 11, 10, 23, 0))
    asyncio.run(ctl.tick())
    assert actuator.calls[-1] == ("ia", 100.0)
