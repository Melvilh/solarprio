"""Shared test doubles."""

import asyncio
import time

from solarprio import Device, DeviceKind


class FakeBus:
    """Stands in for MqttBus: stores published messages and serves canned values."""

    def __init__(self):
        self.published: list[tuple[str, str]] = []
        self.values: dict[str, tuple[bytes, float]] = {}  # topic -> (payload, age)
        self.subscribed: set[str] = set()

    def subscribe(self, topic):
        self.subscribed.add(topic)

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload))

    def latest(self, topic):
        return self.values.get(topic)

    def feed(self, topic, payload, age=0.0):
        self.values[topic] = (payload.encode() if isinstance(payload, str) else payload, age)


def ev_dev(**kw):
    return Device(**{**dict(id="ev", name="Car", priority=1, kind=DeviceKind.EV_CHARGER, phases=1), **kw})


def run(coro):
    return asyncio.run(coro)


def wait_for(predicate, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False
