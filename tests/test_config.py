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
    assert [d.id for d in cfg.devices] == ["dimmer_heater", "pool_pump", "server"]
    assert cfg.actuators["server"].type == "http"
    assert cfg.source.topics == {"export": "house/grid/power_w"}


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
