"""Helpers turning raw measurements into the ``available_w`` the engine needs.

``available_w`` must include the power managed loads already draw: if a heater
takes 2000 W and 300 W is still exported, 2300 W is available to the engine.
"""

from __future__ import annotations


def available_from_export(export_w: float, routed_w: float) -> float:
    """Grid export (positive = exporting) plus what managed loads already consume."""
    return export_w + routed_w


def available_from_production(production_w: float, consumption_w: float, routed_w: float) -> float:
    """Production minus the house consumption that is *not* managed by the engine.

    ``consumption_w`` is the total house consumption, including managed loads.
    """
    return production_w - (consumption_w - routed_w)
