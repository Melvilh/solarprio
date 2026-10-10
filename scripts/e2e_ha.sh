#!/bin/sh
# End-to-end test: real Home Assistant + real Chromium (Playwright) driving the solarprio panel.
# Needs .venv-ha with: pytest-homeassistant-custom-component, playwright, and the HA component
# requirements (see README). Chromium is expected at $CHROMIUM (default /opt/pw-browsers/chromium).
# Screenshots are written to $E2E_OUT (default: a temp dir, printed at the end).
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
PY="$ROOT/.venv-ha/bin/python"
mkdir -p "$WORK/config/custom_components"
ln -s "$ROOT/custom_components/solarprio" "$WORK/config/custom_components/solarprio"
cp "$ROOT/tests_e2e/configuration.yaml" "$WORK/config/"
"$ROOT/.venv-ha/bin/hass" -c "$WORK/config" > "$WORK/ha.log" 2>&1 &
HA_PID=$!
trap 'kill $HA_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 90); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8123/ || true)" = "200" ] && break
  sleep 1
done
cd "${E2E_OUT:-$WORK}"
"$PY" "$ROOT/tests_e2e/setup_ha.py" > auth.json
"$PY" "$ROOT/tests_e2e/browser_test.py"
echo "screenshots and HA log in: $(pwd) / $WORK/ha.log"
