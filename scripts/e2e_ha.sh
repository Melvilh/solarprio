#!/bin/sh
# End-to-end test: real Home Assistant + real Chromium (Playwright) driving the solarprio panel.
# Needs .venv-ha with: pytest-homeassistant-custom-component, playwright, and the HA component
# requirements (see README). Chromium is expected at $CHROMIUM (default /opt/pw-browsers/chromium).
# Screenshots are written to $E2E_OUT (default: a temp dir, printed at the end).
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
PY="$ROOT/.venv-ha/bin/python"
cd "${E2E_OUT:-$WORK}"
for SCENARIO in basic ev; do
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
  "$PY" "$ROOT/tests_e2e/setup_ha.py" "$SCENARIO" > auth.json
  if [ "$SCENARIO" = basic ]; then TEST=browser_test.py; else TEST=browser_test_ev.py; fi
  echo "=== scenario: $SCENARIO ==="
  "$PY" "$ROOT/tests_e2e/$TEST"
  kill $HA_PID 2>/dev/null || true
  wait $HA_PID 2>/dev/null || true
done
echo "screenshots and HA logs in: $(pwd) / $WORK"
