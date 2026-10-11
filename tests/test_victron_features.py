"""Runtime features needed to talk to a Victron GX device (Venus OS MQTT): keep-alive, summed phases, JSON payloads."""
import asyncio

import pytest

from solarprio import Device, DeviceKind
from solarprio.runtime.adapters import MeasurementUnavailable, MqttActuator, MqttPowerSource, MqttReadings
from solarprio.runtime.config import ConfigError, ReadingsConfig, SourceConfig, parse_config
from solarprio.runtime.keepalive import keepalive_loop

from fakes import FakeBus, ev_dev, run

PHASES = ["N/id/system/0/Ac/Grid/L1/Power", "N/id/system/0/Ac/Grid/L2/Power", "N/id/system/0/Ac/Grid/L3/Power"]


def source(bus, **kw):
    cfg = SourceConfig(mode="export", topics={"export": PHASES}, field="value", **kw)
    return MqttPowerSource(bus, cfg, stale_after_s=30)


def feed_phases(bus, values, age=0.0):
    for topic, v in zip(PHASES, values):
        bus.feed(topic, '{"value": %s}' % v, age)


# ------------------------------------------------------------- summed phases

def test_phases_are_summed_and_the_sign_can_be_inverted():
    bus = FakeBus()
    feed_phases(bus, [-300, -250.5, -100])  # exporting on three phases (sign convention to be checked on the real system)
    src = source(bus)
    assert bus.subscribed == set(PHASES)  # subscribes to every phase
    assert run(src.read_available_w(0)) == -650.5
    assert run(source(bus, invert=True).read_available_w(0)) == 650.5
    assert run(source(bus, invert=True).read_available_w(2000)) == 2650.5  # routed power is added back


@pytest.mark.parametrize("bad", ["missing", "stale", "null", "garbage"])
def test_one_unusable_phase_makes_the_whole_measurement_unavailable(bad):
    bus = FakeBus()
    feed_phases(bus, [-300, -250, -100])
    if bad == "missing":
        del bus.values[PHASES[2]]
    elif bad == "stale":
        bus.feed(PHASES[1], '{"value": -250}', age=31)
    elif bad == "null":
        bus.feed(PHASES[0], '{"value": null}')  # a phase that does not exist on this installation
    else:
        bus.feed(PHASES[0], "not json")
    with pytest.raises(MeasurementUnavailable):
        run(source(bus).read_available_w(0))


def test_config_accepts_one_topic_or_a_list_and_rejects_empty():
    base = {"device": [{"id": "a", "name": "A", "priority": 1, "kind": "on_off", "power_w": 100, "actuator": {"type": "mqtt", "topic": "t"}}]}
    one = parse_config({**base, "source": {"mode": "export", "export_topic": "g"}})
    assert one.source.topics == {"export": ["g"]}
    many = parse_config({**base, "source": {"mode": "export", "export_topic": ["a", "b", "c"]}})
    assert many.source.topics == {"export": ["a", "b", "c"]}
    for bad in ([], [""], [1], ""):
        with pytest.raises(ConfigError, match="topic"):
            parse_config({**base, "source": {"mode": "export", "export_topic": bad}})


# ---------------------------------------------------------- numeric plug status

def test_victron_status_codes_decide_plugged_state():
    bus = FakeBus()
    cfg = ReadingsConfig(
        connected_topic="N/id/evcharger/40/Status", field="value",
        connected_values=["1", "2", "3", "4", "5", "6", "7", "21", "22", "23", "24"], disconnected_values=["0"],
    )
    readings = MqttReadings(bus, {"ev": cfg}, stale_after_s=30)
    expected = {0: False, 1: True, 2: True, 3: True, 4: True, 21: True, 24: True, 9: None}  # 9 = welded contacts error
    for status, plugged in expected.items():
        bus.feed("N/id/evcharger/40/Status", '{"value": %d}' % status)
        got = readings.read_readings().get("ev")
        assert (got.connected if got else None) is plugged, status


# ----------------------------------------------------------- JSON payloads

def test_ev_commands_use_json_payloads_in_victron_format():
    bus, dev = FakeBus(), ev_dev(phases=3, voltage_v=230)
    opt = {
        "topic": "W/id/evcharger/40/SetCurrent", "payload_template": '{"value": {value}}',
        "switch_topic": "W/id/evcharger/40/StartStop", "payload_on": '{"value": 1}', "payload_off": '{"value": 0}',
    }
    act = MqttActuator(bus, {"ev": dev}, {"ev": opt})
    run(act.apply("ev", 10 * 690))
    assert bus.published == [("W/id/evcharger/40/SetCurrent", '{"value": 10.0}'), ("W/id/evcharger/40/StartStop", '{"value": 1}')]
    bus.published.clear()
    run(act.apply("ev", 0))
    assert bus.published == [("W/id/evcharger/40/StartStop", '{"value": 0}')]


def test_payload_template_also_applies_to_a_battery_setpoint():
    bus = FakeBus()
    bat = Device(id="bat", name="B", priority=1, kind=DeviceKind.BATTERY, power_w=3000)
    act = MqttActuator(bus, {"bat": bat}, {"bat": {"topic": "W/id/settings/0/Settings/CGwacs/MaxChargePower", "payload_template": '{"value": {value}}'}})
    run(act.apply("bat", 1500))
    assert bus.published == [("W/id/settings/0/Settings/CGwacs/MaxChargePower", '{"value": 1500}')]


# ----------------------------------------------------------------- keep-alive

class KeepaliveBus:
    def __init__(self):
        self.connections, self.sent, self.fail = 1, [], 0

    def publish(self, topic, payload, retain=False):
        if self.fail:
            self.fail -= 1
            raise ConnectionError("not connected")
        self.sent.append((topic, payload))


def test_keepalive_first_request_is_empty_then_suppresses_republish_and_empties_again_after_reconnect():
    async def scenario():
        bus, stop = KeepaliveBus(), asyncio.Event()
        task = asyncio.create_task(keepalive_loop(bus, "R/id/keepalive", 0.05, '{"keepalive-options": ["suppress-republish"]}', stop))
        await asyncio.sleep(0.18)
        bus.connections += 1  # the connection was re-established
        await asyncio.sleep(0.12)
        stop.set()
        await task
        return bus.sent

    sent = asyncio.run(scenario())
    payloads = [p for _, p in sent]
    assert payloads[0] == ""  # full republish first
    assert all(topic == "R/id/keepalive" for topic, _ in sent)
    assert payloads[1] == '{"keepalive-options": ["suppress-republish"]}'
    later = payloads[2:]
    assert "" in later  # after the reconnection, everything is requested again
    assert later[later.index("") + 1:][:1] in ([], ['{"keepalive-options": ["suppress-republish"]}'])


def test_keepalive_retries_quickly_when_the_broker_is_unreachable_and_does_not_mark_it_sent():
    async def scenario():
        bus, stop = KeepaliveBus(), asyncio.Event()
        bus.fail = 2
        task = asyncio.create_task(keepalive_loop(bus, "R/id/keepalive", 0.05, "later", stop))
        await asyncio.sleep(0.3)
        stop.set()
        await task
        return bus.sent

    sent = asyncio.run(scenario())
    assert sent and sent[0][1] == ""  # the first successful one is still the full request


def test_keepalive_interval_is_validated():
    base = {"source": {"mode": "export", "export_topic": "g"},
            "device": [{"id": "a", "name": "A", "priority": 1, "kind": "on_off", "power_w": 100, "actuator": {"type": "mqtt", "topic": "t"}}]}
    with pytest.raises(ConfigError, match="keepalive_interval_s"):
        parse_config({**base, "mqtt": {"keepalive_topic": "R/id/keepalive", "keepalive_interval_s": 0}})
    cfg = parse_config({**base, "mqtt": {"keepalive_topic": "R/id/keepalive"}})
    assert cfg.mqtt.keepalive_interval_s == 30  # under Victron's 60 s timeout


# ------------------------------------------------------------- export margin

def test_margin_is_kept_back_from_the_available_power():
    bus = FakeBus()
    feed_phases(bus, [-300, -250, -100])  # meter reads -650 W; with invert that is 650 W exported
    assert run(source(bus, invert=True, margin_w=50).read_available_w(0)) == 600
    assert run(source(bus, invert=True, margin_w=50).read_available_w(1000)) == 1600  # routed power is still added back first


def test_a_negative_margin_is_refused():
    base = {"mqtt": {"host": "h"}, "source": {"mode": "export", "topics": {"export": "t"}, "margin_w": -5}, "devices": []}
    with pytest.raises(ConfigError):
        parse_config(base)
