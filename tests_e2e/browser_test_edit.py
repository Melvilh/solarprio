"""Real Home Assistant + real Chromium: add, edit, configure and delete from the sidebar panel."""
import json

from common import api, browser_tokens, state, wait, wait_no_view_transition
from playwright.sync_api import sync_playwright

NEW = "Serveur 2"

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 1100, "height": 900}, locale="fr-FR")
    ctx.add_init_script(f"localStorage.setItem('hassTokens', JSON.stringify({json.dumps(browser_tokens())}));")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8123/solarprio")
    rows = page.locator("solarprio-panel li.row")
    wait(lambda: rows.count() == 3, 30, "3 device rows")
    wait_no_view_transition(page)

    def names():
        return page.locator("solarprio-panel li.row .name").all_inner_texts()

    def ws(msg):
        return page.evaluate("async (m) => document.querySelector('home-assistant').hass.callWS(m)", msg)

    # ---- add: choose the type, then the form in French, with explanations
    page.locator("solarprio-panel #btn-add").click()
    dialog = page.locator("solarprio-panel .dialog")
    dialog.wait_for()
    kinds = page.locator("solarprio-panel .dialog button.kind").all_inner_texts()
    print("types offered:", kinds)
    assert len(kinds) == 4 and any("Batterie" in k for k in kinds), kinds
    page.screenshot(path="panel_add_type.png")
    page.locator("solarprio-panel .dialog button.kind").first.click()
    page.locator("solarprio-panel #f-name").wait_for()

    text = dialog.inner_text()
    assert "Entité du signal heures creuses" in text and "États qui signifient heures creuses" in text, text
    assert "offpeak_entity" not in text and "offpeak_values" not in text, "raw field names must not be shown"
    assert "période tarifaire de votre Linky" in text  # the explanation is there
    page.screenshot(path="panel_add_form.png", full_page=True)

    # entity suggestions come from the instance: only switch / input_boolean / light for an on/off device
    options = page.locator("solarprio-panel").evaluate("el => [...el.shadowRoot.querySelectorAll('#dl-entity_id option')].map(o => o.value)")
    assert "input_boolean.pump" in options and "input_number.dimmer" not in options, options

    # required fields are checked before anything is sent
    page.locator("solarprio-panel .dialog button[type=submit]").click()
    assert page.locator("solarprio-panel .field.invalid").count() >= 3
    assert "Obligatoire" in dialog.inner_text()
    assert rows.count() == 3

    # a server-side refusal is shown and keeps the dialog open
    page.fill("solarprio-panel #f-name", NEW)
    page.fill("solarprio-panel #f-entity_id", "sensor.grid_power")  # not a switch
    page.fill("solarprio-panel #f-power_w", "500")
    page.locator("solarprio-panel .dialog button[type=submit]").click()
    wait(lambda: "Non enregistré" in dialog.inner_text(), 10, "refusal message")
    print("refusal shown:", page.locator("solarprio-panel .form-error").inner_text())

    # a valid one
    page.fill("solarprio-panel #f-entity_id", "input_boolean.ev_switch")
    page.locator("solarprio-panel .dialog button[type=submit]").click()
    wait(lambda: rows.count() == 4, 30, "4 rows after the addition")
    assert NEW in names(), names()
    assert page.locator("solarprio-panel").count() == 1 and "pas configuré" not in page.locator("solarprio-panel").inner_text()
    print("added:", names())
    saved = [d for d in ws({"type": "solarprio/state"})["devices"] if d["name"] == NEW][0]
    assert saved["entity_id"] == "input_boolean.ev_switch" and saved["power_w"] == 500 and saved["enabled"] is True

    # ---- edit: values are pre-filled; change the power
    row = page.locator(f"solarprio-panel li.row:has-text('{NEW}')")
    row.locator("button.edit").click()
    page.locator("solarprio-panel #f-power_w").wait_for()
    assert page.input_value("solarprio-panel #f-power_w") == "500"
    assert page.input_value("solarprio-panel #f-name") == NEW
    page.fill("solarprio-panel #f-power_w", "650")
    page.locator("solarprio-panel .dialog button[type=submit]").click()
    wait(lambda: any(d["power_w"] == 650 for d in ws({"type": "solarprio/state"})["devices"] if d["name"] == NEW), 30, "power 650 saved")
    wait(lambda: "650 W" in page.locator(f"solarprio-panel li.row:has-text('{NEW}') .sub").inner_text(), 30, "row shows 650 W")
    print("edited:", page.locator(f"solarprio-panel li.row:has-text('{NEW}') .sub").inner_text())

    # ---- cancel and Escape close without saving
    row.locator("button.edit").click()
    page.locator("solarprio-panel #f-power_w").wait_for()
    page.fill("solarprio-panel #f-power_w", "999")
    page.keyboard.press("Escape")
    assert page.locator("solarprio-panel .dialog").count() == 0
    assert [d["power_w"] for d in ws({"type": "solarprio/state"})["devices"] if d["name"] == NEW] == [650]

    # ---- site settings: invalid value refused, valid one saved and applied
    page.locator("solarprio-panel #btn-settings").click()
    page.locator("solarprio-panel #f-stale_after_s").wait_for()
    assert "Réglages de la mesure" in dialog.inner_text() and "stale_after_s" not in dialog.inner_text()
    assert page.input_value("solarprio-panel #f-stale_after_s") == "3600"
    page.fill("solarprio-panel #f-stale_after_s", "1")
    page.locator("solarprio-panel .dialog button[type=submit]").click()
    wait(lambda: page.locator("solarprio-panel .field.invalid").count() == 1, 10, "the offending field is marked")
    page.fill("solarprio-panel #f-stale_after_s", "1800")
    page.locator("solarprio-panel .dialog button[type=submit]").click()
    wait(lambda: ws({"type": "solarprio/settings_form", "language": "fr"})["values"]["stale_after_s"] == 1800, 30, "setting saved")
    wait(lambda: rows.count() == 4, 30, "panel back after the reload")
    print("settings saved: stale_after_s =", ws({"type": "solarprio/settings_form"})["values"]["stale_after_s"])

    # ---- delete with confirmation
    page.locator(f"solarprio-panel li.row:has-text('{NEW}') button.remove").click()
    page.locator("solarprio-panel .dialog .danger").wait_for()
    page.locator("solarprio-panel .dialog .cancel").click()
    assert rows.count() == 4
    page.locator(f"solarprio-panel li.row:has-text('{NEW}') button.remove").click()
    page.locator("solarprio-panel .dialog .danger").click()
    wait(lambda: rows.count() == 3 and NEW not in names(), 30, "device deleted")
    print("deleted:", names())

    # the other devices are untouched and routing resumed
    assert names() == ["Chauffe-eau (variateur)", "Pompe piscine", "Serveur de calcul"]
    wait(lambda: state("sensor.solarprio_status") == "routing", 30, "routing after the changes")
    page.screenshot(path="panel_after_edit.png")
    print("page errors (Home Assistant's own are expected):", errors)
    browser.close()
print("E2E EDIT OK")
