import asyncio

from solarprio import Device, DeviceKind, Engine
from solarprio.runtime.adapters import MeasurementUnavailable
from solarprio.runtime.config import RuntimeConfig
from solarprio.runtime.controller import Controller


class FakeSource:
    def __init__(self):
        self.export = 0.0
        self.error: Exception | None = None

    async def read_available_w(self, routed_w):
        if self.error:
            raise self.error
        return self.export + routed_w


class FakeActuator:
    def __init__(self):
        self.calls: list[tuple[str, float]] = []
        self.fail_for: set[str] = set()

    async def apply(self, device_id, power_w):
        if device_id in self.fail_for:
            raise RuntimeError("boom")
        self.calls.append((device_id, power_w))


def build(on_stale="off", **dev_kw):
    clock = [0.0]
    source, actuator = FakeSource(), FakeActuator()
    devices = [
        Device(id="a", name="A", priority=1, kind=DeviceKind.ON_OFF, power_w=1000, **dev_kw),
        Device(id="b", name="B", priority=2, kind=DeviceKind.ON_OFF, power_w=500),
    ]
    ctl = Controller(Engine(devices), source, actuator, RuntimeConfig(on_stale=on_stale, resend_every_s=60), lambda: clock[0])
    return ctl, source, actuator, clock


def run(coro):
    return asyncio.run(coro)


def test_commands_are_sent_only_when_they_change():
    ctl, source, actuator, clock = build()
    source.export = 1600  # a (1000) + b (500) both fit

    run(ctl.tick())
    assert actuator.calls == [("a", 1000), ("b", 500)]

    clock[0] = 5
    run(ctl.tick())
    assert len(actuator.calls) == 2  # unchanged: nothing re-sent


def test_unchanged_commands_are_resent_after_resend_interval():
    ctl, source, actuator, clock = build()
    source.export = 1600
    run(ctl.tick())
    clock[0] = 61
    run(ctl.tick())
    assert len(actuator.calls) == 4


def test_lost_measurement_switches_off_by_default():
    ctl, source, actuator, clock = build()
    source.export = 1600
    run(ctl.tick())

    source.error = MeasurementUnavailable("stale")
    clock[0] = 5
    run(ctl.tick())
    assert actuator.calls[-2:] == [("a", 0.0), ("b", 0.0)]


def test_lost_measurement_hold_keeps_state():
    ctl, source, actuator, clock = build(on_stale="hold")
    source.export = 1600
    run(ctl.tick())
    n = len(actuator.calls)

    source.error = MeasurementUnavailable("stale")
    clock[0] = 5
    run(ctl.tick())
    assert len(actuator.calls) == n


def test_lost_measurement_still_honors_min_on_time():
    ctl, source, actuator, clock = build(min_on_s=300)
    source.export = 1600
    run(ctl.tick())
    source.error = MeasurementUnavailable("stale")
    clock[0] = 10
    run(ctl.tick())
    assert ("a", 0.0) not in actuator.calls  # a is held on, b goes off
    assert ("b", 0.0) in actuator.calls


def test_failing_device_does_not_block_others_and_is_retried():
    ctl, source, actuator, clock = build()
    source.export = 1600
    actuator.fail_for = {"a"}
    run(ctl.tick())
    assert actuator.calls == [("b", 500)]

    actuator.fail_for = set()
    clock[0] = 5
    run(ctl.tick())
    assert ("a", 1000) in actuator.calls  # failed send was not recorded, so it is retried


def test_shutdown_switches_everything_off():
    ctl, source, actuator, clock = build(min_on_s=300)
    source.export = 1600
    run(ctl.tick())
    run(ctl.shutdown())
    assert actuator.calls[-2:] == [("a", 0.0), ("b", 0.0)]  # even with min_on_s


def test_slow_device_does_not_delay_others():
    class SlowActuator(FakeActuator):
        async def apply(self, device_id, power_w):
            if device_id == "a":
                await asyncio.sleep(0.3)
            await super().apply(device_id, power_w)

    ctl, source, _, clock = build()
    ctl._actuator = SlowActuator()
    source.export = 1600

    async def timed():
        t0 = asyncio.get_running_loop().time()
        await ctl.tick()
        return asyncio.get_running_loop().time() - t0

    # concurrent: total ~0.3 s (one slow device), not the sum of all devices
    assert asyncio.run(timed()) < 0.5
    assert ("b", 500) in ctl._actuator.calls


def test_shutdown_reports_devices_that_could_not_be_switched_off():
    ctl, source, actuator, clock = build()
    source.export = 1600
    run(ctl.tick())
    actuator.fail_for = {"b"}
    assert run(ctl.shutdown()) == ["b"]
