"""Standalone runtime against a SIMULATED Victron GX device (Venus OS MQTT) on a real MQTT broker.

The simulation follows Victron's published documentation (dbus-flashmq README, Venus OS D-Bus list):
values are published as {"value": X} on N/<id>/..., only while a keep-alive was received on R/<id>/keepalive
(Victron's timeout is 60 s; shortened here), and commands are written on W/<id>/... as {"value": X}.
It is NOT a real Victron device. The sign of the grid power (negative = export) is an assumption of this
simulation, matching the example configuration (invert = true).
"""

import asyncio
import json
import os
import signal
import threading
import time

import paho.mqtt.client as mqtt

from fakes import wait_for
from solarprio.runtime.app import run

PID = "c0ffee123456"
EVCS = "40"
KEEPALIVE_TIMEOUT_S = 3.0  # Victron: 60 s
SURPLUS_W = 2500.0  # solar production minus the house consumption, before any routing
V = 230.0


class FakeVenus:
    def __init__(self, port):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fake-venus")
        self.client.on_message = self._on_message
        self.client.connect("127.0.0.1", port)
        self.client.subscribe([(f"R/{PID}/#", 0), (f"W/{PID}/#", 0)])
        self.client.loop_start()
        self.alive_until = 0.0
        self.keepalives: list[str] = []
        self.set_current, self.start, self.plugged = 0.0, 0, True
        self.stop = threading.Event()
        self.published_values = 0
        threading.Thread(target=self._publisher, daemon=True).start()

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode()
        if msg.topic == f"R/{PID}/keepalive":
            self.keepalives.append(payload)
            self.alive_until = time.monotonic() + KEEPALIVE_TIMEOUT_S
            if payload == "":
                self._publish_all()  # full republish on a plain keep-alive
        elif msg.topic == f"W/{PID}/evcharger/{EVCS}/SetCurrent":
            self.set_current = float(json.loads(payload)["value"])
        elif msg.topic == f"W/{PID}/evcharger/{EVCS}/StartStop":
            self.start = int(json.loads(payload)["value"])

    @property
    def ev_power(self) -> float:
        return self.set_current * V if (self.start == 1 and self.plugged) else 0.0

    def _status(self) -> int:
        if not self.plugged:
            return 0  # Disconnected
        return 2 if self.ev_power > 0 else 1  # Charging / Connected

    def _publish_all(self):
        grid_total = -SURPLUS_W + self.ev_power  # negative = exporting (assumption of this simulation)
        topics = {f"system/0/Ac/Grid/L{i}/Power": grid_total / 3 for i in (1, 2, 3)}
        topics[f"evcharger/{EVCS}/Status"] = self._status()
        topics[f"evcharger/{EVCS}/Ac/Power"] = self.ev_power
        for path, value in topics.items():
            self.client.publish(f"N/{PID}/{path}", json.dumps({"value": value}))  # not retained, like dbus-flashmq
            self.published_values += 1

    def _publisher(self):
        while not self.stop.is_set():
            if time.monotonic() < self.alive_until:  # silent once the keep-alive has expired
                self._publish_all()
            time.sleep(0.2)


def test_runtime_against_a_simulated_victron_gx(broker_port, tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(f"""
[runtime]
interval_s = 0.2
stale_after_s = 5

[mqtt]
host = "127.0.0.1"
port = {broker_port}
client_id = "solarprio-victron-test"
keepalive_topic = "R/{PID}/keepalive"
keepalive_interval_s = 1

[source]
mode = "export"
export_topic = ["N/{PID}/system/0/Ac/Grid/L1/Power", "N/{PID}/system/0/Ac/Grid/L2/Power", "N/{PID}/system/0/Ac/Grid/L3/Power"]
field = "value"
invert = true

[[device]]
id = "evcs"
name = "EVCS"
priority = 1
kind = "ev_charger"
phases = 1
min_current_a = 6
max_current_a = 16
  [device.actuator]
  type = "mqtt"
  topic = "W/{PID}/evcharger/{EVCS}/SetCurrent"
  payload_template = '{{"value": {{value}}}}'
  switch_topic = "W/{PID}/evcharger/{EVCS}/StartStop"
  payload_on = '{{"value": 1}}'
  payload_off = '{{"value": 0}}'
  [device.readings]
  field = "value"
  connected_topic = "N/{PID}/evcharger/{EVCS}/Status"
  disconnected_values = ["0"]
  connected_values = ["1", "2", "3", "4"]
  measured_topic = "N/{PID}/evcharger/{EVCS}/Ac/Power"
""")
    venus = FakeVenus(broker_port)

    async def scenario():
        task = asyncio.create_task(run(str(config)))
        try:
            loop = asyncio.get_running_loop()

            async def until(predicate, what, timeout=12.0):
                end = time.monotonic() + timeout
                while time.monotonic() < end:
                    if predicate():
                        return
                    await asyncio.sleep(0.1)
                raise AssertionError(f"timeout waiting for: {what}; keepalives={venus.keepalives}, "
                                     f"set_current={venus.set_current}, start={venus.start}")

            # 2500 W surplus: floor(2500 / 230) = 10 A, charger started
            await until(lambda: venus.start == 1 and venus.set_current == 10.0, "10 A and StartStop=1")
            # the car is unplugged (status 0): the charge is stopped
            venus.plugged = False
            await until(lambda: venus.start == 0, "StartStop=0 when disconnected")
            venus.plugged = True
            await until(lambda: venus.start == 1 and venus.set_current == 10.0, "charging again")
            # the simulated GX stops publishing 3 s after the last keep-alive: the runtime must have kept it alive
            await asyncio.sleep(KEEPALIVE_TIMEOUT_S + 1.5)
            assert time.monotonic() < venus.alive_until, "keep-alive was not sent often enough: Venus went silent"
            # still routing after the keep-alive window. Wait for the steady value instead of sampling one instant:
            # the three phases and the measured power arrive as separate messages, so a single reading can mix old and
            # new values (a one-cycle transient that the next cycle corrects).
            await until(lambda: venus.start == 1 and venus.set_current == 10.0, "still 10 A after the keep-alive window", timeout=5.0)
        finally:
            os.kill(os.getpid(), signal.SIGTERM)  # same path as `docker stop`
            await asyncio.wait_for(task, 10)

    try:
        asyncio.run(scenario())
        assert wait_for(lambda: venus.start == 0), "the charger must be stopped on shutdown"
        # first keep-alive empty (full publish), the following ones suppress the republish
        assert venus.keepalives[0] == ""
        assert len(venus.keepalives) >= 4
        assert all(json.loads(p) == {"keepalive-options": ["suppress-republish"]} for p in venus.keepalives[1:])
    finally:
        venus.stop.set()
        venus.client.loop_stop()
