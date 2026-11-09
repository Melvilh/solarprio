"""Every language is complete (and no text is left over), and the check tells a newcomer what a new language still lacks."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_translations as ct  # noqa: E402


@pytest.mark.parametrize("lang", ct.languages())
def test_the_language_is_complete(lang):
    assert ct.problems(lang) == []


def test_english_and_french_are_both_shipped():
    assert {"en", "fr"} <= set(ct.languages())


def test_a_new_language_is_told_what_it_lacks_and_works_meanwhile():
    issues = ct.problems("xx")  # a language nobody wrote yet
    assert any("translations/xx.json lacks" in i for i in issues)
    assert len([i for i in issues if i.startswith("translations/xx.json lacks")]) == len(ct.json_paths("en"))
