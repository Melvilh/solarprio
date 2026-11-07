#!/bin/sh
# Example (adapt it): run COMMAND once a day when solarprio says "go".
#
# solarprio switches a Home Assistant helper (an input_boolean) on when there is solar surplus or off-peak power. This script,
# run from cron every few minutes on the machine that does the work, reads that helper and starts COMMAND.
#   - COMMAND is run at most once per day and only counts as done when it exits successfully (otherwise it is retried).
#   - If no "go" came, FALLBACK_AFTER (HH:MM, optional) runs it anyway from that time, so the daily task is never skipped.
#   - If Home Assistant cannot be reached, nothing runs until the fallback time.
# It never switches anything off and never stops a running command: write COMMAND so that it can be interrupted safely.
#
# Environment: HA_URL (for example http://homeassistant.local:8123), HA_TOKEN (a long-lived access token: keep it in a
# file readable by root only, never in a repository), GO_ENTITY (input_boolean.xxx), COMMAND, and optionally STATE_DIR,
# FALLBACK_AFTER.
set -eu
: "${HA_URL:?set HA_URL}" "${HA_TOKEN:?set HA_TOKEN}" "${GO_ENTITY:?set GO_ENTITY}" "${COMMAND:?set COMMAND}"
STATE_DIR=${STATE_DIR:-/var/tmp/solarprio-tasks}
FALLBACK_AFTER=${FALLBACK_AFTER:-}
mkdir -p "$STATE_DIR"
FLAG="$STATE_DIR/$(printf '%s' "$GO_ENTITY" | tr -c 'A-Za-z0-9' '_').$(date +%F)"
[ -e "$FLAG" ] && exit 0 # already done today

STATE=$(curl -fsS -m 10 -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/states/$GO_ENTITY" 2>/dev/null |
  sed -n 's/.*"state": *"\([^"]*\)".*/\1/p' || true)
RUN=no
[ "$STATE" = "on" ] && RUN=yes
if [ "$RUN" = no ] && [ -n "$FALLBACK_AFTER" ]; then
  NOW=$(date +%H%M)
  LIMIT=$(printf '%s' "$FALLBACK_AFTER" | tr -d ':')
  [ "$NOW" -ge "$LIMIT" ] && RUN=yes
fi
[ "$RUN" = yes ] || exit 0
sh -c "$COMMAND" && touch "$FLAG"
