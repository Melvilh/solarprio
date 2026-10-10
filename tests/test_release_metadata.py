"""Metadata that Home Assistant, HACS and package tooling rely on must stay consistent."""
import json
import re
import struct
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = next((ROOT / "custom_components").iterdir())  # HACS allows exactly one integration per repository


def read(path):
    return Path(path).read_text()


def test_exactly_one_integration_directory():
    dirs = [d for d in (ROOT / "custom_components").iterdir() if d.is_dir() and not d.name.startswith("__")]
    assert len(dirs) == 1


def test_versions_are_identical_everywhere():
    pyproject = tomllib.loads(read(ROOT / "pyproject.toml"))["project"]["version"]
    manifest = json.loads(read(INTEGRATION / "manifest.json"))["version"]
    package = re.search(r'__version__ = "([^"]+)"', read(next((ROOT / "src").glob("*/__init__.py")))).group(1)
    panel = re.search(r'VERSION = "([^"]+)"', read(INTEGRATION / "panel.py")).group(1)
    assert pyproject == manifest == package == panel, (pyproject, manifest, package, panel)


def test_manifest_has_what_hacs_and_hassfest_require():
    manifest = json.loads(read(INTEGRATION / "manifest.json"))
    for key in ("domain", "documentation", "issue_tracker", "codeowners", "name", "version"):  # HACS
        assert key in manifest, key
    assert manifest["domain"] == INTEGRATION.name
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"] and keys[2:] == sorted(keys[2:]), "hassfest wants: domain, name, then alphabetical"


def test_hacs_json_and_license():
    assert json.loads(read(ROOT / "hacs.json"))["name"]
    license_text = read(ROOT / "LICENSE")
    assert "Apache License" in license_text and "Version 2.0, January 2004" in license_text


def test_brand_icons_have_the_sizes_home_assistant_requires():
    def size(path):
        data = Path(path).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        return struct.unpack(">II", data[16:24])

    assert size(INTEGRATION / "brand" / "icon.png") == (256, 256)
    assert size(INTEGRATION / "brand" / "icon@2x.png") == (512, 512)


def test_translations_cover_the_same_keys():
    def keys(node, prefix=""):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from keys(v, f"{prefix}.{k}")
        else:
            yield prefix

    en = set(keys(json.loads(read(INTEGRATION / "translations" / "en.json"))))
    fr = set(keys(json.loads(read(INTEGRATION / "translations" / "fr.json"))))
    strings = set(keys(json.loads(read(INTEGRATION / "strings.json"))))
    assert en == fr == strings, (en ^ fr, en ^ strings)
