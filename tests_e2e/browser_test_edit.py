"""Real Home Assistant + real Chromium: add, edit, configure and delete from the sidebar panel, with Home Assistant's own
form components (entity picker, number fields, expandable section, dialog)."""
import json

from common import api, browser_tokens, state, wait, wait_no_view_transition
from playwright.sync_api import sync_playwright

NEW = "Serveur 2"
PUMP2 = "EV charger switch"  # input_boolean.ev_switch, a free switch for the new device

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 1000, "height": 1000}, locale="fr-FR")
    ctx.add_init_script(f"localStorage.setItem('hassTokens', JSON.stringify({json.dumps(browser_tokens())}));")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8123/solarprio")
    panel = page.locator("solarprio-panel")
    rows = page.locator("solarprio-panel li.row")
    wait(lambda: rows.count() == 3, 30, "3 device rows")
    wait_no_view_transition(page)

    def names():
        return page.locator("solarprio-panel li.row .name").all_inner_texts()

    def ws(msg):
        return page.evaluate("async (m) => document.querySelector('home-assistant').hass.callWS(m)", msg)

    def dialog_text():
        """All the text of the dialog, through the shadow roots of Home Assistant's components (innerText stops at them)."""
        return page.locator("solarprio-panel ha-dialog").evaluate("""root => {
          const out = [];
          const walk = (node) => {
            if (node.nodeType === 3) { out.push(node.textContent); return; }
            if (node.shadowRoot) node.shadowRoot.childNodes.forEach(walk);
            node.childNodes.forEach(walk);
          };
          walk(root);
          return out.join(' ').replace(/\s+/g, ' ');
        }""")

    def button(text):
        return page.locator("solarprio-panel ha-dialog ha-button", has_text=text)

    def field(label):
        return panel.get_by_label(label).first

    def picker(label):
        return page.locator("solarprio-panel ha-dialog ha-selector", has_text=label).locator("ha-entity-picker").first

    def choose_entity(label, query, name):
        picker(label).click()
        page.wait_for_timeout(600)
        page.keyboard.type(query)
        page.wait_for_timeout(800)
        page.locator("ha-combo-box-item", has_text=name).first.click()
        page.wait_for_timeout(400)

    def entity_results(label, query):
        picker(label).click()
        page.wait_for_timeout(600)
        page.keyboard.type(query)
        page.wait_for_timeout(800)
        found = [t for t in page.locator("ha-combo-box-item").all_inner_texts()
                 if query.lower() in t.lower() and "Aucune entité trouvée" not in t and "Créer une nouvelle" not in t]
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        return found

    # ---- the look is Home Assistant's own: its form, its dialog, its buttons, its switches
    for tag in ("ha-card", "ha-button", "ha-switch", "ha-icon-button"):
        assert page.locator(f"solarprio-panel {tag}").count() > 0, f"the panel should use {tag}"
    assert page.locator("solarprio-panel button.btn, solarprio-panel label.switch").count() == 0, "no home-made controls left"

    # ---- add: ready-made models, then the other types
    page.locator("solarprio-panel #btn-add").click()
    button("Chauffe-eau sur routeur solaire").wait_for()
    presets = [t for t in page.locator("solarprio-panel ha-dialog ha-button").all_inner_texts() if "Chauffe-eau sur" in t or "Victron" in t]
    kinds = [t for t in page.locator("solarprio-panel ha-dialog ha-button").all_inner_texts() if t not in presets and t != "Annuler"]
    print("ready-made models:", presets)
    print("types offered:", kinds)
    assert len(presets) == 3 and len(kinds) == 5 and any("Batterie" in k for k in kinds) and any("Tâche informatique" in k for k in kinds)
    assert any("Victron" in t and "testé en simulation seulement" in t for t in presets), presets  # a brand model says how far it was checked
    assert not any("serveur" in k.lower() for k in kinds), kinds  # no suggestion to cut a server's power
    page.screenshot(path="panel_add_type.png")

    # a model fills the water heater values; the advanced settings are folded away
    button("Chauffe-eau sur routeur solaire").click()
    field("Arrêter de chauffer avec le soleil").wait_for()
    assert field("Arrêter de chauffer avec le soleil").input_value() == "65"
    assert field("Arrêter de chauffer en heures creuses").input_value() == "60"
    assert not field("Attente après un changement").is_visible(), "the advanced settings start folded"
    page.get_by_text("Réglages avancés").first.click()
    field("Attente après un changement").wait_for()
    assert field("Attente après un changement").input_value() == "8" and field("Plus grande montée").input_value() == "200"
    page.screenshot(path="panel_add_preset.png", full_page=True)
    page.keyboard.press("Escape")
    wait(lambda: page.locator("solarprio-panel ha-dialog").count() == 0, 10, "dialog closed with Escape")

    # ---- a plain on/off device
    page.locator("solarprio-panel #btn-add").click()
    button("Charge tout-ou-rien").click()
    field("Nom").wait_for()
    page.get_by_text("Réglages avancés").first.click()  # the off-peak details are under "advanced settings"
    text = dialog_text()
    assert "Entité du signal heures creuses" in text and "États qui signifient heures creuses" in text, text
    assert "offpeak_entity" not in text and "offpeak_values" not in text, "raw field names must not be shown"
    assert "période tarifaire de votre Linky" in text  # the explanation is there
    page.screenshot(path="panel_add_form.png", full_page=True)

    # the entity picker is Home Assistant's: search by name, only the right kinds of entity for an on/off device
    assert entity_results("Entité à piloter", "Pump"), "the pump (input_boolean) is offered"
    page.screenshot(path="panel_picker_open.png")
    assert not entity_results("Entité à piloter", "Dimmer"), "a number is not offered for an on/off device"

    # required fields are checked before anything is sent
    button("Enregistrer").click()
    try:
        wait(lambda: "Obligatoire" in dialog_text(), 10, "required messages")
    except AssertionError:
        print("DIALOG TEXT:", dialog_text()[:1500])
        page.screenshot(path="panel_required_failed.png")
        raise
    assert rows.count() == 3

    # a server-side refusal is shown and keeps the dialog open (a number out of range)
    field("Nom").fill(NEW)
    choose_entity("Entité à piloter", "EV", PUMP2)
    field("Puissance maximale").fill("500")
    field("Priorité").fill("5000")  # above the maximum of 999
    button("Enregistrer").click()
    wait(lambda: "Non enregistré" in dialog_text(), 10, "refusal message")
    print("refusal shown:", page.locator("solarprio-panel ha-alert").inner_text())

    # a valid one
    field("Priorité").fill("4")
    button("Enregistrer").click()
    wait(lambda: rows.count() == 4, 30, "4 rows after the addition")
    assert NEW in names(), names()
    assert page.locator("solarprio-panel").count() == 1 and "pas configuré" not in page.locator("solarprio-panel").inner_text()
    print("added:", names())
    saved = [d for d in ws({"type": "solarprio/state"})["devices"] if d["name"] == NEW][0]
    assert saved["entity_id"] == "input_boolean.ev_switch" and saved["power_w"] == 500 and saved["enabled"] is True

    # ---- edit: values are pre-filled; change the power
    row = page.locator(f"solarprio-panel li.row:has-text('{NEW}')")
    row.locator(".edit").click()
    field("Puissance maximale").wait_for()
    assert field("Puissance maximale").input_value() == "500"
    assert field("Nom").input_value() == NEW
    field("Puissance maximale").fill("650")
    button("Enregistrer").click()
    wait(lambda: any(d["power_w"] == 650 for d in ws({"type": "solarprio/state"})["devices"] if d["name"] == NEW), 30, "power 650 saved")
    wait(lambda: "650 W" in page.locator(f"solarprio-panel li.row:has-text('{NEW}') .sub").inner_text(), 30, "row shows 650 W")
    print("edited:", page.locator(f"solarprio-panel li.row:has-text('{NEW}') .sub").inner_text())

    # ---- cancel and Escape close without saving
    row.locator(".edit").click()
    field("Puissance maximale").wait_for()
    field("Puissance maximale").fill("999")
    button("Annuler").click()
    wait(lambda: page.locator("solarprio-panel ha-dialog").count() == 0, 10, "dialog closed by Cancel")
    assert [d["power_w"] for d in ws({"type": "solarprio/state"})["devices"] if d["name"] == NEW] == [650]

    # ---- site settings: invalid value refused, valid one saved and applied
    page.locator("solarprio-panel #btn-settings").click()
    page.get_by_text("Réglages avancés").first.click()  # the delay is under "advanced settings"
    delay = panel.get_by_label("Mesure considérée perdue après").first
    delay.wait_for()
    assert "Réglages de la mesure" in dialog_text() and "stale_after_s" not in dialog_text()
    assert delay.input_value() == "3600"
    delay.fill("5000")  # above the 3600 s maximum
    button("Enregistrer").click()
    try:
        wait(lambda: "Valeur invalide" in dialog_text(), 10, "the offending field is marked")
    except AssertionError:
        print("DIALOG TEXT:", dialog_text()[-900:])
        page.screenshot(path="panel_invalid_failed.png")
        raise
    delay.fill("0")  # 0 = never judge by age: allowed
    button("Enregistrer").click()
    wait(lambda: ws({"type": "solarprio/settings_form", "language": "fr"})["values"]["stale_after_s"] == 0, 30, "setting saved")
    wait(lambda: rows.count() == 4, 30, "panel back after the reload")
    print("settings saved: stale_after_s =", ws({"type": "solarprio/settings_form"})["values"]["stale_after_s"])

    # ---- delete with confirmation
    page.locator(f"solarprio-panel li.row:has-text('{NEW}') .remove").click()
    button("Supprimer").wait_for()
    button("Annuler").click()
    wait(lambda: page.locator("solarprio-panel ha-dialog").count() == 0, 10, "confirmation cancelled")
    assert rows.count() == 4
    page.locator(f"solarprio-panel li.row:has-text('{NEW}') .remove").click()
    button("Supprimer").click()
    wait(lambda: rows.count() == 3 and NEW not in names(), 30, "device deleted")
    print("deleted:", names())

    # the other devices are untouched and routing resumed
    assert names() == ["Chauffe-eau (variateur)", "Pompe piscine", "Serveur de calcul"]
    wait(lambda: state("sensor.solarprio_status") == "routing", 30, "routing after the changes")
    page.screenshot(path="panel_after_edit.png")
    print("page errors (Home Assistant's own are expected):", errors)
    browser.close()
print("E2E EDIT OK")
