"""Constants for the solarprio integration."""

DOMAIN = "solarprio"

CONF_MODE = "mode"
CONF_EXPORT_ENTITY = "export_entity"
CONF_PRODUCTION_ENTITY = "production_entity"
CONF_CONSUMPTION_ENTITY = "consumption_entity"
CONF_INVERT = "invert"
CONF_INTERVAL = "interval_s"
CONF_STALE_AFTER = "stale_after_s"
CONF_ON_STALE = "on_stale"

MODE_EXPORT = "export"
MODE_PRODUCTION = "production"

ON_STALE_OFF = "off"
ON_STALE_HOLD = "hold"

CONF_DEVICES = "devices"

DEFAULT_INTERVAL = 5
DEFAULT_STALE_AFTER = 60

PANEL_URL_PATH = "solarprio"
PANEL_STATIC_URL = "/solarprio_static/panel.js"

# Unchanged commands are sent again this often (heartbeat for devices with a watchdog, and for devices that missed one).
RESEND_EVERY_S = 30.0
