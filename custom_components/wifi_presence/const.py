"""Constants for WiFi Presence."""

DOMAIN = "wifi_presence"

CONF_SUBNET = "subnet"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_CONSIDER_HOME = "consider_home"
CONF_TRACKED = "tracked"
CONF_MANUAL_MACS = "manual_macs"

DEFAULT_SUBNET = "192.168.86.0/24"  # Google WiFi default
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_CONSIDER_HOME = 180
