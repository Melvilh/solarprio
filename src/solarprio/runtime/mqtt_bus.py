"""Thin MQTT wrapper (paho-mqtt 2.x): caches the latest value of subscribed topics."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

import paho.mqtt.client as mqtt

from .config import MqttConfig

log = logging.getLogger(__name__)


def parse_number(payload: bytes | str, field: str | None = None) -> float:
    """Parse a plain number or a JSON document (``field`` may be dotted: ``a.b``)."""
    text = payload.decode() if isinstance(payload, bytes) else payload
    if field:
        value = json.loads(text)
        for part in field.split("."):
            value = value[part]
        return float(value)
    return float(text)


def _is_done(info: mqtt.MQTTMessageInfo) -> bool:
    try:
        return info.is_published()
    except RuntimeError:
        return True  # failed publishes are not worth tracking


class MqttBus:
    def __init__(self, cfg: MqttConfig, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._latest: dict[str, tuple[bytes, float]] = {}
        self._topics: set[str] = set()
        self._pending: list[mqtt.MQTTMessageInfo] = []
        self._connected = threading.Event()
        self.connections = 0  # incremented on every (re)connection, so callers can detect a reconnect
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg.client_id)
        if cfg.username:
            self._client.username_pw_set(cfg.username, cfg.password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._cfg = cfg

    def subscribe(self, topic: str) -> None:
        self._topics.add(topic)

    def start(self, timeout: float = 10.0) -> None:
        self._client.connect_async(self._cfg.host, self._cfg.port)
        self._client.loop_start()
        if not self._connected.wait(timeout):
            log.warning("MQTT broker not reachable yet at %s:%s, will keep retrying", self._cfg.host, self._cfg.port)

    def stop(self, flush_timeout: float = 3.0) -> None:
        """Disconnect after giving in-flight publishes (e.g. shutdown commands) time to be acknowledged."""
        deadline = time.monotonic() + flush_timeout
        for info in self._pending:
            try:
                if not info.is_published():
                    info.wait_for_publish(timeout=max(deadline - time.monotonic(), 0))
            except (ValueError, RuntimeError):
                pass  # the broker was never reachable for this message: nothing more to wait for
        self._client.disconnect()
        self._client.loop_stop()

    def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        """Publish a message; raises ``ConnectionError`` when it cannot be handed to the broker connection.

        The caller (the controller) then knows the command was NOT sent and retries on the next cycle,
        instead of believing a load was switched.
        """
        info = self._client.publish(topic, payload, qos=1, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"could not publish to {topic}: {mqtt.error_string(info.rc)}")
        self._pending = [i for i in self._pending if not _is_done(i)] + [info]

    def latest(self, topic: str) -> tuple[bytes, float] | None:
        """Return ``(payload, age_seconds)`` or None if nothing was received yet."""
        with self._lock:
            item = self._latest.get(topic)
        if item is None:
            return None
        payload, ts = item
        return payload, self._clock() - ts

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code != 0:
            log.error("MQTT connection refused: %s", reason_code)
            return
        self.connections += 1
        self._connected.set()
        for topic in self._topics:  # also re-subscribes after a reconnect
            client.subscribe(topic)

    def _on_message(self, client, userdata, msg) -> None:
        with self._lock:
            self._latest[msg.topic] = (bytes(msg.payload), self._clock())
