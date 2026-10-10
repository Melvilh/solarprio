"""Create the owner user and a solarprio entry with 3 devices on a fresh real HA instance. Prints the auth JSON."""
import json, sys, urllib.request

BASE = "http://127.0.0.1:8123"
CLIENT = BASE + "/"


def call(method, path, body=None, token=None, form=False):
    data = None
    headers = {}
    if body is not None:
        if form:
            from urllib.parse import urlencode
            data = urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


user = call("POST", "/api/onboarding/users", {"client_id": CLIENT, "name": "Owner", "username": "owner", "password": "test-pass-123", "language": "fr"})
tokens = call("POST", "/auth/token", {"grant_type": "authorization_code", "code": user["auth_code"], "client_id": CLIENT}, form=True)
token = tokens["access_token"]
for step in ("core_config", "analytics", "integration"):
    try:
        body = {"client_id": CLIENT, "redirect_uri": CLIENT} if step == "integration" else {}
        call("POST", f"/api/onboarding/{step}", body, token)
    except Exception as e:
        print("onboarding", step, e, file=sys.stderr)

flow = call("POST", "/api/config/config_entries/flow", {"handler": "solarprio", "show_advanced_options": False}, token)
flow = call("POST", f"/api/config/config_entries/flow/{flow['flow_id']}", {"mode": "export"}, token)
flow = call("POST", f"/api/config/config_entries/flow/{flow['flow_id']}",
            {"export_entity": "sensor.grid_power", "invert": False, "interval_s": 2, "stale_after_s": 3600, "on_stale": "off"}, token)
entry_id = flow["result"]["entry_id"]

SCENARIOS = {
    "basic": [
        ("on_off_proportional", {"name": "Chauffe-eau (variateur)", "entity_id": "input_number.dimmer", "priority": 1, "power_w": 2000,
                                  "min_power_w": 100, "scale": "percent", "min_on_s": 0, "min_off_s": 0}, "proportional"),
        ("pump", {"name": "Pompe piscine", "entity_id": "input_boolean.pump", "priority": 2, "power_w": 800,
                  "min_on_s": 0, "min_off_s": 0, "start_margin_w": 0, "stay_tolerance_w": 0}, "on_off"),
        ("server", {"name": "Serveur de calcul", "entity_id": "input_boolean.server", "priority": 3, "power_w": 300,
                    "min_on_s": 0, "min_off_s": 0, "start_margin_w": 0, "stay_tolerance_w": 0}, "on_off"),
    ],
    "ev": [
        ("battery", {"name": "Batterie maison", "entity_id": "input_number.bat_charge", "priority": 1, "power_w": 3000, "min_power_w": 200,
                     "scale": "watts", "soc_entity": "input_number.bat_soc", "soc_max": 90, "soc_resume_margin": 3,
                     "min_on_s": 0, "min_off_s": 0}, "battery"),
        ("ev", {"name": "Borne de recharge", "entity_id": "input_number.ev_current", "switch_entity": "input_boolean.ev_switch", "priority": 2,
                "phases": "1", "voltage_v": 230, "min_current_a": 6, "max_current_a": 16, "current_step_a": 1,
                "connected_entity": "input_boolean.car_plugged", "soc_entity": "input_number.car_soc", "soc_max": 80,
                "min_on_s": 0, "min_off_s": 0, "start_margin_w": 0, "stay_tolerance_w": 0}, "ev_charger"),
        ("pump", {"name": "Pompe piscine", "entity_id": "input_boolean.pump", "priority": 3, "power_w": 800,
                  "min_on_s": 0, "min_off_s": 0, "start_margin_w": 0, "stay_tolerance_w": 0}, "on_off"),
    ],
}
scenario = sys.argv[1] if len(sys.argv) > 1 else "basic"
for _, form, kind in SCENARIOS[scenario]:
    f = call("POST", "/api/config/config_entries/options/flow", {"handler": entry_id}, token)
    f = call("POST", f"/api/config/config_entries/options/flow/{f['flow_id']}", {"next_step_id": "add_device"}, token)
    f = call("POST", f"/api/config/config_entries/options/flow/{f['flow_id']}", {"kind": kind}, token)
    assert f["step_id"] == "device_details", f
    f = call("POST", f"/api/config/config_entries/options/flow/{f['flow_id']}", form, token)
    assert f["type"] == "create_entry", f
print(json.dumps({"token": token, "refresh_token": tokens["refresh_token"], "entry_id": entry_id}))
