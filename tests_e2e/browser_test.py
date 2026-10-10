import json, threading, time, urllib.request
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8123"
cfg = json.load(open("auth.json"))
TOKEN = cfg["token"]
SURPLUS = 1000  # W of solar surplus before any routing


def api(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def state(entity):
    return api("GET", f"/api/states/{entity}")["state"]


def wait(pred, timeout=20, what=""):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if pred():
                return
        except Exception:
            pass
        time.sleep(0.3)
    raise AssertionError(f"timeout waiting for: {what}")


# Simulated meter: grid export = surplus - what the routed devices really consume.
stop_meter = threading.Event()


def meter():
    while not stop_meter.is_set():
        try:
            routed = float(state("input_number.dimmer")) / 100 * 2000
            routed += 800 if state("input_boolean.pump") == "on" else 0
            routed += 300 if state("input_boolean.server") == "on" else 0
            api("POST", "/api/services/input_number/set_value", {"entity_id": "input_number.grid", "value": SURPLUS - routed})
        except Exception:
            pass
        time.sleep(0.5)


threading.Thread(target=meter, daemon=True).start()
tokens = {"access_token": TOKEN, "token_type": "Bearer", "expires_in": 1800, "hassUrl": BASE, "clientId": BASE + "/",
          "expires": int(time.time() * 1000) + 1_700_000, "refresh_token": cfg["refresh_token"]}

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 1100, "height": 800}, locale="fr-FR")
    ctx.add_init_script(f"localStorage.setItem('hassTokens', JSON.stringify({json.dumps(tokens)}));")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/solarprio")
    rows = page.locator("solarprio-panel li.row")
    wait(lambda: rows.count() == 3, 30, "3 device rows in the panel")

    # reset to a known state with the same websocket API the panel uses
    page.evaluate("""async () => {
      const hass = document.querySelector('home-assistant').hass;
      await hass.callWS({type: 'solarprio/reorder', ids: ['chauffe_eau_variateur', 'pompe_piscine', 'serveur_de_calcul']});
      for (const id of ['chauffe_eau_variateur', 'pompe_piscine', 'serveur_de_calcul'])
        await hass.callWS({type: 'solarprio/set_device_enabled', device_id: id, enabled: true});
      await hass.callWS({type: 'solarprio/set_routing', enabled: true});
    }""")
    wait(lambda: state("input_number.dimmer") == "50.0" and state("input_boolean.pump") == "off" and state("input_boolean.server") == "off",
         what="steady state before the drag: dimmer 50 %, pump and server off")
    print("before drag: dimmer", state("input_number.dimmer"), "pump", state("input_boolean.pump"), "server", state("input_boolean.server"))
    page.reload()
    wait(lambda: rows.count() == 3, 30, "rows after reset")

    def order():
        return page.locator("solarprio-panel li.row .name").all_inner_texts()

    print("initial order:", order())
    assert order() == ["Chauffe-eau (variateur)", "Pompe piscine", "Serveur de calcul"]
    page.screenshot(path="panel_before.png")

    # real mouse drag: grab the handle of row 2 and drop it above row 1
    h2 = page.locator("solarprio-panel li.row:nth-child(2) .handle")
    # Home Assistant runs a View Transition after load/navigation; while it is active, every press goes to
    # <html> and is lost (a Home Assistant behaviour, not the panel). Wait for it to end before pressing.
    wait(lambda: page.evaluate("document.getAnimations({subtree: true}).filter(a => ((a.effect && a.effect.pseudoElement) || '').startsWith('::view-transition')).length === 0"),
         10, "Home Assistant view transition to finish")
    r1 = page.locator("solarprio-panel li.row:nth-child(1)").bounding_box()
    b = h2.bounding_box()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    page.mouse.down()
    page.mouse.move(b["x"] + 5, b["y"] - 20, steps=5)
    page.mouse.move(b["x"] + 5, r1["y"] + 5, steps=10)
    page.screenshot(path="panel_dragging.png")
    page.mouse.up()

    try:
        wait(lambda: order() == ["Pompe piscine", "Chauffe-eau (variateur)", "Serveur de calcul"], 5, "UI order after drop")
    except AssertionError:
        page.screenshot(path="panel_drop_failed.png")
        print("order at failure:", order())
        raise
    print("order after drop:", order())
    # the devices follow: pump (800 W) now first, dimmer gets the remaining 200 W = 10 %
    wait(lambda: state("input_boolean.pump") == "on", what="pump on after becoming priority 1")
    wait(lambda: state("input_number.dimmer") == "10.0", what="dimmer at 10 % (200 W left)")
    print("after reorder -> pump:", state("input_boolean.pump"), "dimmer:", state("input_number.dimmer"), "server:", state("input_boolean.server"))
    page.wait_for_timeout(3500)  # let the panel poll
    page.screenshot(path="panel_after.png")

    page.reload()
    wait(lambda: rows.count() == 3, 30, "rows after reload")
    assert order() == ["Pompe piscine", "Chauffe-eau (variateur)", "Serveur de calcul"], order()
    print("order persisted after reload:", order())

    # arrow-button path
    page.locator("solarprio-panel li.row:nth-child(3) button.up").click()
    wait(lambda: order()[1] == "Serveur de calcul", 5, "arrow move")
    print("after arrow click:", order())

    # per-device enable switch (row 1 = pump)
    page.locator("solarprio-panel li.row:nth-child(1) label.switch").click()
    wait(lambda: state("input_boolean.pump") == "off", what="pump off after disabling it in the panel")
    print("pump after disabling in panel:", state("input_boolean.pump"))

    # master routing switch
    page.locator("solarprio-panel #routing").click()
    wait(lambda: state("sensor.solarprio_status") == "disabled", what="routing disabled")
    wait(lambda: state("input_number.dimmer") == "0.0" and state("input_boolean.server") == "off", what="all loads off")
    print("routing off -> dimmer:", state("input_number.dimmer"), "server:", state("input_boolean.server"))
    page.wait_for_timeout(3500)
    page.screenshot(path="panel_routing_off.png")

    page.set_viewport_size({"width": 390, "height": 800})
    page.wait_for_timeout(500)
    page.screenshot(path="panel_mobile.png")
    print("page errors:", errors)
    browser.close()
stop_meter.set()
print("E2E OK")
