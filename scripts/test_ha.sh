#!/bin/sh
# Run the Home Assistant integration tests (needs .venv-ha with pytest-homeassistant-custom-component).
cd "$(dirname "$0")/.." && exec .venv-ha/bin/python -m pytest tests_ha -p no:sugar \
  -o asyncio_mode=auto -o pythonpath=". src" -o testpaths=tests_ha "$@"
