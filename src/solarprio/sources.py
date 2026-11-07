"""Helpers turning raw measurements into the ``available_w`` the engine needs.

``available_w`` must include the power managed loads already draw: if a heater
takes 2000 W and 300 W is still exported, 2300 W is available to the engine.
"""

from __future__ import annotations

# States that mean "off-peak" when the user gives no list of their own. Written from what meters and helpers usually
# report (a binary sensor, a boolean, the historic Linky tariff period "HC.."); check what YOUR sensor reports and set the
# values explicitly if it differs. Anything else counts as "not off-peak".
DEFAULT_OFFPEAK_WORDS = frozenset({"on", "true", "1", "yes", "hc", "hc..", "off_peak", "off-peak", "offpeak", "low"})
UNKNOWN_WORDS = frozenset({"", "unknown", "unavailable", "none", "null", "nan"})


def parse_offpeak_state(text: object, off_peak_values: list[str] | tuple[str, ...] | None = None) -> bool | None:
    """Turn the state of a tariff entity or topic into "off-peak now" (True), "not now" (False) or unknown (None).

    ``off_peak_values``: the states that mean off-peak (case-insensitive, exact). Without it a default list is used and
    any text containing "creuse" also counts (for example "HEURES CREUSES"). Unknown or unavailable gives None, which the
    engine treats as "not off-peak" (it never forces a load on an unknown signal).
    """
    word = str(text).strip().strip('"').lower()
    if word in UNKNOWN_WORDS:
        return None
    if off_peak_values:
        return word in {str(v).strip().lower() for v in off_peak_values}
    return word in DEFAULT_OFFPEAK_WORDS or "creuse" in word


def available_from_export(export_w: float, routed_w: float) -> float:
    """Grid export (positive = exporting) plus what managed loads already consume."""
    return export_w + routed_w


def available_from_production(production_w: float, consumption_w: float, routed_w: float) -> float:
    """Production minus the house consumption that is *not* managed by the engine.

    ``consumption_w`` is the total house consumption, including managed loads.
    """
    return production_w - (consumption_w - routed_w)
