"""Concrete PowerSource and DeviceActuator implementations for the standalone runtime."""

from __future__ import annotations

import asyncio
import logging
import urllib.request

from ..models import Device, DeviceKind
from ..sources import available_from_export, available_from_production
from .config import ActuatorConfig, SourceConfig
from .mqtt_bus import MqttBus, parse_number

log = logging.getLogger(__name__)


class MeasurementUnavailable(Exception):
    """The power measurement is missing, unparsable or too old."""


class MqttPowerSource:
    def __init__(self, bus: MqttBus, cfg: SourceConfig, stale_after_s: float) -> None:
        self._bus, self._cfg, self._stale_after_s = bus, cfg, stale_after_s
        for topic in cfg.topics.values():
            bus.subscribe(topic)

    def _read(self, key: str) -> float:
        topic = self._cfg.topics[key]
        item = self._bus.latest(topic)
        if item is None:
            raise MeasurementUnavailable(f"no value received yet on {topic}")
        payload, age = item
        if age > self._stale_after_s:
            raise MeasurementUnavailable(f"value on {topic} is {age:.0f}s old")
        try:
            return parse_number(payload, self._cfg.field)
        except (ValueError, KeyError, TypeError) as e:
            raise MeasurementUnavailable(f"cannot parse payload on {topic}: {e}") from e

    async def read_available_w(self, routed_w: float) -> float:
        if self._cfg.mode == "export":
            export = self._read("export")
            if self._cfg.invert:
                export = -export
            return available_from_export(export, routed_w)
        return available_from_production(self._read("production"), self._read("consumption"), routed_w)


class MqttActuator:
    """Publishes a command per device.

    Options: ``topic`` (required); ``payload_on`` / ``payload_off`` for on/off loads;
    for proportional loads ``scale`` = ``"percent"`` (default) or ``"watts"``.
    """

    def __init__(self, bus: MqttBus, devices: dict[str, Device], options: dict[str, dict]) -> None:
        self._bus, self._devices, self._options = bus, devices, options

    async def apply(self, device_id: str, power_w: float) -> None:
        dev, opt = self._devices[device_id], self._options[device_id]
        if dev.kind is DeviceKind.ON_OFF:
            payload = opt.get("payload_on", "ON") if power_w > 0 else opt.get("payload_off", "OFF")
        elif opt.get("scale", "percent") == "watts":
            payload = f"{power_w:.0f}"
        else:
            payload = f"{power_w / dev.power_w * 100:.1f}"
        self._bus.publish(opt["topic"], payload, retain=opt.get("retain", False))


class HttpActuator:
    """Calls a URL template; ``{power_w}``, ``{percent}`` and ``{state}`` (on/off) are substituted."""

    def __init__(self, devices: dict[str, Device], options: dict[str, dict], timeout_s: float = 5.0) -> None:
        self._devices, self._options, self._timeout_s = devices, options, timeout_s

    async def apply(self, device_id: str, power_w: float) -> None:
        dev, opt = self._devices[device_id], self._options[device_id]
        url = opt["url"].format(
            power_w=f"{power_w:.0f}",
            percent=f"{power_w / dev.power_w * 100:.1f}",
            state="on" if power_w > 0 else "off",
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
