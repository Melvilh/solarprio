"""Central regulation in the standalone runtime: temperature topics, the house power, the subscription cap, the emergency cut."""
import asyncio
from datetime import datetime

import pytest

from fakes import FakeBus, wait_for
from solarprio import Device, DeviceKind, DeviceReading, Engine
from solarprio.runtime.adapters import MqttPowerSource, MqttReadings
from solarprio.runtime.config import ConfigError, ReadingsConfig, RuntimeConfig, SourceConfig, parse_config
from solarprio.runtime.controller import Controller

from test_config import minimal
from test_controller import FakeActuator


def heater_raw(**device):
    raw = minimal(runtime={"subscription_va": 5700, "emergency_import_w": 250}, source={
        "mode": "export", "export_topic": "grid/export_w", "house_topic": "grid/house_w"})
    raw["device"][0].update(kind="proportional", power_w=2400, min_power_w=15, temp_max_solar=65, temp_max_offpeak=60, temp_min=40,
                            hold_s=8, ramp_up_w=200, deadband_w=15,
                            readings={"measured_topic": "heater/power", "temperature_topic": "heater/temp"}, **device)
    return raw


def test_the_regulation_settings_are_read_from_the_toml():
    cfg = parse_config(heater_raw())
    dev = cfg.devices[0]
    assert (dev.temp_max_solar, dev.temp_max_offpeak, dev.temp_min, dev.hold_s, dev.ramp_up_w, dev.deadband_w) == (65, 60, 40, 8, 200, 15)
    assert cfg.runtime.subscription_va == 5700 and cfg.runtime.emergency_import_w == 250
    assert cfg.source.topics["house"] == ["grid/house_w"]
    assert cfg.readings["a"].temperature_topic == "heater/temp"


@pytest.mark.parametrize("change, message", [
    (lambda r: r["source"].pop("house_topic"), "house_topic"),  # a subscription limit needs the house power
    (lambda r: r["runtime"].update(subscription_va=-1), "subscription_va"),
    (lambda r: r["runtime"].update(emergency_import_w=0), "emergency_import_w"),
    (lambda r: r["device"][0].update(temp_min=70), "'a'"),  # minimum above the maximum
    (lambda r: r["device"][0]["readings"].update(temperature_unit="K"), "temperature_unit"),
])
def test_bad_regulation_settings_are_reported(change, message):
    raw = heater_raw()
    change(raw)
    with pytest.raises(ConfigError, match=message):
        parse_config(raw)


@pytest.mark.parametrize("payload, unit, expected", [("52.5", "C", 52.5), ("149", "F", 65.0), ('{"value": 40}', "C", 40.0)])
def test_the_temperature_topic_is_read_in_celsius(payload, unit, expected):
    bus = FakeBus()
    cfg = ReadingsConfig(temperature_topic="t", temperature_unit=unit, field="value" if payload.startswith("{") else None)
    readings = MqttReadings(bus, {"a": cfg}, stale_after_s=30)
    bus.feed("t", payload)
    assert readings.read_readings()["a"].temperature == pytest.approx(expected)
    bus.feed("t", "garbage")
    assert "a" not in readings.read_readings()


def test_the_source_reports_the_import_and_the_house_power():
    bus = FakeBus()
    cfg = SourceConfig(mode="export", topics={"export": ["grid/export_w"], "house": ["grid/house_w"]})
    source = MqttPowerSource(bus, cfg, stale_after_s=30)
    assert source.read_house_w() is None  # nothing received yet: unknown, not a failure
    bus.feed("grid/export_w", "-400")
    bus.feed("grid/house_w", "3000")
    assert asyncio.run(source.read_available_w(0.0)) == -400 and source.last_import_w == 400
    assert source.read_house_w() == 3000
    bus.feed("grid/house_w", "3000", age=99)
    assert source.read_house_w() is None  # too old: unknown
    prod = MqttPowerSource(bus, SourceConfig(mode="production", topics={"production": ["p"], "consumption": ["c"]}), 30)
    bus.feed("p", "1000")
    bus.feed("c", "1800")
    asyncio.run(prod.read_available_w(0.0))
    assert prod.last_import_w == 800 and prod.read_house_w() is None  # no house topic configured


def test_the_controller_passes_the_house_power_and_the_import_to_the_engine():
    bus = FakeBus()
    cfg = SourceConfig(mode="export", topics={"export": ["grid/export_w"], "house": ["grid/house_w"]})
    source = MqttPowerSource(bus, cfg, stale_after_s=30)
    heater = Device(id="ecs", name="ECS", priority=1, kind=DeviceKind.PROPORTIONAL, power_w=2400, min_power_w=15, temp_min=40,
                    temp_max_solar=65)
    engine = Engine([heater], subscription_va=5700, emergency_import_w=250)
    actuator = FakeActuator()
    ctl = Controller(engine, source, actuator, RuntimeConfig(), lambda: 0.0, local_clock=lambda: datetime(2026, 11, 10, 14, 0))
    engine.set_reading("ecs", DeviceReading(temperature=30.0, measured_w=0.0))
    bus.feed("grid/export_w", "-3000")  # the house imports 3000 W
    bus.feed("grid/house_w", "3000")
    asyncio.run(ctl.tick())
    assert actuator.calls[-1] == ("ecs", 2400.0)  # sanitary heating from the grid, 2700 W of room


def test_a_water_heater_regulated_centrally_over_real_mqtt(broker_port, tmp_path):
    import paho.mqtt.client as mqtt
    from solarprio.runtime.app import run

    config = tmp_path / "config.toml"
    config.write_text(f"""
[runtime]
interval_s = 0.2
stale_after_s = 1.5
subscription_va = 5700
emergency_import_w = 250

[mqtt]
host = "127.0.0.1"
port = {broker_port}
client_id = "solarprio-test-heater"

[source]
mode = "export"
export_topic = "grid/export_w"
house_topic = "grid/house_w"

[[device]]
id = "ecs"
name = "Water heater"
priority = 1
kind = "proportional"
power_w = 2400
min_power_w = 15
min_on_s = 600
temp_max_solar = 65
temp_min = 40
  [device.actuator]
  type = "mqtt"
  topic = "out/heater"
  scale = "watts"
  [device.readings]
  measured_topic = "heater/power"
  temperature_topic = "heater/temp"
""")
    received: dict[str, str] = {}
    observer = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="observer-heater")
    observer.on_message = lambda c, u, m: received.__setitem__(m.topic, m.payload.decode())
    observer.connect("127.0.0.1", broker_port)
    observer.subscribe("out/#")
    observer.loop_start()
    world = {"temp": "50", "export": "1500", "house": "1000", "house_on": True}

    async def scenario():
        stop_task = asyncio.create_task(run(str(config)))
        try:
            pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="world-heater")
            pub.connect("127.0.0.1", broker_port)
            pub.loop_start()

            async def hold(seconds, expect):
                for _ in range(int(seconds * 10)):
                    pub.publish("grid/export_w", world["export"])
                    pub.publish("heater/temp", world["temp"])
                    pub.publish("heater/power", "0")
                    if world["house_on"]:
                        pub.publish("grid/house_w", world["house"])
                    await asyncio.sleep(0.1)
                    if received.get("out/heater") == expect:
                        return
                assert received.get("out/heater") == expect, (received.get("out/heater"), expect)

            await hold(6, "1500")  # the sun heats the water
            world["export"] = "-400"
            await hold(6, "0")  # 400 W imported: the emergency cut, which no minimum run time holds back
            world.update(export="1500")
            await hold(6, "1500")
            world["temp"] = "66"
            await hold(6, "0")  # the tank is hot: the central rule stops it
            world.update(temp="30", export="-3000", house="3000")
            await hold(6, "2400")  # too cold: sanitary heating from the grid, 2700 W of room under the subscription
            world["house_on"] = False
            await hold(8, "0")  # the house power is lost: nothing is fed from the grid blindly
            pub.loop_stop()
        finally:
            import os
            import signal

            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.wait_for(stop_task, 10)

    try:
        asyncio.run(scenario())
        assert wait_for(lambda: received.get("out/heater") == "0")
    finally:
        observer.loop_stop()


def test_the_controller_cuts_what_runs_on_the_sun_when_the_import_is_too_high():
    bus = FakeBus()
    cfg = SourceConfig(mode="export", topics={"export": ["grid/export_w"]})
    source = MqttPowerSource(bus, cfg, stale_after_s=30)
    pump = Device(id="pump", name="Pump", priority=1, kind=DeviceKind.ON_OFF, power_w=500, min_on_s=600)
    engine = Engine([pump], emergency_import_w=250)
    actuator = FakeActuator()
    clock = [0.0]
    ctl = Controller(engine, source, actuator, RuntimeConfig(), lambda: clock[0], local_clock=lambda: datetime(2026, 11, 10, 14, 0))
    bus.feed("grid/export_w", "700")
    asyncio.run(ctl.tick())
    assert actuator.calls[-1] == ("pump", 500.0)
    clock[0] += 5
    bus.feed("grid/export_w", "-400")  # 400 W imported, over the 250 W threshold
    asyncio.run(ctl.tick())
    assert actuator.calls[-1] == ("pump", 0.0)  # at once, although the minimum run time is 10 minutes
