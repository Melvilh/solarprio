"""Helpers shared by the end-to-end scenarios (talk to the real Home Assistant started by scripts/e2e_ha.sh)."""
import json
import threading
import time
import urllib.request

BASE = "http://127.0.0.1:8123"
AUTH = json.load(open("auth.json"))
TOKEN = AUTH["token"]


def api(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def state(entity):
    return api("GET", f"/api/states/{entity}")["state"]


def num(entity):
    return float(state(entity))


def set_state(domain, entity, value=None, on=None):
    if on is not None:
        api("POST", f"/api/services/{domain}/turn_{'on' if on else 'off'}", {"entity_id": entity})
    else:
        api("POST", f"/api/services/{domain}/set_value", {"entity_id": entity, "value": value})


def wait(pred, timeout=25, what=""):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            if pred():
                return
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(0.3)
    raise AssertionError(f"timeout waiting for: {what}" + (f" (last error: {last})" if last else ""))


def start_meter(compute_routed, surplus, stop):
    """Simulated grid meter: export = surplus - what the routed devices really draw."""
    def loop():
        while not stop.is_set():
            try:
                set_state("input_number", "input_number.grid", surplus() - compute_routed())
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
    threading.Thread(target=loop, daemon=True).start()


def browser_tokens():
    return {"access_token": TOKEN, "token_type": "Bearer", "expires_in": 1800, "hassUrl": BASE, "clientId": BASE + "/",
            "expires": int(time.time() * 1000) + 1_700_000, "refresh_token": AUTH["refresh_token"]}


def wait_no_view_transition(page, timeout=10):
    """Home Assistant runs a View Transition after load; presses during it are lost (HA behaviour)."""
    wait(lambda: page.evaluate("document.getAnimations({subtree: true}).filter(a => ((a.effect && a.effect.pseudoElement) || '').startsWith('::view-transition')).length === 0"),
         timeout, "Home Assistant view transition to finish")
