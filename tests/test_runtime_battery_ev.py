import asyncio

import pytest

from solarprio import Device, DeviceKind, DeviceReading, Engine
from solarprio.runtime.adapters import MqttActuator, MqttReadings
from solarprio.runtime.config import ConfigError, ReadingsConfig, RuntimeConfig, load_config, parse_config
from solarprio.runtime.controller import Controller
from pathlib import Path

from fakes import FakeBus, ev_dev, run

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------ actuators

def test_ev_actuator_publishes_amps_then_switch_on_and_switch_off_on_stop():
    bus, dev = FakeBus(), ev_dev()
    act = MqttActuator(bus, {"ev": dev}, {"ev": {"topic": "wb/current", "switch_topic": "wb/enable"}})
    run(act.apply("ev", 10 * 230))
    assert bus.published == [("wb/current", "10.0"), ("wb/enable", "ON")]
    bus.published.clear()
    run(act.apply("ev", 0))
    assert bus.published == [("wb/enable", "OFF")]  # the current is left alone


def test_ev_actuator_without_switch_pauses_with_zero_amps():
    bus, dev = FakeBus(), ev_dev()
    act = MqttActuator(bus, {"ev": dev}, {"ev": {"topic": "wb/current"}})
    run(act.apply("ev", 6 * 230))
    run(act.apply("ev", 0))
    assert bus.published == [("wb/current", "6.0"), ("wb/current", "0.0")]


def test_ev_actuator_three_phase_amps():
    bus, dev = FakeBus(), ev_dev(phases=3)
    act = MqttActuator(bus, {"ev": dev}, {"ev": {"topic": "wb/current"}})
    run(act.apply("ev", 7 * 690))
    assert bus.published == [("wb/current", "7.0")]


def test_battery_actuator_watts_and_percent():
    bus = FakeBus()
    bat = Device(id="bat", name="B", priority=1, kind=DeviceKind.BATTERY, power_w=3000)
    run(MqttActuator(bus, {"bat": bat}, {"bat": {"topic": "bat/set"}}).apply("bat", 1500))
    run(MqttActuator(bus, {"bat": bat}, {"bat": {"topic": "bat/set", "scale": "percent"}}).apply("bat", 1500))
    assert bus.published == [("bat/set", "1500"), ("bat/set", "50.0")]


# ------------------------------------------------------------- readings

def test_readings_parse_values_units_json_and_plug_words():
    bus = FakeBus()
    cfgs = {
        "bat": ReadingsConfig(soc_topic="bat/soc", measured_topic="bat/p", measured_unit="kW"),
        "ev": ReadingsConfig(connected_topic="wb/plug"),
        "js": ReadingsConfig(soc_topic="js/soc", field="state.level"),
    }
    readings = MqttReadings(bus, cfgs, stale_after_s=30)
    assert bus.subscribed == {"bat/soc", "bat/p", "wb/plug", "js/soc"}
    bus.feed("bat/soc", "73.5")
    bus.feed("bat/p", "1.25")
    bus.feed("js/soc", '{"state": {"level": 41}}')
    for word, expected in (("ON", True), ("true", True), ("1", True), ('"connected"', True), ("OFF", False), ("unplugged", False), ("banana", None)):
        bus.feed("wb/plug", word)
        got = readings.read_readings().get("ev")
        assert (got.connected if got else None) is expected, word
    out = readings.read_readings()
    assert out["bat"] == DeviceReading(measured_w=1250.0, soc=73.5, connected=None)
    assert out["js"].soc == 41.0


def test_readings_ignore_stale_and_unparsable_values():
    bus = FakeBus()
    readings = MqttReadings(bus, {"bat": ReadingsConfig(soc_topic="bat/soc", measured_topic="bat/p")}, stale_after_s=30)
    bus.feed("bat/soc", "80", age=31)  # too old
    bus.feed("bat/p", "n/a")  # not a number
    assert readings.read_readings() == {}
    bus.feed("bat/soc", "80", age=5)
    assert readings.read_readings()["bat"].soc == 80.0


# ----------------------------------------------------------- controller

class Source:
    def __init__(self):
        self.export = 0.0

    async def read_available_w(self, routed_w):
        return self.export + routed_w


class Recorder:
    def __init__(self):
        self.calls = []

    async def apply(self, device_id, power_w):
        self.calls.append((device_id, power_w))


class Readings:
    def __init__(self):
        self.data: dict[str, DeviceReading] = {}

    def read_readings(self):
        return dict(self.data)


def test_controller_uses_readings_unplugged_car_frees_surplus_and_soc_limit_applies():
    clock = [0.0]
    source, actuator, readings = Source(), Recorder(), Readings()
    devices = [
        ev_dev(priority=1),
        Device(id="pump", name="Pump", priority=2, kind=DeviceKind.ON_OFF, power_w=800),
        Device(id="bat", name="Bat", priority=3, kind=DeviceKind.BATTERY, power_w=3000, soc_max=90),
    ]
    ctl = Controller(Engine(devices), source, actuator, RuntimeConfig(resend_every_s=1e9), lambda: clock[0], readings=readings)
    source.export = 4000
    readings.data = {"ev": DeviceReading(connected=False), "bat": DeviceReading(soc=50)}
    cmds = asyncio.run(ctl.tick())
    assert cmds == {"ev": 0, "pump": 800, "bat": 3000}  # car unplugged: pump 800 W, battery takes up to its 3000 W max

    clock[0] = 10
    readings.data = {"ev": DeviceReading(connected=True), "bat": DeviceReading(soc=95)}
    cmds = asyncio.run(ctl.tick())
    assert cmds["ev"] == 16 * 230 and cmds["bat"] == 0  # plugged in: the car takes up to 16 A; battery is over its limit


def test_controller_without_readings_still_works():
    source, actuator = Source(), Recorder()
    ctl = Controller(Engine([ev_dev()]), source, actuator, RuntimeConfig())
    source.export = 2000
    assert asyncio.run(ctl.tick())["ev"] == 8 * 230


# --------------------------------------------------------------- config

def test_example_config_battery_and_ev_sections():
    cfg = load_config(ROOT / "config.example.toml")
    ev = next(d for d in cfg.devices if d.id == "wallbox")
    assert (ev.min_power_w, ev.power_w) == (1380, 3680)
    assert cfg.actuators["wallbox"].options["switch_topic"] == "wallbox/enable"
    assert cfg.readings["wallbox"].connected_topic == "wallbox/car_connected"
    assert cfg.readings["home_battery"].soc_topic == "battery/soc"


def minimal(device):
    return {"source": {"mode": "export", "export_topic": "g"}, "device": [device]}


def test_invalid_ev_and_readings_are_config_errors():
    base = {"id": "ev", "name": "Car", "priority": 1, "kind": "ev_charger", "actuator": {"type": "mqtt", "topic": "t"}}
    with pytest.raises(ConfigError, match="min_current_a"):
        parse_config(minimal({**base, "min_current_a": 20, "max_current_a": 16}))
    with pytest.raises(ConfigError, match="readings"):
        parse_config(minimal({**base, "readings": {"soc_topik": "x"}}))
    with pytest.raises(ConfigError, match="measured_unit"):
        parse_config(minimal({**base, "readings": {"measured_unit": "MW"}}))


# ------------------------------------------------- broker unreachable

def test_publish_without_a_broker_connection_raises_so_the_command_is_retried():
    from solarprio.runtime.config import MqttConfig
    from solarprio.runtime.mqtt_bus import MqttBus

    bus = MqttBus(MqttConfig(host="127.0.0.1", port=1))  # never started: not connected
    with pytest.raises(ConnectionError):
        bus.publish("a/b", "ON")
    bus.stop(flush_timeout=0.1)  # must not raise even though nothing was ever delivered


def test_controller_retries_a_command_the_bus_refused():
    class FlakyActuator:
        def __init__(self):
            self.up, self.calls = False, []

        async def apply(self, device_id, power_w):
            if not self.up:
                raise ConnectionError("broker down")
            self.calls.append((device_id, power_w))

    clock, source, actuator = [0.0], Source(), FlakyActuator()
    ctl = Controller(Engine([ev_dev()]), source, actuator, RuntimeConfig(resend_every_s=1e9), lambda: clock[0])
    source.export = 2000
    asyncio.run(ctl.tick())
    assert actuator.calls == []  # nothing delivered, and the controller does not pretend it was
    actuator.up, clock[0] = True, 5
    asyncio.run(ctl.tick())
    # retried on the next cycle with the same 8 A: the undelivered command was not counted as routed power
    assert actuator.calls == [("ev", 8 * 230)]
