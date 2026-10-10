"""Periodic keep-alive for brokers that only publish while somebody asks (Victron Venus OS).

Venus OS (dbus-flashmq) publishes values only after a read request on ``R/<portal ID>/keepalive`` and stops
after 60 s without one. The first request (and the first after a reconnection) is empty so every topic is
republished; later ones carry ``{"keepalive-options": ["suppress-republish"]}`` to avoid resending everything.
"""

from __future__ import annotations

import asyncio
import logging

from .mqtt_bus import MqttBus

log = logging.getLogger(__name__)

RETRY_S = 2.0  # while the broker is unreachable, try again soon instead of waiting a whole interval


async def keepalive_loop(bus: MqttBus, topic: str, interval_s: float, later_payload: str, stop: asyncio.Event) -> None:
    seen_connections = -1
    while not stop.is_set():
        wait_s = interval_s
        try:
            connections = bus.connections
            if connections != seen_connections:
                bus.publish(topic, "")  # full republish: first request, or the connection was re-established
                seen_connections = connections
            else:
                bus.publish(topic, later_payload)
        except ConnectionError as e:
            log.warning("keep-alive not sent (%s), retrying", e)
            wait_s = min(RETRY_S, interval_s)
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait_s)
        except asyncio.TimeoutError:
            pass
