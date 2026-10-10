"""Shared fixtures."""

import asyncio
import socket
import threading

import pytest


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def broker_port():
    from amqtt.broker import Broker

    port = free_port()
    ready, stop = threading.Event(), threading.Event()
    errors: list[Exception] = []

    def serve():
        async def main():
            broker = Broker({
                "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
                "sys_interval": 0,
                "auth": {"allow-anonymous": True, "plugins": ["auth_anonymous"]},
                "topic-check": {"enabled": False},
            })
            await broker.start()
            ready.set()
            while not stop.is_set():
                await asyncio.sleep(0.05)
            await broker.shutdown()

        try:
            asyncio.run(main())
        except Exception as e:  # noqa: BLE001
            errors.append(e)
            ready.set()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    assert ready.wait(10)
    if errors:
        pytest.skip(f"test broker could not start: {errors[0]!r}")
    yield port
    stop.set()
    t.join(5)
