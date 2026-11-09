"""Adding, editing and removing devices, and editing the site settings, from the sidebar panel (websocket API)."""
import pytest
from homeassistant.core import HomeAssistant

from custom_components.solarprio.config_flow import _details_schema
from custom_components.solarprio.const import DOMAIN
from custom_components.solarprio.forms import clean_site, site_fields

from .test_integration import GRID, coordinator, dev
from .test_panel import prepare, ws

KINDS = ["on_off", "proportional", "battery", "ev_charger", "task"]
HEATER = dict(name="Water heater", entity_id="switch.heater", priority=1, power_w=2000, min_on_s=0, min_off_s=0,
              start_margin_w=0, stay_tolerance_w=0)


@pytest.mark.parametrize("kind", KINDS)
async def test_panel_and_options_flow_show_exactly_the_same_fields(hass: HomeAssistant, hass_ws_client, kind):
    await prepare(hass)
    client = await hass_ws_client(hass)
    resp = await ws(client, type="solarprio/device_form", kind=kind, language="fr")
    assert resp["success"]
    panel_fields = [f["name"] for f in resp["result"]["fields"]]
    assert panel_fields == [str(k) for k in _details_schema(kind, {}, 1).schema]  # same fields, same order


async def test_the_form_comes_with_labels_help_and_type_names_in_the_users_language(hass: HomeAssistant, hass_ws_client):
    await prepare(hass)
    client = await hass_ws_client(hass)
    fr = (await ws(client, type="solarprio/device_form", kind="on_off", language="fr"))["result"]
    en = (await ws(client, type="solarprio/device_form", kind="on_off", language="en"))["result"]
    label = lambda r, name: next(f for f in r["fields"] if f["name"] == name)  # noqa: E731
    assert label(fr, "offpeak_entity")["label"] == "Entité du signal heures creuses (facultatif)"
    assert label(en, "offpeak_entity")["label"] == "Off-peak signal entity (optional)"
    assert label(fr, "offpeak_entity")["description"] and label(en, "offpeak_values")["description"]
    assert fr["kinds"]["battery"] == "Batterie" and en["kinds"]["battery"] == "Battery"
    unknown = (await ws(client, type="solarprio/device_form", kind="on_off", language="xx"))["result"]
    assert label(unknown, "offpeak_entity")["label"] == "Off-peak signal entity (optional)"  # falls back to English


@pytest.mark.parametrize("kind", KINDS)
async def test_every_field_of_every_form_has_a_label_and_the_required_ones_are_marked(hass: HomeAssistant, hass_ws_client, kind):
    await prepare(hass)
    client = await hass_ws_client(hass)
    for language in ("en", "fr"):
        fields = (await ws(client, type="solarprio/device_form", kind=kind, language=language))["result"]["fields"]
        assert all(f["label"] != f["name"] for f in fields), [f["name"] for f in fields if f["label"] == f["name"]]
        assert {f["name"] for f in fields if f["required"]} >= {"name", "entity_id", "priority"}


async def test_adding_a_device_from_the_panel(hass: HomeAssistant, hass_ws_client):
    entry, *_ = await prepare(hass, devices=[], grid="0")
    client = await hass_ws_client(hass)
    resp = await ws(client, type="solarprio/device_save", kind="on_off", values=HEATER)
    assert resp["success"], resp
    await hass.async_block_till_done()
    saved = entry.options["devices"]
    assert [d["id"] for d in saved] == ["water_heater"] and saved[0]["enabled"] is True and saved[0]["kind"] == "on_off"
    assert coordinator(hass, entry).engine.device("water_heater").power_w == 2000  # the entry reloaded with it


async def test_editing_a_device_keeps_its_identity_and_enabled_state(hass: HomeAssistant, hass_ws_client):
    entry, *_ = await prepare(hass, devices=[dev(id="pump", name="Pump", entity_id="switch.pump", power_w=800, enabled=False)], grid="0")
    client = await hass_ws_client(hass)
    form = (await ws(client, type="solarprio/device_form", kind="on_off", device_id="pump", language="en"))["result"]
    assert form["values"]["name"] == "Pump" and form["values"]["power_w"] == 800
    resp = await ws(client, type="solarprio/device_save", kind="on_off", device_id="pump",
                    values={**HEATER, "name": "Pump 2", "entity_id": "switch.pump", "power_w": 900})
    assert resp["success"]
    await hass.async_block_till_done()
    (saved,) = entry.options["devices"]
    assert saved["id"] == "pump" and saved["name"] == "Pump 2" and saved["power_w"] == 900 and saved["enabled"] is False


@pytest.mark.parametrize("values", [
    {**HEATER, "power_w": 0},  # power must be > 0
    {**HEATER, "offpeak": "25:00-06:00", "measured_entity": "sensor.p"},
    {**HEATER, "offpeak": "22:30-06:30"},  # needs a measured power
    {**HEATER, "temp_max_solar": 65},  # temperature limits need a temperature sensor
    {**HEATER, "temp_entity": "sensor.t", "temp_max_solar": 65, "temp_min": 63},  # minimum too close to the maximum
    {k: v for k, v in HEATER.items() if k != "priority"},
])
async def test_invalid_devices_are_refused_and_nothing_is_saved(hass: HomeAssistant, hass_ws_client, values):
    entry, *_ = await prepare(hass, devices=[], grid="0")
    client = await hass_ws_client(hass)
    resp = await ws(client, type="solarprio/device_save", kind="on_off", values=values)
    assert not resp["success"] and resp["error"]["code"] == "invalid_device"
    assert entry.options["devices"] == []


async def test_unknown_kind_or_device_is_refused(hass: HomeAssistant, hass_ws_client):
    await prepare(hass, devices=[], grid="0")
    client = await hass_ws_client(hass)
    assert not (await ws(client, type="solarprio/device_save", kind="toaster", values=HEATER))["success"]
    resp = await ws(client, type="solarprio/device_save", kind="on_off", device_id="ghost", values=HEATER)
    assert resp["error"]["code"] == "unknown_device"
    resp = await ws(client, type="solarprio/device_form", kind="on_off", device_id="ghost")
    assert resp["error"]["code"] == "unknown_device"
    resp = await ws(client, type="solarprio/device_remove", device_id="ghost")
    assert resp["error"]["code"] == "unknown_device"


async def test_removing_a_device_switches_it_off(hass: HomeAssistant, hass_ws_client):
    entry, set_value, turn_on, turn_off = await prepare(
        hass, devices=[dev(id="pump", name="Pump", entity_id="switch.pump", power_w=800)], grid="2000")
    assert [c.data["entity_id"] for c in turn_on] == ["switch.pump"]
    client = await hass_ws_client(hass)
    resp = await ws(client, type="solarprio/device_remove", device_id="pump")
    assert resp["success"]
    await hass.async_block_till_done()
    assert entry.options["devices"] == []
    assert [c.data["entity_id"] for c in turn_off] == ["switch.pump"]  # not left running without anyone looking after it


async def test_ids_stay_unique_when_the_same_name_is_added_twice(hass: HomeAssistant, hass_ws_client):
    entry, *_ = await prepare(hass, devices=[], grid="0")
    client = await hass_ws_client(hass)
    for _ in range(2):
        assert (await ws(client, type="solarprio/device_save", kind="on_off", values=HEATER))["success"]
        await hass.async_block_till_done()
    assert [d["id"] for d in entry.options["devices"]] == ["water_heater", "water_heater_2"]


# ---------------------------------------------------------------- site settings

async def test_the_settings_form_and_saving_new_measurement_settings(hass: HomeAssistant, hass_ws_client):
    entry, *_ = await prepare(hass, devices=[], grid="0")
    client = await hass_ws_client(hass)
    form = (await ws(client, type="solarprio/settings_form", language="fr"))["result"]
    names = [f["name"] for f in form["fields"]]
    assert names[0] == "mode" and "stale_after_s" in names and "offpeak_budget_w" in names
    assert all(f["label"] != f["name"] for f in form["fields"]), [f["name"] for f in form["fields"] if f["label"] == f["name"]]
    assert form["values"]["stale_after_s"] == 60

    values = {**form["values"], "stale_after_s": 300, "margin_w": 80}
    resp = await ws(client, type="solarprio/settings_save", values=values)
    assert resp["success"], resp
    await hass.async_block_till_done()
    assert entry.data["stale_after_s"] == 300 and entry.data["margin_w"] == 80
    assert coordinator(hass, entry)._conf["stale_after_s"] == 300  # reloaded: the running coordinator uses it


async def test_settings_changes_are_validated(hass: HomeAssistant, hass_ws_client):
    entry, *_ = await prepare(hass, devices=[], grid="0")
    client = await hass_ws_client(hass)
    good = dict(entry.data)
    for field, value in (("stale_after_s", -1), ("interval_s", "fast"), ("on_stale", "explode"), ("mode", "magic"),
                         ("export_entity", "switch.not_a_sensor"), ("margin_w", -5)):
        resp = await ws(client, type="solarprio/settings_save", values={**good, field: value})
        assert not resp["success"] and resp["error"]["code"] == "invalid_settings" and resp["error"]["message"] == field, field
    assert dict(entry.data) == good


async def test_switching_to_production_mode_needs_both_sensors(hass: HomeAssistant, hass_ws_client):
    entry, *_ = await prepare(hass, devices=[], grid="0")
    client = await hass_ws_client(hass)
    base = {k: v for k, v in dict(entry.data).items() if k not in ("export_entity", "invert")}
    resp = await ws(client, type="solarprio/settings_save", values={**base, "mode": "production", "production_entity": "sensor.pv"})
    assert resp["error"]["message"] == "consumption_entity"
    resp = await ws(client, type="solarprio/settings_save",
                    values={**base, "mode": "production", "production_entity": "sensor.pv", "consumption_entity": "sensor.house"})
    assert resp["success"]
    await hass.async_block_till_done()
    assert entry.data["mode"] == "production" and "export_entity" not in entry.data


async def test_the_site_form_covers_the_same_settings_as_the_setup_form(hass: HomeAssistant):
    """Guard against drift: a setting added to the setup form must appear in the panel form, and the other way round."""
    shown = set()
    for mode in ("export", "production"):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"mode": mode})
        shown |= {str(k) for k in result["data_schema"].schema}
        hass.config_entries.flow.async_abort(result["flow_id"])  # so the next init is not "already in progress"
    assert shown == {f.name for f in site_fields()} - {"mode"}


def test_missing_settings_take_their_default_and_bad_ones_are_named():
    ok = clean_site({"mode": "export", "export_entity": "sensor.g"})
    assert ok["stale_after_s"] == 60 and ok["on_stale"] == "off" and ok["invert"] is False and "production_entity" not in ok
    with pytest.raises(ValueError, match="export_entity"):
        clean_site({"mode": "export"})


@pytest.mark.parametrize("kind, values", [
    ("on_off", {**HEATER, "min_on_s": -5}),  # below the minimum of the field
    ("on_off", {**HEATER, "priority": 1000}),
    ("on_off", {**HEATER, "power_w": "lots"}),
    ("on_off", {**HEATER, "power_w": True}),
    ("on_off", {**HEATER, "entity_id": "sensor.heater"}),  # not a switch / light
    ("on_off", {**HEATER, "measured_entity": "switch.x"}),  # not a sensor
    ("battery", {**HEATER, "entity_id": "number.bat", "scale": "kilowatts"}),
    ("ev_charger", {**HEATER, "entity_id": "number.evse", "phases": "2"}),
    ("on_off", {"priority": 1, "power_w": 100}),  # no name, no entity
])
async def test_out_of_range_or_wrongly_typed_values_are_refused(hass: HomeAssistant, hass_ws_client, kind, values):
    entry, *_ = await prepare(hass, devices=[], grid="0")
    client = await hass_ws_client(hass)
    resp = await ws(client, type="solarprio/device_save", kind=kind, values=values)
    assert not resp["success"] and resp["error"]["code"] == "invalid_device", values
    assert entry.options["devices"] == []


async def test_each_kind_can_be_saved_with_its_own_fields(hass: HomeAssistant, hass_ws_client):
    entry, *_ = await prepare(hass, devices=[], grid="0")
    client = await hass_ws_client(hass)
    forms = {
        "proportional": {"name": "Dimmer", "entity_id": "light.heater", "priority": 1, "power_w": 2400, "min_power_w": 100,
                         "scale": "percent", "min_on_s": 0, "min_off_s": 0, "done_below_w": 0, "done_after_s": 120},
        "battery": {"name": "Battery", "entity_id": "number.bat", "priority": 2, "power_w": 3000, "min_power_w": 0, "scale": "watts",
                    "soc_max": 90, "soc_resume_margin": 2, "min_on_s": 0, "min_off_s": 0},
        "ev_charger": {"name": "Wallbox", "entity_id": "number.evse", "priority": 3, "phases": "3", "voltage_v": 230,
                       "min_current_a": 6, "max_current_a": 16, "current_step_a": 1, "soc_max": 100, "min_on_s": 0, "min_off_s": 0,
                       "start_margin_w": 0, "stay_tolerance_w": 0, "done_below_w": 0, "done_after_s": 120},
    }
    for kind, values in forms.items():
        resp = await ws(client, type="solarprio/device_save", kind=kind, values=values)
        assert resp["success"], (kind, resp)
        await hass.async_block_till_done()
    saved = {d["kind"]: d for d in entry.options["devices"]}
    assert set(saved) == set(forms)
    assert saved["ev_charger"]["phases"] == 3 and saved["ev_charger"]["power_w"] == 16 * 230 * 3  # derived, stored for the panel


def test_the_panel_address_changes_with_the_file_so_a_browser_never_keeps_an_old_panel(tmp_path, monkeypatch):
    from custom_components.solarprio import panel

    fake = tmp_path / "panel.js"
    monkeypatch.setattr(panel, "PANEL_JS", fake)
    fake.write_text("one")
    first = panel._asset_version()
    fake.write_text("two")
    assert panel._asset_version() != first and panel._asset_version().startswith(panel.VERSION)
