"""Control loop tying source, engine and actuators together."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from ..engine import Engine
from ..ports import DeviceActuator, PowerSource
from .adapters import MeasurementUnavailable
from .config import RuntimeConfig

log = logging.getLogger(__name__)


class Controller:
    def __init__(
        self,
        engine: Engine,
        source: PowerSource,
        actuator: DeviceActuator,
        cfg: RuntimeConfig,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._engine, self._source, self._actuator, self._cfg, self._clock = engine, source, actuator, cfg, clock
        self._sent: dict[str, tuple[float, float]] = {}  # device -> (power_w, sent_at)

    async def tick(self) -> dict[str, float]:
        """Run one control cycle and return the commands decided."""
        now = self._clock()
        try:
            available = await self._source.read_available_w(self._engine.routed_w)
        except MeasurementUnavailable as e:
            return await self._on_measurement_lost(e, now)

        commands = self._engine.step(available, now)
        log.debug("available=%.0fW commands=%s", available, commands)
        await self._send(commands, now)
        return commands

    async def _on_measurement_lost(self, err: Exception, now: float) -> dict[str, float]:
        if self._cfg.on_stale == "hold":
            log.warning("measurement unavailable (%s): holding current state", err)
            return {i: self._engine.state(i).power_w for i in self._sent}
        log.warning("measurement unavailable (%s): switching all loads off", err)
        # step(0) still honors min on/off timers, like any other cycle
        commands = self._engine.step(0.0, now)
        await self._send(commands, now)
        return commands

    async def _send(self, commands: dict[str, float], now: float) -> None:
        """Send changed (or expired) commands concurrently: a slow device must not delay the others."""
        pending = []
        for device_id, power in commands.items():
            previous = self._sent.get(device_id)
            changed = previous is None or previous[0] != power
            expired = previous is not None and now - previous[1] >= self._cfg.resend_every_s
            if changed or expired:
                pending.append((device_id, power))

        results = await asyncio.gather(*(self._actuator.apply(i, p) for i, p in pending), return_exceptions=True)
        for (device_id, power), result in zip(pending, results):
            if isinstance(result, Exception):
                log.error("failed to apply %.0fW to %s: %r", power, device_id, result)
                continue  # not recorded as sent, so it is retried next cycle
            self._sent[device_id] = (power, now)

    async def run(self, stop: asyncio.Event) -> list[str]:
        while not stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._cfg.interval_s)
            except asyncio.TimeoutError:
                pass
        return await self.shutdown()

    async def shutdown(self) -> list[str]:
        """Switch every load off. Ignores min on/off timers: the process is stopping.

        Returns the ids of devices that could not be switched off.
        """
        ids = list(self._sent)
        results = await asyncio.gather(*(self._actuator.apply(i, 0.0) for i in ids), return_exceptions=True)
        failed = [i for i, r in zip(ids, results) if isinstance(r, Exception)]
        for i in failed:
            log.error("could not switch off %s on shutdown", i)
        return failed
