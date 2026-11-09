"""List what a language still lacks, or check that the languages agree.

    python scripts/check_translations.py          # check every language that exists; exit 1 if one is incomplete
    python scripts/check_translations.py es       # what is missing in Spanish (or a new language you are starting)

Two places hold the texts: ``custom_components/solarprio/translations/<lang>.json`` (Home Assistant's forms, entity names,
setup) and the object ``T`` of ``custom_components/solarprio/frontend/panel.js`` (the sidebar panel). English is the reference;
a language that lacks a text falls back to English, so a partial translation works while it is being written.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "solarprio"


def flatten(node, prefix=""):
    """The paths of all the texts of a nested dictionary."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from flatten(value, f"{prefix}.{key}" if prefix else str(key))
    else:
        yield prefix


def json_paths(lang: str) -> set[str]:
    path = COMPONENT / "translations" / f"{lang}.json"
    return set(flatten(json.loads(path.read_text(encoding="utf-8")))) if path.exists() else set()


def panel_dictionaries() -> dict[str, dict]:
    """The object T of panel.js (one entry per language), read by Node. Empty when Node is not installed."""
    node = shutil.which("node")
    if node is None:
        return {}
    source = (COMPONENT / "frontend" / "panel.js").read_text(encoding="utf-8")
    start = source.index("const T = {")
    depth, i, quote = 0, source.index("{", start), None
    begin = i
    while i < len(source):
        ch = source[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    code = f"const T = {source[begin:i + 1]}; console.log(JSON.stringify(T));"
    out = subprocess.run([node, "-e", code], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def languages() -> list[str]:
    return sorted(p.stem for p in (COMPONENT / "translations").glob("*.json"))


def problems(lang: str) -> list[str]:
    """What is wrong or missing for a language, compared with English."""
    found = []
    reference = json_paths("en")
    mine = json_paths(lang)
    found += [f"translations/{lang}.json lacks {p}" for p in sorted(reference - mine)]
    found += [f"translations/{lang}.json has an unknown text {p}" for p in sorted(mine - reference)]
    panel = panel_dictionaries()
    if panel:
        en = set(flatten(panel["en"]))
        if lang in panel:
            have = set(flatten(panel[lang]))
            found += [f"panel.js T.{lang} lacks {p}" for p in sorted(en - have)]
            found += [f"panel.js T.{lang} has an unknown text {p}" for p in sorted(have - en)]
        else:
            found.append(f"panel.js has no T.{lang} yet (the panel falls back to English)")
    return found


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        issues = problems(argv[1])
        print("\n".join(issues) if issues else f"{argv[1]}: complete")
        return 1 if issues else 0
    bad = 0
    for lang in languages():
        issues = problems(lang)
        bad += bool(issues)
        print(f"{lang}: " + ("complete" if not issues else f"{len(issues)} problem(s)"))
        for issue in issues:
            print("   ", issue)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
