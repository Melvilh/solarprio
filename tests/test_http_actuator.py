import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from solarprio import Device, DeviceKind
from solarprio.runtime.adapters import HttpActuator


def test_http_actuator_substitutes_placeholders_and_uses_method():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    dev = Device(id="x", name="X", priority=1, kind=DeviceKind.PROPORTIONAL, power_w=2000)
    act = HttpActuator({"x": dev}, {"x": {"url": base + "/set?w={power_w}&p={percent}&s={state}", "method": "POST"}})
    try:
        asyncio.run(act.apply("x", 500))
        asyncio.run(act.apply("x", 0))
    finally:
        server.shutdown()
    assert seen == ["/set?w=500&p=25.0&s=on", "/set?w=0&p=0.0&s=off"]
