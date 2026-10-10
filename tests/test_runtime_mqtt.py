"""End-to-end test: real MQTT broker (amqtt) + the real runtime + a paho client playing meter and device."""

import asyncio
import socket
import threading
import time

import paho.mqtt.client as mqtt
import pytest

from solarprio.runtime.app import run


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def broker_port():
    from amqtt.broker import Broker

    port = free_port()
    ready, stop = threading.Event(), threading.Event()
    errors: list[Exception] = []

    def serve():
        async def main():
            broker = Broker({
                "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
                "sys_interval": 0,
                "auth": {"allow-anonymous": True, "plugins": ["auth_anonymous"]},
                "topic-check": {"enabled": False},
            })
            await broker.start()
            ready.set()
            while not stop.is_set():
                await asyncio.sleep(0.05)
            await broker.shutdown()

        try:
            asyncio.run(main())
        except Exception as e:  # noqa: BLE001
            errors.append(e)
            ready.set()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    assert ready.wait(10)
    if errors:
        pytest.skip(f"test broker could not start: {errors[0]!r}")
    yield port
    stop.set()
    t.join(5)


def wait_for(predicate, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


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
