"""The GitHub issue forms people are sent to (from the panel and the README): they must be valid forms, or GitHub shows nothing."""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
FORMS = sorted((Path(__file__).resolve().parents[1] / ".github" / "ISSUE_TEMPLATE").glob("*.yml"))
KNOWN = {"markdown", "textarea", "input", "dropdown", "checkboxes"}


def test_the_three_forms_exist_and_no_old_markdown_template_is_left():
    names = {p.name for p in FORMS}
    assert {"bug_report.yml", "feature_request.yml", "compatibility.yml", "config.yml"} <= names
    assert not list(FORMS[0].parent.glob("*.md"))  # two templates for one thing would confuse the chooser


@pytest.mark.parametrize("path", [p for p in FORMS if p.name != "config.yml"], ids=lambda p: p.name)
def test_a_form_is_valid_for_github(path):
    form = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert form["name"] and form["description"] and form["body"]
    ids = []
    for block in form["body"]:
        assert block["type"] in KNOWN, block
        if block["type"] != "markdown":
            assert block["attributes"]["label"], block
            ids.append(block["id"])
        if block["type"] == "dropdown":
            assert len(block["attributes"]["options"]) >= 2
    assert len(ids) == len(set(ids)), "form field ids must be unique"
    assert any(b.get("validations", {}).get("required") for b in form["body"]), "something must be required"


def test_the_chooser_does_not_allow_blank_issues_and_points_to_the_docs():
    config = yaml.safe_load((FORMS[0].parent / "config.yml").read_text(encoding="utf-8"))
    assert config["blank_issues_enabled"] is False
    assert all(link["url"].startswith("https://github.com/Melvilh/solarprio/") for link in config["contact_links"])
