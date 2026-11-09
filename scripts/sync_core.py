"""Copy the core engine into the Home Assistant integration (vendoring).

HACS installs only ``custom_components/<domain>``, so the integration carries its own copy of
the core. ``src/solarprio`` stays the single source of truth; a test checks both are identical.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "solarprio"
DST = ROOT / "custom_components" / "solarprio" / "core"
FILES = ["__init__.py", "engine.py", "models.py", "ports.py", "sources.py"]


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        (DST / name).write_text((SRC / name).read_text())
    (DST / "profiles" / "data").mkdir(parents=True, exist_ok=True)
    for path in [SRC / "profiles" / "__init__.py", *sorted((SRC / "profiles" / "data").glob("*.json"))]:
        (DST / path.relative_to(SRC)).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"synced {len(FILES)} files to {DST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
