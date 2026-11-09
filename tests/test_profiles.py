import tomllib
from pathlib import Path

import pytest

from solarprio.profiles import ProfileError, expand, get_profile, load_profiles
from solarprio.runtime.config import ConfigError, parse_config

ROOT = Path(__file__).resolve().parents[1]


def test_every_profile_is_valid():
    assert len(load_profiles()) >= 4
    for p in load_profiles().values():
        assert p["status"] in ("verified", "simulated", "from_docs", "untested")


def test_unknown_profile_and_params():
    with pytest.raises(ProfileError):
        get_profile("nope")
    with pytest.raises(ProfileError):
        expand("victron-grid", {"portal_id": "x", "bogus": 1}, "source")
    with pytest.raises(ProfileError):
        expand("victron-grid", {}, "source")  # portal_id required
    with pytest.raises(ProfileError):
        expand("victron-grid", {"portal_id": "x"}, "device")  # wrong target
    with pytest.raises(ProfileError):
        expand("victron-grid", {"portal_id": "x", "phases": 0}, "source")


def _load(name):
    return tomllib.loads((ROOT / name).read_text())


def test_victron_profile_equals_hand_written_example():
    text = (ROOT / "config.victron.example.toml").read_text().replace("<EVCS_INSTANCE>", "40")
    hand = parse_config(tomllib.loads(text))
    prof = parse_config(_load("examples/victron-profile.toml"))
    assert prof.source == hand.source
    assert (prof.mqtt.keepalive_topic, prof.mqtt.keepalive_interval_s) == (hand.mqtt.keepalive_topic, hand.mqtt.keepalive_interval_s)
    (hd,), (pd,) = hand.devices, prof.devices
    for attr in ("kind", "phases", "voltage_v", "min_current_a", "max_current_a", "min_on_s", "start_margin_w"):
        assert getattr(pd, attr) == getattr(hd, attr), attr
    assert prof.actuators["evcs"] == hand.actuators["evcs"]
    assert prof.readings["evcs"] == hand.readings["evcs"]


def test_local_values_override_profile():
    raw = _load("examples/victron-profile.toml")
    raw["device"][0]["max_current_a"] = 10
    assert parse_config(raw).devices[0].max_current_a == 10


def test_profile_errors_are_config_errors():
    raw = _load("examples/victron-profile.toml")
    raw["device"][0]["profile"] = "nope"
    with pytest.raises(ConfigError):
        parse_config(raw)


def test_every_profile_is_documented_and_its_docs_exist():
    compat = (ROOT / "docs" / "COMPATIBILITY.md").read_text()
    profiles_doc = (ROOT / "docs" / "PROFILES.md").read_text()
    for pid, p in load_profiles().items():
        assert f"`{pid}`" in compat, f"{pid} is missing from docs/COMPATIBILITY.md"
        assert f"`{pid}`" in profiles_doc, f"{pid} is missing from docs/PROFILES.md"
        if p.get("docs"):
            assert (ROOT / p["docs"]).exists(), p["docs"]
