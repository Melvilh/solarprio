"""Static checks of the ESPHome examples. The C++ itself is only compiled by ESPHome on the user's machine (never here), so
these catch the mistakes that are cheap to catch: a YAML-style ``#`` comment written inside a C++ lambda broke the first
published actuator file at compile time."""
import re
from pathlib import Path

import pytest

FILES = sorted((Path(__file__).resolve().parents[1] / "examples" / "esphome").glob("*.yaml"))


def block_lambdas(lines):
    """Yield (line number, text) of the lines inside every multi-line ``lambda: |-`` block."""
    i = 0
    while i < len(lines):
        if re.match(r"^\s*(- )?lambda:\s*\|[-+]?\s*$", lines[i]):
            base = len(lines[i]) - len(lines[i].lstrip())
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > base):
                yield j + 1, lines[j]
                j += 1
            i = j
        else:
            i += 1


def test_the_examples_exist():
    assert FILES


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_yaml_comment_inside_a_cpp_lambda(path):
    for number, text in block_lambdas(path.read_text().split("\n")):
        code = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)  # a # inside a string is fine
        assert "#" not in code, f"{path.name}:{number}: '#' is not a C++ comment, use //  ->  {text.strip()}"


def test_the_checker_catches_the_original_mistake():
    bad = ["      - lambda: |-", "          id(x) = 0;         # the last order is no longer valid"]
    assert any("#" in t for _, t in block_lambdas(bad))
