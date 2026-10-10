"""Concrete PowerSource and DeviceActuator implementations for the standalone runtime."""

from __future__ import annotations

import asyncio
import logging
import urllib.request

from ..models import Device, DeviceKind, DeviceReading
from ..sources import available_from_export, available_from_production
from .config import ActuatorConfig, ReadingsConfig, SourceConfig
from .mqtt_bus import MqttBus, parse_number

log = logging.getLogger(__name__)


class MeasurementUnavailable(Exception):
    """The power measurement is missing, unparsable or too old."""


class MqttPowerSource:
    def __init__(self, bus: MqttBus, cfg: SourceConfig, stale_after_s: float) -> None:
        self._bus, self._cfg, self._stale_after_s = bus, cfg, stale_after_s
        for topics in cfg.topics.values():
            for topic in topics:
                bus.subscribe(topic)

    def _read(self, key: str) -> float:
        """Value of a quantity; when several topics are configured (one per phase) they are summed.

        Every topic must be fresh and numeric: a missing phase makes the whole measurement unavailable
        rather than silently under-counting.
        """
        total = 0.0
        for topic in self._cfg.topics[key]:
            item = self._bus.latest(topic)
            if item is None:
                raise MeasurementUnavailable(f"no value received yet on {topic}")
            payload, age = item
            if age > self._stale_after_s:
                raise MeasurementUnavailable(f"value on {topic} is {age:.0f}s old")
            try:
                total += parse_number(payload, self._cfg.field)
            except (ValueError, KeyError, TypeError) as e:
                raise MeasurementUnavailable(f"cannot parse payload on {topic}: {e}") from e
        return total

    async def read_available_w(self, routed_w: float) -> float:
        if self._cfg.mode == "export":
            export = self._read("export")
            if self._cfg.invert:
                export = -export
            return available_from_export(export, routed_w)
        return available_from_production(self._read("production"), self._read("consumption"), routed_w)


TRUTHY = {"on", "true", "1", "connected", "plugged", "plugged_in", "yes"}
FALSY = {"off", "false", "0", "disconnected", "unplugged", "no"}


class MqttReadings:
    """Reads each device's measured power, state of charge and plug state from MQTT topics."""

    def __init__(self, bus: MqttBus, configs: dict[str, ReadingsConfig], stale_after_s: float) -> None:
        self._bus, self._configs, self._stale_after_s = bus, configs, stale_after_s
        for cfg in configs.values():
            for topic in (cfg.measured_topic, cfg.soc_topic, cfg.connected_topic):
                if topic:
                    bus.subscribe(topic)

    def _fresh(self, topic: str | None) -> bytes | None:
        if not topic:
            return None
        item = self._bus.latest(topic)
        if item is None or item[1] > self._stale_after_s:
            return None
        return item[0]

    def read_readings(self) -> dict[str, DeviceReading]:
        out: dict[str, DeviceReading] = {}
        for device_id, cfg in self._configs.items():
            measured = soc = connected = None
            if (raw := self._fresh(cfg.measured_topic)) is not None:
                try:
                    measured = parse_number(raw, cfg.field) * (1000 if cfg.measured_unit == "kW" else 1)
                except (ValueError, KeyError, TypeError):
                    pass
            if (raw := self._fresh(cfg.soc_topic)) is not None:
                try:
                    soc = parse_number(raw, cfg.field)
                except (ValueError, KeyError, TypeError):
                    pass
            if (raw := self._fresh(cfg.connected_topic)) is not None:
                word = raw.decode(errors="ignore").strip().strip('"').lower()
                if cfg.field:  # JSON payload such as {"value": 2}
                    try:
                        word = str(parse_number(raw, cfg.field)).removesuffix(".0")
                    except (ValueError, KeyError, TypeError):
                        word = ""
                yes = {w.lower() for w in cfg.connected_values} if cfg.connected_values is not None else TRUTHY
                no = {w.lower() for w in cfg.disconnected_values} if cfg.disconnected_values is not None else FALSY
                connected = True if word in yes else False if word in no else None
            if measured is not None or soc is not None or connected is not None:
                out[device_id] = DeviceReading(measured_w=measured, soc=soc, connected=connected)
        return out


class MqttActuator:
    """Publishes a command per device.

    Options: ``topic`` (required); ``payload_on`` / ``payload_off`` for on/off loads (any text, e.g. JSON);
    ``payload_template`` wraps a numeric command, ``{value}`` being replaced (e.g. ``{"value": {value}}``);
    ``scale`` for the others: ``"percent"`` (proportional default), ``"watts"`` (battery default),
    ``"amps"`` (EV charger default). An EV charger may also have a ``switch_topic`` (same payload options),
    switched on after the current is set and off when the charge stops; without it 0 A pauses the charger.
    """

    def __init__(self, bus: MqttBus, devices: dict[str, Device], options: dict[str, dict]) -> None:
        self._bus, self._devices, self._options = bus, devices, options

    async def apply(self, device_id: str, power_w: float) -> None:
        dev, opt = self._devices[device_id], self._options[device_id]
        retain = opt.get("retain", False)
        on, off = opt.get("payload_on", "ON"), opt.get("payload_off", "OFF")
        if dev.kind is DeviceKind.ON_OFF:
            self._bus.publish(opt["topic"], on if power_w > 0 else off, retain=retain)
            return
        default_scale = {DeviceKind.EV_CHARGER: "amps", DeviceKind.BATTERY: "watts"}.get(dev.kind, "percent")
        scale = opt.get("scale", default_scale)
        value = {
            "watts": f"{power_w:.0f}",
            "amps": f"{dev.current_for(power_w):.1f}",
            "percent": f"{power_w / dev.power_w * 100:.1f}",
        }[scale]
        if "payload_template" in opt:
            value = opt["payload_template"].replace("{value}", value)  # not str.format: JSON braces
        switch_topic = opt.get("switch_topic")
        if dev.kind is DeviceKind.EV_CHARGER and switch_topic:
            if power_w > 0:
                self._bus.publish(opt["topic"], value, retain=retain)
                self._bus.publish(switch_topic, on, retain=retain)
            else:
                self._bus.publish(switch_topic, off, retain=retain)
            return
        self._bus.publish(opt["topic"], value, retain=retain)


class HttpActuator:
    """Calls a URL template; ``{power_w}``, ``{percent}``, ``{amps}`` and ``{state}`` (on/off) are substituted."""

    def __init__(self, devices: dict[str, Device], options: dict[str, dict], timeout_s: float = 5.0) -> None:
        self._devices, self._options, self._timeout_s = devices, options, timeout_s

    async def apply(self, device_id: str, power_w: float) -> None:
        dev, opt = self._devices[device_id], self._options[device_id]
        url = opt["url"].format(
            power_w=f"{power_w:.0f}",
            percent=f"{power_w / dev.power_w * 100:.1f}",
            state="on" if power_w > 0 else "off",
            amps=f"{dev.current_for(power_w):.1f}",
        )
        req = urllib.request.Request(url, method=opt.get("method", "GET"))
        await asyncio.to_thread(self._call, req)

    def _call(self, req: urllib.request.Request) -> None:
        with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:  # noqa: S310 - URL comes from operator config
            resp.read()


class DispatchActuator:
    """Routes each device to the actuator type declared in its config."""

    def __init__(self, bus: MqttBus, devices: list[Device], actuators: dict[str, ActuatorConfig]) -> None:
        by_id = {d.id: d for d in devices}
        mqtt_opts = {i: a.options for i, a in actuators.items() if a.type == "mqtt"}
        http_opts = {i: a.options for i, a in actuators.items() if a.type == "http"}
        self._mqtt = MqttActuator(bus, by_id, mqtt_opts)
        self._http = HttpActuator(by_id, http_opts)
        self._type = {i: a.type for i, a in actuators.items()}

    async def apply(self, device_id: str, power_w: float) -> None:
        actuator = self._mqtt if self._type[device_id] == "mqtt" else self._http
        await actuator.apply(device_id, power_w)
