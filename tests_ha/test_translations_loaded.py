"""What Home Assistant really loads for the device form, in both languages: every field has a label."""
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from custom_components.solarprio.config_flow import _details_schema
from custom_components.solarprio.const import DOMAIN

KINDS = ["on_off", "proportional", "battery", "ev_charger", "task"]


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_every_field_of_every_device_form_has_a_label_and_the_loaded_translations_contain_it(hass: HomeAssistant, language):
    loaded = await async_get_translations(hass, language, "options", [DOMAIN])
    prefix = f"component.{DOMAIN}.options.step.device_details"
    missing = []
    for kind in KINDS:
        for key in _details_schema(kind, {}, 1).schema:
            if f"{prefix}.data.{key}" not in loaded:
                missing.append(f"{kind}: {key}")
    assert not missing, f"fields without a label in {language}: {sorted(set(missing))}"


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_the_off_peak_fields_are_explained(hass: HomeAssistant, language):
    loaded = await async_get_translations(hass, language, "options", [DOMAIN])
    prefix = f"component.{DOMAIN}.options.step.device_details.data_description"
    for key in ("offpeak", "offpeak_entity", "offpeak_values", "reset_at", "done_below_w", "done_after_s"):
        assert loaded.get(f"{prefix}.{key}"), f"no explanation for {key} in {language}"
