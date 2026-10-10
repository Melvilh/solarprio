"""Entry point of the standalone runtime: ``python -m solarprio --config config.toml``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from ..engine import Engine
from .adapters import DispatchActuator, MqttPowerSource, MqttReadings
from .config import ConfigError, load_config
from .controller import Controller
from .mqtt_bus import MqttBus

log = logging.getLogger("solarprio")


async def run(config_path: str) -> list[str]:
    cfg = load_config(config_path)
    bus = MqttBus(cfg.mqtt)
    source = MqttPowerSource(bus, cfg.source, cfg.runtime.stale_after_s)
    actuator = DispatchActuator(bus, cfg.devices, cfg.actuators)
    readings = MqttReadings(bus, cfg.readings, cfg.runtime.stale_after_s)
    controller = Controller(Engine(cfg.devices), source, actuator, cfg.runtime, readings=readings)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    bus.start()
    log.info("started with %d device(s), interval %ss", len(cfg.devices), cfg.runtime.interval_s)
    try:
        failed = await controller.run(stop)
    finally:
        bus.stop()
    if failed:
        log.error("stopped, but these loads may still be on: %s", ", ".join(failed))
    else:
        log.info("stopped, all loads switched off")
    return failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="solarprio")
    parser.add_argument("--config", required=True, help="path to the TOML configuration")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        failed = asyncio.run(run(args.config))
    except (ConfigError, OSError) as e:
        print(f"configuration error: {e}", file=sys.stderr)
        return 2
    return 1 if failed else 0  # non-zero tells a supervisor that some loads may still be on
