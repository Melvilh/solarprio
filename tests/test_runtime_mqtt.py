"""End-to-end test: real MQTT broker (amqtt) + the real runtime + a paho client playing meter and device."""

import asyncio
import time

import paho.mqtt.client as mqtt
import pytest

from fakes import wait_for
from solarprio.runtime.app import run


def test_surplus_is_routed_by_priority_over_real_mqtt(broker_port, tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(f"""
[runtime]
interval_s = 0.2
stale_after_s = 5

[mqtt]
host = "127.0.0.1"
port = {broker_port}
client_id = "solarprio-test"

[source]
mode = "export"
export_topic = "grid/export_w"

[[device]]
id = "dimmer"
name = "Dimmer"
priority = 1
kind = "proportional"
power_w = 2000
  [device.actuator]
  type = "mqtt"
  topic = "out/dimmer"

[[device]]
id = "pump"
name = "Pump"
priority = 2
kind = "on_off"
power_w = 800
  [device.actuator]
  type = "mqtt"
  topic = "out/pump"
""")

    received: dict[str, str] = {}
    observer = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="observer")
    observer.on_message = lambda c, u, m: received.__setitem__(m.topic, m.payload.decode())
    observer.connect("127.0.0.1", broker_port)
    observer.subscribe("out/#")
    observer.loop_start()

    async def scenario():
        stop_task = asyncio.create_task(run(str(config)))
        try:
            # meter publishes 2300 W export every 0.1 s -> dimmer 100 %, pump needs 800 but only 300 left
            publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="meter")
            publisher.connect("127.0.0.1", broker_port)
            publisher.loop_start()
            for _ in range(60):
                publisher.publish("grid/export_w", "2300")
                if received.get("out/dimmer") == "100.0":
                    break
                await asyncio.sleep(0.1)
            assert received.get("out/dimmer") == "100.0"
            assert received.get("out/pump", "OFF") == "OFF"
            publisher.loop_stop()
        finally:
            import os
            import signal

            os.kill(os.getpid(), signal.SIGTERM)  # same path as `docker stop`
            await asyncio.wait_for(stop_task, 10)

    try:
        asyncio.run(scenario())
        # after SIGTERM the runtime must have switched everything off
        assert wait_for(lambda: received.get("out/dimmer") == "0.0")
        assert wait_for(lambda: received.get("out/pump") == "OFF")
    finally:
        observer.loop_stop()


def test_battery_and_ev_charger_over_real_mqtt(broker_port, tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(f"""
[runtime]
interval_s = 0.2
stale_after_s = 5

[mqtt]
host = "127.0.0.1"
port = {broker_port}
client_id = "solarprio-test-ev"

[source]
mode = "export"
export_topic = "grid/export_w"

[[device]]
id = "bat"
name = "Battery"
priority = 1
kind = "battery"
power_w = 3000
min_power_w = 200
soc_max = 90
  [device.actuator]
  type = "mqtt"
  topic = "out/bat"
  [device.readings]
  soc_topic = "in/bat_soc"

[[device]]
id = "ev"
name = "Car"
priority = 2
kind = "ev_charger"
phases = 1
min_current_a = 6
max_current_a = 16
  [device.actuator]
  type = "mqtt"
  topic = "out/ev/current"
  switch_topic = "out/ev/enable"
  [device.readings]
  connected_topic = "in/car_plugged"
""")
    received: dict[str, str] = {}
    observer = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="observer-ev")
    observer.on_message = lambda c, u, m: received.__setitem__(m.topic, m.payload.decode())
    observer.connect("127.0.0.1", broker_port)
    observer.subscribe("out/#")
    observer.loop_start()

    SURPLUS = 5000.0

    def drawn_w():
        total = float(received.get("out/bat", 0))
        if received.get("out/ev/enable") == "ON":
            total += float(received.get("out/ev/current", 0)) * 230
        return total

    async def scenario():
        task = asyncio.create_task(run(str(config)))
        meter = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="meter-ev")
        meter.connect("127.0.0.1", broker_port)
        meter.loop_start()
        try:
            async def feed_until(predicate, what, timeout=12.0):
                end = time.monotonic() + timeout
                while time.monotonic() < end:
                    meter.publish("grid/export_w", str(SURPLUS - drawn_w()))  # simulated meter reacts to the commands
                    meter.publish("in/bat_soc", "50")
                    meter.publish("in/car_plugged", state["plugged"])
                    if predicate():
                        return
                    await asyncio.sleep(0.1)
                raise AssertionError(f"timeout waiting for: {what}; received={received}")

            state = {"plugged": "ON"}
            # 5000 W: battery takes 3000 W, the car the remaining 2000 W = 8 A
            await feed_until(lambda: received.get("out/bat") == "3000" and received.get("out/ev/current") == "8.0"
                             and received.get("out/ev/enable") == "ON", "battery 3000 W and EV 8 A")
            # car unplugged: the charger is switched off
            state["plugged"] = "OFF"
            await feed_until(lambda: received.get("out/ev/enable") == "OFF", "charger off when unplugged")
            # plugged again: back to 8 A
            state["plugged"] = "ON"
            await feed_until(lambda: received.get("out/ev/enable") == "ON" and received.get("out/ev/current") == "8.0", "charger back on")
            meter.loop_stop()
        finally:
            import os
            import signal

            os.kill(os.getpid(), signal.SIGTERM)  # same path as `docker stop`
            await asyncio.wait_for(task, 10)

    try:
        asyncio.run(scenario())
        assert wait_for(lambda: received.get("out/bat") == "0")
        assert wait_for(lambda: received.get("out/ev/enable") == "OFF")
    finally:
        observer.loop_stop()
