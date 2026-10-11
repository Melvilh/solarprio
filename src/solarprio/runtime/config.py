"""TOML configuration for the standalone runtime."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import Device, DeviceKind


class ConfigError(ValueError):
    pass


@dataclass
class RuntimeConfig:
    interval_s: float = 5.0
    stale_after_s: float = 30.0  # measurement older than this is considered lost
    on_stale: str = "off"  # "off" (safe default) or "hold"
    resend_every_s: float = 60.0  # re-send unchanged commands, in case a device missed one


@dataclass
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    client_id: str = "solarprio"
    # Some brokers (Victron Venus OS) only publish values while a keep-alive is received periodically.
    keepalive_topic: str | None = None
    keepalive_interval_s: float = 30.0
    keepalive_payload: str = '{"keepalive-options": ["suppress-republish"]}'  # sent after the first (empty) one


@dataclass
class SourceConfig:
    mode: str  # "export" or "production"
    topics: dict[str, list[str]]  # export: {"export"}; production: {"production", "consumption"}; several = summed
    field: str | None = None  # JSON field to extract from payloads, if payloads are JSON
    invert: bool = False  # export: meter reports import as positive
    margin_w: float = 0.0  # watts deliberately left unrouted (keeps a small export despite measurement noise and latency)


@dataclass
class ReadingsConfig:
    """MQTT topics giving a device's measured power, state of charge and plug state."""

    measured_topic: str | None = None
    soc_topic: str | None = None
    connected_topic: str | None = None
    # Payload words meaning plugged / unplugged; default words (on/off, true/false, 1/0...) apply when unset.
    # A payload in neither list counts as "unknown", which the engine treats as plugged in.
    connected_values: list[str] | None = None
    disconnected_values: list[str] | None = None
    field: str | None = None  # JSON field to extract from payloads, if payloads are JSON
    measured_unit: str = "W"  # "W" or "kW"


@dataclass
class ActuatorConfig:
    type: str  # "mqtt" or "http"
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    runtime: RuntimeConfig
    mqtt: MqttConfig
    source: SourceConfig
    devices: list[Device]
    actuators: dict[str, ActuatorConfig]
    readings: dict[str, ReadingsConfig] = field(default_factory=dict)


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return parse_config(raw)


def parse_config(raw: dict[str, Any]) -> Config:
    runtime = RuntimeConfig(**raw.get("runtime", {}))
    if runtime.on_stale not in ("off", "hold"):
        raise ConfigError("runtime.on_stale must be 'off' or 'hold'")
    if runtime.interval_s <= 0:
        raise ConfigError("runtime.interval_s must be > 0")

    try:
        mqtt = MqttConfig(**raw.get("mqtt", {}))
    except TypeError as e:
        raise ConfigError(f"invalid [mqtt] section: {e}") from e
    if mqtt.keepalive_interval_s <= 0:
        raise ConfigError("mqtt.keepalive_interval_s must be > 0")

    src = raw.get("source")
    if not src:
        raise ConfigError("missing [source] section")
    mode = src.get("mode")
    if mode == "export":
        needed = ["export_topic"]
    elif mode == "production":
        needed = ["production_topic", "consumption_topic"]
    else:
        raise ConfigError("source.mode must be 'export' or 'production'")
    for key in needed:
        if key not in src:
            raise ConfigError(f"source.{key} is required in {mode} mode")
    topics: dict[str, list[str]] = {}
    for key in needed:
        value = src[key]
        names = [value] if isinstance(value, str) else value
        if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
            raise ConfigError(f"source.{key} must be a topic or a non-empty list of topics")
        topics[key.removesuffix("_topic")] = names
    if float(src.get("margin_w", 0.0)) < 0:
        raise ConfigError("source.margin_w must be >= 0")
    source = SourceConfig(
        mode=mode,
        topics=topics,
        field=src.get("field"),
        invert=bool(src.get("invert", False)),
        margin_w=float(src.get("margin_w", 0.0)),
    )

    devices: list[Device] = []
    actuators: dict[str, ActuatorConfig] = {}
    readings: dict[str, ReadingsConfig] = {}
    for entry in raw.get("device", []):
        entry = dict(entry)
        reading_cfg = entry.pop("readings", None)
        actuator = entry.pop("actuator", None)
        if actuator is None or "type" not in actuator:
            raise ConfigError(f"device {entry.get('id')!r}: missing actuator.type")
        try:
            entry["kind"] = DeviceKind(entry["kind"])
            device = Device(**entry)
        except (KeyError, TypeError, ValueError) as e:
            raise ConfigError(f"invalid device {entry.get('id')!r}: {e}") from e
        if actuator["type"] not in ("mqtt", "http"):
            raise ConfigError(f"device {device.id!r}: unknown actuator type {actuator['type']!r}")
        # fail at start-up, not at the first command
        if actuator["type"] == "mqtt" and not actuator.get("topic"):
            raise ConfigError(f"device {device.id!r}: an mqtt actuator needs a 'topic'")
        if actuator["type"] == "http":
            url = str(actuator.get("url", ""))
            if not url.lower().startswith(("http://", "https://")):
                raise ConfigError(f"device {device.id!r}: an http actuator needs an 'url' starting with http:// or https://")
        devices.append(device)
        if reading_cfg:
            try:
                readings[device.id] = ReadingsConfig(**reading_cfg)
            except TypeError as e:
                raise ConfigError(f"device {device.id!r}: invalid readings section: {e}") from e
            if readings[device.id].measured_unit not in ("W", "kW"):
                raise ConfigError(f"device {device.id!r}: readings.measured_unit must be 'W' or 'kW'")
        actuators[device.id] = ActuatorConfig(
            type=actuator["type"], options={k: v for k, v in actuator.items() if k != "type"}
        )

    if not devices:
        raise ConfigError("no [[device]] defined")
    ids = [d.id for d in devices]
    if len(set(ids)) != len(ids):
        raise ConfigError("duplicate device ids")

    return Config(runtime=runtime, mqtt=mqtt, source=source, devices=devices, actuators=actuators, readings=readings)
