"""Scenario: battery (priority 1), EV charger (2), pump (3) on a real Home Assistant, observed in the real panel."""
import json
import threading

from common import api, browser_tokens, num, set_state, state, start_meter, wait, wait_no_view_transition
from playwright.sync_api import sync_playwright

SURPLUS = 5000.0
EV_V = 230.0


def routed():
    total = num("input_number.bat_charge")
    if state("input_boolean.ev_switch") == "on" and state("input_boolean.car_plugged") == "on":
        total += num("input_number.ev_current") * EV_V
    if state("input_boolean.pump") == "on":
        total += 800
    return total


stop = threading.Event()
start_meter(routed, lambda: SURPLUS, stop)

# known starting state
set_state("input_number", "input_number.bat_soc", 50)
set_state("input_number", "input_number.car_soc", 30)
set_state("input_boolean", "input_boolean.car_plugged", on=True)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 1100, "height": 800}, locale="en-US")
    ctx.add_init_script(f"localStorage.setItem('hassTokens', JSON.stringify({json.dumps(browser_tokens())}));")
    page = ctx.new_page()
    page.goto("http://127.0.0.1:8123/solarprio")
    rows = page.locator("solarprio-panel li.row")
    wait(lambda: rows.count() == 3, 30, "3 device rows")
    wait_no_view_transition(page)

    # a. 5000 W surplus: battery 3000 W, the car gets the remaining 2000 W = 8 A (floor), the pump (800 W) does not fit
    wait(lambda: num("input_number.bat_charge") == 3000 and num("input_number.ev_current") == 8
         and state("input_boolean.ev_switch") == "on" and state("input_boolean.pump") == "off",
         what="battery 3000 W, EV 8 A, pump off")
    print("a. battery", state("input_number.bat_charge"), "W | EV", state("input_number.ev_current"), "A switch", state("input_boolean.ev_switch"), "| pump", state("input_boolean.pump"))
    wait(lambda: "8 A" in page.locator("solarprio-panel li.row:nth-child(2) .sub").inner_text(), what="panel shows 8 A")
    wait(lambda: "SoC 50 %" in page.locator("solarprio-panel li.row:nth-child(1) .sub").inner_text(), what="panel shows battery SoC")
    page.screenshot(path="panel_ev_a.png")

    # the day-to-day switches of a device are in its row, and they are the same as its entities: the car has a forced run
    def forced_entities():
        return [x["state"] for x in api("GET", "/api/states") if x["entity_id"].startswith("switch.") and "forced_run" in x["entity_id"] and "borne" in x["entity_id"]]

    forced = page.locator('solarprio-panel li.row:nth-child(2) ha-switch.ctl[data-control="forced_run"]')
    assert forced.count() == 1, "the EV charger row has a forced run switch"
    assert page.locator('solarprio-panel li.row:nth-child(3) ha-switch.ctl').count() == 0, "a plain pump has none"
    assert forced_entities() == ["off"]
    forced.click()
    wait(lambda: forced_entities() == ["on"], what="the forced run entity follows the panel")
    forced.click()
    wait(lambda: forced_entities() == ["off"], what="and goes back")
    print("a2. forced run switch of the car works from the panel")

    # b. unplug the car: it stops, the surplus it freed goes to the pump
    set_state("input_boolean", "input_boolean.car_plugged", on=False)
    wait(lambda: state("input_boolean.ev_switch") == "off" and state("input_boolean.pump") == "on", what="car off, pump on")
    wait(lambda: "unplugged" in page.locator("solarprio-panel li.row:nth-child(2) .sub").inner_text(), what="panel shows unplugged")
    print("b. unplugged -> EV switch", state("input_boolean.ev_switch"), "| pump", state("input_boolean.pump"))

    # c. battery reaches its 90 % limit and stops; re-plug: the car gets everything left (5000 - 800 pump = 4200 W -> capped at 16 A)
    set_state("input_number", "input_number.bat_soc", 95)
    set_state("input_boolean", "input_boolean.car_plugged", on=True)
    wait(lambda: num("input_number.bat_charge") == 0 and num("input_number.ev_current") == 16 and state("input_boolean.ev_switch") == "on",
         what="battery stopped at SoC limit, EV at 16 A")
    print("c. battery", state("input_number.bat_charge"), "W | EV", state("input_number.ev_current"), "A | pump", state("input_boolean.pump"))
    wait(lambda: "16 A" in page.locator("solarprio-panel li.row:nth-child(2) .sub").inner_text(), what="panel shows 16 A")
    page.screenshot(path="panel_ev_c.png")

    # d. SoC falls back under the hysteresis threshold (90 - 3): the battery charges again and the car gets less
    set_state("input_number", "input_number.bat_soc", 86)
    wait(lambda: num("input_number.bat_charge") == 3000 and num("input_number.ev_current") == 8, what="battery resumes, EV back to 8 A")
    print("d. battery resumed:", state("input_number.bat_charge"), "W | EV", state("input_number.ev_current"), "A")

    # e. routing switch off: everything stops (battery setpoint 0, charger off)
    page.locator("solarprio-panel #routing").click()
    wait(lambda: num("input_number.bat_charge") == 0 and state("input_boolean.ev_switch") == "off" and state("input_boolean.pump") == "off",
         what="all off")
    print("e. routing off -> battery", state("input_number.bat_charge"), "| EV switch", state("input_boolean.ev_switch"), "| pump", state("input_boolean.pump"))
    browser.close()
stop.set()
print("E2E EV OK")
