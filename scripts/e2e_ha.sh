#!/bin/sh
# End-to-end test: real Home Assistant + real Chromium (Playwright) driving the solarprio panel.
# Needs .venv-ha with: pytest-homeassistant-custom-component, playwright, and the HA component
# requirements (see README). Chromium is expected at $CHROMIUM (default /opt/pw-browsers/chromium).
# Screenshots are written to $E2E_OUT (default: a temp dir, printed at the end).
set -eu
HA_PID=
cleanup() { [ -n "$HA_PID" ] && kill "$HA_PID" 2>/dev/null || true; }  # never leave a Home Assistant running when a scenario fails
trap cleanup EXIT
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
PY="$ROOT/.venv-ha/bin/python"
cd "${E2E_OUT:-$WORK}"
for SCENARIO in ${E2E_SCENARIOS:-basic ev edit}; do
  CONFIG="$WORK/config-$SCENARIO"
  mkdir -p "$CONFIG/custom_components"
  ln -s "$ROOT/custom_components/solarprio" "$CONFIG/custom_components/solarprio"
  cp "$ROOT/tests_e2e/configuration.yaml" "$CONFIG/"
  "$ROOT/.venv-ha/bin/hass" -c "$CONFIG" > "$WORK/ha-$SCENARIO.log" 2>&1 &
  HA_PID=$!
  for _ in $(seq 1 90); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8123/ || true)" = "200" ] && break
    sleep 1
  done
  case "$SCENARIO" in
    basic) SETUP=basic; TEST=browser_test.py ;;
    ev) SETUP=ev; TEST=browser_test_ev.py ;;
    edit) SETUP=basic; TEST=browser_test_edit.py ;;
  esac
  "$PY" "$ROOT/tests_e2e/setup_ha.py" "$SETUP" > auth.json
  echo "=== scenario: $SCENARIO ==="
  "$PY" "$ROOT/tests_e2e/$TEST"
  kill $HA_PID 2>/dev/null || true
  wait $HA_PID 2>/dev/null || true
done
echo "screenshots and HA logs in: $(pwd) / $WORK"
