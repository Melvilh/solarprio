#!/usr/bin/env python3
"""Replace the provisional project identity (name, repository, owner) in one go.

    python scripts/set_identity.py --name helio_router --display "Helio Router" \\
        --repo acme/helio-router --owner acme

``--name`` is the technical name: the Home Assistant domain, the Python package, the CLI command and the
folder names (lowercase letters, digits and underscores, starting with a letter). ``--display`` is the name
shown to people. Run it once on a clean working tree, then review ``git diff`` and run the tests.

Before choosing a name, check it is free: that no Home Assistant core integration uses the domain
(homeassistant/components/<name>), that the GitHub repository, PyPI project and container image names are free,
and that it does not infringe a trademark (in France: INPI). This script cannot check any of that.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD = "solarprio"
OLD_CAMEL = "SolarPrio"
TEXT_SUFFIXES = {".py", ".md", ".json", ".toml", ".yml", ".yaml", ".js", ".sh", ".cfg", ".txt", ".conf", ".svg"}
SKIP_FILES = {"LICENSE"}
SKIP_PATHS = {"scripts/set_identity.py", "scripts/release_check.py"}  # they contain the markers on purpose
EXTRA_TEXT_NAMES = {"Dockerfile", ".dockerignore", ".gitignore"}  # tracked text files without a suffix
PROSE_FILES = {"strings.json", "en.json", "fr.json"}


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    return [ROOT / n for n in out if n]


def camel(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def split_markdown(text: str):
    """Yield (segment, is_code) for fenced blocks and inline code spans versus prose."""
    pattern = re.compile(r"(```.*?```|`[^`\n]*`)", re.S)
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            yield text[pos:m.start()], False
        yield m.group(0), True
        pos = m.end()
    if pos < len(text):
        yield text[pos:], False


def rewrite(path: Path, text: str, a: argparse.Namespace) -> str:
    name, display = a.name, a.display
    hyphen = name.replace("_", "-")
    repo_url = f"https://github.com/{a.repo}"

    text = text.replace(f"{OLD}-panel", f"{hyphen}-panel")  # custom element names need a hyphen
    text = text.replace(f"https://example.invalid/{OLD}/issues", f"{repo_url}/issues")
    text = text.replace(f"https://example.invalid/{OLD}", repo_url)
    text = text.replace("OWNER/REPO", a.repo)
    text = text.replace(" (provisional name)", "")
    text = text.replace(OLD_CAMEL, camel(name))

    if path.name == "manifest.json":
        data = json.loads(text.replace(OLD, name))
        data["name"] = display
        data["codeowners"] = [f"@{a.owner}"]
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if path.name == "hacs.json":
        data = json.loads(text)
        data["name"] = display
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    if path.suffix == ".md":
        parts = [seg.replace(OLD, name) if code else seg.replace(OLD, display) for seg, code in split_markdown(text)]
        return "".join(parts)
    if path.name in PROSE_FILES:
        return text.replace(OLD, display)

    # code: display name only where a person reads it
    text = re.sub(rf'(name=|sidebar_title=|title=)"{OLD}"', lambda m: f'{m.group(1)}"{display}"', text)
    if path.name == "panel.js":
        lines = [
            line.replace(OLD, display) if re.match(r"\s+(notConfigured|empty):", line) else line.replace(OLD, name)
            for line in text.split("\n")
        ]
        return "\n".join(lines)
    return text.replace(OLD, name)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="technical name / Home Assistant domain, e.g. helio_router")
    p.add_argument("--display", required=True, help='name shown to people, e.g. "Helio Router"')
    p.add_argument("--repo", required=True, help="GitHub repository, OWNER/REPO")
    p.add_argument("--owner", required=True, help="GitHub user or organisation for manifest codeowners")
    p.add_argument("--force", action="store_true", help="run even if the working tree is not clean")
    a = p.parse_args()

    if not re.fullmatch(r"[a-z][a-z0-9_]*", a.name):
        sys.exit("--name must be lowercase letters, digits and underscores, starting with a letter")
    if a.name == OLD:
        sys.exit("that is already the current name")
    slug = re.sub(r"[^a-z0-9]+", "_", a.display.lower()).strip("_")
    if slug != a.name:
        sys.exit(
            f"the display name must turn into the technical name when lowercased with non-alphanumerics as underscores "
            f"(\"{a.display}\" -> \"{slug}\", expected \"{a.name}\"): Home Assistant derives entity ids from it"
        )
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", a.repo):
        sys.exit("--repo must look like OWNER/REPO")
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty and not a.force:
        sys.exit("working tree is not clean; commit first (or use --force)")

    changed = 0
    for path in tracked_files():
        if path.name in SKIP_FILES or path.relative_to(ROOT).as_posix() in SKIP_PATHS or (path.suffix not in TEXT_SUFFIXES and path.name not in EXTRA_TEXT_NAMES):
            continue
        text = path.read_text()
        new = rewrite(path, text, a)
        if new != text:
            path.write_text(new)
            changed += 1

    # rename the folders last (git mv keeps history)
    for old, new in ((ROOT / "src" / OLD, ROOT / "src" / a.name), (ROOT / "custom_components" / OLD, ROOT / "custom_components" / a.name)):
        if old.exists():
            subprocess.run(["git", "mv", str(old), str(new)], cwd=ROOT, check=True)

    subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_core.py")], cwd=ROOT, check=True)
    print(f"rewrote {changed} files; domain '{a.name}', display '{a.display}', repo {a.repo}")
    print("Next: review `git diff`, run the tests (pytest, scripts/test_ha.sh), then scripts/release_check.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
