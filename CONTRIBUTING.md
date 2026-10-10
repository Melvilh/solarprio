# Contributing

Thanks for helping. This project switches electrical loads, so changes to the allocation engine and the
safety behaviour (measurement loss, limits, shutdown) get extra scrutiny.

## Ground rules

- By contributing you agree your work is licensed under the Apache License 2.0 (the project license).
- `src/solarprio` is the single source of truth for the engine. After editing it run
  `python scripts/sync_core.py`; a test fails if the copy in `custom_components/` drifts.
- Add a test for every behaviour change. For safety rules, check that the test fails when the rule is broken.
- Keep the engine free of Home Assistant imports.
- Do not claim hardware support you have not tested; say what was tested and how.

## Setup

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                         # engine + standalone runtime

python -m venv .venv-ha
.venv-ha/bin/pip install -r tests_ha/requirements.txt
scripts/test_ha.sh                       # Home Assistant integration tests
```

The end-to-end test (real Home Assistant + Chromium) additionally needs `playwright` and
`tests_e2e/ha-requirements.txt` in `.venv-ha`, then `scripts/e2e_ha.sh`.

## Validate like CI

- `hassfest`: run it from a Home Assistant core checkout of the tested version:
  `python -m script.hassfest --action validate --integration-path <repo>/custom_components/solarprio`
- Release gate: `python scripts/release_check.py`

## Pull requests

Explain what changed and why, what you tested and how, and anything you could not test.
