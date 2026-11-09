"""Catalog of ready-made profiles, by brand and model.

A profile is a data file (``data/<id>.json``): no code is needed to add one. It describes a device or a measurement source of
a given brand with the values and topics that are known for it, and the few parameters the user still has to give (an
identifier, a number of phases). It serves two places:

- the standalone runtime: ``[[device]] profile = "victron-evcs"`` and ``params = {...}`` in the TOML file expands to the
  full configuration, and everything written next to it overrides the profile;
- the Home Assistant panel: a profile with an ``ha`` section is offered as a ready-made model when adding a device.

Every profile states honestly how far it was checked (``status``): ``verified`` (run on real hardware), ``simulated``
(automated tests against a simulated device), ``from_docs`` (written from the manufacturer's documentation) or ``untested``.
"""

from __future__ import annotations

import copy
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent / "data"
STATUSES = ("verified", "simulated", "from_docs", "untested")
TARGETS = ("device", "source")
CATEGORIES = ("water_heater", "heat_pump", "ev_charger", "battery", "inverter", "relay", "meter", "task", "other")
_ALLOWED_KEYS = {"id", "brand", "model", "category", "target", "status", "docs", "label", "params", "runtime", "ha", "notes"}
_PLACEHOLDER = re.compile(r"\$\{(\w+)\}")


class ProfileError(ValueError):
    """A profile is malformed, unknown, or used with wrong parameters."""


def localized(text: Any, language: str = "en") -> str:
    """A text that is either a string or a ``{"en": ..., "fr": ...}`` dictionary, in the wanted language (else English)."""
    if isinstance(text, dict):
        return str(text.get(language[:2].lower()) or text.get("en") or next(iter(text.values()), ""))
    return str(text)


def _check(profile: dict[str, Any], name: str) -> None:
    where = f"profile {name!r}"
    unknown = set(profile) - _ALLOWED_KEYS
    if unknown:
        raise ProfileError(f"{where}: unknown keys {sorted(unknown)}")
    for key in ("id", "brand", "model", "category", "target", "status", "label"):
        if key not in profile:
            raise ProfileError(f"{where}: missing {key!r}")
    if profile["id"] != name:
        raise ProfileError(f"{where}: the id must equal the file name")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", profile["id"]):
        raise ProfileError(f"{where}: the id must be lowercase words joined by dashes")
    if profile["status"] not in STATUSES:
        raise ProfileError(f"{where}: status must be one of {STATUSES}")
    if profile["target"] not in TARGETS:
        raise ProfileError(f"{where}: target must be one of {TARGETS}")
    if profile["category"] not in CATEGORIES:
        raise ProfileError(f"{where}: category must be one of {CATEGORIES}")
    if not isinstance(profile["label"], dict) or not profile["label"].get("en"):
        raise ProfileError(f"{where}: label needs at least an English text")
    if "runtime" not in profile and "ha" not in profile:
        raise ProfileError(f"{where}: needs a 'runtime' section, an 'ha' section, or both")
    if "runtime" in profile and not isinstance(profile["runtime"], dict):
        raise ProfileError(f"{where}: runtime must be a table")
    if "ha" in profile:
        ha = profile["ha"]
        if profile["target"] != "device" or not isinstance(ha, dict) or "kind" not in ha or not isinstance(ha.get("values", {}), dict):
            raise ProfileError(f"{where}: ha must be {{'kind': ..., 'values': {{...}}}} and only for a device profile")
    names = []
    for param in profile.get("params", []):
        if not isinstance(param, dict) or "name" not in param or not re.fullmatch(r"\w+", str(param["name"])):
            raise ProfileError(f"{where}: every param needs a name")
        if param["name"] in names:
            raise ProfileError(f"{where}: duplicate param {param['name']!r}")
        names.append(param["name"])
        if not param.get("required") and "default" not in param:
            raise ProfileError(f"{where}: param {param['name']!r} needs a default or must be required")
    used = set(_PLACEHOLDER.findall(json.dumps(profile.get("runtime", {})))) | {
        p for r in _find_repeats(profile.get("runtime", {})) for p in [r]
    }
    missing = used - set(names) - {"n"}
    if missing:
        raise ProfileError(f"{where}: placeholders without a param: {sorted(missing)}")


def _find_repeats(node: Any) -> list[str]:
    if isinstance(node, dict):
        found = [node["$repeat"]] if "$repeat" in node else []
        return found + [r for v in node.values() for r in _find_repeats(v)]
    if isinstance(node, list):
        return [r for v in node for r in _find_repeats(v)]
    return []


@lru_cache(maxsize=1)
def load_profiles() -> dict[str, dict[str, Any]]:
    """Every profile of the catalog, validated, by id."""
    profiles: dict[str, dict[str, Any]] = {}
    for path in sorted(DATA.glob("*.json")):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as err:
            raise ProfileError(f"profile {path.name}: not valid JSON ({err})") from None
        _check(profile, path.stem)
        profiles[profile["id"]] = profile
    return profiles


def get_profile(profile_id: str) -> dict[str, Any]:
    try:
        return load_profiles()[profile_id]
    except KeyError:
        known = ", ".join(sorted(load_profiles())) or "none"
        raise ProfileError(f"unknown profile {profile_id!r} (known: {known})") from None


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """``override`` on top of ``base``: tables are merged key by key, anything else is replaced."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def resolve_params(profile: dict[str, Any], given: dict[str, Any]) -> dict[str, Any]:
    spec = {p["name"]: p for p in profile.get("params", [])}
    unknown = set(given) - set(spec)
    if unknown:
        raise ProfileError(f"profile {profile['id']!r}: unknown params {sorted(unknown)} (known: {sorted(spec)})")
    values = {}
    for name, p in spec.items():
        if name in given:
            values[name] = given[name]
        elif "default" in p:
            values[name] = p["default"]
        else:
            raise ProfileError(f"profile {profile['id']!r}: the param {name!r} is required")
    return values


def _substitute(node: Any, values: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$repeat" in node:  # {"$repeat": "phases", "template": "L${n}"} -> ["L1", "L2", ...]
            count = values[node["$repeat"]]
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 12:
                raise ProfileError(f"param {node['$repeat']!r} must be a whole number between 1 and 12")
            return [_substitute(node["template"], {**values, "n": n}) for n in range(1, count + 1)]
        return {k: _substitute(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, values) for v in node]
    if isinstance(node, str):
        whole = _PLACEHOLDER.fullmatch(node)
        if whole:
            return values[whole.group(1)]  # keeps the type: a number stays a number
        return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), node)
    return node


def expand(profile_id: str, params: dict[str, Any] | None, target: str) -> dict[str, Any]:
    """The runtime configuration fragment of a profile, with its parameters filled in."""
    profile = get_profile(profile_id)
    if profile["target"] != target:
        raise ProfileError(f"profile {profile_id!r} is a {profile['target']} profile, not a {target} one")
    if "runtime" not in profile:
        raise ProfileError(f"profile {profile_id!r} has no runtime configuration (it is for the Home Assistant panel)")
    return _substitute(copy.deepcopy(profile["runtime"]), resolve_params(profile, params or {}))


def ha_presets() -> dict[str, dict[str, Any]]:
    """The device profiles that have an ``ha`` section: ready-made models for the Home Assistant panel, by profile id."""
    return {
        pid: {"kind": p["ha"]["kind"], "values": dict(p["ha"].get("values", {})), "label": p["label"], "brand": p["brand"],
              "status": p["status"], "notes": p.get("notes", "")}
        for pid, p in load_profiles().items()
        if "ha" in p
    }
