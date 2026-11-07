from pathlib import Path

import pytest

from solarprio.runtime.config import ConfigError, load_config, parse_config
from solarprio.runtime.mqtt_bus import parse_number

ROOT = Path(__file__).resolve().parent.parent


def minimal(**overrides):
    raw = {
        "source": {"mode": "export", "export_topic": "grid"},
        "device": [
            {"id": "a", "name": "A", "priority": 1, "kind": "on_off", "power_w": 100,
             "actuator": {"type": "mqtt", "topic": "t"}},
        ],
    }
    raw.update(overrides)
    return raw


def test_example_config_is_valid():
    cfg = load_config(ROOT / "config.example.toml")
    assert [d.id for d in cfg.devices] == ["dimmer_heater", "pool_pump", "heavy_tasks", "home_battery", "wallbox"]
    assert cfg.devices[2].kind.value == "task" and cfg.actuators["heavy_tasks"].type == "mqtt"
    assert cfg.source.topics == {"export": ["house/grid/power_w"]}


def test_production_mode_needs_both_topics():
    with pytest.raises(ConfigError, match="consumption_topic"):
        parse_config(minimal(source={"mode": "production", "production_topic": "p"}))


@pytest.mark.parametrize(
    "raw, message",
    [
        (minimal(source={"mode": "nope"}), "source.mode"),
        (minimal(device=[]), "no \\[\\[device\\]\\]"),
        (minimal(runtime={"on_stale": "explode"}), "on_stale"),
        (minimal(runtime={"interval_s": 0}), "interval_s"),
    ],
)
def test_invalid_configs_are_rejected(raw, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(raw)


def test_invalid_device_is_reported_with_its_id():
    bad = minimal()
    bad["device"][0]["power_w"] = -5
    with pytest.raises(ConfigError, match="'a'"):
        parse_config(bad)


def test_unknown_actuator_type_and_duplicate_ids():
    bad = minimal()
    bad["device"][0]["actuator"] = {"type": "carrier-pigeon"}
    with pytest.raises(ConfigError, match="actuator type"):
        parse_config(bad)
    dup = minimal()
    dup["device"].append(dict(dup["device"][0]))
    with pytest.raises(ConfigError, match="duplicate"):
        parse_config(dup)


def test_parse_number_plain_and_json():
    assert parse_number(b" 123.5\n") == 123.5
    assert parse_number('{"ENERGY": {"Power": 120}}', "ENERGY.Power") == 120.0
    with pytest.raises(KeyError):
        parse_number('{"a": 1}', "b")


def test_actuators_are_checked_at_load_time():
    base = {"id": "a", "name": "A", "priority": 1, "kind": "on_off", "power_w": 100}
    with pytest.raises(ConfigError, match="topic"):
        parse_config(minimal_with({**base, "actuator": {"type": "mqtt"}}))
    with pytest.raises(ConfigError, match="url"):
        parse_config(minimal_with({**base, "actuator": {"type": "http"}}))
    with pytest.raises(ConfigError, match="http:// or https://"):
        parse_config(minimal_with({**base, "actuator": {"type": "http", "url": "file:///etc/passwd"}}))
    parse_config(minimal_with({**base, "actuator": {"type": "http", "url": "HTTPS://host/x"}}))  # accepted


def minimal_with(device):
    return {"source": {"mode": "export", "export_topic": "g"}, "device": [device]}


def test_victron_example_config_is_valid_and_has_the_victron_specifics():
    cfg = load_config(ROOT / "config.victron.example.toml")
    assert cfg.mqtt.keepalive_topic == "R/<PORTAL_ID>/keepalive" and cfg.mqtt.keepalive_interval_s < 60
    assert len(cfg.source.topics["export"]) == 3 and cfg.source.field == "value" and cfg.source.invert
    ev = cfg.devices[0]
    assert (ev.min_power_w, ev.power_w) == (1380, 3680)
    opts = cfg.actuators["evcs"].options
    assert opts["payload_template"] == '{"value": {value}}' and opts["payload_on"] == '{"value": 1}'
    assert cfg.readings["evcs"].disconnected_values == ["0"]
