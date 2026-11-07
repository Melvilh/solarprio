"""examples/task-go-poll.sh against a fake Home Assistant: once a day, on "go", with a fallback, nothing on errors."""
import json
import os
import subprocess
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "examples" / "task-go-poll.sh"


class FakeHA:
    def __init__(self):
        self.state, self.requests = "off", []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append((self.path, self.headers.get("Authorization")))
                body = json.dumps({"entity_id": "input_boolean.go", "state": outer.state, "attributes": {}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def ha():
    fake = FakeHA()
    yield fake
    fake.close()


def run(tmp_path, url, command=None, fallback=None, expect=0):
    marker = tmp_path / "ran"
    env = {**os.environ, "HA_URL": url, "HA_TOKEN": "secret-token", "GO_ENTITY": "input_boolean.go",
           "COMMAND": command or f"echo x >> {marker}", "STATE_DIR": str(tmp_path / "state")}
    env.pop("FALLBACK_AFTER", None)
    if fallback:
        env["FALLBACK_AFTER"] = fallback
    proc = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == expect, proc.stderr
    return marker.read_text().count("x") if marker.exists() else 0


def test_it_runs_the_command_once_a_day_when_the_signal_is_on(ha, tmp_path):
    ha.state = "on"
    assert run(tmp_path, ha.url) == 1
    assert run(tmp_path, ha.url) == 1  # still "go" but already done today
    assert ha.requests[0] == ("/api/states/input_boolean.go", "Bearer secret-token")


def test_it_does_nothing_while_the_signal_is_off(ha, tmp_path):
    assert run(tmp_path, ha.url) == 0
    ha.state = "on"
    assert run(tmp_path, ha.url) == 1


def test_the_fallback_runs_the_task_when_no_go_came(ha, tmp_path):
    assert run(tmp_path, ha.url, fallback="00:00") == 1  # any time of the day is after 00:00
    if datetime.now().strftime("%H%M") < "2359":  # skip the one minute before midnight
        other = tmp_path / "other"
        other.mkdir()
        assert run(other, ha.url, fallback="23:59") == 0  # not yet


def test_unreachable_home_assistant_runs_nothing_before_the_fallback(tmp_path):
    assert run(tmp_path, "http://127.0.0.1:1") == 0
    assert run(tmp_path, "http://127.0.0.1:1", fallback="00:00") == 1


def test_a_failing_command_is_retried_the_next_time(ha, tmp_path):
    ha.state = "on"
    marker = tmp_path / "attempts"
    failing = f"echo x >> {marker}; exit 1"
    run(tmp_path, ha.url, command=failing, expect=1)  # the failure is reported to cron through the exit status
    run(tmp_path, ha.url, command=failing, expect=1)
    assert marker.read_text().count("x") == 2  # no "done today" flag after a failure
    run(tmp_path, ha.url, command=f"echo x >> {marker}")
    run(tmp_path, ha.url, command=f"echo x >> {marker}")
    assert marker.read_text().count("x") == 3  # succeeded once, then done for the day


def test_it_refuses_to_run_without_its_settings(tmp_path):
    proc = subprocess.run(["sh", str(SCRIPT)], env={"PATH": os.environ["PATH"]}, capture_output=True, text=True)
    assert proc.returncode != 0 and "HA_URL" in proc.stderr
