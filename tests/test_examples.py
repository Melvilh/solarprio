"""Every example configuration shipped in the repository must parse: a broken recipe fails CI."""
from pathlib import Path

import pytest

from solarprio.runtime.config import load_config

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted([*ROOT.glob("config*.example.toml"), *(ROOT / "examples").glob("*.toml")])


def test_the_example_files_are_found():
    names = {p.name for p in FILES}
    assert {"config.example.toml", "config.victron.example.toml", "_template.toml"} <= names


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_example_configuration_is_valid(path):
    cfg = load_config(path)
    assert cfg.devices
