#!/usr/bin/env python3
"""Pre-release gate: fails while provisional values remain. Run before tagging a release.

Checks things a unit test cannot decide for you: that the project identity has been chosen,
that URLs are real, that the changelog mentions the version being released.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
problems: list[str] = []

integration = next(d for d in (ROOT / "custom_components").iterdir() if d.is_dir() and not d.name.startswith("__"))
manifest = json.loads((integration / "manifest.json").read_text())

for key in ("documentation", "issue_tracker"):
    if "example.invalid" in manifest[key] or "OWNER/REPO" in manifest[key]:
        problems.append(f"manifest.json {key} is still a placeholder: {manifest[key]}")
if not manifest["codeowners"]:
    problems.append("manifest.json codeowners is empty (use e.g. [\"@your-github-name\"])")

tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
for name in tracked:
    path = ROOT / name
    if path.suffix in {".png", ".svg", ".gif"} or not path.is_file() or name in {"scripts/release_check.py", "scripts/set_identity.py"}:
        continue
    text = path.read_text(errors="ignore")
    for marker in ("example.invalid", "OWNER/REPO", "provisional name"):
        if marker in text:
            problems.append(f"{name}: contains '{marker}'")

changelog = (ROOT / "CHANGELOG.md").read_text()
if f"## [{manifest['version']}]" not in changelog:
    problems.append(f"CHANGELOG.md has no section for version {manifest['version']}")

status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
if status.strip():
    problems.append("working tree is not clean")

if problems:
    print("NOT READY TO RELEASE:")
    for p in problems:
        print(" -", p)
    sys.exit(1)
print(f"ready to release {manifest['version']}")
